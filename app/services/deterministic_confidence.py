"""Conservative categorical confidence for deterministic parser output.

The release contract deliberately exposes rule outcomes rather than numeric
scores.  These values are not probabilities and do not represent a fitted or
statistically calibrated estimate.  Each dimension inspects only its own
bounded structural signals so an OCR engine confidence can never become
layout or table-structure confidence.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import ContentItem, ParseResult, TableCandidateGate


_MAX_ITEMS = 65_536
_MAX_CONCERNS_PER_ITEM = 64
_MAX_REASON_CODES = 8
_MAX_SIDECAR_BYTES = 4_096

_TEXT_TYPES = frozenset(
    {
        "caption",
        "code",
        "footnote",
        "heading",
        "key_value",
        "list",
        "list_item",
        "paragraph",
        "section_header",
        "text",
        "title",
    }
)
_TEXT_CONCERN_TOKENS = frozenset(
    {
        "character",
        "font",
        "glyph",
        "hyphen",
        "lexical",
        "ocr",
        "source_alignment",
        "text",
    }
)
_LAYOUT_CONCERN_TOKENS = frozenset(
    {
        "bbox",
        "caption",
        "geometry",
        "layout",
        "outline",
        "page_identity",
        "reading_order",
        "relationship",
        "running_region",
    }
)
_TABLE_CONCERN_TOKENS = frozenset(
    {
        "cell",
        "column",
        "continuation",
        "grid",
        "header",
        "merge",
        "row",
        "span",
        "table",
    }
)

DimensionName = Literal["text", "layout", "table"]
ConfidenceLevel = Literal["supported", "guarded", "unsupported", "unavailable"]
ConfidenceDecision = Literal[
    "accept",
    "concern",
    "fallback",
    "withhold",
    "not_applicable",
]
ReasonCode = Literal[
    "complete_item_geometry",
    "explicit_concern_reported",
    "inspection_limit_exceeded",
    "item_geometry_missing",
    "layout_items_present",
    "layout_output_missing",
    "native_text_source",
    "no_table_output",
    "non_native_text_source",
    "output_warning_reported",
    "page_failure_reported",
    "reading_order_contiguous",
    "source_supported_table",
    "table_shape_contradictory",
    "table_structure_evidence_limited",
    "text_items_present",
    "text_output_missing",
]


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DeterministicConfidenceDimension(_ClosedModel):
    """One independent, categorical rule result."""

    dimension: DimensionName
    applicability: Literal["applicable", "not_applicable"]
    level: ConfidenceLevel
    decision: ConfidenceDecision
    reason_codes: tuple[ReasonCode, ...] = Field(
        min_length=1,
        max_length=_MAX_REASON_CODES,
    )

    @model_validator(mode="after")
    def validate_threshold_mapping(self) -> DeterministicConfidenceDimension:
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("confidence reason codes must be unique")
        expected = {
            "supported": "accept",
            "guarded": "concern",
            "unsupported": "fallback",
            "unavailable": "withhold",
        }[self.level]
        if self.applicability == "not_applicable":
            if (
                self.dimension != "table"
                or self.level != "unavailable"
                or self.decision != "not_applicable"
                or self.reason_codes != ("no_table_output",)
            ):
                raise ValueError("not-applicable confidence dimension differs")
        elif self.decision != expected:
            raise ValueError("confidence level/decision threshold differs")
        return self


class DeterministicConfidence(_ClosedModel):
    """Bounded root sidecar with fixed dimension order and semantics."""

    schema_version: Literal["1.0"] = "1.0"
    policy_id: Literal["p08-release-confidence-v1"] = (
        "p08-release-confidence-v1"
    )
    basis: Literal["deterministic_rules"] = "deterministic_rules"
    value_semantics: Literal["categorical_not_probability"] = (
        "categorical_not_probability"
    )
    dimensions: tuple[
        DeterministicConfidenceDimension,
        DeterministicConfidenceDimension,
        DeterministicConfidenceDimension,
    ]
    overall_decision: Literal["accept", "concern", "fallback", "withhold"]

    @model_validator(mode="after")
    def validate_dimension_order_and_size(self) -> DeterministicConfidence:
        if tuple(value.dimension for value in self.dimensions) != (
            "text",
            "layout",
            "table",
        ):
            raise ValueError("confidence dimensions must be text/layout/table")
        applicable = [
            value.decision
            for value in self.dimensions
            if value.decision != "not_applicable"
        ]
        expected = "accept"
        for decision in ("concern", "withhold", "fallback"):
            if decision in applicable:
                expected = decision
        if self.overall_decision != expected:
            raise ValueError("overall confidence decision differs")
        encoded = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > _MAX_SIDECAR_BYTES:
            raise ValueError("confidence sidecar exceeds its byte cap")
        return self


def _dimension(
    name: DimensionName,
    level: ConfidenceLevel,
    *reasons: ReasonCode,
) -> DeterministicConfidenceDimension:
    decision: ConfidenceDecision = {
        "supported": "accept",
        "guarded": "concern",
        "unsupported": "fallback",
        "unavailable": "withhold",
    }[level]
    return DeterministicConfidenceDimension(
        dimension=name,
        applicability="applicable",
        level=level,
        decision=decision,
        reason_codes=tuple(dict.fromkeys(reasons))[:_MAX_REASON_CODES],
    )


def _table_not_applicable() -> DeterministicConfidenceDimension:
    return DeterministicConfidenceDimension(
        dimension="table",
        applicability="not_applicable",
        level="unavailable",
        decision="not_applicable",
        reason_codes=("no_table_output",),
    )


def _bounded_items(
    result: ParseResult,
) -> tuple[list[tuple[ContentItem, int]], bool]:
    items: list[tuple[ContentItem, int]] = []
    for page in result.pages:
        for item in page.items:
            if len(items) == _MAX_ITEMS:
                return items, True
            items.append((item, page.page_index))
    return items, False


def _item_concerns(item: ContentItem) -> tuple[tuple[str, ...], bool]:
    raw = (item.model_extra or {}).get("parse_concerns", ())
    if raw is None:
        return (), False
    if not isinstance(raw, (list, tuple)):
        return ("malformed",), False
    values: list[str] = []
    for value in raw[:_MAX_CONCERNS_PER_ITEM]:
        if not isinstance(value, str):
            values.append("malformed")
        else:
            values.append(value.casefold())
    return tuple(values), len(raw) > _MAX_CONCERNS_PER_ITEM


def _has_concern(
    items: list[tuple[ContentItem, int]],
    tokens: frozenset[str],
) -> tuple[bool, bool]:
    limited = False
    for item, _page_index in items:
        concerns, was_limited = _item_concerns(item)
        limited = limited or was_limited
        if any(
            concern == "malformed"
            or any(token in concern for token in tokens)
            for concern in concerns
        ):
            return True, limited
    return False, limited


def _has_warnings(result: ParseResult) -> bool:
    return bool(result.warnings or any(page.warnings for page in result.pages))


def _has_page_failure(result: ParseResult) -> bool:
    return any(not page.success for page in result.pages)


def _has_usable_text(item: ContentItem) -> bool:
    """Require bounded, non-blank text rather than trusting the item type."""

    value = item.value
    if isinstance(value, str):
        return bool(value.strip()) and len(value.encode("utf-8")) <= 1_048_576
    if isinstance(value, (list, tuple)) and 1 <= len(value) <= 65_536:
        total_bytes = 0
        for member in value:
            if not isinstance(member, str) or not member.strip():
                return False
            total_bytes += len(member.encode("utf-8"))
            if total_bytes > 1_048_576:
                return False
        return True
    return False


def _text_dimension(
    result: ParseResult,
    items: list[tuple[ContentItem, int]],
    item_limit: bool,
) -> DeterministicConfidenceDimension:
    typed_text_items = [item for item, _ in items if item.type in _TEXT_TYPES]
    if item_limit:
        return _dimension(
            "text",
            "unsupported",
            "inspection_limit_exceeded",
        )
    if not typed_text_items:
        return _dimension("text", "unavailable", "text_output_missing")
    if any(not _has_usable_text(item) for item in typed_text_items):
        return _dimension("text", "unavailable", "text_output_missing")
    text_items = typed_text_items
    concerns, concern_limit = _has_concern(
        [(item, 0) for item in text_items],
        _TEXT_CONCERN_TOKENS,
    )
    if concern_limit:
        return _dimension(
            "text",
            "unsupported",
            "inspection_limit_exceeded",
        )
    if _has_page_failure(result):
        return _dimension(
            "text",
            "unsupported",
            "text_items_present",
            "page_failure_reported",
        )
    if concerns:
        return _dimension(
            "text",
            "unsupported",
            "text_items_present",
            "explicit_concern_reported",
        )
    reasons: list[ReasonCode] = ["text_items_present"]
    if _has_warnings(result):
        reasons.append("output_warning_reported")
    if all(item.source == "native" for item in text_items):
        reasons.append("native_text_source")
    else:
        reasons.append("non_native_text_source")
    return _dimension(
        "text",
        "guarded" if _has_warnings(result) or reasons[-1] != "native_text_source" else "supported",
        *reasons,
    )


def _layout_dimension(
    result: ParseResult,
    items: list[tuple[ContentItem, int]],
    item_limit: bool,
) -> DeterministicConfidenceDimension:
    if item_limit:
        return _dimension(
            "layout",
            "unsupported",
            "inspection_limit_exceeded",
        )
    if not items:
        return _dimension("layout", "unavailable", "layout_output_missing")
    concerns, concern_limit = _has_concern(items, _LAYOUT_CONCERN_TOKENS)
    if concern_limit:
        return _dimension(
            "layout",
            "unsupported",
            "inspection_limit_exceeded",
        )
    if _has_page_failure(result):
        return _dimension(
            "layout",
            "unsupported",
            "layout_items_present",
            "page_failure_reported",
        )
    if concerns:
        return _dimension(
            "layout",
            "unsupported",
            "layout_items_present",
            "explicit_concern_reported",
        )
    page_orders: dict[int, list[int]] = {}
    for item, page_index in items:
        page_orders.setdefault(page_index, []).append(item.reading_order)
    orders_are_contiguous = all(
        values == list(range(len(values))) for values in page_orders.values()
    )
    if not orders_are_contiguous:
        return _dimension(
            "layout",
            "unsupported",
            "layout_items_present",
            "explicit_concern_reported",
        )
    complete_geometry = all(item.bbox is not None for item, _ in items)
    reasons: list[ReasonCode] = [
        "layout_items_present",
        "reading_order_contiguous",
        "complete_item_geometry" if complete_geometry else "item_geometry_missing",
    ]
    if _has_warnings(result):
        reasons.append("output_warning_reported")
    return _dimension(
        "layout",
        "supported" if complete_geometry and not _has_warnings(result) else "guarded",
        *reasons,
    )


def _rectangular_table(item: ContentItem) -> bool:
    extras = item.model_extra or {}
    rows = extras.get("rows", item.value)
    if (
        not isinstance(rows, list)
        or not rows
        or len(rows) > 4_096
        or not isinstance(rows[0], list)
        or not rows[0]
        or len(rows[0]) > 256
    ):
        return False
    columns = len(rows[0])
    if any(
        not isinstance(row, list)
        or len(row) != columns
        or any(not isinstance(value, str) for value in row)
        for row in rows
    ):
        return False
    row_count = extras.get("row_count")
    column_count = extras.get("column_count")
    return not (
        row_count is not None and row_count != len(rows)
        or column_count is not None and column_count != columns
    )


def _table_source_supported(item: ContentItem) -> bool:
    evidence = item.table_evidence
    if evidence is not None:
        if evidence.status != "valid":
            return False
        gate = evidence.gate
        return gate is None or gate.outcome == "canonical_table"
    gate = (item.model_extra or {}).get("table_candidate_gate")
    if type(gate) is not dict:
        return False
    try:
        validated = TableCandidateGate.model_validate(gate, strict=True)
    except (MemoryError, TypeError, ValueError, OverflowError):
        return False
    return validated.outcome == "canonical_table"


def _table_has_explicit_rejection(item: ContentItem) -> bool:
    evidence = item.table_evidence
    if evidence is not None and evidence.status != "valid":
        return True
    gate: Any = evidence.gate if evidence is not None else (
        item.model_extra or {}
    ).get("table_candidate_gate")
    if evidence is None and type(gate) is dict:
        try:
            gate = TableCandidateGate.model_validate(gate, strict=True)
        except (MemoryError, TypeError, ValueError, OverflowError):
            return True
    outcome = gate.outcome if isinstance(gate, TableCandidateGate) else None
    return outcome in {
        "chart",
        "form",
        "key_value",
        "structural_failure",
        "unresolved",
        "visual",
    }


def _table_dimension(
    result: ParseResult,
    items: list[tuple[ContentItem, int]],
    item_limit: bool,
) -> DeterministicConfidenceDimension:
    tables = [item for item, _ in items if item.type == "table"]
    if not tables:
        return _table_not_applicable()
    if item_limit:
        return _dimension(
            "table",
            "unsupported",
            "inspection_limit_exceeded",
        )
    concerns, concern_limit = _has_concern(
        [(item, 0) for item in tables],
        _TABLE_CONCERN_TOKENS,
    )
    if concern_limit:
        return _dimension(
            "table",
            "unsupported",
            "inspection_limit_exceeded",
        )
    if _has_page_failure(result):
        return _dimension("table", "unsupported", "page_failure_reported")
    if concerns:
        return _dimension(
            "table",
            "unsupported",
            "explicit_concern_reported",
        )
    if any(not _rectangular_table(item) for item in tables):
        return _dimension(
            "table",
            "unsupported",
            "table_shape_contradictory",
        )
    if any(_table_has_explicit_rejection(item) for item in tables):
        return _dimension(
            "table",
            "unsupported",
            "explicit_concern_reported",
        )
    if all(_table_source_supported(item) for item in tables):
        return _dimension("table", "supported", "source_supported_table")
    reasons: list[ReasonCode] = ["table_structure_evidence_limited"]
    if _has_warnings(result):
        reasons.append("output_warning_reported")
    return _dimension("table", "guarded", *reasons)


def assess_deterministic_confidence(result: ParseResult) -> DeterministicConfidence:
    """Assess a validated parse result with independent, bounded rules."""

    if not isinstance(result, ParseResult):
        raise TypeError("deterministic confidence requires a ParseResult")
    items, item_limit = _bounded_items(result)
    dimensions = (
        _text_dimension(result, items, item_limit),
        _layout_dimension(result, items, item_limit),
        _table_dimension(result, items, item_limit),
    )
    applicable = [
        value.decision
        for value in dimensions
        if value.decision != "not_applicable"
    ]
    overall: Literal["accept", "concern", "fallback", "withhold"] = "accept"
    for decision in ("concern", "withhold", "fallback"):
        if decision in applicable:
            overall = decision
    return DeterministicConfidence(
        dimensions=dimensions,
        overall_decision=overall,
    )


def apply_deterministic_confidence(
    result: ParseResult,
    *,
    enabled: bool,
) -> ParseResult:
    """Return exact input while off, or a shallow copy with one typed sidecar."""

    if not enabled:
        return result
    sidecar = assess_deterministic_confidence(result)
    candidate = result.model_copy()
    extras = dict(result.model_extra or {})
    extras["deterministic_confidence"] = sidecar.model_dump(mode="json")
    object.__setattr__(candidate, "__pydantic_extra__", extras)
    return candidate
