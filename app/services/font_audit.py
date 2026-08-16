"""Bounded, detection-only PDF font mapping audit.

The audit uses PDFMiner's normal page interpreter so page and Form XObject
text share one traversal. It records only dictionary state, character codes,
mapping outcomes, advances, and page-space geometry. Embedded font program
bytes are never executed, returned, logged, or persisted.
"""

from __future__ import annotations

import hashlib
import io
import math
import time
import unicodedata
import zlib
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pdfminer.cmapdb import CMapParser, FileUnicodeMap
from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import LTChar
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfexceptions import PDFException
from pdfminer.pdffont import PDFFont, PDFUnicodeNotDefined
from pdfminer.pdfinterp import (
    PDFGraphicState,
    PDFPageInterpreter,
    PDFResourceManager,
    PDFTextState,
)
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser
from pdfminer.pdftypes import (
    PDFObjRef,
    PDFStream,
    dict_value,
    list_value,
    resolve1,
)
from pdfminer.psparser import literal_name
from pydantic import BaseModel, ConfigDict, Field


FONT_AUDIT_SCHEMA_VERSION = "1.0"
MAX_INPUT_BYTES = 25 * 1024 * 1024
MAX_PAGES = 100
MAX_FONT_OBJECTS = 256
MAX_RECORDED_CHARACTERS = 500_000
MAX_RECORDED_RUNS = 10_000
MAX_RUNS_PER_FINDING = 256
MAX_CIDS_PER_RECORD = 256
MAX_DIAGNOSTICS = 20
MAX_RAW_CMAP_BYTES = 2 * 1024 * 1024
MAX_DECODED_CMAP_BYTES = 2 * 1024 * 1024
MAX_CMAP_MAPPINGS = 262_144
MAX_CID_TO_GID_BYTES = 2 * 65_536
MAX_AUDIT_SECONDS = 5.0
MIN_COLLAPSED_SPACE_USES = 8
MIN_COLLAPSED_SPACE_CIDS = 4
MIN_COLLAPSED_SPACE_RATIO = 0.5

_STANDARD_14 = frozenset(
    {
        "Courier",
        "Courier-Bold",
        "Courier-BoldOblique",
        "Courier-Oblique",
        "Helvetica",
        "Helvetica-Bold",
        "Helvetica-BoldOblique",
        "Helvetica-Oblique",
        "Symbol",
        "Times-Bold",
        "Times-BoldItalic",
        "Times-Italic",
        "Times-Roman",
        "ZapfDingbats",
    }
)


class _AuditModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class FontAuditBBox(_AuditModel):
    x: float
    y: float
    width: float = Field(ge=0)
    height: float = Field(ge=0)
    unit: Literal["pt"] = "pt"


class FontAuditRun(_AuditModel):
    page_index: int = Field(ge=1)
    bbox: FontAuditBBox
    character_count: int = Field(ge=1)
    mapped_space_count: int = Field(ge=0)
    distinct_cids: list[int]


class FontInventoryRecord(_AuditModel):
    font_ref: str
    font_object_id: int | None = Field(default=None, ge=1)
    object_identity_basis: Literal[
        "indirect_object",
        "direct_dictionary",
    ]
    base_font: str
    subtype: str
    encoding: str | None = None
    to_unicode: Literal[
        "present",
        "missing",
        "ambiguous",
        "not_applicable",
    ]
    cid_to_gid: Literal[
        "identity",
        "non_identity",
        "malformed",
        "stream_unresolved",
        "missing",
        "not_applicable",
        "unsupported",
    ]
    embedded_program: bool
    embedded_program_state: Literal[
        "present",
        "missing",
        "dangling",
        "non_stream",
    ]
    standard_14: bool
    classification: Literal["healthy", "suspicious", "unresolved", "unused"]
    page_indexes: list[int]
    used_character_count: int = Field(ge=0)
    distinct_used_cids: int = Field(ge=0)
    mapped_space_count: int = Field(ge=0)
    distinct_space_mapped_cids: int = Field(ge=0)
    replacement_or_undefined_count: int = Field(ge=0)
    private_use_count: int = Field(ge=0)
    control_count: int = Field(ge=0)
    positive_advance_space_count: int = Field(ge=0)


class FontAuditFinding(_AuditModel):
    health: Literal["suspicious", "unresolved"]
    font_ref: str
    font_object_id: int | None = Field(default=None, ge=1)
    object_identity_basis: Literal[
        "indirect_object",
        "direct_dictionary",
    ]
    base_font: str
    subtype: str
    page_indexes: list[int]
    reason_codes: list[str]
    confidence_basis: dict[str, Any]
    run_count: int = Field(default=0, ge=0)
    runs_truncated: bool = False
    runs: list[FontAuditRun]


class FontAuditDiagnostic(_AuditModel):
    code: str
    message: str
    page_index: int | None = Field(default=None, ge=1)
    font_ref: str | None = None
    font_object_id: int | None = Field(default=None, ge=1)


class FontAuditReport(_AuditModel):
    schema_version: Literal["1.0"] = FONT_AUDIT_SCHEMA_VERSION
    source_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    status: Literal["complete", "partial", "unavailable"]
    fonts_inspected: int = Field(ge=0)
    font_cache_hit_count: int = Field(ge=0)
    pages_inspected: int = Field(ge=0)
    characters_inspected: int = Field(ge=0)
    fonts: list[FontInventoryRecord]
    findings: list[FontAuditFinding]
    diagnostics: list[FontAuditDiagnostic]


@dataclass(slots=True)
class _FontSpec:
    font_ref: str
    object_id: int | None
    object_identity_basis: Literal[
        "indirect_object",
        "direct_dictionary",
    ]
    base_font: str
    subtype: str
    encoding: str | None
    to_unicode: str
    to_unicode_ambiguous_cids: frozenset[int]
    cid_to_gid: str
    cid_to_gid_bytes: bytes | None
    embedded_program: bool
    embedded_program_state: str
    standard_14: bool


@dataclass(slots=True)
class _Character:
    font_ref: str
    page_index: int
    cid: int
    mapped_text: str
    advance: float
    bbox: tuple[float, float, float, float]
    font_width: float = 0.0


@dataclass(slots=True)
class _Run:
    font_ref: str
    page_index: int
    characters: list[_Character] = field(default_factory=list)


def _safe_name(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return literal_name(resolve1(value))
    except Exception:
        text = str(value).strip()
        if text.startswith("/'") and text.endswith("'"):
            return text[2:-1]
        if text.startswith("/"):
            return text[1:]
        return text or None


def _base_font_name(value: Any) -> str:
    name = _safe_name(value) or "unknown"
    return name.split("+", 1)[-1] if "+" in name else name


def _resolved_mapping(value: Any) -> Mapping[str, Any]:
    try:
        resolved = resolve1(value)
    except Exception:
        return {}
    return resolved if isinstance(resolved, Mapping) else {}


def _font_dictionary_with_descriptor(
    spec: Mapping[str, Any],
) -> Mapping[str, Any]:
    subtype = _safe_name(spec.get("Subtype"))
    candidate: Mapping[str, Any] = spec
    if subtype == "Type0":
        try:
            descendants = list_value(resolve1(spec.get("DescendantFonts")))
        except Exception:
            descendants = []
        if descendants:
            candidate = _resolved_mapping(descendants[0])
    return candidate


def _embedded_program_details(
    spec: Mapping[str, Any],
) -> tuple[bool, str]:
    candidate = _font_dictionary_with_descriptor(spec)
    if "FontDescriptor" not in candidate:
        return False, "missing"
    try:
        descriptor = resolve1(candidate.get("FontDescriptor"))
    except Exception:
        return False, "dangling"
    if not isinstance(descriptor, Mapping):
        return False, "non_stream"

    entries = [
        descriptor.get(key)
        for key in ("FontFile", "FontFile2", "FontFile3")
        if descriptor.get(key) is not None
    ]
    if not entries:
        return False, "missing"

    saw_dangling = False
    saw_non_stream = False
    for entry in entries:
        try:
            resolved = resolve1(entry)
        except Exception:
            saw_dangling = True
            continue
        if isinstance(entry, PDFObjRef) and resolved is None:
            saw_dangling = True
            continue
        if isinstance(resolved, PDFStream):
            # Do not decode, execute, return, log, or persist font bytes.
            return True, "present"
        saw_non_stream = True
    if saw_dangling:
        return False, "dangling"
    if saw_non_stream:
        return False, "non_stream"
    return False, "missing"


def _descendant(spec: Mapping[str, Any]) -> Mapping[str, Any]:
    if _safe_name(spec.get("Subtype")) != "Type0":
        return {}
    try:
        descendants = list_value(resolve1(spec.get("DescendantFonts")))
    except Exception:
        return {}
    return _resolved_mapping(descendants[0]) if descendants else {}


def _bounded_cid_to_gid_bytes(stream: PDFStream) -> bytes:
    raw_value = stream.get_rawdata()
    if raw_value is None:
        decoded_value = stream.data
        if not isinstance(decoded_value, bytes):
            raise _CMapFilterError("unavailable CIDToGIDMap stream")
        if len(decoded_value) > MAX_CID_TO_GID_BYTES:
            raise _CMapLimitError("decoded CIDToGIDMap stream")
        return decoded_value
    raw = raw_value
    if len(raw) > MAX_CID_TO_GID_BYTES:
        raise _CMapLimitError("CIDToGIDMap stream")

    filters = stream.get_filters()
    if not filters:
        decoded = raw
    elif len(filters) == 1 and _safe_name(filters[0][0]) in {
        "FlateDecode",
        "Fl",
    }:
        decompressor = zlib.decompressobj()
        try:
            decoded = decompressor.decompress(
                raw,
                MAX_CID_TO_GID_BYTES + 1,
            )
        except zlib.error as exc:
            raise _CMapFilterError("invalid Flate CIDToGIDMap stream") from exc
        if (
            len(decoded) > MAX_CID_TO_GID_BYTES
            or decompressor.unconsumed_tail
            or not decompressor.eof
        ):
            raise _CMapLimitError("decoded CIDToGIDMap stream")
    else:
        raise _CMapFilterError("unsupported CIDToGIDMap filter chain")

    if len(decoded) > MAX_CID_TO_GID_BYTES:
        raise _CMapLimitError("decoded CIDToGIDMap stream")
    return decoded


def _cid_to_gid_details(
    spec: Mapping[str, Any],
) -> tuple[str, bytes | None]:
    if _safe_name(spec.get("Subtype")) != "Type0":
        return "not_applicable", None
    descendant = _descendant(spec)
    if "CIDToGIDMap" not in descendant:
        return "missing", None
    raw_value = descendant.get("CIDToGIDMap")
    if _safe_name(raw_value) == "Identity":
        return "identity", None
    try:
        resolved = resolve1(raw_value)
    except Exception:
        return "malformed", None
    if not isinstance(resolved, PDFStream):
        return "unsupported", None
    try:
        return "stream_unresolved", _bounded_cid_to_gid_bytes(resolved)
    except _CMapLimitError:
        return "malformed", None
    except _CMapFilterError:
        return "unsupported", None


def _to_unicode_state(
    spec: Mapping[str, Any],
    ambiguous_cids: frozenset[int],
) -> str:
    if _safe_name(spec.get("Subtype")) != "Type0":
        return "not_applicable"
    if spec.get("ToUnicode") is None:
        return "missing"
    return "ambiguous" if ambiguous_cids else "present"


class _CMapLimitError(ValueError):
    pass


class _CMapFilterError(ValueError):
    pass


class _FontObjectLimitReached(PDFException):
    pass


class _CharacterLimitReached(PDFException):
    pass


class _ConflictDetectingUnicodeMap(FileUnicodeMap):
    def __init__(self) -> None:
        super().__init__()
        self.mapping_count = 0
        self.conflicting_cids: set[int] = set()

    def add_cid2unichr(self, cid: int, code: Any) -> None:
        before = self.cid2unichr.get(cid)
        super().add_cid2unichr(cid, code)
        self.mapping_count += 1
        if self.mapping_count > MAX_CMAP_MAPPINGS:
            raise _CMapLimitError("ToUnicode mapping count")
        after = self.cid2unichr.get(cid)
        if before is not None and after != before:
            self.conflicting_cids.add(cid)


def _ambiguous_to_unicode_cids(decoded: bytes) -> frozenset[int]:
    unicode_map = _ConflictDetectingUnicodeMap()
    CMapParser(unicode_map, io.BytesIO(decoded)).run()
    return frozenset(unicode_map.conflicting_cids)


def _bounded_cmap_sizes(
    spec: Mapping[str, Any],
) -> tuple[int, int, bytes] | None:
    if spec.get("ToUnicode") is None:
        return None
    stream = resolve1(spec["ToUnicode"])
    if not isinstance(stream, PDFStream):
        return None
    raw_value = stream.get_rawdata()
    if raw_value is None:
        decoded_value = stream.data
        if not isinstance(decoded_value, bytes):
            raise _CMapFilterError("unavailable ToUnicode stream")
        if len(decoded_value) > MAX_DECODED_CMAP_BYTES:
            raise _CMapLimitError("decoded ToUnicode stream")
        return len(decoded_value), len(decoded_value), decoded_value
    raw = raw_value
    raw_size = len(raw)
    if raw_size > MAX_RAW_CMAP_BYTES:
        raise _CMapLimitError("compressed ToUnicode stream")

    filters = stream.get_filters()
    if not filters:
        decoded = raw
        decoded_size = raw_size
    elif len(filters) == 1 and _safe_name(filters[0][0]) in {
        "FlateDecode",
        "Fl",
    }:
        decompressor = zlib.decompressobj()
        try:
            decoded = decompressor.decompress(
                raw,
                MAX_DECODED_CMAP_BYTES + 1,
            )
        except zlib.error as exc:
            raise _CMapFilterError("invalid Flate ToUnicode stream") from exc
        if (
            len(decoded) > MAX_DECODED_CMAP_BYTES
            or decompressor.unconsumed_tail
            or not decompressor.eof
        ):
            raise _CMapLimitError("decoded ToUnicode stream")
        decoded_size = len(decoded)
    else:
        # Do not let PDFMiner decode an unbounded or unreviewed filter chain.
        raise _CMapFilterError("unsupported ToUnicode filter chain")

    if decoded_size > MAX_DECODED_CMAP_BYTES:
        raise _CMapLimitError("decoded ToUnicode stream")
    return raw_size, decoded_size, decoded


def _inspect_font_spec(
    *,
    font_ref: str,
    object_id: int | None,
    object_identity_basis: Literal[
        "indirect_object",
        "direct_dictionary",
    ],
    to_unicode_ambiguous_cids: frozenset[int],
    spec: Mapping[str, Any],
) -> _FontSpec:
    base_font = _base_font_name(spec.get("BaseFont"))
    embedded, embedded_state = _embedded_program_details(spec)
    cid_to_gid, cid_to_gid_bytes = _cid_to_gid_details(spec)
    return _FontSpec(
        font_ref=font_ref,
        object_id=object_id,
        object_identity_basis=object_identity_basis,
        base_font=base_font,
        subtype=_safe_name(spec.get("Subtype")) or "unknown",
        encoding=_safe_name(spec.get("Encoding")),
        to_unicode=_to_unicode_state(spec, to_unicode_ambiguous_cids),
        to_unicode_ambiguous_cids=to_unicode_ambiguous_cids,
        cid_to_gid=cid_to_gid,
        cid_to_gid_bytes=cid_to_gid_bytes,
        embedded_program=embedded,
        embedded_program_state=embedded_state,
        standard_14=base_font in _STANDARD_14,
    )


def _without_embedded_font_programs(
    spec: Mapping[str, object],
) -> Mapping[str, object]:
    """Return a shallow PDFMiner font spec with font-program entries removed."""

    sanitized = dict(spec)
    try:
        descriptor = resolve1(sanitized.get("FontDescriptor"))
    except Exception:
        descriptor = None
    if isinstance(descriptor, Mapping):
        safe_descriptor = dict(descriptor)
        for key in ("FontFile", "FontFile2", "FontFile3"):
            safe_descriptor.pop(key, None)
        sanitized["FontDescriptor"] = safe_descriptor
    elif "FontDescriptor" in sanitized:
        sanitized["FontDescriptor"] = {}
    return sanitized


class _BoundedResourceManager(PDFResourceManager):
    def __init__(self, *, deadline: float) -> None:
        super().__init__(caching=True)
        self.deadline = deadline
        self.font_specs: dict[str, _FontSpec] = {}
        self.font_refs: dict[int, str] = {}
        self.direct_spec_refs: dict[int, str] = {}
        self.direct_specs: dict[int, Mapping[str, object]] = {}
        self.direct_font_count = 0
        self.font_cache_hit_count = 0
        self.diagnostics: list[FontAuditDiagnostic] = []

    def _diagnose(
        self,
        code: str,
        message: str,
        *,
        font_ref: str | None = None,
        font_object_id: int | None = None,
    ) -> None:
        if len(self.diagnostics) < MAX_DIAGNOSTICS:
            self.diagnostics.append(
                FontAuditDiagnostic(
                    code=code,
                    message=message,
                    font_ref=font_ref,
                    font_object_id=font_object_id,
                )
            )

    def get_font(
        self,
        objid: object,
        spec: Mapping[str, object],
    ) -> PDFFont:
        if time.perf_counter() > self.deadline:
            raise TimeoutError("PDF font audit deadline exceeded")
        subtype = _safe_name(spec.get("Subtype"))
        if objid is None and subtype in {"CIDFontType0", "CIDFontType2"}:
            # PDFMiner recursively constructs a Type0 descendant. Remove
            # FontFile* entries from that construction path so the detection
            # audit never decodes or interprets an embedded font program.
            return super().get_font(
                objid,
                _without_embedded_font_programs(spec),
            )
        integer_id = (
            int(objid)
            if isinstance(objid, int) and not isinstance(objid, bool)
            else None
        )
        if integer_id is not None and integer_id in self._cached_fonts:
            self.font_cache_hit_count += 1

        if integer_id is not None:
            font_ref = f"object:{integer_id}"
            identity_basis: Literal[
                "indirect_object",
                "direct_dictionary",
            ] = "indirect_object"
        else:
            direct_key = id(spec)
            font_ref = self.direct_spec_refs.get(direct_key, "")
            if not font_ref:
                self.direct_font_count += 1
                font_ref = f"direct:{self.direct_font_count}"
                self.direct_spec_refs[direct_key] = font_ref
                self.direct_specs[direct_key] = spec
            identity_basis = "direct_dictionary"

        if font_ref not in self.font_specs:
            if len(self.font_specs) >= MAX_FONT_OBJECTS:
                self._diagnose(
                    "font_object_limit",
                    "Font object inventory reached the audit bound.",
                    font_ref=font_ref,
                    font_object_id=integer_id,
                )
                raise _FontObjectLimitReached(
                    "PDF font audit object limit reached"
                )
            try:
                cmap_sizes = _bounded_cmap_sizes(spec)
                ambiguous_cids = (
                    _ambiguous_to_unicode_cids(cmap_sizes[2])
                    if cmap_sizes is not None
                    else frozenset()
                )
            except _CMapLimitError:
                self._diagnose(
                    "to_unicode_stream_limit",
                    "ToUnicode stream exceeds the audit bound.",
                    font_ref=font_ref,
                    font_object_id=integer_id,
                )
                raise PDFException("ToUnicode stream exceeds audit bound")
            except _CMapFilterError:
                self._diagnose(
                    "to_unicode_filter_unsupported",
                    "ToUnicode stream uses an unsupported filter chain.",
                    font_ref=font_ref,
                    font_object_id=integer_id,
                )
                raise PDFException(
                    "ToUnicode stream filter is unsupported"
                )
            except Exception as exc:
                self._diagnose(
                    "to_unicode_map_malformed",
                    "ToUnicode stream could not be structurally audited.",
                    font_ref=font_ref,
                    font_object_id=integer_id,
                )
                raise PDFException(
                    "ToUnicode stream structure is malformed"
                ) from exc
            self.font_specs[font_ref] = _inspect_font_spec(
                font_ref=font_ref,
                object_id=integer_id,
                object_identity_basis=identity_basis,
                to_unicode_ambiguous_cids=ambiguous_cids,
                spec=spec,
            )

        font = super().get_font(
            objid,
            _without_embedded_font_programs(spec),
        )
        self.font_refs[id(font)] = font_ref
        return font


class _AuditDevice(PDFPageAggregator):
    def __init__(self, resource_manager: _BoundedResourceManager) -> None:
        super().__init__(resource_manager)
        self.resource_manager = resource_manager
        self.page_index = 0
        self.page_bbox = (0.0, 0.0, 0.0, 0.0)
        self.characters: list[_Character] = []
        self.runs: list[_Run] = []
        self._active_run: _Run | None = None
        self.characters_seen = 0
        self.character_limit_reached = False
        self.run_limit_reached = False

    def begin_page(self, page: PDFPage, ctm: tuple[float, ...]) -> None:
        super().begin_page(page, ctm)
        self.page_bbox = tuple(float(value) for value in self.cur_item.bbox)

    def render_string(
        self,
        textstate: PDFTextState,
        seq: Iterable[int | float | bytes],
        ncs: Any,
        graphicstate: PDFGraphicState,
    ) -> None:
        font = textstate.font
        font_ref = (
            self.resource_manager.font_refs.get(id(font))
            if font is not None
            else None
        )
        active = (
            _Run(font_ref=font_ref, page_index=self.page_index)
            if font_ref is not None
            else None
        )
        prior = self._active_run
        self._active_run = active
        try:
            super().render_string(textstate, seq, ncs, graphicstate)
        finally:
            self._active_run = prior
        if active is not None and active.characters:
            if len(self.runs) < MAX_RECORDED_RUNS:
                self.runs.append(active)
            else:
                self.run_limit_reached = True

    def render_char(
        self,
        matrix: tuple[float, float, float, float, float, float],
        font: PDFFont,
        fontsize: float,
        scaling: float,
        rise: float,
        cid: int,
        ncs: Any,
        graphicstate: PDFGraphicState,
    ) -> float:
        font_ref = self.resource_manager.font_refs.get(id(font))
        if font_ref is not None:
            self.characters_seen += 1
            if (
                self.characters_seen == 1
                or self.characters_seen % 256 == 0
            ) and time.perf_counter() > self.resource_manager.deadline:
                raise TimeoutError("PDF font audit deadline exceeded")
            if len(self.characters) >= MAX_RECORDED_CHARACTERS:
                self.character_limit_reached = True
                raise _CharacterLimitReached(
                    "PDF font audit character limit reached"
                )

        try:
            text = font.to_unichr(cid)
            if not isinstance(text, str):
                text = str(text)
        except PDFUnicodeNotDefined:
            text = self.handle_undefined_char(font, cid)
        textwidth = font.char_width(cid)
        textdisp = font.char_disp(cid)
        item = LTChar(
            matrix,
            font,
            fontsize,
            scaling,
            rise,
            text,
            textwidth,
            textdisp,
            ncs,
            graphicstate,
        )
        self.cur_item.add(item)

        if font_ref is not None:
            page_left, _page_bottom, _page_right, page_top = self.page_bbox
            left, bottom, right, top = (
                float(value) for value in item.bbox
            )
            record = _Character(
                font_ref=font_ref,
                page_index=self.page_index,
                cid=int(cid),
                mapped_text=text,
                advance=float(item.adv),
                bbox=(
                    left - page_left,
                    page_top - top,
                    max(right - left, 0.0),
                    max(top - bottom, 0.0),
                ),
                font_width=float(textwidth),
            )
            self.characters.append(record)
            if (
                self._active_run is not None
                and self._active_run.font_ref == font_ref
            ):
                self._active_run.characters.append(record)
        return float(item.adv)


def _is_private_use(value: str) -> bool:
    return any(
        (
            0xE000 <= ord(character) <= 0xF8FF
            or 0xF0000 <= ord(character) <= 0xFFFFD
            or 0x100000 <= ord(character) <= 0x10FFFD
        )
        for character in value
    )


def _is_control(value: str) -> bool:
    return any(
        unicodedata.category(character) == "Cc"
        and character not in {"\t", "\n", "\r"}
        for character in value
    )


def _is_replacement_or_undefined(value: str) -> bool:
    return "\ufffd" in value or value.startswith("(cid:")


def _union_bbox(
    characters: Sequence[_Character],
) -> FontAuditBBox:
    left = min(character.bbox[0] for character in characters)
    top = min(character.bbox[1] for character in characters)
    right = max(
        character.bbox[0] + character.bbox[2]
        for character in characters
    )
    bottom = max(
        character.bbox[1] + character.bbox[3]
        for character in characters
    )
    return FontAuditBBox(
        x=round(left, 3),
        y=round(top, 3),
        width=round(max(right - left, 0.0), 3),
        height=round(max(bottom - top, 0.0), 3),
    )


def _finding_runs(
    runs: Sequence[_Run],
    *,
    font_ref: str,
    affected_cids: set[int] | None,
) -> tuple[list[FontAuditRun], int]:
    output: list[FontAuditRun] = []
    total = 0
    for run in runs:
        if run.font_ref != font_ref:
            continue
        selected = (
            run.characters
            if affected_cids is None
            else [
                character
                for character in run.characters
                if character.cid in affected_cids
            ]
        )
        if not selected:
            continue
        total += 1
        if len(output) < MAX_RUNS_PER_FINDING:
            output.append(
                FontAuditRun(
                    page_index=run.page_index,
                    bbox=_union_bbox(selected),
                    character_count=len(selected),
                    mapped_space_count=sum(
                        character.mapped_text.isspace()
                        for character in selected
                    ),
                    distinct_cids=sorted(
                        {character.cid for character in selected}
                    )[:MAX_CIDS_PER_RECORD],
                )
            )
    return output, total


def _resolved_cid_to_gid_state(
    spec: _FontSpec,
    cids: set[int],
) -> str:
    if spec.cid_to_gid != "stream_unresolved":
        return spec.cid_to_gid
    if not cids:
        return "stream_unresolved"
    mapping = spec.cid_to_gid_bytes
    if mapping is None:
        return "malformed"

    identity = True
    for cid in cids:
        if cid < 0:
            return "malformed"
        offset = cid * 2
        if offset + 2 > len(mapping):
            return "malformed"
        glyph_id = int.from_bytes(mapping[offset : offset + 2], "big")
        if glyph_id != cid:
            identity = False
    return "identity" if identity else "non_identity"


def _classify_font(
    spec: _FontSpec,
    characters: Sequence[_Character],
    runs: Sequence[_Run],
) -> tuple[FontInventoryRecord, FontAuditFinding | None]:
    used = len(characters)
    cids = {character.cid for character in characters}
    cid_to_gid = _resolved_cid_to_gid_state(spec, cids)
    space_characters = [
        character
        for character in characters
        if character.mapped_text.isspace()
    ]
    space_cids = {character.cid for character in space_characters}
    replacement_count = sum(
        _is_replacement_or_undefined(character.mapped_text)
        for character in characters
    )
    private_use_count = sum(
        _is_private_use(character.mapped_text)
        for character in characters
    )
    control_count = sum(
        _is_control(character.mapped_text)
        for character in characters
    )
    positive_advance_spaces = sum(
        character.advance > 1e-6 for character in space_characters
    )
    reason_codes: list[str] = []
    affected_cids: set[int] | None = set()
    health: Literal["suspicious", "unresolved"] | None = None

    ambiguous_used_cids = set(spec.to_unicode_ambiguous_cids) & cids
    if ambiguous_used_cids:
        health = "unresolved"
        reason_codes.append("to_unicode_ambiguous")
        affected_cids.update(ambiguous_used_cids)
    if used and cid_to_gid in {"malformed", "unsupported"}:
        health = "unresolved"
        reason_codes.append(f"cid_to_gid_{cid_to_gid}")
        affected_cids = None
    if used and spec.embedded_program_state in {"dangling", "non_stream"}:
        health = "unresolved"
        reason_codes.append(
            f"embedded_program_{spec.embedded_program_state}"
        )
        affected_cids = None

    missing_type0_map = (
        used
        and spec.subtype == "Type0"
        and spec.to_unicode == "missing"
    )
    if missing_type0_map:
        # Undefined replacement text is expected when the map is absent. It is
        # unresolved structural evidence, not proof that the source mapping is
        # actively wrong.
        health = "unresolved"
        reason_codes.append("to_unicode_missing")
        affected_cids = None
    else:
        collapsed_space = (
            len(space_characters) >= MIN_COLLAPSED_SPACE_USES
            and len(space_cids) >= MIN_COLLAPSED_SPACE_CIDS
            and len(space_characters) / max(used, 1)
            >= MIN_COLLAPSED_SPACE_RATIO
        )
        if collapsed_space:
            health = "suspicious"
            reason_codes.append("many_to_one_space_mapping")
            if affected_cids is not None:
                affected_cids.update(space_cids)
            if positive_advance_spaces >= MIN_COLLAPSED_SPACE_USES:
                reason_codes.append("positive_advance_space_mapping")

        anomaly_floor = max(2, math.ceil(used * 0.1))
        if used and replacement_count >= anomaly_floor:
            health = "suspicious"
            reason_codes.append("replacement_or_undefined_mapping")
            if affected_cids is not None:
                affected_cids.update(
                    character.cid
                    for character in characters
                    if _is_replacement_or_undefined(character.mapped_text)
                )
        if used and private_use_count >= max(3, math.ceil(used * 0.25)):
            health = "suspicious"
            reason_codes.append("private_use_mapping")
            if affected_cids is not None:
                affected_cids.update(
                    character.cid
                    for character in characters
                    if _is_private_use(character.mapped_text)
                )
        if used and control_count >= anomaly_floor:
            health = "suspicious"
            reason_codes.append("control_character_mapping")
            if affected_cids is not None:
                affected_cids.update(
                    character.cid
                    for character in characters
                    if _is_control(character.mapped_text)
                )

    classification = (
        health if health is not None else ("healthy" if used else "unused")
    )
    page_indexes = sorted(
        {character.page_index for character in characters}
    )
    inventory = FontInventoryRecord(
        font_ref=spec.font_ref,
        font_object_id=spec.object_id,
        object_identity_basis=spec.object_identity_basis,
        base_font=spec.base_font,
        subtype=spec.subtype,
        encoding=spec.encoding,
        to_unicode=spec.to_unicode,
        cid_to_gid=cid_to_gid,
        embedded_program=spec.embedded_program,
        embedded_program_state=spec.embedded_program_state,
        standard_14=spec.standard_14,
        classification=classification,
        page_indexes=page_indexes,
        used_character_count=used,
        distinct_used_cids=len(cids),
        mapped_space_count=len(space_characters),
        distinct_space_mapped_cids=len(space_cids),
        replacement_or_undefined_count=replacement_count,
        private_use_count=private_use_count,
        control_count=control_count,
        positive_advance_space_count=positive_advance_spaces,
    )
    if health is None:
        return inventory, None

    finding_runs, finding_run_count = _finding_runs(
        runs,
        font_ref=spec.font_ref,
        affected_cids=affected_cids,
    )
    finding = FontAuditFinding(
        health=health,
        font_ref=spec.font_ref,
        font_object_id=spec.object_id,
        object_identity_basis=spec.object_identity_basis,
        base_font=spec.base_font,
        subtype=spec.subtype,
        page_indexes=page_indexes,
        reason_codes=reason_codes,
        confidence_basis={
            "used_character_count": used,
            "distinct_used_cids": len(cids),
            "mapped_space_count": len(space_characters),
            "distinct_space_mapped_cids": len(space_cids),
            "positive_advance_space_count": positive_advance_spaces,
            "replacement_or_undefined_count": replacement_count,
            "private_use_count": private_use_count,
            "control_count": control_count,
            "to_unicode": spec.to_unicode,
            "to_unicode_ambiguous_cid_count": len(
                spec.to_unicode_ambiguous_cids
            ),
            "to_unicode_ambiguous_used_cids": sorted(
                ambiguous_used_cids
            )[:MAX_CIDS_PER_RECORD],
            "cid_to_gid": cid_to_gid,
            "embedded_program": spec.embedded_program,
            "embedded_program_state": spec.embedded_program_state,
        },
        run_count=finding_run_count,
        runs_truncated=finding_run_count > len(finding_runs),
        runs=finding_runs,
    )
    return inventory, finding


def _unavailable(
    code: str,
    message: str,
    *,
    source_sha256: str | None = None,
) -> FontAuditReport:
    return FontAuditReport(
        source_sha256=source_sha256,
        status="unavailable",
        fonts_inspected=0,
        font_cache_hit_count=0,
        pages_inspected=0,
        characters_inspected=0,
        fonts=[],
        findings=[],
        diagnostics=[FontAuditDiagnostic(code=code, message=message)],
    )


def audit_pdf_fonts(pdf_bytes: bytes) -> FontAuditReport:
    """Inspect used PDF fonts without changing text or retaining font bytes."""

    if not isinstance(pdf_bytes, bytes):
        return _unavailable(
            "invalid_input_type",
            "Font audit requires immutable PDF bytes.",
        )
    source_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    if not pdf_bytes:
        return _unavailable(
            "empty_pdf",
            "Font audit received an empty PDF.",
            source_sha256=source_sha256,
        )
    if len(pdf_bytes) > MAX_INPUT_BYTES:
        return _unavailable(
            "pdf_size_limit",
            "PDF exceeds the font-audit input bound.",
            source_sha256=source_sha256,
        )

    resource_manager = _BoundedResourceManager(
        deadline=time.perf_counter() + MAX_AUDIT_SECONDS
    )
    device = _AuditDevice(resource_manager)
    pages_inspected = 0
    diagnostics: list[FontAuditDiagnostic] = []
    try:
        stream = io.BytesIO(pdf_bytes)
        document = PDFDocument(PDFParser(stream), caching=True)
        interpreter = PDFPageInterpreter(resource_manager, device)
        for page_index, page in enumerate(PDFPage.create_pages(document), 1):
            if time.perf_counter() > resource_manager.deadline:
                diagnostics.append(
                    FontAuditDiagnostic(
                        code="audit_timeout",
                        message="PDF font audit exceeded its time bound.",
                    )
                )
                break
            if page_index > MAX_PAGES:
                diagnostics.append(
                    FontAuditDiagnostic(
                        code="page_limit",
                        message="PDF page count exceeds the audit bound.",
                    )
                )
                break
            device.page_index = page_index
            try:
                interpreter.process_page(page)
                pages_inspected += 1
            except (_CharacterLimitReached, _FontObjectLimitReached):
                # The corresponding bounded diagnostic is retained below or
                # by the resource manager. Do not process more untrusted data.
                break
            except Exception as exc:
                diagnostics.append(
                    FontAuditDiagnostic(
                        code=(
                            "audit_timeout"
                            if isinstance(exc, TimeoutError)
                            else "page_audit_failed"
                        ),
                        message=(
                            (
                                "PDF font audit exceeded its time bound."
                                if isinstance(exc, TimeoutError)
                                else (
                                    "Font audit could not inspect one page: "
                                    f"{type(exc).__name__}."
                                )
                            )
                        ),
                        page_index=page_index,
                    )
                )
                if pages_inspected == 0:
                    break
    except Exception as exc:
        return _unavailable(
            "pdf_audit_failed",
            f"Font audit could not open the PDF: {type(exc).__name__}.",
            source_sha256=source_sha256,
        )
    finally:
        device.close()

    if device.character_limit_reached:
        diagnostics.append(
            FontAuditDiagnostic(
                code="character_limit",
                message="Character evidence exceeded the audit bound.",
            )
        )
    if device.run_limit_reached:
        diagnostics.append(
            FontAuditDiagnostic(
                code="run_limit",
                message="Run evidence exceeded the audit bound.",
            )
        )
    diagnostics.extend(resource_manager.diagnostics)
    diagnostics = diagnostics[:MAX_DIAGNOSTICS]

    by_font: dict[str, list[_Character]] = defaultdict(list)
    for character in device.characters:
        by_font[character.font_ref].append(character)

    fonts: list[FontInventoryRecord] = []
    findings: list[FontAuditFinding] = []
    for font_ref, spec in resource_manager.font_specs.items():
        inventory, finding = _classify_font(
            spec,
            by_font.get(font_ref, []),
            device.runs,
        )
        fonts.append(inventory)
        if finding is not None:
            findings.append(finding)

    status: Literal["complete", "partial", "unavailable"] = (
        "partial" if diagnostics else "complete"
    )
    if (
        pages_inspected == 0
        and diagnostics
        and not fonts
        and not device.characters
    ):
        status = "unavailable"
    return FontAuditReport(
        source_sha256=source_sha256,
        status=status,
        fonts_inspected=len(fonts),
        font_cache_hit_count=resource_manager.font_cache_hit_count,
        pages_inspected=pages_inspected,
        characters_inspected=len(device.characters),
        fonts=fonts,
        findings=findings,
        diagnostics=diagnostics,
    )
