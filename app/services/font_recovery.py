"""Bounded deterministic recovery for audited identity-mapped PDF fonts.

This module is deliberately separate from :mod:`font_audit`.  Detection never
decodes an embedded font program.  Recovery runs only for suspicious fonts
selected by that audit, decodes one bounded ``FontFile2`` stream per selected
indirect font, and reads only the TrueType metrics and Unicode cmap tables.
Font programs are never executed, returned, logged, or persisted.
"""

from __future__ import annotations

import hashlib
import io
import math
import time
import unicodedata
import zlib
from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfinterp import PDFPageInterpreter
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser
from pdfminer.pdftypes import PDFStream, resolve1
from pydantic import BaseModel, ConfigDict, Field

from app.services.font_audit import (
    FONT_AUDIT_SCHEMA_VERSION,
    MAX_CMAP_MAPPINGS,
    MAX_DIAGNOSTICS,
    MAX_FONT_OBJECTS,
    MAX_INPUT_BYTES,
    MAX_PAGES,
    MAX_RECORDED_CHARACTERS,
    FontAuditBBox,
    FontAuditReport,
    _AuditDevice,
    _BoundedResourceManager,
    _Character,
    _Run,
    _font_dictionary_with_descriptor,
    _resolved_cid_to_gid_state,
    _safe_name,
    _union_bbox,
)


FONT_RECOVERY_SCHEMA_VERSION = "1.0"
MAX_RAW_FONT_PROGRAM_BYTES = 4 * 1024 * 1024
MAX_DECODED_FONT_PROGRAM_BYTES = 8 * 1024 * 1024
MAX_SFNT_TABLES = 128
MAX_CMAP_SUBTABLES = 64
MAX_RECOVERY_RUNS = 2_000
MAX_RECOVERED_GLYPHS = 50_000
MAX_RECOVERY_SECONDS = 5.0
WIDTH_TOLERANCE_EM = 0.002


class _RecoveryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class FontRecoveryGlyph(_RecoveryModel):
    evidence_id: str
    page_index: int = Field(ge=1)
    run_index: int = Field(ge=1)
    glyph_index: int = Field(ge=0)
    font_ref: str
    font_object_id: int = Field(ge=1)
    cid: int = Field(ge=0)
    glyph_id: int = Field(ge=0)
    original_text: str
    recovered_text: str = Field(min_length=1, max_length=1)
    unicode_code_point: int = Field(ge=0, le=0x10FFFF)
    bbox: FontAuditBBox
    page_advance: float
    pdf_width_em: float
    embedded_advance_width: int = Field(ge=0)
    units_per_em: int = Field(ge=16, le=16_384)
    width_delta_em: float = Field(ge=0)
    method: Literal["embedded_truetype_cmap_identity"] = (
        "embedded_truetype_cmap_identity"
    )


class FontRecoveryRun(_RecoveryModel):
    evidence_id: str
    page_index: int = Field(ge=1)
    run_index: int = Field(ge=1)
    font_ref: str
    font_object_id: int = Field(ge=1)
    bbox: FontAuditBBox
    original_text: str
    recovered_text: str
    glyphs: list[FontRecoveryGlyph]
    confidence_basis: dict[str, Any]
    method: Literal["embedded_truetype_cmap_identity"] = (
        "embedded_truetype_cmap_identity"
    )


class FontRecoveryRefusal(_RecoveryModel):
    font_ref: str
    font_object_id: int | None = Field(default=None, ge=1)
    page_indexes: list[int]
    reason_code: str
    message: str


class FontRecoveryDiagnostic(_RecoveryModel):
    code: str
    message: str
    page_index: int | None = Field(default=None, ge=1)
    font_ref: str | None = None
    font_object_id: int | None = Field(default=None, ge=1)


class FontRecoveryReport(_RecoveryModel):
    schema_version: Literal["1.0"] = FONT_RECOVERY_SCHEMA_VERSION
    audit_schema_version: Literal["1.0"] = FONT_AUDIT_SCHEMA_VERSION
    source_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    status: Literal["complete", "partial", "unavailable"]
    fonts_considered: int = Field(ge=0)
    fonts_recovered: int = Field(ge=0)
    font_programs_parsed: int = Field(ge=0)
    pages_inspected: int = Field(ge=0)
    characters_inspected: int = Field(ge=0)
    recovered_glyph_count: int = Field(ge=0)
    runs: list[FontRecoveryRun]
    refusals: list[FontRecoveryRefusal]
    diagnostics: list[FontRecoveryDiagnostic]


@dataclass(frozen=True, slots=True)
class _ParsedTrueType:
    units_per_em: int
    num_glyphs: int
    advances: Mapping[int, int]
    codepoints_by_gid: Mapping[int, frozenset[int]]


class _RecoveryError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _RecoveryGlyphLimitReached(Exception):
    pass


class _RecoveryRunLimitReached(Exception):
    pass


def _need(
    data: bytes,
    offset: int,
    length: int,
    *,
    code: str = "embedded_font_malformed",
) -> None:
    if offset < 0 or length < 0 or offset + length > len(data):
        raise _RecoveryError(code, "Embedded TrueType table is truncated.")


def _u16(data: bytes, offset: int) -> int:
    _need(data, offset, 2)
    return int.from_bytes(data[offset : offset + 2], "big")


def _s16(data: bytes, offset: int) -> int:
    _need(data, offset, 2)
    return int.from_bytes(data[offset : offset + 2], "big", signed=True)


def _u32(data: bytes, offset: int) -> int:
    _need(data, offset, 4)
    return int.from_bytes(data[offset : offset + 4], "big")


def _bounded_font_program(stream: PDFStream) -> bytes:
    raw_value = stream.get_rawdata()
    if raw_value is None:
        decoded = stream.data
        if not isinstance(decoded, bytes):
            raise _RecoveryError(
                "embedded_program_unavailable",
                "Embedded FontFile2 bytes are unavailable.",
            )
        if len(decoded) > MAX_DECODED_FONT_PROGRAM_BYTES:
            raise _RecoveryError(
                "embedded_program_limit",
                "Decoded FontFile2 exceeds the recovery bound.",
            )
        return decoded

    raw = raw_value
    if len(raw) > MAX_RAW_FONT_PROGRAM_BYTES:
        raise _RecoveryError(
            "embedded_program_limit",
            "Compressed FontFile2 exceeds the recovery bound.",
        )
    filters = stream.get_filters()
    if not filters:
        decoded = raw
    elif (
        len(filters) == 1
        and _safe_name(filters[0][0]) in {"FlateDecode", "Fl"}
    ):
        decoder = zlib.decompressobj()
        try:
            decoded = decoder.decompress(
                raw,
                MAX_DECODED_FONT_PROGRAM_BYTES + 1,
            )
        except zlib.error as exc:
            raise _RecoveryError(
                "embedded_program_malformed",
                "Embedded FontFile2 has invalid Flate data.",
            ) from exc
        if (
            len(decoded) > MAX_DECODED_FONT_PROGRAM_BYTES
            or decoder.unconsumed_tail
            or not decoder.eof
        ):
            raise _RecoveryError(
                "embedded_program_limit",
                "Decoded FontFile2 exceeds the recovery bound.",
            )
    else:
        raise _RecoveryError(
            "embedded_program_filter_unsupported",
            "Embedded FontFile2 uses an unsupported filter chain.",
        )
    if len(decoded) > MAX_DECODED_FONT_PROGRAM_BYTES:
        raise _RecoveryError(
            "embedded_program_limit",
            "Decoded FontFile2 exceeds the recovery bound.",
        )
    return decoded


def _sfnt_tables(data: bytes) -> dict[str, tuple[int, int]]:
    _need(data, 0, 12)
    if data[:4] not in {b"\x00\x01\x00\x00", b"true"}:
        raise _RecoveryError(
            "embedded_font_unsupported",
            "Only TrueType sfnt FontFile2 programs are supported.",
        )
    table_count = _u16(data, 4)
    if not 1 <= table_count <= MAX_SFNT_TABLES:
        raise _RecoveryError(
            "embedded_font_table_limit",
            "TrueType table count exceeds the recovery bound.",
        )
    _need(data, 12, table_count * 16)
    tables: dict[str, tuple[int, int]] = {}
    for index in range(table_count):
        position = 12 + index * 16
        tag_bytes = data[position : position + 4]
        try:
            tag = tag_bytes.decode("ascii")
        except UnicodeDecodeError as exc:
            raise _RecoveryError(
                "embedded_font_malformed",
                "TrueType table tag is not ASCII.",
            ) from exc
        if tag in tables:
            raise _RecoveryError(
                "embedded_font_malformed",
                "TrueType table directory contains a duplicate tag.",
            )
        offset = _u32(data, position + 8)
        length = _u32(data, position + 12)
        _need(data, offset, length)
        tables[tag] = (offset, length)
    return tables


def _table(
    data: bytes,
    tables: Mapping[str, tuple[int, int]],
    tag: str,
) -> bytes:
    record = tables.get(tag)
    if record is None:
        raise _RecoveryError(
            "embedded_font_required_table_missing",
            f"Embedded TrueType program has no {tag} table.",
        )
    offset, length = record
    return data[offset : offset + length]


def _parse_cmap_format_4(
    subtable: bytes,
    *,
    num_glyphs: int,
    mapping_limit: int | None = None,
    mapping_budget: list[int] | None = None,
    used_glyph_ids: frozenset[int] = frozenset(),
    selected_code_points: frozenset[int] = frozenset(),
    charge_mapping_budget: bool = True,
    deadline: float | None = None,
) -> dict[int, int]:
    _need(subtable, 0, 16)
    length = _u16(subtable, 2)
    if length > len(subtable) or length < 16:
        raise _RecoveryError(
            "embedded_cmap_malformed",
            "TrueType format-4 cmap length is invalid.",
        )
    table = subtable[:length]
    segment_count_x2 = _u16(table, 6)
    if segment_count_x2 == 0 or segment_count_x2 % 2:
        raise _RecoveryError(
            "embedded_cmap_malformed",
            "TrueType format-4 segment count is invalid.",
        )
    segment_count = segment_count_x2 // 2
    if segment_count > 8_192:
        raise _RecoveryError(
            "embedded_cmap_limit",
            "TrueType format-4 segment count exceeds the recovery bound.",
        )
    end_offset = 14
    start_offset = end_offset + segment_count * 2 + 2
    delta_offset = start_offset + segment_count * 2
    range_offset = delta_offset + segment_count * 2
    _need(table, range_offset, segment_count * 2, code="embedded_cmap_malformed")

    output: dict[int, int] = {}
    retained_by_gid: dict[int, int] = {}
    mapping_count = 0
    effective_mapping_limit = (
        MAX_CMAP_MAPPINGS
        if mapping_limit is None
        else mapping_limit
    )
    previous_end = -1
    for index in range(segment_count):
        if deadline is not None and time.perf_counter() > deadline:
            raise _RecoveryError(
                "recovery_timeout",
                "Font recovery exceeded its time bound.",
            )
        end_code = _u16(table, end_offset + index * 2)
        start_code = _u16(table, start_offset + index * 2)
        delta = _s16(table, delta_offset + index * 2)
        glyph_range_offset = _u16(table, range_offset + index * 2)
        if start_code > end_code or start_code <= previous_end:
            raise _RecoveryError(
                "embedded_cmap_malformed",
                "TrueType format-4 segments overlap or are unordered.",
            )
        previous_end = end_code
        if start_code == 0xFFFF and end_code == 0xFFFF:
            continue
        entry_count = end_code - start_code + 1
        mapping_count += entry_count
        if mapping_budget is not None and charge_mapping_budget:
            mapping_budget[0] -= entry_count
        if (
            mapping_count > effective_mapping_limit
            or (
                mapping_budget is not None
                and mapping_budget[0] < 0
            )
        ):
            raise _RecoveryError(
                "embedded_cmap_limit",
                "TrueType cmap mapping count exceeds the recovery bound.",
            )
        for entry_index, code_point in enumerate(
            range(start_code, end_code + 1)
        ):
            if (
                deadline is not None
                and entry_index % 1024 == 0
                and time.perf_counter() > deadline
            ):
                raise _RecoveryError(
                    "recovery_timeout",
                    "Font recovery exceeded its time bound.",
                )
            if glyph_range_offset == 0:
                glyph_id = (code_point + delta) & 0xFFFF
            else:
                glyph_position = (
                    range_offset
                    + index * 2
                    + glyph_range_offset
                    + (code_point - start_code) * 2
                )
                _need(
                    table,
                    glyph_position,
                    2,
                    code="embedded_cmap_malformed",
                )
                glyph_id = _u16(table, glyph_position)
                if glyph_id:
                    glyph_id = (glyph_id + delta) & 0xFFFF
            if glyph_id:
                if glyph_id >= num_glyphs:
                    raise _RecoveryError(
                        "embedded_cmap_malformed",
                        "TrueType cmap references a glyph outside maxp.",
                    )
                if code_point in selected_code_points:
                    output[code_point] = glyph_id
                elif glyph_id in used_glyph_ids:
                    retained = retained_by_gid.get(glyph_id, 0)
                    if retained < 2:
                        output[code_point] = glyph_id
                        retained_by_gid[glyph_id] = retained + 1
    return output


def _parse_cmap_format_12(
    subtable: bytes,
    *,
    num_glyphs: int,
    mapping_limit: int | None = None,
    mapping_budget: list[int] | None = None,
    used_glyph_ids: frozenset[int] = frozenset(),
    selected_code_points: frozenset[int] = frozenset(),
    charge_mapping_budget: bool = True,
    deadline: float | None = None,
) -> dict[int, int]:
    _need(subtable, 0, 16)
    length = _u32(subtable, 4)
    if length > len(subtable) or length < 16:
        raise _RecoveryError(
            "embedded_cmap_malformed",
            "TrueType format-12 cmap length is invalid.",
        )
    table = subtable[:length]
    group_count = _u32(table, 12)
    if group_count > MAX_CMAP_MAPPINGS:
        raise _RecoveryError(
            "embedded_cmap_limit",
            "TrueType format-12 group count exceeds the recovery bound.",
        )
    _need(table, 16, group_count * 12, code="embedded_cmap_malformed")
    output: dict[int, int] = {}
    retained_by_gid: dict[int, int] = {}
    sorted_used_glyph_ids = tuple(sorted(used_glyph_ids))
    sorted_selected_code_points = tuple(sorted(selected_code_points))
    mapping_count = 0
    effective_mapping_limit = (
        MAX_CMAP_MAPPINGS
        if mapping_limit is None
        else mapping_limit
    )
    previous_end = -1
    for index in range(group_count):
        if deadline is not None and time.perf_counter() > deadline:
            raise _RecoveryError(
                "recovery_timeout",
                "Font recovery exceeded its time bound.",
            )
        position = 16 + index * 12
        start = _u32(table, position)
        end = _u32(table, position + 4)
        start_glyph = _u32(table, position + 8)
        if start > end or start <= previous_end or end > 0x10FFFF:
            raise _RecoveryError(
                "embedded_cmap_malformed",
                "TrueType format-12 groups overlap or are invalid.",
            )
        previous_end = end
        count = end - start + 1
        mapping_count += count
        if mapping_budget is not None and charge_mapping_budget:
            mapping_budget[0] -= count
        if (
            mapping_count > effective_mapping_limit
            or (
                mapping_budget is not None
                and mapping_budget[0] < 0
            )
        ):
            raise _RecoveryError(
                "embedded_cmap_limit",
                "TrueType cmap mapping count exceeds the recovery bound.",
            )
        if start_glyph + count > num_glyphs:
            raise _RecoveryError(
                "embedded_cmap_malformed",
                "TrueType cmap references a glyph outside maxp.",
            )
        lower = bisect_left(sorted_used_glyph_ids, start_glyph)
        upper = bisect_right(
            sorted_used_glyph_ids,
            start_glyph + count - 1,
        )
        candidate_glyph_ids = sorted_used_glyph_ids[lower:upper]
        for candidate_index, glyph_id in enumerate(candidate_glyph_ids):
            if (
                deadline is not None
                and candidate_index % 1024 == 0
                and time.perf_counter() > deadline
            ):
                raise _RecoveryError(
                    "recovery_timeout",
                    "Font recovery exceeded its time bound.",
                )
            if glyph_id:
                retained = retained_by_gid.get(glyph_id, 0)
                if retained < 2:
                    output[start + glyph_id - start_glyph] = glyph_id
                    retained_by_gid[glyph_id] = retained + 1
        selected_lower = bisect_left(sorted_selected_code_points, start)
        selected_upper = bisect_right(sorted_selected_code_points, end)
        for selected_index, code_point in enumerate(
            sorted_selected_code_points[selected_lower:selected_upper]
        ):
            if (
                deadline is not None
                and selected_index % 1024 == 0
                and time.perf_counter() > deadline
            ):
                raise _RecoveryError(
                    "recovery_timeout",
                    "Font recovery exceeded its time bound.",
                )
            output[code_point] = start_glyph + code_point - start
    return output


def _parse_unicode_cmap(
    cmap: bytes,
    *,
    num_glyphs: int,
    used_glyph_ids: frozenset[int] = frozenset(),
    mapping_budget: list[int] | None = None,
    deadline: float | None = None,
) -> Mapping[int, frozenset[int]]:
    _need(cmap, 0, 4, code="embedded_cmap_malformed")
    if _u16(cmap, 0) != 0:
        raise _RecoveryError(
            "embedded_cmap_unsupported",
            "TrueType cmap version is unsupported.",
        )
    subtable_count = _u16(cmap, 2)
    if not 1 <= subtable_count <= MAX_CMAP_SUBTABLES:
        raise _RecoveryError(
            "embedded_cmap_limit",
            "TrueType cmap subtable count exceeds the recovery bound.",
        )
    _need(cmap, 4, subtable_count * 8, code="embedded_cmap_malformed")
    trusted_offsets: list[int] = []
    for index in range(subtable_count):
        position = 4 + index * 8
        platform_id = _u16(cmap, position)
        encoding_id = _u16(cmap, position + 2)
        offset = _u32(cmap, position + 4)
        if platform_id == 0 or (
            platform_id == 3 and encoding_id in {1, 10}
        ):
            if offset not in trusted_offsets:
                trusted_offsets.append(offset)
    if not trusted_offsets:
        raise _RecoveryError(
            "embedded_cmap_unsupported",
            "Embedded TrueType program has no supported Unicode cmap.",
        )

    merged: dict[int, int] = {}
    retained_by_gid: dict[int, int] = {}
    remaining_mappings = (
        mapping_budget
        if mapping_budget is not None
        else [MAX_CMAP_MAPPINGS]
    )
    supported_subtables: list[tuple[int, int]] = []
    for offset in trusted_offsets:
        if deadline is not None and time.perf_counter() > deadline:
            raise _RecoveryError(
                "recovery_timeout",
                "Font recovery exceeded its time bound.",
            )
        _need(cmap, offset, 2, code="embedded_cmap_malformed")
        format_id = _u16(cmap, offset)
        if format_id == 4:
            mapping = _parse_cmap_format_4(
                cmap[offset:],
                num_glyphs=num_glyphs,
                mapping_budget=remaining_mappings,
                used_glyph_ids=used_glyph_ids,
                deadline=deadline,
            )
        elif format_id == 12:
            mapping = _parse_cmap_format_12(
                cmap[offset:],
                num_glyphs=num_glyphs,
                mapping_budget=remaining_mappings,
                used_glyph_ids=used_glyph_ids,
                deadline=deadline,
            )
        else:
            continue
        supported_subtables.append((offset, format_id))
        for code_point, glyph_id in mapping.items():
            prior = merged.get(code_point)
            if prior is not None and prior != glyph_id:
                raise _RecoveryError(
                    "embedded_cmap_conflicting_subtables",
                    "Unicode cmap subtables disagree for one code point.",
                )
            if prior is not None:
                continue
            retained = retained_by_gid.get(glyph_id, 0)
            if retained < 2:
                merged[code_point] = glyph_id
                retained_by_gid[glyph_id] = retained + 1

    if not supported_subtables:
        raise _RecoveryError(
            "embedded_cmap_unsupported",
            "Embedded TrueType Unicode cmap format is unsupported.",
        )

    # The used-GID pass above bounds retained state, but by itself could hide
    # a disagreement where another trusted subtable assigns one implicated
    # code point to an unused GID. Re-read only the at-most-two candidates per
    # used GID and compare their assignments. The declared mapping budget was
    # already charged during the first pass, so this validation pass does not
    # consume it again.
    implicated_code_points = frozenset(merged)
    for offset, format_id in supported_subtables:
        if format_id == 4:
            selected_mapping = _parse_cmap_format_4(
                cmap[offset:],
                num_glyphs=num_glyphs,
                mapping_budget=remaining_mappings,
                selected_code_points=implicated_code_points,
                charge_mapping_budget=False,
                deadline=deadline,
            )
        else:
            selected_mapping = _parse_cmap_format_12(
                cmap[offset:],
                num_glyphs=num_glyphs,
                mapping_budget=remaining_mappings,
                selected_code_points=implicated_code_points,
                charge_mapping_budget=False,
                deadline=deadline,
            )
        for code_point, glyph_id in selected_mapping.items():
            expected = merged.get(code_point)
            if expected is not None and expected != glyph_id:
                raise _RecoveryError(
                    "embedded_cmap_conflicting_subtables",
                    "Unicode cmap subtables disagree for one code point.",
                )

    by_gid: dict[int, set[int]] = {}
    for code_point, glyph_id in merged.items():
        by_gid.setdefault(glyph_id, set()).add(code_point)
    return {
        glyph_id: frozenset(sorted(code_points))
        for glyph_id, code_points in by_gid.items()
    }


def _parse_true_type(
    data: bytes,
    *,
    used_glyph_ids: frozenset[int] = frozenset(),
    mapping_budget: list[int] | None = None,
    deadline: float | None = None,
) -> _ParsedTrueType:
    if deadline is not None and time.perf_counter() > deadline:
        raise _RecoveryError(
            "recovery_timeout",
            "Font recovery exceeded its time bound.",
        )
    tables = _sfnt_tables(data)
    head = _table(data, tables, "head")
    maxp = _table(data, tables, "maxp")
    hhea = _table(data, tables, "hhea")
    hmtx = _table(data, tables, "hmtx")
    cmap = _table(data, tables, "cmap")

    _need(head, 0, 54)
    if _u32(head, 12) != 0x5F0F3CF5:
        raise _RecoveryError(
            "embedded_font_malformed",
            "TrueType head magic is invalid.",
        )
    units_per_em = _u16(head, 18)
    if not 16 <= units_per_em <= 16_384:
        raise _RecoveryError(
            "embedded_font_malformed",
            "TrueType unitsPerEm is invalid.",
        )
    _need(maxp, 0, 6)
    num_glyphs = _u16(maxp, 4)
    if not 1 <= num_glyphs <= 65_535:
        raise _RecoveryError(
            "embedded_font_malformed",
            "TrueType maxp glyph count is invalid.",
        )
    _need(hhea, 0, 36)
    metric_count = _u16(hhea, 34)
    if not 1 <= metric_count <= num_glyphs:
        raise _RecoveryError(
            "embedded_font_malformed",
            "TrueType hhea metric count is invalid.",
        )
    required_hmtx = metric_count * 4 + (num_glyphs - metric_count) * 2
    _need(hmtx, 0, required_hmtx)
    glyph_ids_for_metrics = tuple(
        sorted(
            glyph_id
            for glyph_id in used_glyph_ids
            if 0 <= glyph_id < num_glyphs
        )
    )
    final_advance = _u16(hmtx, (metric_count - 1) * 4)
    advances = {
        glyph_id: (
            _u16(hmtx, glyph_id * 4)
            if glyph_id < metric_count
            else final_advance
        )
        for glyph_id in glyph_ids_for_metrics
    }

    return _ParsedTrueType(
        units_per_em=units_per_em,
        num_glyphs=num_glyphs,
        advances=advances,
        codepoints_by_gid=_parse_unicode_cmap(
            cmap,
            num_glyphs=num_glyphs,
            used_glyph_ids=used_glyph_ids,
            mapping_budget=mapping_budget,
            deadline=deadline,
        ),
    )


def _extract_true_type(
    spec: Mapping[str, Any],
    *,
    used_glyph_ids: frozenset[int] = frozenset(),
    mapping_budget: list[int] | None = None,
    deadline: float | None = None,
) -> _ParsedTrueType:
    candidate = _font_dictionary_with_descriptor(spec)
    if _safe_name(candidate.get("Subtype")) != "CIDFontType2":
        raise _RecoveryError(
            "unsupported_descendant_subtype",
            "Recovery requires a CIDFontType2 descendant.",
        )
    try:
        descriptor = resolve1(candidate.get("FontDescriptor"))
    except Exception as exc:
        raise _RecoveryError(
            "embedded_program_dangling",
            "FontDescriptor cannot be resolved.",
        ) from exc
    if not isinstance(descriptor, Mapping):
        raise _RecoveryError(
            "embedded_program_missing",
            "FontDescriptor is missing or invalid.",
        )
    if descriptor.get("FontFile2") is None:
        raise _RecoveryError(
            "embedded_program_missing",
            "Eligible font has no embedded TrueType FontFile2.",
        )
    if descriptor.get("FontFile") is not None or descriptor.get("FontFile3") is not None:
        raise _RecoveryError(
            "embedded_program_ambiguous",
            "Eligible font declares multiple embedded program types.",
        )
    try:
        stream = resolve1(descriptor.get("FontFile2"))
    except Exception as exc:
        raise _RecoveryError(
            "embedded_program_dangling",
            "Embedded FontFile2 cannot be resolved.",
        ) from exc
    if not isinstance(stream, PDFStream):
        raise _RecoveryError(
            "embedded_program_non_stream",
            "Embedded FontFile2 is not a stream.",
        )
    return _parse_true_type(
        _bounded_font_program(stream),
        used_glyph_ids=used_glyph_ids,
        mapping_budget=mapping_budget,
        deadline=deadline,
    )


def _is_ligature_code_point(code_point: int) -> bool:
    decomposition = unicodedata.decomposition(chr(code_point))
    if not decomposition.startswith("<"):
        return False
    pieces = decomposition.split()
    return len(pieces) > 2


def _is_unsafe_code_point(code_point: int) -> bool:
    if 0xD800 <= code_point <= 0xDFFF:
        return True
    category = unicodedata.category(chr(code_point))
    # Format controls are deliberately refused as a class. This includes
    # bidirectional overrides/isolates and invisible join controls; recovery
    # must never introduce display-order or invisible-control behavior into
    # trusted public text.
    if category in {"Cc", "Cf", "Cs", "Co", "Cn"}:
        return True
    return (
        code_point & 0xFFFF in {0xFFFE, 0xFFFF}
        or 0xFDD0 <= code_point <= 0xFDEF
    )


def _evidence_id(
    font_ref: str,
    page_index: int,
    run_index: int,
    glyph_index: int | None = None,
) -> str:
    payload = ":".join(
        (
            font_ref,
            str(page_index),
            str(run_index),
            "" if glyph_index is None else str(glyph_index),
        )
    )
    return "font-recovery-" + hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()[:24]


class _RecoveryResourceManager(_BoundedResourceManager):
    def __init__(
        self,
        *,
        deadline: float,
        eligible_refs: set[str],
    ) -> None:
        super().__init__(deadline=deadline)
        self.eligible_refs = eligible_refs
        self.eligible_specs: dict[str, Mapping[str, object]] = {}
        self.parsed_programs: dict[str, _ParsedTrueType] = {}
        self.program_errors: dict[str, _RecoveryError] = {}
        self.font_programs_parsed = 0
        # This budget is shared by every embedded cmap parsed for the
        # document. Compact cmap ranges therefore cannot reset a large
        # expansion allowance for each eligible font.
        self.cmap_mapping_budget = [MAX_CMAP_MAPPINGS]

    def get_font(
        self,
        objid: object,
        spec: Mapping[str, object],
    ) -> Any:
        font = super().get_font(objid, spec)
        font_ref = self.font_refs.get(id(font))
        if (
            font_ref in self.eligible_refs
            and font_ref not in self.eligible_specs
        ):
            self.eligible_specs[font_ref] = spec
        return font

    def parse_program(
        self,
        font_ref: str,
        used_glyph_ids: frozenset[int],
    ) -> _ParsedTrueType | None:
        if font_ref in self.parsed_programs:
            return self.parsed_programs[font_ref]
        if font_ref in self.program_errors:
            return None
        spec = self.eligible_specs.get(font_ref)
        if spec is None:
            self.program_errors[font_ref] = _RecoveryError(
                "embedded_program_unavailable",
                "Eligible embedded program was not encountered.",
            )
            return None
        try:
            if time.perf_counter() > self.deadline:
                raise _RecoveryError(
                    "recovery_timeout",
                    "Font recovery exceeded its time bound.",
                )
            parsed = _extract_true_type(
                spec,
                used_glyph_ids=used_glyph_ids,
                mapping_budget=self.cmap_mapping_budget,
                deadline=self.deadline,
            )
            self.parsed_programs[font_ref] = parsed
            self.font_programs_parsed += 1
            return parsed
        except _RecoveryError as exc:
            self.program_errors[font_ref] = exc
        except Exception as exc:  # bounded fail-closed diagnostic
            self.program_errors[font_ref] = _RecoveryError(
                "embedded_font_malformed",
                "Embedded TrueType program could not be parsed: "
                f"{type(exc).__name__}.",
            )
        return None


class _RecoveryDevice(_AuditDevice):
    def render_string(self, *args: Any, **kwargs: Any) -> None:
        if len(self.runs) >= MAX_RECOVERY_RUNS:
            self.run_limit_reached = True
            raise _RecoveryRunLimitReached(
                "Font recovery run limit reached"
            )
        super().render_string(*args, **kwargs)

    def render_char(self, *args: Any, **kwargs: Any) -> float:
        character_limit = min(
            MAX_RECORDED_CHARACTERS,
            MAX_RECOVERED_GLYPHS,
        )
        if len(self.characters) >= character_limit:
            self.character_limit_reached = True
            raise _RecoveryGlyphLimitReached(
                "Font recovery glyph limit reached"
            )
        return super().render_char(*args, **kwargs)


def _as_audit_payload(
    audit_report: FontAuditReport | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(audit_report, FontAuditReport):
        return audit_report.model_dump(mode="json", exclude_none=True)
    if not isinstance(audit_report, Mapping):
        raise TypeError("font recovery requires a font-audit report")
    validated = FontAuditReport.model_validate(dict(audit_report))
    return validated.model_dump(mode="json", exclude_none=True)


def _font_refusal(
    font: Mapping[str, Any],
    *,
    reason_code: str,
    message: str,
) -> FontRecoveryRefusal:
    object_id = font.get("font_object_id")
    return FontRecoveryRefusal(
        font_ref=str(font.get("font_ref") or "unknown"),
        font_object_id=(
            int(object_id)
            if isinstance(object_id, int) and not isinstance(object_id, bool)
            else None
        ),
        page_indexes=[
            int(value) for value in (font.get("page_indexes") or [])
        ],
        reason_code=reason_code,
        message=message,
    )


def _eligibility(
    audit: Mapping[str, Any],
) -> tuple[dict[str, Mapping[str, Any]], list[FontRecoveryRefusal]]:
    fonts = {
        str(font.get("font_ref")): font
        for font in (audit.get("fonts") or [])
        if isinstance(font, Mapping) and font.get("font_ref")
    }
    eligible: dict[str, Mapping[str, Any]] = {}
    refusals: list[FontRecoveryRefusal] = []
    findings = audit.get("findings") or []
    for finding in findings:
        if not isinstance(finding, Mapping):
            continue
        font_ref = str(finding.get("font_ref") or "")
        font = fonts.get(font_ref, finding)
        if finding.get("health") != "suspicious":
            reasons = [
                str(value) for value in (finding.get("reason_codes") or [])
            ]
            reason = reasons[0] if reasons else "audit_unresolved"
            refusals.append(
                _font_refusal(
                    font,
                    reason_code=reason,
                    message="Font audit did not classify this font as safely recoverable.",
                )
            )
            continue
        if font.get("object_identity_basis") != "indirect_object":
            refusals.append(
                _font_refusal(
                    font,
                    reason_code="direct_font_identity_unsupported",
                    message="Direct font identity is not stable across the recovery pass.",
                )
            )
            continue
        object_id = font.get("font_object_id")
        if not isinstance(object_id, int) or isinstance(object_id, bool):
            refusals.append(
                _font_refusal(
                    font,
                    reason_code="font_object_identity_missing",
                    message="Indirect recovery requires a stable font object ID.",
                )
            )
            continue
        if font.get("subtype") != "Type0":
            refusals.append(
                _font_refusal(
                    font,
                    reason_code="unsupported_font_subtype",
                    message="Only audited Type0 fonts are recoverable.",
                )
            )
            continue
        if font.get("to_unicode") != "present":
            refusals.append(
                _font_refusal(
                    font,
                    reason_code=f"to_unicode_{font.get('to_unicode') or 'unknown'}",
                    message="Recovery requires an audited, unambiguous ToUnicode stream.",
                )
            )
            continue
        if font.get("encoding") != "Identity-H":
            refusals.append(
                _font_refusal(
                    font,
                    reason_code="unsupported_font_encoding",
                    message="Only horizontal Identity-H fonts are recoverable.",
                )
            )
            continue
        if font.get("cid_to_gid") != "identity":
            refusals.append(
                _font_refusal(
                    font,
                    reason_code=f"cid_to_gid_{font.get('cid_to_gid') or 'unknown'}",
                    message="Recovery requires an identity CID-to-GID mapping.",
                )
            )
            continue
        if (
            font.get("embedded_program") is not True
            or font.get("embedded_program_state") != "present"
        ):
            refusals.append(
                _font_refusal(
                    font,
                    reason_code=(
                        "embedded_program_"
                        + str(font.get("embedded_program_state") or "missing")
                    ),
                    message="Recovery requires a present embedded TrueType program.",
                )
            )
            continue
        eligible[font_ref] = font
    return eligible, refusals


def _validate_font_characters(
    font_ref: str,
    characters: Sequence[_Character],
    program: _ParsedTrueType,
) -> tuple[dict[int, int], float]:
    recovered: dict[int, int] = {}
    maximum_width_delta = 0.0
    for character in characters:
        glyph_id = character.cid
        if glyph_id < 0 or glyph_id >= program.num_glyphs:
            raise _RecoveryError(
                "embedded_cmap_missing_used_glyph",
                "A used identity glyph falls outside the embedded maxp table.",
            )
        candidates = program.codepoints_by_gid.get(glyph_id, frozenset())
        if not candidates:
            raise _RecoveryError(
                "embedded_cmap_missing_used_glyph",
                "A used identity glyph has no embedded Unicode mapping.",
            )
        if len(candidates) != 1:
            raise _RecoveryError(
                "embedded_cmap_many_to_one",
                "A used glyph maps to more than one Unicode code point.",
            )
        code_point = next(iter(candidates))
        if _is_ligature_code_point(code_point):
            raise _RecoveryError(
                "embedded_cmap_ligature",
                "A used glyph is a compatibility ligature.",
            )
        if _is_unsafe_code_point(code_point):
            raise _RecoveryError(
                "embedded_cmap_unsafe_codepoint",
                "A used glyph maps to an unsafe Unicode scalar.",
            )
        embedded_width = program.advances[glyph_id] / program.units_per_em
        width_delta = abs(character.font_width - embedded_width)
        if (
            not math.isfinite(character.font_width)
            or character.font_width < 0
            or not math.isfinite(character.advance)
            or not all(math.isfinite(value) for value in character.bbox)
        ):
            raise _RecoveryError(
                "glyph_geometry_invalid",
                "A used glyph has non-finite width, advance, or geometry.",
            )
        if width_delta > WIDTH_TOLERANCE_EM:
            raise _RecoveryError(
                "font_advance_mismatch",
                "PDF width disagrees with the embedded hmtx advance.",
            )
        maximum_width_delta = max(maximum_width_delta, width_delta)
        recovered[glyph_id] = code_point
    return recovered, maximum_width_delta


def _validate_live_font_eligibility(
    audited_font: Mapping[str, Any],
    live_spec: Any,
    characters: Sequence[_Character],
) -> None:
    """Revalidate every trusted audit predicate against this PDF pass."""

    if live_spec is None:
        raise _RecoveryError(
            "live_font_not_found",
            "The audited font object was not found in the recovery pass.",
        )
    if (
        live_spec.object_identity_basis != "indirect_object"
        or live_spec.object_id != audited_font.get("font_object_id")
        or live_spec.font_ref != audited_font.get("font_ref")
    ):
        raise _RecoveryError(
            "live_font_identity_mismatch",
            "Live font identity does not match the supplied audit report.",
        )
    if live_spec.subtype != "Type0":
        raise _RecoveryError(
            "unsupported_font_subtype",
            "Live recovery font is not Type0.",
        )
    if live_spec.encoding != "Identity-H":
        raise _RecoveryError(
            "unsupported_font_encoding",
            "Live recovery font is not Identity-H.",
        )
    if live_spec.to_unicode != "present":
        raise _RecoveryError(
            f"to_unicode_{live_spec.to_unicode}",
            "Live ToUnicode state does not match safe eligibility.",
        )
    used_cids = {character.cid for character in characters}
    if live_spec.to_unicode_ambiguous_cids & used_cids:
        raise _RecoveryError(
            "to_unicode_ambiguous",
            "Live ToUnicode mapping is ambiguous for a used CID.",
        )
    cid_to_gid = _resolved_cid_to_gid_state(live_spec, used_cids)
    if cid_to_gid != "identity":
        raise _RecoveryError(
            f"cid_to_gid_{cid_to_gid}",
            "Live CID-to-GID mapping is not identity.",
        )
    if (
        live_spec.embedded_program is not True
        or live_spec.embedded_program_state != "present"
    ):
        raise _RecoveryError(
            "embedded_program_" + live_spec.embedded_program_state,
            "Live font has no safely resolvable embedded program.",
        )


def _recovery_run(
    run: _Run,
    *,
    run_index: int,
    object_id: int,
    program: _ParsedTrueType,
    code_points: Mapping[int, int],
    maximum_width_delta: float,
) -> FontRecoveryRun:
    glyphs: list[FontRecoveryGlyph] = []
    for glyph_index, character in enumerate(run.characters):
        code_point = code_points[character.cid]
        recovered_text = chr(code_point)
        glyphs.append(
            FontRecoveryGlyph(
                evidence_id=_evidence_id(
                    run.font_ref,
                    run.page_index,
                    run_index,
                    glyph_index,
                ),
                page_index=run.page_index,
                run_index=run_index,
                glyph_index=glyph_index,
                font_ref=run.font_ref,
                font_object_id=object_id,
                cid=character.cid,
                glyph_id=character.cid,
                original_text=character.mapped_text,
                recovered_text=recovered_text,
                unicode_code_point=code_point,
                bbox=FontAuditBBox(
                    x=round(character.bbox[0], 3),
                    y=round(character.bbox[1], 3),
                    width=round(character.bbox[2], 3),
                    height=round(character.bbox[3], 3),
                ),
                page_advance=round(character.advance, 6),
                pdf_width_em=round(character.font_width, 6),
                embedded_advance_width=program.advances[character.cid],
                units_per_em=program.units_per_em,
                width_delta_em=round(
                    abs(
                        character.font_width
                        - (
                            program.advances[character.cid]
                            / program.units_per_em
                        )
                    ),
                    9,
                ),
            )
        )
    return FontRecoveryRun(
        evidence_id=_evidence_id(
            run.font_ref,
            run.page_index,
            run_index,
        ),
        page_index=run.page_index,
        run_index=run_index,
        font_ref=run.font_ref,
        font_object_id=object_id,
        bbox=_union_bbox(run.characters),
        original_text="".join(
            character.mapped_text for character in run.characters
        ),
        recovered_text="".join(glyph.recovered_text for glyph in glyphs),
        glyphs=glyphs,
        confidence_basis={
            "font_subtype": "Type0",
            "descendant_subtype": "CIDFontType2",
            "encoding": "Identity-H",
            "cid_to_gid": "identity",
            "unicode_cmap": "one_to_one_over_used_glyphs",
            "pdf_width_matches_hmtx": True,
            "maximum_width_delta_em": round(maximum_width_delta, 9),
            "semantic_completion": False,
        },
    )


def _unavailable(
    code: str,
    message: str,
    *,
    source_sha256: str | None = None,
) -> FontRecoveryReport:
    return FontRecoveryReport(
        source_sha256=source_sha256,
        status="unavailable",
        fonts_considered=0,
        fonts_recovered=0,
        font_programs_parsed=0,
        pages_inspected=0,
        characters_inspected=0,
        recovered_glyph_count=0,
        runs=[],
        refusals=[],
        diagnostics=[FontRecoveryDiagnostic(code=code, message=message)],
    )


def recover_pdf_font_text(
    pdf_bytes: bytes,
    audit_report: FontAuditReport | Mapping[str, Any],
) -> FontRecoveryReport:
    """Recover only audited, indirect, identity-mapped TrueType glyph runs."""

    if not isinstance(pdf_bytes, bytes):
        return _unavailable(
            "invalid_input_type",
            "Font recovery requires immutable PDF bytes.",
        )
    if not pdf_bytes:
        return _unavailable(
            "empty_pdf",
            "Font recovery received an empty PDF.",
        )
    source_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    if len(pdf_bytes) > MAX_INPUT_BYTES:
        return _unavailable(
            "pdf_size_limit",
            "PDF exceeds the font-recovery input bound.",
            source_sha256=source_sha256,
        )
    try:
        audit = _as_audit_payload(audit_report)
    except Exception as exc:
        return _unavailable(
            "invalid_audit_report",
            f"Font-audit report is invalid: {type(exc).__name__}.",
            source_sha256=source_sha256,
        )
    audit_source_sha256 = audit.get("source_sha256")
    if not isinstance(audit_source_sha256, str):
        return _unavailable(
            "audit_source_unbound",
            "Font recovery requires an audit bound to exact PDF bytes.",
            source_sha256=source_sha256,
        )
    if source_sha256 != audit_source_sha256:
        return _unavailable(
            "audit_source_mismatch",
            "Font-audit source identity does not match the recovery PDF.",
            source_sha256=source_sha256,
        )
    if audit.get("status") != "complete":
        return _unavailable(
            "audit_incomplete",
            "Font recovery requires a complete font-audit report.",
            source_sha256=source_sha256,
        )

    eligible, refusals = _eligibility(audit)
    fonts_considered = len(eligible) + len(refusals)
    if not eligible:
        return FontRecoveryReport(
            source_sha256=source_sha256,
            status="complete",
            fonts_considered=fonts_considered,
            fonts_recovered=0,
            font_programs_parsed=0,
            pages_inspected=0,
            characters_inspected=0,
            recovered_glyph_count=0,
            runs=[],
            refusals=refusals,
            diagnostics=[],
        )
    if len(eligible) > MAX_FONT_OBJECTS:
        return _unavailable(
            "font_object_limit",
            "Eligible font count exceeds the recovery bound.",
            source_sha256=source_sha256,
        )

    resource_manager = _RecoveryResourceManager(
        deadline=time.perf_counter() + MAX_RECOVERY_SECONDS,
        eligible_refs=set(eligible),
    )
    device = _RecoveryDevice(resource_manager)
    pages_inspected = 0
    diagnostics: list[FontRecoveryDiagnostic] = []
    try:
        document = PDFDocument(PDFParser(io.BytesIO(pdf_bytes)), caching=True)
        interpreter = PDFPageInterpreter(resource_manager, device)
        for page_index, page in enumerate(PDFPage.create_pages(document), 1):
            if time.perf_counter() > resource_manager.deadline:
                diagnostics.append(
                    FontRecoveryDiagnostic(
                        code="recovery_timeout",
                        message="Font recovery exceeded its time bound.",
                    )
                )
                break
            if page_index > MAX_PAGES:
                diagnostics.append(
                    FontRecoveryDiagnostic(
                        code="page_limit",
                        message="PDF page count exceeds the recovery bound.",
                    )
                )
                break
            device.page_index = page_index
            try:
                interpreter.process_page(page)
                pages_inspected += 1
            except _RecoveryGlyphLimitReached:
                diagnostics.append(
                    FontRecoveryDiagnostic(
                        code="recovered_glyph_limit",
                        message="Recovered glyph evidence reached its bound.",
                        page_index=page_index,
                    )
                )
                break
            except _RecoveryRunLimitReached:
                diagnostics.append(
                    FontRecoveryDiagnostic(
                        code="recovery_run_limit",
                        message="Recovered run evidence reached its bound.",
                        page_index=page_index,
                    )
                )
                break
            except Exception as exc:
                diagnostics.append(
                    FontRecoveryDiagnostic(
                        code=(
                            "recovery_timeout"
                            if isinstance(exc, TimeoutError)
                            else "page_recovery_failed"
                        ),
                        message=(
                            "Font recovery exceeded its time bound."
                            if isinstance(exc, TimeoutError)
                            else (
                                "Font recovery could not inspect one page: "
                                f"{type(exc).__name__}."
                            )
                        ),
                        page_index=page_index,
                    )
                )
                break
    except Exception as exc:
        return _unavailable(
            "pdf_recovery_failed",
            f"Font recovery could not open the PDF: {type(exc).__name__}.",
            source_sha256=source_sha256,
        )
    finally:
        device.close()

    if (
        device.character_limit_reached
        and not any(
            diagnostic.code == "recovered_glyph_limit"
            for diagnostic in diagnostics
        )
    ):
        diagnostics.append(
            FontRecoveryDiagnostic(
                code="recovered_glyph_limit",
                message="Glyph recovery evidence reached its bound.",
            )
        )
    if (
        device.run_limit_reached
        and not any(
            diagnostic.code == "recovery_run_limit"
            for diagnostic in diagnostics
        )
    ):
        diagnostics.append(
            FontRecoveryDiagnostic(
                code="recovery_run_limit",
                message="Recovered run evidence reached its bound.",
            )
        )

    characters_by_font: dict[str, list[_Character]] = {
        font_ref: [] for font_ref in eligible
    }
    for character in device.characters:
        if character.font_ref in characters_by_font:
            characters_by_font[character.font_ref].append(character)

    if diagnostics:
        return FontRecoveryReport(
            source_sha256=source_sha256,
            status="partial",
            fonts_considered=fonts_considered,
            fonts_recovered=0,
            font_programs_parsed=0,
            pages_inspected=pages_inspected,
            characters_inspected=len(device.characters),
            recovered_glyph_count=0,
            runs=[],
            refusals=refusals,
            diagnostics=diagnostics[:MAX_DIAGNOSTICS],
        )

    code_points_by_font: dict[str, dict[int, int]] = {}
    maximum_delta_by_font: dict[str, float] = {}
    recovered_refs: set[str] = set()
    for font_ref, font in eligible.items():
        characters = characters_by_font.get(font_ref, [])
        if not characters:
            refusals.append(
                _font_refusal(
                    font,
                    reason_code="eligible_font_unused",
                    message="Eligible font had no recoverable used glyphs.",
                )
            )
            continue
        try:
            _validate_live_font_eligibility(
                font,
                resource_manager.font_specs.get(font_ref),
                characters,
            )
        except _RecoveryError as exc:
            refusals.append(
                _font_refusal(
                    font,
                    reason_code=exc.code,
                    message=exc.message,
                )
            )
            continue
        program = resource_manager.parse_program(
            font_ref,
            frozenset(character.cid for character in characters),
        )
        if program is None:
            error = resource_manager.program_errors[font_ref]
            refusals.append(
                _font_refusal(
                    font,
                    reason_code=error.code,
                    message=error.message,
                )
            )
            continue
        try:
            code_points, maximum_delta = _validate_font_characters(
                font_ref,
                characters,
                program,
            )
        except _RecoveryError as exc:
            refusals.append(
                _font_refusal(
                    font,
                    reason_code=exc.code,
                    message=exc.message,
                )
            )
            continue
        code_points_by_font[font_ref] = code_points
        maximum_delta_by_font[font_ref] = maximum_delta
        recovered_refs.add(font_ref)

    runs: list[FontRecoveryRun] = []
    recovered_glyph_count = 0
    for run_index, run in enumerate(device.runs, 1):
        if run.font_ref not in recovered_refs or not run.characters:
            continue
        if len(runs) >= MAX_RECOVERY_RUNS:
            diagnostics.append(
                FontRecoveryDiagnostic(
                    code="recovery_run_limit",
                    message="Recovered run evidence reached its bound.",
                )
            )
            break
        if recovered_glyph_count + len(run.characters) > MAX_RECOVERED_GLYPHS:
            diagnostics.append(
                FontRecoveryDiagnostic(
                    code="recovered_glyph_limit",
                    message="Recovered glyph evidence reached its bound.",
                )
            )
            break
        font = eligible[run.font_ref]
        object_id = font.get("font_object_id")
        if not isinstance(object_id, int) or isinstance(object_id, bool):
            continue
        program = resource_manager.parsed_programs[run.font_ref]
        recovered_run = _recovery_run(
            run,
            run_index=run_index,
            object_id=object_id,
            program=program,
            code_points=code_points_by_font[run.font_ref],
            maximum_width_delta=maximum_delta_by_font[run.font_ref],
        )
        if recovered_run.recovered_text == recovered_run.original_text:
            continue
        runs.append(recovered_run)
        recovered_glyph_count += len(recovered_run.glyphs)

    status: Literal["complete", "partial", "unavailable"] = (
        "partial" if diagnostics else "complete"
    )
    return FontRecoveryReport(
        source_sha256=source_sha256,
        status=status,
        fonts_considered=fonts_considered,
        fonts_recovered=len(recovered_refs),
        font_programs_parsed=resource_manager.font_programs_parsed,
        pages_inspected=pages_inspected,
        characters_inspected=len(device.characters),
        recovered_glyph_count=recovered_glyph_count,
        runs=runs,
        refusals=refusals,
        diagnostics=diagnostics[:MAX_DIAGNOSTICS],
    )
