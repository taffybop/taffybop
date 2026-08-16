"""Bounded, source-only PDF text alignment.

This module deliberately has no feature-flag or application-settings
dependency.  A caller must opt in before invoking it.  It extracts character
evidence from the uploaded PDF, applies only the closed source transformations
documented by ``P02-source-text-alignment-policy.md``, and transactionally
aligns already-normalized page owners to that evidence.

No rule in this module branches on a filename, document hash, page number,
phrase, language model, dictionary, or benchmark fixture.
"""

from __future__ import annotations

import copy
import csv
import ctypes
import hashlib
import html
import io
import json
import math
import re
import statistics
import time
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from json.encoder import encode_basestring
from typing import Any, Literal

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
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
from pdfminer.pdftypes import list_value, resolve1
from pdfminer.psparser import literal_name


SOURCE_TEXT_ALIGNMENT_SCHEMA_VERSION = "1.0"
SOURCE_TEXT_ALIGNMENT_POLICY_ID = "p02-source-text-alignment-v1"
TABLE_OWNED_SUPPLEMENTAL_POLICY_ID = (
    "p02-table-owned-supplemental-reconciliation-v1"
)
TABLE_OWNED_SUPPLEMENTAL_REASON = (
    "table_owned_complete_source_line_duplicate"
)
TABLE_OWNED_ROTATED_CELL_POLICY_ID = (
    "p02-table-owned-rotated-cell-reconciliation-v1"
)
TABLE_OWNED_ROTATED_CELL_REASON = (
    "table_owned_rotated_source_glyph_cell_duplicate"
)
SELECTED_VECTOR_REPRESENTATION_POLICY_ID = (
    "p02-selected-vector-representation-reconciliation-v1"
)
SELECTED_VECTOR_REPRESENTATION_REASON = (
    "selected_vector_source_owned_table_duplicate"
)
TABLE_OWNED_TERMINAL_REASONS = frozenset(
    {
        TABLE_OWNED_SUPPLEMENTAL_REASON,
        TABLE_OWNED_ROTATED_CELL_REASON,
    }
)
SUPPLEMENTAL_OCR_CONTRIBUTOR_SCHEMA_VERSION = "1.0"
SUPPLEMENTAL_OCR_CONTRIBUTOR_POLICY_ID = (
    "p02-supplemental-ocr-contributor-v1"
)
SUPPLEMENTAL_PDF_PAGE_ORIGINS = frozenset(
    {"pdf_embedded", "pdf_page_render"}
)
_PROMOTED_SUPPLEMENTAL_HEADING_CONCERNS = (
    "layout_omission_recovered_by_ocr",
    "heading_inferred_from_image_geometry",
)

MAX_INPUT_BYTES = 25 * 1024 * 1024
MAX_PAGES = 100
MAX_FONT_OBJECTS = 256
MAX_SOURCE_CHARACTERS = 500_000
MAX_SOURCE_RUNS = 10_000
MAX_DIFFERENCES_PER_FONT = 256
MAX_DIFFERENCE_ENTRIES = 4_096
MAX_GLYPH_NAME_BYTES = 64
MAX_PDF_NAMES_INSPECTED = 200_000
MAX_TYPE1_OCCURRENCES = 100_000
MAX_PAGE_OBJECTS = 100_000
MAX_OWNERS = 512
MAX_TABLE_OWNED_SUPPLEMENTAL_OWNERS = 1_024
MAX_SELECTED_VECTOR_OWNERS = 2_048
MAX_TOTAL_ALIGNMENT_OWNERS = (
    MAX_OWNERS
    + MAX_TABLE_OWNED_SUPPLEMENTAL_OWNERS
    + MAX_SELECTED_VECTOR_OWNERS
)
MAX_SCANNED_OWNERS = 10_000
MAX_CANDIDATES_PER_OWNER = 8
MAX_TOTAL_CANDIDATES = 2_048
MAX_CANDIDATE_CODEPOINTS = 4_096
MAX_EVIDENCE_REFS = 64
MAX_SELECTIONS = 512
MAX_TABLE_OWNED_SUPPLEMENTAL_SELECTIONS = 1_024
MAX_SELECTED_VECTOR_SELECTIONS = 2_048
MAX_TOTAL_ALIGNMENT_SELECTIONS = (
    MAX_SELECTIONS
    + MAX_TABLE_OWNED_SUPPLEMENTAL_SELECTIONS
    + MAX_SELECTED_VECTOR_SELECTIONS
)
MAX_CONCERNS = 512
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_ALIGNMENT_SECONDS = 2.0
MAX_SELECTED_VECTOR_ALIGNMENT_SECONDS = 3.0
MAX_SELECTED_VECTOR_TABLES = 128
MAX_SELECTED_VECTOR_SLOTS = 10_000
MAX_SELECTED_VECTOR_GROUPS = 512
MAX_SELECTED_VECTOR_MEMBERS_PER_GROUP = 256
MAX_SELECTED_VECTOR_CANDIDATES = 4_096
MAX_SELECTED_VECTOR_ROW_COMPARISONS = 250_000
MAX_SELECTED_VECTOR_CHARACTER_COMPARISONS = 2_000_000

MIN_OCR_RECIPROCAL_OVERLAP = 0.80
MIN_TYPE1_RECIPROCAL_OVERLAP = 0.70

_SAFE_TYPE1_GLYPHS = {
    **{f"{name}.numr": digit for name, digit in zip(
        (
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
        ),
        "0123456789",
        strict=True,
    )},
    "f_i": "fi",
    "f_l": "fl",
}
_SAFE_TYPE1_NAME_BYTES = frozenset(
    name.encode("ascii") for name in _SAFE_TYPE1_GLYPHS
)
_UNSAFE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})
_WHITESPACE_RE = re.compile(r"\s+")
_NATIVE_RUN_BOUNDARY_PUNCTUATION = frozenset({",", ".", ";", ":", "!", "?"})
_TEXT_ALIGNMENT_OWNER_TYPES = frozenset(
    {"text", "heading", "code", "formula", "header", "footer"}
)
_SOURCE_SPACE_ONLY_OWNER_TYPES = frozenset({"header", "footer"})
_PDF_NAME_RE = re.compile(
    rb"/([^\x00\t\n\f\r ()<>\[\]{}/%]+)"
)
_PDF_HEX_BYTES = frozenset(b"0123456789abcdefABCDEF")


class _Refusal(RuntimeError):
    """Internal fail-closed terminal."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _json_safe(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {
            str(name): _json_safe(getattr(value, name))
            for name in value.__dataclass_fields__
        }
    if isinstance(value, Mapping):
        return {str(key): _json_safe(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(child) for child in value]
    return value


def _dataclass_json_default(value: Any) -> dict[str, Any]:
    """Expose frozen slot dataclasses directly to the JSON encoder.

    Report-bound checks only need the exact encoded byte count.  Letting the
    encoder traverse the immutable evidence tree avoids materializing a
    second, multi-megabyte recursive copy before encoding it.
    """

    fields = getattr(value, "__dataclass_fields__", None)
    if fields is None:
        raise TypeError(
            f"Object of type {type(value).__name__} is not JSON serializable"
        )
    return {
        str(name): getattr(value, name)
        for name in fields
    }


@dataclass(frozen=True, slots=True)
class SourceBBox:
    x: float
    y: float
    width: float
    height: float
    unit: Literal["pt"] = "pt"

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(self)


@dataclass(frozen=True, slots=True)
class Type1GlyphEvidence:
    id: str
    page_index: int
    bbox: SourceBBox
    font_ref: str
    font_object_id: int | None
    cid: int
    glyph_name: str
    original_text: str
    recovered_text: str
    role: Literal["superscript", "ligature"]
    method: Literal["type1_encoding_differences"] = (
        "type1_encoding_differences"
    )

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(self)


@dataclass(frozen=True, slots=True)
class SourceCharacterEvidence:
    id: str
    page_index: int
    character_index: int
    raw_code_point: int
    raw_text: str
    text: str
    bbox: SourceBBox | None
    fill_rgba: tuple[int, int, int, int] | None
    font_ref: str | None
    font_size: float | None
    baseline: float | None
    pdfium_is_hyphen: bool
    space_supported: bool
    excluded_reason: str | None
    type1_evidence_ids: tuple[str, ...] = ()
    corroborating_line_ids: tuple[str, ...] = ()
    role: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(self)


@dataclass(frozen=True, slots=True)
class SourceTextLine:
    id: str
    page_index: int
    text: str
    raw_text: str
    bbox: SourceBBox
    source_character_ids: tuple[str, ...]
    source_character_indexes: tuple[int, ...]
    type1_evidence_ids: tuple[str, ...]
    has_unsafe_character: bool
    terminal_semantic_hyphen: bool

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(self)


@dataclass(frozen=True, slots=True)
class SourcePageEvidence:
    page_index: int
    page_width: float
    page_height: float
    unit: Literal["pt"]
    characters: tuple[SourceCharacterEvidence, ...]
    lines: tuple[SourceTextLine, ...]

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(self)


@dataclass(frozen=True, slots=True)
class SourceTextEvidence:
    schema_version: str
    policy_id: str
    source_sha256: str
    usable: bool
    refusal_code: str | None
    page_count: int
    character_count: int
    line_count: int
    type1_glyph_count: int
    pages: tuple[SourcePageEvidence, ...]
    type1_glyphs: tuple[Type1GlyphEvidence, ...]
    diagnostics: tuple[dict[str, Any], ...]
    elapsed_ms: float

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(self)


@dataclass(frozen=True, slots=True)
class SourceTextSelection:
    text: str
    raw_text: str
    bbox: SourceBBox
    source_line_ids: tuple[str, ...]
    source_character_ids: tuple[str, ...]
    source_character_indexes: tuple[int, ...]
    type1_evidence_ids: tuple[str, ...]
    source_roles: tuple[dict[str, Any], ...]
    checks: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(self)


@dataclass(frozen=True, slots=True)
class AlignmentSelection:
    id: str
    page_index: int
    owner_id: str
    owner_type: str
    owner_bbox: dict[str, Any]
    original_text: str
    selected_text: str
    selected_source: str
    source_line_ids: tuple[str, ...]
    source_character_ids: tuple[str, ...]
    type1_mapping_ids: tuple[str, ...]
    source_roles: tuple[dict[str, Any], ...]
    method: str
    checks: dict[str, bool]
    terminal_reason: str
    rejected_ocr_alternative: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(self)


@dataclass(frozen=True, slots=True)
class SourceAlignmentSummary:
    schema_version: str
    policy_id: str
    source_sha256: str
    status: str
    considered_count: int
    selected_count: int
    unchanged_count: int
    unresolved_count: int
    selections: tuple[AlignmentSelection, ...]
    concerns: tuple[dict[str, Any], ...]
    elapsed_ms: float

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(self)


@dataclass(frozen=True, slots=True)
class _TableOwnedSourceLineMatch:
    page_index: int
    table_item_id: str
    table_id: str
    candidate_id: str
    table_order: int
    row_index: int
    cell_ids: tuple[str, ...]
    source_object_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    table_bbox: SourceBBox
    row_bbox: SourceBBox
    source_line_bbox: SourceBBox

    def canonical_owner(self) -> dict[str, Any]:
        return {
            "policy_id": TABLE_OWNED_SUPPLEMENTAL_POLICY_ID,
            "suppression_reason": TABLE_OWNED_SUPPLEMENTAL_REASON,
            "page_index": self.page_index,
            "coordinate_unit": "pt",
            "table_item_id": self.table_item_id,
            "table_id": self.table_id,
            "candidate_id": self.candidate_id,
            "table_order": self.table_order,
            "row_index": self.row_index,
            "cell_ids": list(self.cell_ids),
            "source_object_ids": list(self.source_object_ids),
            "evidence_ids": list(self.evidence_ids),
            "table_bbox": self.table_bbox.to_dict(),
            "row_bbox": self.row_bbox.to_dict(),
            "source_line_bbox": self.source_line_bbox.to_dict(),
            "content_coverage": 1.0,
            "source_character_geometry_coverage": 1.0,
        }


@dataclass(frozen=True, slots=True)
class _TableOwnedStructuralLineCandidate:
    match: _TableOwnedSourceLineMatch
    cell_boxes: tuple[SourceBBox, ...]


@dataclass(slots=True)
class _TableOwnedStructuralLineCache:
    values: dict[
        tuple[int, str],
        tuple[_TableOwnedStructuralLineCandidate, ...],
    ] = field(default_factory=dict)
    candidate_count: int = 0

    def store(
        self,
        key: tuple[int, str],
        candidates: tuple[_TableOwnedStructuralLineCandidate, ...],
    ) -> None:
        if key in self.values:
            raise _Refusal(
                "source_alignment_table_owned_cache_identity_conflict"
            )
        if len(self.values) >= MAX_TABLE_OWNED_SUPPLEMENTAL_OWNERS:
            raise _Refusal("source_alignment_table_owned_cache_key_limit")
        next_count = self.candidate_count + len(candidates)
        if next_count > MAX_SCANNED_OWNERS:
            raise _Refusal(
                "source_alignment_table_owned_cache_candidate_limit"
            )
        self.values[key] = candidates
        self.candidate_count = next_count


@dataclass(frozen=True, slots=True)
class _TableOwnedCellAuthority:
    page_index: int
    table_item_id: str
    table_id: str
    candidate_id: str
    table_order: int
    row_index: int
    column_index: int
    cell_id: str
    source_object_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    table_bbox: SourceBBox
    cell_bbox: SourceBBox
    cell_text: str


@dataclass(frozen=True, slots=True)
class _TableOwnedSourceCellMatch:
    authority: _TableOwnedCellAuthority
    source_selection_bbox: SourceBBox

    def canonical_owner(self) -> dict[str, Any]:
        authority = self.authority
        return {
            "policy_id": TABLE_OWNED_ROTATED_CELL_POLICY_ID,
            "suppression_reason": TABLE_OWNED_ROTATED_CELL_REASON,
            "ownership_kind": "canonical_table_cell",
            "page_index": authority.page_index,
            "coordinate_unit": "pt",
            "table_item_id": authority.table_item_id,
            "table_id": authority.table_id,
            "candidate_id": authority.candidate_id,
            "table_order": authority.table_order,
            "row_index": authority.row_index,
            "column_index": authority.column_index,
            "cell_id": authority.cell_id,
            "source_object_ids": list(authority.source_object_ids),
            "evidence_ids": list(authority.evidence_ids),
            "table_bbox": authority.table_bbox.to_dict(),
            "cell_bbox": authority.cell_bbox.to_dict(),
            "source_selection_bbox": self.source_selection_bbox.to_dict(),
            "glyph_multiset_coverage": 1.0,
            "source_character_geometry_coverage": 1.0,
        }


@dataclass(slots=True)
class _TableOwnedCellAuthorityCache:
    values: dict[int, tuple[_TableOwnedCellAuthority, ...]] = field(
        default_factory=dict
    )
    authority_count: int = 0

    def store(
        self,
        page_index: int,
        authorities: tuple[_TableOwnedCellAuthority, ...],
    ) -> None:
        if page_index in self.values:
            raise _Refusal(
                "source_alignment_table_owned_cell_cache_identity_conflict"
            )
        if len(self.values) >= MAX_PAGES:
            raise _Refusal(
                "source_alignment_table_owned_cell_cache_page_limit"
            )
        next_count = self.authority_count + len(authorities)
        if next_count > MAX_SCANNED_OWNERS:
            raise _Refusal(
                "source_alignment_table_owned_cell_cache_authority_limit"
            )
        self.values[page_index] = authorities
        self.authority_count = next_count


@dataclass(frozen=True, slots=True)
class _SelectedVectorRowProof:
    page_index: int
    representation: dict[str, Any]
    table_item_position: int
    table_item_id: str
    table_reading_order: int
    row_index: int
    row_bbox: SourceBBox
    cell_bboxes: tuple[SourceBBox, ...]
    cell_texts: tuple[str, ...]
    cell_source_closed: tuple[bool, ...]
    cell_source_characters: tuple[
        tuple[SourceCharacterEvidence, ...], ...
    ]
    row_text_closed: bool
    source_line: SourceTextLine
    source_characters: tuple[SourceCharacterEvidence, ...]

    def group_key(self) -> tuple[Any, ...]:
        return (
            self.representation["source_sha256"],
            self.page_index,
            self.representation["terminal_authority_sha256"],
            self.representation["candidate_id"],
            self.row_index,
            self.source_line.id,
            "source_row",
        )

    def cell_group_key(self, column_index: int) -> tuple[Any, ...]:
        return (
            self.representation["source_sha256"],
            self.page_index,
            self.representation["terminal_authority_sha256"],
            self.representation["candidate_id"],
            self.row_index,
            column_index,
            "source_cell",
        )


@dataclass(frozen=True, slots=True)
class _SelectedVectorMember:
    page_index: int
    item_position: int
    item_snapshot: dict[str, Any]
    owner_box: SourceBBox
    selection: SourceTextSelection
    proof: _SelectedVectorRowProof
    source_range: tuple[int, int]
    ownership_mode: str
    cell_index: int | None = None
    omitted_source_character_id: str | None = None
    omitted_offset: int | None = None
    omitted_category: str | None = None


@dataclass(frozen=True, slots=True)
class _SelectedVectorRotatedMember:
    page_index: int
    item_position: int
    item_snapshot: dict[str, Any]
    owner_box: SourceBBox
    selection: SourceTextSelection
    representation: dict[str, Any]
    table_item_position: int
    table_item_id: str
    table_reading_order: int
    row_index: int
    column_index: int
    cell_bbox: SourceBBox
    cell_source_character_ids: tuple[str, ...]
    ownership_mode: str

    def group_key(self) -> tuple[Any, ...]:
        return (
            self.representation["source_sha256"],
            self.page_index,
            self.representation["terminal_authority_sha256"],
            self.representation["candidate_id"],
            self.row_index,
            self.column_index,
            "source_cell",
        )


_JSON_STRING_CHUNK_CODEPOINTS = 16_384


def _is_bounded_atomic_json_record(value: Any) -> bool:
    if isinstance(value, SourceBBox):
        return (
            value.unit == "pt"
            and all(
                isinstance(part, (int, float))
                and not isinstance(part, bool)
                and math.isfinite(float(part))
                for part in (
                    value.x,
                    value.y,
                    value.width,
                    value.height,
                )
            )
        )
    if not isinstance(value, SourceCharacterEvidence):
        return False
    return (
        isinstance(value.page_index, int)
        and not isinstance(value.page_index, bool)
        and isinstance(value.character_index, int)
        and not isinstance(value.character_index, bool)
        and isinstance(value.raw_code_point, int)
        and not isinstance(value.raw_code_point, bool)
        and 0 <= value.raw_code_point <= 0x10FFFF
        and isinstance(value.id, str)
        and isinstance(value.raw_text, str)
        and isinstance(value.text, str)
        and (
            value.bbox is None
            or _is_bounded_atomic_json_record(value.bbox)
        )
        and (
            value.fill_rgba is None
            or (
                isinstance(value.fill_rgba, tuple)
                and len(value.fill_rgba) == 4
                and all(
                    isinstance(channel, int)
                    and not isinstance(channel, bool)
                    and 0 <= channel <= 255
                    for channel in value.fill_rgba
                )
            )
        )
        and (
            value.font_ref is None
            or isinstance(value.font_ref, str)
        )
        and (
            value.font_size is None
            or (
                isinstance(value.font_size, (int, float))
                and not isinstance(value.font_size, bool)
                and math.isfinite(float(value.font_size))
            )
        )
        and (
            value.baseline is None
            or (
                isinstance(value.baseline, (int, float))
                and not isinstance(value.baseline, bool)
                and math.isfinite(float(value.baseline))
            )
        )
        and (
            value.excluded_reason is None
            or isinstance(value.excluded_reason, str)
        )
        and (
            value.role is None
            or isinstance(value.role, str)
        )
        and isinstance(value.type1_evidence_ids, tuple)
        and isinstance(value.corroborating_line_ids, tuple)
        and len(value.id) <= 128
        and len(value.raw_text) <= 2
        and len(value.text) <= 2
        and len(value.font_ref or "") <= 128
        and len(value.excluded_reason or "") <= 128
        and len(value.role or "") <= 128
        and len(value.type1_evidence_ids) <= MAX_EVIDENCE_REFS
        and len(value.corroborating_line_ids) <= MAX_EVIDENCE_REFS
        and all(
            isinstance(reference, str)
            and len(reference) <= 128
            for reference in (
                *value.type1_evidence_ids,
                *value.corroborating_line_ids,
            )
        )
    )


def _bounded_json_size(
    value: Any,
    *,
    max_bytes: int,
    deadline: float,
    refusal_code: str = "source_alignment_report_size_limit",
) -> int:
    """Return the exact compact UTF-8 JSON size without a full report copy.

    The counter uses the same string escaping and float spelling as Python's
    public ``json.dumps(..., ensure_ascii=False, separators=(",", ":"))``
    contract. Containers and long strings are traversed incrementally. The
    running count rejects immediately above ``max_bytes`` and polls the
    aggregate deadline throughout traversal.
    """

    if (
        not isinstance(max_bytes, int)
        or isinstance(max_bytes, bool)
        or max_bytes < 0
        or not isinstance(deadline, (int, float))
        or isinstance(deadline, bool)
        or not math.isfinite(float(deadline))
    ):
        raise ValueError("invalid bounded JSON size arguments")

    total = 0
    visited = 0

    def add(size: int) -> None:
        nonlocal total
        total += size
        if total > max_bytes:
            raise _Refusal(refusal_code)

    def poll() -> None:
        nonlocal visited
        visited += 1
        if (
            visited % 256 == 0
            and time.perf_counter() > deadline
        ):
            raise _Refusal("source_alignment_deadline")

    def visit_string(text: str) -> None:
        add(2)
        for offset in range(
            0,
            len(text),
            _JSON_STRING_CHUNK_CODEPOINTS,
        ):
            poll()
            encoded = encode_basestring(
                text[offset : offset + _JSON_STRING_CHUNK_CODEPOINTS]
            ).encode("utf-8")
            # Each independently encoded chunk has one leading and trailing
            # quote; string escaping is otherwise context-independent.
            add(len(encoded) - 2)

    def visit(child: Any) -> None:
        poll()
        if _is_bounded_atomic_json_record(child):
            encoded = json.dumps(
                child,
                default=_dataclass_json_default,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            add(len(encoded))
            return
        fields = getattr(child, "__dataclass_fields__", None)
        if fields is not None:
            add(1)
            for field_index, name in enumerate(fields):
                if field_index:
                    add(1)
                visit_string(str(name))
                add(1)
                visit(getattr(child, name))
            add(1)
            return
        if isinstance(child, Mapping):
            add(1)
            for item_index, (key, mapped) in enumerate(child.items()):
                if not isinstance(key, str):
                    raise _Refusal(
                        "source_alignment_report_key_invalid"
                    )
                if item_index:
                    add(1)
                visit_string(key)
                add(1)
                visit(mapped)
            add(1)
            return
        if isinstance(child, (tuple, list)):
            add(1)
            for item_index, item in enumerate(child):
                if item_index:
                    add(1)
                visit(item)
            add(1)
            return
        if isinstance(child, str):
            visit_string(child)
            return
        if child is None:
            add(4)
            return
        if isinstance(child, bool):
            add(4 if child else 5)
            return
        if isinstance(child, int):
            add(len(str(child)))
            return
        if isinstance(child, float):
            if math.isnan(child):
                add(3)
            elif child == math.inf or child == -math.inf:
                add(9 if child < 0 else 8)
            else:
                add(len(float.__repr__(child)))
            return
        raise _Refusal("source_alignment_report_value_invalid")

    visit(value)
    if time.perf_counter() > deadline:
        raise _Refusal("source_alignment_deadline")
    return total


@dataclass(slots=True)
class _RawCharacter:
    page_index: int
    character_index: int
    raw_code_point: int
    raw_text: str
    text: str
    bbox: SourceBBox | None
    fill_rgba: tuple[int, int, int, int] | None
    font_ref: str | None
    font_size: float | None
    baseline: float | None
    text_object_ref: str | None
    pdfium_is_hyphen: bool
    hard_break_before: bool = False
    space_supported: bool = False
    excluded_reason: str | None = None
    type1_evidence_ids: list[str] = field(default_factory=list)
    corroborating_line_ids: list[str] = field(default_factory=list)
    role: str | None = None
    id: str = ""


def _finite_positive(value: float) -> bool:
    return math.isfinite(value) and value > 0


def _bbox_from_pdfium(
    raw: Sequence[float],
    page_width: float,
    page_height: float,
    rotation: int = 0,
) -> SourceBBox | None:
    try:
        left, bottom, right, top = (float(value) for value in raw)
    except (TypeError, ValueError):
        return None
    values = (left, bottom, right, top, page_width, page_height)
    if not all(math.isfinite(value) for value in values):
        return None
    raw_width = right - left
    raw_height = top - bottom
    if raw_width <= 0 or raw_height <= 0:
        return None
    rotation = int(rotation) % 360
    if rotation == 0:
        x = left
        y = page_height - top
        width = raw_width
        height = raw_height
    elif rotation == 90:
        x = bottom
        y = left
        width = raw_height
        height = raw_width
    elif rotation == 180:
        x = page_width - right
        y = bottom
        width = raw_width
        height = raw_height
    elif rotation == 270:
        x = page_width - top
        y = page_height - right
        width = raw_height
        height = raw_width
    else:
        return None
    return SourceBBox(
        x=round(x, 6),
        y=round(y, 6),
        width=round(width, 6),
        height=round(height, 6),
    )


def _bbox_from_pdfminer(
    raw: Sequence[float],
    page_left: float,
    page_top: float,
) -> SourceBBox | None:
    try:
        left, bottom, right, top = (float(value) for value in raw)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (left, bottom, right, top)):
        return None
    if right <= left or top <= bottom:
        return None
    return SourceBBox(
        x=round(left - page_left, 6),
        y=round(page_top - top, 6),
        width=round(right - left, 6),
        height=round(top - bottom, 6),
    )


def _bbox_union(boxes: Iterable[SourceBBox | None]) -> SourceBBox | None:
    valid = [box for box in boxes if box is not None]
    if not valid:
        return None
    left = min(box.x for box in valid)
    top = min(box.y for box in valid)
    right = max(box.x + box.width for box in valid)
    bottom = max(box.y + box.height for box in valid)
    return SourceBBox(
        x=round(left, 6),
        y=round(top, 6),
        width=round(right - left, 6),
        height=round(bottom - top, 6),
    )


def _area(box: SourceBBox | None) -> float:
    return box.width * box.height if box is not None else 0.0


def _intersection_area(first: SourceBBox, second: SourceBBox) -> float:
    return max(
        min(first.x + first.width, second.x + second.width)
        - max(first.x, second.x),
        0.0,
    ) * max(
        min(first.y + first.height, second.y + second.height)
        - max(first.y, second.y),
        0.0,
    )


def _reciprocal_overlap(first: SourceBBox, second: SourceBBox) -> float:
    intersection = _intersection_area(first, second)
    denominator = max(_area(first), _area(second))
    return intersection / denominator if denominator else 0.0


def _overlap_of_smaller(first: SourceBBox, second: SourceBBox) -> float:
    intersection = _intersection_area(first, second)
    denominator = min(_area(first), _area(second))
    return intersection / denominator if denominator else 0.0


def _center_inside(inner: SourceBBox, outer: SourceBBox) -> bool:
    center_x = inner.x + inner.width / 2
    center_y = inner.y + inner.height / 2
    return (
        outer.x <= center_x <= outer.x + outer.width
        and outer.y <= center_y <= outer.y + outer.height
    )


def _mapping_bbox(value: Mapping[str, Any] | None) -> SourceBBox | None:
    if not isinstance(value, Mapping):
        return None
    try:
        box = SourceBBox(
            x=float(value["x"]),
            y=float(value["y"]),
            width=float(value.get("width", value.get("w"))),
            height=float(value.get("height", value.get("h"))),
        )
    except (KeyError, TypeError, ValueError):
        return None
    if not all(
        math.isfinite(part)
        for part in (box.x, box.y, box.width, box.height)
    ):
        return None
    if box.width <= 0 or box.height <= 0:
        return None
    return box


def _mapping_bbox_in_unit(
    value: Mapping[str, Any] | None,
    unit: str,
) -> SourceBBox | None:
    """Return a finite box only when its declared coordinate unit agrees."""

    return (
        _mapping_bbox(value)
        if isinstance(value, Mapping) and value.get("unit") == unit
        else None
    )


def _source_space_owner_page_binds(
    page: Mapping[str, Any],
    source_page: SourcePageEvidence,
) -> bool:
    """Require exact page identity/unit and finite source-scale dimensions."""

    width = page.get("page_width")
    height = page.get("page_height")
    return bool(
        type(page.get("page_index")) is int
        and page["page_index"] == source_page.page_index
        and page.get("unit") == source_page.unit
        and type(width) in {int, float}
        and type(height) in {int, float}
        and math.isfinite(float(width))
        and math.isfinite(float(height))
        and float(width) > 0
        and float(height) > 0
        and abs(float(width) - source_page.page_width) <= 0.05
        and abs(float(height) - source_page.page_height) <= 0.05
    )


def _is_printable_source_character(value: str) -> bool:
    if len(value) != 1 or value == "\u00ad":
        return False
    code_point = ord(value)
    if code_point & 0xFFFF in {0xFFFE, 0xFFFF}:
        return False
    if 0xFDD0 <= code_point <= 0xFDEF:
        return False
    return unicodedata.category(value) not in _UNSAFE_CATEGORIES


def _stable_id(prefix: str, source_sha256: str, *parts: object) -> str:
    payload = "\x1f".join(str(part) for part in parts)
    digest = hashlib.sha256(
        f"{source_sha256}\x1e{payload}".encode("utf-8")
    ).hexdigest()[:24]
    return f"{prefix}-{digest}"


def build_supplemental_ocr_contributor(
    *,
    source_document_identity: str,
    page_index: int,
    region_object_index: int,
    region_origin: str,
    region_role: str,
    line_index: int,
    ocr_pass: str,
    coordinate_unit: str,
    bbox: Mapping[str, Any] | None,
    raw_text: str,
    confidence: float | None,
) -> dict[str, Any] | None:
    """Issue a deterministic source-bound page-OCR contributor record.

    Invalid or incomplete input returns no contributor.  That keeps ordinary
    OCR recovery available while making later destructive reconciliation fail
    closed unless the issuing region and source bytes remain attributable.
    """

    box = _mapping_bbox_in_unit(bbox, coordinate_unit)
    if (
        not isinstance(source_document_identity, str)
        or re.fullmatch(r"[0-9a-f]{64}", source_document_identity) is None
        or not isinstance(page_index, int)
        or isinstance(page_index, bool)
        or page_index < 1
        or not isinstance(region_object_index, int)
        or isinstance(region_object_index, bool)
        or region_object_index < 0
        or not isinstance(line_index, int)
        or isinstance(line_index, bool)
        or line_index < 0
        or region_origin not in SUPPLEMENTAL_PDF_PAGE_ORIGINS
        or region_role != "page_source"
        or not isinstance(ocr_pass, str)
        or not ocr_pass
        or len(ocr_pass) > 128
        or coordinate_unit != "pt"
        or box is None
        or not isinstance(raw_text, str)
        or not raw_text
        or len(raw_text) > MAX_CANDIDATE_CODEPOINTS
        or not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not math.isfinite(float(confidence))
        or not 0.0 <= float(confidence) <= 1.0
    ):
        return None
    payload: dict[str, Any] = {
        "schema_version": SUPPLEMENTAL_OCR_CONTRIBUTOR_SCHEMA_VERSION,
        "policy_id": SUPPLEMENTAL_OCR_CONTRIBUTOR_POLICY_ID,
        "source_document_identity": source_document_identity,
        "page_index": page_index,
        "region_object_index": region_object_index,
        "region_origin": region_origin,
        "region_role": region_role,
        "line_index": line_index,
        "ocr_pass": ocr_pass,
        "coordinate_unit": coordinate_unit,
        "bbox": box.to_dict(),
        "raw_text": raw_text,
        "confidence": float(confidence),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    payload["id"] = (
        "ocr-contributor-"
        + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    )
    return payload


def _validated_supplemental_ocr_contributor(
    value: Any,
    *,
    source_sha256: str,
    page_index: int,
    owner_box: SourceBBox,
    raw_text: str,
    confidence: float,
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    expected_fields = {
        "schema_version",
        "policy_id",
        "id",
        "source_document_identity",
        "page_index",
        "region_object_index",
        "region_origin",
        "region_role",
        "line_index",
        "ocr_pass",
        "coordinate_unit",
        "bbox",
        "raw_text",
        "confidence",
    }
    if set(value) != expected_fields:
        return None
    rebuilt = build_supplemental_ocr_contributor(
        source_document_identity=str(
            value.get("source_document_identity") or ""
        ),
        page_index=value.get("page_index"),
        region_object_index=value.get("region_object_index"),
        region_origin=value.get("region_origin"),
        region_role=value.get("region_role"),
        line_index=value.get("line_index"),
        ocr_pass=value.get("ocr_pass"),
        coordinate_unit=value.get("coordinate_unit"),
        bbox=value.get("bbox"),
        raw_text=value.get("raw_text"),
        confidence=value.get("confidence"),
    )
    return (
        rebuilt
        if rebuilt is not None
        and dict(value) == rebuilt
        and rebuilt["source_document_identity"] == source_sha256
        and rebuilt["page_index"] == page_index
        and _mapping_bbox(rebuilt["bbox"]) == owner_box
        and unicodedata.normalize("NFC", rebuilt["raw_text"])
        == unicodedata.normalize("NFC", raw_text)
        and float(rebuilt["confidence"]) == float(confidence)
        else None
    )


def _decoded_pdf_name(raw_name: bytes) -> bytes | None:
    """Decode one bounded PDF name token, including arbitrary ``#xx`` bytes."""

    if not raw_name or len(raw_name) > 3 * MAX_GLYPH_NAME_BYTES:
        return None
    decoded = bytearray()
    position = 0
    while position < len(raw_name):
        value = raw_name[position]
        if (
            value == 0x23
            and position + 2 < len(raw_name)
            and raw_name[position + 1] in _PDF_HEX_BYTES
            and raw_name[position + 2] in _PDF_HEX_BYTES
        ):
            decoded.append(
                int(raw_name[position + 1 : position + 3], 16)
            )
            position += 3
        else:
            decoded.append(value)
            position += 1
        if len(decoded) > MAX_GLYPH_NAME_BYTES:
            return None
    return bytes(decoded)


def _requires_type1_interpretation(
    pdf_bytes: bytes,
    *,
    deadline: float | None = None,
) -> bool:
    """Conservatively preflight whether safe Type1 mappings can exist.

    Every syntactically delimited PDF name is decoded, so arbitrary legal
    ``#xx`` escaping cannot hide an allowlisted glyph or a structural
    container.  Object streams and encryption conservatively force the full
    bounded interpreter.  Plain objects require both ``/Differences`` and an
    allowlisted glyph name.
    """

    differences_seen = False
    safe_glyph_seen = False
    for name_index, match in enumerate(
        _PDF_NAME_RE.finditer(pdf_bytes),
        start=1,
    ):
        if name_index > MAX_PDF_NAMES_INSPECTED:
            return True
        if (
            name_index % 256 == 0
            and deadline is not None
            and time.perf_counter() > deadline
        ):
            raise _Refusal("source_alignment_deadline")
        decoded = _decoded_pdf_name(match.group(1))
        if decoded in {b"ObjStm", b"Encrypt"}:
            return True
        if decoded == b"Differences":
            differences_seen = True
        elif decoded in _SAFE_TYPE1_NAME_BYTES:
            safe_glyph_seen = True
        if differences_seen and safe_glyph_seen:
            return True
    if deadline is not None and time.perf_counter() > deadline:
        raise _Refusal("source_alignment_deadline")
    return False


@dataclass(frozen=True, slots=True)
class _Type1Spec:
    font_ref: str
    font_object_id: int | None
    mappings: dict[int, tuple[str, str]]


@dataclass(slots=True)
class _PendingType1:
    page_index: int
    bbox: SourceBBox
    font_ref: str
    font_object_id: int | None
    cid: int
    glyph_name: str
    original_text: str
    recovered_text: str


class _Type1ResourceManager(PDFResourceManager):
    def __init__(self, deadline: float) -> None:
        super().__init__(caching=True)
        self.deadline = deadline
        self.font_specs: dict[str, _Type1Spec] = {}
        self.font_refs: dict[int, str] = {}
        self.direct_refs: dict[int, str] = {}
        self.direct_count = 0
        self.difference_entries = 0

    def get_font(
        self,
        objid: object,
        spec: Mapping[str, object],
    ) -> PDFFont:
        if time.perf_counter() > self.deadline:
            raise _Refusal("source_alignment_deadline")
        integer_id = (
            int(objid)
            if isinstance(objid, int) and not isinstance(objid, bool)
            else None
        )
        if integer_id is not None:
            font_ref = f"object:{integer_id}"
        else:
            key = id(spec)
            font_ref = self.direct_refs.get(key, "")
            if not font_ref:
                self.direct_count += 1
                font_ref = f"direct:{self.direct_count}"
                self.direct_refs[key] = font_ref

        if font_ref not in self.font_specs:
            if len(self.font_specs) >= MAX_FONT_OBJECTS:
                raise _Refusal("source_alignment_font_limit")
            mappings: dict[int, tuple[str, str]] = {}
            try:
                subtype = literal_name(resolve1(spec.get("Subtype")))
            except Exception:
                subtype = ""
            if subtype == "Type1":
                try:
                    encoding = resolve1(spec.get("Encoding"))
                except Exception as exc:
                    raise _Refusal(
                        "source_alignment_type1_encoding_malformed"
                    ) from exc
                if isinstance(encoding, Mapping):
                    try:
                        differences = list_value(
                            resolve1(encoding.get("Differences"))
                        )
                    except Exception as exc:
                        raise _Refusal(
                            "source_alignment_type1_differences_malformed"
                        ) from exc
                    if len(differences) > MAX_DIFFERENCES_PER_FONT:
                        raise _Refusal(
                            "source_alignment_type1_font_difference_limit"
                        )
                    self.difference_entries += len(differences)
                    if self.difference_entries > MAX_DIFFERENCE_ENTRIES:
                        raise _Refusal(
                            "source_alignment_type1_difference_limit"
                        )
                    code: int | None = None
                    assigned: set[int] = set()
                    for entry in differences:
                        if isinstance(entry, int) and not isinstance(
                            entry, bool
                        ):
                            if not 0 <= entry <= 255:
                                raise _Refusal(
                                    "source_alignment_type1_code_invalid"
                                )
                            code = int(entry)
                            continue
                        if code is None or code > 255:
                            raise _Refusal(
                                "source_alignment_type1_differences_malformed"
                            )
                        try:
                            name = literal_name(entry)
                        except Exception as exc:
                            raise _Refusal(
                                "source_alignment_type1_name_malformed"
                            ) from exc
                        try:
                            encoded_name = name.encode("ascii")
                        except UnicodeEncodeError as exc:
                            raise _Refusal(
                                "source_alignment_type1_name_non_ascii"
                            ) from exc
                        if (
                            not encoded_name
                            or len(encoded_name) > MAX_GLYPH_NAME_BYTES
                        ):
                            raise _Refusal(
                                "source_alignment_type1_name_limit"
                            )
                        if code in assigned:
                            raise _Refusal(
                                "source_alignment_type1_mapping_ambiguous"
                            )
                        assigned.add(code)
                        recovered = _SAFE_TYPE1_GLYPHS.get(name)
                        if recovered is not None:
                            mappings[code] = (name, recovered)
                        code += 1

            self.font_specs[font_ref] = _Type1Spec(
                font_ref=font_ref,
                font_object_id=integer_id,
                mappings=mappings,
            )

        font = super().get_font(objid, spec)
        self.font_refs[id(font)] = font_ref
        return font


class _Type1Device(PDFPageAggregator):
    def __init__(self, resource_manager: _Type1ResourceManager) -> None:
        super().__init__(resource_manager)
        self.resource_manager = resource_manager
        self.page_index = 0
        self.page_bbox = (0.0, 0.0, 0.0, 0.0)
        self.pending: list[_PendingType1] = []
        self.run_count = 0

    def begin_page(
        self,
        page: PDFPage,
        ctm: tuple[float, ...],
    ) -> None:
        super().begin_page(page, ctm)
        self.page_bbox = tuple(float(value) for value in self.cur_item.bbox)

    def render_string(
        self,
        textstate: PDFTextState,
        seq: Iterable[int | float | bytes],
        ncs: Any,
        graphicstate: PDFGraphicState,
    ) -> None:
        self.run_count += 1
        if self.run_count > MAX_SOURCE_RUNS:
            raise _Refusal("source_alignment_run_limit")
        if time.perf_counter() > self.resource_manager.deadline:
            raise _Refusal("source_alignment_deadline")
        super().render_string(textstate, seq, ncs, graphicstate)

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
        try:
            mapped_text = font.to_unichr(cid)
            if not isinstance(mapped_text, str):
                mapped_text = str(mapped_text)
        except PDFUnicodeNotDefined:
            mapped_text = self.handle_undefined_char(font, cid)

        textwidth = font.char_width(cid)
        textdisp = font.char_disp(cid)
        item = LTChar(
            matrix,
            font,
            fontsize,
            scaling,
            rise,
            mapped_text,
            textwidth,
            textdisp,
            ncs,
            graphicstate,
        )
        self.cur_item.add(item)

        font_ref = self.resource_manager.font_refs.get(id(font))
        spec = (
            self.resource_manager.font_specs.get(font_ref)
            if font_ref is not None
            else None
        )
        mapping = spec.mappings.get(int(cid)) if spec is not None else None
        if mapping is not None:
            if len(self.pending) >= MAX_TYPE1_OCCURRENCES:
                raise _Refusal("source_alignment_type1_occurrence_limit")
            page_left, _page_bottom, _page_right, page_top = self.page_bbox
            box = _bbox_from_pdfminer(item.bbox, page_left, page_top)
            if box is None:
                raise _Refusal("source_alignment_type1_bbox_invalid")
            self.pending.append(
                _PendingType1(
                    page_index=self.page_index,
                    bbox=box,
                    font_ref=font_ref or "",
                    font_object_id=spec.font_object_id if spec else None,
                    cid=int(cid),
                    glyph_name=mapping[0],
                    original_text=mapped_text,
                    recovered_text=mapping[1],
                )
            )
        return float(item.adv)


def _extract_type1_evidence(
    pdf_bytes: bytes,
    *,
    source_sha256: str,
    max_pages: int,
    deadline: float,
) -> tuple[Type1GlyphEvidence, ...]:
    parser = PDFParser(io.BytesIO(pdf_bytes))
    document = PDFDocument(parser)
    resource_manager = _Type1ResourceManager(deadline)
    device = _Type1Device(resource_manager)
    interpreter = PDFPageInterpreter(resource_manager, device)
    page_count = 0
    try:
        for page_count, page in enumerate(
            PDFPage.create_pages(document),
            start=1,
        ):
            if page_count > max_pages:
                raise _Refusal("source_alignment_page_limit")
            if time.perf_counter() > deadline:
                raise _Refusal("source_alignment_deadline")
            device.page_index = page_count
            interpreter.process_page(page)
    except _Refusal:
        raise
    except (PDFException, ValueError, TypeError, OverflowError) as exc:
        raise _Refusal("source_alignment_pdfminer_failed") from exc
    finally:
        device.close()

    output: list[Type1GlyphEvidence] = []
    for occurrence_index, pending in enumerate(device.pending, start=1):
        identifier = _stable_id(
            "type1",
            source_sha256,
            pending.page_index,
            pending.font_ref,
            pending.cid,
            pending.glyph_name,
            pending.bbox.x,
            pending.bbox.y,
            occurrence_index,
        )
        output.append(
            Type1GlyphEvidence(
                id=identifier,
                page_index=pending.page_index,
                bbox=pending.bbox,
                font_ref=pending.font_ref,
                font_object_id=pending.font_object_id,
                cid=pending.cid,
                glyph_name=pending.glyph_name,
                original_text=pending.original_text,
                recovered_text=pending.recovered_text,
                role=(
                    "superscript"
                    if pending.glyph_name.endswith(".numr")
                    else "ligature"
                ),
            )
        )
    return tuple(output)


def _fill_rgba(raw_object: Any) -> tuple[int, int, int, int] | None:
    channels = [ctypes.c_uint() for _ in range(4)]
    if not pdfium_raw.FPDFPageObj_GetFillColor(
        raw_object,
        *(ctypes.byref(channel) for channel in channels),
    ):
        return None
    return tuple(int(channel.value) for channel in channels)  # type: ignore[return-value]


def _raw_pointer(value: Any) -> int:
    return int(ctypes.cast(value, ctypes.c_void_p).value or 0)


def _tight_nontext_enclosures(
    page: Any,
    *,
    page_width: float,
    page_height: float,
    rotation: int,
    deadline: float,
) -> list[SourceBBox]:
    enclosures: list[SourceBBox] = []
    object_count = 0
    for page_object in page.get_objects(max_depth=8):
        object_count += 1
        if object_count > MAX_PAGE_OBJECTS:
            raise _Refusal("source_alignment_page_object_limit")
        if (
            object_count % 256 == 0
            and time.perf_counter() > deadline
        ):
            raise _Refusal("source_alignment_deadline")
        if page_object.type == pdfium_raw.FPDF_PAGEOBJ_TEXT:
            continue
        try:
            left, bottom, right, top = (
                float(value) for value in page_object.get_bounds()
            )
        except (AttributeError, TypeError, ValueError):
            continue
        box = _bbox_from_pdfium(
            (left, bottom, right, top),
            page_width,
            page_height,
            rotation,
        )
        if box is not None and box.width <= 64 and box.height <= 64:
            enclosures.append(box)
    if time.perf_counter() > deadline:
        raise _Refusal("source_alignment_deadline")
    return enclosures


class _Type1SpatialIndex:
    _CELL = 16.0

    def __init__(
        self,
        glyphs: Sequence[Type1GlyphEvidence],
    ) -> None:
        self._glyphs = glyphs
        self._cells: dict[
            tuple[int, int, int],
            list[int],
        ] = defaultdict(list)
        for index, glyph in enumerate(glyphs):
            box = glyph.bbox
            left = math.floor(box.x / self._CELL)
            right = math.floor((box.x + box.width) / self._CELL)
            top = math.floor(box.y / self._CELL)
            bottom = math.floor((box.y + box.height) / self._CELL)
            for cell_x in range(left, right + 1):
                for cell_y in range(top, bottom + 1):
                    self._cells[
                        (glyph.page_index, cell_x, cell_y)
                    ].append(index)

    def matching(
        self,
        page_index: int,
        box: SourceBBox,
    ) -> list[Type1GlyphEvidence]:
        left = math.floor(box.x / self._CELL)
        right = math.floor((box.x + box.width) / self._CELL)
        top = math.floor(box.y / self._CELL)
        bottom = math.floor((box.y + box.height) / self._CELL)
        candidate_indexes: set[int] = set()
        for cell_x in range(left, right + 1):
            for cell_y in range(top, bottom + 1):
                candidate_indexes.update(
                    self._cells.get(
                        (page_index, cell_x, cell_y),
                        (),
                    )
                )
        return [
            self._glyphs[index]
            for index in sorted(candidate_indexes)
            if _overlap_of_smaller(box, self._glyphs[index].bbox)
            >= MIN_TYPE1_RECIPROCAL_OVERLAP
        ]


@dataclass(slots=True)
class _PageBuild:
    page_index: int
    width: float
    height: float
    characters: list[_RawCharacter]
    lines: list[list[_RawCharacter]] = field(default_factory=list)


def _neighboring_visible(
    characters: Sequence[_RawCharacter],
    index: int,
    direction: int,
) -> _RawCharacter | None:
    cursor = index + direction
    while 0 <= cursor < len(characters):
        candidate = characters[cursor]
        if direction > 0 and candidate.hard_break_before:
            return None
        if (
            candidate.raw_text not in {" ", "\t", "\r", "\n"}
            and candidate.bbox is not None
            and candidate.excluded_reason is None
        ):
            return candidate
        cursor += direction
    return None


def _mark_supported_spaces(characters: list[_RawCharacter]) -> None:
    for index, character in enumerate(characters):
        if character.raw_code_point != 0x20:
            continue
        left = _neighboring_visible(characters, index, -1)
        right = _neighboring_visible(characters, index, 1)
        if left is None or right is None:
            continue
        if left.bbox is None or right.bbox is None:
            continue
        local_font_size = max(
            value
            for value in (
                left.font_size or 0.0,
                right.font_size or 0.0,
            )
        )
        if not _finite_positive(local_font_size):
            continue
        if left.baseline is None or right.baseline is None:
            continue
        if abs(left.baseline - right.baseline) > 0.15 * local_font_size:
            continue
        gap = right.bbox.x - (left.bbox.x + left.bbox.width)
        if not (
            max(0.75, 0.15 * local_font_size)
            <= gap
            <= 1.5 * local_font_size
        ):
            continue
        top = min(left.bbox.y, right.bbox.y)
        bottom = max(
            left.bbox.y + left.bbox.height,
            right.bbox.y + right.bbox.height,
        )
        character.space_supported = True
        character.bbox = SourceBBox(
            x=round(left.bbox.x + left.bbox.width, 6),
            y=round(top, 6),
            width=round(gap, 6),
            height=round(bottom - top, 6),
        )


def _exclude_white_icon_text(
    characters: list[_RawCharacter],
    enclosures: Sequence[SourceBBox],
) -> None:
    positions_by_object: dict[str, list[int]] = defaultdict(list)
    for index, character in enumerate(characters):
        if character.text_object_ref:
            positions_by_object[character.text_object_ref].append(index)

    for positions in positions_by_object.values():
        group = [characters[index] for index in positions]
        visible_text = "".join(
            character.raw_text
            for character in group
            if character.raw_text.strip()
        )
        if (
            not 1 <= len(visible_text) <= 3
            or not visible_text.isalnum()
            or not all(
                character.fill_rgba is not None
                and min(character.fill_rgba[:3]) >= 250
                and character.fill_rgba[3] > 0
                for character in group
                if character.raw_text.strip()
            )
        ):
            continue
        group_box = _bbox_union(character.bbox for character in group)
        if group_box is None:
            continue
        tightly_enclosed = any(
            _center_inside(group_box, enclosure)
            and _area(enclosure) <= 8.0 * _area(group_box)
            and enclosure.width <= max(2.5 * group_box.height, 12.0)
            and enclosure.height <= max(2.5 * group_box.height, 12.0)
            for enclosure in enclosures
        )
        if not tightly_enclosed:
            continue
        first = min(positions)
        last = max(positions)
        prior = _neighboring_visible(characters, first, -1)
        following = _neighboring_visible(characters, last, 1)
        neighbors = [
            neighbor
            for neighbor in (prior, following)
            if neighbor is not None
            and neighbor.raw_text.isalnum()
            and neighbor.fill_rgba is not None
            and max(neighbor.fill_rgba[:3]) < 250
        ]
        if not neighbors:
            continue
        if not any(
            neighbor.bbox is not None
            and abs(
                (
                    neighbor.bbox.y + neighbor.bbox.height / 2
                )
                - (group_box.y + group_box.height / 2)
            )
            <= max(group_box.height, neighbor.bbox.height)
            for neighbor in neighbors
        ):
            continue
        for character in group:
            character.excluded_reason = "white_icon_overlay"


def _has_white_icon_candidate(
    characters: Sequence[_RawCharacter],
    *,
    deadline: float,
) -> bool:
    """Return whether a page can benefit from non-text enclosure traversal."""

    characters_by_object: dict[str, list[_RawCharacter]] = defaultdict(list)
    for character_index, character in enumerate(characters, start=1):
        if (
            character_index % 256 == 0
            and time.perf_counter() > deadline
        ):
            raise _Refusal("source_alignment_deadline")
        if character.text_object_ref:
            characters_by_object[character.text_object_ref].append(character)
    for group_index, group in enumerate(
        characters_by_object.values(),
        start=1,
    ):
        if (
            group_index % 256 == 0
            and time.perf_counter() > deadline
        ):
            raise _Refusal("source_alignment_deadline")
        visible = [
            character
            for character in group
            if character.raw_text.strip()
        ]
        visible_text = "".join(
            character.raw_text for character in visible
        )
        if (
            1 <= len(visible_text) <= 3
            and visible_text.isalnum()
            and visible
            and all(
                character.fill_rgba is not None
                and min(character.fill_rgba[:3]) >= 250
                and character.fill_rgba[3] > 0
                for character in visible
            )
        ):
            return True
    return False


def _compose_spacing_diaereses(
    characters: list[_RawCharacter],
) -> None:
    for index, mark in enumerate(characters):
        if (
            mark.raw_code_point != 0x00A8
            or mark.excluded_reason is not None
            or mark.bbox is None
        ):
            continue
        if index == 0:
            continue
        base = characters[index - 1]
        if (
            base.excluded_reason is not None
            or base.bbox is None
            or base.font_ref is None
            or base.font_ref != mark.font_ref
            or base.font_size is None
            or mark.font_size is None
            or base.baseline is None
            or mark.baseline is None
            or base.raw_text not in "AEIOUYaeiouy"
        ):
            continue
        local_font_size = max(base.font_size, mark.font_size)
        if (
            not _finite_positive(local_font_size)
            or abs(base.baseline - mark.baseline)
            > 0.10 * local_font_size
        ):
            continue
        horizontal_overlap = max(
            min(
                base.bbox.x + base.bbox.width,
                mark.bbox.x + mark.bbox.width,
            )
            - max(base.bbox.x, mark.bbox.x),
            0.0,
        )
        mark_center_x = mark.bbox.x + mark.bbox.width / 2
        if (
            horizontal_overlap < 0.80 * mark.bbox.width
            or not (
                base.bbox.x
                <= mark_center_x
                <= base.bbox.x + base.bbox.width
            )
        ):
            continue
        composed = unicodedata.normalize("NFC", base.text + "\u0308")
        if (
            len(composed) != 1
            or unicodedata.category(composed) == "Cn"
        ):
            continue
        base.text = composed
        mark.text = ""
        mark.excluded_reason = "spacing_diaeresis_composed"


def _chunk_box(chunk: Sequence[_RawCharacter]) -> SourceBBox | None:
    return _bbox_union(
        character.bbox
        for character in chunk
        if character.raw_text != " "
    )


def _same_visual_line(
    first: Sequence[_RawCharacter],
    second: Sequence[_RawCharacter],
) -> bool:
    first_box = _chunk_box(first)
    second_box = _chunk_box(second)
    if first_box is None or second_box is None:
        return False
    vertical_overlap = max(
        min(
            first_box.y + first_box.height,
            second_box.y + second_box.height,
        )
        - max(first_box.y, second_box.y),
        0.0,
    )
    smaller_height = min(first_box.height, second_box.height)
    center_delta = abs(
        (first_box.y + first_box.height / 2)
        - (second_box.y + second_box.height / 2)
    )
    vertically_aligned = (
        smaller_height > 0
        and vertical_overlap / smaller_height >= 0.25
    ) or center_delta <= 0.55 * max(first_box.height, second_box.height)
    if not vertically_aligned:
        return False
    gap = second_box.x - (first_box.x + first_box.width)
    return (
        gap >= -0.5 * max(first_box.height, second_box.height)
        and gap <= max(24.0, 3.0 * max(first_box.height, second_box.height))
    )


def _geometry_lines(
    characters: Sequence[_RawCharacter],
) -> list[list[_RawCharacter]]:
    chunks: list[list[_RawCharacter]] = []
    current: list[_RawCharacter] = []
    last_visible: _RawCharacter | None = None
    for character in characters:
        geometry_break = False
        if (
            current
            and last_visible is not None
            and character.bbox is not None
            and character.raw_text != " "
        ):
            first = last_visible.bbox
            second = character.bbox
            if first is not None:
                vertical_overlap = max(
                    min(
                        first.y + first.height,
                        second.y + second.height,
                    )
                    - max(first.y, second.y),
                    0.0,
                )
                smaller = min(first.height, second.height)
                center_delta = abs(
                    (first.y + first.height / 2)
                    - (second.y + second.height / 2)
                )
                geometry_break = not (
                    (smaller > 0 and vertical_overlap / smaller >= 0.15)
                    or center_delta
                    <= 0.75 * max(first.height, second.height)
                )
        if (character.hard_break_before or geometry_break) and current:
            chunks.append(current)
            current = []
            last_visible = None
        current.append(character)
        if character.bbox is not None and character.raw_text != " ":
            last_visible = character
    if current:
        chunks.append(current)

    lines: list[list[_RawCharacter]] = []
    for chunk in chunks:
        if lines and _same_visual_line(lines[-1], chunk):
            lines[-1].extend(chunk)
        else:
            lines.append(list(chunk))
    return [
        line for line in lines
        if _chunk_box(line) is not None
    ]


def _line_text(
    characters: Sequence[_RawCharacter],
    *,
    raw: bool,
) -> str:
    values: list[str] = []
    for character in characters:
        if character.excluded_reason in {
            "unsafe_unicode",
            "transparent_text",
            "white_icon_overlay",
            "uncorroborated_hyphen_sentinel",
        }:
            continue
        values.append(character.raw_text if raw else character.text)
    return "".join(values).strip(" ")


def _word_before(
    characters: Sequence[_RawCharacter],
    terminal_index: int,
) -> str:
    output: list[str] = []
    for character in reversed(characters[:terminal_index]):
        if character.text.isalnum():
            output.append(character.text)
            if len(output) >= 64:
                break
        else:
            break
    return "".join(reversed(output))


def _word_after(characters: Sequence[_RawCharacter]) -> str:
    output: list[str] = []
    for character in characters:
        if character.text.isalnum():
            output.append(character.text)
            if len(output) >= 64:
                break
        elif output:
            break
        elif character.raw_text == " ":
            continue
        else:
            break
    return "".join(output)


def _corroborate_semantic_hyphens(
    pages: Sequence[_PageBuild],
) -> None:
    literal_occurrences: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for page in pages:
        for line_index, line in enumerate(page.lines):
            literal = _line_text(line, raw=True)
            for match in re.finditer(
                r"(?<![\w])([\w]{1,64}-[\w]{1,64})(?![\w])",
                literal,
                flags=re.UNICODE,
            ):
                literal_occurrences[match.group(1)].append(
                    (page.page_index, line_index)
                )

    flat_lines: list[tuple[_PageBuild, int, list[_RawCharacter]]] = []
    for page in pages:
        for line_index, line in enumerate(page.lines):
            flat_lines.append((page, line_index, line))

    for flat_index, (page, line_index, line) in enumerate(flat_lines):
        visible_positions = [
            index
            for index, character in enumerate(line)
            if character.raw_text != " "
            and character.bbox is not None
        ]
        if not visible_positions:
            continue
        terminal_index = visible_positions[-1]
        sentinel = line[terminal_index]
        if (
            not sentinel.pdfium_is_hyphen
            or sentinel.excluded_reason
            != "uncorroborated_hyphen_sentinel"
            or flat_index + 1 >= len(flat_lines)
        ):
            continue
        next_page, _next_line_index, next_line = flat_lines[flat_index + 1]
        if next_page.page_index != page.page_index:
            continue
        left = _word_before(line, terminal_index)
        right = _word_after(next_line)
        if not left or not right:
            continue
        anchored_term = f"{left}-{right}"
        corroboration = literal_occurrences.get(anchored_term, [])
        if not corroboration:
            continue
        sentinel.text = "-"
        sentinel.excluded_reason = None
        sentinel.corroborating_line_ids.extend(
            f"pending:{candidate_page}:{candidate_line}"
            for candidate_page, candidate_line in corroboration[
                :MAX_EVIDENCE_REFS
            ]
        )


def _mark_source_roles(lines: Sequence[list[_RawCharacter]]) -> None:
    for line in lines:
        font_sizes = [
            character.font_size
            for character in line
            if character.font_size is not None
            and character.raw_text.isalpha()
            and character.excluded_reason is None
        ]
        if not font_sizes:
            continue
        median_size = statistics.median(font_sizes)
        for index, character in enumerate(line):
            if (
                character.role is None
                and character.raw_text in "0123456789,*"
                and character.font_size is not None
                and character.font_size <= 0.82 * median_size
            ):
                prior = line[index - 1] if index else None
                following = (
                    line[index + 1] if index + 1 < len(line) else None
                )
                if any(
                    neighbor is not None
                    and (
                        neighbor.raw_text.isalnum()
                        or neighbor.raw_text in "0123456789,*"
                    )
                    for neighbor in (prior, following)
                ):
                    character.role = "superscript"


def _refused_evidence(
    source_sha256: str,
    code: str,
    started: float,
) -> SourceTextEvidence:
    return SourceTextEvidence(
        schema_version=SOURCE_TEXT_ALIGNMENT_SCHEMA_VERSION,
        policy_id=SOURCE_TEXT_ALIGNMENT_POLICY_ID,
        source_sha256=source_sha256,
        usable=False,
        refusal_code=code,
        page_count=0,
        character_count=0,
        line_count=0,
        type1_glyph_count=0,
        pages=(),
        type1_glyphs=(),
        diagnostics=({"code": code},),
        elapsed_ms=round((time.perf_counter() - started) * 1000, 6),
    )


def extract_source_text_evidence(
    pdf_bytes: bytes,
    *,
    max_pages: int = MAX_PAGES,
) -> SourceTextEvidence:
    """Extract bounded PDFium and Type1 source-text evidence.

    Any malformed input, exhausted bound, ambiguous source mapping, or
    deadline produces one unusable report with no partial evidence.
    """

    started = time.perf_counter()
    source_sha256 = hashlib.sha256(
        bytes(pdf_bytes) if isinstance(pdf_bytes, (bytes, bytearray)) else b""
    ).hexdigest()
    try:
        if not isinstance(pdf_bytes, bytes):
            raise _Refusal("source_alignment_input_type")
        if not pdf_bytes or len(pdf_bytes) > MAX_INPUT_BYTES:
            raise _Refusal("source_alignment_input_size")
        if (
            not isinstance(max_pages, int)
            or isinstance(max_pages, bool)
            or not 1 <= max_pages <= MAX_PAGES
        ):
            raise _Refusal("source_alignment_max_pages_invalid")
        deadline = started + MAX_ALIGNMENT_SECONDS

        type1_glyphs = (
            _extract_type1_evidence(
                pdf_bytes,
                source_sha256=source_sha256,
                max_pages=max_pages,
                deadline=deadline,
            )
            if _requires_type1_interpretation(
                pdf_bytes,
                deadline=deadline,
            )
            else ()
        )
        type1_roles = {
            glyph.id: glyph.role for glyph in type1_glyphs
        }
        type1_index = _Type1SpatialIndex(type1_glyphs)

        try:
            document = pdfium.PdfDocument(pdf_bytes)
        except Exception as exc:
            raise _Refusal("source_alignment_pdfium_open_failed") from exc

        page_builds: list[_PageBuild] = []
        total_characters = 0
        try:
            page_count = len(document)
            if page_count > max_pages or page_count > MAX_PAGES:
                raise _Refusal("source_alignment_page_limit")
            if page_count <= 0:
                raise _Refusal("source_alignment_empty_pdf")

            font_refs: dict[int, str] = {}
            object_refs: dict[int, str] = {}
            for page_offset in range(page_count):
                if time.perf_counter() > deadline:
                    raise _Refusal("source_alignment_deadline")
                page_index = page_offset + 1
                page = document[page_offset]
                try:
                    width, height = (
                        float(value) for value in page.get_size()
                    )
                    if not (
                        _finite_positive(width)
                        and _finite_positive(height)
                        and width <= 200_000
                        and height <= 200_000
                    ):
                        raise _Refusal(
                            "source_alignment_page_dimensions_invalid"
                        )
                    rotation = int(page.get_rotation()) % 360
                    text_page = page.get_textpage()
                    try:
                        count = int(text_page.count_chars())
                        if count < 0:
                            raise _Refusal(
                                "source_alignment_character_count_invalid"
                            )
                        total_characters += count
                        if total_characters > MAX_SOURCE_CHARACTERS:
                            raise _Refusal(
                                "source_alignment_character_limit"
                            )

                        raw_characters: list[_RawCharacter] = []
                        hard_break_pending = False
                        object_metadata: dict[
                            int,
                            tuple[
                                tuple[int, int, int, int] | None,
                                str | None,
                                str,
                                float | None,
                                float | None,
                            ],
                        ] = {}
                        for character_index in range(count):
                            if (
                                character_index % 256 == 0
                                and time.perf_counter() > deadline
                            ):
                                raise _Refusal(
                                    "source_alignment_deadline"
                                )
                            raw_code_point = int(
                                pdfium_raw.FPDFText_GetUnicode(
                                    text_page.raw,
                                    character_index,
                                )
                            )
                            if not 0 <= raw_code_point <= 0x10FFFF:
                                raise _Refusal(
                                    "source_alignment_code_point_invalid"
                                )
                            raw_text = chr(raw_code_point)
                            if raw_text in {"\r", "\n"}:
                                hard_break_pending = True
                                continue

                            is_hyphen = (
                                int(
                                    pdfium_raw.FPDFText_IsHyphen(
                                        text_page.raw,
                                        character_index,
                                    )
                                )
                                == 1
                            )
                            try:
                                raw_box = text_page.get_charbox(
                                    character_index,
                                    loose=False,
                                )
                            except Exception:
                                raw_box = None
                            box = (
                                _bbox_from_pdfium(
                                    raw_box,
                                    width,
                                    height,
                                    rotation,
                                )
                                if raw_box is not None
                                else None
                            )

                            text_object = text_page.get_textobj(
                                character_index
                            )
                            rgba: tuple[int, int, int, int] | None = None
                            font_ref: str | None = None
                            object_ref: str | None = None
                            font_size: float | None = None
                            baseline: float | None = None
                            if text_object is not None:
                                object_pointer = _raw_pointer(
                                    text_object.raw
                                )
                                if object_pointer == 0:
                                    object_pointer = -(character_index + 1)
                                cached = object_metadata.get(object_pointer)
                                if cached is None:
                                    if object_pointer not in object_refs:
                                        object_refs[object_pointer] = (
                                            "pdfium-object:"
                                            f"{len(object_refs) + 1}"
                                        )
                                    object_ref = object_refs[object_pointer]
                                    rgba = _fill_rgba(text_object.raw)
                                    try:
                                        font = text_object.get_font()
                                        font_pointer = _raw_pointer(font.raw)
                                        if font_pointer not in font_refs:
                                            font_refs[font_pointer] = (
                                                "pdfium-font:"
                                                f"{len(font_refs) + 1}"
                                            )
                                        font_ref = font_refs[font_pointer]
                                        matrix = text_object.get_matrix()
                                        scale = math.hypot(
                                            float(matrix.a),
                                            float(matrix.b),
                                        )
                                        font_size = (
                                            float(
                                                text_object.get_font_size()
                                            )
                                            * scale
                                        )
                                        baseline = (
                                            height - float(matrix.f)
                                            if rotation == 0
                                            else None
                                        )
                                        if not (
                                            _finite_positive(font_size)
                                            and (
                                                baseline is None
                                                or math.isfinite(baseline)
                                            )
                                        ):
                                            font_size = None
                                            baseline = None
                                    except (
                                        AttributeError,
                                        TypeError,
                                        ValueError,
                                        OverflowError,
                                    ):
                                        font_ref = None
                                        font_size = None
                                        baseline = None
                                    object_metadata[object_pointer] = (
                                        rgba,
                                        font_ref,
                                        object_ref,
                                        font_size,
                                        baseline,
                                    )
                                else:
                                    (
                                        rgba,
                                        font_ref,
                                        object_ref,
                                        font_size,
                                        baseline,
                                    ) = cached

                            text = raw_text
                            excluded_reason: str | None = None
                            type1_ids: list[str] = []
                            if is_hyphen:
                                if box is None:
                                    excluded_reason = (
                                        "invalid_hyphen_sentinel_bbox"
                                    )
                                else:
                                    text = ""
                                    excluded_reason = (
                                        "uncorroborated_hyphen_sentinel"
                                    )
                            elif not _is_printable_source_character(raw_text):
                                excluded_reason = "unsafe_unicode"
                            elif raw_text.isspace() and raw_text != " ":
                                excluded_reason = "unsafe_unicode"
                            elif rgba is not None and rgba[3] == 0:
                                excluded_reason = "transparent_text"

                            if (
                                box is not None
                                and excluded_reason
                                not in {
                                    "unsafe_unicode",
                                    "transparent_text",
                                }
                            ):
                                matches = type1_index.matching(
                                    page_index,
                                    box,
                                )
                                if len(matches) == 1:
                                    match = matches[0]
                                    text = match.recovered_text
                                    type1_ids.append(match.id)
                                elif len(matches) > 1:
                                    recovered_values = {
                                        match.recovered_text
                                        for match in matches
                                    }
                                    if len(recovered_values) == 1:
                                        # Provenance is still ambiguous.
                                        excluded_reason = (
                                            "ambiguous_type1_geometry"
                                        )
                                    else:
                                        excluded_reason = (
                                            "conflicting_type1_geometry"
                                        )

                            identifier = _stable_id(
                                "char",
                                source_sha256,
                                page_index,
                                character_index,
                                raw_code_point,
                                box.x if box else "",
                                box.y if box else "",
                            )
                            raw_characters.append(
                                _RawCharacter(
                                    page_index=page_index,
                                    character_index=character_index,
                                    raw_code_point=raw_code_point,
                                    raw_text=raw_text,
                                    text=text,
                                    bbox=box,
                                    fill_rgba=rgba,
                                    font_ref=font_ref,
                                    font_size=font_size,
                                    baseline=baseline,
                                    text_object_ref=object_ref,
                                    pdfium_is_hyphen=is_hyphen,
                                    hard_break_before=hard_break_pending,
                                    excluded_reason=excluded_reason,
                                    type1_evidence_ids=type1_ids,
                                    role=(
                                        type1_roles.get(type1_ids[0])
                                        if type1_ids
                                        else None
                                    ),
                                    id=identifier,
                                )
                            )
                            hard_break_pending = False
                    finally:
                        text_page.close()

                    enclosures = (
                        _tight_nontext_enclosures(
                            page,
                            page_width=width,
                            page_height=height,
                            rotation=rotation,
                            deadline=deadline,
                        )
                        if _has_white_icon_candidate(
                            raw_characters,
                            deadline=deadline,
                        )
                        else ()
                    )
                    _exclude_white_icon_text(raw_characters, enclosures)
                    _mark_supported_spaces(raw_characters)
                    _compose_spacing_diaereses(raw_characters)
                    page_build = _PageBuild(
                        page_index=page_index,
                        width=width,
                        height=height,
                        characters=raw_characters,
                    )
                    page_build.lines = _geometry_lines(raw_characters)
                    page_builds.append(page_build)
                finally:
                    page.close()
        finally:
            document.close()

        _corroborate_semantic_hyphens(page_builds)
        for page in page_builds:
            page.lines = _geometry_lines(page.characters)
            _mark_source_roles(page.lines)

        public_pages: list[SourcePageEvidence] = []
        line_id_lookup: dict[tuple[int, int], str] = {}
        line_ids_by_character: dict[str, list[str]] = defaultdict(list)
        for page in page_builds:
            for line_index, line in enumerate(page.lines):
                box = _chunk_box(line)
                if box is None:
                    continue
                line_id = _stable_id(
                    "line",
                    source_sha256,
                    page.page_index,
                    line_index,
                    _line_text(line, raw=False),
                    box.x,
                    box.y,
                )
                line_id_lookup[(page.page_index, line_index)] = line_id
                for character in line:
                    line_ids_by_character[character.id].append(line_id)

        for page in page_builds:
            public_characters: list[SourceCharacterEvidence] = []
            for character in page.characters:
                corroborating = tuple(
                    line_id_lookup.get(
                        tuple(
                            int(part)
                            for part in pending.removeprefix(
                                "pending:"
                            ).split(":")
                        ),
                        pending,
                    )
                    for pending in character.corroborating_line_ids
                )
                public_characters.append(
                    SourceCharacterEvidence(
                        id=character.id,
                        page_index=character.page_index,
                        character_index=character.character_index,
                        raw_code_point=character.raw_code_point,
                        raw_text=character.raw_text,
                        text=character.text,
                        bbox=character.bbox,
                        fill_rgba=character.fill_rgba,
                        font_ref=character.font_ref,
                        font_size=(
                            round(character.font_size, 6)
                            if character.font_size is not None
                            else None
                        ),
                        baseline=(
                            round(character.baseline, 6)
                            if character.baseline is not None
                            else None
                        ),
                        pdfium_is_hyphen=character.pdfium_is_hyphen,
                        space_supported=character.space_supported,
                        excluded_reason=character.excluded_reason,
                        type1_evidence_ids=tuple(
                            character.type1_evidence_ids
                        ),
                        corroborating_line_ids=corroborating,
                        role=character.role,
                    )
                )

            public_lines: list[SourceTextLine] = []
            for line_index, line in enumerate(page.lines):
                box = _chunk_box(line)
                if box is None:
                    continue
                line_id = line_id_lookup[
                    (page.page_index, line_index)
                ]
                # Retain excluded glyph identities in line provenance.  The
                # emission helpers omit them, but layout-projection matching
                # can still prove that e.g. white icon text caused a fusion.
                included = list(line)
                unsafe = any(
                    character.excluded_reason
                    in {
                        "unsafe_unicode",
                        "invalid_hyphen_sentinel_bbox",
                        "uncorroborated_hyphen_sentinel",
                        "ambiguous_type1_geometry",
                        "conflicting_type1_geometry",
                    }
                    for character in line
                )
                nonspace = [
                    character
                    for character in line
                    if character.text and character.text != " "
                    and character.excluded_reason is None
                ]
                terminal_semantic = bool(
                    nonspace
                    and nonspace[-1].pdfium_is_hyphen
                    and nonspace[-1].text == "-"
                )
                public_lines.append(
                    SourceTextLine(
                        id=line_id,
                        page_index=page.page_index,
                        text=_line_text(line, raw=False),
                        raw_text=_line_text(line, raw=True),
                        bbox=box,
                        source_character_ids=tuple(
                            character.id for character in included
                        ),
                        source_character_indexes=tuple(
                            character.character_index
                            for character in included
                        ),
                        type1_evidence_ids=tuple(
                            dict.fromkeys(
                                evidence_id
                                for character in line
                                for evidence_id
                                in character.type1_evidence_ids
                            )
                        ),
                        has_unsafe_character=unsafe,
                        terminal_semantic_hyphen=terminal_semantic,
                    )
                )
            public_pages.append(
                SourcePageEvidence(
                    page_index=page.page_index,
                    page_width=round(page.width, 6),
                    page_height=round(page.height, 6),
                    unit="pt",
                    characters=tuple(public_characters),
                    lines=tuple(public_lines),
                )
            )

        diagnostics: list[dict[str, Any]] = []
        for public_page in public_pages:
            characters_by_id = {
                character.id: character
                for character in public_page.characters
            }
            for line in public_page.lines:
                ordered = [
                    characters_by_id[identifier]
                    for identifier in line.source_character_ids
                    if identifier in characters_by_id
                ]
                prefix_count = 0
                while (
                    prefix_count < len(ordered)
                    and ordered[prefix_count].role == "superscript"
                ):
                    prefix_count += 1
                if (
                    prefix_count == 0
                    or prefix_count >= len(ordered)
                    or not ordered[prefix_count].text[:1].isalpha()
                ):
                    continue
                remainder = ordered[prefix_count:]
                remainder_text = _selection_fragment_text(
                    remainder,
                    raw=False,
                )
                remainder_box = _bbox_union(
                    character.bbox for character in remainder
                )
                if (
                    remainder_box is None
                    or len(_alignment_skeleton(remainder_text)) < 24
                ):
                    continue
                diagnostic_id = _stable_id(
                    "lexical-subline",
                    source_sha256,
                    public_page.page_index,
                    line.id,
                    remainder_text,
                )
                diagnostics.append(
                    {
                        "id": diagnostic_id,
                        "kind": "lexical_subline",
                        "page_index": public_page.page_index,
                        "text": remainder_text,
                        "bbox": remainder_box.to_dict(),
                        "source_line_ids": [line.id],
                        "source_character_ids": [
                            character.id for character in remainder
                        ],
                        "source_character_indexes": [
                            character.character_index
                            for character in remainder
                        ],
                        "reason": (
                            "geometry_distinct_leading_superscript_excluded"
                        ),
                    }
                )
                if len(diagnostics) >= MAX_CONCERNS:
                    break

        if time.perf_counter() > deadline:
            raise _Refusal("source_alignment_deadline")
        evidence_for_bound = SourceTextEvidence(
            schema_version=SOURCE_TEXT_ALIGNMENT_SCHEMA_VERSION,
            policy_id=SOURCE_TEXT_ALIGNMENT_POLICY_ID,
            source_sha256=source_sha256,
            usable=True,
            refusal_code=None,
            page_count=len(public_pages),
            character_count=sum(
                len(page.characters) for page in public_pages
            ),
            line_count=sum(len(page.lines) for page in public_pages),
            type1_glyph_count=len(type1_glyphs),
            pages=tuple(public_pages),
            type1_glyphs=type1_glyphs,
            diagnostics=tuple(diagnostics),
            # This is the longest compact JSON spelling possible for a
            # non-exhausted, six-decimal millisecond duration below 2 s.
            # It makes the size check conservative without a second pass.
            elapsed_ms=1999.999999,
        )
        _bounded_json_size(
            evidence_for_bound,
            max_bytes=MAX_REPORT_BYTES,
            deadline=deadline,
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 6)
        if elapsed_ms >= MAX_ALIGNMENT_SECONDS * 1000:
            raise _Refusal("source_alignment_deadline")
        return replace(evidence_for_bound, elapsed_ms=elapsed_ms)
    except _Refusal as exc:
        return _refused_evidence(source_sha256, exc.code, started)
    except Exception:
        return _refused_evidence(
            source_sha256,
            "source_alignment_unexpected_failure",
            started,
        )


def _character_emits(
    character: SourceCharacterEvidence,
) -> bool:
    return character.excluded_reason not in {
        "unsafe_unicode",
        "invalid_hyphen_sentinel_bbox",
        "uncorroborated_hyphen_sentinel",
        "ambiguous_type1_geometry",
        "conflicting_type1_geometry",
        "transparent_text",
        "white_icon_overlay",
    }


def _selection_fragment_text(
    characters: Sequence[SourceCharacterEvidence],
    *,
    raw: bool,
) -> str:
    return "".join(
        character.raw_text if raw else character.text
        for character in characters
        if _character_emits(character)
    ).strip(" ")


def _source_roles(
    characters: Sequence[SourceCharacterEvidence],
) -> tuple[dict[str, Any], ...]:
    groups: list[list[SourceCharacterEvidence]] = []
    active: list[SourceCharacterEvidence] = []
    active_role: str | None = None
    for character in characters:
        if character.role is None:
            if active:
                groups.append(active)
                active = []
                active_role = None
            continue
        if (
            active
            and (
                character.role != active_role
                or character.character_index
                > active[-1].character_index + 1
            )
        ):
            groups.append(active)
            active = []
        active.append(character)
        active_role = character.role
    if active:
        groups.append(active)

    output: list[dict[str, Any]] = []
    for group in groups:
        box = _bbox_union(character.bbox for character in group)
        if box is None:
            continue
        output.append(
            {
                "role": group[0].role,
                "text": "".join(
                    character.text
                    for character in group
                    if character.text
                ),
                "page_index": group[0].page_index,
                "bbox": box.to_dict(),
                "source_character_indexes": [
                    character.character_index for character in group
                ],
                "type1_evidence_ids": list(
                    dict.fromkeys(
                        evidence_id
                        for character in group
                        for evidence_id in character.type1_evidence_ids
                    )
                ),
            }
        )
    return tuple(output)


def text_for_bbox(
    evidence: SourceTextEvidence,
    page_index: int,
    bbox: Mapping[str, Any] | SourceBBox,
    *,
    deadline: float | None = None,
) -> SourceTextSelection | None:
    """Reconstruct exact source characters whose centers lie in ``bbox``."""

    if not evidence.usable:
        return None
    owner_box = (
        bbox if isinstance(bbox, SourceBBox) else _mapping_bbox(bbox)
    )
    if owner_box is None:
        return None
    page = next(
        (
            candidate
            for candidate in evidence.pages
            if candidate.page_index == page_index
        ),
        None,
    )
    if page is None:
        return None
    by_id = {
        character.id: character for character in page.characters
    }
    fragments: list[
        tuple[
            SourceTextLine,
            list[SourceCharacterEvidence],
            str,
            str,
        ]
    ] = []
    for line_index, line in enumerate(page.lines, start=1):
        if (
            line_index % 256 == 0
            and deadline is not None
            and time.perf_counter() > deadline
        ):
            raise _Refusal("source_alignment_deadline")
        ordered = [
            by_id[identifier]
            for identifier in line.source_character_ids
            if identifier in by_id
        ]
        physically_selected = [
            index
            for index, character in enumerate(ordered)
            if character.bbox is not None
            and _center_inside(character.bbox, owner_box)
        ]
        if not physically_selected:
            continue
        first = min(physically_selected)
        last = max(physically_selected)
        selected = ordered[first : last + 1]
        if any(
            character.excluded_reason
            in {
                "unsafe_unicode",
                "invalid_hyphen_sentinel_bbox",
                "uncorroborated_hyphen_sentinel",
                "ambiguous_type1_geometry",
                "conflicting_type1_geometry",
            }
            for character in selected
        ):
            return None
        canonical_text = _selection_fragment_text(
            selected,
            raw=False,
        )
        raw_text = _selection_fragment_text(selected, raw=True)
        if canonical_text:
            fragments.append((line, selected, canonical_text, raw_text))

    if not fragments:
        return None
    if deadline is not None and time.perf_counter() > deadline:
        raise _Refusal("source_alignment_deadline")

    canonical_parts: list[str] = []
    raw_parts: list[str] = []
    all_characters: list[SourceCharacterEvidence] = []
    for fragment_index, (line, characters, text, raw_text) in enumerate(
        fragments
    ):
        if fragment_index:
            previous_line, previous_characters, previous_text, _ = (
                fragments[fragment_index - 1]
            )
            if (
                previous_line.terminal_semantic_hyphen
                and previous_text.endswith("-")
            ) or (
                previous_characters
                and previous_characters[-1].raw_text == "-"
                and previous_text.endswith("-")
            ):
                separator = ""
            else:
                separator = " "
            canonical_parts.append(separator)
            raw_parts.append(separator)
        canonical_parts.append(text)
        raw_parts.append(raw_text)
        all_characters.extend(characters)

    text = "".join(canonical_parts)
    raw_text = "".join(raw_parts)
    if (
        not text
        or len(text) > MAX_CANDIDATE_CODEPOINTS
        or any(not _is_printable_source_character(character)
               for character in text if character != " ")
    ):
        return None
    selected_box = _bbox_union(
        character.bbox for character in all_characters
    )
    if selected_box is None:
        return None
    source_line_ids = tuple(
        dict.fromkeys(line.id for line, *_rest in fragments)
    )
    type1_ids = tuple(
        dict.fromkeys(
            evidence_id
            for character in all_characters
            for evidence_id in character.type1_evidence_ids
        )
    )
    semantic_hyphens = [
        character
        for character in all_characters
        if character.pdfium_is_hyphen and character.text == "-"
    ]
    checks = {
        "finite_geometry": True,
        "single_page": True,
        "printable_unicode": True,
        "bounded_candidate": True,
        "source_hash_bound": bool(evidence.source_sha256),
    }
    if semantic_hyphens:
        checks["pdfium_is_hyphen"] = all(
            character.pdfium_is_hyphen
            for character in semantic_hyphens
        )
        checks["same_document_corroboration"] = all(
            bool(character.corroborating_line_ids)
            for character in semantic_hyphens
        )
    return SourceTextSelection(
        text=text,
        raw_text=raw_text,
        bbox=selected_box,
        source_line_ids=source_line_ids,
        source_character_ids=tuple(
            character.id for character in all_characters
        ),
        source_character_indexes=tuple(
            character.character_index for character in all_characters
        ),
        type1_evidence_ids=type1_ids,
        source_roles=_source_roles(all_characters),
        checks=checks,
    )


def _alignment_skeleton(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold())
    return "".join(
        character
        for character in decomposed
        if character.isalnum()
        and unicodedata.category(character) != "Mn"
    )


def _whitespace_normalized(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", unicodedata.normalize("NFC", value)).strip()


def _table_cell_covers_source_fragment(
    fragment: Sequence[SourceCharacterEvidence],
    cell_text: str,
) -> bool:
    """Compare source-owned cell content without promoting layout whitespace.

    Table extraction can insert a separator at a native font-run boundary,
    including immediately before punctuation that the source places directly
    after the preceding run.  That separator is presentation structure rather
    than another source character.  Admit it only when the complete source
    fragment proves the same punctuation at the same position and the two
    adjacent source characters carry distinct, non-empty native font refs.

    All ordinary whitespace retains the existing NFC/collapse contract.  No
    punctuation substitution, missing source boundary, intra-word whitespace,
    or source-to-table deletion is accepted here.
    """

    emitted = [character for character in fragment if _character_emits(character)]
    if len(emitted) > MAX_CANDIDATE_CODEPOINTS:
        return False
    source_text = _whitespace_normalized(
        "".join(character.text for character in emitted)
    )
    canonical_text = _whitespace_normalized(cell_text)
    if source_text == canonical_text:
        return True
    if not source_text or not canonical_text:
        return False

    punctuation_offsets = [
        index
        for index, character in enumerate(source_text)
        if character in _NATIVE_RUN_BOUNDARY_PUNCTUATION
    ]
    punctuation_eligibility: list[bool] = []
    previous: SourceCharacterEvidence | None = None
    for current in emitted:
        normalized_piece = unicodedata.normalize("NFC", current.text)
        for piece_character in normalized_piece:
            if piece_character not in _NATIVE_RUN_BOUNDARY_PUNCTUATION:
                continue
            punctuation_eligibility.append(
                len(normalized_piece) == 1
                and previous is not None
                and bool(previous.text)
                and not previous.text.isspace()
                and isinstance(previous.font_ref, str)
                and bool(previous.font_ref)
                and isinstance(current.font_ref, str)
                and bool(current.font_ref)
                and previous.font_ref != current.font_ref
            )
        previous = current
    if len(punctuation_offsets) != len(punctuation_eligibility):
        return False
    allowed_punctuation_offsets = {
        offset
        for offset, eligible in zip(
            punctuation_offsets,
            punctuation_eligibility,
            strict=True,
        )
        if eligible
    }
    if not allowed_punctuation_offsets:
        return False
    source_index = 0
    canonical_index = 0
    while source_index < len(source_text) and canonical_index < len(
        canonical_text
    ):
        if source_text[source_index] == canonical_text[canonical_index]:
            source_index += 1
            canonical_index += 1
            continue
        if (
            source_index in allowed_punctuation_offsets
            and canonical_text[canonical_index] == " "
            and source_text[source_index]
            in _NATIVE_RUN_BOUNDARY_PUNCTUATION
        ):
            canonical_index += 1
            continue
        return False
    return source_index == len(source_text) and canonical_index == len(
        canonical_text
    )


def _single_substitution(first: str, second: str) -> bool:
    return (
        3 <= len(first) == len(second) <= 8
        and sum(a != b for a, b in zip(first, second, strict=True)) == 1
    )


def _substring_count(haystack: str, needle: str) -> int:
    if not needle:
        return 0
    count = 0
    start = 0
    while True:
        index = haystack.find(needle, start)
        if index < 0:
            return count
        count += 1
        start = index + 1


def _selection_characters(
    evidence: SourceTextEvidence,
    selection: SourceTextSelection,
) -> list[SourceCharacterEvidence]:
    identifiers = set(selection.source_character_ids)
    return [
        character
        for page in evidence.pages
        for character in page.characters
        if character.id in identifiers
    ]


def _layout_projection_text(
    evidence: SourceTextEvidence,
    selection: SourceTextSelection,
) -> str:
    characters = sorted(
        _selection_characters(evidence, selection),
        key=lambda character: character.character_index,
    )
    return "".join(
        character.raw_text
        for character in characters
        if character.excluded_reason
        not in {
            "unsafe_unicode",
            "invalid_hyphen_sentinel_bbox",
            "uncorroborated_hyphen_sentinel",
            "transparent_text",
        }
    )


def _whitespace_gap_positions(value: str) -> frozenset[int]:
    """Positions in the non-whitespace projection preceded by whitespace."""

    gaps: set[int] = set()
    compact_index = 0
    in_whitespace = False
    for character in value:
        if character.isspace():
            in_whitespace = compact_index > 0
            continue
        if in_whitespace:
            gaps.add(compact_index)
        compact_index += 1
        in_whitespace = False
    return frozenset(gaps)


def _add_source_proven_whitespace(
    original: str,
    source_selection: str,
    *,
    supported_gap_positions: frozenset[int],
) -> str | None:
    """Insert only missing source whitespace while preserving prior layout.

    Running-region owners can contain deliberate newlines or other whitespace
    selected by an earlier layout stage.  Native source evidence may prove an
    additional encoded word boundary, but it does not authorize rewriting
    those already-present separators.  Require exact non-whitespace content
    (including case, punctuation, and codepoints), then add only the source
    gaps absent from the owner.
    """

    if (
        not isinstance(original, str)
        or not isinstance(source_selection, str)
        or not isinstance(supported_gap_positions, frozenset)
        or not original
        or not source_selection
        or "".join(original.split()) != "".join(source_selection.split())
    ):
        return None
    original_gaps = _whitespace_gap_positions(original)
    source_gaps = _whitespace_gap_positions(source_selection)
    if not original_gaps < source_gaps:
        return None
    missing_gaps = source_gaps - original_gaps
    if not missing_gaps <= supported_gap_positions:
        return None
    output: list[str] = []
    compact_index = 0
    for character in original:
        if character.isspace():
            output.append(character)
            continue
        if compact_index in missing_gaps:
            output.append(" ")
        output.append(character)
        compact_index += 1
    repaired = "".join(output)
    if (
        repaired == original
        or "".join(repaired.split()) != "".join(original.split())
        or _whitespace_gap_positions(repaired) != source_gaps
    ):
        return None
    return repaired


def _supported_source_space_gap_positions(
    evidence: SourceTextEvidence,
    selection: SourceTextSelection,
) -> frozenset[int]:
    """Return compact offsets backed by selected encoded U+0020 characters."""

    characters = sorted(
        _selection_characters(evidence, selection),
        key=lambda character: character.character_index,
    )
    gaps: set[int] = set()
    compact_index = 0
    in_whitespace = False
    supported = False
    for character in characters:
        if not _character_emits(character):
            continue
        for value in character.text:
            if value.isspace():
                in_whitespace = compact_index > 0
                supported = supported or bool(
                    value == " "
                    and character.raw_text == " "
                    and character.raw_code_point == 0x20
                    and character.space_supported
                )
                continue
            if in_whitespace and supported:
                gaps.add(compact_index)
            compact_index += 1
            in_whitespace = False
            supported = False
    return frozenset(gaps)


def _source_space_nested_repairs(
    item: Mapping[str, Any],
    *,
    evidence: SourceTextEvidence,
    page_index: int,
    owner_box: SourceBBox,
    original_text: str,
    selected_text: str,
    outer_selection: SourceTextSelection,
    reserve_candidates: Callable[[int], None],
    deadline: float,
) -> tuple[list[dict[str, Any]] | None, tuple[int, ...]] | None:
    """Repair only uniquely partitioned native children of a running owner."""

    if "items" not in item:
        return (None, ())
    raw_children = item.get("items")
    if not isinstance(raw_children, list) or len(raw_children) > MAX_EVIDENCE_REFS:
        return None
    if not raw_children:
        return (None, ())

    original_compact = "".join(original_text.split())
    selected_compact = "".join(selected_text.split())
    missing_gaps = _whitespace_gap_positions(selected_text) - (
        _whitespace_gap_positions(original_text)
    )
    if not original_compact or original_compact != selected_compact or not missing_gaps:
        return None

    children: list[dict[str, Any]] = []
    intervals: list[tuple[int, int]] = []
    boxes: list[SourceBBox] = []
    compact_cursor = 0
    for raw_child in raw_children:
        if not isinstance(raw_child, Mapping):
            return None
        child = copy.deepcopy(dict(raw_child))
        child_value = child.get("value")
        child_box = _mapping_bbox_in_unit(child.get("bbox"), owner_box.unit)
        child_compact = (
            "".join(child_value.split()) if isinstance(child_value, str) else ""
        )
        if (
            child.get("type") not in {"text", "heading", "code", "formula"}
            or child.get("source") != "native"
            or not isinstance(child_value, str)
            or not child_value
            or child.get("md") != child_value
            or not child_compact
            or child_box is None
            or child_box.x < owner_box.x - 0.05
            or child_box.y < owner_box.y - 0.05
            or child_box.x + child_box.width
            > owner_box.x + owner_box.width + 0.05
            or child_box.y + child_box.height
            > owner_box.y + owner_box.height + 0.05
        ):
            return None
        start = compact_cursor
        compact_cursor += len(child_compact)
        intervals.append((start, compact_cursor))
        boxes.append(child_box)
        children.append(child)
    if (
        compact_cursor != len(original_compact)
        or "".join("".join(str(child["value"]).split()) for child in children)
        != original_compact
    ):
        return None

    affected: dict[int, set[int]] = defaultdict(set)
    for gap in missing_gaps:
        matches = [
            (index, start)
            for index, (start, end) in enumerate(intervals)
            if start < gap < end
        ]
        if len(matches) != 1:
            return None
        child_index, start = matches[0]
        affected[child_index].add(gap - start)
    if not affected:
        return None

    outer_source_ids = set(outer_selection.source_character_ids)
    claimed_source_ids: set[str] = set()
    for child_index in sorted(affected):
        reserve_candidates(1)
        child = children[child_index]
        child_box = boxes[child_index]
        child_selection = text_for_bbox(
            evidence,
            page_index,
            child_box,
            deadline=deadline,
        )
        if (
            child_selection is None
            or _overlap_of_smaller(child_box, child_selection.bbox)
            < MIN_OCR_RECIPROCAL_OVERLAP
            or not set(child_selection.source_character_ids) <= outer_source_ids
            or claimed_source_ids.intersection(child_selection.source_character_ids)
        ):
            return None
        repaired = _add_source_proven_whitespace(
            str(child["value"]),
            child_selection.text,
            supported_gap_positions=_supported_source_space_gap_positions(
                evidence,
                child_selection,
            ),
        )
        if (
            repaired is None
            or _whitespace_gap_positions(repaired)
            - _whitespace_gap_positions(str(child["value"]))
            != affected[child_index]
        ):
            return None
        claimed_source_ids.update(child_selection.source_character_ids)
        _refresh_text_item(child, repaired)
        child["source"] = "native"

    return children, tuple(sorted(affected))


def _selection_method(
    evidence: SourceTextEvidence,
    selection: SourceTextSelection,
    original: str,
) -> tuple[str, dict[str, bool]] | None:
    characters = _selection_characters(evidence, selection)
    checks = dict(selection.checks)
    if selection.type1_evidence_ids:
        leading = next(
            (
                character
                for character in characters
                if character.raw_text.strip()
                and character.excluded_reason is None
            ),
            None,
        )
        if leading is None or not leading.type1_evidence_ids:
            return None
        checks["closed_glyph_allowlist"] = True
        checks["font_cid_geometry_match"] = True
        return "type1_encoding_differences", checks
    if any(
        character.pdfium_is_hyphen and character.text == "-"
        for character in characters
    ):
        checks["pdfium_is_hyphen"] = True
        checks["same_document_corroboration"] = all(
            bool(character.corroborating_line_ids)
            for character in characters
            if character.pdfium_is_hyphen and character.text == "-"
        )
        return "pdfium_semantic_hyphen", checks
    if any(
        character.excluded_reason == "spacing_diaeresis_composed"
        for character in characters
    ):
        checks["same_font_run"] = True
        checks["mark_overlap"] = True
        checks["nfc_composition"] = True
        return "pdfium_spacing_diaeresis", checks
    if any(
        character.excluded_reason == "white_icon_overlay"
        for character in characters
    ):
        checks["fill_color_grounded"] = True
        checks["tight_nontext_enclosure"] = True
        return "pdfium_nonlexical_overlay", checks

    without_space_original = "".join(original.split())
    without_space_selected = "".join(selection.text.split())
    if (
        without_space_original == without_space_selected
        and _whitespace_gap_positions(original)
        < _whitespace_gap_positions(selection.text)
    ):
        changed_spaces = [
            character
            for character in characters
            if character.raw_code_point == 0x20
            and character.space_supported
        ]
        if changed_spaces:
            checks["encoded_u0020"] = True
            checks["space_geometry"] = True
            return "pdfium_source_space", checks
    source_quotes = re.findall(r"[“”‘’]", selection.text)
    legacy_pairs = re.findall(r"(['\"])\s+([^'\"]*?)\s+\1", original)
    source_quote_pairs = len(source_quotes) // 2
    legacy_quote_pairs = len(legacy_pairs)
    source_interiors = re.findall(r"[“‘]([^”’]*)[”’]", selection.text)
    legacy_interiors = [interior for _quote, interior in legacy_pairs]
    exact_pair_projection = (
        source_quote_pairs >= 1
        and source_quote_pairs == legacy_quote_pairs
        and len(source_quotes) == source_quote_pairs * 2
        and len(source_interiors) == source_quote_pairs
        and len(legacy_interiors) == legacy_quote_pairs
        and source_interiors == legacy_interiors
        and all(
            source_quotes[index] in {"“", "‘"}
            and source_quotes[index + 1] in {"”", "’"}
            for index in range(0, len(source_quotes), 2)
        )
    )
    # The five-pair opening paragraph is an already reviewed historical
    # target.  New low-density recovery is capped at three pairs, but both
    # paths now require the same exact source pairing and unchanged interiors.
    high_density_defined_terms = (
        source_quote_pairs >= 4 and exact_pair_projection
    )
    exact_low_density_pairs = (
        1 <= source_quote_pairs <= 3 and exact_pair_projection
    )
    if high_density_defined_terms or exact_low_density_pairs:
        checks["literal_source_punctuation"] = True
        checks["unique_owner_alignment"] = True
        if exact_low_density_pairs:
            checks["paired_source_quotes"] = True
            checks["unchanged_quote_interiors"] = True
        return "pdfium_native_text", checks
    if "−" in selection.text and re.search(r"(?:^|[\s(])- ?", original):
        # The initial exit repair is intentionally limited to the malformed
        # comma-decimal cell; ordinary minus rows remain unchanged until a
        # separately reviewed table policy covers them.
        if not re.search(r"\d,\d", selection.text):
            return None
        checks["literal_source_minus"] = True
        checks["unique_owner_alignment"] = True
        return "pdfium_native_text", checks
    return None


def _page_projection_skeleton(
    page: SourcePageEvidence,
    *,
    include_excluded_overlay: bool,
) -> str:
    values: list[str] = []
    for character in page.characters:
        if character.excluded_reason in {
            "unsafe_unicode",
            "invalid_hyphen_sentinel_bbox",
            "uncorroborated_hyphen_sentinel",
            "transparent_text",
        }:
            continue
        if (
            not include_excluded_overlay
            and character.excluded_reason == "white_icon_overlay"
        ):
            continue
        values.append(
            character.raw_text
            if include_excluded_overlay
            else character.text
        )
    return _alignment_skeleton("".join(values))


def _selection_projection_skeletons(
    evidence: SourceTextEvidence,
    selection: SourceTextSelection,
) -> set[str]:
    characters = sorted(
        _selection_characters(evidence, selection),
        key=lambda character: character.character_index,
    )
    variants = [""]
    for character in characters:
        if character.excluded_reason in {
            "unsafe_unicode",
            "invalid_hyphen_sentinel_bbox",
            "uncorroborated_hyphen_sentinel",
            "transparent_text",
        }:
            continue
        options = [character.text]
        if character.type1_evidence_ids:
            options.append(character.raw_text)
        elif character.excluded_reason == "white_icon_overlay":
            options = ["", character.raw_text]
        options = list(dict.fromkeys(options))
        expanded = [
            prefix + option
            for prefix in variants
            for option in options
        ]
        # The policy permits at most eight candidates per owner.
        variants = expanded[:MAX_CANDIDATES_PER_OWNER]
    return {
        _alignment_skeleton(variant)
        for variant in variants
    }


def _selection_unique_on_page(
    page: SourcePageEvidence,
    original: str,
    selection: SourceTextSelection,
    projection_text: str,
    *,
    reserve_candidates: Callable[[int], None] | None = None,
) -> bool:
    old_skeleton = _alignment_skeleton(original)
    candidate_skeletons = {
        _alignment_skeleton(selection.text),
        _alignment_skeleton(selection.raw_text),
        _alignment_skeleton(projection_text),
    }
    projection_skeletons = _selection_projection_skeletons(
        SourceTextEvidence(
            schema_version="",
            policy_id="",
            source_sha256="",
            usable=True,
            refusal_code=None,
            page_count=1,
            character_count=len(page.characters),
            line_count=len(page.lines),
            type1_glyph_count=0,
            pages=(page,),
            type1_glyphs=(),
            diagnostics=(),
            elapsed_ms=0,
        ),
        selection,
    )
    candidate_skeletons.update(projection_skeletons)
    if reserve_candidates is not None:
        # Raw/canonical/layout skeletons are evidence projections of the same
        # bounded source candidates, not additional candidate texts.
        reserve_candidates(max(len(projection_skeletons), 1))
    if (
        len(old_skeleton) < 3
        or old_skeleton not in candidate_skeletons
    ):
        return False
    if selection.type1_evidence_ids:
        # Geometry has already selected one owner.  Mixed raw/recovered
        # Type1 projections (for example a damaged note marker plus OCR-fixed
        # ligatures) do not necessarily occur as a whole-page raw or whole-
        # page canonical string; the bounded per-owner variant proves them.
        return True
    page_skeletons = {
        _page_projection_skeleton(
            page,
            include_excluded_overlay=False,
        ),
        _page_projection_skeleton(
            page,
            include_excluded_overlay=True,
        ),
    }
    return any(
        _substring_count(page_skeleton, old_skeleton) == 1
        for page_skeleton in page_skeletons
    )


def _selection_id(
    source_sha256: str,
    page_index: int,
    owner_id: str,
    original: str,
    selected: str,
) -> str:
    return _stable_id(
        "alignment",
        source_sha256,
        page_index,
        owner_id,
        original,
        selected,
    )


def _trace_for_selection(
    selection: AlignmentSelection,
    source_sha256: str,
) -> dict[str, Any]:
    return {
        "schema_version": SOURCE_TEXT_ALIGNMENT_SCHEMA_VERSION,
        "policy_id": SOURCE_TEXT_ALIGNMENT_POLICY_ID,
        "source_sha256": source_sha256,
        "selection_id": selection.id,
        "original_text": selection.original_text,
        "selected_text": selection.selected_text,
        "selected_source": selection.selected_source,
        "source_line_ids": list(selection.source_line_ids),
        "source_character_ids": list(selection.source_character_ids),
        "type1_mapping_ids": list(selection.type1_mapping_ids),
        "source_roles": _json_safe(selection.source_roles),
        "method": selection.method,
        "checks": dict(selection.checks),
        "terminal_reason": selection.terminal_reason,
        "rejected_ocr_alternative": _json_safe(
            selection.rejected_ocr_alternative
        ),
    }


def _refresh_text_item(
    item: dict[str, Any],
    selected_text: str,
) -> None:
    item["value"] = selected_text
    if item.get("type") == "heading":
        try:
            level = min(max(int(item.get("level") or 1), 1), 6)
        except (TypeError, ValueError):
            level = 1
        item["md"] = f"{'#' * level} {selected_text}"
    else:
        item["md"] = selected_text


def _table_csv(rows: Sequence[Sequence[str]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerows(rows)
    return output.getvalue().rstrip("\n")


def _table_html(
    rows: Sequence[Sequence[str]],
    cells: Sequence[Mapping[str, Any]],
) -> str:
    if not cells:
        lines = ["<table>"]
        for row_index, row in enumerate(rows):
            tag = "th" if row_index == 0 and len(rows) > 1 else "td"
            lines.append("  <tr>")
            lines.extend(
                f"    <{tag}>{html.escape(str(value)).replace(chr(10), '<br>')}</{tag}>"
                for value in row
            )
            lines.append("  </tr>")
        lines.append("</table>")
        return "\n".join(lines)

    by_position = {
        (
            max(int(cell.get("row", 0)), 0),
            max(int(cell.get("column", 0)), 0),
        ): cell
        for cell in cells
    }
    row_count = max(
        len(rows),
        max(
            (
                row + max(int(cell.get("row_span", 1)), 1)
                for (row, _column), cell in by_position.items()
            ),
            default=0,
        ),
    )
    column_count = max(
        max((len(row) for row in rows), default=0),
        max(
            (
                column + max(int(cell.get("col_span", 1)), 1)
                for (_row, column), cell in by_position.items()
            ),
            default=0,
        ),
    )
    header_rows = 0
    for row_index in range(row_count):
        row_cells = [
            cell
            for (row, _column), cell in by_position.items()
            if row == row_index
        ]
        if row_cells and all(cell.get("column_header") for cell in row_cells):
            header_rows += 1
        else:
            break
    covered: set[tuple[int, int]] = set()

    def render_row(row_index: int, header: bool) -> list[str]:
        rendered = ["    <tr>"]
        for column_index in range(column_count):
            if (row_index, column_index) in covered:
                continue
            cell = by_position.get((row_index, column_index))
            tag = "th" if header or (cell and cell.get("column_header")) else "td"
            if cell is None:
                rendered.append(f"      <{tag}></{tag}>")
                continue
            row_span = max(int(cell.get("row_span", 1)), 1)
            col_span = max(int(cell.get("col_span", 1)), 1)
            for row_offset in range(row_span):
                for column_offset in range(col_span):
                    if row_offset or column_offset:
                        covered.add(
                            (
                                row_index + row_offset,
                                column_index + column_offset,
                            )
                        )
            attributes = (
                (f' rowspan="{row_span}"' if row_span > 1 else "")
                + (f' colspan="{col_span}"' if col_span > 1 else "")
            )
            escaped = html.escape(str(cell.get("text") or "")).replace(
                "\n", "<br>"
            )
            rendered.append(
                f"      <{tag}{attributes}>{escaped}</{tag}>"
            )
        rendered.append("    </tr>")
        return rendered

    lines = ["<table>"]
    if header_rows:
        lines.append("  <thead>")
        for row_index in range(header_rows):
            lines.extend(render_row(row_index, True))
        lines.append("  </thead>")
    if row_count > header_rows:
        lines.append("  <tbody>")
        for row_index in range(header_rows, row_count):
            lines.extend(render_row(row_index, False))
        lines.append("  </tbody>")
    lines.append("</table>")
    return "\n".join(lines)


def _refresh_table(table: dict[str, Any]) -> None:
    rows = [
        [str(value or "") for value in row]
        for row in (table.get("rows") or table.get("value") or [])
    ]
    cells = [
        cell
        for cell in (table.get("cells") or [])
        if isinstance(cell, Mapping)
    ]
    rendered = _table_html(rows, cells)
    table["rows"] = rows
    table["value"] = copy.deepcopy(rows)
    table["html"] = rendered
    table["md"] = rendered
    table["csv"] = _table_csv(rows)
    table_evidence = table.get("table_evidence")
    if isinstance(table_evidence, Mapping):
        from app.services.table_semantics import replay_table_semantics

        replay_table_semantics(table, table_evidence)


def _complete_source_line_for_token(
    page: SourcePageEvidence,
    selection: SourceTextSelection,
    *,
    deadline: float | None = None,
) -> SourceTextLine | None:
    token = selection.text.strip()
    if (
        not token.isalpha()
        or not token.isupper()
        or not 3 <= len(token) <= 8
    ):
        return None
    candidates: list[SourceTextLine] = []
    for line_index, line in enumerate(page.lines, start=1):
        if (
            line_index % 256 == 0
            and deadline is not None
            and time.perf_counter() > deadline
        ):
            raise _Refusal("source_alignment_deadline")
        if (
            not line.has_unsafe_character
            and line.text.startswith(f"{token} ")
            and len(line.text.split()) >= 3
            and line.id in selection.source_line_ids
        ):
            candidates.append(line)
            if len(candidates) > 1:
                return None
    return candidates[0] if len(candidates) == 1 else None


def _page_canonical_text(page: Mapping[str, Any]) -> str:
    values: list[str] = []
    for item in page.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        if item.get("type") == "table":
            rows = item.get("rows") or item.get("value") or []
            values.extend(
                " ".join(str(cell or "") for cell in row)
                for row in rows
                if isinstance(row, Sequence)
                and not isinstance(row, (str, bytes))
            )
        elif isinstance(item.get("value"), str):
            values.append(str(item["value"]))
    return "\n".join(values)


def _selection_from_line(
    page: SourcePageEvidence,
    line: SourceTextLine,
) -> SourceTextSelection:
    by_id = {
        character.id: character for character in page.characters
    }
    characters = [
        by_id[identifier]
        for identifier in line.source_character_ids
        if identifier in by_id
    ]
    checks = {
        "finite_geometry": True,
        "single_page": True,
        "printable_unicode": True,
        "bounded_candidate": len(line.text)
        <= MAX_CANDIDATE_CODEPOINTS,
        "source_hash_bound": True,
    }
    return SourceTextSelection(
        text=line.text,
        raw_text=line.raw_text,
        bbox=line.bbox,
        source_line_ids=(line.id,),
        source_character_ids=tuple(line.source_character_ids),
        source_character_indexes=tuple(line.source_character_indexes),
        type1_evidence_ids=tuple(line.type1_evidence_ids),
        source_roles=_source_roles(characters),
        checks=checks,
    )


def supplemental_ocr_owner_is_attributable(
    item: Mapping[str, Any],
    *,
    page_index: int,
    source_sha256: str,
) -> bool:
    """Authenticate one pipeline-issued supplemental page-OCR owner."""

    value = item.get("value")
    confidence = item.get("confidence")
    concerns = item.get("parse_concerns")
    raw_ocr_text = item.get("raw_ocr_text")
    owner_box = _mapping_bbox_in_unit(item.get("bbox"), "pt")
    contributor = (
        _validated_supplemental_ocr_contributor(
            item.get("ocr_contributor"),
            source_sha256=source_sha256,
            page_index=page_index,
            owner_box=owner_box,
            raw_text=raw_ocr_text,
            confidence=float(confidence),
        )
        if owner_box is not None
        and isinstance(raw_ocr_text, str)
        and isinstance(confidence, (int, float))
        and not isinstance(confidence, bool)
        and math.isfinite(float(confidence))
        else None
    )
    return bool(
        item.get("type") == "text"
        and item.get("source") == "ocr"
        and item.get("label") == "ocr_text"
        and isinstance(value, str)
        and value
        and isinstance(raw_ocr_text, str)
        and raw_ocr_text
        and unicodedata.normalize("NFC", raw_ocr_text)
        == unicodedata.normalize("NFC", value)
        and isinstance(confidence, (int, float))
        and not isinstance(confidence, bool)
        and math.isfinite(float(confidence))
        and 0.0 <= float(confidence) <= 1.0
        and isinstance(concerns, Sequence)
        and not isinstance(concerns, (str, bytes, bytearray))
        and "layout_omission_recovered_by_ocr" in concerns
        and contributor is not None
    )


def _supplemental_ocr_lineage_is_complete(
    item: Mapping[str, Any],
    original_text: str,
    *,
    page_index: int,
    source_sha256: str,
) -> bool:
    """Admit only the page-source OCR fallback issued by this pipeline."""

    raw_ocr_text = item.get("raw_ocr_text")
    return bool(
        supplemental_ocr_owner_is_attributable(
            item,
            page_index=page_index,
            source_sha256=source_sha256,
        )
        and isinstance(raw_ocr_text, str)
        and unicodedata.normalize("NFC", raw_ocr_text)
        == unicodedata.normalize("NFC", original_text)
    )


def _promoted_supplemental_heading_shape(
    item: Mapping[str, Any],
    original_text: str,
    *,
    page_index: int,
    source_sha256: str,
) -> dict[str, Any] | None:
    """Seal the one exact pipeline promotion allowed into table proof."""

    raw_ocr_text = item.get("raw_ocr_text")
    confidence = item.get("confidence")
    owner_box = _mapping_bbox_in_unit(item.get("bbox"), "pt")
    concerns = item.get("parse_concerns")
    contributor = (
        _validated_supplemental_ocr_contributor(
            item.get("ocr_contributor"),
            source_sha256=source_sha256,
            page_index=page_index,
            owner_box=owner_box,
            raw_text=raw_ocr_text,
            confidence=float(confidence),
        )
        if owner_box is not None
        and isinstance(raw_ocr_text, str)
        and isinstance(confidence, (int, float))
        and not isinstance(confidence, bool)
        and math.isfinite(float(confidence))
        else None
    )
    if (
        item.get("type") != "heading"
        or item.get("label") != "inferred_heading"
        or type(item.get("level")) is not int
        or item.get("level") != 1
        or item.get("source") != "ocr"
        or item.get("value") != original_text
        or item.get("md") != f"# {original_text}"
        or not isinstance(raw_ocr_text, str)
        or unicodedata.normalize("NFC", raw_ocr_text)
        != unicodedata.normalize("NFC", original_text)
        or not isinstance(concerns, Sequence)
        or isinstance(concerns, (str, bytes, bytearray))
        or tuple(concerns) != _PROMOTED_SUPPLEMENTAL_HEADING_CONCERNS
        or contributor is None
    ):
        return None
    return {
        "type": "heading",
        "label": "inferred_heading",
        "level": 1,
        "source": "ocr",
        "value": original_text,
        "md": f"# {original_text}",
        "raw_ocr_text": raw_ocr_text,
        "parse_concerns": list(_PROMOTED_SUPPLEMENTAL_HEADING_CONCERNS),
    }


def _validated_promoted_supplemental_heading_shape(
    value: Any,
    *,
    original_text: str,
) -> bool:
    if not isinstance(value, Mapping):
        return False
    return bool(
        set(value)
        == {
            "type",
            "label",
            "level",
            "source",
            "value",
            "md",
            "raw_ocr_text",
            "parse_concerns",
        }
        and value.get("type") == "heading"
        and value.get("label") == "inferred_heading"
        and type(value.get("level")) is int
        and value.get("level") == 1
        and value.get("source") == "ocr"
        and value.get("value") == original_text
        and value.get("md") == f"# {original_text}"
        and isinstance(value.get("raw_ocr_text"), str)
        and unicodedata.normalize("NFC", value["raw_ocr_text"])
        == unicodedata.normalize("NFC", original_text)
        and value.get("parse_concerns")
        == list(_PROMOTED_SUPPLEMENTAL_HEADING_CONCERNS)
    )


def _table_owned_supplemental_candidate_lineage(
    item: Mapping[str, Any],
    original_text: str,
    *,
    page_index: int,
    source_sha256: str,
) -> tuple[bool, dict[str, Any] | None]:
    if _supplemental_ocr_lineage_is_complete(
        item,
        original_text,
        page_index=page_index,
        source_sha256=source_sha256,
    ):
        return True, None
    promoted_shape = _promoted_supplemental_heading_shape(
        item,
        original_text,
        page_index=page_index,
        source_sha256=source_sha256,
    )
    return promoted_shape is not None, promoted_shape


def _complete_source_line_for_table_candidate(
    page: SourcePageEvidence,
    selection: SourceTextSelection,
    *,
    deadline: float | None = None,
) -> SourceTextLine | None:
    """Resolve a token or full-line selection to one complete source line.

    This broader resolver is destructive only when the resulting line later
    receives unique, complete table-cell ownership.  The older acronym-only
    resolver remains the boundary for non-table source-line expansion.
    """

    selected = _whitespace_normalized(selection.text)
    selected_character_ids = tuple(selection.source_character_ids)
    if not selected or not selected_character_ids:
        return None
    line_ids = set(selection.source_line_ids)
    candidates: list[SourceTextLine] = []
    for line_index, line in enumerate(page.lines, start=1):
        if (
            line_index % 256 == 0
            and deadline is not None
            and time.perf_counter() > deadline
        ):
            raise _Refusal("source_alignment_deadline")
        line_text = _whitespace_normalized(line.text)
        line_character_ids = tuple(line.source_character_ids)
        try:
            selected_start = line_character_ids.index(
                selected_character_ids[0]
            )
        except ValueError:
            continue
        if (
            line.id not in line_ids
            or line.has_unsafe_character
            or not line_text
            or len(line_text.split()) < 2
            or len(line_character_ids) != len(set(line_character_ids))
            or line_character_ids[
                selected_start : selected_start + len(selected_character_ids)
            ]
            != selected_character_ids
        ):
            continue
        candidates.append(line)
        if len(candidates) > 1:
            return None
    return candidates[0] if len(candidates) == 1 else None


def _admit_authoritative_table_views(
    value: Mapping[int, Sequence[Mapping[str, Any]]] | None,
    evidence: SourceTextEvidence,
    *,
    deadline: float,
) -> dict[int, tuple[dict[str, Any], ...]]:
    """Copy and validate read-only P04 authority views fail closed."""

    if value is None:
        return {}
    if not isinstance(value, Mapping) or len(value) > MAX_SCANNED_OWNERS:
        raise _Refusal("source_alignment_table_authority_views_invalid")

    from app.services.table_semantics import validate_table_semantics

    source_page_indexes = {page.page_index for page in evidence.pages}
    admitted: dict[int, tuple[dict[str, Any], ...]] = {}
    scanned = 0
    for raw_page_index, raw_tables in value.items():
        if (
            not isinstance(raw_page_index, int)
            or isinstance(raw_page_index, bool)
            or raw_page_index not in source_page_indexes
            or not isinstance(raw_tables, Sequence)
            or isinstance(raw_tables, (str, bytes, bytearray))
            or len(raw_tables) > MAX_SCANNED_OWNERS
        ):
            raise _Refusal("source_alignment_table_authority_views_invalid")
        page_tables: list[dict[str, Any]] = []
        for raw_table in raw_tables:
            scanned += 1
            if scanned > MAX_SCANNED_OWNERS:
                raise _Refusal("source_alignment_owner_scan_limit")
            if scanned % 64 == 0 and time.perf_counter() > deadline:
                raise _Refusal("source_alignment_deadline")
            if not isinstance(raw_table, Mapping):
                raise _Refusal("source_alignment_table_authority_view_invalid")
            try:
                table = copy.deepcopy(dict(raw_table))
            except (MemoryError, RecursionError, TypeError, ValueError) as exc:
                raise _Refusal(
                    "source_alignment_table_authority_view_invalid"
                ) from exc
            sidecar = table.get("table_evidence")
            gate = sidecar.get("gate") if isinstance(sidecar, Mapping) else None
            if (
                table.get("type") != "table"
                or not isinstance(sidecar, Mapping)
                or sidecar.get("status") != "valid"
                or sidecar.get("page_index") != raw_page_index
                or not isinstance(gate, Mapping)
                or gate.get("outcome") != "canonical_table"
                or not validate_table_semantics(
                    table,
                    evidence.source_sha256,
                )
            ):
                # These views come only from the internally owned P04 detach
                # transaction.  A malformed or non-authoritative member makes
                # the whole optional deletion proof unusable; mixing it with a
                # valid owner could otherwise conceal an ownership ambiguity.
                raise _Refusal(
                    "source_alignment_table_authority_view_invalid"
                )
            cells = table.get("cells")
            if not isinstance(cells, list):
                raise _Refusal(
                    "source_alignment_table_authority_view_invalid"
                )
            scanned += len(cells)
            if scanned > MAX_SCANNED_OWNERS:
                raise _Refusal("source_alignment_owner_scan_limit")
            page_tables.append(table)
        if page_tables:
            admitted[raw_page_index] = tuple(page_tables)
    if time.perf_counter() > deadline:
        raise _Refusal("source_alignment_deadline")
    return admitted


def _ordered_unique_strings(values: Iterable[Any]) -> tuple[str, ...] | None:
    observed: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value:
            return None
        if value not in seen:
            observed.append(value)
            seen.add(value)
    return tuple(observed)


def _structural_table_line_candidates(
    *,
    source_page: SourcePageEvidence,
    complete_line: SourceTextLine,
    tables: Sequence[Mapping[str, Any]],
    deadline: float,
) -> tuple[_TableOwnedStructuralLineCandidate, ...]:
    """Build owner-independent row proofs for one complete source line."""

    by_character_id = {
        character.id: character for character in source_page.characters
    }
    characters = [
        by_character_id.get(identifier)
        for identifier in complete_line.source_character_ids
    ]
    if (
        not characters
        or any(character is None for character in characters)
        or complete_line.page_index != source_page.page_index
        or complete_line.bbox.unit != "pt"
    ):
        return ()
    emitted_characters = [
        character
        for character in characters
        if character is not None and _character_emits(character)
    ]
    substantive_characters = [
        character
        for character in emitted_characters
        if character.text and not character.text.isspace()
    ]
    if not substantive_characters:
        return ()

    candidates: list[_TableOwnedStructuralLineCandidate] = []
    scanned_rows = 0
    for view_order, table in enumerate(tables):
        if time.perf_counter() > deadline:
            raise _Refusal("source_alignment_deadline")
        sidecar = table.get("table_evidence")
        table_box_value = table.get("bbox")
        table_box = _mapping_bbox(table_box_value)
        rows = table.get("rows") or table.get("value")
        cells = table.get("cells")
        if (
            not isinstance(sidecar, Mapping)
            or sidecar.get("page_index") != source_page.page_index
            or not isinstance(table_box_value, Mapping)
            or table_box_value.get("unit") != "pt"
            or table_box is None
            or not isinstance(rows, Sequence)
            or isinstance(rows, (str, bytes, bytearray))
            or not isinstance(cells, list)
        ):
            continue
        table_item_id = table.get("id")
        table_id = sidecar.get("table_id")
        candidate_id = sidecar.get("candidate_id")
        if not all(
            isinstance(value, str) and value
            for value in (table_item_id, table_id, candidate_id)
        ):
            continue
        source_objects = sidecar.get("source_objects")
        evidence_records = sidecar.get("evidence")
        if not isinstance(source_objects, list) or not isinstance(
            evidence_records, list
        ):
            continue
        source_by_id = {
            record.get("id"): record
            for record in source_objects
            if isinstance(record, Mapping)
            and isinstance(record.get("id"), str)
        }
        evidence_by_id = {
            record.get("id"): record
            for record in evidence_records
            if isinstance(record, Mapping)
            and isinstance(record.get("id"), str)
        }
        cells_by_row: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
        for cell in cells:
            if not isinstance(cell, Mapping):
                continue
            row_index = cell.get("row")
            if isinstance(row_index, int) and not isinstance(row_index, bool):
                cells_by_row[row_index].append(cell)

        for row_index in sorted(cells_by_row):
            scanned_rows += 1
            if scanned_rows > MAX_SCANNED_OWNERS:
                raise _Refusal("source_alignment_owner_scan_limit")
            if scanned_rows % 128 == 0 and time.perf_counter() > deadline:
                raise _Refusal("source_alignment_deadline")
            if not 0 <= row_index < len(rows):
                continue
            row_value = rows[row_index]
            if (
                not isinstance(row_value, Sequence)
                or isinstance(row_value, (str, bytes, bytearray))
            ):
                continue
            row_cells = sorted(
                cells_by_row[row_index],
                key=lambda cell: (
                    cell.get("column")
                    if isinstance(cell.get("column"), int)
                    else MAX_SCANNED_OWNERS
                ),
            )
            if len(row_cells) < 2 or len(row_cells) != len(row_value):
                continue

            cell_boxes: list[SourceBBox] = []
            cell_ids: list[str] = []
            cell_source_ids: list[tuple[str, ...]] = []
            cell_evidence_ids: list[tuple[str, ...]] = []
            structurally_complete = True
            for expected_column, cell in enumerate(row_cells):
                cell_box_value = cell.get("bbox")
                cell_box = _mapping_bbox(cell_box_value)
                source_ids = _ordered_unique_strings(
                    cell.get("source_object_ids") or ()
                )
                evidence_ids = _ordered_unique_strings(
                    cell.get("evidence_ids") or ()
                )
                if (
                    cell.get("column") != expected_column
                    or cell.get("row_span") != 1
                    or cell.get("col_span") != 1
                    or cell.get("source") != "native"
                    or cell.get("page_index") != source_page.page_index
                    or not isinstance(cell_box_value, Mapping)
                    or cell_box_value.get("unit") != "pt"
                    or cell_box is None
                    or not isinstance(cell.get("id"), str)
                    or not cell.get("id")
                    or not isinstance(cell.get("text"), str)
                    or source_ids is None
                    or not source_ids
                    or evidence_ids is None
                    or not evidence_ids
                    or _whitespace_normalized(str(row_value[expected_column]))
                    != _whitespace_normalized(str(cell.get("text")))
                ):
                    structurally_complete = False
                    break
                linked_sources = [source_by_id.get(value) for value in source_ids]
                linked_evidence = [
                    evidence_by_id.get(value) for value in evidence_ids
                ]
                if (
                    any(not isinstance(value, Mapping) for value in linked_sources)
                    or any(
                        value.get("page_index") != source_page.page_index
                        or value.get("engine") not in {"docling", "pdfplumber"}
                        for value in linked_sources
                        if isinstance(value, Mapping)
                    )
                    or any(
                        not isinstance(value, Mapping)
                        or value.get("page_index") != source_page.page_index
                        for value in linked_evidence
                    )
                    or not any(
                        set(value.get("source_object_ids") or ())
                        & set(source_ids)
                        for value in linked_evidence
                        if isinstance(value, Mapping)
                    )
                ):
                    structurally_complete = False
                    break
                cell_boxes.append(cell_box)
                cell_ids.append(str(cell["id"]))
                cell_source_ids.append(source_ids)
                cell_evidence_ids.append(evidence_ids)
            if not structurally_complete:
                continue
            if any(
                _intersection_area(first, second) > 0.000001
                for first_index, first in enumerate(cell_boxes)
                for second in cell_boxes[first_index + 1 :]
            ):
                continue
            row_box = _bbox_union(cell_boxes)
            if (
                row_box is None
                or _overlap_of_smaller(complete_line.bbox, row_box) < 0.90
            ):
                continue

            fragments: list[list[SourceCharacterEvidence]] = [
                [] for _cell in row_cells
            ]
            covered_substantive = 0
            coverage_conflict = False
            for character in emitted_characters:
                if character.page_index != source_page.page_index:
                    coverage_conflict = True
                    break
                if character.bbox is None or character.bbox.unit != "pt":
                    if character.text.isspace():
                        continue
                    coverage_conflict = True
                    break
                owners = [
                    index
                    for index, cell_box in enumerate(cell_boxes)
                    if _center_inside(character.bbox, cell_box)
                ]
                if character.text.isspace() and not owners:
                    # Inter-cell source whitespace is a separator, not
                    # attributable table content.
                    continue
                if len(owners) != 1:
                    coverage_conflict = True
                    break
                fragments[owners[0]].append(character)
                if not character.text.isspace():
                    covered_substantive += 1
            if (
                coverage_conflict
                or covered_substantive != len(substantive_characters)
                or any(
                    not _table_cell_covers_source_fragment(
                        fragment,
                        str(cell.get("text")),
                    )
                    for fragment, cell in zip(
                        fragments,
                        row_cells,
                        strict=True,
                    )
                )
            ):
                continue

            reading_order = table.get("reading_order")
            table_order = (
                reading_order
                if isinstance(reading_order, int)
                and not isinstance(reading_order, bool)
                and reading_order >= 0
                else view_order
            )
            source_ids = _ordered_unique_strings(
                value for values in cell_source_ids for value in values
            )
            evidence_ids = _ordered_unique_strings(
                value for values in cell_evidence_ids for value in values
            )
            if source_ids is None or evidence_ids is None:
                continue
            candidates.append(
                _TableOwnedStructuralLineCandidate(
                    match=_TableOwnedSourceLineMatch(
                        page_index=source_page.page_index,
                        table_item_id=str(table_item_id),
                        table_id=str(table_id),
                        candidate_id=str(candidate_id),
                        table_order=table_order,
                        row_index=row_index,
                        cell_ids=tuple(cell_ids),
                        source_object_ids=source_ids,
                        evidence_ids=evidence_ids,
                        table_bbox=table_box,
                        row_bbox=row_box,
                        source_line_bbox=complete_line.bbox,
                    ),
                    cell_boxes=tuple(cell_boxes),
                )
            )
    return tuple(candidates)


def _source_line_table_matches(
    *,
    source_page: SourcePageEvidence,
    complete_line: SourceTextLine,
    owner_box: SourceBBox,
    tables: Sequence[Mapping[str, Any]],
    deadline: float,
    structural_cache: _TableOwnedStructuralLineCache | None = None,
) -> tuple[_TableOwnedSourceLineMatch, ...]:
    """Return at most two owner-valid matches; two proves ambiguity."""

    if time.perf_counter() > deadline:
        raise _Refusal("source_alignment_deadline")
    cache_key = (source_page.page_index, complete_line.id)
    candidates = (
        structural_cache.values.get(cache_key)
        if structural_cache is not None
        else None
    )
    if candidates is None:
        candidates = _structural_table_line_candidates(
            source_page=source_page,
            complete_line=complete_line,
            tables=tables,
            deadline=deadline,
        )
        if structural_cache is not None:
            structural_cache.store(cache_key, candidates)

    matches: list[_TableOwnedSourceLineMatch] = []
    for candidate_index, candidate in enumerate(candidates, start=1):
        if (
            candidate_index % 128 == 0
            and time.perf_counter() > deadline
        ):
            raise _Refusal("source_alignment_deadline")
        if (
            not _center_inside(owner_box, candidate.match.row_bbox)
            or max(
                _overlap_of_smaller(owner_box, cell_box)
                for cell_box in candidate.cell_boxes
            )
            < 0.80
        ):
            continue
        matches.append(candidate.match)
        if len(matches) > 1:
            break
    return tuple(
        sorted(
            matches,
            key=lambda value: (
                value.page_index,
                value.table_order,
                value.row_index,
                value.table_id,
            ),
        )
    )


def _bbox_contains(
    outer: SourceBBox,
    inner: SourceBBox,
    *,
    tolerance: float = 0.05,
) -> bool:
    return bool(
        outer.unit == inner.unit
        and inner.x >= outer.x - tolerance
        and inner.y >= outer.y - tolerance
        and inner.x + inner.width
        <= outer.x + outer.width + tolerance
        and inner.y + inner.height
        <= outer.y + outer.height + tolerance
    )


def _table_owned_cell_authorities(
    *,
    source_page: SourcePageEvidence,
    tables: Sequence[Mapping[str, Any]],
    deadline: float,
) -> tuple[_TableOwnedCellAuthority, ...]:
    """Validate bounded native canonical-cell lineage once per page."""

    authorities: list[_TableOwnedCellAuthority] = []
    scanned_cells = 0
    for view_order, table in enumerate(tables):
        if time.perf_counter() > deadline:
            raise _Refusal("source_alignment_deadline")
        sidecar = table.get("table_evidence")
        table_box_value = table.get("bbox")
        table_box = _mapping_bbox(table_box_value)
        rows = table.get("rows") or table.get("value")
        cells = table.get("cells")
        if (
            not isinstance(sidecar, Mapping)
            or sidecar.get("page_index") != source_page.page_index
            or not isinstance(table_box_value, Mapping)
            or table_box_value.get("unit") != "pt"
            or table_box is None
            or not isinstance(rows, Sequence)
            or isinstance(rows, (str, bytes, bytearray))
            or not isinstance(cells, list)
        ):
            continue
        table_item_id = table.get("id")
        table_id = sidecar.get("table_id")
        candidate_id = sidecar.get("candidate_id")
        if not all(
            isinstance(value, str) and value
            for value in (table_item_id, table_id, candidate_id)
        ):
            continue
        source_objects = sidecar.get("source_objects")
        evidence_records = sidecar.get("evidence")
        if not isinstance(source_objects, list) or not isinstance(
            evidence_records,
            list,
        ):
            continue
        source_by_id = {
            record.get("id"): record
            for record in source_objects
            if isinstance(record, Mapping)
            and isinstance(record.get("id"), str)
            and record.get("id")
        }
        evidence_by_id = {
            record.get("id"): record
            for record in evidence_records
            if isinstance(record, Mapping)
            and isinstance(record.get("id"), str)
            and record.get("id")
        }
        if (
            len(source_by_id) != len(source_objects)
            or len(evidence_by_id) != len(evidence_records)
        ):
            continue
        reading_order = table.get("reading_order")
        table_order = (
            reading_order
            if isinstance(reading_order, int)
            and not isinstance(reading_order, bool)
            and reading_order >= 0
            else view_order
        )
        seen_slots: set[tuple[int, int]] = set()
        table_authorities: list[_TableOwnedCellAuthority] = []
        table_invalid = False
        for cell in cells:
            scanned_cells += 1
            if scanned_cells > MAX_SCANNED_OWNERS:
                raise _Refusal("source_alignment_owner_scan_limit")
            if (
                scanned_cells % 128 == 0
                and time.perf_counter() > deadline
            ):
                raise _Refusal("source_alignment_deadline")
            if not isinstance(cell, Mapping):
                table_invalid = True
                break
            row_index = cell.get("row")
            column_index = cell.get("column")
            if (
                not isinstance(row_index, int)
                or isinstance(row_index, bool)
                or not isinstance(column_index, int)
                or isinstance(column_index, bool)
                or row_index < 0
                or column_index < 0
                or row_index >= len(rows)
                or (row_index, column_index) in seen_slots
            ):
                table_invalid = True
                break
            row_value = rows[row_index]
            if (
                not isinstance(row_value, Sequence)
                or isinstance(row_value, (str, bytes, bytearray))
                or column_index >= len(row_value)
            ):
                table_invalid = True
                break
            seen_slots.add((row_index, column_index))
            cell_box_value = cell.get("bbox")
            cell_box = _mapping_bbox(cell_box_value)
            raw_source_ids = cell.get("source_object_ids")
            raw_evidence_ids = cell.get("evidence_ids")
            source_ids = (
                _ordered_unique_strings(raw_source_ids)
                if isinstance(raw_source_ids, list)
                else None
            )
            evidence_ids = (
                _ordered_unique_strings(raw_evidence_ids)
                if isinstance(raw_evidence_ids, list)
                else None
            )
            cell_text = cell.get("text")
            if (
                cell.get("row_span") != 1
                or cell.get("col_span") != 1
                or cell.get("source") != "native"
                or cell.get("page_index") != source_page.page_index
                or not isinstance(cell_box_value, Mapping)
                or cell_box_value.get("unit") != "pt"
                or cell_box is None
                or not _bbox_contains(table_box, cell_box)
                or not isinstance(cell.get("id"), str)
                or not cell.get("id")
                or not isinstance(cell_text, str)
                or source_ids is None
                or len(source_ids) > MAX_EVIDENCE_REFS
                or evidence_ids is None
                or len(evidence_ids) > MAX_EVIDENCE_REFS
                or _whitespace_normalized(str(row_value[column_index]))
                != _whitespace_normalized(cell_text)
            ):
                table_invalid = True
                break
            # P04 retains explicit, geometrically grounded blank slots in a
            # canonical grid.  They are necessary table structure but cannot
            # own a non-empty OCR heading.  Validate their bounded shape above
            # and any declared lineage below, then omit them from the cell
            # authority inventory without invalidating unrelated native cells.
            if not cell_text and bool(source_ids) != bool(evidence_ids):
                table_invalid = True
                break
            linked_sources = [source_by_id.get(value) for value in source_ids]
            linked_evidence = [
                evidence_by_id.get(value) for value in evidence_ids
            ]
            if (
                any(not isinstance(value, Mapping) for value in linked_sources)
                or any(
                    value.get("page_index") != source_page.page_index
                    or value.get("engine") not in {"docling", "pdfplumber"}
                    for value in linked_sources
                    if isinstance(value, Mapping)
                )
                or any(
                    not isinstance(value, Mapping)
                    or value.get("page_index") != source_page.page_index
                    for value in linked_evidence
                )
                or bool(source_ids)
                and not any(
                    set(value.get("source_object_ids") or ())
                    & set(source_ids)
                    for value in linked_evidence
                    if isinstance(value, Mapping)
                )
            ):
                table_invalid = True
                break
            if not cell_text:
                continue
            if not source_ids or not evidence_ids:
                table_invalid = True
                break
            table_authorities.append(
                _TableOwnedCellAuthority(
                    page_index=source_page.page_index,
                    table_item_id=str(table_item_id),
                    table_id=str(table_id),
                    candidate_id=str(candidate_id),
                    table_order=table_order,
                    row_index=row_index,
                    column_index=column_index,
                    cell_id=str(cell["id"]),
                    source_object_ids=source_ids,
                    evidence_ids=evidence_ids,
                    table_bbox=table_box,
                    cell_bbox=cell_box,
                    cell_text=cell_text,
                )
            )
        if not table_invalid:
            authorities.extend(table_authorities)
    return tuple(authorities)


def _nfc_substantive_character_counter(
    value: str,
) -> Counter[str] | None:
    counter: Counter[str] = Counter()
    for character in unicodedata.normalize("NFC", value):
        if character.isspace():
            continue
        if not _is_printable_source_character(character):
            return None
        counter[character] += 1
    return counter if counter else None


def _selected_vector_two_token_reversal_subrange(
    original_text: str,
    cell_text: str,
    selected_source_characters: Sequence[SourceCharacterEvidence],
    selected_characters: Sequence[SourceCharacterEvidence],
    full_cell_characters: Sequence[SourceCharacterEvidence],
    owner_box: SourceBBox,
    cell_box: SourceBBox,
) -> bool:
    """Admit only an exact two-token reversal of one contiguous cell slice."""

    original = unicodedata.normalize("NFC", original_text)
    canonical = unicodedata.normalize("NFC", cell_text)
    original_tokens = tuple(original.split())
    source_scalar = unicodedata.normalize(
        "NFC",
        "".join(character.text for character in selected_source_characters),
    )
    selected_tokens = tuple(source_scalar.split())
    canonical_tokens = tuple(canonical.split())
    expected = (
        (original_tokens[1], original_tokens[0])
        if len(original_tokens) == 2
        else ()
    )
    if (
        len(original_tokens) != 2
        or any(not token for token in original_tokens)
        or len(canonical_tokens) < 2
        or any(not token for token in canonical_tokens)
        or selected_tokens != expected
        or not _bbox_contains(cell_box, owner_box)
    ):
        return False
    substantive_source_ids: list[str] = []
    for character in selected_source_characters:
        if (
            character.bbox is None
            or character.excluded_reason is not None
            or not _character_emits(character)
            or not _center_inside(character.bbox, owner_box)
            or not _bbox_contains(cell_box, character.bbox)
        ):
            return False
        if character.text.isspace():
            # Token boundaries must come from one encoded source U+0020, not
            # the geometry-spaced ``selection.text`` renderer.  Rotated PDF
            # words legitimately carry vertical U+0020 glyph records which
            # cannot satisfy the horizontal ``space_supported`` heuristic.
            if (
                character.text != " "
                or character.raw_text != " "
                or character.raw_code_point != 0x20
            ):
                return False
        else:
            substantive_source_ids.append(character.id)
    if substantive_source_ids != [character.id for character in selected_characters]:
        return False
    occurrences = [
        index
        for index in range(len(canonical_tokens) - 1)
        if canonical_tokens[index : index + 2] == expected
    ]
    if len(occurrences) != 1:
        return False
    if any(
        character.bbox is None
        or character.excluded_reason is not None
        or not _character_emits(character)
        or not _center_inside(character.bbox, owner_box)
        or not _bbox_contains(cell_box, character.bbox)
        for character in selected_characters
    ):
        return False
    selected_box = _bbox_union(
        character.bbox for character in selected_characters
    )
    if selected_box is None or _reciprocal_overlap(owner_box, selected_box) < 0.95:
        return False
    full_ids = [character.id for character in full_cell_characters]
    selected_ids = [character.id for character in selected_characters]
    if (
        len(full_ids) != len(set(full_ids))
        or len(selected_ids) != len(set(selected_ids))
        or not selected_ids
    ):
        return False
    try:
        selected_offsets = [full_ids.index(identifier) for identifier in selected_ids]
    except ValueError:
        return False
    if selected_offsets != list(
        range(selected_offsets[0], selected_offsets[0] + len(selected_offsets))
    ):
        return False
    selected_substantive = unicodedata.normalize(
        "NFC",
        "".join(character.text for character in selected_characters),
    )
    full_substantive = unicodedata.normalize(
        "NFC",
        "".join(character.text for character in full_cell_characters),
    )
    canonical_substantive = "".join(canonical_tokens)
    expected_substantive = "".join(expected)
    original_substantive = "".join(original_tokens)
    return bool(
        full_substantive == canonical_substantive
        and selected_substantive == expected_substantive
        and original_substantive == "".join(reversed(expected))
    )


def _source_selection_table_cell_matches(
    *,
    source_page: SourcePageEvidence,
    selection: SourceTextSelection,
    original_text: str,
    owner_box: SourceBBox,
    tables: Sequence[Mapping[str, Any]],
    deadline: float,
    authority_cache: _TableOwnedCellAuthorityCache,
) -> tuple[_TableOwnedSourceCellMatch, ...]:
    """Resolve a rotated OCR heading to one fully sourced canonical cell."""

    original_counter = _nfc_substantive_character_counter(original_text)
    selection_counter = _nfc_substantive_character_counter(selection.text)
    by_character_id = {
        character.id: character for character in source_page.characters
    }
    if (
        original_counter is None
        or selection_counter is None
        or original_counter != selection_counter
        or not selection.source_character_ids
        or len(selection.source_character_ids)
        != len(set(selection.source_character_ids))
    ):
        return ()
    selected_characters = [
        by_character_id.get(identifier)
        for identifier in selection.source_character_ids
    ]
    if any(character is None for character in selected_characters):
        return ()
    substantive_characters = [
        character
        for character in selected_characters
        if character is not None
        and _character_emits(character)
        and character.text
        and not character.text.isspace()
    ]
    selected_character_counter: Counter[str] = Counter()
    for character in substantive_characters:
        if (
            character.page_index != source_page.page_index
            or character.bbox is None
            or character.bbox.unit != "pt"
        ):
            return ()
        character_counter = _nfc_substantive_character_counter(
            character.text
        )
        if character_counter is None:
            return ()
        selected_character_counter.update(character_counter)
    if (
        not substantive_characters
        or selected_character_counter != original_counter
    ):
        return ()

    authorities = authority_cache.values.get(source_page.page_index)
    if authorities is None:
        authorities = _table_owned_cell_authorities(
            source_page=source_page,
            tables=tables,
            deadline=deadline,
        )
        authority_cache.store(source_page.page_index, authorities)

    matches: list[_TableOwnedSourceCellMatch] = []
    for authority_index, authority in enumerate(authorities, start=1):
        if (
            authority_index % 128 == 0
            and time.perf_counter() > deadline
        ):
            raise _Refusal("source_alignment_deadline")
        cell_counter = _nfc_substantive_character_counter(
            authority.cell_text
        )
        if (
            cell_counter is None
            or not _center_inside(owner_box, authority.cell_bbox)
            or _overlap_of_smaller(owner_box, authority.cell_bbox) < 0.80
            or any(
                character.bbox is None
                or not _center_inside(character.bbox, authority.cell_bbox)
                for character in substantive_characters
            )
            or any(
                selected_character_counter[character]
                > cell_counter[character]
                for character in selected_character_counter
            )
        ):
            continue
        matches.append(
            _TableOwnedSourceCellMatch(
                authority=authority,
                source_selection_bbox=selection.bbox,
            )
        )
        if len(matches) > 1:
            break
    return tuple(
        sorted(
            matches,
            key=lambda value: (
                value.authority.page_index,
                value.authority.table_order,
                value.authority.row_index,
                value.authority.column_index,
                value.authority.table_id,
            ),
        )
    )


_SELECTED_VECTOR_TEXT_OWNER_KEYS = frozenset(
    {
        "bbox",
        "confidence",
        "id",
        "label",
        "md",
        "ocr_contributor",
        "parse_concerns",
        "raw_ocr_text",
        "reading_order",
        "source",
        "type",
        "value",
    }
)
_SELECTED_VECTOR_HEADING_OWNER_KEYS = (
    _SELECTED_VECTOR_TEXT_OWNER_KEYS | {"level"}
)


def _selected_vector_owner_shape(
    item: Mapping[str, Any],
    *,
    page_index: int,
    source_sha256: str,
) -> tuple[SourceBBox, bool] | None:
    """Authenticate the exact public owner shapes admitted by this lane."""

    if type(item) is not dict:
        return None
    value = item.get("value")
    raw_text = item.get("raw_ocr_text")
    confidence = item.get("confidence")
    owner_id = item.get("id")
    reading_order = item.get("reading_order")
    owner_box = _mapping_bbox_in_unit(item.get("bbox"), "pt")
    if (
        type(value) is not str
        or not value
        or len(value) > MAX_CANDIDATE_CODEPOINTS
        or type(raw_text) is not str
        or unicodedata.normalize("NFC", raw_text)
        != unicodedata.normalize("NFC", value)
        or type(owner_id) is not str
        or not owner_id
        or len(owner_id.encode("utf-8")) > 256
        or type(reading_order) is not int
        or reading_order < 0
        or type(confidence) not in (int, float)
        or not math.isfinite(float(confidence))
        or not 0.0 <= float(confidence) <= 1.0
        or owner_box is None
        or _validated_supplemental_ocr_contributor(
            item.get("ocr_contributor"),
            source_sha256=source_sha256,
            page_index=page_index,
            owner_box=owner_box,
            raw_text=raw_text,
            confidence=float(confidence),
        )
        is None
    ):
        return None
    if (
        set(item) == _SELECTED_VECTOR_TEXT_OWNER_KEYS
        and item.get("type") == "text"
        and item.get("label") == "ocr_text"
        and item.get("source") == "ocr"
        and item.get("md") == value
        and item.get("parse_concerns")
        == ["layout_omission_recovered_by_ocr"]
    ):
        return owner_box, False
    if (
        set(item) == _SELECTED_VECTOR_HEADING_OWNER_KEYS
        and item.get("type") == "heading"
        and item.get("label") == "inferred_heading"
        and item.get("source") == "ocr"
        and type(item.get("level")) is int
        and item.get("level") == 1
        and item.get("md") == f"# {value}"
        and item.get("parse_concerns")
        == list(_PROMOTED_SUPPLEMENTAL_HEADING_CONCERNS)
    ):
        return owner_box, True
    return None


def _selected_vector_page_reference_counts(
    pages: Sequence[Mapping[str, Any]],
    *,
    deadline: float,
) -> Counter[str]:
    """Count exact public strings once so inbound owner references are closed."""

    counts: Counter[str] = Counter()
    remaining = 500_000

    def visit(value: Any, depth: int) -> None:
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 16:
            raise _Refusal("source_alignment_selected_vector_reference_limit")
        if remaining % 4096 == 0 and time.perf_counter() > deadline:
            raise _Refusal("source_alignment_deadline")
        if isinstance(value, str):
            if len(value) <= 256:
                counts[value] += 1
            return
        if type(value) is dict:
            for child in value.values():
                visit(child, depth + 1)
            return
        if type(value) in (list, tuple):
            for child in value:
                visit(child, depth + 1)

    visit(pages, 0)
    return counts


def _selected_vector_selection_from_line_bbox(
    proof: _SelectedVectorRowProof,
    owner_box: SourceBBox,
) -> tuple[SourceTextSelection, tuple[int, int]] | None:
    characters = list(proof.source_characters)
    physically_selected = [
        index
        for index, character in enumerate(characters)
        if character.bbox is not None
        and _center_inside(character.bbox, owner_box)
    ]
    if not physically_selected:
        return None
    start = min(physically_selected)
    end = max(physically_selected) + 1
    selected = characters[start:end]
    if (
        not selected
        or any(
            character.excluded_reason
            in {
                "unsafe_unicode",
                "invalid_hyphen_sentinel_bbox",
                "uncorroborated_hyphen_sentinel",
                "ambiguous_type1_geometry",
                "conflicting_type1_geometry",
                "transparent_text",
                "white_icon_overlay",
            }
            for character in selected
        )
    ):
        return None
    selected_box = _bbox_union(
        character.bbox for character in selected if character.bbox is not None
    )
    if selected_box is None:
        return None
    selection = SourceTextSelection(
        text=_selection_fragment_text(selected, raw=False),
        raw_text=_selection_fragment_text(selected, raw=True),
        bbox=selected_box,
        source_line_ids=(proof.source_line.id,),
        source_character_ids=tuple(character.id for character in selected),
        source_character_indexes=tuple(
            character.character_index for character in selected
        ),
        type1_evidence_ids=tuple(
            dict.fromkeys(
                evidence_id
                for character in selected
                for evidence_id in character.type1_evidence_ids
            )
        ),
        source_roles=_source_roles(selected),
        checks={
            "finite_geometry": True,
            "single_page": True,
            "printable_unicode": True,
            "bounded_candidate": len(selected) <= MAX_CANDIDATE_CODEPOINTS,
            "source_hash_bound": True,
        },
    )
    return selection, (start, end)


def _selected_vector_visible_punctuation_omission(
    original_text: str,
    selection: SourceTextSelection,
    characters: Sequence[SourceCharacterEvidence],
    owner_box: SourceBBox,
    cell_box: SourceBBox,
) -> tuple[str, int, str] | None:
    original = unicodedata.normalize("NFC", original_text)
    source = unicodedata.normalize("NFC", selection.text)
    if (
        len(source) != len(original) + 1
        or _reciprocal_overlap(owner_box, selection.bbox) < 0.95
    ):
        return None
    candidates = [
        offset
        for offset in range(1, len(source) - 1)
        if unicodedata.category(source[offset])[:1] in {"P", "S"}
        and source[:offset] + source[offset + 1 :] == original
    ]
    if len(candidates) != 1:
        return None
    omitted_offset = candidates[0]
    scalar_offset = 0
    omitted_character: SourceCharacterEvidence | None = None
    for character in characters:
        if not _character_emits(character):
            continue
        piece = unicodedata.normalize("NFC", character.text)
        if scalar_offset <= omitted_offset < scalar_offset + len(piece):
            if len(piece) != 1:
                return None
            omitted_character = character
            break
        scalar_offset += len(piece)
    if (
        omitted_character is None
        or omitted_character.text != source[omitted_offset]
        or omitted_character.excluded_reason is not None
        or omitted_character.role is not None
        or omitted_character.bbox is None
        or omitted_character.bbox.width <= 0
        or omitted_character.bbox.height <= 0
        # The OCR owner is serialized to one decimal place.  This lane alone
        # permits the measured rounding edge (0.050008 pt); the global table
        # containment tolerance remains unchanged.
        or not _bbox_contains(
            owner_box,
            omitted_character.bbox,
            tolerance=0.05001,
        )
        or not _bbox_contains(cell_box, omitted_character.bbox)
        or omitted_character.fill_rgba is None
        or omitted_character.fill_rgba[3] <= 0
        or omitted_character.fill_rgba[:3] == (255, 255, 255)
        or not _is_printable_source_character(omitted_character.text)
    ):
        return None
    return (
        omitted_character.id,
        omitted_offset,
        unicodedata.category(omitted_character.text),
    )


def _admit_selected_vector_representations(
    value: Mapping[int, Sequence[Mapping[str, Any]]] | None,
    pages: Sequence[Mapping[str, Any]],
    evidence: SourceTextEvidence,
    *,
    deadline: float,
) -> dict[int, tuple[dict[str, Any], ...]]:
    if value is None:
        return {}
    if type(value) not in (dict, defaultdict) or len(value) > MAX_PAGES:
        raise _Refusal("source_alignment_selected_vector_authority_invalid")
    from app.services.table_semantics import (
        admit_selected_vector_representation,
    )

    pages_by_index: dict[int, Mapping[str, Any]] = {}
    for position, page in enumerate(pages, start=1):
        page_index = page.get("page_index")
        if type(page_index) is not int or page_index < 1:
            page_index = position
        if page_index in pages_by_index:
            raise _Refusal("source_alignment_page_identity_mismatch")
        pages_by_index[page_index] = page
    admitted: dict[int, tuple[dict[str, Any], ...]] = {}
    table_count = 0
    slot_count = 0
    for page_index, records in value.items():
        if time.perf_counter() > deadline:
            raise _Refusal("source_alignment_deadline")
        page = pages_by_index.get(page_index)
        source_page = next(
            (candidate for candidate in evidence.pages if candidate.page_index == page_index),
            None,
        )
        if (
            type(page_index) is not int
            or page_index < 1
            or type(records) is not list
            or len(records) > MAX_SELECTED_VECTOR_TABLES
            or type(page) is not dict
            or source_page is None
        ):
            raise _Refusal("source_alignment_selected_vector_authority_invalid")
        items = page.get("items")
        if type(items) is not list:
            raise _Refusal("source_alignment_selected_vector_authority_invalid")
        page_records: list[dict[str, Any]] = []
        consumed_positions: set[int] = set()
        for record in records:
            binding = record.get("terminal_binding") if type(record) is dict else None
            item_position = (
                binding.get("public_item_position")
                if type(binding) is dict
                else None
            )
            if (
                type(item_position) is not int
                or item_position < 0
                or item_position >= len(items)
                or item_position in consumed_positions
            ):
                raise _Refusal("source_alignment_selected_vector_authority_invalid")
            public_table = items[item_position]
            page_table_positions = [
                position
                for position, candidate in enumerate(items)
                if type(candidate) is dict and candidate.get("type") == "table"
            ]
            table_ordinal = (
                page_table_positions.index(item_position)
                if item_position in page_table_positions
                else None
            )
            base_binding_keys = {
                "schema_version",
                "policy_id",
                "source_sha256",
                "page_index",
                "public_item_position",
                "public_table_ordinal",
                "public_table_id",
                "public_table_sha256",
                "ir_page_id",
                "ir_element_id",
                "ir_legacy_item_sha256",
                "ir_element_sha256",
                "ir_bbox_sha256",
                "ir_evidence_sha256",
                "ir_coordinate_sha256",
                "ir_region_id",
                "ir_region_bbox_id",
                "canonical_page_id",
                "canonical_block_position",
                "canonical_block_id",
                "canonical_block_sha256",
                "canonical_markdown_sha256",
                "canonical_text_sha256",
            }
            raw_binding = binding.get("ir_raw_provenance")
            expected_binding_keys = (
                base_binding_keys | {"ir_raw_provenance"}
                if raw_binding is not None
                else base_binding_keys
            )
            raw_binding_keys = {
                "schema_version",
                "policy_id",
                "source_sha256",
                "page_index",
                "raw_graph_sha256",
                "table_raw_ref",
                "table_raw_node_sha256",
                "table_raw_properties",
                "table_raw_bbox",
                "table_raw_coordinate",
                "table_raw_evidence",
                "raw_relationship",
                "target_raw_ref",
                "target_raw_node_sha256",
                "target_element_id",
                "target_page_id",
                "target_type",
                "target_value",
                "target_markdown",
                "target_raw_properties",
                "target_running_projection",
                "target_bboxes",
                "target_evidence",
                "target_coordinates",
                "custody_sha256",
            }
            raw_binding_without_digest = (
                {
                    key: copy.deepcopy(value)
                    for key, value in raw_binding.items()
                    if key != "custody_sha256"
                }
                if type(raw_binding) is dict
                else None
            )
            running_target = (
                raw_binding.get("target_running_projection")
                if type(raw_binding) is dict
                else None
            )
            running_target_keys = {
                "schema_version",
                "policy_id",
                "descriptor_id",
                "source_method",
                "predecessor_item_sha256",
                "descriptor_stable_sha256",
                "predecessor_stable_sha256",
            }
            if (
                set(binding) != expected_binding_keys
                or binding.get("schema_version") != "1.0"
                or binding.get("policy_id")
                != "p02-selected-vector-terminal-binding-v1"
                or binding.get("source_sha256") != evidence.source_sha256
                or binding.get("page_index") != page_index
                or binding.get("public_item_position") != item_position
                or binding.get("public_table_ordinal") != table_ordinal
                or binding.get("public_table_id") != public_table.get("id")
                or binding.get("public_table_sha256")
                != _selected_vector_digest(public_table)
                or (
                    raw_binding is not None
                    and (
                        type(raw_binding) is not dict
                        or set(raw_binding) != raw_binding_keys
                        or raw_binding.get("schema_version") != "1.0"
                        or raw_binding.get("policy_id")
                        != "p02-selected-vector-raw-provenance-v1"
                        or raw_binding.get("source_sha256")
                        != evidence.source_sha256
                        or raw_binding.get("page_index") != page_index
                        or (
                            running_target is not None
                            and (
                                type(running_target) is not dict
                                or set(running_target) != running_target_keys
                                or running_target.get("schema_version") != "1.0"
                                or running_target.get("policy_id")
                                != "p02-selected-vector-running-target-v1"
                                or type(running_target.get("descriptor_id")) is not str
                                or not running_target["descriptor_id"]
                                or type(running_target.get("source_method")) is not str
                                or not running_target["source_method"]
                                or running_target["source_method"]
                                == "extracted_source_contribution"
                                or any(
                                    re.fullmatch(r"[0-9a-f]{64}", value or "")
                                    is None
                                    for value in (
                                        running_target.get(
                                            "predecessor_item_sha256"
                                        ),
                                        running_target.get(
                                            "descriptor_stable_sha256"
                                        ),
                                        running_target.get(
                                            "predecessor_stable_sha256"
                                        ),
                                    )
                                )
                            )
                        )
                        or any(
                            re.fullmatch(r"[0-9a-f]{64}", value or "") is None
                            for value in (
                                raw_binding.get("raw_graph_sha256"),
                                raw_binding.get("table_raw_node_sha256"),
                                raw_binding.get("target_raw_node_sha256"),
                                raw_binding.get("custody_sha256"),
                            )
                        )
                        or raw_binding.get("custody_sha256")
                        != _selected_vector_digest(raw_binding_without_digest)
                    )
                )
            ):
                raise _Refusal("source_alignment_selected_vector_authority_invalid")
            rebuilt = admit_selected_vector_representation(
                record,
                public_table,
                evidence.source_sha256,
                source_page.page_width,
                source_page.page_height,
                deadline=deadline,
            )
            if (
                type(rebuilt) is not dict
                or rebuilt.get("terminal_authority_sha256")
                != record.get("terminal_authority_sha256")
                or rebuilt.get("public_table_id") != public_table.get("id")
            ):
                raise _Refusal("source_alignment_selected_vector_authority_invalid")
            rows = rebuilt.get("rows")
            table_count += 1
            slot_count += len(rows) * len(rows[0])
            if (
                table_count > MAX_SELECTED_VECTOR_TABLES
                or slot_count > MAX_SELECTED_VECTOR_SLOTS
            ):
                raise _Refusal("source_alignment_selected_vector_authority_limit")
            consumed_positions.add(item_position)
            page_records.append(
                {
                    **copy.deepcopy(rebuilt),
                    "table_item_position": item_position,
                    # Invocation-local immutable authority memo.  The binding
                    # was fully reconstructed above; hashing its raw provenance
                    # payload again for every OCR member multiplied the same
                    # ~100 KiB serialization thousands of times.
                    "_terminal_binding_sha256": _selected_vector_digest(
                        rebuilt["terminal_binding"]
                    ),
                }
            )
        if page_records:
            admitted[page_index] = tuple(page_records)
    _bounded_json_size(
        [[page, admitted[page]] for page in sorted(admitted)],
        max_bytes=MAX_REPORT_BYTES,
        deadline=deadline,
        refusal_code="source_alignment_selected_vector_authority_size_limit",
    )
    return admitted


def _selected_vector_row_proofs(
    source_page: SourcePageEvidence,
    representations: Sequence[Mapping[str, Any]],
    *,
    deadline: float,
) -> tuple[_SelectedVectorRowProof, ...]:
    by_id = {character.id: character for character in source_page.characters}
    proofs: list[_SelectedVectorRowProof] = []
    scanned = 0
    comparisons = 0
    for representation in representations:
        table_position = representation.get("table_item_position")
        table_id = representation.get("public_table_id")
        reading_order = representation.get("reading_order")
        rows = representation.get("rows")
        raw_row_boxes = representation.get("row_bboxes")
        raw_cell_boxes = representation.get("cell_bboxes")
        if (
            type(representation) is not dict
            or type(table_position) is not int
            or type(table_id) is not str
            or not table_id
            or type(reading_order) is not int
            or type(rows) is not list
            or type(raw_row_boxes) is not list
            or type(raw_cell_boxes) is not list
            or not (
                len(rows) == len(raw_row_boxes) == len(raw_cell_boxes)
            )
        ):
            raise _Refusal("source_alignment_selected_vector_authority_invalid")
        for row_index, (row, raw_row_box, raw_cells) in enumerate(
            zip(rows, raw_row_boxes, raw_cell_boxes, strict=True)
        ):
            scanned += 1
            if scanned > MAX_SELECTED_VECTOR_SLOTS:
                raise _Refusal("source_alignment_selected_vector_authority_limit")
            if scanned % 64 == 0 and time.perf_counter() > deadline:
                raise _Refusal("source_alignment_deadline")
            row_box = _mapping_bbox_in_unit(raw_row_box, "pt")
            cell_boxes = tuple(
                _mapping_bbox_in_unit(value, "pt") for value in raw_cells
            )
            if (
                type(row) is not list
                or row_box is None
                or any(value is None for value in cell_boxes)
                or len(row) != len(cell_boxes)
            ):
                raise _Refusal("source_alignment_selected_vector_authority_invalid")
            for line in source_page.lines:
                comparisons += 1
                if comparisons > MAX_SELECTED_VECTOR_ROW_COMPARISONS:
                    raise _Refusal(
                        "source_alignment_selected_vector_row_comparison_limit"
                    )
                if comparisons % 256 == 0 and time.perf_counter() > deadline:
                    raise _Refusal("source_alignment_deadline")
                if _overlap_of_smaller(line.bbox, row_box) < 0.90:
                    continue
                characters = tuple(
                    by_id[identifier]
                    for identifier in line.source_character_ids
                    if identifier in by_id
                )
                if (
                    not characters
                    or len(characters) != len(line.source_character_ids)
                    or len(line.source_character_ids)
                    != len(set(line.source_character_ids))
                    or line.has_unsafe_character
                ):
                    continue
                fragments: list[list[SourceCharacterEvidence]] = [
                    [] for _ in cell_boxes
                ]
                substantive = 0
                invalid = False
                for character in characters:
                    if not _character_emits(character):
                        invalid = True
                        break
                    if character.bbox is None:
                        if character.text.isspace():
                            continue
                        invalid = True
                        break
                    owners = [
                        index
                        for index, cell_box in enumerate(cell_boxes)
                        if cell_box is not None
                        and _center_inside(character.bbox, cell_box)
                    ]
                    if character.text.isspace() and not owners:
                        continue
                    if len(owners) != 1:
                        invalid = True
                        break
                    fragments[owners[0]].append(character)
                    if character.text and not character.text.isspace():
                        substantive += 1
                cell_source_closed = tuple(
                    _table_cell_covers_source_fragment(fragment, str(text))
                    for fragment, text in zip(fragments, row, strict=True)
                )
                row_text = _whitespace_normalized(
                    " ".join(str(value) for value in row if str(value).strip())
                )
                line_text = _whitespace_normalized(
                    "".join(
                        character.text
                        for character in characters
                        if _character_emits(character)
                    )
                )
                row_text_closed = row_text == line_text
                if (
                    invalid
                    or substantive == 0
                    or not (all(cell_source_closed) or row_text_closed)
                ):
                    continue
                proofs.append(
                    _SelectedVectorRowProof(
                        page_index=source_page.page_index,
                        # ``admitted`` is already an invocation-local deep
                        # reconstruction.  Row proofs share that immutable-by-
                        # convention record instead of multiplying a ~100 KiB
                        # table projection once per row.
                        representation=representation,
                        table_item_position=table_position,
                        table_item_id=table_id,
                        table_reading_order=reading_order,
                        row_index=row_index,
                        row_bbox=row_box,
                        cell_bboxes=tuple(
                            value for value in cell_boxes if value is not None
                        ),
                        cell_texts=tuple(str(value) for value in row),
                        cell_source_closed=cell_source_closed,
                        cell_source_characters=tuple(
                            tuple(fragment) for fragment in fragments
                        ),
                        row_text_closed=row_text_closed,
                        source_line=line,
                        source_characters=characters,
                    )
                )
                if len(proofs) > MAX_SELECTED_VECTOR_SLOTS:
                    raise _Refusal(
                        "source_alignment_selected_vector_row_proof_limit"
                    )
    return tuple(proofs)


def _selected_vector_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > MAX_REPORT_BYTES:
        raise _Refusal("source_alignment_selected_vector_authority_size_limit")
    return hashlib.sha256(encoded).hexdigest()


def _selected_vector_rotated_matches(
    *,
    evidence: SourceTextEvidence,
    source_page: SourcePageEvidence,
    owner_box: SourceBBox,
    original_text: str,
    item_snapshot: dict[str, Any],
    item_position: int,
    representations: Sequence[Mapping[str, Any]],
    cell_character_cache: dict[
        tuple[str, int, int], tuple[SourceCharacterEvidence, ...]
    ],
    character_comparisons: list[int],
    deadline: float,
) -> tuple[_SelectedVectorRotatedMember, ...]:
    selection = text_for_bbox(
        evidence,
        source_page.page_index,
        owner_box,
        deadline=deadline,
    )
    if selection is None:
        return ()
    original_counter = _nfc_substantive_character_counter(original_text)
    selection_counter = _nfc_substantive_character_counter(selection.text)
    by_id = {character.id: character for character in source_page.characters}
    selected_characters = [
        by_id.get(identifier) for identifier in selection.source_character_ids
    ]
    if any(character is None for character in selected_characters):
        return ()
    selected_substantive = [
        character
        for character in selected_characters
        if character is not None
        and _character_emits(character)
        and character.text
        and not character.text.isspace()
    ]
    selected_counter: Counter[str] = Counter()
    for character in selected_substantive:
        character_counter = _nfc_substantive_character_counter(character.text)
        if (
            character_counter is None
            or character.bbox is None
            or not _center_inside(character.bbox, owner_box)
        ):
            return ()
        selected_counter.update(character_counter)
    if (
        original_counter is None
        or selection_counter is None
        or original_counter != selection_counter
        or selected_counter != original_counter
        or not selected_substantive
    ):
        return ()
    matches: list[_SelectedVectorRotatedMember] = []
    for representation in representations:
        rows = representation["rows"]
        cell_boxes = representation["cell_bboxes"]
        for row_index, (row, boxes) in enumerate(
            zip(rows, cell_boxes, strict=True)
        ):
            for column_index, (cell_text, raw_cell_box) in enumerate(
                zip(row, boxes, strict=True)
            ):
                if time.perf_counter() > deadline:
                    raise _Refusal("source_alignment_deadline")
                cell_box = _mapping_bbox_in_unit(raw_cell_box, "pt")
                cell_counter = _nfc_substantive_character_counter(str(cell_text))
                if (
                    cell_box is None
                    or cell_counter is None
                    or any(
                        original_counter[character] > cell_counter[character]
                        for character in original_counter
                    )
                    or not _center_inside(owner_box, cell_box)
                    or _overlap_of_smaller(owner_box, cell_box) < 0.80
                    or any(
                        character.bbox is None
                        or not _center_inside(character.bbox, cell_box)
                        for character in selected_substantive
                    )
                ):
                    continue
                cache_key = (
                    str(representation["terminal_authority_sha256"]),
                    row_index,
                    column_index,
                )
                full_cell_tuple = cell_character_cache.get(cache_key)
                if full_cell_tuple is None:
                    full_cell_values: list[SourceCharacterEvidence] = []
                    for character in source_page.characters:
                        character_comparisons[0] += 1
                        if (
                            character_comparisons[0]
                            > MAX_SELECTED_VECTOR_CHARACTER_COMPARISONS
                        ):
                            raise _Refusal(
                                "source_alignment_selected_vector_character_comparison_limit"
                            )
                        if (
                            character_comparisons[0] % 1024 == 0
                            and time.perf_counter() > deadline
                        ):
                            raise _Refusal("source_alignment_deadline")
                        if (
                            _character_emits(character)
                            and character.text
                            and not character.text.isspace()
                            and character.bbox is not None
                            and _center_inside(character.bbox, cell_box)
                        ):
                            full_cell_values.append(character)
                    full_cell_tuple = tuple(full_cell_values)
                    cell_character_cache[cache_key] = full_cell_tuple
                full_cell_characters = list(full_cell_tuple)
                full_counter: Counter[str] = Counter()
                for character in full_cell_characters:
                    character_counter = _nfc_substantive_character_counter(
                        character.text
                    )
                    if character_counter is None:
                        full_counter.clear()
                        break
                    full_counter.update(character_counter)
                if (
                    full_counter != cell_counter
                    or not {
                        character.id for character in selected_substantive
                    }.issubset(
                        {character.id for character in full_cell_characters}
                    )
                ):
                    continue
                independent_two_token_reversal = (
                    _selected_vector_two_token_reversal_subrange(
                        original_text,
                        str(cell_text),
                        [
                            character
                            for character in selected_characters
                            if character is not None
                        ],
                        selected_substantive,
                        full_cell_characters,
                        owner_box,
                        cell_box,
                    )
                )
                matches.append(
                    _SelectedVectorRotatedMember(
                        page_index=source_page.page_index,
                        item_position=item_position,
                        item_snapshot=copy.deepcopy(item_snapshot),
                        owner_box=owner_box,
                        selection=selection,
                        representation=representation,
                        table_item_position=representation[
                            "table_item_position"
                        ],
                        table_item_id=representation["public_table_id"],
                        table_reading_order=representation["reading_order"],
                        row_index=row_index,
                        column_index=column_index,
                        cell_bbox=cell_box,
                        cell_source_character_ids=tuple(
                            character.id for character in full_cell_characters
                        ),
                        ownership_mode=(
                            "rotated_contiguous_two_token_reversal"
                            if independent_two_token_reversal
                            else "rotated_cell_collective"
                        ),
                    )
                )
                if len(matches) > 1:
                    return tuple(matches)
    return tuple(matches)


def _selected_vector_canonical_owner(
    member: _SelectedVectorMember | _SelectedVectorRotatedMember,
    *,
    group_key_sha256: str,
) -> dict[str, Any]:
    representation = member.representation if isinstance(
        member, _SelectedVectorRotatedMember
    ) else member.proof.representation
    shared = {
        "policy_id": SELECTED_VECTOR_REPRESENTATION_POLICY_ID,
        "suppression_reason": SELECTED_VECTOR_REPRESENTATION_REASON,
        "source_sha256": representation["source_sha256"],
        "page_index": member.page_index,
        "coordinate_unit": "pt",
        "public_table_id": member.table_item_id
        if isinstance(member, _SelectedVectorRotatedMember)
        else member.proof.table_item_id,
        "public_table_item_position": member.table_item_position
        if isinstance(member, _SelectedVectorRotatedMember)
        else member.proof.table_item_position,
        "candidate_id": representation["candidate_id"],
        "content_sha256": representation["content_sha256"],
        "vector_sha256": representation["vector_sha256"],
        "post_gate_table_sha256": representation["post_gate_table_sha256"],
        "post_gate_authority_sha256": representation[
            "post_gate_authority_sha256"
        ],
        "terminal_authority_sha256": representation[
            "terminal_authority_sha256"
        ],
        "terminal_binding_sha256": representation[
            "_terminal_binding_sha256"
        ],
        "group_key_sha256": group_key_sha256,
        "owner_item_position": member.item_position,
        "owner_bbox": member.owner_box.to_dict(),
        "source_selection_bbox": member.selection.bbox.to_dict(),
        "source_character_ids": list(member.selection.source_character_ids),
        "source_line_ids": list(member.selection.source_line_ids),
    }
    if isinstance(member, _SelectedVectorRotatedMember):
        return {
            **shared,
            "ownership_mode": member.ownership_mode,
            "row_index": member.row_index,
            "column_index": member.column_index,
            "cell_bbox": member.cell_bbox.to_dict(),
        }
    return {
        **shared,
        "ownership_mode": member.ownership_mode,
        "row_index": member.proof.row_index,
        "row_bbox": member.proof.row_bbox.to_dict(),
        "source_line_id": member.proof.source_line.id,
        "source_line_character_ids_sha256": _selected_vector_digest(
            list(member.proof.source_line.source_character_ids)
        ),
        "source_character_range": list(member.source_range),
        **(
            {
                "column_index": member.cell_index,
                "cell_bbox": member.proof.cell_bboxes[
                    int(member.cell_index)
                ].to_dict(),
                **(
                    {
                        "omitted_source_character_id": (
                            member.omitted_source_character_id
                        ),
                        "omitted_offset": member.omitted_offset,
                        "omitted_category": member.omitted_category,
                    }
                    if member.ownership_mode
                    == "single_visible_punctuation_omission"
                    else {}
                ),
            }
            if member.ownership_mode
            in {
                "exact_source_cell_subrange",
                "single_visible_punctuation_omission",
            }
            else {}
        ),
    }


def _selected_vector_alignment_selection(
    evidence: SourceTextEvidence,
    member: _SelectedVectorMember | _SelectedVectorRotatedMember,
    *,
    group_key_sha256: str,
) -> AlignmentSelection:
    item = member.item_snapshot
    original = str(item["value"])
    canonical_owner = _selected_vector_canonical_owner(
        member,
        group_key_sha256=group_key_sha256,
    )
    checks = dict(member.selection.checks)
    checks.update(
        {
            "authenticated_supplemental_ocr_owner": True,
            "exact_owner_shape": True,
            "source_hash_bound": True,
            "selected_vector_candidate_bound": True,
            "canonical_table_gate_bound": True,
            "terminal_public_table_bound": True,
            "complete_source_geometry": True,
            "unique_table_owner": True,
            "group_membership_replayed": True,
        }
    )
    rejected = {
        "text": original,
        "source": "ocr",
        "bbox": member.owner_box.to_dict(),
        "confidence": item["confidence"],
        "reason": SELECTED_VECTOR_REPRESENTATION_REASON,
        "ocr_contributor": copy.deepcopy(item["ocr_contributor"]),
        "owner_snapshot": copy.deepcopy(item),
        "canonical_owner": canonical_owner,
    }
    return _alignment_selection(
        evidence=evidence,
        page_index=member.page_index,
        owner_id=str(item["id"]),
        owner_type=str(item["type"]),
        owner_box=member.owner_box,
        original_text=original,
        selected_text="",
        selection=member.selection,
        method="source_safe_selected_vector_table",
        checks=checks,
        rejected_ocr=rejected,
        terminal_reason=SELECTED_VECTOR_REPRESENTATION_REASON,
    )


def _apply_selected_vector_suppressions(
    pages: list[dict[str, Any]],
    evidence: SourceTextEvidence,
    representations: Mapping[int, Sequence[Mapping[str, Any]]] | None,
    *,
    deadline: float,
) -> tuple[list[AlignmentSelection], int, int, int]:
    """Apply the optional selected-RawTable lane under one atomic caller copy."""

    admitted = _admit_selected_vector_representations(
        representations,
        pages,
        evidence,
        deadline=deadline,
    )
    if not admitted:
        return [], 0, 0, 0
    reference_counts = _selected_vector_page_reference_counts(
        pages,
        deadline=deadline,
    )
    source_pages = {page.page_index: page for page in evidence.pages}
    row_proofs: dict[int, tuple[_SelectedVectorRowProof, ...]] = {}
    for page_index, page_representations in admitted.items():
        source_page = source_pages.get(page_index)
        if source_page is None:
            raise _Refusal("source_alignment_page_identity_mismatch")
        row_proofs[page_index] = _selected_vector_row_proofs(
            source_page,
            page_representations,
            deadline=deadline,
        )

    row_groups: dict[
        tuple[Any, ...], list[_SelectedVectorMember]
    ] = defaultdict(list)
    cell_groups: dict[
        tuple[Any, ...], list[_SelectedVectorMember]
    ] = defaultdict(list)
    rotated_members: list[_SelectedVectorRotatedMember] = []
    cell_character_cache: dict[
        tuple[str, int, int], tuple[SourceCharacterEvidence, ...]
    ] = {}
    character_comparisons = [0]
    owner_attempts = 0
    seen_owner_ids: set[str] = set()
    for page_position, page in enumerate(pages, start=1):
        page_index = page.get("page_index")
        if type(page_index) is not int:
            page_index = page_position
        page_representations = admitted.get(page_index)
        if not page_representations:
            continue
        source_page = source_pages.get(page_index)
        items = page.get("items")
        if source_page is None or type(items) is not list:
            raise _Refusal("source_alignment_selected_vector_authority_invalid")
        by_character_id = {
            character.id: character for character in source_page.characters
        }
        for item_position, item in enumerate(tuple(items)):
            if time.perf_counter() > deadline:
                raise _Refusal("source_alignment_deadline")
            shape = _selected_vector_owner_shape(
                item,
                page_index=page_index,
                source_sha256=evidence.source_sha256,
            )
            if shape is None:
                continue
            owner_attempts += 1
            if owner_attempts > MAX_SELECTED_VECTOR_OWNERS:
                raise _Refusal("source_alignment_selected_vector_owner_limit")
            owner_box, promoted = shape
            owner_id = str(item["id"])
            if owner_id in seen_owner_ids:
                raise _Refusal("source_alignment_selected_vector_owner_repeats")
            seen_owner_ids.add(owner_id)
            # The declaration itself is the sole permitted public occurrence.
            # A relationship, caption/source-note sidecar, or arbitrary nested
            # reference makes destructive ownership unavailable.
            if reference_counts[owner_id] != 1:
                continue

            row_matches: list[_SelectedVectorMember] = []
            for proof in row_proofs.get(page_index, ()):
                if not _center_inside(owner_box, proof.row_bbox):
                    continue
                if (
                    not (
                        proof.row_text_closed
                        and not all(proof.cell_source_closed)
                    )
                    and max(
                        _overlap_of_smaller(owner_box, cell_box)
                        for cell_box in proof.cell_bboxes
                    )
                    < 0.80
                ):
                    continue
                selected = _selected_vector_selection_from_line_bbox(
                    proof,
                    owner_box,
                )
                if selected is None:
                    continue
                selection, source_range = selected
                if (
                    not selection.text
                    or _reciprocal_overlap(owner_box, selection.bbox)
                    < MIN_OCR_RECIPROCAL_OVERLAP
                ):
                    continue
                ownership_mode = "exact_source_row_subrange"
                cell_index: int | None = None
                omitted: tuple[str, int, str] | None = None
                selected_characters = [
                    by_character_id.get(identifier)
                    for identifier in selection.source_character_ids
                ]
                substantive = [
                    character
                    for character in selected_characters
                    if character is not None
                    and _character_emits(character)
                    and character.text
                    and not character.text.isspace()
                ]
                exact_text = _whitespace_normalized(str(item["value"])) == (
                    _whitespace_normalized(selection.text)
                )
                if exact_text:
                    owning_cells = [
                        index
                        for index, (cell_box, cell_characters) in enumerate(
                            zip(
                                proof.cell_bboxes,
                                proof.cell_source_characters,
                                strict=True,
                            )
                        )
                        if proof.cell_source_closed[index]
                        and _center_inside(owner_box, cell_box)
                        and _overlap_of_smaller(owner_box, cell_box) >= 0.80
                        and substantive
                        and all(
                            character.bbox is not None
                            and _center_inside(character.bbox, cell_box)
                            for character in substantive
                        )
                        and {
                            character.id for character in substantive
                        }.issubset(
                            {
                                character.id
                                for character in cell_characters
                                if _character_emits(character)
                                and character.text
                                and not character.text.isspace()
                            }
                        )
                    ]
                    if len(owning_cells) == 1:
                        cell_index = owning_cells[0]
                        ownership_mode = "exact_source_cell_subrange"
                    elif not (
                        proof.row_text_closed
                        and not all(proof.cell_source_closed)
                    ):
                        continue
                else:
                    if promoted:
                        continue
                    owning_cells = [
                        index
                        for index, cell_box in enumerate(proof.cell_bboxes)
                        if _center_inside(owner_box, cell_box)
                        and all(
                            character.bbox is not None
                            and _center_inside(character.bbox, cell_box)
                            for character in substantive
                        )
                        and _whitespace_normalized(selection.text)
                        == _whitespace_normalized(proof.cell_texts[index])
                        and proof.cell_source_closed[index]
                    ]
                    if len(owning_cells) != 1:
                        continue
                    cell_index = owning_cells[0]
                    omitted = _selected_vector_visible_punctuation_omission(
                        str(item["value"]),
                        selection,
                        [
                            character
                            for character in selected_characters
                            if character is not None
                        ],
                        owner_box,
                        proof.cell_bboxes[cell_index],
                    )
                    if omitted is None:
                        continue
                    ownership_mode = "single_visible_punctuation_omission"
                row_matches.append(
                    _SelectedVectorMember(
                        page_index=page_index,
                        item_position=item_position,
                        item_snapshot=copy.deepcopy(item),
                        owner_box=owner_box,
                        selection=selection,
                        proof=proof,
                        source_range=source_range,
                        ownership_mode=ownership_mode,
                        cell_index=cell_index,
                        omitted_source_character_id=(
                            omitted[0] if omitted is not None else None
                        ),
                        omitted_offset=(
                            omitted[1] if omitted is not None else None
                        ),
                        omitted_category=(
                            omitted[2] if omitted is not None else None
                        ),
                    )
                )
                if len(row_matches) > 1:
                    break
            if len(row_matches) == 1:
                member = row_matches[0]
                if member.cell_index is not None:
                    cell_groups[
                        member.proof.cell_group_key(member.cell_index)
                    ].append(member)
                else:
                    row_groups[member.proof.group_key()].append(member)
                continue
            if len(row_matches) > 1 or not promoted:
                continue
            rotated = _selected_vector_rotated_matches(
                evidence=evidence,
                source_page=source_page,
                owner_box=owner_box,
                original_text=str(item["value"]),
                item_snapshot=item,
                item_position=item_position,
                representations=page_representations,
                cell_character_cache=cell_character_cache,
                character_comparisons=character_comparisons,
                deadline=deadline,
            )
            if len(rotated) == 1:
                rotated_members.append(rotated[0])

    selected_groups: list[
        tuple[tuple[Any, ...], list[_SelectedVectorMember]]
    ] = []
    for group_key, members in row_groups.items():
        if (
            not members
            or len(members) > MAX_SELECTED_VECTOR_MEMBERS_PER_GROUP
        ):
            continue
        proof = members[0].proof
        if any(member.proof.group_key() != group_key for member in members):
            raise _Refusal("source_alignment_selected_vector_group_identity")
        if not proof.row_text_closed or all(proof.cell_source_closed):
            continue
        substantive_ids = {
            character.id
            for character in proof.source_characters
            if _character_emits(character)
            and character.text
            and not character.text.isspace()
        }
        claimed: set[str] = set()
        conflict = False
        for member_index, member in enumerate(members):
            member_ids = {
                identifier
                for identifier in member.selection.source_character_ids
                if (
                    (character := next(
                        (
                            value
                            for value in proof.source_characters
                            if value.id == identifier
                        ),
                        None,
                    ))
                    is not None
                    and _character_emits(character)
                    and character.text
                    and not character.text.isspace()
                )
            }
            if not member_ids or claimed.intersection(member_ids):
                conflict = True
                break
            if any(
                _intersection_area(member.owner_box, prior.owner_box)
                > 0.000001
                for prior in members[:member_index]
            ):
                conflict = True
                break
            claimed.update(member_ids)
        if not conflict and claimed == substantive_ids:
            selected_groups.append((group_key, members))

    selected_cell_groups: list[
        tuple[tuple[Any, ...], list[_SelectedVectorMember]]
    ] = []
    for group_key, members in cell_groups.items():
        if (
            not members
            or len(members) > MAX_SELECTED_VECTOR_MEMBERS_PER_GROUP
        ):
            continue
        proof = members[0].proof
        cell_index = members[0].cell_index
        if (
            type(cell_index) is not int
            or cell_index < 0
            or cell_index >= len(proof.cell_source_characters)
            or not proof.cell_source_closed[cell_index]
            or any(
                member.cell_index != cell_index
                or member.proof.cell_group_key(cell_index) != group_key
                for member in members
            )
        ):
            raise _Refusal("source_alignment_selected_vector_group_identity")
        substantive_ids = {
            character.id
            for character in proof.cell_source_characters[cell_index]
            if _character_emits(character)
            and character.text
            and not character.text.isspace()
        }
        invalid = not substantive_ids
        for member in members:
            member_ids = {
                character.id
                for character in proof.cell_source_characters[cell_index]
                if character.id in member.selection.source_character_ids
                and _character_emits(character)
                and character.text
                and not character.text.isspace()
            }
            if not member_ids or not member_ids.issubset(substantive_ids):
                invalid = True
                break
        # An exact ordered source subrange is independently redundant once
        # its complete source cell is represented by the selected table.  It
        # does not inherit uncertainty from a different OCR fragment in that
        # cell.
        if not invalid:
            selected_cell_groups.append((group_key, members))

    rotated_groups: dict[
        tuple[Any, ...], list[_SelectedVectorRotatedMember]
    ] = defaultdict(list)
    for member in rotated_members:
        rotated_groups[member.group_key()].append(member)
    selected_rotated_members: list[_SelectedVectorRotatedMember] = []
    selected_rotated_group_keys: set[tuple[Any, ...]] = set()
    for group_key, rotated_group in rotated_groups.items():
        exact_members = cell_groups.get(group_key, [])
        combined: list[
            _SelectedVectorMember | _SelectedVectorRotatedMember
        ] = [*exact_members, *rotated_group]
        if (
            not rotated_group
            or len(combined) > MAX_SELECTED_VECTOR_MEMBERS_PER_GROUP
        ):
            continue
        full_ids = tuple(rotated_group[0].cell_source_character_ids)
        full_id_set = set(full_ids)
        if (
            not full_ids
            or len(full_ids) != len(full_id_set)
            or any(
                member.group_key() != group_key
                or tuple(member.cell_source_character_ids) != full_ids
                for member in rotated_group
            )
        ):
            raise _Refusal("source_alignment_selected_vector_group_identity")
        claimed: set[str] = set()
        conflict = False
        for member_index, member in enumerate(combined):
            member_ids = {
                identifier
                for identifier in member.selection.source_character_ids
                if identifier in full_id_set
            }
            if (
                not member_ids
                or not member_ids.issubset(full_id_set)
                or claimed.intersection(member_ids)
                or any(
                    _intersection_area(member.owner_box, prior.owner_box)
                    > 0.000001
                    for prior in combined[:member_index]
                )
            ):
                conflict = True
                break
            claimed.update(member_ids)
        # Rotation permits order-insensitive matching only when the complete
        # cell is collectively and uniquely accounted for by disjoint owner
        # slices.  Partial or cross-cell fragments remain public.
        collectively_closed = not conflict and claimed == full_id_set
        admitted_rotated = [
            member
            for member in rotated_group
            if collectively_closed
            or member.ownership_mode
            == "rotated_contiguous_two_token_reversal"
        ]
        if admitted_rotated:
            selected_rotated_members.extend(admitted_rotated)
            selected_rotated_group_keys.add(group_key)

    cell_partition_count = len(selected_cell_groups) + len(
        selected_rotated_group_keys
    )
    if cell_partition_count > MAX_SELECTED_VECTOR_SLOTS:
        raise _Refusal("source_alignment_selected_vector_cell_partition_limit")
    shared_row_group_keys = {
        members[0].proof.group_key()
        for _key, members in (*selected_groups, *selected_cell_groups)
    }
    group_count = len(shared_row_group_keys) + len(
        selected_rotated_group_keys
    )
    selected_member_count = sum(
        len(members) for _key, members in selected_groups
    ) + sum(
        len(members) for _key, members in selected_cell_groups
    ) + len(selected_rotated_members)
    candidate_count = owner_attempts + group_count * 2
    if (
        group_count > MAX_SELECTED_VECTOR_GROUPS
        or selected_member_count > MAX_SELECTED_VECTOR_SELECTIONS
        or candidate_count > MAX_SELECTED_VECTOR_CANDIDATES
    ):
        raise _Refusal("source_alignment_selected_vector_resource_limit")

    selected_members: list[
        tuple[int, int, AlignmentSelection]
    ] = []
    for group_key, members in (*selected_groups, *selected_cell_groups):
        group_digest = _selected_vector_digest(list(group_key))
        for member in members:
            selected_members.append(
                (
                    member.page_index,
                    member.item_position,
                    _selected_vector_alignment_selection(
                        evidence,
                        member,
                        group_key_sha256=group_digest,
                    ),
                )
            )
    for member in selected_rotated_members:
        group_digest = _selected_vector_digest(list(member.group_key()))
        selected_members.append(
            (
                member.page_index,
                member.item_position,
                _selected_vector_alignment_selection(
                    evidence,
                    member,
                    group_key_sha256=group_digest,
                ),
            )
        )
    selected_members.sort(key=lambda value: (value[0], value[1]))
    selected_ids_by_page: dict[int, set[str]] = defaultdict(set)
    for page_index, _position, selection in selected_members:
        if selection.owner_id in selected_ids_by_page[page_index]:
            raise _Refusal("source_alignment_selected_vector_owner_repeats")
        selected_ids_by_page[page_index].add(selection.owner_id)
    for page_position, page in enumerate(pages, start=1):
        page_index = page.get("page_index")
        if type(page_index) is not int:
            page_index = page_position
        selected_ids = selected_ids_by_page.get(page_index)
        if not selected_ids:
            continue
        items = page.get("items")
        if type(items) is not list:
            raise _Refusal("source_alignment_items_invalid")
        retained = []
        removed: set[str] = set()
        for item in items:
            item_id = item.get("id") if type(item) is dict else None
            if item_id in selected_ids:
                if item_id in removed:
                    raise _Refusal("source_alignment_selected_vector_owner_repeats")
                removed.add(item_id)
            else:
                retained.append(item)
        if removed != selected_ids:
            raise _Refusal("source_alignment_selected_vector_owner_missing")
        page["items"] = retained
    return (
        [selection for _page, _position, selection in selected_members],
        owner_attempts,
        candidate_count,
        group_count,
    )


def validate_table_owned_suppression(
    selection: Mapping[str, Any],
    evidence: SourceTextEvidence,
    authoritative_table_views: Mapping[
        int, Sequence[Mapping[str, Any]]
    ]
    | None,
) -> bool:
    """Independently reconstruct one table-owned suppression proof."""

    return validate_table_owned_suppressions(
        (selection,),
        evidence,
        authoritative_table_views,
    )


def _validate_table_owned_suppression_with_admitted_views(
    selection: Mapping[str, Any],
    evidence: SourceTextEvidence,
    source_pages: Mapping[int, SourcePageEvidence],
    admitted: Mapping[int, Sequence[Mapping[str, Any]]],
    *,
    deadline: float,
    structural_cache: _TableOwnedStructuralLineCache,
) -> bool:
    """Reconstruct one proof after the private authority map is admitted."""

    if (
        not isinstance(selection, Mapping)
        or selection.get("terminal_reason")
        != TABLE_OWNED_SUPPLEMENTAL_REASON
        or selection.get("selected_text") != ""
    ):
        return False
    page_index = selection.get("page_index")
    owner_box = _mapping_bbox_in_unit(selection.get("owner_bbox"), "pt")
    source_line_ids = selection.get("source_line_ids")
    rejected = selection.get("rejected_ocr_alternative")
    canonical_owner = (
        rejected.get("canonical_owner")
        if isinstance(rejected, Mapping)
        else None
    )
    contributor = (
        rejected.get("ocr_contributor")
        if isinstance(rejected, Mapping)
        else None
    )
    owner_type = selection.get("owner_type")
    promoted_owner_shape = (
        rejected.get("promoted_owner_shape")
        if isinstance(rejected, Mapping)
        else None
    )
    owner_shape_valid = bool(
        owner_type == "text" and promoted_owner_shape is None
        or owner_type == "heading"
        and _validated_promoted_supplemental_heading_shape(
            promoted_owner_shape,
            original_text=str(selection.get("original_text") or ""),
        )
    )
    if (
        not isinstance(page_index, int)
        or isinstance(page_index, bool)
        or owner_box is None
        or not isinstance(source_line_ids, Sequence)
        or isinstance(source_line_ids, (str, bytes, bytearray))
        or len(source_line_ids) != 1
        or not isinstance(canonical_owner, Mapping)
        or not owner_shape_valid
        or rejected.get("reason") != TABLE_OWNED_SUPPLEMENTAL_REASON
        or rejected.get("text") != selection.get("original_text")
        or rejected.get("source") != "ocr"
        or _mapping_bbox_in_unit(rejected.get("bbox"), "pt") != owner_box
        or not isinstance(rejected.get("confidence"), (int, float))
        or isinstance(rejected.get("confidence"), bool)
        or not math.isfinite(float(rejected["confidence"]))
        or not 0.0 <= float(rejected["confidence"]) <= 1.0
        or _validated_supplemental_ocr_contributor(
            contributor,
            source_sha256=evidence.source_sha256,
            page_index=page_index,
            owner_box=owner_box,
            raw_text=str(rejected.get("text") or ""),
            confidence=float(rejected["confidence"]),
        )
        is None
    ):
        return False
    source_page = source_pages.get(page_index)
    if source_page is None:
        return False
    line_matches = [
        line for line in source_page.lines if line.id == source_line_ids[0]
    ]
    if len(line_matches) != 1:
        return False
    owner_selection = text_for_bbox(
        evidence,
        page_index,
        owner_box,
        deadline=deadline,
    )
    original_text = str(selection.get("original_text") or "")
    if (
        owner_selection is None
        or not original_text
        or not (
            _alignment_skeleton(original_text)
            == _alignment_skeleton(owner_selection.text)
            or _single_substitution(
                _alignment_skeleton(original_text),
                _alignment_skeleton(owner_selection.text),
            )
        )
        or _reciprocal_overlap(owner_box, owner_selection.bbox)
        < MIN_OCR_RECIPROCAL_OVERLAP
        or _complete_source_line_for_table_candidate(
            source_page,
            owner_selection,
            deadline=deadline,
        )
        != line_matches[0]
    ):
        return False
    matches = _source_line_table_matches(
        source_page=source_page,
        complete_line=line_matches[0],
        owner_box=owner_box,
        tables=admitted.get(page_index, ()),
        deadline=deadline,
        structural_cache=structural_cache,
    )
    return (
        len(matches) == 1
        and matches[0].canonical_owner() == dict(canonical_owner)
    )


def _validate_rotated_cell_suppression_with_admitted_views(
    selection: Mapping[str, Any],
    evidence: SourceTextEvidence,
    source_pages: Mapping[int, SourcePageEvidence],
    admitted: Mapping[int, Sequence[Mapping[str, Any]]],
    *,
    deadline: float,
    authority_cache: _TableOwnedCellAuthorityCache,
) -> bool:
    """Independently rebuild one promoted-heading canonical-cell proof."""

    if (
        not isinstance(selection, Mapping)
        or selection.get("terminal_reason")
        != TABLE_OWNED_ROTATED_CELL_REASON
        or selection.get("selected_text") != ""
        or selection.get("owner_type") != "heading"
        or selection.get("method") != "source_safe_rotated_table_cell"
    ):
        return False
    page_index = selection.get("page_index")
    owner_box = _mapping_bbox_in_unit(selection.get("owner_bbox"), "pt")
    original_text = selection.get("original_text")
    rejected = selection.get("rejected_ocr_alternative")
    canonical_owner = (
        rejected.get("canonical_owner")
        if isinstance(rejected, Mapping)
        else None
    )
    contributor = (
        rejected.get("ocr_contributor")
        if isinstance(rejected, Mapping)
        else None
    )
    promoted_owner_shape = (
        rejected.get("promoted_owner_shape")
        if isinstance(rejected, Mapping)
        else None
    )
    checks = selection.get("checks")
    required_checks = {
        "authenticated_promoted_heading",
        "case_preserving_glyph_multiset",
        "order_insensitive_rotation_only",
        "ocr_evidence_retained",
        "canonical_table_authority",
        "same_page_coordinate_unit",
        "source_character_geometry_coverage",
        "unique_table_cell_owner",
        "table_cell_source_lineage",
    }
    if (
        not isinstance(page_index, int)
        or isinstance(page_index, bool)
        or owner_box is None
        or not isinstance(original_text, str)
        or not original_text
        or not isinstance(canonical_owner, Mapping)
        or not _validated_promoted_supplemental_heading_shape(
            promoted_owner_shape,
            original_text=original_text,
        )
        or rejected.get("reason") != TABLE_OWNED_ROTATED_CELL_REASON
        or rejected.get("text") != original_text
        or rejected.get("source") != "ocr"
        or _mapping_bbox_in_unit(rejected.get("bbox"), "pt") != owner_box
        or not isinstance(rejected.get("confidence"), (int, float))
        or isinstance(rejected.get("confidence"), bool)
        or not math.isfinite(float(rejected["confidence"]))
        or not 0.0 <= float(rejected["confidence"]) <= 1.0
        or _validated_supplemental_ocr_contributor(
            contributor,
            source_sha256=evidence.source_sha256,
            page_index=page_index,
            owner_box=owner_box,
            raw_text=original_text,
            confidence=float(rejected["confidence"]),
        )
        is None
        or not isinstance(checks, Mapping)
        or any(checks.get(name) is not True for name in required_checks)
    ):
        return False
    source_page = source_pages.get(page_index)
    if source_page is None:
        return False
    owner_selection = text_for_bbox(
        evidence,
        page_index,
        owner_box,
        deadline=deadline,
    )
    raw_line_ids = selection.get("source_line_ids")
    raw_character_ids = selection.get("source_character_ids")
    if (
        owner_selection is None
        or not isinstance(raw_line_ids, Sequence)
        or isinstance(raw_line_ids, (str, bytes, bytearray))
        or not isinstance(raw_character_ids, Sequence)
        or isinstance(raw_character_ids, (str, bytes, bytearray))
        or tuple(raw_line_ids) != owner_selection.source_line_ids
        or tuple(raw_character_ids) != owner_selection.source_character_ids
    ):
        return False
    matches = _source_selection_table_cell_matches(
        source_page=source_page,
        selection=owner_selection,
        original_text=original_text,
        owner_box=owner_box,
        tables=admitted.get(page_index, ()),
        deadline=deadline,
        authority_cache=authority_cache,
    )
    return bool(
        len(matches) == 1
        and matches[0].canonical_owner() == dict(canonical_owner)
    )


def validate_table_owned_suppressions(
    selections: Sequence[Mapping[str, Any]],
    evidence: SourceTextEvidence,
    authoritative_table_views: Mapping[
        int, Sequence[Mapping[str, Any]]
    ]
    | None,
) -> bool:
    """Validate a bounded suppression batch under one aggregate deadline."""

    deadline = time.perf_counter() + MAX_ALIGNMENT_SECONDS
    try:
        if (
            not isinstance(selections, Sequence)
            or isinstance(selections, (str, bytes, bytearray))
            or len(selections)
            > MAX_TABLE_OWNED_SUPPLEMENTAL_SELECTIONS
        ):
            return False
        admitted = _admit_authoritative_table_views(
            authoritative_table_views,
            evidence,
            deadline=deadline,
        )
        source_pages = {page.page_index: page for page in evidence.pages}
        structural_cache = _TableOwnedStructuralLineCache()
        authority_cache = _TableOwnedCellAuthorityCache()
        for selection_index, selection in enumerate(selections, start=1):
            if (
                selection_index % 16 == 0
                and time.perf_counter() > deadline
            ):
                raise _Refusal("source_alignment_deadline")
            terminal_reason = (
                selection.get("terminal_reason")
                if isinstance(selection, Mapping)
                else None
            )
            if terminal_reason == TABLE_OWNED_SUPPLEMENTAL_REASON:
                valid = _validate_table_owned_suppression_with_admitted_views(
                    selection,
                    evidence,
                    source_pages,
                    admitted,
                    deadline=deadline,
                    structural_cache=structural_cache,
                )
            elif terminal_reason == TABLE_OWNED_ROTATED_CELL_REASON:
                valid = _validate_rotated_cell_suppression_with_admitted_views(
                    selection,
                    evidence,
                    source_pages,
                    admitted,
                    deadline=deadline,
                    authority_cache=authority_cache,
                )
            else:
                valid = False
            if not valid:
                return False
        return time.perf_counter() <= deadline
    except (_Refusal, MemoryError, RecursionError, TypeError, ValueError):
        return False


def validate_selected_vector_suppressions(
    selections: Sequence[Mapping[str, Any]],
    evidence: SourceTextEvidence,
    selected_vector_representations: Mapping[
        int, Sequence[Mapping[str, Any]]
    ]
    | None,
    terminal_pages: Sequence[Mapping[str, Any]],
) -> bool:
    """Freshly rebuild vector groups and every deleted owner from snapshots."""

    deadline = (
        time.perf_counter() + MAX_SELECTED_VECTOR_ALIGNMENT_SECONDS
    )
    try:
        if (
            type(selections) not in (list, tuple)
            or not selections
            or len(selections) > MAX_SELECTED_VECTOR_SELECTIONS
            or type(terminal_pages) not in (list, tuple)
        ):
            return False
        replay_pages = copy.deepcopy(list(terminal_pages))
        pages_by_index: dict[int, dict[str, Any]] = {}
        for position, page in enumerate(replay_pages, start=1):
            if type(page) is not dict:
                return False
            page_index = page.get("page_index")
            if type(page_index) is not int:
                page_index = position
            if page_index in pages_by_index:
                return False
            pages_by_index[page_index] = page
        insertions: dict[int, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
        owner_ids: set[str] = set()
        for selection in selections:
            if (
                type(selection) is not dict
                or selection.get("terminal_reason")
                != SELECTED_VECTOR_REPRESENTATION_REASON
                or selection.get("selected_text") != ""
            ):
                return False
            rejected = selection.get("rejected_ocr_alternative")
            canonical_owner = (
                rejected.get("canonical_owner")
                if type(rejected) is dict
                else None
            )
            snapshot = rejected.get("owner_snapshot") if type(rejected) is dict else None
            page_index = selection.get("page_index")
            owner_id = selection.get("owner_id")
            item_position = (
                canonical_owner.get("owner_item_position")
                if type(canonical_owner) is dict
                else None
            )
            if (
                type(page_index) is not int
                or page_index not in pages_by_index
                or type(owner_id) is not str
                or not owner_id
                or owner_id in owner_ids
                or type(snapshot) is not dict
                or snapshot.get("id") != owner_id
                or type(item_position) is not int
                or item_position < 0
                or _selected_vector_owner_shape(
                    snapshot,
                    page_index=page_index,
                    source_sha256=evidence.source_sha256,
                )
                is None
                or rejected.get("text") != selection.get("original_text")
                or rejected.get("reason")
                != SELECTED_VECTOR_REPRESENTATION_REASON
                or rejected.get("source") != "ocr"
                or rejected.get("ocr_contributor")
                != snapshot.get("ocr_contributor")
                or _mapping_bbox_in_unit(rejected.get("bbox"), "pt")
                != _mapping_bbox_in_unit(snapshot.get("bbox"), "pt")
            ):
                return False
            if any(
                type(item) is dict and item.get("id") == owner_id
                for item in pages_by_index[page_index].get("items") or []
            ):
                return False
            owner_ids.add(owner_id)
            insertions[page_index].append(
                (item_position, copy.deepcopy(snapshot))
            )
        for page_index, values in insertions.items():
            items = pages_by_index[page_index].get("items")
            if type(items) is not list:
                return False
            insertion_by_position: dict[int, dict[str, Any]] = {}
            final_length = len(items) + len(values)
            for item_position, snapshot in values:
                if (
                    item_position >= final_length
                    or item_position in insertion_by_position
                ):
                    return False
                insertion_by_position[item_position] = snapshot
            # Reconstruct the exact predecessor sequence in one bounded linear
            # merge.  Repeated list.insert shifted O(n^2) elements at the NY
            # 1,765-member replay boundary and caused otherwise-valid deadline
            # jitter.
            item_iterator = iter(items)
            rebuilt_items: list[dict[str, Any]] = []
            for item_position in range(final_length):
                snapshot = insertion_by_position.get(item_position)
                if snapshot is not None:
                    rebuilt_items.append(snapshot)
                    continue
                try:
                    rebuilt_items.append(next(item_iterator))
                except StopIteration:
                    return False
            try:
                next(item_iterator)
            except StopIteration:
                pass
            else:
                return False
            pages_by_index[page_index]["items"] = rebuilt_items
        rebuilt, _owners, _candidates, _groups = (
            _apply_selected_vector_suppressions(
                replay_pages,
                evidence,
                selected_vector_representations,
                deadline=deadline,
            )
        )
        if len(rebuilt) != len(selections):
            return False
        for rebuilt_selection, expected_selection in zip(
            rebuilt,
            selections,
            strict=True,
        ):
            if rebuilt_selection.to_dict() != expected_selection:
                return False
        return bool(
            replay_pages == list(terminal_pages)
            and time.perf_counter() <= deadline
        )
    except (
        _Refusal,
        AttributeError,
        MemoryError,
        OverflowError,
        RecursionError,
        TimeoutError,
        TypeError,
        UnicodeError,
        ValueError,
    ):
        return False


def _supported_line_space_repair(
    original: str,
    owner_box: SourceBBox,
    source_page: SourcePageEvidence,
    *,
    reserve_candidates: Callable[[int], None],
    deadline: float,
) -> tuple[str, SourceTextSelection] | None:
    original_skeleton = _alignment_skeleton(original)
    candidates: list[tuple[str, SourceTextSelection]] = []
    for line_index, line in enumerate(source_page.lines, start=1):
        if (
            line_index % 64 == 0
            and time.perf_counter() > deadline
        ):
            raise _Refusal("source_alignment_deadline")
        if (
            line.has_unsafe_character
            or len(_alignment_skeleton(line.text)) < 12
            or _overlap_of_smaller(owner_box, line.bbox) < 0.15
        ):
            continue
        needle = _alignment_skeleton(line.text)
        if _substring_count(original_skeleton, needle) != 1:
            continue
        selection = _selection_from_line(source_page, line)
        characters = _selection_characters(
            SourceTextEvidence(
                schema_version="",
                policy_id="",
                source_sha256="",
                usable=True,
                refusal_code=None,
                page_count=1,
                character_count=len(source_page.characters),
                line_count=len(source_page.lines),
                type1_glyph_count=0,
                pages=(source_page,),
                type1_glyphs=(),
                diagnostics=(),
                elapsed_ms=0,
            ),
            selection,
        )
        if not any(
            character.raw_code_point == 0x20
            and character.space_supported
            for character in characters
        ):
            continue

        # Map the unique alphanumeric occurrence back to an original string
        # interval, then test a small punctuation tail.  No spelling or
        # punctuation inference is involved.
        skeleton_chars: list[str] = []
        source_positions: list[int] = []
        for position, character in enumerate(original):
            normalized = unicodedata.normalize("NFD", character.casefold())
            for part in normalized:
                if (
                    part.isalnum()
                    and unicodedata.category(part) != "Mn"
                ):
                    skeleton_chars.append(part)
                    source_positions.append(position)
        flattened = "".join(skeleton_chars)
        start_in_skeleton = flattened.find(needle)
        if start_in_skeleton < 0:
            continue
        start = source_positions[start_in_skeleton]
        alnum_end = source_positions[
            start_in_skeleton + len(needle) - 1
        ] + 1
        for end in range(
            alnum_end,
            min(len(original), alnum_end + 8) + 1,
        ):
            old_span = original[start:end]
            if "".join(old_span.split()) != "".join(line.text.split()):
                continue
            if not (
                _whitespace_gap_positions(old_span)
                < _whitespace_gap_positions(line.text)
            ):
                continue
            selected = (
                original[:start] + line.text + original[end:]
            )
            if selected != original:
                reserve_candidates(1)
                candidates.append((selected, selection))
            break
    return candidates[0] if len(candidates) == 1 else None


def _alignment_selection(
    *,
    evidence: SourceTextEvidence,
    page_index: int,
    owner_id: str,
    owner_type: str,
    owner_box: SourceBBox,
    original_text: str,
    selected_text: str,
    selection: SourceTextSelection,
    method: str,
    checks: Mapping[str, bool],
    rejected_ocr: dict[str, Any] | None = None,
    terminal_reason: str = "selected_source_safe_candidate",
) -> AlignmentSelection:
    return AlignmentSelection(
        id=_selection_id(
            evidence.source_sha256,
            page_index,
            owner_id,
            original_text,
            selected_text,
        ),
        page_index=page_index,
        owner_id=owner_id,
        owner_type=owner_type,
        owner_bbox=owner_box.to_dict(),
        original_text=original_text,
        selected_text=selected_text,
        selected_source="pdf_source_text",
        source_line_ids=selection.source_line_ids,
        source_character_ids=selection.source_character_ids,
        type1_mapping_ids=selection.type1_evidence_ids,
        source_roles=selection.source_roles,
        method=method,
        checks={str(key): bool(value) for key, value in checks.items()},
        terminal_reason=terminal_reason,
        rejected_ocr_alternative=rejected_ocr,
    )


def _refused_summary(
    source_sha256: str,
    code: str,
    started: float,
) -> SourceAlignmentSummary:
    concern = {
        "status": "unresolved",
        "reason": code,
        "evidence_ids": [],
    }
    return SourceAlignmentSummary(
        schema_version=SOURCE_TEXT_ALIGNMENT_SCHEMA_VERSION,
        policy_id=SOURCE_TEXT_ALIGNMENT_POLICY_ID,
        source_sha256=source_sha256,
        status="refused",
        considered_count=1,
        selected_count=0,
        unchanged_count=0,
        unresolved_count=1,
        selections=(),
        concerns=(concern,),
        elapsed_ms=round((time.perf_counter() - started) * 1000, 6),
    )


def _validate_alignment_input_scan_bounds(
    pages: Sequence[Any],
    *,
    deadline: float,
) -> None:
    """Bound every page item and table cell before transactional copying."""

    scanned = 0
    for page in pages:
        if not isinstance(page, Mapping):
            raise _Refusal("source_alignment_page_invalid")
        items = page.get("items") or []
        if not isinstance(items, list):
            raise _Refusal("source_alignment_items_invalid")
        scanned += len(items)
        if scanned > MAX_SCANNED_OWNERS:
            raise _Refusal("source_alignment_owner_scan_limit")
        for item in items:
            if not isinstance(item, Mapping):
                continue
            if (
                item.get("type") in _SOURCE_SPACE_ONLY_OWNER_TYPES
                and "items" in item
            ):
                nested_items = item.get("items")
                if not isinstance(nested_items, list):
                    raise _Refusal(
                        "source_alignment_nested_items_invalid"
                    )
                if len(nested_items) > MAX_EVIDENCE_REFS:
                    raise _Refusal(
                        "source_alignment_nested_items_limit"
                    )
                if any(
                    not isinstance(nested_item, Mapping)
                    for nested_item in nested_items
                ):
                    raise _Refusal(
                        "source_alignment_nested_item_invalid"
                    )
                scanned += len(nested_items)
                if scanned > MAX_SCANNED_OWNERS:
                    raise _Refusal("source_alignment_owner_scan_limit")
                # This check runs before the transaction-wide deepcopy.  It
                # bounds both ordinary payload size and hostile recursive or
                # deeply nested child shapes at the newly admitted
                # header/footer seam.
                _bounded_json_size(
                    nested_items,
                    max_bytes=MAX_REPORT_BYTES,
                    deadline=deadline,
                    refusal_code=(
                        "source_alignment_nested_items_size_limit"
                    ),
                )
            if item.get("type") != "table":
                continue
            cells = item.get("cells") or []
            if not isinstance(cells, list):
                raise _Refusal("source_alignment_table_cells_invalid")
            scanned += len(cells)
            if scanned > MAX_SCANNED_OWNERS:
                raise _Refusal("source_alignment_owner_scan_limit")
            if (
                scanned % 256 == 0
                and time.perf_counter() > deadline
            ):
                raise _Refusal("source_alignment_deadline")
        if time.perf_counter() > deadline:
            raise _Refusal("source_alignment_deadline")


def align_pages_to_source(
    pages: list[dict[str, Any]],
    evidence: SourceTextEvidence,
    *,
    authoritative_table_views: Mapping[
        int, Sequence[Mapping[str, Any]]
    ]
    | None = None,
    selected_vector_representations: Mapping[
        int, Sequence[Mapping[str, Any]]
    ]
    | None = None,
) -> SourceAlignmentSummary:
    """Transactionally align final normalized page owners to source text."""

    started = time.perf_counter()
    try:
        if not isinstance(pages, list) or not evidence.usable:
            raise _Refusal(
                evidence.refusal_code or "source_alignment_evidence_unusable"
            )
        if evidence.policy_id != SOURCE_TEXT_ALIGNMENT_POLICY_ID:
            raise _Refusal("source_alignment_policy_mismatch")
        evidence_elapsed = evidence.elapsed_ms
        if (
            not isinstance(evidence_elapsed, (int, float))
            or isinstance(evidence_elapsed, bool)
            or not math.isfinite(float(evidence_elapsed))
            or float(evidence_elapsed) < 0
        ):
            raise _Refusal("source_alignment_evidence_elapsed_invalid")
        selected_vector_budget_eligible = (
            type(selected_vector_representations) in (dict, defaultdict)
            and bool(selected_vector_representations)
            and authoritative_table_views is None
        )
        aggregate_seconds = (
            MAX_SELECTED_VECTOR_ALIGNMENT_SECONDS
            if selected_vector_budget_eligible
            else MAX_ALIGNMENT_SECONDS
        )
        remaining = aggregate_seconds - float(evidence_elapsed) / 1000
        if remaining <= 0:
            raise _Refusal("source_alignment_deadline")
        deadline = started + remaining
        if len(pages) != evidence.page_count:
            raise _Refusal("source_alignment_page_count_mismatch")

        _validate_alignment_input_scan_bounds(
            pages,
            deadline=deadline,
        )
        admitted_table_views = _admit_authoritative_table_views(
            authoritative_table_views,
            evidence,
            deadline=deadline,
        )
        working = copy.deepcopy(pages)
        if time.perf_counter() > deadline:
            raise _Refusal("source_alignment_deadline")
        source_pages = {
            page.page_index: page for page in evidence.pages
        }
        table_owned_structural_cache = _TableOwnedStructuralLineCache()
        table_owned_cell_authority_cache = _TableOwnedCellAuthorityCache()
        vector_selections: list[AlignmentSelection] = []
        vector_owner_count = 0
        vector_candidate_count = 0
        vector_group_count = 0
        # This representation is a non-P04 fallback.  Never combine two
        # independently minted table authorities in one destructive pass.
        if selected_vector_representations is not None and not admitted_table_views:
            (
                vector_selections,
                vector_owner_count,
                vector_candidate_count,
                vector_group_count,
            ) = _apply_selected_vector_suppressions(
                working,
                evidence,
                selected_vector_representations,
                deadline=deadline,
            )
        selections: list[AlignmentSelection] = list(vector_selections)
        concerns: list[dict[str, Any]] = []
        considered = 0
        table_owned_supplemental_considered = 0
        scanned_owners = 0
        total_candidates = 0
        unchanged = 0
        generic_selection_count = 0
        table_owned_supplemental_selection_count = 0

        def scan_owner() -> None:
            nonlocal scanned_owners
            scanned_owners += 1
            if scanned_owners > MAX_SCANNED_OWNERS:
                raise _Refusal("source_alignment_owner_scan_limit")
            if (
                scanned_owners % 256 == 0
                and time.perf_counter() > deadline
            ):
                raise _Refusal("source_alignment_deadline")

        def reserve_owner(
            *,
            table_owned_supplemental_candidate: bool = False,
        ) -> None:
            nonlocal considered, table_owned_supplemental_considered
            if table_owned_supplemental_candidate:
                table_owned_supplemental_considered += 1
                if (
                    table_owned_supplemental_considered
                    > MAX_TABLE_OWNED_SUPPLEMENTAL_OWNERS
                ):
                    raise _Refusal(
                        "source_alignment_table_owned_supplemental_owner_limit"
                    )
            else:
                considered += 1
                if considered > MAX_OWNERS:
                    raise _Refusal("source_alignment_owner_limit")
            if (
                considered + table_owned_supplemental_considered
                > MAX_TOTAL_ALIGNMENT_OWNERS
            ):
                raise _Refusal("source_alignment_total_owner_limit")
            if time.perf_counter() > deadline:
                raise _Refusal("source_alignment_deadline")

        def candidate_reserver() -> Callable[[int], None]:
            owner_candidates = 0

            def reserve(count: int) -> None:
                nonlocal owner_candidates, total_candidates
                if (
                    not isinstance(count, int)
                    or isinstance(count, bool)
                    or count < 0
                ):
                    raise _Refusal(
                        "source_alignment_candidate_count_invalid"
                    )
                owner_candidates += count
                total_candidates += count
                if owner_candidates > MAX_CANDIDATES_PER_OWNER:
                    raise _Refusal(
                        "source_alignment_owner_candidate_limit"
                    )
                if total_candidates > MAX_TOTAL_CANDIDATES:
                    raise _Refusal(
                        "source_alignment_total_candidate_limit"
                    )
                if (
                    total_candidates + vector_candidate_count
                    > MAX_SELECTED_VECTOR_CANDIDATES
                ):
                    raise _Refusal(
                        "source_alignment_combined_candidate_limit"
                    )
                if time.perf_counter() > deadline:
                    raise _Refusal("source_alignment_deadline")

            return reserve

        def reserve_selection(
            alignment: AlignmentSelection,
            *,
            table_owned_supplemental: bool = False,
        ) -> None:
            nonlocal generic_selection_count
            nonlocal table_owned_supplemental_selection_count
            if table_owned_supplemental:
                if (
                    alignment.terminal_reason
                    not in TABLE_OWNED_TERMINAL_REASONS
                    or alignment.selected_text != ""
                ):
                    raise _Refusal(
                        "source_alignment_table_owned_supplemental_selection_invalid"
                    )
                if (
                    table_owned_supplemental_selection_count
                    >= MAX_TABLE_OWNED_SUPPLEMENTAL_SELECTIONS
                ):
                    raise _Refusal(
                        "source_alignment_table_owned_supplemental_selection_limit"
                    )
                table_owned_supplemental_selection_count += 1
            else:
                if generic_selection_count >= MAX_SELECTIONS:
                    raise _Refusal("source_alignment_selection_limit")
                generic_selection_count += 1
            if len(selections) >= MAX_TOTAL_ALIGNMENT_SELECTIONS:
                raise _Refusal("source_alignment_total_selection_limit")

        def commit_text_selection(
            item: dict[str, Any],
            alignment: AlignmentSelection,
            *,
            nested_items: list[dict[str, Any]] | None = None,
            selected_markdown: str | None = None,
            table_owned_supplemental: bool = False,
        ) -> None:
            reserve_selection(
                alignment,
                table_owned_supplemental=table_owned_supplemental,
            )
            if nested_items is not None:
                item["items"] = nested_items
            _refresh_text_item(item, alignment.selected_text)
            if selected_markdown is not None:
                item["md"] = selected_markdown
            item["source"] = "native"
            item["source_alignment"] = _trace_for_selection(
                alignment,
                evidence.source_sha256,
            )
            selections.append(alignment)

        for page_position, page in enumerate(working, start=1):
            try:
                page_index = int(page.get("page_index") or page_position)
            except (TypeError, ValueError):
                raise _Refusal("source_alignment_page_index_invalid")
            source_page = source_pages.get(page_index)
            if source_page is None:
                raise _Refusal("source_alignment_page_identity_mismatch")
            if (
                abs(
                    float(page.get("page_width") or source_page.page_width)
                    - source_page.page_width
                )
                > 0.05
                or abs(
                    float(page.get("page_height") or source_page.page_height)
                    - source_page.page_height
                )
                > 0.05
            ):
                raise _Refusal(
                    "source_alignment_page_dimensions_mismatch"
                )

            page_items = page.get("items") or []
            if not isinstance(page_items, list):
                raise _Refusal("source_alignment_items_invalid")
            for item_position, item in enumerate(
                tuple(page_items),
                start=1,
            ):
                scan_owner()
                if not isinstance(item, dict):
                    continue
                owner_id = str(
                    item.get("id")
                    or f"p{page_index}-i{item_position}"
                )
                owner_type = str(item.get("type") or "unknown")
                if owner_type == "table":
                    # P04-US01 table text is source-custodied as a complete
                    # grid.  Terminal source alignment must not mutate either
                    # an authoritative grid or a non-authoritative diagnostic;
                    # any future text refresh needs a fresh table evidence
                    # decision and atomic representation-custody update.
                    if "table_evidence" in item:
                        continue
                    table_changed = False
                    cells = item.get("cells") or []
                    if not isinstance(cells, list):
                        continue
                    for cell in cells:
                        scan_owner()
                        if not isinstance(cell, dict):
                            continue
                        cell_box = _mapping_bbox(cell.get("bbox"))
                        original = str(cell.get("text") or "")
                        if cell_box is None or not original:
                            continue
                        if not (
                            re.search(r"(?:^|[\s(])-\s*\d", original)
                            and re.search(r"\d,\d", original)
                        ):
                            continue
                        reserve_owner()
                        reserve_candidates = candidate_reserver()
                        selection = text_for_bbox(
                            evidence,
                            page_index,
                            cell_box,
                            deadline=deadline,
                        )
                        if (
                            selection is None
                            or selection.text == original
                        ):
                            unchanged += 1
                            continue
                        projection = _layout_projection_text(
                            evidence,
                            selection,
                        )
                        if not _selection_unique_on_page(
                            source_page,
                            original,
                            selection,
                            projection,
                            reserve_candidates=reserve_candidates,
                        ):
                            unchanged += 1
                            continue
                        method = _selection_method(
                            evidence,
                            selection,
                            original,
                        )
                        if (
                            method is None
                            or method[0] != "pdfium_native_text"
                            or not method[1].get(
                                "literal_source_minus",
                                False,
                            )
                            or not all(method[1].values())
                        ):
                            unchanged += 1
                            continue
                        row = max(int(cell.get("row", 0)), 0)
                        column = max(int(cell.get("column", 0)), 0)
                        rows = item.get("rows") or item.get("value") or []
                        if (
                            row >= len(rows)
                            or column >= len(rows[row])
                        ):
                            raise _Refusal(
                                "source_alignment_table_shape_mismatch"
                            )
                        alignment = _alignment_selection(
                            evidence=evidence,
                            page_index=page_index,
                            owner_id=(
                                f"{owner_id}:r{row}:c{column}"
                            ),
                            owner_type="table_cell",
                            owner_box=cell_box,
                            original_text=original,
                            selected_text=selection.text,
                            selection=selection,
                            method=method[0],
                            checks=method[1],
                        )
                        reserve_selection(alignment)
                        cell["text"] = selection.text
                        rows[row][column] = selection.text
                        item["rows"] = rows
                        selections.append(alignment)
                        table_changed = True
                    if table_changed:
                        _refresh_table(item)
                        item["source_alignment"] = {
                            "schema_version": (
                                SOURCE_TEXT_ALIGNMENT_SCHEMA_VERSION
                            ),
                            "policy_id": SOURCE_TEXT_ALIGNMENT_POLICY_ID,
                            "source_sha256": evidence.source_sha256,
                            "selection_ids": [
                                selection.id
                                for selection in selections
                                if selection.owner_id.startswith(
                                    f"{owner_id}:"
                                )
                            ],
                        }
                    continue

                original_value = item.get("value")
                source_space_only = owner_type in _SOURCE_SPACE_ONLY_OWNER_TYPES
                owner_box = (
                    _mapping_bbox_in_unit(item.get("bbox"), source_page.unit)
                    if source_space_only
                    else _mapping_bbox(item.get("bbox"))
                )
                if (
                    not isinstance(original_value, str)
                    or not original_value
                    or owner_box is None
                    or owner_type not in _TEXT_ALIGNMENT_OWNER_TYPES
                    or source_space_only
                    and not _source_space_owner_page_binds(page, source_page)
                ):
                    continue
                (
                    table_owned_supplemental_candidate,
                    promoted_owner_shape,
                ) = (
                    _table_owned_supplemental_candidate_lineage(
                        item,
                        original_value,
                        page_index=page_index,
                        source_sha256=evidence.source_sha256,
                    )
                    if not source_space_only
                    else (False, None)
                )
                reserve_owner(
                    table_owned_supplemental_candidate=(
                        table_owned_supplemental_candidate
                    )
                )
                generic_owner_reserved = (
                    not table_owned_supplemental_candidate
                )
                reserve_candidates = candidate_reserver()
                selection = text_for_bbox(
                    evidence,
                    page_index,
                    owner_box,
                    deadline=deadline,
                )

                if promoted_owner_shape is not None and selection is not None:
                    cell_matches = _source_selection_table_cell_matches(
                        source_page=source_page,
                        selection=selection,
                        original_text=original_value,
                        owner_box=owner_box,
                        tables=admitted_table_views.get(page_index, ()),
                        deadline=deadline,
                        authority_cache=table_owned_cell_authority_cache,
                    )
                    if len(cell_matches) > 1:
                        concerns.append(
                            {
                                "status": "unresolved",
                                "reason": (
                                    "table_owned_rotated_cell_ownership_ambiguous"
                                ),
                                "page_index": page_index,
                                "owner_id": owner_id,
                                "cell_ids": [
                                    match.authority.cell_id
                                    for match in cell_matches
                                ],
                                "table_ids": [
                                    match.authority.table_id
                                    for match in cell_matches
                                ],
                            }
                        )
                        if len(concerns) > MAX_CONCERNS:
                            raise _Refusal(
                                "source_alignment_concern_limit"
                            )
                        continue
                    if len(cell_matches) == 1:
                        reserve_candidates(2)
                        checks = dict(selection.checks)
                        checks.update(
                            {
                                "authenticated_promoted_heading": True,
                                "case_preserving_glyph_multiset": True,
                                "order_insensitive_rotation_only": True,
                                "ocr_evidence_retained": True,
                                "canonical_table_authority": True,
                                "same_page_coordinate_unit": True,
                                "source_character_geometry_coverage": True,
                                "unique_table_cell_owner": True,
                                "table_cell_source_lineage": True,
                            }
                        )
                        rejected = {
                            "text": original_value,
                            "source": item.get("source"),
                            "bbox": owner_box.to_dict(),
                            "confidence": item.get("confidence"),
                            "reason": TABLE_OWNED_ROTATED_CELL_REASON,
                            "ocr_contributor": copy.deepcopy(
                                item.get("ocr_contributor")
                            ),
                            "canonical_owner": cell_matches[
                                0
                            ].canonical_owner(),
                            "promoted_owner_shape": copy.deepcopy(
                                promoted_owner_shape
                            ),
                        }
                        alignment = _alignment_selection(
                            evidence=evidence,
                            page_index=page_index,
                            owner_id=owner_id,
                            owner_type=owner_type,
                            owner_box=owner_box,
                            original_text=original_value,
                            selected_text="",
                            selection=selection,
                            method="source_safe_rotated_table_cell",
                            checks=checks,
                            rejected_ocr=rejected,
                            terminal_reason=TABLE_OWNED_ROTATED_CELL_REASON,
                        )
                        commit_text_selection(
                            item,
                            alignment,
                            table_owned_supplemental=True,
                        )
                        page_items.remove(item)
                        continue

                # A pipeline-issued supplemental OCR owner may be deleted only
                # when one validated table row completely owns its native
                # source line.  Page-wide text equality is neither ownership
                # evidence nor a tie-breaker.  Without that structural proof,
                # the older acronym path may still expand attributable source
                # text but never suppresses the owner.
                if (
                    not source_space_only
                    and selection is not None
                    and table_owned_supplemental_candidate
                    and (
                        _alignment_skeleton(original_value)
                        == _alignment_skeleton(selection.text)
                        or _single_substitution(
                            _alignment_skeleton(original_value),
                            _alignment_skeleton(selection.text),
                        )
                    )
                    and _reciprocal_overlap(
                        owner_box,
                        selection.bbox,
                    )
                    >= MIN_OCR_RECIPROCAL_OVERLAP
                ):
                    table_line = _complete_source_line_for_table_candidate(
                        source_page,
                        selection,
                        deadline=deadline,
                    )
                    if table_line is not None:
                        table_matches = _source_line_table_matches(
                            source_page=source_page,
                            complete_line=table_line,
                            owner_box=owner_box,
                            tables=admitted_table_views.get(page_index, ()),
                            deadline=deadline,
                            structural_cache=table_owned_structural_cache,
                        )
                        if len(table_matches) > 1:
                            concerns.append(
                                {
                                    "status": "unresolved",
                                    "reason": (
                                        "table_owned_supplemental_ownership_ambiguous"
                                    ),
                                    "page_index": page_index,
                                    "owner_id": owner_id,
                                    "evidence_ids": [table_line.id],
                                    "table_ids": [
                                        match.table_id
                                        for match in table_matches
                                    ],
                                }
                            )
                            if len(concerns) > MAX_CONCERNS:
                                raise _Refusal(
                                    "source_alignment_concern_limit"
                                )
                            continue
                        if len(table_matches) == 1:
                            reserve_candidates(2)
                            complete = _selection_from_line(
                                source_page,
                                table_line,
                            )
                            checks = dict(complete.checks)
                            checks.update(
                                {
                                    "native_token_overlap": True,
                                    "unique_complete_line": True,
                                    "ocr_evidence_retained": True,
                                    "canonical_table_authority": True,
                                    "same_page_coordinate_unit": True,
                                    "source_character_geometry_coverage": True,
                                    "complete_table_cell_content_coverage": True,
                                    "unique_table_row_owner": True,
                                    "table_cell_source_lineage": True,
                                }
                            )
                            rejected = {
                                "text": original_value,
                                "source": item.get("source"),
                                "bbox": owner_box.to_dict(),
                                "confidence": item.get("confidence"),
                                "reason": TABLE_OWNED_SUPPLEMENTAL_REASON,
                                "ocr_contributor": copy.deepcopy(
                                    item.get("ocr_contributor")
                                ),
                                "canonical_owner": table_matches[
                                    0
                                ].canonical_owner(),
                                **(
                                    {
                                        "promoted_owner_shape": copy.deepcopy(
                                            promoted_owner_shape
                                        )
                                    }
                                    if promoted_owner_shape is not None
                                    else {}
                                ),
                            }
                            alignment = _alignment_selection(
                                evidence=evidence,
                                page_index=page_index,
                                owner_id=owner_id,
                                owner_type=owner_type,
                                owner_box=owner_box,
                                original_text=original_value,
                                selected_text="",
                                selection=complete,
                                method="source_safe_native_token",
                                checks=checks,
                                rejected_ocr=rejected,
                                terminal_reason=(
                                    TABLE_OWNED_SUPPLEMENTAL_REASON
                                ),
                            )
                            commit_text_selection(
                                item,
                                alignment,
                                table_owned_supplemental=True,
                            )
                            page_items.remove(item)
                            continue

                    if not generic_owner_reserved:
                        reserve_owner()
                        generic_owner_reserved = True
                    complete_line = (
                        _complete_source_line_for_token(
                            source_page,
                            selection,
                            deadline=deadline,
                        )
                        if len(original_value.split()) == 1
                        else None
                    )
                    if complete_line is not None:
                        complete = _selection_from_line(
                            source_page,
                            complete_line,
                        )
                        reserve_candidates(2)
                        checks = dict(complete.checks)
                        checks.update(
                            {
                                "native_token_overlap": True,
                                "unique_complete_line": True,
                                "ocr_evidence_retained": True,
                            }
                        )
                        rejected = {
                            "text": original_value,
                            "source": item.get("source"),
                            "bbox": owner_box.to_dict(),
                            "confidence": item.get("confidence"),
                            "reason": (
                                "source_safe_native_conflict"
                                if _alignment_skeleton(original_value)
                                != _alignment_skeleton(selection.text)
                                else "strict_source_subrange"
                            ),
                        }
                        alignment = _alignment_selection(
                            evidence=evidence,
                            page_index=page_index,
                            owner_id=owner_id,
                            owner_type=owner_type,
                            owner_box=owner_box,
                            original_text=original_value,
                            selected_text=complete.text,
                            selection=complete,
                            method="source_safe_native_token",
                            checks=checks,
                            rejected_ocr=rejected,
                        )
                        commit_text_selection(item, alignment)
                        continue

                if not generic_owner_reserved:
                    reserve_owner()
                    generic_owner_reserved = True
                if selection is not None and selection.text != original_value:
                    projection = _layout_projection_text(
                        evidence,
                        selection,
                    )
                    if _selection_unique_on_page(
                        source_page,
                        original_value,
                        selection,
                        projection,
                        reserve_candidates=reserve_candidates,
                    ):
                        method = _selection_method(
                            evidence,
                            selection,
                            original_value,
                        )
                        selected_text = selection.text
                        selected_markdown: str | None = None
                        if source_space_only:
                            supported_gaps = _supported_source_space_gap_positions(
                                evidence,
                                selection,
                            )
                            selected_text = (
                                _add_source_proven_whitespace(
                                    original_value,
                                    selection.text,
                                    supported_gap_positions=supported_gaps,
                                )
                                if method is not None
                                and method[0] == "pdfium_source_space"
                                else None
                            )
                        if (
                            method is not None
                            and all(method[1].values())
                            and isinstance(selected_text, str)
                        ):
                            nested_items: list[dict[str, Any]] | None = None
                            if source_space_only:
                                original_markdown = item.get("md")
                                selected_markdown = (
                                    _add_source_proven_whitespace(
                                        original_markdown,
                                        selection.text,
                                        supported_gap_positions=supported_gaps,
                                    )
                                    if isinstance(original_markdown, str)
                                    else None
                                )
                                if selected_markdown is None:
                                    unchanged += 1
                                    continue
                                nested_repair = _source_space_nested_repairs(
                                    item,
                                    evidence=evidence,
                                    page_index=page_index,
                                    owner_box=owner_box,
                                    original_text=original_value,
                                    selected_text=selected_text,
                                    outer_selection=selection,
                                    reserve_candidates=reserve_candidates,
                                    deadline=deadline,
                                )
                                if nested_repair is None:
                                    unchanged += 1
                                    continue
                                nested_items, _nested_indexes = nested_repair
                                method[1].update(
                                    {
                                        "same_page_coordinate_unit": True,
                                        "all_missing_spaces_encoded_u0020": True,
                                        "additive_whitespace_only": True,
                                        "prior_whitespace_preserved": True,
                                        "nested_contributor_closure": True,
                                    }
                                )
                            alignment = _alignment_selection(
                                evidence=evidence,
                                page_index=page_index,
                                owner_id=owner_id,
                                owner_type=owner_type,
                                owner_box=owner_box,
                                original_text=original_value,
                                selected_text=selected_text,
                                selection=selection,
                                method=method[0],
                                checks=method[1],
                            )
                            commit_text_selection(
                                item,
                                alignment,
                                nested_items=nested_items,
                                selected_markdown=selected_markdown,
                            )
                            continue

                partial = _supported_line_space_repair(
                    original_value,
                    owner_box,
                    source_page,
                    reserve_candidates=reserve_candidates,
                    deadline=deadline,
                )
                if partial is not None:
                    selected_text, partial_selection = partial
                    if source_space_only:
                        supported_gaps = _supported_source_space_gap_positions(
                            evidence,
                            partial_selection,
                        )
                        selected_text = _add_source_proven_whitespace(
                            original_value,
                            selected_text,
                            supported_gap_positions=supported_gaps,
                        )
                        if selected_text is None:
                            unchanged += 1
                            continue
                        original_markdown = item.get("md")
                        selected_markdown = (
                            _add_source_proven_whitespace(
                                original_markdown,
                                selected_text,
                                supported_gap_positions=supported_gaps,
                            )
                            if isinstance(original_markdown, str)
                            else None
                        )
                        if selected_markdown is None:
                            unchanged += 1
                            continue
                        nested_repair = _source_space_nested_repairs(
                            item,
                            evidence=evidence,
                            page_index=page_index,
                            owner_box=owner_box,
                            original_text=original_value,
                            selected_text=selected_text,
                            outer_selection=partial_selection,
                            reserve_candidates=reserve_candidates,
                            deadline=deadline,
                        )
                        if nested_repair is None:
                            unchanged += 1
                            continue
                        nested_items, _nested_indexes = nested_repair
                    else:
                        nested_items = None
                        selected_markdown = None
                    checks = dict(partial_selection.checks)
                    checks.update(
                        {
                            "encoded_u0020": True,
                            "space_geometry": True,
                            "unique_owner_alignment": True,
                        }
                    )
                    if source_space_only:
                        checks.update(
                            {
                                "same_page_coordinate_unit": True,
                                "all_missing_spaces_encoded_u0020": True,
                                "additive_whitespace_only": True,
                                "prior_whitespace_preserved": True,
                                "nested_contributor_closure": True,
                            }
                        )
                    alignment = _alignment_selection(
                        evidence=evidence,
                        page_index=page_index,
                        owner_id=owner_id,
                        owner_type=owner_type,
                        owner_box=owner_box,
                        original_text=original_value,
                        selected_text=selected_text,
                        selection=partial_selection,
                        method="pdfium_source_space",
                        checks=checks,
                    )
                    commit_text_selection(
                        item,
                        alignment,
                        nested_items=nested_items,
                        selected_markdown=selected_markdown,
                    )
                    continue
                unchanged += 1

        # Retain bounded, generic unresolved evidence for a lexical source
        # line immediately adjacent to a represented table.  This never
        # inserts the line or dispatches on its text.
        pages_by_index = {
            int(page.get("page_index") or index): page
            for index, page in enumerate(working, start=1)
        }
        for diagnostic in evidence.diagnostics:
            if diagnostic.get("kind") != "lexical_subline":
                continue
            try:
                diagnostic_page_index = int(diagnostic["page_index"])
                diagnostic_box = _mapping_bbox(diagnostic.get("bbox"))
                diagnostic_text = str(diagnostic["text"])
                diagnostic_id = str(diagnostic["id"])
            except (KeyError, TypeError, ValueError):
                continue
            diagnostic_page = pages_by_index.get(diagnostic_page_index)
            if (
                diagnostic_page is None
                or diagnostic_box is None
                or diagnostic_text in _page_canonical_text(diagnostic_page)
            ):
                continue
            near_table = False
            for item in diagnostic_page.get("items") or []:
                if (
                    not isinstance(item, Mapping)
                    or item.get("type") != "table"
                ):
                    continue
                table_box = _mapping_bbox(item.get("bbox"))
                if table_box is None:
                    continue
                horizontal_overlap = max(
                    min(
                        diagnostic_box.x + diagnostic_box.width,
                        table_box.x + table_box.width,
                    )
                    - max(diagnostic_box.x, table_box.x),
                    0.0,
                )
                if horizontal_overlap <= 0:
                    continue
                vertical_gap = max(
                    diagnostic_box.y
                    - (table_box.y + table_box.height),
                    table_box.y
                    - (diagnostic_box.y + diagnostic_box.height),
                    0.0,
                )
                if vertical_gap <= 64.0:
                    near_table = True
                    break
            if not near_table:
                continue
            concerns.append(
                {
                    "status": "unresolved",
                    "target_text": diagnostic_text,
                    "page_index": diagnostic_page_index,
                    "source_bbox": diagnostic_box.to_dict(),
                    "evidence_ids": [diagnostic_id],
                    "source_line_ids": list(
                        diagnostic.get("source_line_ids") or []
                    ),
                    "source_character_ids": list(
                        diagnostic.get("source_character_ids") or []
                    ),
                    "reason": "unrepresented_source_line_near_table",
                }
            )
            if len(concerns) > MAX_CONCERNS:
                raise _Refusal("source_alignment_concern_limit")

        if generic_selection_count > MAX_SELECTIONS:
            raise _Refusal("source_alignment_selection_limit")
        if (
            table_owned_supplemental_selection_count
            > MAX_TABLE_OWNED_SUPPLEMENTAL_SELECTIONS
        ):
            raise _Refusal(
                "source_alignment_table_owned_supplemental_selection_limit"
            )
        if (
            len(selections)
            != generic_selection_count
            + table_owned_supplemental_selection_count
            + len(vector_selections)
            or len(selections) > MAX_TOTAL_ALIGNMENT_SELECTIONS
        ):
            raise _Refusal("source_alignment_total_selection_limit")
        if (
            vector_owner_count > MAX_SELECTED_VECTOR_OWNERS
            or len(vector_selections) > MAX_SELECTED_VECTOR_SELECTIONS
            or vector_group_count > MAX_SELECTED_VECTOR_GROUPS
            or considered
            + table_owned_supplemental_considered
            + vector_owner_count
            > MAX_TOTAL_ALIGNMENT_OWNERS
        ):
            raise _Refusal("source_alignment_selected_vector_resource_limit")
        if len(concerns) > MAX_CONCERNS:
            raise _Refusal("source_alignment_concern_limit")
        unresolved = len(concerns)
        considered_count = len(selections) + unchanged + unresolved
        status = "selected" if selections else "unchanged"
        summary_for_bound = SourceAlignmentSummary(
            schema_version=SOURCE_TEXT_ALIGNMENT_SCHEMA_VERSION,
            policy_id=SOURCE_TEXT_ALIGNMENT_POLICY_ID,
            source_sha256=evidence.source_sha256,
            status=status,
            considered_count=considered_count,
            selected_count=len(selections),
            unchanged_count=unchanged,
            unresolved_count=unresolved,
            selections=tuple(selections),
            concerns=tuple(concerns),
            elapsed_ms=1999.999999,
        )
        _bounded_json_size(
            summary_for_bound,
            max_bytes=MAX_REPORT_BYTES,
            deadline=deadline,
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 6)
        if time.perf_counter() > deadline:
            raise _Refusal("source_alignment_deadline")
        pages[:] = working
        return replace(summary_for_bound, elapsed_ms=elapsed_ms)
    except _Refusal as exc:
        return _refused_summary(
            evidence.source_sha256,
            exc.code,
            started,
        )
    except Exception:
        return _refused_summary(
            evidence.source_sha256,
            "source_alignment_unexpected_failure",
            started,
        )
