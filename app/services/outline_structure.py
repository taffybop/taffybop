"""Bounded source-grounded outline semantics for P03-US07.

The public v1 items remain authoritative.  This module extracts an immutable
native-PDF marker report, projects a strict additive IR graph and anchor-only
public sidecar, and supplies the validated canonical replacement used by the
presentation layer.  Every entry point is local-only and fails closed.
"""

from __future__ import annotations

import hashlib
import html
import io
import json
import math
import re
import time
from collections import Counter
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from typing import Any, Literal
from urllib.parse import unquote

import pdfplumber
import pypdfium2 as pdfium
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.ir import (
    ConfidenceRecord,
    DocumentIR,
    ElementPresentationDirective,
    ElementRecord,
    EvidenceMethod,
    EvidenceRecord,
    FormGroupSemanticDescriptor,
    IRBoundingBox,
    IRConcern,
    OutlineGroupSemanticDescriptor,
    OutlineItemSemanticDescriptor,
    RelationshipRecord,
    RelationshipType,
)


POLICY_ID = "p03-outline-structure-v1"
REPORT_VERSION = "1.0"

MAX_SOURCE_CHARACTERS_PER_PAGE = 500_000
MAX_SOURCE_CHARACTERS_PER_DOCUMENT = 2_000_000
MAX_SOURCE_WORDS_PER_PAGE = 100_000
MAX_SOURCE_WORDS_PER_DOCUMENT = 500_000
MAX_MARKER_CANDIDATES_PER_PAGE = 2_048
MAX_MARKER_CANDIDATES_PER_DOCUMENT = 10_000
MAX_DEPTH = 8
MAX_MARKER_BYTES = 64
MAX_ITEM_TEXT_BYTES = 16 * 1024
MAX_NODES_PER_GROUP = 256
MAX_GROUPS_PER_PAGE = 256
MAX_GROUPS_PER_DOCUMENT = 2_048
MAX_NODES_PER_PAGE = 4_096
MAX_NODES_PER_DOCUMENT = 32_768
MAX_INTERSTITIALS_PER_GROUP = 64
MAX_RELATIONSHIPS_PER_PAGE = 16_384
MAX_RELATIONSHIPS_PER_DOCUMENT = 65_536
MAX_COMPARISONS_PER_PAGE = 65_536
MAX_PUBLIC_GROUP_BYTES = 512 * 1024
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_CONCERNS_PER_PAGE = 64
MAX_CONCERNS_PER_DOCUMENT = 256
SOURCE_EXTRACTION_DEADLINE_SECONDS = 2.0
PROJECTION_PAGE_DEADLINE_SECONDS = 0.25
PROJECTION_DOCUMENT_DEADLINE_SECONDS = 2.0
INDENT_TOLERANCE_POINTS = 2.0
MINIMUM_INDENT_STEP_POINTS = 6.0

_ALLOWED_CONCERNS = frozenset(
    {
        "outline_source_evidence_unavailable",
        "outline_source_limit",
        "outline_candidate_limit",
        "outline_geometry_ambiguous",
        "outline_marker_ambiguous",
        "outline_sequence_invalid",
        "outline_interstitial_ambiguous",
        "outline_relationship_limit",
        "outline_canonical_custody_invalid",
        "outline_projection_failed_closed",
        "outline_concerns_truncated",
    }
)
_PUBLIC_OUTLINE_KEYS = frozenset(
    {
        "layout_outline_structure_projected",
        "outline_policy",
        "outline_group",
        "outline_items",
        "outline_continuations",
    }
)
_BULLET_MARKERS = frozenset({"•", "◦", "-", "*", "▪", "‣"})
_DECIMAL_MARKER = re.compile(r"^([1-9][0-9]{0,3})[.)]$")
_ALPHA_MARKER = re.compile(r"^(?:([a-z])[.)]|\(([a-z])\))$")
_TOP_LEVEL_OUTLINE_TYPES = frozenset({"text", "paragraph", "clause"})


@dataclass(frozen=True, slots=True)
class OutlineSourceBBox:
    x: float
    y: float
    width: float
    height: float
    unit: Literal["pt"] = "pt"


@dataclass(frozen=True, slots=True)
class OutlineSourceObject:
    reader: Literal["pdfplumber"]
    page_index: int
    word_index: int


@dataclass(frozen=True, slots=True)
class OutlineSourceMarker:
    raw_marker: str
    marker_style: Literal["bullet", "decimal", "lower_alpha"]
    ordinal: int
    bbox: OutlineSourceBBox
    source_object: OutlineSourceObject


@dataclass(frozen=True, slots=True)
class OutlineSourcePage:
    page_index: int
    page_width: float
    page_height: float
    unit: Literal["pt"]
    coordinate_system_id: str
    source_character_count: int
    source_word_count: int
    markers: tuple[OutlineSourceMarker, ...]
    concern_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OutlineSourceCounts:
    pages: int
    source_characters: int
    source_words: int
    marker_candidates: int
    concerns: int


@dataclass(frozen=True, slots=True)
class OutlineEvidenceReport:
    report_version: Literal["1.0"]
    policy_id: Literal["p03-outline-structure-v1"]
    source_sha256: str
    status: Literal["available", "unavailable", "refused"]
    pages: tuple[OutlineSourcePage, ...]
    counts: OutlineSourceCounts
    concern_codes: tuple[str, ...]
    extraction_ms: float


@dataclass(frozen=True, slots=True)
class OutlineGroupRendering:
    group_element_id: str
    anchor_element_id: str
    predecessor_primary_ids: tuple[str, ...]
    contributor_element_ids: tuple[str, ...]
    relationship_ids: tuple[str, ...]
    markdown: str
    text: str


class _StrictPublicModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _validate_public_path(value: list[str | int]) -> list[str | int]:
    if (
        len(value) not in {4, 6}
        or value[0] != "pages"
        or isinstance(value[1], bool)
        or not isinstance(value[1], int)
        or value[1] < 0
        or value[2] != "items"
        or isinstance(value[3], bool)
        or not isinstance(value[3], int)
        or value[3] < 0
        or (
            len(value) == 6
            and (
                value[4] != "items"
                or isinstance(value[5], bool)
                or not isinstance(value[5], int)
                or value[5] < 0
            )
        )
    ):
        raise ValueError("outline public path differs")
    return value


def _validate_nonempty_unique_ids(values: list[str]) -> list[str]:
    if any(not value or len(value.encode("utf-8")) > 256 for value in values) or len(
        values
    ) != len(set(values)):
        raise ValueError("outline public ID list differs")
    return values


def _valid_public_id(value: str) -> bool:
    return bool(value) and len(value.encode("utf-8")) <= 256


def _validate_concern_codes(values: list[str]) -> list[str]:
    if len(values) != len(set(values)) or any(
        value not in _ALLOWED_CONCERNS for value in values
    ):
        raise ValueError("outline public concern codes differ")
    return values


class PublicBBox(_StrictPublicModel):
    x: float
    y: float
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    unit: Literal["pt"]

    @model_validator(mode="after")
    def validate_finite(self) -> "PublicBBox":
        if not all(
            math.isfinite(value) for value in (self.x, self.y, self.width, self.height)
        ):
            raise ValueError("outline bbox values must be finite")
        return self


class PublicConfidence(_StrictPublicModel):
    scope: Literal["evidence"]
    score: None
    unavailable_reason: Literal["not_calibrated", "source_state_unavailable"]


class PublicSourceObject(_StrictPublicModel):
    reader: Literal["pdfplumber"]
    page_index: int = Field(ge=1, strict=True)
    word_index: int = Field(ge=0, strict=True)


class PublicOutlineGroup(_StrictPublicModel):
    id: str
    element_id: str
    page_id: str
    sequence_kind: Literal["unordered", "ordered", "legal"]
    marker_style: Literal["bullet", "decimal", "lower_alpha"]
    anchor_public_item_id: str
    anchor_element_id: str
    anchor_public_path: list[str | int]
    group_bbox: PublicBBox
    member_item_ids: list[str] = Field(min_length=2, max_length=MAX_NODES_PER_GROUP)
    member_element_ids: list[str] = Field(
        min_length=2,
        max_length=MAX_NODES_PER_GROUP,
    )
    continuation_ids: list[str] = Field(max_length=MAX_INTERSTITIALS_PER_GROUP)
    continuation_element_ids: list[str] = Field(max_length=MAX_INTERSTITIALS_PER_GROUP)
    relationship_ids: list[str] = Field(max_length=MAX_RELATIONSHIPS_PER_PAGE)
    relationship_cardinality: dict[str, int]
    canonical_block_id: str
    canonical_primary_element_id: str
    canonical_contributor_element_ids: list[str] = Field(
        max_length=MAX_NODES_PER_DOCUMENT
    )
    canonical_relationship_ids: list[str] = Field(
        max_length=MAX_RELATIONSHIPS_PER_DOCUMENT
    )
    canonical_markdown_sha256: str
    canonical_text_sha256: str
    source_method: Literal["native"]
    confidence: PublicConfidence
    concern_codes: list[str] = Field(max_length=MAX_CONCERNS_PER_PAGE)

    _validate_anchor_path = field_validator("anchor_public_path")(_validate_public_path)
    _validate_member_item_ids = field_validator("member_item_ids")(
        _validate_nonempty_unique_ids
    )
    _validate_member_element_ids = field_validator("member_element_ids")(
        _validate_nonempty_unique_ids
    )
    _validate_continuation_ids = field_validator("continuation_ids")(
        _validate_nonempty_unique_ids
    )
    _validate_continuation_element_ids = field_validator("continuation_element_ids")(
        _validate_nonempty_unique_ids
    )
    _validate_relationship_ids = field_validator("relationship_ids")(
        _validate_nonempty_unique_ids
    )
    _validate_canonical_contributors = field_validator(
        "canonical_contributor_element_ids"
    )(_validate_nonempty_unique_ids)
    _validate_canonical_relationships = field_validator("canonical_relationship_ids")(
        _validate_nonempty_unique_ids
    )
    _validate_concerns = field_validator("concern_codes")(_validate_concern_codes)

    @model_validator(mode="after")
    def validate_closed_group(self) -> "PublicOutlineGroup":
        identifiers = (
            self.id,
            self.element_id,
            self.page_id,
            self.anchor_public_item_id,
            self.anchor_element_id,
            self.canonical_block_id,
            self.canonical_primary_element_id,
        )
        if any(not _valid_public_id(value) for value in identifiers):
            raise ValueError("outline public group ID differs")
        if len(self.anchor_public_path) != 4:
            raise ValueError("outline group anchor path differs")
        if (self.sequence_kind, self.marker_style) not in {
            ("unordered", "bullet"),
            ("ordered", "decimal"),
            ("legal", "lower_alpha"),
        }:
            raise ValueError("outline sequence kind/marker style differs")
        if set(self.relationship_cardinality) != {
            "contains",
            "outline_parent_of",
            "outline_next",
            "outline_continuation_of",
        } or any(
            isinstance(value, bool) or value < 0
            for value in self.relationship_cardinality.values()
        ):
            raise ValueError("outline relationship cardinality differs")
        if (
            re.fullmatch(r"[0-9a-f]{64}", self.canonical_markdown_sha256) is None
            or re.fullmatch(r"[0-9a-f]{64}", self.canonical_text_sha256) is None
        ):
            raise ValueError("outline canonical digest differs")
        return self


class PublicOutlineItem(_StrictPublicModel):
    id: str
    element_id: str
    source_public_item_id: str
    source_public_path: list[str | int]
    source_bbox_id: str
    source_evidence_ids: list[str]
    source_object: PublicSourceObject
    sequence_kind: Literal["unordered", "ordered", "legal"]
    marker_style: Literal["bullet", "decimal", "lower_alpha"]
    raw_marker: str
    marker_bbox: PublicBBox
    marker_ownership: Literal["separate", "value_prefix"]
    marker_separator: str
    body_text: str
    predecessor_value_sha256: str
    level: int = Field(ge=0, lt=MAX_DEPTH, strict=True)
    ordinal: int = Field(ge=1, strict=True)
    parent_id: str | None
    marker_bbox_id: str
    marker_evidence_id: str
    source_method: Literal["native"]
    confidence: PublicConfidence
    concern_codes: list[str] = Field(max_length=MAX_CONCERNS_PER_PAGE)
    relationship_ids: list[str] = Field(max_length=323)
    continuation_ids: list[str] = Field(max_length=MAX_INTERSTITIALS_PER_GROUP)

    _validate_source_path = field_validator("source_public_path")(_validate_public_path)
    _validate_source_evidence_ids = field_validator("source_evidence_ids")(
        _validate_nonempty_unique_ids
    )
    _validate_relationship_ids = field_validator("relationship_ids")(
        _validate_nonempty_unique_ids
    )
    _validate_continuation_ids = field_validator("continuation_ids")(
        _validate_nonempty_unique_ids
    )
    _validate_concerns = field_validator("concern_codes")(_validate_concern_codes)

    @model_validator(mode="after")
    def validate_marker_fields(self) -> "PublicOutlineItem":
        identifiers = (
            self.id,
            self.element_id,
            self.source_public_item_id,
            self.source_bbox_id,
            self.marker_bbox_id,
            self.marker_evidence_id,
        )
        if any(not _valid_public_id(value) for value in identifiers):
            raise ValueError("outline public item ID differs")
        if self.parent_id is not None and not _valid_public_id(self.parent_id):
            raise ValueError("outline public parent ID differs")
        if (
            not self.source_evidence_ids
            or self.marker_evidence_id in self.source_evidence_ids
        ):
            raise ValueError("outline marker/source evidence custody overlaps")
        if re.fullmatch(r"[0-9a-f]{64}", self.predecessor_value_sha256) is None:
            raise ValueError("outline predecessor value digest differs")
        if (
            not self.raw_marker
            or len(self.raw_marker.encode("utf-8")) > MAX_MARKER_BYTES
        ):
            raise ValueError("outline marker exceeds its byte limit")
        if (
            not self.body_text
            or len(self.body_text.encode("utf-8")) > MAX_ITEM_TEXT_BYTES
        ):
            raise ValueError("outline item body exceeds its byte limit")
        if self.marker_ownership == "separate":
            if self.marker_separator != "":
                raise ValueError("separate marker separator differs")
        elif self.marker_separator != " ":
            raise ValueError("value-prefix marker separator differs")
        return self


class PublicOutlineContinuation(_StrictPublicModel):
    id: str
    element_id: str
    source_public_item_id: str
    source_public_path: list[str | int]
    source_type: Literal["table"]
    bbox_id: str
    bbox: PublicBBox
    source_evidence_ids: list[str]
    target_node_id: str
    source_method: Literal["native"]
    confidence: PublicConfidence
    concern_codes: list[str] = Field(max_length=MAX_CONCERNS_PER_PAGE)
    relationship_ids: list[str] = Field(min_length=1, max_length=1)

    _validate_source_path = field_validator("source_public_path")(_validate_public_path)
    _validate_source_evidence_ids = field_validator("source_evidence_ids")(
        _validate_nonempty_unique_ids
    )
    _validate_relationship_ids = field_validator("relationship_ids")(
        _validate_nonempty_unique_ids
    )
    _validate_concerns = field_validator("concern_codes")(_validate_concern_codes)

    @model_validator(mode="after")
    def validate_closed_continuation(self) -> "PublicOutlineContinuation":
        identifiers = (
            self.id,
            self.element_id,
            self.source_public_item_id,
            self.bbox_id,
            self.target_node_id,
        )
        if any(not _valid_public_id(value) for value in identifiers):
            raise ValueError("outline continuation ID differs")
        if len(self.source_public_path) != 4 or not self.source_evidence_ids:
            raise ValueError("outline continuation source binding differs")
        return self


@dataclass(frozen=True, slots=True)
class _Target:
    element_id: str
    anchor_element_id: str
    public_item_id: str
    public_path: tuple[str | int, ...]
    bbox_id: str
    evidence_ids: tuple[str, ...]
    bbox: tuple[float, float, float, float]
    value: str
    nested: bool
    page_index: int
    reading_rank: int


@dataclass(frozen=True, slots=True)
class _MatchedNode:
    target: _Target
    marker: OutlineSourceMarker
    marker_ownership: Literal["separate", "value_prefix"]
    marker_separator: str
    body_text: str


@dataclass(frozen=True, slots=True)
class _NodePlan:
    matched: _MatchedNode
    item_id: str
    marker_bbox_id: str
    marker_evidence_id: str
    level: int
    ordinal: int
    parent_element_id: str | None
    parent_item_id: str | None


@dataclass(frozen=True, slots=True)
class _ContinuationPlan:
    id: str
    element_id: str
    public_item_id: str
    public_path: tuple[str | int, ...]
    bbox_id: str
    bbox: tuple[float, float, float, float]
    evidence_ids: tuple[str, ...]
    target_element_id: str
    target_item_id: str


@dataclass(frozen=True, slots=True)
class _RelationshipPlan:
    id: str
    type: RelationshipType
    source_id: str
    target_id: str
    evidence_ids: tuple[str, ...]
    metadata: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class _CanonicalClosure:
    block_id: str
    page_id: str
    primary_element_id: str
    primary_element_type: str
    predecessor_primary_ids: tuple[str, ...]
    contributing_element_ids: tuple[str, ...]
    predecessor_relationship_ids: tuple[str, ...]
    relationship_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _GroupPlan:
    id: str
    element_id: str
    bbox_id: str
    evidence_id: str
    page_id: str
    page_index: int
    coordinate_system_id: str
    sequence_kind: Literal["unordered", "ordered", "legal"]
    marker_style: Literal["bullet", "decimal", "lower_alpha"]
    anchor_element_id: str
    anchor_public_item_id: str
    anchor_public_path: tuple[str | int, ...]
    nodes: tuple[_NodePlan, ...]
    continuations: tuple[_ContinuationPlan, ...]
    relationships: tuple[_RelationshipPlan, ...]
    bbox: tuple[float, float, float, float]
    concern_codes: tuple[str, ...]


class _SourceLimitError(ValueError):
    pass


class _PageSourceError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _PageProjectionError(ValueError):
    pass


class _DocumentProjectionError(ValueError):
    pass


def _strict_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _stable_id(prefix: str, *parts: object) -> str:
    return f"{prefix}-{hashlib.sha256(_strict_json_bytes(parts)).hexdigest()[:20]}"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _source_bbox(value: Mapping[str, Any]) -> OutlineSourceBBox:
    x = round(float(value["x0"]), 3)
    y = round(float(value["top"]), 3)
    width = round(float(value["x1"]) - float(value["x0"]), 3)
    height = round(float(value["bottom"]) - float(value["top"]), 3)
    if not all(math.isfinite(item) for item in (x, y, width, height)) or (
        x < 0 or y < 0 or width <= 0 or height <= 0
    ):
        raise _SourceLimitError("outline source marker bbox is invalid")
    return OutlineSourceBBox(x=x, y=y, width=width, height=height)


def _marker_kind(value: str) -> tuple[str, int] | None:
    if value in _BULLET_MARKERS:
        return "bullet", 1
    decimal = _DECIMAL_MARKER.fullmatch(value)
    if decimal is not None:
        return "decimal", int(decimal.group(1))
    alpha = _ALPHA_MARKER.fullmatch(value)
    if alpha is not None:
        letter = alpha.group(1) or alpha.group(2)
        assert letter is not None
        return "lower_alpha", ord(letter) - ord("a") + 1
    return None


def _marker_family(value: str, style: str) -> str:
    if style == "bullet":
        return "bullet"
    if value.startswith("(") and value.endswith(")"):
        return "parenthesized"
    if value.endswith("."):
        return "period"
    if value.endswith(")"):
        return "right_parenthesis"
    return "unsupported"


def _same_visual_line(first: Mapping[str, Any], second: Mapping[str, Any]) -> bool:
    first_top = float(first["top"])
    first_bottom = float(first["bottom"])
    second_top = float(second["top"])
    second_bottom = float(second["bottom"])
    overlap = min(first_bottom, second_bottom) - max(first_top, second_top)
    return overlap >= 0.5 * min(
        first_bottom - first_top,
        second_bottom - second_top,
    )


def _coordinate_system_id(source_sha256: str, page_index: int) -> str:
    document_id = _stable_id("doc", source_sha256)
    page_id = _stable_id("page", document_id, page_index)
    return _stable_id(
        "coords",
        page_id,
        "pt",
        (1.0, 0.0, 0.0, 1.0, 0.0, 0.0),
        None,
    )


def _assign_bullet_ordinals(
    candidates: Sequence[tuple[int, Mapping[str, Any], str, int]],
) -> list[tuple[int, Mapping[str, Any], str, int]]:
    """Infer bullet sibling ordinals from bounded native geometry."""

    bullet_x_values = sorted(
        float(word["x0"])
        for _word_index, word, style, _ordinal in candidates
        if style == "bullet"
    )
    centers: list[float] = []
    for x_value in bullet_x_values:
        if not any(
            abs(center - x_value) <= INDENT_TOLERANCE_POINTS for center in centers
        ):
            centers.append(x_value)

    result: list[tuple[int, Mapping[str, Any], str, int]] = []
    counters = [0 for _value in centers]
    previous_bullet: Mapping[str, Any] | None = None
    for word_index, word, style, ordinal in candidates:
        if style != "bullet":
            previous_bullet = None
            result.append((word_index, word, style, ordinal))
            continue
        x_value = float(word["x0"])
        level = next(
            (
                index
                for index, center in enumerate(centers)
                if abs(center - x_value) <= INDENT_TOLERANCE_POINTS
            ),
            0,
        )
        if previous_bullet is not None and level == 0:
            vertical_gap = float(word["top"]) - float(previous_bullet["top"])
            line_height = max(
                float(word["bottom"]) - float(word["top"]),
                float(previous_bullet["bottom"]) - float(previous_bullet["top"]),
            )
            if vertical_gap > line_height * 2.0:
                counters = [0 for _value in centers]
        counters[level] += 1
        for deeper_level in range(level + 1, len(counters)):
            counters[deeper_level] = 0
        result.append((word_index, word, style, counters[level]))
        previous_bullet = word
    return result


def _report_payload(report: OutlineEvidenceReport) -> dict[str, Any]:
    return asdict(report)


def _validate_source_report(
    report: OutlineEvidenceReport,
    *,
    expected_source_sha256: str,
) -> None:
    """Validate the complete closed source report before projection."""

    if type(report) is not OutlineEvidenceReport:
        raise _DocumentProjectionError("outline source report type differs")
    if (
        report.report_version != REPORT_VERSION
        or report.policy_id != POLICY_ID
        or report.source_sha256 != expected_source_sha256
        or re.fullmatch(r"[0-9a-f]{64}", report.source_sha256) is None
        or report.status not in {"available", "unavailable", "refused"}
        or type(report.pages) is not tuple
        or type(report.counts) is not OutlineSourceCounts
        or type(report.concern_codes) is not tuple
        or isinstance(report.extraction_ms, bool)
        or not isinstance(report.extraction_ms, (int, float))
        or not math.isfinite(report.extraction_ms)
        or report.extraction_ms < 0
    ):
        raise _DocumentProjectionError("outline source report header differs")
    if (
        len(report.concern_codes) > MAX_CONCERNS_PER_DOCUMENT
        or len(report.concern_codes) != len(set(report.concern_codes))
        or any(value not in _ALLOWED_CONCERNS for value in report.concern_codes)
    ):
        raise _DocumentProjectionError("outline report concerns differ")

    page_indexes: list[int] = []
    source_characters = 0
    source_words = 0
    marker_candidates = 0
    page_concerns = 0
    for page in report.pages:
        if type(page) is not OutlineSourcePage:
            raise _DocumentProjectionError("outline source page type differs")
        if (
            type(page.page_index) is not int
            or page.page_index < 1
            or page.unit != "pt"
            or isinstance(page.page_width, bool)
            or not isinstance(page.page_width, (int, float))
            or isinstance(page.page_height, bool)
            or not isinstance(page.page_height, (int, float))
            or not math.isfinite(page.page_width)
            or not math.isfinite(page.page_height)
            or page.page_width <= 0
            or page.page_height <= 0
            or page.coordinate_system_id
            != _coordinate_system_id(report.source_sha256, page.page_index)
            or type(page.source_character_count) is not int
            or not 0 <= page.source_character_count <= MAX_SOURCE_CHARACTERS_PER_PAGE
            or type(page.source_word_count) is not int
            or not 0 <= page.source_word_count <= MAX_SOURCE_WORDS_PER_PAGE
            or type(page.markers) is not tuple
            or len(page.markers) > MAX_MARKER_CANDIDATES_PER_PAGE
            or type(page.concern_codes) is not tuple
            or len(page.concern_codes) > MAX_CONCERNS_PER_PAGE
            or len(page.concern_codes) != len(set(page.concern_codes))
            or any(value not in _ALLOWED_CONCERNS for value in page.concern_codes)
        ):
            raise _DocumentProjectionError("outline source page differs")
        if page.concern_codes and (
            page.concern_codes
            not in {
                ("outline_source_limit",),
                ("outline_geometry_ambiguous",),
            }
            or page.markers
        ):
            raise _DocumentProjectionError(
                "outline page refusal representation differs"
            )
        page_indexes.append(page.page_index)
        source_characters += page.source_character_count
        source_words += page.source_word_count
        marker_candidates += len(page.markers)
        page_concerns += len(page.concern_codes)
        marker_keys: list[tuple[float, float, bytes, int]] = []
        source_objects: set[tuple[int, int]] = set()
        for marker in page.markers:
            if (
                type(marker) is not OutlineSourceMarker
                or type(marker.source_object) is not OutlineSourceObject
                or type(marker.bbox) is not OutlineSourceBBox
                or marker.source_object.reader != "pdfplumber"
                or marker.source_object.page_index != page.page_index
                or type(marker.source_object.word_index) is not int
                or not 0 <= marker.source_object.word_index < page.source_word_count
                or marker.marker_style not in {"bullet", "decimal", "lower_alpha"}
                or type(marker.ordinal) is not int
                or marker.ordinal < 1
                or not marker.raw_marker
                or len(marker.raw_marker.encode("utf-8")) > MAX_MARKER_BYTES
                or marker.bbox.unit != "pt"
            ):
                raise _DocumentProjectionError("outline source marker differs")
            parsed_marker = _marker_kind(marker.raw_marker)
            if parsed_marker is None or parsed_marker[0] != marker.marker_style:
                raise _DocumentProjectionError("outline marker syntax differs")
            if marker.marker_style != "bullet" and (parsed_marker[1] != marker.ordinal):
                raise _DocumentProjectionError("outline marker ordinal differs")
            box_values = (
                marker.bbox.x,
                marker.bbox.y,
                marker.bbox.width,
                marker.bbox.height,
            )
            if (
                any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    for value in box_values
                )
                or marker.bbox.x < 0
                or marker.bbox.y < 0
                or marker.bbox.width <= 0
                or marker.bbox.height <= 0
                or marker.bbox.x + marker.bbox.width > page.page_width + 0.001
                or marker.bbox.y + marker.bbox.height > page.page_height + 0.001
            ):
                raise _DocumentProjectionError("outline marker bbox differs")
            source_key = (
                marker.source_object.page_index,
                marker.source_object.word_index,
            )
            if source_key in source_objects:
                raise _DocumentProjectionError("outline source marker repeats")
            source_objects.add(source_key)
            marker_keys.append(
                (
                    marker.bbox.y,
                    marker.bbox.x,
                    marker.raw_marker.encode("utf-8"),
                    marker.source_object.word_index,
                )
            )
        if marker_keys != sorted(marker_keys):
            raise _DocumentProjectionError("outline source marker order differs")

    if page_indexes != sorted(set(page_indexes)):
        raise _DocumentProjectionError("outline source page order differs")
    counts = report.counts
    count_values = (
        counts.pages,
        counts.source_characters,
        counts.source_words,
        counts.marker_candidates,
        counts.concerns,
    )
    if any(type(value) is not int or value < 0 for value in count_values) or (
        counts.pages != len(report.pages)
        or counts.source_characters != source_characters
        or counts.source_words != source_words
        or counts.marker_candidates != marker_candidates
        or counts.concerns != page_concerns + len(report.concern_codes)
        or counts.source_characters > MAX_SOURCE_CHARACTERS_PER_DOCUMENT
        or counts.source_words > MAX_SOURCE_WORDS_PER_DOCUMENT
        or counts.marker_candidates > MAX_MARKER_CANDIDATES_PER_DOCUMENT
    ):
        raise _DocumentProjectionError("outline source counts differ")
    if report.status == "available":
        if report.concern_codes:
            raise _DocumentProjectionError(
                "available outline report has document concerns"
            )
    elif (
        report.pages
        or counts.pages
        or counts.source_characters
        or counts.source_words
        or counts.marker_candidates
        or counts.concerns != len(report.concern_codes)
        or len(report.concern_codes) != 1
        or (
            report.status == "refused"
            and report.concern_codes != ("outline_source_limit",)
        )
        or (
            report.status == "unavailable"
            and report.concern_codes != ("outline_source_evidence_unavailable",)
        )
    ):
        raise _DocumentProjectionError("outline source refusal differs")
    if len(_strict_json_bytes(_report_payload(report))) > MAX_REPORT_BYTES:
        raise _DocumentProjectionError("outline source report byte limit exceeded")


def _refused_report(
    *,
    source_sha256: str,
    started_at: float,
    code: Literal["outline_source_evidence_unavailable", "outline_source_limit"],
) -> OutlineEvidenceReport:
    elapsed_ms = round(max(time.perf_counter() - started_at, 0.0) * 1000.0, 3)
    return OutlineEvidenceReport(
        report_version=REPORT_VERSION,
        policy_id=POLICY_ID,
        source_sha256=source_sha256,
        status="refused" if code == "outline_source_limit" else "unavailable",
        pages=(),
        counts=OutlineSourceCounts(0, 0, 0, 0, 1),
        concern_codes=(code,),
        extraction_ms=elapsed_ms,
    )


def extract_outline_evidence(
    pdf_bytes: bytes,
    *,
    max_pages: int = 100,
) -> OutlineEvidenceReport:
    """Extract bounded native marker evidence from every scanned PDF page.

    The scan charges all pages against document counters.  The immutable report
    retains only pages carrying accepted line-start marker candidates, matching
    the reviewed oracle and avoiding unrelated-page payload growth.
    """

    if not isinstance(pdf_bytes, bytes) or not pdf_bytes:
        raise ValueError("outline evidence requires nonempty PDF bytes")
    if isinstance(max_pages, bool) or not isinstance(max_pages, int) or max_pages < 1:
        raise ValueError("max_pages must be a positive integer")
    started = time.perf_counter()
    source_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    retained_pages: list[OutlineSourcePage] = []
    document_characters = 0
    document_words = 0
    document_candidates = 0

    def check_deadline() -> None:
        if time.perf_counter() - started > SOURCE_EXTRACTION_DEADLINE_SECONDS:
            raise _SourceLimitError("outline extraction deadline exceeded")

    try:
        with (
            pdfium.PdfDocument(pdf_bytes) as geometry_document,
            pdfplumber.open(io.BytesIO(pdf_bytes)) as document,
        ):
            if len(document.pages) > max_pages:
                raise _SourceLimitError("outline source page limit exceeded")
            if len(geometry_document) != len(document.pages):
                raise _SourceLimitError("outline source page count differs")
            for page_index, page in enumerate(document.pages, 1):
                check_deadline()
                geometry_failed = False
                try:
                    raw_width, raw_height = geometry_document[page_index - 1].get_size()
                    page_width = float(raw_width)
                    page_height = float(raw_height)
                    if not all(
                        math.isfinite(value) and value > 0
                        for value in (page_width, page_height)
                    ):
                        raise ValueError("invalid PDFium page geometry")
                except Exception:
                    geometry_failed = True
                    try:
                        page_width = float(page.width)
                        page_height = float(page.height)
                    except (TypeError, ValueError) as exc:
                        raise _SourceLimitError(
                            "outline page geometry is unavailable"
                        ) from exc
                    if not all(
                        math.isfinite(value) and value > 0
                        for value in (page_width, page_height)
                    ):
                        raise _SourceLimitError("outline page geometry is unavailable")
                check_deadline()
                chars = page.chars
                check_deadline()
                words = page.extract_words()
                check_deadline()
                character_count = len(chars)
                word_count = len(words)
                document_characters += character_count
                document_words += word_count
                if (
                    document_characters > MAX_SOURCE_CHARACTERS_PER_DOCUMENT
                    or document_words > MAX_SOURCE_WORDS_PER_DOCUMENT
                ):
                    raise _SourceLimitError("outline source text limit exceeded")
                page_concern = (
                    "outline_geometry_ambiguous"
                    if geometry_failed
                    else (
                        "outline_source_limit"
                        if (
                            character_count > MAX_SOURCE_CHARACTERS_PER_PAGE
                            or word_count > MAX_SOURCE_WORDS_PER_PAGE
                        )
                        else None
                    )
                )
                if page_concern is not None:
                    retained_pages.append(
                        OutlineSourcePage(
                            page_index=page_index,
                            page_width=page_width,
                            page_height=page_height,
                            unit="pt",
                            coordinate_system_id=_coordinate_system_id(
                                source_sha256,
                                page_index,
                            ),
                            # A page-local resource refusal exposes only a
                            # bounded sentinel count; the exact observed count
                            # is still charged to the document counters above.
                            source_character_count=min(
                                character_count,
                                MAX_SOURCE_CHARACTERS_PER_PAGE,
                            ),
                            source_word_count=min(
                                word_count,
                                MAX_SOURCE_WORDS_PER_PAGE,
                            ),
                            markers=(),
                            concern_codes=(page_concern,),
                        )
                    )
                    continue

                try:
                    syntactic: list[tuple[int, Mapping[str, Any], str, int]] = []
                    comparisons = 0
                    line_min_x: dict[tuple[float, float], float] = {}
                    for word in words:
                        check_deadline()
                        comparisons += 1
                        if comparisons > MAX_COMPARISONS_PER_PAGE:
                            raise _PageSourceError("outline_source_limit")
                        line_key = (
                            round(float(word["top"]), 1),
                            round(float(word["bottom"]), 1),
                        )
                        x_value = float(word["x0"])
                        line_min_x[line_key] = min(
                            x_value,
                            line_min_x.get(line_key, x_value),
                        )
                    for word_index, word in enumerate(words):
                        check_deadline()
                        text_value = word.get("text")
                        if not isinstance(text_value, str):
                            continue
                        marker = _marker_kind(text_value)
                        if marker is None:
                            continue
                        if len(text_value.encode("utf-8")) > MAX_MARKER_BYTES:
                            continue
                        line_key = (
                            round(float(word["top"]), 1),
                            round(float(word["bottom"]), 1),
                        )
                        comparisons += 1
                        if comparisons > MAX_COMPARISONS_PER_PAGE:
                            raise _PageSourceError("outline_source_limit")
                        if float(word["x0"]) <= line_min_x[line_key] + 0.001:
                            syntactic.append((word_index, word, marker[0], marker[1]))

                    bullet_count = 0
                    ordered_by_style: dict[
                        str,
                        list[tuple[int, float]],
                    ] = {}
                    for index, value in enumerate(syntactic):
                        check_deadline()
                        if value[2] == "bullet":
                            bullet_count += 1
                        else:
                            ordered_by_style.setdefault(value[2], []).append(
                                (index, float(value[1]["x0"]))
                            )
                    aligned_ordered: set[int] = set()
                    for style_values in ordered_by_style.values():
                        style_values.sort(key=lambda value: (value[1], value[0]))
                        cluster: list[tuple[int, float]] = []
                        cluster_x: float | None = None
                        for candidate in style_values:
                            check_deadline()
                            comparisons += 1
                            if comparisons > MAX_COMPARISONS_PER_PAGE:
                                raise _PageSourceError("outline_source_limit")
                            if (
                                cluster_x is None
                                or abs(candidate[1] - cluster_x)
                                <= INDENT_TOLERANCE_POINTS
                            ):
                                if cluster_x is None:
                                    cluster_x = candidate[1]
                                cluster.append(candidate)
                                continue
                            if len(cluster) >= 2:
                                aligned_ordered.update(value[0] for value in cluster)
                            cluster = [candidate]
                            cluster_x = candidate[1]
                        if len(cluster) >= 2:
                            aligned_ordered.update(value[0] for value in cluster)
                    retained: list[tuple[int, Mapping[str, Any], str, int]] = []
                    for index, value in enumerate(syntactic):
                        check_deadline()
                        if (
                            value[2] == "bullet" and bullet_count >= 2
                        ) or index in aligned_ordered:
                            retained.append(value)
                    retained.sort(
                        key=lambda value: (
                            round(float(value[1]["top"]), 3),
                            round(float(value[1]["x0"]), 3),
                            str(value[1]["text"]).encode("utf-8"),
                            value[0],
                        )
                    )
                    retained = _assign_bullet_ordinals(retained)
                    document_candidates += len(retained)
                    if document_candidates > MAX_MARKER_CANDIDATES_PER_DOCUMENT:
                        raise _SourceLimitError(
                            "outline document marker limit exceeded"
                        )
                    if len(retained) > MAX_MARKER_CANDIDATES_PER_PAGE:
                        raise _PageSourceError("outline_source_limit")
                    if not retained:
                        continue
                    marker_records: list[OutlineSourceMarker] = []
                    for word_index, word, style, ordinal in retained:
                        check_deadline()
                        marker_records.append(
                            OutlineSourceMarker(
                                raw_marker=str(word["text"]),
                                marker_style=style,  # type: ignore[arg-type]
                                ordinal=ordinal,
                                bbox=_source_bbox(word),
                                source_object=OutlineSourceObject(
                                    reader="pdfplumber",
                                    page_index=page_index,
                                    word_index=word_index,
                                ),
                            )
                        )
                    markers = tuple(marker_records)
                    retained_pages.append(
                        OutlineSourcePage(
                            page_index=page_index,
                            page_width=page_width,
                            page_height=page_height,
                            unit="pt",
                            coordinate_system_id=_coordinate_system_id(
                                source_sha256,
                                page_index,
                            ),
                            source_character_count=character_count,
                            source_word_count=word_count,
                            markers=markers,
                        )
                    )
                except _PageSourceError as exc:
                    retained_pages.append(
                        OutlineSourcePage(
                            page_index=page_index,
                            page_width=page_width,
                            page_height=page_height,
                            unit="pt",
                            coordinate_system_id=_coordinate_system_id(
                                source_sha256,
                                page_index,
                            ),
                            source_character_count=character_count,
                            source_word_count=word_count,
                            markers=(),
                            concern_codes=(exc.code,),
                        )
                    )
                except _SourceLimitError as exc:
                    if "deadline" in str(exc) or "document" in str(exc):
                        raise
                    retained_pages.append(
                        OutlineSourcePage(
                            page_index=page_index,
                            page_width=page_width,
                            page_height=page_height,
                            unit="pt",
                            coordinate_system_id=_coordinate_system_id(
                                source_sha256,
                                page_index,
                            ),
                            source_character_count=character_count,
                            source_word_count=word_count,
                            markers=(),
                            concern_codes=("outline_geometry_ambiguous",),
                        )
                    )
                check_deadline()
        check_deadline()
        counts = OutlineSourceCounts(
            pages=len(retained_pages),
            source_characters=sum(
                value.source_character_count for value in retained_pages
            ),
            source_words=sum(value.source_word_count for value in retained_pages),
            marker_candidates=sum(len(value.markers) for value in retained_pages),
            concerns=sum(len(value.concern_codes) for value in retained_pages),
        )
        report = OutlineEvidenceReport(
            report_version=REPORT_VERSION,
            policy_id=POLICY_ID,
            source_sha256=source_sha256,
            status="available",
            pages=tuple(retained_pages),
            counts=counts,
            concern_codes=(),
            extraction_ms=round(
                max(time.perf_counter() - started, 0.0) * 1000.0,
                3,
            ),
        )
        if len(_strict_json_bytes(_report_payload(report))) > MAX_REPORT_BYTES:
            raise _SourceLimitError("outline source report byte limit exceeded")
        check_deadline()
        _validate_source_report(report, expected_source_sha256=source_sha256)
        return report
    except _SourceLimitError:
        return _refused_report(
            source_sha256=source_sha256,
            started_at=started,
            code="outline_source_limit",
        )


def _bounded_timing(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(parsed, 3) if math.isfinite(parsed) and parsed >= 0 else 0.0


def outline_processing_summary(
    metrics: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return the exact bounded enabled-stage processing summary."""

    source = metrics or {}
    extraction_ms = _bounded_timing(source.get("extraction_ms", 0.0))
    projection_ms = _bounded_timing(source.get("projection_ms", 0.0))
    status = source.get("status", "unavailable")
    if status not in {"projected", "no_candidates", "unavailable", "failed_closed"}:
        status = "failed_closed"

    def count(key: str) -> int:
        value = source.get(key, 0)
        return (
            value
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0
            else 0
        )

    group_count = count("group_count")
    node_count = count("node_count")
    relationship_count = count("relationship_count")
    concern_count = count("concern_count")
    if status == "projected" and group_count == 0:
        status = (
            "no_candidates"
            if node_count == 0 and relationship_count == 0
            else "failed_closed"
        )
    elif status == "projected" and (
        node_count < group_count * 2 or relationship_count < node_count
    ):
        status = "failed_closed"
    elif status == "no_candidates" and (
        group_count or node_count or relationship_count
    ):
        status = "failed_closed"

    reason = source.get("reason")
    if not isinstance(reason, str) or reason not in _ALLOWED_CONCERNS:
        reason = None
    if status in {"projected", "no_candidates"}:
        reason = None
    elif status == "unavailable":
        if reason not in {
            "outline_source_evidence_unavailable",
            "outline_source_limit",
        }:
            reason = "outline_source_evidence_unavailable"
    elif reason in {
        None,
        "outline_source_evidence_unavailable",
        "outline_source_limit",
    }:
        reason = "outline_projection_failed_closed"

    return {
        "policy_id": POLICY_ID,
        "status": status,
        "reason": reason,
        "group_count": group_count,
        "node_count": node_count,
        "relationship_count": relationship_count,
        "concern_count": concern_count,
        "extraction_ms": extraction_ms,
        "projection_ms": projection_ms,
        "total_ms": round(extraction_ms + projection_ms, 3),
    }


def _legacy_item(element: ElementRecord) -> Mapping[str, Any] | None:
    value = element.properties.get("legacy_item")
    return value if isinstance(value, Mapping) else None


def _box_tuple(box: IRBoundingBox) -> tuple[float, float, float, float]:
    return (box.x, box.y, box.width, box.height)


def _check_projection_deadlines(
    *,
    started_at: float,
    page_started_at: float,
) -> None:
    now = time.perf_counter()
    if now - started_at > PROJECTION_DOCUMENT_DEADLINE_SECONDS:
        raise _DocumentProjectionError("outline document deadline exceeded")
    if now - page_started_at > PROJECTION_PAGE_DEADLINE_SECONDS:
        raise _PageProjectionError("outline page deadline exceeded")


def _check_projection_document_deadline(*, started_at: float) -> None:
    if time.perf_counter() - started_at > PROJECTION_DOCUMENT_DEADLINE_SECONDS:
        raise _DocumentProjectionError("outline document deadline exceeded")


def _target_index(
    ir: DocumentIR,
    *,
    started_at: float,
    page_started_at: float,
    page_indexes: frozenset[int] | None = None,
) -> dict[int, list[_Target]]:
    elements: dict[str, ElementRecord] = {}
    bboxes: dict[str, IRBoundingBox] = {}
    evidence: dict[str, EvidenceRecord] = {}
    for value in ir.elements:
        _check_projection_deadlines(
            started_at=started_at,
            page_started_at=page_started_at,
        )
        elements[value.id] = value
    for value in ir.bboxes:
        _check_projection_deadlines(
            started_at=started_at,
            page_started_at=page_started_at,
        )
        bboxes[value.id] = value
    for value in ir.evidence:
        _check_projection_deadlines(
            started_at=started_at,
            page_started_at=page_started_at,
        )
        evidence[value.id] = value

    selected_pages = [
        value
        for value in ir.pages
        if page_indexes is None or value.page_index in page_indexes
    ]
    selected_page_ids = {value.id for value in selected_pages}
    children_by_parent: dict[str, list[ElementRecord]] = {}
    for child in ir.elements:
        _check_projection_deadlines(
            started_at=started_at,
            page_started_at=page_started_at,
        )
        parent_id = child.properties.get("parent_element_id")
        if (
            child.page_id in selected_page_ids
            and isinstance(parent_id, str)
            and child.properties.get("collection") == "items"
        ):
            children_by_parent.setdefault(parent_id, []).append(child)

    def source_binding(
        element: ElementRecord,
    ) -> tuple[str, tuple[str, ...]] | None:
        if not element.bbox_ids:
            return None
        bbox_id = element.bbox_ids[0]
        if bbox_id not in bboxes:
            return None
        evidence_ids = tuple(
            evidence_id
            for evidence_id in element.evidence_ids
            if evidence_id in evidence and evidence[evidence_id].bbox_id == bbox_id
        )
        if not evidence_ids:
            return None
        return bbox_id, evidence_ids

    targets: dict[int, list[_Target]] = {}
    page_offsets = {
        page.id: offset
        for offset, page in enumerate(
            sorted(ir.pages, key=lambda value: value.page_index)
        )
    }
    for page in sorted(selected_pages, key=lambda value: value.page_index):
        _check_projection_deadlines(
            started_at=started_at,
            page_started_at=page_started_at,
        )
        page_offset = page_offsets[page.id]
        for rank, element_id in enumerate(page.presentation_element_ids):
            _check_projection_deadlines(
                started_at=started_at,
                page_started_at=page_started_at,
            )
            element = elements[element_id]
            legacy = _legacy_item(element)
            if legacy is None:
                continue
            public_id = legacy.get("id")
            if not isinstance(public_id, str) or not public_id:
                continue
            element_binding = source_binding(element)
            if (
                isinstance(element.value, str)
                and element_binding is not None
                and element.type.casefold() in _TOP_LEVEL_OUTLINE_TYPES
            ):
                element_bbox_id, element_evidence_ids = element_binding
                targets.setdefault(page.page_index, []).append(
                    _Target(
                        element_id=element.id,
                        anchor_element_id=element.id,
                        public_item_id=public_id,
                        public_path=("pages", page_offset, "items", rank),
                        bbox_id=element_bbox_id,
                        evidence_ids=element_evidence_ids,
                        bbox=_box_tuple(bboxes[element_bbox_id]),
                        value=element.value,
                        nested=False,
                        page_index=page.page_index,
                        reading_rank=rank,
                    )
                )
            if element.type.casefold() != "list":
                continue
            for child in children_by_parent.get(element.id, []):
                _check_projection_deadlines(
                    started_at=started_at,
                    page_started_at=page_started_at,
                )
                if not isinstance(child.value, str):
                    continue
                child_binding = source_binding(child)
                if child_binding is None:
                    continue
                child_bbox_id, child_evidence_ids = child_binding
                child_index = child.properties.get("index")
                if isinstance(child_index, bool) or not isinstance(child_index, int):
                    continue
                targets.setdefault(page.page_index, []).append(
                    _Target(
                        element_id=child.id,
                        anchor_element_id=element.id,
                        public_item_id=public_id,
                        public_path=(
                            "pages",
                            page_offset,
                            "items",
                            rank,
                            "items",
                            child_index,
                        ),
                        bbox_id=child_bbox_id,
                        evidence_ids=child_evidence_ids,
                        bbox=_box_tuple(bboxes[child_bbox_id]),
                        value=child.value,
                        nested=True,
                        page_index=page.page_index,
                        reading_rank=rank,
                    )
                )
    for values in targets.values():
        _check_projection_deadlines(
            started_at=started_at,
            page_started_at=page_started_at,
        )
        values.sort(
            key=lambda value: (value.reading_rank, value.public_path, value.element_id)
        )
    return targets


def _bbox_contains_marker(
    bbox: tuple[float, float, float, float],
    marker: OutlineSourceBBox,
) -> bool:
    x, y, width, height = bbox
    vertical_overlap = min(
        marker.y + marker.height,
        y + height,
    ) - max(marker.y, y)
    return (
        marker.x >= x - 1.0
        and marker.x + marker.width <= x + width + 1.0
        and vertical_overlap >= 0.5 * min(marker.height, height)
    )


def _match_markers(
    ir: DocumentIR,
    report: OutlineEvidenceReport,
    *,
    started_at: float,
    metrics: MutableMapping[str, Any] | None = None,
    page_indexes: frozenset[int] | None = None,
    page_started_at: float | None = None,
) -> tuple[list[_MatchedNode], dict[int, set[str]]]:
    page_started = (
        page_started_at if page_started_at is not None else time.perf_counter()
    )
    targets = _target_index(
        ir,
        started_at=started_at,
        page_started_at=page_started,
        page_indexes=page_indexes,
    )
    matched: list[_MatchedNode] = []
    rejected: dict[int, set[str]] = {}
    used_elements: set[str] = set()
    comparisons_by_page: Counter[int] = Counter()
    existing_ledger = (
        metrics.get("comparisons_by_page") if metrics is not None else None
    )
    comparison_ledger: dict[int, int] = (
        existing_ledger if isinstance(existing_ledger, dict) else {}
    )
    for page in report.pages:
        if page_indexes is None or page.page_index in page_indexes:
            comparison_ledger.setdefault(page.page_index, 0)
    if metrics is not None:
        metrics["comparisons_by_page"] = comparison_ledger
    target_buckets: dict[int, dict[int, list[_Target]]] = {}
    bucket_height = 16.0
    for target_page, page_targets in targets.items():
        page_buckets = target_buckets.setdefault(target_page, {})
        for target in page_targets:
            _check_projection_deadlines(
                started_at=started_at,
                page_started_at=page_started,
            )
            first_bucket = math.floor((target.bbox[1] - 1.0) / bucket_height)
            last_bucket = math.floor(
                (target.bbox[1] + target.bbox[3] + 1.0) / bucket_height
            )
            if last_bucket - first_bucket > MAX_COMPARISONS_PER_PAGE:
                raise _PageProjectionError("outline target bucket limit exceeded")
            for bucket in range(first_bucket, last_bucket + 1):
                page_buckets.setdefault(bucket, []).append(target)
    for source_page in report.pages:
        if page_indexes is not None and source_page.page_index not in page_indexes:
            continue
        _check_projection_deadlines(
            started_at=started_at,
            page_started_at=page_started,
        )
        for marker in source_page.markers:
            _check_projection_deadlines(
                started_at=started_at,
                page_started_at=page_started,
            )
            candidates: list[tuple[float, _Target, str, str, str]] = []
            marker_bucket = math.floor(marker.bbox.y / bucket_height)
            for target in target_buckets.get(source_page.page_index, {}).get(
                marker_bucket,
                [],
            ):
                _check_projection_deadlines(
                    started_at=started_at,
                    page_started_at=page_started,
                )
                comparisons_by_page[source_page.page_index] += 1
                comparison_ledger[source_page.page_index] = comparisons_by_page[
                    source_page.page_index
                ]
                if (
                    comparisons_by_page[source_page.page_index]
                    > MAX_COMPARISONS_PER_PAGE
                ):
                    raise _PageProjectionError("outline comparison limit exceeded")
                if not _bbox_contains_marker(target.bbox, marker.bbox):
                    continue
                value = target.value
                if value.startswith(marker.raw_marker + " "):
                    ownership = "value_prefix"
                    separator = " "
                    body = value[len(marker.raw_marker) + 1 :]
                elif target.nested:
                    ownership = "separate"
                    separator = ""
                    body = value
                else:
                    continue
                if not body or len(body.encode("utf-8")) > MAX_ITEM_TEXT_BYTES:
                    continue
                area = target.bbox[2] * target.bbox[3]
                candidates.append((area, target, ownership, separator, body))
            candidates.sort(key=lambda value: (value[0], value[1].element_id))
            nested_candidates = [value for value in candidates if value[1].nested]
            top_candidates = [value for value in candidates if not value[1].nested]
            if marker.marker_style == "lower_alpha" and top_candidates:
                candidates = top_candidates
            elif nested_candidates:
                candidates = nested_candidates
            if len(candidates) != 1 or candidates[0][1].element_id in used_elements:
                rejected.setdefault(source_page.page_index, set()).add(
                    "outline_geometry_ambiguous"
                )
                continue
            _area, target, ownership, separator, body = candidates[0]
            used_elements.add(target.element_id)
            matched.append(
                _MatchedNode(
                    target=target,
                    marker=marker,
                    marker_ownership=ownership,  # type: ignore[arg-type]
                    marker_separator=separator,
                    body_text=body,
                )
            )
            _check_projection_deadlines(
                started_at=started_at,
                page_started_at=page_started,
            )
    matched.sort(
        key=lambda value: (
            value.target.page_index,
            value.target.reading_rank,
            value.target.public_path,
            value.marker.bbox.y,
            value.marker.bbox.x,
            value.marker.raw_marker.encode("utf-8"),
            value.marker.source_object.word_index,
        )
    )
    return matched, rejected


def _page_primary_lookup(
    ir: DocumentIR,
    *,
    deadline_check: Callable[[], None] | None = None,
) -> tuple[dict[str, int], dict[str, tuple[str, tuple[str | int, ...]]]]:
    elements = {value.id: value for value in ir.elements}
    ranks: dict[str, int] = {}
    public: dict[str, tuple[str, tuple[str | int, ...]]] = {}
    for page_offset, page in enumerate(
        sorted(ir.pages, key=lambda value: value.page_index)
    ):
        if deadline_check is not None:
            deadline_check()
        for rank, element_id in enumerate(page.presentation_element_ids):
            if deadline_check is not None:
                deadline_check()
            ranks[element_id] = rank
            legacy = _legacy_item(elements[element_id])
            if legacy is not None and isinstance(legacy.get("id"), str):
                public[element_id] = (
                    str(legacy["id"]),
                    ("pages", page_offset, "items", rank),
                )
    return ranks, public


def _infer_nested_levels(
    values: Sequence[_MatchedNode],
    *,
    deadline_check: Callable[[], None] | None = None,
) -> tuple[int, ...]:
    centers: list[float] = []
    levels: list[int] = []
    for value in values:
        if deadline_check is not None:
            deadline_check()
        x = value.marker.bbox.x
        level = next(
            (
                index
                for index, center in enumerate(centers)
                if abs(center - x) <= INDENT_TOLERANCE_POINTS
            ),
            None,
        )
        if level is None:
            centers.append(x)
            centers.sort()
            if any(
                current - previous < MINIMUM_INDENT_STEP_POINTS
                for previous, current in zip(centers, centers[1:], strict=False)
            ):
                raise _PageProjectionError("outline indentation is ambiguous")
            level = centers.index(x)
        levels.append(level)
    if len(centers) > MAX_DEPTH or not levels or levels[0] != 0:
        raise _PageProjectionError("outline depth differs")
    if any(current > previous + 1 for previous, current in zip(levels, levels[1:])):
        raise _PageProjectionError("outline levels are skipped")
    return tuple(levels)


def _form_owned_element_ids(ir: DocumentIR) -> frozenset[str]:
    owned = {value.id for value in ir.elements if value.form_semantics is not None}
    for element in ir.elements:
        descriptor = element.form_semantics
        if isinstance(descriptor, FormGroupSemanticDescriptor):
            owned.update(descriptor.contributor_element_ids)
    return frozenset(owned)


def _build_group_plans(
    ir: DocumentIR,
    matched: Sequence[_MatchedNode],
    *,
    deadline_check: Callable[[], None] | None = None,
) -> tuple[_GroupPlan, ...]:
    def charge() -> None:
        if deadline_check is not None:
            deadline_check()

    charge()
    elements = {value.id: value for value in ir.elements}
    charge()
    bboxes = {value.id: value for value in ir.bboxes}
    charge()
    evidence = {value.id: value for value in ir.evidence}
    charge()
    pages_by_index = {value.page_index: value for value in ir.pages}
    ranks, public = _page_primary_lookup(
        ir,
        deadline_check=deadline_check,
    )
    raw_groups: list[
        tuple[
            Literal["unordered", "ordered", "legal"],
            Literal["bullet", "decimal", "lower_alpha"],
            str,
            tuple[str | int, ...],
            list[tuple[_MatchedNode, int, int, str | None]],
            list[
                tuple[
                    str,
                    str,
                    tuple[str | int, ...],
                    str,
                    tuple[float, float, float, float],
                    tuple[str, ...],
                ]
            ],
        ]
    ] = []

    nested_by_anchor: dict[str, list[_MatchedNode]] = {}
    top_by_page: dict[int, list[_MatchedNode]] = {}
    for value in matched:
        charge()
        if value.target.nested:
            nested_by_anchor.setdefault(value.target.anchor_element_id, []).append(
                value
            )
        else:
            top_by_page.setdefault(value.target.page_index, []).append(value)

    for anchor_id, values in nested_by_anchor.items():
        charge()
        values.sort(key=lambda value: value.target.public_path[-1])
        expected_children = sorted(
            (
                value
                for value in elements.values()
                if value.properties.get("parent_element_id") == anchor_id
                and value.properties.get("collection") == "items"
            ),
            key=lambda value: (
                value.properties.get("index")
                if isinstance(value.properties.get("index"), int)
                and not isinstance(value.properties.get("index"), bool)
                else MAX_NODES_PER_GROUP + 1,
                value.id,
            ),
        )
        expected_indexes = [
            value.properties.get("index") for value in expected_children
        ]
        if (
            not 2 <= len(expected_children) <= MAX_NODES_PER_GROUP
            or expected_indexes != list(range(len(expected_children)))
            or [value.target.element_id for value in values]
            != [value.id for value in expected_children]
        ):
            raise _PageProjectionError("outline list membership is incomplete")
        marker_styles = {value.marker.marker_style for value in values}
        if len(values) < 2 or len(marker_styles) != 1:
            continue
        [nested_marker_style] = marker_styles
        if nested_marker_style == "lower_alpha":
            continue
        if (
            len(
                {
                    _marker_family(
                        value.marker.raw_marker,
                        nested_marker_style,
                    )
                    for value in values
                }
            )
            != 1
        ):
            continue
        levels = _infer_nested_levels(
            values,
            deadline_check=deadline_check,
        )
        parents: list[str | None] = []
        latest_by_level: dict[int, str] = {}
        ordinals: Counter[str | None] = Counter()
        node_rows: list[tuple[_MatchedNode, int, int, str | None]] = []
        for value, level in zip(values, levels, strict=True):
            charge()
            parent = None if level == 0 else latest_by_level.get(level - 1)
            if level > 0 and parent is None:
                raise _PageProjectionError("outline parent is unavailable")
            parents.append(parent)
            ordinals[parent] += 1
            if (
                nested_marker_style != "bullet"
                and value.marker.ordinal != ordinals[parent]
            ):
                raise _PageProjectionError("outline ordered sibling sequence differs")
            node_rows.append((value, level, ordinals[parent], parent))
            latest_by_level[level] = value.target.element_id
            for stale in [key for key in latest_by_level if key > level]:
                latest_by_level.pop(stale, None)
        anchor_public_id, anchor_path = public[anchor_id]
        raw_groups.append(
            (
                (
                    "unordered"
                    if nested_marker_style == "bullet"
                    else (
                        "legal" if nested_marker_style == "lower_alpha" else "ordered"
                    )
                ),
                nested_marker_style,  # type: ignore[arg-type]
                anchor_public_id,
                anchor_path,
                node_rows,
                [],
            )
        )

    for page_index, values in top_by_page.items():
        charge()
        values.sort(key=lambda value: value.target.reading_rank)
        start = 0
        while start < len(values):
            charge()
            style = values[start].marker.marker_style
            family = _marker_family(values[start].marker.raw_marker, style)
            end = start + 1
            while (
                end < len(values)
                and values[end].marker.marker_style == style
                and _marker_family(
                    values[end].marker.raw_marker,
                    style,
                )
                == family
                and abs(values[end].marker.bbox.x - values[start].marker.bbox.x)
                <= INDENT_TOLERANCE_POINTS
            ):
                charge()
                between = pages_by_index[page_index].presentation_element_ids[
                    values[end - 1].target.reading_rank + 1 : values[
                        end
                    ].target.reading_rank
                ]
                if any(elements[value].type.casefold() != "table" for value in between):
                    break
                end += 1
            segment = values[start:end]
            start = end
            if len(segment) < 3 or style == "bullet":
                continue
            if [value.marker.ordinal for value in segment] != list(
                range(1, len(segment) + 1)
            ):
                continue
            node_rows = [
                (value, 0, index, None) for index, value in enumerate(segment, 1)
            ]
            continuation_rows: list[
                tuple[
                    str,
                    str,
                    tuple[str | int, ...],
                    str,
                    tuple[float, float, float, float],
                    tuple[str, ...],
                ]
            ] = []
            for first, second in zip(segment, segment[1:], strict=False):
                charge()
                between = pages_by_index[page_index].presentation_element_ids[
                    first.target.reading_rank + 1 : second.target.reading_rank
                ]
                if len(between) > MAX_INTERSTITIALS_PER_GROUP:
                    raise _PageProjectionError("outline interstitial limit exceeded")
                for element_id in between:
                    charge()
                    continuation = elements[element_id]
                    if (
                        continuation.type.casefold() != "table"
                        or not continuation.bbox_ids
                    ):
                        raise _PageProjectionError("outline interstitial is ambiguous")
                    public_id, public_path = public[element_id]
                    bbox_id = continuation.bbox_ids[0]
                    continuation_bbox = _box_tuple(bboxes[bbox_id])
                    adjacent_min_x = min(
                        first.target.bbox[0],
                        second.target.bbox[0],
                    )
                    adjacent_max_x = max(
                        first.target.bbox[0] + first.target.bbox[2],
                        second.target.bbox[0] + second.target.bbox[2],
                    )
                    overlap_width = max(
                        0.0,
                        min(
                            continuation_bbox[0] + continuation_bbox[2],
                            adjacent_max_x,
                        )
                        - max(continuation_bbox[0], adjacent_min_x),
                    )
                    smaller_width = min(
                        continuation_bbox[2],
                        adjacent_max_x - adjacent_min_x,
                    )
                    if smaller_width <= 0 or overlap_width / smaller_width < 0.80:
                        raise _PageProjectionError(
                            "outline interstitial overlap is insufficient"
                        )
                    source_evidence_ids = tuple(
                        evidence_id
                        for evidence_id in continuation.evidence_ids
                        if evidence_id in evidence
                        and evidence[evidence_id].bbox_id == bbox_id
                    )
                    if not source_evidence_ids:
                        raise _PageProjectionError(
                            "outline interstitial evidence is unavailable"
                        )
                    continuation_rows.append(
                        (
                            element_id,
                            public_id,
                            public_path,
                            bbox_id,
                            continuation_bbox,
                            source_evidence_ids,
                        )
                    )
            if len(continuation_rows) > MAX_INTERSTITIALS_PER_GROUP:
                raise _PageProjectionError("outline interstitial limit exceeded")
            anchor = segment[0].target
            raw_groups.append(
                (
                    "legal" if style == "lower_alpha" else "ordered",
                    style,  # type: ignore[arg-type]
                    anchor.public_item_id,
                    anchor.public_path,
                    node_rows,
                    continuation_rows,
                )
            )

    plans: list[_GroupPlan] = []
    for (
        sequence_kind,
        marker_style,
        anchor_public_id,
        anchor_path,
        rows,
        continuation_rows,
    ) in raw_groups:
        charge()
        if not 2 <= len(rows) <= MAX_NODES_PER_GROUP:
            continue
        anchor_element_id = rows[0][0].target.anchor_element_id
        member_element_ids = tuple(value[0].target.element_id for value in rows)
        continuation_element_ids = tuple(value[0] for value in continuation_rows)
        page_index = rows[0][0].target.page_index
        page = pages_by_index[page_index]
        group_id = _stable_id(
            "outline-group",
            POLICY_ID,
            ir.source_sha256,
            page_index,
            anchor_element_id,
            member_element_ids,
            continuation_element_ids,
        )
        group_element_id = _stable_id("outline-element", group_id)
        node_plans: list[_NodePlan] = []
        element_to_item: dict[str, str] = {}
        for matched_value, level, ordinal, parent_element_id in rows:
            charge()
            item_id = _stable_id(
                "outline-item", group_id, matched_value.target.element_id
            )
            element_to_item[matched_value.target.element_id] = item_id
            node_plans.append(
                _NodePlan(
                    matched=matched_value,
                    item_id=item_id,
                    marker_bbox_id=_stable_id(
                        "outline-bbox",
                        group_id,
                        matched_value.target.element_id,
                        "marker",
                        matched_value.marker.source_object.word_index,
                    ),
                    marker_evidence_id=_stable_id(
                        "outline-evidence",
                        group_id,
                        matched_value.target.element_id,
                        "marker",
                        matched_value.marker.source_object.word_index,
                    ),
                    level=level,
                    ordinal=ordinal,
                    parent_element_id=parent_element_id,
                    parent_item_id=(
                        None
                        if parent_element_id is None
                        else element_to_item[parent_element_id]
                    ),
                )
            )
        continuation_plans: list[_ContinuationPlan] = []
        for (
            element_id,
            public_id,
            public_path,
            bbox_id,
            bbox,
            evidence_ids,
        ) in continuation_rows:
            charge()
            element_rank = ranks[element_id]
            prior_nodes = [
                value
                for value in node_plans
                if value.matched.target.reading_rank < element_rank
            ]
            if not prior_nodes:
                raise _PageProjectionError("outline continuation has no prior owner")
            target = prior_nodes[-1]
            continuation_plans.append(
                _ContinuationPlan(
                    id=_stable_id(
                        "outline-continuation",
                        group_id,
                        element_id,
                        target.item_id,
                    ),
                    element_id=element_id,
                    public_item_id=public_id,
                    public_path=public_path,
                    bbox_id=bbox_id,
                    bbox=bbox,
                    evidence_ids=evidence_ids,
                    target_element_id=target.matched.target.element_id,
                    target_item_id=target.item_id,
                )
            )
        marker_evidence = {
            value.matched.target.element_id: value.marker_evidence_id
            for value in node_plans
        }
        relationships: list[_RelationshipPlan] = []

        def add_relationship(
            relationship_type: RelationshipType,
            source_id: str,
            target_id: str,
            evidence_ids: tuple[str, ...],
            **metadata: Any,
        ) -> None:
            relationship_id = _stable_id(
                "outline-relationship",
                POLICY_ID,
                group_id,
                relationship_type.value,
                source_id,
                target_id,
            )
            relationships.append(
                _RelationshipPlan(
                    id=relationship_id,
                    type=relationship_type,
                    source_id=source_id,
                    target_id=target_id,
                    evidence_ids=evidence_ids,
                    metadata={
                        "canonical_inert": True,
                        "outline_group_id": group_id,
                        "outline_policy": POLICY_ID,
                        **metadata,
                    },
                )
            )

        group_evidence_id = _stable_id("outline-evidence", group_id, "group")
        for node in node_plans:
            charge()
            add_relationship(
                RelationshipType.CONTAINS,
                group_element_id,
                node.matched.target.element_id,
                (group_evidence_id, node.marker_evidence_id),
            )
        for node in node_plans:
            charge()
            if node.parent_element_id is not None:
                add_relationship(
                    RelationshipType.OUTLINE_PARENT_OF,
                    node.parent_element_id,
                    node.matched.target.element_id,
                    (
                        marker_evidence[node.parent_element_id],
                        node.marker_evidence_id,
                    ),
                )
        siblings: dict[str | None, list[_NodePlan]] = {}
        for node in node_plans:
            charge()
            siblings.setdefault(node.parent_element_id, []).append(node)
        continuation_by_target: dict[str, list[_ContinuationPlan]] = {}
        for value in continuation_plans:
            charge()
            continuation_by_target.setdefault(value.target_element_id, []).append(value)
        for values in siblings.values():
            charge()
            for first, second in zip(values, values[1:], strict=False):
                charge()
                intervening = [
                    value.element_id
                    for value in continuation_by_target.get(
                        first.matched.target.element_id,
                        [],
                    )
                ]
                add_relationship(
                    RelationshipType.OUTLINE_NEXT,
                    first.matched.target.element_id,
                    second.matched.target.element_id,
                    (first.marker_evidence_id, second.marker_evidence_id),
                    intervening_element_ids=intervening,
                )
        for continuation in continuation_plans:
            charge()
            add_relationship(
                RelationshipType.OUTLINE_CONTINUATION_OF,
                continuation.element_id,
                continuation.target_element_id,
                (
                    *continuation.evidence_ids,
                    marker_evidence[continuation.target_element_id],
                ),
                interstitial_kind="table",
            )
        if len(relationships) > MAX_RELATIONSHIPS_PER_PAGE:
            raise _PageProjectionError("outline relationship limit exceeded")
        source_boxes = [value[0].target.bbox for value in rows] + [
            value.bbox for value in continuation_plans
        ]
        min_x = min(value[0] for value in source_boxes)
        min_y = min(value[1] for value in source_boxes)
        max_x = max(value[0] + value[2] for value in source_boxes)
        max_y = max(value[1] + value[3] for value in source_boxes)
        plans.append(
            _GroupPlan(
                id=group_id,
                element_id=group_element_id,
                bbox_id=_stable_id("outline-bbox", group_id, "group"),
                evidence_id=group_evidence_id,
                page_id=page.id,
                page_index=page_index,
                coordinate_system_id=page.coordinate_system_id,
                sequence_kind=sequence_kind,
                marker_style=marker_style,
                anchor_element_id=anchor_element_id,
                anchor_public_item_id=anchor_public_id,
                anchor_public_path=anchor_path,
                nodes=tuple(node_plans),
                continuations=tuple(continuation_plans),
                relationships=tuple(relationships),
                bbox=(min_x, min_y, max_x - min_x, max_y - min_y),
                concern_codes=(),
            )
        )
    plans.sort(
        key=lambda value: (
            value.page_index,
            ranks[value.anchor_element_id],
            value.anchor_element_id,
        )
    )
    charge()
    return tuple(plans)


def _canonical_closure(
    group: _GroupPlan,
    predecessor: Any,
    *,
    form_owned_element_ids: Sequence[str],
    deadline_check: Callable[[], None] | None = None,
) -> _CanonicalClosure:
    def charge() -> None:
        if deadline_check is not None:
            deadline_check()

    charge()
    blocks = [
        block
        for page in predecessor.pages
        for block in page.blocks
        if block.omission_reason is None
    ]
    target_ids = {
        group.anchor_element_id,
        *(value.matched.target.element_id for value in group.nodes),
        *(value.element_id for value in group.continuations),
    }
    owners: dict[str, list[Any]] = {value: [] for value in target_ids}
    for block in blocks:
        charge()
        for contributor in block.contributing_element_ids:
            charge()
            if contributor in owners:
                owners[contributor].append(block)
    if any(len(value) != 1 for value in owners.values()):
        raise _PageProjectionError("outline canonical target ownership is not exact")
    selected_ids = {value[0].id for value in owners.values()}
    selected = [value for value in blocks if value.id in selected_ids]
    anchor_blocks = [
        value
        for value in selected
        if value.primary_element_id == group.anchor_element_id
    ]
    if len(anchor_blocks) != 1 or anchor_blocks[0].scope != "body":
        raise _PageProjectionError("outline canonical anchor ownership is not exact")
    [anchor] = anchor_blocks
    directly_rendered_ids = {
        group.anchor_element_id,
        *(value.matched.target.element_id for value in group.nodes),
    }
    continuation_ids = {value.element_id for value in group.continuations}
    for block in selected:
        charge()
        if block.primary_element_id in continuation_ids:
            continue
        if any(
            value not in directly_rendered_ids
            for value in block.contributing_element_ids
        ):
            raise _PageProjectionError(
                "outline canonical closure contains unrendered contributors"
            )
    contributors: list[str] = []
    predecessor_relationship_ids: list[str] = []
    predecessor_primary_ids: list[str] = []
    for block in selected:
        charge()
        predecessor_primary_ids.append(block.primary_element_id)
        for value in block.contributing_element_ids:
            charge()
            if value not in contributors:
                contributors.append(value)
        for value in block.relationship_ids:
            charge()
            if value not in predecessor_relationship_ids:
                predecessor_relationship_ids.append(value)
    if group.anchor_element_id in contributors:
        contributors.remove(group.anchor_element_id)
    contributors.insert(0, group.anchor_element_id)
    if set(contributors) & set(form_owned_element_ids):
        raise _PageProjectionError("outline canonical closure overlaps form ownership")
    story_relationship_ids = [value.id for value in group.relationships]
    return _CanonicalClosure(
        block_id=anchor.id,
        page_id=anchor.page_id,
        primary_element_id=anchor.primary_element_id,
        primary_element_type=anchor.primary_element_type,
        predecessor_primary_ids=tuple(predecessor_primary_ids),
        contributing_element_ids=tuple(contributors),
        predecessor_relationship_ids=tuple(predecessor_relationship_ids),
        relationship_ids=tuple(
            sorted({*predecessor_relationship_ids, *story_relationship_ids})
        ),
    )


def _safe_plain_text(value: str) -> str:
    return "".join(
        character
        if character >= " " and character not in {"\x7f", "\u2028", "\u2029"}
        else "�"
        for character in value
    )


_UNSAFE_LINK_SCHEME = re.compile(
    r"(?:javascript|vbscript|data|file|blob)\s*:",
    re.IGNORECASE,
)
_MARKDOWN_INLINE_DESTINATION = re.compile(
    r"(?<!\\)\]\(\s*([^\s)]+)",
)
_MARKDOWN_REFERENCE_DESTINATION = re.compile(
    r"(?m)^\s{0,3}\[[^\]\r\n]+\]:\s*([^\s]+)",
)
_URI_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*):")


class _ContinuationTableHTMLValidator(HTMLParser):
    _ALLOWED_TAGS = frozenset({"table", "thead", "tbody", "tr", "th", "td"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.stack: list[str] = []
        self.root_count = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag not in self._ALLOWED_TAGS:
            raise ValueError("outline continuation HTML tag is unsafe")
        if not self.stack:
            if tag != "table":
                raise ValueError("outline continuation HTML root differs")
            self.root_count += 1
        allowed_attributes = {"rowspan", "colspan"} if tag in {"th", "td"} else set()
        if len(attrs) != len({key for key, _value in attrs}) or any(
            key not in allowed_attributes
            or value is None
            or re.fullmatch(r"[1-9][0-9]{0,3}", value) is None
            for key, value in attrs
        ):
            raise ValueError("outline continuation HTML attributes are unsafe")
        self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack.pop() != tag:
            raise ValueError("outline continuation HTML nesting differs")

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        raise ValueError("outline continuation self-closing HTML is unsafe")

    def handle_comment(self, data: str) -> None:
        raise ValueError("outline continuation HTML comment is unsafe")

    def handle_decl(self, decl: str) -> None:
        raise ValueError("outline continuation HTML declaration is unsafe")

    def handle_pi(self, data: str) -> None:
        raise ValueError("outline continuation HTML instruction is unsafe")

    def unknown_decl(self, data: str) -> None:
        raise ValueError("outline continuation HTML declaration is unsafe")


def _validate_continuation_markdown(value: str) -> None:
    """Reject active Markdown before predecessor bytes enter an outline block."""

    if any(
        ord(character) < 32 and character not in {"\n", "\t"} for character in value
    ):
        raise ValueError("outline continuation markdown is unsafe")
    if "<" in value or ">" in value:
        validator = _ContinuationTableHTMLValidator()
        try:
            validator.feed(value)
            validator.close()
        except (ValueError, AssertionError) as exc:
            raise ValueError("outline continuation markdown is unsafe") from exc
        if validator.stack or validator.root_count != 1:
            raise ValueError("outline continuation markdown is unsafe")
    decoded = unquote(html.unescape(value))
    compact = "".join(
        character
        for character in decoded
        if not character.isspace() and character != "\\" and ord(character) >= 32
    )
    if _UNSAFE_LINK_SCHEME.search(compact):
        raise ValueError("outline continuation link scheme is unsafe")
    destinations = [
        *(_MARKDOWN_INLINE_DESTINATION.findall(decoded)),
        *(_MARKDOWN_REFERENCE_DESTINATION.findall(decoded)),
    ]
    for raw_destination in destinations:
        destination = raw_destination.strip("\"'")
        if not destination or destination.startswith("//"):
            raise ValueError("outline continuation link destination is unsafe")
        match = _URI_SCHEME.match(destination)
        if match is not None and match.group(1).casefold() not in {
            "http",
            "https",
            "mailto",
        }:
            raise ValueError("outline continuation link scheme is unsafe")


def _list_tag(sequence_kind: str, marker_style: str) -> tuple[str, str]:
    if sequence_kind == "unordered":
        return "ul", ""
    if marker_style == "decimal":
        return "ol", ""
    if marker_style == "lower_alpha":
        return "ol", ' type="a"'
    raise ValueError("outline ordered marker style is unsupported")


def _render_outline(
    *,
    group_id: str,
    sequence_kind: str,
    marker_style: str,
    nodes: Sequence[Mapping[str, Any]],
    continuations: Sequence[Mapping[str, Any]],
    continuation_markdown: Mapping[str, str],
    continuation_text: Mapping[str, str],
    deadline_check: Callable[[], None] | None = None,
) -> tuple[str, str]:
    def charge() -> None:
        if deadline_check is not None:
            deadline_check()

    charge()
    by_parent: dict[str | None, list[Mapping[str, Any]]] = {}
    for node in nodes:
        charge()
        by_parent.setdefault(node["parent_id"], []).append(node)
    if len(by_parent.get(None, [])) < 2:
        raise ValueError("outline group requires at least two roots")
    for siblings in by_parent.values():
        charge()
        if [value["ordinal"] for value in siblings] != list(
            range(1, len(siblings) + 1)
        ):
            raise ValueError("outline sibling ordinals must begin at one")
    continuation_by_target: dict[str, list[Mapping[str, Any]]] = {}
    for value in continuations:
        charge()
        continuation_by_target.setdefault(value["target_node_id"], []).append(value)
    tag, type_attribute = _list_tag(sequence_kind, marker_style)
    start_attribute = ' start="1"' if tag == "ol" else ""
    root_open = (
        f'<{tag} data-outline-group="{html.escape(group_id, quote=True)}" '
        f'data-outline-policy="{POLICY_ID}"{type_attribute}{start_attribute}>'
    )
    markdown_lines = [root_open]
    text_lines: list[str] = []

    def render_level(parent_id: str | None, level: int, *, root: bool) -> None:
        siblings = by_parent.get(parent_id, [])
        if not root:
            markdown_lines.append(
                f"{'  ' * level}<{tag}{type_attribute}{start_attribute}>"
            )
        for node in siblings:
            charge()
            if node["level"] != level:
                raise ValueError("outline node level differs")
            indent = "  " * (level + 1)
            value_attribute = f' value="{node["ordinal"]}"' if tag == "ol" else ""
            opening = (
                f'{indent}<li data-outline-item="'
                f'{html.escape(str(node["id"]), quote=True)}" '
                f'data-source-marker="'
                f'{html.escape(str(node["raw_marker"]), quote=True)}"'
                f"{value_attribute}>"
                f"{html.escape(_safe_plain_text(str(node['body_text'])), quote=False)}"
            )
            text_lines.append(
                f"{'  ' * level}{_safe_plain_text(str(node['raw_marker']))} "
                f"{_safe_plain_text(str(node['body_text']))}"
            )
            children = node["id"] in by_parent
            owned = continuation_by_target.get(str(node["id"]), [])
            if not children and not owned:
                markdown_lines.append(f"{opening}</li>")
                continue
            markdown_lines.append(opening)
            if children:
                render_level(str(node["id"]), level + 1, root=False)
            for continuation in owned:
                charge()
                element_id = str(continuation["element_id"])
                markdown = continuation_markdown[element_id]
                text = continuation_text[element_id]
                if markdown != markdown.strip() or text != text.strip():
                    raise ValueError("outline continuation has outer whitespace")
                _validate_continuation_markdown(markdown)
                markdown_lines.extend(markdown.split("\n"))
                text_lines.extend(
                    f"{'  ' * (level + 1)}{line}" for line in text.split("\n")
                )
            markdown_lines.append(f"{indent}</li>")
        if not root:
            markdown_lines.append(f"{'  ' * level}</{tag}>")

    render_level(None, 0, root=True)
    markdown_lines.append(f"</{tag}>")
    return "\n".join(markdown_lines), "\n".join(text_lines)


def _public_bbox(value: tuple[float, float, float, float]) -> dict[str, Any]:
    return {
        "x": round(value[0], 3),
        "y": round(value[1], 3),
        "width": round(value[2], 3),
        "height": round(value[3], 3),
        "unit": "pt",
    }


def _materialize_group(
    ir: DocumentIR,
    group: _GroupPlan,
    closure: _CanonicalClosure,
    predecessor: Any,
    *,
    deadline_check: Callable[[], None] | None = None,
) -> None:
    def charge() -> None:
        if deadline_check is not None:
            deadline_check()

    charge()
    predecessor_blocks = {
        block.primary_element_id: block
        for page_value in predecessor.pages
        for block in page_value.blocks
        if block.omission_reason is None
    }
    for continuation in group.continuations:
        charge()
        block = predecessor_blocks.get(continuation.element_id)
        if block is None:
            raise _PageProjectionError(
                "outline continuation canonical source is unavailable"
            )
        if block.markdown != block.markdown.strip() or block.text != block.text.strip():
            raise _PageProjectionError("outline continuation has outer whitespace")
        try:
            _validate_continuation_markdown(block.markdown)
        except ValueError as exc:
            raise _PageProjectionError(str(exc)) from exc

    elements = {value.id: value for value in ir.elements}
    anchor = elements[group.anchor_element_id]
    anchor_legacy = _legacy_item(anchor)
    if anchor_legacy is None or anchor_legacy.get("id") != group.anchor_public_item_id:
        raise _PageProjectionError("outline public anchor is unavailable")
    page = next(value for value in ir.pages if value.id == group.page_id)
    region_matches = [
        value
        for value in ir.regions
        if value.page_id == page.id and group.anchor_element_id in value.element_ids
    ]
    if len(region_matches) != 1:
        raise _PageProjectionError("outline anchor has no unique region")
    group_bbox = IRBoundingBox(
        id=group.bbox_id,
        coordinate_system_id=group.coordinate_system_id,
        x=round(group.bbox[0], 3),
        y=round(group.bbox[1], 3),
        width=round(group.bbox[2], 3),
        height=round(group.bbox[3], 3),
        role="region",
    )
    ir.bboxes.append(group_bbox)
    ir.evidence.append(
        EvidenceRecord(
            id=group.evidence_id,
            element_id=group.element_id,
            method=EvidenceMethod.DERIVED,
            bbox_id=group.bbox_id,
            value={"policy_id": POLICY_ID, "group_id": group.id},
            confidence=ConfidenceRecord(
                scope="evidence",
                unavailable_reason="not_calibrated",
            ),
            metadata={
                "derivation": "validated_outline_group_union",
                "policy_id": POLICY_ID,
                "group_id": group.id,
                "source_element_id": group.anchor_element_id,
            },
        )
    )
    incident: dict[str, list[str]] = {
        value.matched.target.element_id: [] for value in group.nodes
    }
    for relationship in group.relationships:
        charge()
        for endpoint in (relationship.source_id, relationship.target_id):
            if endpoint in incident:
                incident[endpoint].append(relationship.id)
    for node in group.nodes:
        charge()
        element = elements[node.matched.target.element_id]
        marker = node.matched.marker
        marker_bbox = IRBoundingBox(
            id=node.marker_bbox_id,
            coordinate_system_id=group.coordinate_system_id,
            x=marker.bbox.x,
            y=marker.bbox.y,
            width=marker.bbox.width,
            height=marker.bbox.height,
            role="annotation",
        )
        marker_evidence = EvidenceRecord(
            id=node.marker_evidence_id,
            element_id=element.id,
            method=EvidenceMethod.NATIVE,
            bbox_id=node.marker_bbox_id,
            value=marker.raw_marker,
            confidence=ConfidenceRecord(
                scope="evidence",
                unavailable_reason="not_calibrated",
            ),
            metadata={
                "policy_id": POLICY_ID,
                "group_id": group.id,
                "item_id": node.item_id,
                "reader": "pdfplumber",
                "page_index": group.page_index,
                "word_index": marker.source_object.word_index,
            },
        )
        ir.bboxes.append(marker_bbox)
        ir.evidence.append(marker_evidence)
        element.bbox_ids.append(node.marker_bbox_id)
        element.evidence_ids.append(node.marker_evidence_id)
        element.outline_item = OutlineItemSemanticDescriptor(
            policy_id=POLICY_ID,
            role="item",
            record_id=node.item_id,
            group_element_id=group.element_id,
            public_anchor_element_id=group.anchor_element_id,
            source_public_item_id=node.matched.target.public_item_id,
            source_public_path=list(node.matched.target.public_path),
            sequence_kind=group.sequence_kind,
            marker_style=group.marker_style,
            raw_marker=marker.raw_marker,
            marker_ownership=node.matched.marker_ownership,
            marker_separator=node.matched.marker_separator,
            body_text=node.matched.body_text,
            level=node.level,
            ordinal=node.ordinal,
            parent_element_id=node.parent_element_id,
            marker_bbox_id=node.marker_bbox_id,
            marker_evidence_id=node.marker_evidence_id,
            relationship_ids=incident[element.id],
        )
    group_descriptor = OutlineGroupSemanticDescriptor(
        policy_id=POLICY_ID,
        role="group",
        record_id=group.id,
        sequence_kind=group.sequence_kind,
        marker_style=group.marker_style,
        anchor_element_id=group.anchor_element_id,
        anchor_public_item_id=group.anchor_public_item_id,
        member_item_ids=[value.item_id for value in group.nodes],
        member_element_ids=[value.matched.target.element_id for value in group.nodes],
        continuation_element_ids=[value.element_id for value in group.continuations],
        relationship_ids=[value.id for value in group.relationships],
        canonical_contributor_element_ids=list(closure.contributing_element_ids),
        canonical_relationship_ids=list(closure.relationship_ids),
    )
    group_element = ElementRecord(
        id=group.element_id,
        page_id=group.page_id,
        type="outline_group",
        reading_order=None,
        value=None,
        markdown=None,
        bbox_ids=[group.bbox_id],
        evidence_ids=[group.evidence_id],
        outline_group=group_descriptor,
        presentation_role="subordinate",
        presentation=ElementPresentationDirective(),
        properties={
            "outline_policy": POLICY_ID,
            "public_anchor_element_id": group.anchor_element_id,
        },
    )
    ir.elements.append(group_element)
    page.element_ids.append(group.element_id)
    region_matches[0].element_ids.append(group.element_id)
    for value in group.relationships:
        charge()
        ir.relationships.append(
            RelationshipRecord(
                id=value.id,
                type=value.type,
                source_id=value.source_id,
                target_id=value.target_id,
                evidence_ids=list(value.evidence_ids),
                metadata=dict(value.metadata),
            )
        )

    continuation_markdown = {
        value.element_id: predecessor_blocks[value.element_id].markdown
        for value in group.continuations
    }
    continuation_text = {
        value.element_id: predecessor_blocks[value.element_id].text
        for value in group.continuations
    }
    public_nodes = [
        {
            "id": value.item_id,
            "raw_marker": value.matched.marker.raw_marker,
            "body_text": value.matched.body_text,
            "level": value.level,
            "ordinal": value.ordinal,
            "parent_id": value.parent_item_id,
        }
        for value in group.nodes
    ]
    public_continuation_render = [
        {
            "element_id": value.element_id,
            "target_node_id": value.target_item_id,
        }
        for value in group.continuations
    ]
    canonical_markdown, canonical_text = _render_outline(
        group_id=group.id,
        sequence_kind=group.sequence_kind,
        marker_style=group.marker_style,
        nodes=public_nodes,
        continuations=public_continuation_render,
        continuation_markdown=continuation_markdown,
        continuation_text=continuation_text,
        deadline_check=deadline_check,
    )
    relationship_descriptors: list[dict[str, Any]] = []
    for value in group.relationships:
        charge()
        descriptor = {
            "id": value.id,
            "type": value.type.value,
            "source_id": value.source_id,
            "target_id": value.target_id,
            "evidence_ids": list(value.evidence_ids),
            "canonical_inert": True,
            "outline_group_id": group.id,
            "outline_policy": POLICY_ID,
        }
        if value.type is RelationshipType.OUTLINE_NEXT:
            descriptor["intervening_element_ids"] = list(
                value.metadata["intervening_element_ids"]
            )
        elif value.type is RelationshipType.OUTLINE_CONTINUATION_OF:
            descriptor["interstitial_kind"] = "table"
        relationship_descriptors.append(descriptor)
    continuation_ids_by_target: dict[str, list[str]] = {}
    for value in group.continuations:
        charge()
        continuation_ids_by_target.setdefault(value.target_item_id, []).append(value.id)
    public_items = []
    for value in group.nodes:
        charge()
        source_element = elements[value.matched.target.element_id]
        public_items.append(
            PublicOutlineItem(
                id=value.item_id,
                element_id=source_element.id,
                source_public_item_id=value.matched.target.public_item_id,
                source_public_path=list(value.matched.target.public_path),
                source_bbox_id=value.matched.target.bbox_id,
                source_evidence_ids=list(value.matched.target.evidence_ids),
                source_object=PublicSourceObject(
                    reader="pdfplumber",
                    page_index=group.page_index,
                    word_index=value.matched.marker.source_object.word_index,
                ),
                sequence_kind=group.sequence_kind,
                marker_style=group.marker_style,
                raw_marker=value.matched.marker.raw_marker,
                marker_bbox=PublicBBox(
                    **_public_bbox(
                        (
                            value.matched.marker.bbox.x,
                            value.matched.marker.bbox.y,
                            value.matched.marker.bbox.width,
                            value.matched.marker.bbox.height,
                        )
                    )
                ),
                marker_ownership=value.matched.marker_ownership,
                marker_separator=value.matched.marker_separator,
                body_text=value.matched.body_text,
                predecessor_value_sha256=_sha256_text(value.matched.target.value),
                level=value.level,
                ordinal=value.ordinal,
                parent_id=value.parent_item_id,
                marker_bbox_id=value.marker_bbox_id,
                marker_evidence_id=value.marker_evidence_id,
                source_method="native",
                confidence=PublicConfidence(
                    scope="evidence",
                    score=None,
                    unavailable_reason="not_calibrated",
                ),
                concern_codes=[],
                relationship_ids=incident[source_element.id],
                continuation_ids=continuation_ids_by_target.get(value.item_id, []),
            )
        )
    public_continuations = [
        PublicOutlineContinuation(
            id=value.id,
            element_id=value.element_id,
            source_public_item_id=value.public_item_id,
            source_public_path=list(value.public_path),
            source_type="table",
            bbox_id=value.bbox_id,
            bbox=PublicBBox(**_public_bbox(value.bbox)),
            source_evidence_ids=list(value.evidence_ids),
            target_node_id=value.target_item_id,
            source_method="native",
            confidence=PublicConfidence(
                scope="evidence",
                score=None,
                unavailable_reason="not_calibrated",
            ),
            concern_codes=[],
            relationship_ids=[
                relationship.id
                for relationship in group.relationships
                if relationship.type is RelationshipType.OUTLINE_CONTINUATION_OF
                and relationship.source_id == value.element_id
            ],
        )
        for value in group.continuations
    ]
    cardinality = Counter(value.type.value for value in group.relationships)
    public_group = PublicOutlineGroup(
        id=group.id,
        element_id=group.element_id,
        page_id=group.page_id,
        sequence_kind=group.sequence_kind,
        marker_style=group.marker_style,
        anchor_public_item_id=group.anchor_public_item_id,
        anchor_element_id=group.anchor_element_id,
        anchor_public_path=list(group.anchor_public_path),
        group_bbox=PublicBBox(**_public_bbox(group.bbox)),
        member_item_ids=[value.item_id for value in group.nodes],
        member_element_ids=[value.matched.target.element_id for value in group.nodes],
        continuation_ids=[value.id for value in group.continuations],
        continuation_element_ids=[value.element_id for value in group.continuations],
        relationship_ids=[value.id for value in group.relationships],
        relationship_cardinality={
            key: cardinality[key]
            for key in (
                "contains",
                "outline_parent_of",
                "outline_next",
                "outline_continuation_of",
            )
        },
        canonical_block_id=closure.block_id,
        canonical_primary_element_id=closure.primary_element_id,
        canonical_contributor_element_ids=list(closure.contributing_element_ids),
        canonical_relationship_ids=list(closure.relationship_ids),
        canonical_markdown_sha256=_sha256_text(canonical_markdown),
        canonical_text_sha256=_sha256_text(canonical_text),
        source_method="native",
        confidence=PublicConfidence(
            scope="evidence",
            score=None,
            unavailable_reason="not_calibrated",
        ),
        concern_codes=list(group.concern_codes),
    )
    legacy = dict(anchor_legacy)
    legacy["layout_outline_structure_projected"] = True
    legacy["outline_policy"] = POLICY_ID
    legacy["outline_group"] = public_group.model_dump(mode="json")
    legacy["outline_items"] = [value.model_dump(mode="json") for value in public_items]
    legacy["outline_continuations"] = [
        value.model_dump(mode="json") for value in public_continuations
    ]
    prior_relationships = legacy.get("relationships")
    merged = list(prior_relationships) if isinstance(prior_relationships, list) else []
    merged.extend(relationship_descriptors)
    legacy["relationships"] = merged
    compact = {
        **{key: legacy[key] for key in _PUBLIC_OUTLINE_KEYS},
        "relationships": relationship_descriptors,
    }
    if len(_strict_json_bytes(compact)) > MAX_PUBLIC_GROUP_BYTES:
        raise _PageProjectionError("outline public group byte limit exceeded")
    anchor.properties["legacy_item"] = legacy


def _append_outline_concern(
    ir: DocumentIR,
    code: str,
    *,
    source_ref: str | None = None,
) -> None:
    if code not in _ALLOWED_CONCERNS:
        code = "outline_projection_failed_closed"
    if any(
        value.code == code and value.source_ref == source_ref for value in ir.concerns
    ):
        return
    outline_concerns = [
        value for value in ir.concerns if value.code in _ALLOWED_CONCERNS
    ]
    page_count = sum(value.source_ref == source_ref for value in outline_concerns)
    if len(outline_concerns) >= MAX_CONCERNS_PER_DOCUMENT or (
        source_ref is not None and page_count >= MAX_CONCERNS_PER_PAGE
    ):
        if not any(value.code == "outline_concerns_truncated" for value in ir.concerns):
            ir.concerns.append(
                IRConcern(
                    code="outline_concerns_truncated",
                    message="Additional outline concerns were suppressed.",
                )
            )
        return
    ir.concerns.append(
        IRConcern(
            code=code,
            message="Outline structure projection failed closed.",
            source_ref=source_ref,
        )
    )


def _with_outline_concern(ir: DocumentIR, code: str) -> DocumentIR:
    restored = ir.model_copy(deep=True)
    _append_outline_concern(restored, code)
    return DocumentIR.model_validate(restored.model_dump(mode="json"))


def _validate_projected_canonical_custody(
    ir: DocumentIR,
    presentation: Any,
) -> None:
    elements = {value.id: value for value in ir.elements}
    blocks = [
        block
        for page in presentation.pages
        for block in page.blocks
        if block.omission_reason is None
    ]
    bound_block_ids: list[str] = []
    groups = [value for value in ir.elements if value.outline_group is not None]
    for group_element in groups:
        descriptor = group_element.outline_group
        assert descriptor is not None
        anchor = elements[descriptor.anchor_element_id]
        legacy = _legacy_item(anchor)
        if legacy is None:
            raise ValueError("outline canonical anchor sidecar is unavailable")
        public_group = PublicOutlineGroup.model_validate(legacy.get("outline_group"))
        matching = [
            value for value in blocks if value.id == public_group.canonical_block_id
        ]
        if len(matching) != 1:
            raise ValueError("outline canonical block binding is not exact")
        [block] = matching
        if (
            block.page_id != public_group.page_id
            or block.primary_element_id != public_group.canonical_primary_element_id
            or block.contributing_element_ids
            != public_group.canonical_contributor_element_ids
            or block.relationship_ids != public_group.canonical_relationship_ids
            or _sha256_text(block.markdown) != public_group.canonical_markdown_sha256
            or _sha256_text(block.text) != public_group.canonical_text_sha256
        ):
            raise ValueError("outline canonical replacement custody differs")
        bound_block_ids.append(block.id)
    if len(bound_block_ids) != len(set(bound_block_ids)):
        raise ValueError("outline canonical block is shared by groups")


def _detach_projection_page(
    ir: DocumentIR,
    plans: Sequence[_GroupPlan],
) -> DocumentIR:
    """Copy exactly the append-only containers and page records US07 mutates."""

    page_ids = {value.page_id for value in plans}
    element_ids = {value.anchor_element_id for value in plans} | {
        node.matched.target.element_id for value in plans for node in value.nodes
    }
    detached = ir.model_copy(deep=False)
    detached.bboxes = list(ir.bboxes)
    detached.evidence = list(ir.evidence)
    detached.relationships = list(ir.relationships)
    detached.elements = [
        value.model_copy(deep=True) if value.id in element_ids else value
        for value in ir.elements
    ]
    detached.pages = [
        value.model_copy(deep=True) if value.id in page_ids else value
        for value in ir.pages
    ]
    detached.regions = [
        value.model_copy(deep=True) if value.page_id in page_ids else value
        for value in ir.regions
    ]
    detached.concerns = list(ir.concerns)
    return detached


def project_outline_structure(
    ir: DocumentIR,
    evidence: OutlineEvidenceReport | None,
    metrics: MutableMapping[str, Any] | None = None,
) -> DocumentIR:
    """Project the complete US07 stage atomically, with page-local refusal."""

    started = time.perf_counter()
    extraction_ms = _bounded_timing(
        (metrics or {}).get("extraction_ms", 0.0) if metrics is not None else 0.0
    )
    if extraction_ms == 0.0 and isinstance(evidence, OutlineEvidenceReport):
        extraction_ms = _bounded_timing(evidence.extraction_ms)
    predecessor = ir

    def finish(
        result: DocumentIR,
        *,
        status: str,
        reason: str | None = None,
    ) -> DocumentIR:
        if metrics is not None:
            metrics.update(
                {
                    "extraction_ms": extraction_ms,
                    "projection_ms": round(
                        max(time.perf_counter() - started, 0.0) * 1000.0,
                        3,
                    ),
                    "status": status,
                    "reason": reason,
                    "group_count": sum(
                        value.outline_group is not None for value in result.elements
                    ),
                    "node_count": sum(
                        value.outline_item is not None for value in result.elements
                    ),
                    "relationship_count": sum(
                        value.metadata.get("outline_policy") == POLICY_ID
                        for value in result.relationships
                    ),
                    "concern_count": sum(
                        value.code in _ALLOWED_CONCERNS for value in result.concerns
                    ),
                }
            )
        return result

    if any(
        value.outline_group is not None or value.outline_item is not None
        for value in predecessor.elements
    ):
        return finish(predecessor.model_copy(deep=True), status="projected")
    if evidence is None or not isinstance(evidence, OutlineEvidenceReport):
        return finish(
            _with_outline_concern(
                predecessor,
                "outline_source_evidence_unavailable",
            ),
            status="unavailable",
            reason="outline_source_evidence_unavailable",
        )
    if (
        evidence.report_version != REPORT_VERSION
        or evidence.policy_id != POLICY_ID
        or evidence.source_sha256 != predecessor.source_sha256
    ):
        return finish(
            _with_outline_concern(
                predecessor,
                "outline_source_evidence_unavailable",
            ),
            status="unavailable",
            reason="outline_source_evidence_unavailable",
        )
    try:
        _validate_source_report(
            evidence,
            expected_source_sha256=predecessor.source_sha256,
        )
    except Exception:
        return finish(
            _with_outline_concern(
                predecessor,
                "outline_projection_failed_closed",
            ),
            status="failed_closed",
            reason="outline_projection_failed_closed",
        )
    if evidence.status != "available":
        reason = (
            "outline_source_limit"
            if "outline_source_limit" in evidence.concern_codes
            else "outline_source_evidence_unavailable"
        )
        return finish(
            _with_outline_concern(predecessor, reason),
            status="unavailable",
            reason=reason,
        )
    try:
        if len(_strict_json_bytes(_report_payload(evidence))) > MAX_REPORT_BYTES:
            raise _DocumentProjectionError("outline report byte limit exceeded")
        from app.services.presentation import (
            _build_canonical_presentation_from_validated,
            build_canonical_presentation,
        )

        canonical_predecessor = build_canonical_presentation(predecessor)
        if time.perf_counter() - started > PROJECTION_DOCUMENT_DEADLINE_SECONDS:
            raise _DocumentProjectionError("outline document deadline exceeded")
        working = predecessor
        form_owned = _form_owned_element_ids(predecessor)
        document_group_count = 0
        document_node_count = 0
        document_relationship_count = 0

        def add_page_concern(page_index: int, code: str) -> None:
            nonlocal working
            if working is predecessor:
                working = predecessor.model_copy(deep=True)
            _append_outline_concern(
                working,
                code,
                source_ref=f"page:{page_index}",
            )

        for source_page in evidence.pages:
            page_index = source_page.page_index
            page_started = time.perf_counter()

            def check_page_deadline() -> None:
                _check_projection_deadlines(
                    started_at=started,
                    page_started_at=page_started,
                )

            if source_page.concern_codes:
                add_page_concern(
                    page_index,
                    source_page.concern_codes[0],
                )
                continue
            try:
                check_page_deadline()
                matched, page_rejections = _match_markers(
                    predecessor,
                    evidence,
                    started_at=started,
                    metrics=metrics,
                    page_indexes=frozenset({page_index}),
                    page_started_at=page_started,
                )
                page_plans = list(
                    _build_group_plans(
                        predecessor,
                        matched,
                        deadline_check=check_page_deadline,
                    )
                )
                if not page_plans:
                    for code in sorted(page_rejections.get(page_index, set())):
                        add_page_concern(page_index, code)
                    check_page_deadline()
                    continue
                page_group_count = len(page_plans)
                page_node_count = sum(len(value.nodes) for value in page_plans)
                page_relationship_count = sum(
                    len(value.relationships) for value in page_plans
                )
                document_group_count += page_group_count
                document_node_count += page_node_count
                document_relationship_count += page_relationship_count
                if (
                    document_group_count > MAX_GROUPS_PER_DOCUMENT
                    or document_node_count > MAX_NODES_PER_DOCUMENT
                ):
                    raise _DocumentProjectionError("outline candidate limit exceeded")
                if document_relationship_count > MAX_RELATIONSHIPS_PER_DOCUMENT:
                    raise _DocumentProjectionError(
                        "outline relationship limit exceeded"
                    )
                if (
                    page_group_count > MAX_GROUPS_PER_PAGE
                    or page_node_count > MAX_NODES_PER_PAGE
                    or page_relationship_count > MAX_RELATIONSHIPS_PER_PAGE
                ):
                    add_page_concern(
                        page_index,
                        (
                            "outline_relationship_limit"
                            if page_relationship_count > MAX_RELATIONSHIPS_PER_PAGE
                            else "outline_candidate_limit"
                        ),
                    )
                    continue
                check_page_deadline()
                page_candidate = _detach_projection_page(
                    working,
                    page_plans,
                )
                check_page_deadline()
                for plan in page_plans:
                    check_page_deadline()
                    closure = _canonical_closure(
                        plan,
                        canonical_predecessor,
                        form_owned_element_ids=form_owned,
                        deadline_check=check_page_deadline,
                    )
                    _materialize_group(
                        page_candidate,
                        plan,
                        closure,
                        canonical_predecessor,
                        deadline_check=check_page_deadline,
                    )
                check_page_deadline()
                page_validated = DocumentIR.model_validate(
                    page_candidate.model_dump(mode="json")
                )
                # Full-IR schema validation is document-wide work. Charging
                # scheduler delay during it to the 250 ms page budget can roll
                # back an otherwise complete page under aggregate test/server
                # load; the 2 s document deadline still bounds the operation.
                _check_projection_document_deadline(started_at=started)
                working = page_validated
            except _DocumentProjectionError:
                raise
            except Exception:
                add_page_concern(
                    page_index,
                    "outline_projection_failed_closed",
                )
        projected = working
        if time.perf_counter() - started > PROJECTION_DOCUMENT_DEADLINE_SECONDS:
            raise _DocumentProjectionError("outline document deadline exceeded")
        committed_group_count = sum(
            value.outline_group is not None for value in projected.elements
        )
        if committed_group_count == 0:
            validated = DocumentIR.model_validate(projected.model_dump(mode="json"))
            if time.perf_counter() - started > PROJECTION_DOCUMENT_DEADLINE_SECONDS:
                raise _DocumentProjectionError("outline document deadline exceeded")
            return finish(validated, status="no_candidates")
        try:
            canonical_result = _build_canonical_presentation_from_validated(projected)
            _validate_projected_canonical_custody(
                projected,
                canonical_result,
            )
        except Exception:
            return finish(
                _with_outline_concern(
                    predecessor,
                    "outline_canonical_custody_invalid",
                ),
                status="failed_closed",
                reason="outline_canonical_custody_invalid",
            )
        if time.perf_counter() - started > PROJECTION_DOCUMENT_DEADLINE_SECONDS:
            raise _DocumentProjectionError("outline document deadline exceeded")
        return finish(projected, status="projected")
    except Exception:
        return finish(
            _with_outline_concern(
                predecessor,
                "outline_projection_failed_closed",
            ),
            status="failed_closed",
            reason="outline_projection_failed_closed",
        )


def _relationship_descriptor(value: Mapping[str, Any]) -> bool:
    relationship_type = value.get("type")
    keys = {
        "id",
        "type",
        "source_id",
        "target_id",
        "evidence_ids",
        "canonical_inert",
        "outline_group_id",
        "outline_policy",
    }
    if relationship_type == "outline_next":
        keys.add("intervening_element_ids")
    elif relationship_type == "outline_continuation_of":
        keys.add("interstitial_kind")
    elif relationship_type not in {"contains", "outline_parent_of"}:
        return False
    return (
        set(value) == keys
        and value.get("canonical_inert") is True
        and value.get("outline_policy") == POLICY_ID
        and (
            relationship_type != "outline_continuation_of"
            or value.get("interstitial_kind") == "table"
        )
    )


def _path_value(document: Mapping[str, Any], path: Sequence[str | int]) -> Any:
    current: Any = document
    for part in path:
        if isinstance(part, bool):
            raise ValueError("outline public path contains a boolean")
        current = current[part]
    return current


def _legacy_bbox_tuple(value: Mapping[str, Any]) -> tuple[float, float, float, float]:
    raw = value.get("bbox")
    if not isinstance(raw, Mapping) or raw.get("unit") != "pt":
        raise ValueError("outline public source bbox differs")
    try:
        box = tuple(float(raw[key]) for key in ("x", "y", "width", "height"))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("outline public source bbox differs") from exc
    if (
        any(not math.isfinite(part) for part in box)
        or box[0] < 0
        or box[1] < 0
        or box[2] <= 0
        or box[3] <= 0
    ):
        raise ValueError("outline public source bbox differs")
    return box  # type: ignore[return-value]


def _public_bbox_tuple(value: PublicBBox) -> tuple[float, float, float, float]:
    return (value.x, value.y, value.width, value.height)


def _same_bbox(
    first: Sequence[float],
    second: Sequence[float],
) -> bool:
    return all(
        math.isclose(left, right, rel_tol=0.0, abs_tol=0.001)
        for left, right in zip(first, second, strict=True)
    )


def _validate_public_anchor(
    document: Mapping[str, Any],
    anchor: Mapping[str, Any],
    canonical_block: Mapping[str, Any],
) -> tuple[PublicOutlineGroup, list[Mapping[str, Any]]]:
    if anchor.get("layout_outline_structure_projected") is not True or (
        anchor.get("outline_policy") != POLICY_ID
    ):
        raise ValueError("outline public marker differs")
    group = PublicOutlineGroup.model_validate(anchor.get("outline_group"))
    raw_items = anchor.get("outline_items")
    raw_continuations = anchor.get("outline_continuations")
    raw_relationships = anchor.get("relationships")
    if (
        not isinstance(raw_items, list)
        or not isinstance(raw_continuations, list)
        or (not isinstance(raw_relationships, list))
    ):
        raise ValueError("outline public sidecar is incomplete")
    items = [PublicOutlineItem.model_validate(value) for value in raw_items]
    continuations = [
        PublicOutlineContinuation.model_validate(value) for value in raw_continuations
    ]
    relationships = [
        value
        for value in raw_relationships
        if isinstance(value, Mapping) and value.get("outline_policy") == POLICY_ID
    ]
    if any(not _relationship_descriptor(value) for value in relationships):
        raise ValueError("outline relationship descriptor differs")
    if [value.get("id") for value in relationships] != group.relationship_ids:
        raise ValueError("outline relationship order differs")
    if [value.id for value in items] != group.member_item_ids or (
        [value.element_id for value in items] != group.member_element_ids
    ):
        raise ValueError("outline public member order differs")
    if [value.id for value in continuations] != group.continuation_ids or (
        [value.element_id for value in continuations] != group.continuation_element_ids
    ):
        raise ValueError("outline public continuation order differs")
    if (
        len({value.id for value in items}) != len(items)
        or len({value.element_id for value in items}) != len(items)
        or len({value.id for value in continuations}) != len(continuations)
        or len({value.element_id for value in continuations}) != len(continuations)
        or any(
            value.sequence_kind != group.sequence_kind
            or value.marker_style != group.marker_style
            for value in items
        )
        or (group.sequence_kind == "unordered") != (group.marker_style == "bullet")
    ):
        raise ValueError("outline public group membership differs")
    expected_group_id = _stable_id(
        "outline-group",
        POLICY_ID,
        str(
            (document.get("document") or {}).get("sha256")
            if isinstance(document.get("document"), Mapping)
            else ""
        ),
        items[0].source_object.page_index,
        group.anchor_element_id,
        tuple(group.member_element_ids),
        tuple(group.continuation_element_ids),
    )
    if (
        group.id != expected_group_id
        or group.element_id != _stable_id("outline-element", group.id)
        or not group.canonical_contributor_element_ids
        or group.canonical_contributor_element_ids[0] != group.anchor_element_id
        or not {
            group.anchor_element_id,
            *group.member_element_ids,
            *group.continuation_element_ids,
        }.issubset(set(group.canonical_contributor_element_ids))
        or not set(group.relationship_ids).issubset(group.canonical_relationship_ids)
    ):
        raise ValueError("outline public group stable custody differs")
    if _path_value(document, group.anchor_public_path) is not anchor or (
        group.anchor_public_item_id != anchor.get("id")
    ):
        raise ValueError("outline public anchor path differs")
    anchor_page = _path_value(document, group.anchor_public_path[:2])
    if not isinstance(anchor_page, Mapping):
        raise ValueError("outline public anchor page differs")
    anchor_page_index = anchor_page.get("page_index")
    if (
        isinstance(anchor_page_index, bool)
        or not isinstance(anchor_page_index, int)
        or anchor_page_index < 1
    ):
        raise ValueError("outline public anchor page differs")
    document_record = document.get("document")
    source_sha256 = (
        document_record.get("sha256") if isinstance(document_record, Mapping) else None
    )
    if (
        not isinstance(source_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None
    ):
        raise ValueError("outline document source identity differs")
    expected_document_id = _stable_id("doc", source_sha256)
    expected_page_id = _stable_id(
        "page",
        expected_document_id,
        anchor_page_index,
    )
    if (
        group.page_id != expected_page_id
        or canonical_block.get("page_id") != expected_page_id
        or group.anchor_element_id != canonical_block.get("primary_element_id")
    ):
        raise ValueError("outline anchor internal page binding differs")
    item_ids = {value.id for value in items}
    by_parent: dict[str | None, list[PublicOutlineItem]] = {}
    source_boxes: list[tuple[float, float, float, float]] = []
    all_source_evidence_ids: list[str] = []
    marker_evidence_ids: list[str] = []
    for item in items:
        source = _path_value(document, item.source_public_path)
        if not isinstance(source, Mapping):
            raise ValueError("outline source path is not an item")
        source_page = _path_value(document, item.source_public_path[:2])
        if (
            not isinstance(source_page, Mapping)
            or source_page.get("page_index") != anchor_page_index
            or item.source_object.page_index != anchor_page_index
        ):
            raise ValueError("outline source page binding differs")
        if item.source_public_item_id != (
            source.get("id") if len(item.source_public_path) == 4 else anchor.get("id")
        ):
            raise ValueError("outline source public ID differs")
        if group.sequence_kind == "legal" and len(item.source_public_path) != 4:
            raise ValueError("legal outline requires top-level source items")
        source_bbox = _legacy_bbox_tuple(source)
        marker_bbox = _public_bbox_tuple(item.marker_bbox)
        vertical_overlap = min(
            marker_bbox[1] + marker_bbox[3],
            source_bbox[1] + source_bbox[3],
        ) - max(marker_bbox[1], source_bbox[1])
        if not (
            marker_bbox[0] >= source_bbox[0] - 1.0
            and marker_bbox[0] + marker_bbox[2] <= source_bbox[0] + source_bbox[2] + 1.0
            and vertical_overlap >= 0.5 * min(marker_bbox[3], source_bbox[3])
        ):
            raise ValueError("outline public marker bbox differs from source")
        source_boxes.append(source_bbox)
        all_source_evidence_ids.extend(item.source_evidence_ids)
        marker_evidence_ids.append(item.marker_evidence_id)
        expected_item_id = _stable_id(
            "outline-item",
            group.id,
            item.element_id,
        )
        expected_marker_id = _stable_id(
            "outline-evidence",
            group.id,
            item.element_id,
            "marker",
            item.source_object.word_index,
        )
        if (
            item.id != expected_item_id
            or item.marker_evidence_id != expected_marker_id
            or item.marker_bbox_id
            != _stable_id(
                "outline-bbox",
                group.id,
                item.element_id,
                "marker",
                item.source_object.word_index,
            )
        ):
            raise ValueError("outline public item stable ID differs")
        value = source.get("value")
        expected = (
            item.body_text
            if item.marker_ownership == "separate"
            else item.raw_marker + item.marker_separator + item.body_text
        )
        if value != expected or item.predecessor_value_sha256 != _sha256_text(expected):
            raise ValueError("outline source value binding differs")
        parsed_marker = _marker_kind(item.raw_marker)
        if (
            source.get("source") != "native"
            or parsed_marker is None
            or parsed_marker[0] != item.marker_style
            or (item.marker_style != "bullet" and parsed_marker[1] != item.ordinal)
        ):
            raise ValueError("outline public marker syntax differs")
        if item.parent_id is not None and item.parent_id not in item_ids:
            raise ValueError("outline public parent is unavailable")
        by_parent.setdefault(item.parent_id, []).append(item)
    minimum_root_count = 3 if group.sequence_kind == "legal" else 2
    if len(by_parent.get(None, [])) < minimum_root_count or any(
        value.level != 0 for value in by_parent.get(None, [])
    ):
        raise ValueError("outline public roots are incomplete")
    stack: list[PublicOutlineItem] = []
    for item in items:
        if item.level > len(stack):
            raise ValueError("outline public preorder skips a level")
        expected_parent = None if item.level == 0 else stack[item.level - 1].id
        if item.parent_id != expected_parent:
            raise ValueError("outline public parent stack differs")
        stack[item.level :] = [item]
    if (
        len({_marker_family(value.raw_marker, value.marker_style) for value in items})
        != 1
    ):
        raise ValueError("outline public marker family differs")
    for parent_id, siblings in by_parent.items():
        if [value.ordinal for value in siblings] != list(range(1, len(siblings) + 1)):
            raise ValueError("outline public sibling ordinals differ")
        if parent_id is not None:
            parent = next(value for value in items if value.id == parent_id)
            if any(value.level != parent.level + 1 for value in siblings):
                raise ValueError("outline public levels differ")

    item_by_id = {value.id: value for value in items}
    continuations_by_target: dict[str, list[PublicOutlineContinuation]] = {}
    for continuation in continuations:
        if continuation.target_node_id not in item_by_id:
            raise ValueError("outline continuation target differs")
        source = _path_value(document, continuation.source_public_path)
        source_page = _path_value(document, continuation.source_public_path[:2])
        if (
            not isinstance(source, Mapping)
            or not isinstance(source_page, Mapping)
            or source_page.get("page_index") != anchor_page_index
            or source.get("id") != continuation.source_public_item_id
            or str(source.get("type", "")).casefold() != "table"
        ):
            raise ValueError("outline continuation source binding differs")
        source_bbox = _legacy_bbox_tuple(source)
        if not _same_bbox(source_bbox, _public_bbox_tuple(continuation.bbox)):
            raise ValueError("outline continuation bbox binding differs")
        source_boxes.append(source_bbox)
        all_source_evidence_ids.extend(continuation.source_evidence_ids)
        if continuation.id != _stable_id(
            "outline-continuation",
            group.id,
            continuation.element_id,
            continuation.target_node_id,
        ):
            raise ValueError("outline continuation stable ID differs")
        continuations_by_target.setdefault(
            continuation.target_node_id,
            [],
        ).append(continuation)

    if (
        len(marker_evidence_ids) != len(set(marker_evidence_ids))
        or len(all_source_evidence_ids) != len(set(all_source_evidence_ids))
        or set(marker_evidence_ids) & set(all_source_evidence_ids)
    ):
        raise ValueError("outline public evidence custody differs")
    item_paths = [tuple(value.source_public_path) for value in items]
    continuation_paths = [tuple(value.source_public_path) for value in continuations]
    source_objects = [
        (value.source_object.page_index, value.source_object.word_index)
        for value in items
    ]
    if (
        len(item_paths) != len(set(item_paths))
        or len(continuation_paths) != len(set(continuation_paths))
        or set(item_paths) & set(continuation_paths)
        or len(source_objects) != len(set(source_objects))
    ):
        raise ValueError("outline public source identity repeats")
    expected_group_box = (
        min(value[0] for value in source_boxes),
        min(value[1] for value in source_boxes),
        max(value[0] + value[2] for value in source_boxes),
        max(value[1] + value[3] for value in source_boxes),
    )
    actual_group_box = _public_bbox_tuple(group.group_bbox)
    if not _same_bbox(
        (
            actual_group_box[0],
            actual_group_box[1],
            actual_group_box[0] + actual_group_box[2],
            actual_group_box[1] + actual_group_box[3],
        ),
        expected_group_box,
    ):
        raise ValueError("outline public group bbox differs from source union")

    expected_relationships: list[dict[str, Any]] = []

    def expected_relationship(
        relationship_type: str,
        source_id: str,
        target_id: str,
        evidence_ids: list[str],
        **metadata: Any,
    ) -> None:
        expected_relationships.append(
            {
                "id": _stable_id(
                    "outline-relationship",
                    POLICY_ID,
                    group.id,
                    relationship_type,
                    source_id,
                    target_id,
                ),
                "type": relationship_type,
                "source_id": source_id,
                "target_id": target_id,
                "evidence_ids": evidence_ids,
                "canonical_inert": True,
                "outline_group_id": group.id,
                "outline_policy": POLICY_ID,
                **metadata,
            }
        )

    group_evidence_id = _stable_id("outline-evidence", group.id, "group")
    for item in items:
        expected_relationship(
            "contains",
            group.element_id,
            item.element_id,
            [group_evidence_id, item.marker_evidence_id],
        )
    for item in items:
        if item.parent_id is None:
            continue
        parent = item_by_id[item.parent_id]
        expected_relationship(
            "outline_parent_of",
            parent.element_id,
            item.element_id,
            [parent.marker_evidence_id, item.marker_evidence_id],
        )
    for siblings in by_parent.values():
        for first, second in zip(siblings, siblings[1:], strict=False):
            expected_relationship(
                "outline_next",
                first.element_id,
                second.element_id,
                [first.marker_evidence_id, second.marker_evidence_id],
                intervening_element_ids=[
                    value.element_id
                    for value in continuations_by_target.get(first.id, [])
                ],
            )
    for continuation in continuations:
        target = item_by_id[continuation.target_node_id]
        expected_relationship(
            "outline_continuation_of",
            continuation.element_id,
            target.element_id,
            [*continuation.source_evidence_ids, target.marker_evidence_id],
            interstitial_kind="table",
        )
    if [dict(value) for value in relationships] != expected_relationships:
        raise ValueError("outline public relationship graph differs")
    referenced = Counter(
        relationship_id for value in items for relationship_id in value.relationship_ids
    )
    referenced.update(
        relationship_id
        for value in continuations
        for relationship_id in value.relationship_ids
    )
    expected = Counter()
    item_element_ids = {value.element_id for value in items}
    continuation_element_ids = {value.element_id for value in continuations}
    for relationship in relationships:
        for endpoint in (relationship["source_id"], relationship["target_id"]):
            if endpoint in item_element_ids or endpoint in continuation_element_ids:
                expected[relationship["id"]] += 1
    if referenced != expected:
        raise ValueError("outline public relationship backlinks differ")
    cardinality = Counter(str(value["type"]) for value in relationships)
    if group.relationship_cardinality != {
        key: cardinality[key]
        for key in (
            "contains",
            "outline_parent_of",
            "outline_next",
            "outline_continuation_of",
        )
    }:
        raise ValueError("outline public relationship cardinality differs")
    if (
        group.canonical_block_id != canonical_block.get("id")
        or group.canonical_primary_element_id
        != canonical_block.get("primary_element_id")
        or group.canonical_contributor_element_ids
        != canonical_block.get("contributing_element_ids")
        or group.canonical_relationship_ids != canonical_block.get("relationship_ids")
        or group.canonical_markdown_sha256
        != _sha256_text(str(canonical_block.get("markdown")))
        or group.canonical_text_sha256 != _sha256_text(str(canonical_block.get("text")))
    ):
        raise ValueError("outline canonical public binding differs")
    compact = {
        **{key: anchor[key] for key in _PUBLIC_OUTLINE_KEYS},
        "relationships": relationships,
    }
    if len(_strict_json_bytes(compact)) > MAX_PUBLIC_GROUP_BYTES:
        raise ValueError("outline public group byte limit exceeded")
    return group, relationships


def strip_outline_structure_public(document: Mapping[str, Any]) -> dict[str, Any]:
    """Remove only complete, canonically bound US07 public sidecars."""

    cleaned = deepcopy(dict(document))
    canonical = cleaned.get("canonical_presentation")
    blocks = [
        block
        for page in (
            canonical.get("pages", []) if isinstance(canonical, Mapping) else []
        )
        if isinstance(page, Mapping)
        for block in page.get("blocks", [])
        if isinstance(block, Mapping)
    ]
    pages = cleaned.get("pages")
    if not isinstance(pages, list):
        return cleaned
    for page in pages:
        if not isinstance(page, Mapping):
            continue
        items = page.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            raw_group = item.get("outline_group")
            if not isinstance(raw_group, Mapping):
                continue
            matching = [
                value
                for value in blocks
                if value.get("id") == raw_group.get("canonical_block_id")
                and value.get("primary_element_id")
                == raw_group.get("canonical_primary_element_id")
            ]
            if len(matching) != 1:
                continue
            try:
                _group, story = _validate_public_anchor(cleaned, item, matching[0])
            except Exception:
                continue
            story_ids = {str(value["id"]) for value in story}
            for key in _PUBLIC_OUTLINE_KEYS:
                item.pop(key, None)
            relationships = item.get("relationships")
            if isinstance(relationships, list):
                retained = [
                    value
                    for value in relationships
                    if not (
                        isinstance(value, Mapping)
                        and value.get("outline_policy") == POLICY_ID
                        and value.get("id") in story_ids
                    )
                ]
                if retained:
                    item["relationships"] = retained
                else:
                    item.pop("relationships", None)
    return cleaned


def render_outline_group_semantics(
    anchor: ElementRecord,
    *,
    elements_by_id: Mapping[str, ElementRecord],
    predecessor: Any,
) -> OutlineGroupRendering | None:
    """Resolve one complete sidecar against live IR and predecessor custody."""

    legacy = _legacy_item(anchor)
    if legacy is None or legacy.get("layout_outline_structure_projected") is not True:
        return None
    try:
        group = PublicOutlineGroup.model_validate(legacy.get("outline_group"))
        if group.anchor_element_id != anchor.id:
            return None
        group_element = elements_by_id.get(group.element_id)
        if group_element is None or group_element.outline_group is None:
            return None
        descriptor = group_element.outline_group
        if (
            descriptor.record_id != group.id
            or descriptor.member_item_ids != group.member_item_ids
            or descriptor.member_element_ids != group.member_element_ids
            or descriptor.continuation_element_ids != group.continuation_element_ids
            or descriptor.relationship_ids != group.relationship_ids
            or descriptor.canonical_contributor_element_ids
            != group.canonical_contributor_element_ids
            or descriptor.canonical_relationship_ids != group.canonical_relationship_ids
        ):
            return None
        raw_items = legacy.get("outline_items")
        raw_continuations = legacy.get("outline_continuations")
        if not isinstance(raw_items, list) or not isinstance(raw_continuations, list):
            return None
        items = [PublicOutlineItem.model_validate(value) for value in raw_items]
        continuations = [
            PublicOutlineContinuation.model_validate(value)
            for value in raw_continuations
        ]
        for public_item in items:
            element = elements_by_id.get(public_item.element_id)
            if element is None or element.outline_item is None:
                return None
            item_descriptor = element.outline_item
            if (
                item_descriptor.record_id != public_item.id
                or item_descriptor.group_element_id != group.element_id
                or item_descriptor.raw_marker != public_item.raw_marker
                or item_descriptor.body_text != public_item.body_text
                or item_descriptor.level != public_item.level
                or item_descriptor.ordinal != public_item.ordinal
            ):
                return None
        plan_nodes = [
            {
                "id": value.id,
                "raw_marker": value.raw_marker,
                "body_text": value.body_text,
                "level": value.level,
                "ordinal": value.ordinal,
                "parent_id": value.parent_id,
            }
            for value in items
        ]
        predecessor_blocks = {
            block.primary_element_id: block
            for page in predecessor.pages
            for block in page.blocks
            if block.omission_reason is None
        }
        continuation_markdown = {
            value.element_id: predecessor_blocks[value.element_id].markdown
            for value in continuations
        }
        continuation_text = {
            value.element_id: predecessor_blocks[value.element_id].text
            for value in continuations
        }
        markdown, text = _render_outline(
            group_id=group.id,
            sequence_kind=group.sequence_kind,
            marker_style=group.marker_style,
            nodes=plan_nodes,
            continuations=[
                {
                    "element_id": value.element_id,
                    "target_node_id": value.target_node_id,
                }
                for value in continuations
            ],
            continuation_markdown=continuation_markdown,
            continuation_text=continuation_text,
        )
        if (
            _sha256_text(markdown) != group.canonical_markdown_sha256
            or _sha256_text(text) != group.canonical_text_sha256
        ):
            return None
        target_ids = {
            anchor.id,
            *group.member_element_ids,
            *group.continuation_element_ids,
        }
        owners: dict[str, list[Any]] = {value: [] for value in target_ids}
        for block in predecessor_blocks.values():
            for contributor in block.contributing_element_ids:
                if contributor in owners:
                    owners[contributor].append(block)
        if any(len(value) != 1 for value in owners.values()):
            return None
        selected_ids = {value[0].id for value in owners.values()}
        selected = [
            block
            for page in predecessor.pages
            for block in page.blocks
            if block.id in selected_ids and block.omission_reason is None
        ]
        anchor_blocks = [
            value for value in selected if value.primary_element_id == anchor.id
        ]
        if len(anchor_blocks) != 1 or anchor_blocks[0].scope != "body":
            return None
        contributors: list[str] = []
        predecessor_primary_ids: list[str] = []
        relationship_ids: set[str] = set(group.relationship_ids)
        for block in selected:
            predecessor_primary_ids.append(block.primary_element_id)
            for value in block.contributing_element_ids:
                if value not in contributors:
                    contributors.append(value)
            relationship_ids.update(block.relationship_ids)
        if anchor.id in contributors:
            contributors.remove(anchor.id)
        contributors.insert(0, anchor.id)
        if contributors != group.canonical_contributor_element_ids or (
            sorted(relationship_ids) != group.canonical_relationship_ids
        ):
            return None
        return OutlineGroupRendering(
            group_element_id=group.element_id,
            anchor_element_id=anchor.id,
            predecessor_primary_ids=tuple(predecessor_primary_ids),
            contributor_element_ids=tuple(contributors),
            relationship_ids=tuple(sorted(relationship_ids)),
            markdown=markdown,
            text=text,
        )
    except Exception:
        return None


__all__ = [
    "OutlineEvidenceReport",
    "OutlineGroupRendering",
    "OutlineSourceBBox",
    "OutlineSourceCounts",
    "OutlineSourceMarker",
    "OutlineSourceObject",
    "OutlineSourcePage",
    "extract_outline_evidence",
    "outline_processing_summary",
    "project_outline_structure",
    "render_outline_group_semantics",
    "strip_outline_structure_public",
]
