"""Public request and response models for the parsing API."""

# Pydantic converts ValueError into structured validation failures but lets
# TypeError escape the model-validation boundary.
# ruff: noqa: TRY004

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    GetJsonSchemaHandler,
    StrictFloat,
    StrictInt,
    ValidationInfo,
    field_validator,
    model_serializer,
    model_validator,
)
from pydantic.json_schema import SkipJsonSchema
from pydantic_core import CoreSchema

from app.services.office_charts import OfficeChartStructure
from app.services.source_note_contracts import (
    is_eligible_unresolved_table_candidate,
    is_source_note_owner_item,
)
from app.services.visual_contracts import VisualStructure
from app.services.visual_model_contracts import VisualModelEvidenceBundle


class ApiModel(BaseModel):
    """Base model that permits additive schema evolution."""

    model_config = ConfigDict(extra="allow")


class StrictApiModel(BaseModel):
    """Closed additive contracts introduced behind feature flags."""

    model_config = ConfigDict(extra="forbid")


class StrictTableApiModel(BaseModel):
    """Closed, non-coercing P04 table contracts."""

    model_config = ConfigDict(extra="forbid", strict=True)

    @model_validator(mode="before")
    @classmethod
    def validate_plain_mapping(cls, value: Any) -> Any:
        if type(value) is cls:
            return value
        if type(value) is not dict:
            raise ValueError("table schema value must be an exact object")
        return value


_RUNNING_POLICY_ID = "p03-running-regions-page-identity-v1"
_RUNNING_CONCERN_CODES = frozenset(
    {
        "running_region_source_evidence_unavailable",
        "running_region_source_limit",
        "running_region_candidate_limit",
        "running_region_geometry_ambiguous",
        "running_region_repetition_ambiguous",
        "running_region_navigation_ambiguous",
        "running_region_ownership_conflict",
        "page_identity_embedded_label_invalid",
        "page_identity_detected_label_ambiguous",
        "page_identity_source_conflict",
        "page_identity_display_unsafe",
        "running_region_canonical_custody_invalid",
        "running_region_projection_failed_closed",
        "running_region_concerns_truncated",
    }
)
_PAGE_IDENTITY_CONCERN_CODES = _RUNNING_CONCERN_CODES - {
    "running_region_repetition_ambiguous",
    "running_region_navigation_ambiguous",
    "running_region_canonical_custody_invalid",
}
_SAFE_LABEL_PUNCTUATION = frozenset(" ._-:/|()")
_VISIBLE_INTEGER_RE = re.compile(r"^[1-9][0-9]{0,5}$")
_VISIBLE_FRACTION_RE = re.compile(r"^([1-9][0-9]{0,5})\s*/\s*([1-9][0-9]{0,5})$")
_VISIBLE_PAGE_OF_RE = re.compile(
    r"^Page\s+([1-9][0-9]{0,5})\s+of\s+([1-9][0-9]{0,5})$", re.IGNORECASE
)
_VISIBLE_PIPE_RE = re.compile(r"^Page\s*\|\s*([1-9][0-9]{0,5})$", re.IGNORECASE)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LEGACY_SOURCE_RE = re.compile(
    r"^configured-predecessor:([0-9a-f]{64}):page:([1-9][0-9]*):page_label$"
)
_RUNNING_MARKER_KEYS = frozenset(
    {
        "layout_running_region_projected",
        "running_region_policy",
        "running_region",
    }
)
_MAX_EXTRACTED_CONTRIBUTION_BYTES = 4 * 1024
_MAX_RUNNING_REGIONS_PER_PAGE = 64
_MAX_EXTRACTED_REGIONS_PER_PAGE = 8
_MAX_EXTRACTED_REGIONS_PER_DOCUMENT = 64
_MAX_REPETITION_GROUPS_PER_DOCUMENT = 2_048
_MAX_CONCERNS_PER_PAGE = 64
_MAX_CONCERNS_PER_DOCUMENT = 256

_TABLE_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_TABLE_MAX_ROWS = 4_096
_TABLE_MAX_COLUMNS = 256
_TABLE_MAX_CELLS = 65_536
_TABLE_MAX_REFERENCES = 64
_TABLE_MAX_CELL_BYTES = 16_384
_TABLE_MAX_RECOVERY_SOURCE_OBJECTS = 48
_TABLE_MAX_WORDS_PER_SOURCE = 64
_TABLE_MAX_FONT_NAME_BYTES = 256
_TABLE_MAX_SIDECAR_BYTES = 8 * 1024 * 1024
_TABLE_MAX_DOCUMENT_SIDECAR_BYTES = 64 * 1024 * 1024
_TABLE_MAX_ITEM_BYTES = 8 * 1024 * 1024
_TABLE_MAX_CANONICAL_PAGES = _TABLE_MAX_ROWS
_TABLE_MAX_CANONICAL_BLOCKS = _TABLE_MAX_CELLS
_TABLE_MAX_CANONICAL_VIEW_BYTES = _TABLE_MAX_DOCUMENT_SIDECAR_BYTES
_CUSTODY_MAX_RECORDS = 65_536
_CUSTODY_MAX_RECORD_BYTES = 8 * 1024 * 1024
_CUSTODY_MAX_DOCUMENT_BYTES = 64 * 1024 * 1024
_CUSTODY_SIDECAR_KEYS = frozenset(
    {
        "policy_id",
        "schema_version",
        "authority",
        "source_sha256",
        "canonical_presentation_sha256",
        "record_count",
        "records_sha256",
        "records",
    }
)

_LAYOUT_NOTE_NONLINK_BASES = frozenset(
    {
        "geometry_and_source_evidence",
        "ocr_and_geometry",
    }
)
_LAYOUT_NOTE_LINK_BASES = frozenset(
    {
        "annotation_and_geometry",
        "source_link_and_geometry",
    }
)
_LAYOUT_NOTE_MAX_LINKS = 16
_LAYOUT_NOTE_MAX_URI_BYTES = 2 * 1024
_LAYOUT_NOTE_MAX_VALUE_BYTES = 16 * 1024

_TRUSTED_TABLE_VALIDATION_TOKEN = object()
_TABLE_CONTEXT_FREE_VALIDATION_TOKEN = object()
_MAX_CONTEXT_FREE_INERT_REMNANTS = 64
_MAX_CONTEXT_FREE_RAW_REF_ORDINALS = 4_096


class _TrustedTableValidationContext:
    """Process-local proof that a P03 baseline passed ParseResult validation."""

    __slots__ = (
        "baseline",
        "custody_identity",
        "custody_relationship_ids",
        "token",
    )

    def __init__(
        self,
        token: object,
        baseline: Any,
        custody_identity: tuple[Any, ...] | None = None,
        custody_relationship_ids: tuple[str, ...] | None = None,
    ) -> None:
        self.token = token
        self.baseline = baseline
        self.custody_identity = custody_identity
        self.custody_relationship_ids = custody_relationship_ids


class _TableContextFreeValidationContext:
    """One-shot proof for a bounded alternate visual predecessor rebuild."""

    __slots__ = (
        "base_ir_projection",
        "base_predecessor_blocks",
        "deferred_owners",
        "document_sha256",
        "inert_remnants",
        "result",
        "table_ir_bboxes",
        "table_ir_elements",
        "table_ir_evidence",
        "table_ir_relationships",
        "token",
    )

    def __init__(
        self,
        token: object,
        result: Any,
        document_sha256: str,
        deferred_owners: tuple[tuple[Any, ...], ...],
        inert_remnants: tuple[tuple[Any, ...], ...],
        base_ir_projection: tuple[Any, ...],
        base_predecessor_blocks: tuple[tuple[Any, ...], ...],
        table_ir_bboxes: tuple[tuple[str, str], ...],
        table_ir_elements: tuple[tuple[str, str], ...],
        table_ir_evidence: tuple[tuple[str, str], ...],
        table_ir_relationships: tuple[tuple[str, str], ...],
    ) -> None:
        self.token = token
        self.result = result
        self.document_sha256 = document_sha256
        self.deferred_owners = deferred_owners
        self.inert_remnants = inert_remnants
        self.base_ir_projection = base_ir_projection
        self.base_predecessor_blocks = base_predecessor_blocks
        self.table_ir_bboxes = table_ir_bboxes
        self.table_ir_elements = table_ir_elements
        self.table_ir_evidence = table_ir_evidence
        self.table_ir_relationships = table_ir_relationships


def _trusted_table_validation_context(
    baseline: Any,
    expected_custody: Any | None = None,
) -> Any:
    """Issue the private context used by the terminal P04 commit only."""

    if type(baseline) is not ParseResult:
        raise TypeError("trusted table baseline must be a ParseResult")
    if (
        baseline.canonical_source_custody is not None
        or any(
            item.table_evidence is not None
            for page in baseline.pages
            for item in page.items
        )
    ):
        raise ValueError("trusted table baseline must be an unmarked P03 result")
    custody_identity: tuple[Any, ...] | None = None
    custody_relationship_ids: tuple[str, ...] | None = None
    if expected_custody is not None:
        if type(expected_custody) is not CanonicalSourceCustody:
            raise TypeError(
                "trusted table custody must be CanonicalSourceCustody"
            )
        custody_identity = (
            expected_custody.policy_id,
            expected_custody.schema_version,
            expected_custody.authority,
            expected_custody.source_sha256,
            expected_custody.canonical_presentation_sha256,
            expected_custody.record_count,
            expected_custody.records_sha256,
        )
        custody_relationship_ids = tuple(
            sorted({record.relationship_id for record in expected_custody.records})
        )
    return _TrustedTableValidationContext(
        _TRUSTED_TABLE_VALIDATION_TOKEN,
        baseline,
        custody_identity,
        custody_relationship_ids,
    )


def _trusted_table_baseline_from_context(value: Any) -> Any | None:
    if (
        type(value) is _TrustedTableValidationContext
        and value.token is _TRUSTED_TABLE_VALIDATION_TOKEN
        and type(value.baseline) is ParseResult
    ):
        return value.baseline
    return None


def _trusted_table_custody_identity_from_context(
    value: Any,
) -> tuple[Any, ...] | None:
    if (
        type(value) is _TrustedTableValidationContext
        and value.token is _TRUSTED_TABLE_VALIDATION_TOKEN
        and type(value.baseline) is ParseResult
        and (
            value.custody_identity is None
            or (
                type(value.custody_identity) is tuple
                and len(value.custody_identity) == 7
            )
        )
    ):
        return value.custody_identity
    return None


def _trusted_table_custody_relationship_ids_from_context(
    value: Any,
) -> tuple[str, ...] | None:
    if (
        type(value) is _TrustedTableValidationContext
        and value.token is _TRUSTED_TABLE_VALIDATION_TOKEN
        and type(value.baseline) is ParseResult
        and (
            value.custody_relationship_ids is None
            or (
                type(value.custody_relationship_ids) is tuple
                and tuple(sorted(set(value.custody_relationship_ids)))
                == value.custody_relationship_ids
                and all(
                    type(relationship_id) is str
                    and re.fullmatch(
                        _CUSTODY_RELATIONSHIP_ID_PATTERN,
                        relationship_id,
                    )
                    is not None
                    for relationship_id in value.custody_relationship_ids
                )
            )
        )
    ):
        return value.custody_relationship_ids
    return None


def _table_context_free_validation_from_context(
    value: Any,
    result: Any,
) -> _TableContextFreeValidationContext | None:
    if (
        type(value) is _TableContextFreeValidationContext
        and value.token is _TABLE_CONTEXT_FREE_VALIDATION_TOKEN
        and value.result is result
        and type(value.document_sha256) is str
        and value.document_sha256 == result.document.sha256
        and type(value.deferred_owners) is tuple
        and type(value.inert_remnants) is tuple
        and bool(value.deferred_owners or value.inert_remnants)
    ):
        return value
    return None
_CUSTODY_RECORD_KEYS = frozenset(
    {
        "record_id",
        "record_order",
        "page_index",
        "edge_kind",
        "owner_order",
        "owner_element_id",
        "owner_raw_ref",
        "raw_slot_index",
        "raw_target_slot_index",
        "raw_assertion_sha256",
        "member_element_id",
        "member_raw_ref",
        "member_type",
        "member_content_basis",
        "member_content_sha256",
        "group_element_id",
        "group_raw_ref",
        "group_type",
        "counterpart_element_id",
        "counterpart_raw_ref",
        "counterpart_type",
        "counterpart_content_basis",
        "counterpart_content_sha256",
        "relationship_id",
        "relationship_type",
        "relationship_field",
        "normalized_relationship_field",
        "normalization_outcome",
        "normalized_assertion_count",
        "normalized_relationship_sha256",
        "normalized_evidence_count",
        "source_element_id",
        "source_raw_ref",
        "source_type",
        "source_content_basis",
        "source_content_sha256",
        "target_element_id",
        "target_raw_ref",
        "target_type",
        "target_content_basis",
        "target_content_sha256",
    }
)
_CUSTODY_OPTIONAL_NULL_RECORD_KEYS = frozenset(
    {
        "owner_element_id",
        "raw_target_slot_index",
    }
)
_CUSTODY_RAW_REF_PATTERN = (
    r"^#/(?:groups|texts|pictures|tables|key_value_items|form_items|"
    r"field_regions|field_items)/(?:0|[1-9][0-9]{0,9})$"
)
_CUSTODY_GROUP_REF_PATTERN = r"^#/groups/(?:0|[1-9][0-9]{0,9})$"
_CUSTODY_OWNER_REF_PATTERN = (
    r"^(?:#/(?:body|furniture)|#/(?:groups|texts|pictures|tables|"
    r"key_value_items|form_items|field_regions|field_items)/"
    r"(?:0|[1-9][0-9]{0,9}))$"
)
_CUSTODY_ELEMENT_ID_PATTERN = r"^el-[0-9a-f]{20}$"
_CUSTODY_RELATIONSHIP_ID_PATTERN = r"^rel-[0-9a-f]{20}$"
_CUSTODY_RECORD_ID_PATTERN = r"^custody-[0-9a-f]{64}$"
_CUSTODY_FIELD_PATTERN = r"^[A-Za-z][A-Za-z0-9_.\[\]-]{0,255}$"
_CUSTODY_ELEMENT_TYPE_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
_TABLE_SIDECAR_KEYS = frozenset(
    {
        "policy_id",
        "version",
        "scope",
        "status",
        "table_id",
        "candidate_id",
        "page_index",
        "grid",
        "slots",
        "source_objects",
        "evidence",
        "span_decisions",
        "representation_custody",
        "reconciliation",
        "gate",
        "continuation",
        "concerns",
    }
)
_TABLE_GRID_KEYS = frozenset({"row_count", "column_count", "cell_ids"})
_TABLE_SLOT_KEYS = frozenset(
    {"id", "row", "column", "kind", "cell_id", "covered_by_cell_id"}
)
_TABLE_DOCLING_SOURCE_KEYS = frozenset(
    {"id", "engine", "object_type", "page_index", "raw_ref", "content_sha256"}
)
_TABLE_PDFPLUMBER_SOURCE_KEYS = frozenset(
    {
        "id",
        "engine",
        "object_type",
        "page_index",
        "raw_ref",
        "role",
        "target_row",
        "target_column",
        "words",
        "content_sha256",
    }
)
_TABLE_WORD_KEYS = frozenset({"id", "text", "bbox", "font_name", "bold"})
_TABLE_BBOX_KEYS = frozenset({"x", "y", "width", "height", "unit"})
_TABLE_EVIDENCE_RECORD_KEYS = frozenset(
    {
        "id",
        "method",
        "dimension",
        "page_index",
        "bbox",
        "source_object_ids",
        "confidence",
        "content_sha256",
    }
)
_TABLE_SPAN_KEYS = frozenset(
    {
        "id",
        "cell_id",
        "claimed_row_span",
        "claimed_col_span",
        "emitted_row_span",
        "emitted_col_span",
        "outcome",
        "evidence_ids",
        "concern_codes",
    }
)
_TABLE_CUSTODY_KEYS = frozenset(
    {
        "serializer_policy_id",
        "grid_shape",
        "cells_sha256",
        "rows_sha256",
        "html_sha256",
        "markdown_sha256",
        "csv_sha256",
    }
)
_TABLE_CELL_KEYS = frozenset(
    {
        "id",
        "row",
        "column",
        "row_span",
        "col_span",
        "text",
        "column_header",
        "row_header",
        "row_section",
        "bbox",
        "source",
        "page_index",
        "evidence_ids",
        "source_object_ids",
        "span_decision_id",
        "confidence_dimensions",
    }
)
_TABLE_CONFIDENCE_KEYS = frozenset({"text", "geometry", "structure", "header"})
_TABLE_SCOPE_ORDER = ("P04-US01", "P04-US02", "P04-US04", "P04-US03")
_TABLE_RECONCILIATION_KEYS = frozenset(
    {
        "cluster_id",
        "candidate_ids",
        "selected_candidate_id",
        "outcome",
        "absolute_threshold",
        "selection_margin",
        "scores",
        "evidence_ids",
        "concern_codes",
    }
)
_TABLE_GATE_KEYS = frozenset(
    {
        "decision_id",
        "candidate_id",
        "outcome",
        "owner_item_ids",
        "feature_scores",
        "evidence_ids",
        "concern_codes",
    }
)
_TABLE_GATE_FEATURE_KEYS = frozenset(
    {
        "alignment",
        "cell_coverage",
        "geometry",
        "grid",
        "owner_overlap",
        "provenance",
        "region_type",
        "table_support",
    }
)
_TABLE_CONTINUATION_KEYS = frozenset(
    {
        "merge_id",
        "outcome",
        "source_table_ids",
        "continued_from",
        "page_indexes",
        "signal_ids",
        "repeated_header_cell_ids",
        "evidence_ids",
        "concern_codes",
    }
)
_TABLE_CONCERN_CODES = frozenset(
    {
        "table_ambiguous_border_evidence",
        "table_malformed_source_evidence",
        "table_resource_limit_exceeded",
        "table_source_cell_bbox_unresolved",
        "table_source_cell_grid_unresolved",
        "table_source_form_grid_topology_unresolved",
        "table_source_header_ownership_unresolved",
        "table_source_provenance_unresolved",
        "table_source_rotation_mapping_unresolved",
        "table_source_row_boundary_unresolved",
        "table_source_span_evidence_unresolved",
        "table_reconciliation_conflict",
        "table_reconciliation_low_margin",
        "table_reconciliation_malformed_candidate",
        "table_candidate_chart_owned",
        "table_candidate_form_owned",
        "table_candidate_key_value_alternative",
        "table_candidate_ownership_ambiguous",
        "table_candidate_structure_invalid",
        "table_continuation_ambiguous",
        "table_continuation_incompatible",
    }
)
_TABLE_UNSAFE_CONTROLS = frozenset(
    chr(value) for value in (*range(0x00, 0x09), 0x0B, 0x0C, *range(0x0D, 0x20), 0x7F)
)

TableSha256 = Annotated[str, Field(pattern=_TABLE_SHA256_PATTERN)]
TableNonNegativeNumber = (
    Annotated[StrictInt, Field(ge=0)]
    | Annotated[StrictFloat, Field(ge=0)]
)
TablePositiveNumber = (
    Annotated[StrictInt, Field(gt=0)]
    | Annotated[StrictFloat, Field(gt=0)]
)
TableConfidenceNumber = (
    Annotated[StrictInt, Field(ge=0, le=1)]
    | Annotated[StrictFloat, Field(ge=0, le=1)]
)


def _table_number_is_finite(value: Any) -> bool:
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def _bounded_table_text(value: str, *, maximum_bytes: int, allow_empty: bool) -> str:
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("table text must be valid UTF-8") from exc
    if (not allow_empty and not value) or len(encoded) > maximum_bytes:
        raise ValueError("table text is empty or oversized")
    if any(character in _TABLE_UNSAFE_CONTROLS for character in value):
        raise ValueError("table text contains an unsafe control")
    return value


def _validate_table_hashes(
    values: list[str],
    *,
    allow_empty: bool,
    require_sorted: bool = True,
) -> list[str]:
    if not allow_empty and not values:
        raise ValueError("table references must not be empty")
    if len(values) > _TABLE_MAX_REFERENCES or len(values) != len(set(values)):
        raise ValueError("table references repeat or exceed their cap")
    if require_sorted and values != sorted(values):
        raise ValueError("table references are not in canonical order")
    return values


def _validate_table_concerns(values: list[str]) -> list[str]:
    if (
        len(values) > _TABLE_MAX_REFERENCES
        or values != sorted(set(values))
        or any(value not in _TABLE_CONCERN_CODES for value in values)
    ):
        raise ValueError("table concern codes differ")
    return values


def _iter_strict_table_json_chunks(
    value: Any,
    ancestors: set[int],
    depth: int,
):
    if depth > 64:
        raise ValueError("table JSON nesting exceeds its depth cap")
    if value is None:
        yield "null"
        return
    if type(value) is bool:
        yield "true" if value else "false"
        return
    if type(value) is int:
        if value.bit_length() > 4_096:
            raise ValueError("table JSON integer exceeds its bit cap")
        yield str(value)
        return
    if type(value) is float:
        if not _table_number_is_finite(value):
            raise ValueError("table JSON number must be finite")
        yield json.dumps(value, allow_nan=False, separators=(",", ":"))
        return
    if type(value) is str:
        yield json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return
    if type(value) not in (dict, list):
        raise ValueError("table JSON container must be an exact object or array")

    identity = id(value)
    if identity in ancestors:
        raise ValueError("table JSON container cycle differs")
    ancestors.add(identity)
    try:
        if type(value) is list:
            yield "["
            for index, member in enumerate(value):
                if index:
                    yield ","
                yield from _iter_strict_table_json_chunks(
                    member,
                    ancestors,
                    depth + 1,
                )
            yield "]"
            return

        keys = list(dict.keys(value))
        if any(type(key) is not str for key in keys):
            raise ValueError("table JSON object key differs")
        keys.sort()
        yield "{"
        for index, key in enumerate(keys):
            if index:
                yield ","
            yield json.dumps(key, ensure_ascii=False, separators=(",", ":"))
            yield ":"
            yield from _iter_strict_table_json_chunks(
                dict.__getitem__(value, key),
                ancestors,
                depth + 1,
            )
        yield "}"
    finally:
        ancestors.remove(identity)


def _bounded_table_json_size(value: Any, maximum_bytes: int) -> int | None:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    total_bytes = 0
    try:
        for chunk in _iter_strict_table_json_chunks(payload, set(), 0):
            total_bytes += len(chunk.encode("utf-8"))
            if total_bytes > maximum_bytes:
                return None
    except UnicodeEncodeError as exc:
        raise ValueError("table value is not valid UTF-8 JSON") from exc
    return total_bytes


def _table_json_within_limit(value: BaseModel, maximum_bytes: int) -> bool:
    return _bounded_table_json_size(value, maximum_bytes) is not None


def _raw_table_object(
    value: Any,
    expected_keys: frozenset[str],
    label: str,
) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError(f"{label} must be an exact object")
    if len(value) != len(expected_keys) or any(
        key not in expected_keys for key in value
    ):
        raise ValueError(f"Extra inputs are not permitted in {label}")
    return value


def _raw_table_list(
    value: Any,
    *,
    maximum: int,
    label: str,
    minimum: int = 0,
) -> list[Any]:
    if type(value) is not list:
        raise ValueError(f"{label} must be an exact array")
    if len(value) < minimum or len(value) > maximum:
        raise ValueError(f"{label} must contain between {minimum} and {maximum} items")
    return value


def _raw_table_int(
    value: Any,
    *,
    minimum: int,
    maximum: int,
    label: str,
) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise ValueError(f"{label} is not a bounded strict integer")
    return value


def _raw_table_hash(value: Any, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label} is not a lower-case SHA-256 identity")
    return value


def _raw_table_hashes(
    value: Any,
    *,
    maximum: int,
    label: str,
    minimum: int = 0,
    require_sorted: bool = True,
) -> list[str]:
    values = _raw_table_list(
        value,
        maximum=maximum,
        minimum=minimum,
        label=label,
    )
    identities: set[str] = set()
    previous = ""
    for member in values:
        identity = _raw_table_hash(member, label)
        if identity in identities or (require_sorted and identity <= previous):
            raise ValueError(f"{label} is not unique canonical identity order")
        identities.add(identity)
        previous = identity
    return values


def _raw_table_number(
    value: Any,
    *,
    positive: bool,
    label: str,
) -> int | float:
    if (
        type(value) not in (int, float)
        or not _table_number_is_finite(value)
        or value < 0
        or (positive and value <= 0)
    ):
        raise ValueError(f"{label} is not a finite bounded table number")
    return value


def _preflight_raw_table_bbox(value: Any, label: str) -> None:
    bbox = _raw_table_object(value, _TABLE_BBOX_KEYS, label)
    _raw_table_number(bbox.get("x"), positive=False, label=label)
    _raw_table_number(bbox.get("y"), positive=False, label=label)
    _raw_table_number(bbox.get("width"), positive=True, label=label)
    _raw_table_number(bbox.get("height"), positive=True, label=label)
    if bbox.get("unit") != "pt":
        raise ValueError(f"{label} unit differs")


def _preflight_raw_table_cell(value: Any) -> tuple[list[str], list[str]]:
    cell = _raw_table_object(value, _TABLE_CELL_KEYS, "marked table cell")
    _raw_table_hash(cell.get("id"), "marked table cell ID")
    _raw_table_int(
        cell.get("row"),
        minimum=0,
        maximum=_TABLE_MAX_ROWS - 1,
        label="marked table cell row",
    )
    _raw_table_int(
        cell.get("column"),
        minimum=0,
        maximum=_TABLE_MAX_COLUMNS - 1,
        label="marked table cell column",
    )
    _raw_table_int(
        cell.get("row_span"),
        minimum=1,
        maximum=_TABLE_MAX_ROWS,
        label="marked table cell row span",
    )
    _raw_table_int(
        cell.get("col_span"),
        minimum=1,
        maximum=_TABLE_MAX_COLUMNS,
        label="marked table cell column span",
    )
    text = cell.get("text")
    if type(text) is not str:
        raise ValueError("marked table cell text differs")
    _bounded_table_text(text, maximum_bytes=_TABLE_MAX_CELL_BYTES, allow_empty=True)
    if type(cell.get("column_header")) is not bool:
        raise ValueError("marked table cell header ownership differs")
    if type(cell.get("row_header")) is not bool:
        raise ValueError("marked table cell header ownership differs")
    if type(cell.get("row_section")) is not bool:
        raise ValueError("marked table cell header ownership differs")
    bbox = cell.get("bbox")
    if bbox is not None:
        _preflight_raw_table_bbox(bbox, "marked table cell bbox")
    if cell.get("source") not in ("native", "ocr"):
        raise ValueError("marked table cell source differs")
    _raw_table_int(
        cell.get("page_index"),
        minimum=1,
        maximum=1_000_000,
        label="marked table cell page",
    )
    evidence_ids = _raw_table_hashes(
        cell.get("evidence_ids"),
        minimum=1,
        maximum=_TABLE_MAX_REFERENCES,
        label="marked table cell evidence IDs",
    )
    source_ids = _raw_table_hashes(
        cell.get("source_object_ids"),
        minimum=1,
        maximum=_TABLE_MAX_REFERENCES,
        label="marked table cell source IDs",
    )
    decision_id = cell.get("span_decision_id")
    if decision_id is not None:
        _raw_table_hash(decision_id, "marked table span decision ID")
    dimensions = _raw_table_object(
        cell.get("confidence_dimensions"),
        _TABLE_CONFIDENCE_KEYS,
        "marked table confidence dimensions",
    )
    for dimension in _TABLE_CONFIDENCE_KEYS:
        confidence = dimensions.get(dimension)
        if confidence is not None and (
            type(confidence) not in (int, float)
            or not _table_number_is_finite(confidence)
            or not 0 <= confidence <= 1
        ):
            raise ValueError("marked table confidence dimension differs")
    return source_ids, evidence_ids


def _preflight_raw_table_sidecar(
    value: Any,
    raw_cells: Any = None,
    document_remaining_bytes: int | None = None,
) -> int:
    sidecar = _raw_table_object(value, _TABLE_SIDECAR_KEYS, "table evidence")
    marker_limit = _TABLE_MAX_SIDECAR_BYTES
    if document_remaining_bytes is not None:
        marker_limit = min(marker_limit, max(document_remaining_bytes, 0))
    encoded_size = _bounded_table_json_size(sidecar, marker_limit)
    if encoded_size is None:
        if (
            document_remaining_bytes is not None
            and document_remaining_bytes < _TABLE_MAX_SIDECAR_BYTES
        ):
            raise ValueError(
                "table evidence document aggregate exceeds its byte cap"
            )
        raise ValueError("table evidence exceeds its byte cap")
    grid = _raw_table_object(sidecar.get("grid"), _TABLE_GRID_KEYS, "table grid")
    row_count = _raw_table_int(
        grid.get("row_count"),
        minimum=1,
        maximum=_TABLE_MAX_ROWS,
        label="table row count",
    )
    column_count = _raw_table_int(
        grid.get("column_count"),
        minimum=1,
        maximum=_TABLE_MAX_COLUMNS,
        label="table column count",
    )
    if row_count * column_count > _TABLE_MAX_CELLS:
        raise ValueError("table grid exceeds its slot cap")
    cell_ids = _raw_table_hashes(
        grid.get("cell_ids"),
        maximum=_TABLE_MAX_CELLS,
        label="table grid cell IDs",
        require_sorted=False,
    )
    raw_reconciliation = sidecar.get("reconciliation")
    has_candidate_grid = sidecar.get("status") == "valid" or (
        sidecar.get("status") == "unresolved"
        and type(raw_reconciliation) is dict
        and raw_reconciliation.get("outcome") == "unresolved"
        and bool(cell_ids)
    )
    source_objects = _raw_table_list(
        sidecar.get("source_objects"),
        minimum=1,
        maximum=_TABLE_MAX_CELLS,
        label="table source objects",
    )
    evidence = _raw_table_list(
        sidecar.get("evidence"),
        minimum=1,
        maximum=_TABLE_MAX_CELLS,
        label="table evidence records",
    )
    decisions = _raw_table_list(
        sidecar.get("span_decisions"),
        maximum=_TABLE_MAX_CELLS,
        label="table span decisions",
    )
    if has_candidate_grid and type(raw_cells) is list:
        if len(source_objects) > (
            len(evidence) * _TABLE_MAX_REFERENCES
            + len(raw_cells) * _TABLE_MAX_REFERENCES
        ):
            raise ValueError("table source graph count is unreachable")
        if len(evidence) > (
            len(raw_cells) * _TABLE_MAX_REFERENCES
            + len(decisions) * _TABLE_MAX_REFERENCES
            + 2
        ):
            raise ValueError("table evidence graph count is unreachable")

    slots = _raw_table_list(
        sidecar.get("slots"),
        maximum=_TABLE_MAX_CELLS,
        label="table slots",
    )
    for raw_slot in slots:
        slot = _raw_table_object(raw_slot, _TABLE_SLOT_KEYS, "table slot")
        _raw_table_hash(slot.get("id"), "table slot ID")
        _raw_table_int(
            slot.get("row"),
            minimum=0,
            maximum=_TABLE_MAX_ROWS - 1,
            label="table slot row",
        )
        _raw_table_int(
            slot.get("column"),
            minimum=0,
            maximum=_TABLE_MAX_COLUMNS - 1,
            label="table slot column",
        )
        for key in ("cell_id", "covered_by_cell_id"):
            if slot.get(key) is not None:
                _raw_table_hash(slot.get(key), f"table slot {key}")

    source_ids: list[str] = []
    pdf_source_count = 0
    for raw_source in source_objects:
        if type(raw_source) is not dict:
            raise ValueError("table source object must be an exact object")
        engine = raw_source.get("engine")
        expected_source_keys = (
            _TABLE_DOCLING_SOURCE_KEYS
            if engine == "docling"
            else _TABLE_PDFPLUMBER_SOURCE_KEYS
            if engine == "pdfplumber"
            else frozenset()
        )
        source = _raw_table_object(
            raw_source,
            expected_source_keys,
            "table source object",
        )
        source_ids.append(_raw_table_hash(source.get("id"), "table source ID"))
        _raw_table_int(
            source.get("page_index"),
            minimum=1,
            maximum=1_000_000,
            label="table source page",
        )
        _raw_table_hash(source.get("content_sha256"), "table source content")
        if engine == "docling":
            if source.get("object_type") not in (
                "table_cell",
                "table_geometry",
                "table_grid",
            ):
                raise ValueError("table Docling source object type differs")
            raw_ref = source.get("raw_ref")
            if type(raw_ref) is not str:
                raise ValueError("table source reference differs")
            _bounded_table_text(raw_ref, maximum_bytes=256, allow_empty=False)
            continue
        pdf_source_count += 1
        if (
            source.get("object_type") != "table_word_set"
            or source.get("role") not in ("header", "body_control", "bottom_row")
            or source.get("raw_ref") is not None
        ):
            raise ValueError("table pdfplumber source reference differs")
        _raw_table_int(
            source.get("target_row"),
            minimum=0,
            maximum=_TABLE_MAX_ROWS - 1,
            label="table recovery target row",
        )
        _raw_table_int(
            source.get("target_column"),
            minimum=0,
            maximum=_TABLE_MAX_COLUMNS - 1,
            label="table recovery target column",
        )
        words = _raw_table_list(
            source.get("words"),
            minimum=1,
            maximum=_TABLE_MAX_WORDS_PER_SOURCE,
            label="table recovery words",
        )
        for raw_word in words:
            word = _raw_table_object(raw_word, _TABLE_WORD_KEYS, "table word")
            _raw_table_hash(word.get("id"), "table word ID")
            text = word.get("text")
            font_name = word.get("font_name")
            if type(text) is not str or not text.strip():
                raise ValueError("table word text must not be blank")
            _bounded_table_text(
                text,
                maximum_bytes=_TABLE_MAX_CELL_BYTES,
                allow_empty=False,
            )
            if type(font_name) is not str:
                raise ValueError("table font metadata differs")
            _bounded_table_text(
                font_name,
                maximum_bytes=_TABLE_MAX_FONT_NAME_BYTES,
                allow_empty=False,
            )
            if any(
                ord(character) < 0x20 or ord(character) == 0x7F
                for character in font_name
            ):
                raise ValueError("table font metadata contains an unsafe control")
            if type(word.get("bold")) is not bool:
                raise ValueError("table word bold derivation differs")
            _preflight_raw_table_bbox(word.get("bbox"), "table word bbox")
    if source_ids != sorted(set(source_ids)):
        raise ValueError("table source object identities differ")
    if pdf_source_count > _TABLE_MAX_RECOVERY_SOURCE_OBJECTS:
        raise ValueError("table recovery source count exceeds its cap")

    evidence_ids: list[str] = []
    evidence_source_ids: set[str] = set()
    evidence_descriptors: dict[str, tuple[str, list[str]]] = {}
    for raw_record in evidence:
        record = _raw_table_object(
            raw_record,
            _TABLE_EVIDENCE_RECORD_KEYS,
            "table evidence record",
        )
        evidence_id = _raw_table_hash(record.get("id"), "table evidence ID")
        evidence_ids.append(evidence_id)
        record_sources = _raw_table_hashes(
            record.get("source_object_ids"),
            minimum=1,
            maximum=_TABLE_MAX_REFERENCES,
            label="table evidence source IDs",
        )
        evidence_source_ids.update(record_sources)
        dimension = record.get("dimension")
        if dimension not in (
            "text",
            "geometry",
            "structure",
            "header",
            "ownership",
            "continuation",
        ):
            raise ValueError("table evidence dimension differs")
        if record.get("method") not in (
            "native_text",
            "ocr_text",
            "vector_rule",
            "source_grid",
            "embedded_grid",
            "model_structure",
            "recovered_structure",
            "derived_comparison",
        ):
            raise ValueError("table evidence method differs")
        evidence_descriptors[evidence_id] = (dimension, record_sources)
        bbox = record.get("bbox")
        if bbox is not None:
            _preflight_raw_table_bbox(bbox, "table evidence bbox")
        confidence = record.get("confidence")
        if (
            type(confidence) not in (int, float)
            or not _table_number_is_finite(confidence)
            or not 0 <= confidence <= 1
        ):
            raise ValueError("table evidence confidence differs")
        _raw_table_hash(record.get("content_sha256"), "table evidence content")
    if evidence_ids != sorted(set(evidence_ids)):
        raise ValueError("table evidence identities differ")

    decision_evidence_ids: set[str] = set()
    decision_ids: set[str] = set()
    for raw_decision in decisions:
        decision = _raw_table_object(raw_decision, _TABLE_SPAN_KEYS, "table span")
        decision_id = _raw_table_hash(decision.get("id"), "table span ID")
        if decision_id in decision_ids:
            raise ValueError("table span decision identities repeat")
        decision_ids.add(decision_id)
        _raw_table_hash(decision.get("cell_id"), "table span cell ID")
        for key, maximum in (
            ("claimed_row_span", _TABLE_MAX_ROWS),
            ("emitted_row_span", _TABLE_MAX_ROWS),
            ("claimed_col_span", _TABLE_MAX_COLUMNS),
            ("emitted_col_span", _TABLE_MAX_COLUMNS),
        ):
            _raw_table_int(
                decision.get(key),
                minimum=1,
                maximum=maximum,
                label=f"table span {key}",
            )
        if decision.get("outcome") not in ("supported", "refused", "ambiguous"):
            raise ValueError("table span outcome differs")
        decision_evidence_ids.update(
            _raw_table_hashes(
                decision.get("evidence_ids"),
                maximum=_TABLE_MAX_REFERENCES,
                label="table span evidence IDs",
            )
        )
        raw_concerns = _raw_table_list(
            decision.get("concern_codes"),
            maximum=_TABLE_MAX_REFERENCES,
            label="table span concerns",
        )
        if any(type(code) is not str or len(code) > 256 for code in raw_concerns):
            raise ValueError("table span concern differs")

    custody = _raw_table_object(
        sidecar.get("representation_custody"),
        _TABLE_CUSTODY_KEYS,
        "table representation custody",
    )
    shape = _raw_table_list(
        custody.get("grid_shape"),
        minimum=2,
        maximum=2,
        label="table custody grid shape",
    )
    _raw_table_int(
        shape[0],
        minimum=1,
        maximum=_TABLE_MAX_ROWS,
        label="table custody row count",
    )
    _raw_table_int(
        shape[1],
        minimum=1,
        maximum=_TABLE_MAX_COLUMNS,
        label="table custody column count",
    )
    for key in (
        "cells_sha256",
        "rows_sha256",
        "html_sha256",
        "markdown_sha256",
        "csv_sha256",
    ):
        _raw_table_hash(custody.get(key), f"table custody {key}")
    if custody.get("serializer_policy_id") != "p04-table-grid-serializer-v1":
        raise ValueError("table custody serializer policy differs")
    scope = _raw_table_list(
        sidecar.get("scope"),
        minimum=1,
        maximum=len(_TABLE_SCOPE_ORDER),
        label="table evidence scope",
    )
    reconciliation = sidecar.get("reconciliation")
    gate = sidecar.get("gate")
    continuation = sidecar.get("continuation")
    expected_scope = ["P04-US01"]
    if reconciliation is not None:
        expected_scope.append("P04-US02")
    if gate is not None:
        if reconciliation is None:
            raise ValueError("table gate requires reconciliation")
        expected_scope.append("P04-US04")
    if continuation is not None:
        if gate is None:
            raise ValueError("table continuation requires gate")
        expected_scope.append("P04-US03")
    if scope != expected_scope:
        raise ValueError("table evidence scope differs")
    for metadata, expected_keys, label in (
        (reconciliation, _TABLE_RECONCILIATION_KEYS, "table reconciliation"),
        (gate, _TABLE_GATE_KEYS, "table candidate gate"),
        (continuation, _TABLE_CONTINUATION_KEYS, "table continuation"),
    ):
        if metadata is not None:
            _raw_table_object(metadata, expected_keys, label)
            if _bounded_table_json_size(metadata, _TABLE_MAX_SIDECAR_BYTES) is None:
                raise ValueError(f"{label} exceeds its byte cap")
    concerns = _raw_table_list(
        sidecar.get("concerns"),
        maximum=_TABLE_MAX_REFERENCES,
        label="table concerns",
    )
    if any(type(code) is not str or len(code) > 256 for code in concerns):
        raise ValueError("table concern differs")
    if (
        sidecar.get("policy_id") != "p04-table-evidence-v1"
        or sidecar.get("version") != "1.1"
        or sidecar.get("status") not in ("valid", "unresolved", "structural_failure")
    ):
        raise ValueError("table evidence marker differs")
    _raw_table_hash(sidecar.get("table_id"), "table identity")
    _raw_table_hash(sidecar.get("candidate_id"), "table candidate identity")
    _raw_table_int(
        sidecar.get("page_index"),
        minimum=1,
        maximum=1_000_000,
        label="table evidence page",
    )

    cell_source_ids: set[str] = set()
    cell_evidence_ids: set[str] = set()
    if has_candidate_grid and raw_cells is not None:
        cells = _raw_table_list(
            raw_cells,
            minimum=1,
            maximum=_TABLE_MAX_CELLS,
            label="marked table cells",
        )
        if len(cells) != len(cell_ids):
            raise ValueError("valid table cell count differs")
        observed_cell_ids: list[str] = []
        for raw_cell in cells:
            raw_source_ids, raw_evidence_ids = _preflight_raw_table_cell(raw_cell)
            observed_cell_ids.append(raw_cell["id"])
            cell_source_ids.update(raw_source_ids)
            cell_evidence_ids.update(raw_evidence_ids)
        if observed_cell_ids != cell_ids:
            raise ValueError("valid table cell identity order differs")

    source_id_set = set(source_ids)
    evidence_id_set = set(evidence_ids)
    if not evidence_source_ids <= source_id_set:
        raise ValueError("table evidence source reference differs")
    if not decision_evidence_ids <= evidence_id_set:
        raise ValueError("table span evidence reference differs")
    if raw_cells is not None and has_candidate_grid:
        if (
            not cell_source_ids <= source_id_set
            or not cell_evidence_ids <= evidence_id_set
        ):
            raise ValueError("marked table graph reference differs")
        if source_id_set != evidence_source_ids | cell_source_ids:
            raise ValueError("table source graph contains unused records")
        source_types = {
            source["id"]: source["object_type"]
            for source in source_objects
        }
        table_wide_ids = {
            evidence_id
            for evidence_id, (dimension, linked_sources) in evidence_descriptors.items()
            if len(linked_sources) == 1
            and (
                (
                    dimension == "geometry"
                    and source_types.get(linked_sources[0]) == "table_geometry"
                )
                or (
                    dimension == "structure"
                    and source_types.get(linked_sources[0]) == "table_grid"
                )
            )
        }
        if evidence_id_set != (
            cell_evidence_ids | decision_evidence_ids | table_wide_ids
        ):
            raise ValueError("table evidence graph contains unused records")

    return encoded_size


def _preflight_raw_table_document(value: Any) -> int | None:
    if type(value) is not dict:
        return None
    pages = value.get("pages")
    if type(pages) is not list:
        return None
    has_marked_table = any(
        type(raw_page) is dict
        and type(raw_page.get("items")) is list
        and any(
            type(raw_item) is dict
            and "table_evidence" in raw_item
            for raw_item in raw_page["items"]
        )
        for raw_page in pages
    )
    if not has_marked_table:
        return None

    document = value.get("document")
    if type(document) is not dict:
        raise ValueError("marked table document shape differs")
    page_count = document.get("page_count")
    if (
        type(page_count) is not int
        or page_count != len(pages)
        or page_count > 1_000_000
        or any(
            type(raw_page) is not dict
            or type(raw_page.get("items")) is not list
            for raw_page in pages
        )
    ):
        raise ValueError("marked table page/document coverage differs")
    if [raw_page.get("page_index") for raw_page in pages] != list(
        range(1, len(pages) + 1)
    ):
        raise ValueError("marked table page/document coverage differs")

    item_ids: set[str] = set()
    aggregate_bytes = 0
    table_ids: set[str] = set()
    candidate_ids: set[str] = set()
    for raw_page in pages:
        items = raw_page["items"]
        reading_orders: list[int] = []
        for raw_item in items:
            if type(raw_item) is not dict:
                raise ValueError("marked table item shape differs")
            reading_order = raw_item.get("reading_order")
            item_id = raw_item.get("id")
            if (
                type(reading_order) is not int
                or type(item_id) is not str
                or not item_id
            ):
                raise ValueError("marked table item identity/order differs")
            if item_id in item_ids:
                raise ValueError("marked table item identity/order differs")
            item_ids.add(item_id)
            reading_orders.append(reading_order)
            sidecar = raw_item.get("table_evidence")
            if sidecar is None:
                continue
            if "_p04_predecessor_snapshot" in raw_item:
                raise ValueError("private P04 predecessor snapshot reached the API")
            marker_bytes = _preflight_raw_table_sidecar(
                sidecar,
                raw_item.get("cells"),
                _TABLE_MAX_DOCUMENT_SIDECAR_BYTES - aggregate_bytes,
            )
            if _bounded_table_json_size(raw_item, _TABLE_MAX_ITEM_BYTES) is None:
                raise ValueError("table item exceeds its byte cap")
            aggregate_bytes += marker_bytes
            table_id = sidecar.get("table_id")
            candidate_id = sidecar.get("candidate_id")
            if table_id in table_ids or candidate_id in candidate_ids:
                raise ValueError("marked table document identity repeats")
            table_ids.add(table_id)
            candidate_ids.add(candidate_id)
        if reading_orders != list(range(len(items))):
            raise ValueError("marked table item identity/order differs")
    return aggregate_bytes


def _preflight_raw_marked_canonical(value: Any) -> None:
    """Bound a P04 canonical graph before Pydantic builds nested models.

    A marked response is required to carry exactly one canonical block for
    every public page item.  Checking that inexpensive skeleton first prevents
    a small table marker from authorizing an unrelated, amplified canonical
    payload.
    """

    if type(value) is not dict:
        return
    raw_pages = value.get("pages")
    if type(raw_pages) is not list:
        return
    marked = any(
        type(raw_page) is dict
        and type(raw_page.get("items")) is list
        and any(
            type(raw_item) is dict
            and "table_evidence" in raw_item
            for raw_item in raw_page["items"]
        )
        for raw_page in raw_pages
    )
    if not marked:
        return
    if "canonical_presentation" not in value:
        raise ValueError("marked table canonical presentation is absent")

    canonical = value.get("canonical_presentation")
    if type(canonical) is not dict:
        raise ValueError("marked table canonical presentation differs")
    canonical_pages = canonical.get("pages")
    if (
        type(canonical_pages) is not list
        or len(canonical_pages) != len(raw_pages)
        or len(canonical_pages) > _TABLE_MAX_CANONICAL_PAGES
    ):
        raise ValueError("marked table canonical page coverage differs")

    total_blocks = 0
    total_view_bytes = 0

    def bounded_string(raw: Any, *, maximum: int, label: str) -> None:
        nonlocal total_view_bytes
        if type(raw) is not str:
            raise ValueError(f"marked table canonical {label} differs")
        try:
            encoded_size = len(raw.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise ValueError(
                f"marked table canonical {label} is not UTF-8"
            ) from exc
        if encoded_size > maximum:
            raise ValueError(f"marked table canonical {label} exceeds its byte cap")
        if label == "view":
            total_view_bytes += encoded_size
            if total_view_bytes > _TABLE_MAX_CANONICAL_VIEW_BYTES:
                raise ValueError(
                    "marked table canonical views exceed their aggregate byte cap"
                )

    def validate_view(raw: Any, maximum_ids: int) -> None:
        if type(raw) is not dict:
            raise ValueError("marked table canonical view differs")
        block_ids = raw.get("block_ids")
        if (
            type(block_ids) is not list
            or len(block_ids) > maximum_ids
            or any(type(block_id) is not str or not block_id for block_id in block_ids)
        ):
            raise ValueError("marked table canonical view differs")
        bounded_string(
            raw.get("markdown"),
            maximum=_TABLE_MAX_CANONICAL_VIEW_BYTES,
            label="view",
        )
        bounded_string(
            raw.get("text"),
            maximum=_TABLE_MAX_CANONICAL_VIEW_BYTES,
            label="view",
        )

    for raw_page, canonical_page in zip(raw_pages, canonical_pages, strict=True):
        if type(raw_page) is not dict or type(raw_page.get("items")) is not list:
            raise ValueError("marked table page/document coverage differs")
        if type(canonical_page) is not dict:
            raise ValueError("marked table canonical page coverage differs")
        blocks = canonical_page.get("blocks")
        if (
            type(blocks) is not list
            or len(blocks) != len(raw_page["items"])
            or len(blocks) > _TABLE_MAX_CANONICAL_BLOCKS
        ):
            raise ValueError("marked table canonical block coverage differs")
        total_blocks += len(blocks)
        if total_blocks > _TABLE_MAX_CANONICAL_BLOCKS:
            raise ValueError("marked table canonical block coverage differs")
        for block in blocks:
            if type(block) is not dict:
                raise ValueError("marked table canonical block differs")
            bounded_string(
                block.get("markdown"),
                maximum=_TABLE_MAX_ITEM_BYTES,
                label="block scalar",
            )
            bounded_string(
                block.get("text"),
                maximum=_TABLE_MAX_ITEM_BYTES,
                label="block scalar",
            )
        for view_name in ("full", "body", "header", "footer"):
            validate_view(canonical_page.get(view_name), len(blocks))

    for view_name in ("full", "body", "header", "footer"):
        validate_view(canonical.get(view_name), total_blocks)
    if (
        _bounded_table_json_size(canonical, _TABLE_MAX_DOCUMENT_SIDECAR_BYTES)
        is None
    ):
        raise ValueError("marked table canonical presentation exceeds its byte cap")


def _preflight_raw_canonical_source_custody(value: Any) -> int | None:
    """Bound and close P04 opaque-group custody before nested validation."""

    if type(value) is not dict:
        return None
    raw_pages = value.get("pages")
    marked = type(raw_pages) is list and any(
        type(raw_page) is dict
        and type(raw_page.get("items")) is list
        and any(
            type(raw_item) is dict
            and type(raw_item.get("table_evidence")) is dict
            for raw_item in raw_page["items"]
        )
        for raw_page in raw_pages
    )
    present = "canonical_source_custody" in value
    if marked and not present:
        raise ValueError("marked table canonical source custody is absent")
    if not marked and not present:
        return None
    if not marked:
        raise ValueError("canonical source custody requires a literal table marker")
    raw_sidecar = value.get("canonical_source_custody")
    if (
        type(raw_sidecar) is dict
        and "canonical_presentation_sha256" not in raw_sidecar
    ):
        raise ValueError(
            "marked table canonical presentation custody digest is absent"
        )
    sidecar = _raw_table_object(
        raw_sidecar,
        _CUSTODY_SIDECAR_KEYS,
        "canonical source custody",
    )
    _raw_table_hash(
        sidecar.get("canonical_presentation_sha256"),
        "canonical source custody canonical presentation SHA-256",
    )
    records = sidecar.get("records")
    record_count = sidecar.get("record_count")
    if (
        type(records) is not list
        or len(records) > _CUSTODY_MAX_RECORDS
        or type(record_count) is not int
        or record_count != len(records)
    ):
        raise ValueError("canonical source custody record count differs")
    for raw_record in records:
        if type(raw_record) is not dict:
            raise ValueError(
                "canonical source custody record must be an exact object"
            )
        record_keys = set(raw_record)
        if (
            not _CUSTODY_RECORD_KEYS - _CUSTODY_OPTIONAL_NULL_RECORD_KEYS
            <= record_keys
            or not record_keys <= _CUSTODY_RECORD_KEYS
        ):
            raise ValueError(
                "Extra inputs are not permitted in canonical source custody record"
            )
        record = raw_record
        if (
            _bounded_table_json_size(record, _CUSTODY_MAX_RECORD_BYTES)
            is None
        ):
            raise ValueError("canonical source custody record exceeds its byte cap")
    encoded_size = _bounded_table_json_size(
        sidecar,
        _CUSTODY_MAX_DOCUMENT_BYTES,
    )
    if encoded_size is None:
        raise ValueError("canonical source custody exceeds its document byte cap")
    return encoded_size


def _table_ids_are_strictly_increasing(values: Sequence[str]) -> bool:
    return all(
        left < right
        for left, right in zip(
            values,
            values[1:],
            strict=False,
        )
    )


def _bounded_running_string(
    value: str,
    *,
    maximum_bytes: int = 512,
    single_line: bool = False,
) -> str:
    if (
        not value
        or len(value.encode("utf-8")) > maximum_bytes
        or unicodedata.normalize("NFC", value) != value
        or (single_line and value != value.strip())
        or (single_line and ("\n" in value or "\r" in value))
    ):
        raise ValueError("running-region string is unsafe or oversized")
    for character in value:
        point = ord(character)
        if (
            unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
            or 0xFDD0 <= point <= 0xFDEF
            or point & 0xFFFF in {0xFFFE, 0xFFFF}
        ):
            raise ValueError("running-region string contains an unsafe character")
    return value


def _bounded_label_string(value: str, *, maximum_bytes: int) -> str:
    _bounded_running_string(value, maximum_bytes=maximum_bytes, single_line=True)
    if any(
        not (character.isalpha() or character.isdigit())
        and character not in _SAFE_LABEL_PUNCTUATION
        for character in value
    ):
        raise ValueError("page identity label contains unsupported punctuation")
    return value


def _strict_model_json_size(value: BaseModel) -> int:
    return len(
        json.dumps(
            value.model_dump(mode="json"),
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _strict_number(value: Any, *, nullable: bool = False) -> Any:
    if value is None and nullable:
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("running-region numeric value is not strict")
    return value


def _strict_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ValueError("running-region value is not strict JSON") from exc


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_strict_json_bytes(value)).hexdigest()


def _canonical_presentation_sha256(value: Any) -> str:
    """Return the strict canonical-JSON digest used by final P04 custody."""

    return _sha256_json(value)


def _context_free_visual_ledger_mode_payload(
    payload: Mapping[str, Any],
) -> str | None:
    required = {
        "detected_text",
        "items",
        "ocr_text",
        "raw_ocr_text",
    }
    if not required <= set(payload):
        return None
    raw_ocr_text = payload.get("raw_ocr_text")
    ocr_text = payload.get("ocr_text")
    diagnostics = payload.get("items")
    detected_text = payload.get("detected_text")
    if (
        raw_ocr_text == ""
        and ocr_text == ""
        and diagnostics == []
        and detected_text is False
    ):
        return "empty"
    if not (
        type(raw_ocr_text) is str
        and bool(raw_ocr_text)
        and type(ocr_text) is str
        and bool(ocr_text)
        and type(diagnostics) is list
        and bool(diagnostics)
        and len(diagnostics) <= _MAX_CONTEXT_FREE_RAW_REF_ORDINALS
        and detected_text is True
    ):
        return None
    diagnostic_lines: list[str] = []
    accepted_lines: list[str] = []
    for diagnostic in diagnostics:
        if (
            type(diagnostic) is not dict
            or diagnostic.get("source") != "ocr"
            or type(diagnostic.get("text")) is not str
            or not diagnostic["text"]
            or diagnostic["text"] != diagnostic["text"].strip()
            or type(diagnostic.get("accepted")) is not bool
            or (
                "value" in diagnostic
                and diagnostic.get("value") != diagnostic["text"]
            )
        ):
            return None
        diagnostic_lines.append(diagnostic["text"])
        if diagnostic["accepted"]:
            accepted_lines.append(diagnostic["text"])
    if not accepted_lines:
        return None
    if (
        "\n".join(diagnostic_lines) == raw_ocr_text
        and "\n".join(accepted_lines) == ocr_text
    ):
        return "nonempty"

    # Some P03 ledgers retain overlapping word/line detections while their
    # public OCR strings deterministically keep only the first exact text
    # occurrence.  Admit that one representation only when both strings are
    # the exact stable first-occurrence de-duplication of their ledgers.
    def first_occurrences(lines: Sequence[str]) -> list[str]:
        seen: set[str] = set()
        retained: list[str] = []
        for line in lines:
            if line in seen:
                continue
            seen.add(line)
            retained.append(line)
        return retained

    deduplicated_diagnostics = first_occurrences(diagnostic_lines)
    deduplicated_accepted = first_occurrences(accepted_lines)
    if (
        len(deduplicated_diagnostics) == len(diagnostic_lines)
        or "\n".join(deduplicated_diagnostics) != raw_ocr_text
        or "\n".join(deduplicated_accepted) != ocr_text
    ):
        return None
    return "nonempty_deduplicated"


def _context_free_ir_identity_projection(
    ir: Any,
    source_sensitive_owners: Mapping[
        str,
        tuple[str, tuple[tuple[str, int], ...]],
    ],
) -> tuple[Any, ...]:
    """Hash the complete IR after one exact visual-source normalization."""

    if type(source_sensitive_owners) is not dict:
        raise ValueError("marked table context-free owner proof differs")
    elements_by_id = {element.id: element for element in ir.elements}
    evidence_by_id = {record.id: record for record in ir.evidence}
    bboxes_by_id = {bbox.id: bbox for bbox in ir.bboxes}
    if (
        len(elements_by_id) != len(ir.elements)
        or len(evidence_by_id) != len(ir.evidence)
        or len(bboxes_by_id) != len(ir.bboxes)
    ):
        raise ValueError("marked table context-free IR identity repeats")

    relationship_type_by_collection = {
        "caption": "caption_of",
        "captions": "caption_of",
        "source_note": "source_note_of",
        "source_notes": "source_note_of",
        "footnote": "footnote_of",
        "footnotes": "footnote_of",
        "legend": "legend_of",
        "legends": "legend_of",
        "axis": "axis_of",
        "axes": "axis_of",
        "alternative": "alternative_of",
        "alternatives": "alternative_of",
        "annotation": "annotation_of",
        "annotations": "annotation_of",
    }
    child_tokens: dict[str, str] = {}
    relationship_tokens: dict[str, str] = {}
    evidence_tokens: dict[str, str] = {}
    bbox_tokens: dict[str, str] = {}
    dropped_evidence_ids: set[str] = set()
    owner_sources: dict[str, str] = {}
    semantic_closures: dict[str, tuple[Any, ...]] = {}

    def method_name(record: Any) -> str:
        return str(getattr(record.method, "value", record.method))

    def evidence_for(element: Any) -> list[Any]:
        try:
            records = [evidence_by_id[value] for value in element.evidence_ids]
        except KeyError as exc:
            raise ValueError(
                "marked table context-free evidence binding differs"
            ) from exc
        if any(record.element_id != element.id for record in records):
            raise ValueError("marked table context-free evidence owner differs")
        return records

    for owner_id in sorted(source_sensitive_owners):
        owner_spec = source_sensitive_owners[owner_id]
        if (
            type(owner_id) is not str
            or not owner_id
            or type(owner_spec) is not tuple
            or len(owner_spec) != 2
            or owner_spec[0]
            not in {"empty", "nonempty", "nonempty_deduplicated"}
            or type(owner_spec[1]) is not tuple
            or not owner_spec[1]
            or any(
                type(value) is not tuple
                or len(value) != 2
                or type(value[0]) is not str
                or value[0] not in relationship_type_by_collection
                or type(value[1]) is not int
                or value[1] < 0
                for value in owner_spec[1]
            )
            or len(set(owner_spec[1])) != len(owner_spec[1])
        ):
            raise ValueError("marked table context-free owner proof differs")
        ledger_mode, expected_children = owner_spec
        owner = elements_by_id.get(owner_id)
        legacy_item = (
            owner.properties.get("legacy_item")
            if owner is not None and type(owner.properties) is dict
            else None
        )
        source = (
            legacy_item.get("source")
            if type(legacy_item) is dict
            else None
        )
        if (
            owner is None
            or owner.presentation_role != "primary"
            or source not in {"derived", "ocr"}
            or _context_free_visual_ledger_mode_payload(legacy_item)
            != ledger_mode
        ):
            raise ValueError("marked table context-free owner source differs")
        owner_sources[owner_id] = source

        owner_records = evidence_for(owner)
        ocr_value = legacy_item.get("ocr_text")
        expected_evidence = (
            [(source, "")]
            if ledger_mode == "empty"
            else (
                [("derived", ""), ("ocr", ocr_value)]
                if source == "derived"
                else [("ocr", ocr_value)]
            )
        )
        if len(owner_records) != len(expected_evidence):
            raise ValueError("marked table context-free owner evidence differs")
        for evidence_index, (record, expected) in enumerate(
            zip(owner_records, expected_evidence, strict=True)
        ):
            expected_method, expected_value = expected
            payload = record.model_dump(mode="json")
            metadata = payload.get("metadata")
            if (
                method_name(record) != expected_method
                or record.value != expected_value
                or record.bbox_id
                != (owner.bbox_ids[0] if len(owner.bbox_ids) == 1 else None)
                or type(metadata) is not dict
                or metadata.get("source") != source
            ):
                raise ValueError(
                    "marked table context-free owner evidence differs"
                )
            if ledger_mode == "empty":
                evidence_tokens[record.id] = (
                    "compat-owner-evidence-"
                    f"{_sha256_json((owner_id, evidence_index))}"
                )
            elif source == "derived" and evidence_index == 0:
                dropped_evidence_ids.add(record.id)

        expected_child_keys = set(expected_children)
        observed_child_keys: set[tuple[str, int]] = set()
        child_closures: list[tuple[Any, ...]] = []
        for relationship in ir.relationships:
            if relationship.target_id != owner_id:
                continue
            child = elements_by_id.get(relationship.source_id)
            if child is None or type(child.properties) is not dict:
                continue
            child_key = (
                str(child.properties.get("collection") or ""),
                child.properties.get("index"),
            )
            if child_key not in expected_child_keys:
                continue
            relationship_type = str(
                getattr(relationship.type, "value", relationship.type)
            )
            expected_relationship_type = relationship_type_by_collection[
                child_key[0]
            ]
            legacy_child = child.properties.get("legacy_child")
            expected_role = (
                "alternate"
                if expected_relationship_type == "alternative_of"
                else "subordinate"
            )
            if (
                child_key in observed_child_keys
                or relationship_type != expected_relationship_type
                or child.properties.get("parent_element_id") != owner_id
                or child.presentation_role != expected_role
                or type(legacy_child) is not dict
                or legacy_child.get("source") != source
            ):
                raise ValueError(
                    "marked table context-free semantic-child binding differs"
                )
            observed_child_keys.add(child_key)
            signature = (
                owner_id,
                relationship_type,
                child.page_id,
                child.type,
                child.presentation_role,
                child_key[0],
                child_key[1],
            )
            child_token = f"compat-child-{_sha256_json(signature)}"
            relationship_token = (
                "compat-relationship-"
                f"{_sha256_json((*signature, 'relationship'))}"
            )
            if (
                child.id in child_tokens
                or relationship.id in relationship_tokens
                or child_token in child_tokens.values()
                or relationship_token in relationship_tokens.values()
            ):
                raise ValueError(
                    "marked table context-free semantic-child identity repeats"
                )
            child_tokens[child.id] = child_token
            relationship_tokens[relationship.id] = relationship_token

            if len(child.bbox_ids) > 1:
                raise ValueError(
                    "marked table context-free semantic-child bbox differs"
                )
            for bbox_index, bbox_id in enumerate(child.bbox_ids):
                bbox = bboxes_by_id.get(bbox_id)
                if bbox is None:
                    raise ValueError(
                        "marked table context-free semantic-child bbox differs"
                    )
                bbox_tokens[bbox_id] = (
                    "compat-child-bbox-"
                    f"{_sha256_json((*signature, bbox_index))}"
                )

            child_records = evidence_for(child)
            if len(child_records) != 1:
                raise ValueError(
                    "marked table context-free semantic-child evidence differs"
                )
            [child_record] = child_records
            child_evidence_payload = child_record.model_dump(mode="json")
            child_metadata = child_evidence_payload.get("metadata")
            if (
                method_name(child_record) != source
                or type(child_metadata) is not dict
                or child_metadata.get("source") != source
                or child_metadata.get("collection") != child_key[0]
                or child_metadata.get("index") != child_key[1]
                or child_record.bbox_id
                != (child.bbox_ids[0] if child.bbox_ids else None)
                or list(relationship.evidence_ids) != [child_record.id]
            ):
                raise ValueError(
                    "marked table context-free semantic-child evidence differs"
                )
            evidence_token = (
                "compat-child-evidence-"
                f"{_sha256_json((*signature, 'evidence'))}"
            )
            if (
                child_record.id in evidence_tokens
                or evidence_token in evidence_tokens.values()
            ):
                raise ValueError(
                    "marked table context-free semantic-child evidence repeats"
                )
            evidence_tokens[child_record.id] = evidence_token
            child_closures.append(
                (
                    signature,
                    child.id,
                    tuple(child.bbox_ids),
                    child_record.id,
                    relationship.id,
                )
            )
        if observed_child_keys != expected_child_keys:
            raise ValueError(
                "marked table context-free semantic-child coverage differs"
            )
        semantic_closures[owner_id] = (
            ledger_mode,
            source,
            tuple(
                (method_name(record), record.id)
                for record in owner_records
            ),
            tuple(sorted(child_closures)),
        )

    reference_tokens = {
        **child_tokens,
        **relationship_tokens,
        **evidence_tokens,
        **bbox_tokens,
    }

    def replace_references(value: Any) -> Any:
        if type(value) is str:
            return reference_tokens.get(value, value)
        if type(value) is list:
            return [replace_references(member) for member in value]
        if type(value) is tuple:
            return tuple(replace_references(member) for member in value)
        if type(value) is dict:
            return {
                key: replace_references(member)
                for key, member in value.items()
            }
        return value

    def normalized_element(element: Any) -> dict[str, Any]:
        payload = element.model_dump(mode="json")
        if element.id in owner_sources:
            payload["evidence_ids"] = [
                value
                for value in payload.get("evidence_ids", [])
                if value not in dropped_evidence_ids
            ]
            legacy = payload.get("properties", {}).get("legacy_item")
            if (
                type(legacy) is not dict
                or legacy.get("source") != owner_sources[element.id]
            ):
                raise ValueError(
                    "marked table context-free owner source differs"
                )
            legacy["source"] = "compat-visual-source"
        elif element.id in child_tokens:
            legacy_child = payload.get("properties", {}).get("legacy_child")
            owner_id = payload.get("properties", {}).get("parent_element_id")
            if (
                type(legacy_child) is not dict
                or owner_id not in owner_sources
                or legacy_child.get("source") != owner_sources[owner_id]
            ):
                raise ValueError(
                    "marked table context-free semantic-child source differs"
                )
            legacy_child["source"] = "compat-visual-source"
        return replace_references(payload)

    def normalized_evidence(record: Any) -> dict[str, Any]:
        payload = record.model_dump(mode="json")
        normalized_source: str | None = None
        if record.element_id in owner_sources:
            normalized_source = owner_sources[record.element_id]
        elif record.element_id in child_tokens:
            child = elements_by_id[record.element_id]
            owner_id = child.properties.get("parent_element_id")
            normalized_source = owner_sources.get(owner_id)
            if method_name(record) != normalized_source:
                raise ValueError(
                    "marked table context-free semantic-child evidence differs"
                )
            payload["method"] = "compat-visual-source"
        if normalized_source is not None:
            metadata = payload.get("metadata")
            if (
                type(metadata) is not dict
                or metadata.get("source") != normalized_source
            ):
                raise ValueError(
                    "marked table context-free evidence source differs"
                )
            metadata["source"] = "compat-visual-source"
            if record.element_id in owner_sources and (
                source_sensitive_owners[record.element_id][0] == "empty"
            ):
                if method_name(record) != normalized_source or record.value != "":
                    raise ValueError(
                        "marked table context-free owner evidence differs"
                    )
                payload["method"] = "compat-visual-source"
        return replace_references(payload)

    def record_projection(
        values: Sequence[Any],
        normalizer: Any = None,
        *,
        omitted_ids: set[str] | None = None,
    ) -> tuple[tuple[str, str], ...]:
        projected: list[tuple[str, str]] = []
        omitted = omitted_ids or set()
        for index, value in enumerate(values):
            if getattr(value, "id", None) in omitted:
                continue
            payload = (
                normalizer(value)
                if normalizer is not None
                else replace_references(value.model_dump(mode="json"))
            )
            identity = str(payload.get("id", f"index:{index}"))
            projected.append((identity, _sha256_json(payload)))
        return tuple(projected)

    collections = (
        ("coordinate_systems", record_projection(ir.coordinate_systems)),
        ("bboxes", record_projection(ir.bboxes)),
        ("pages", record_projection(ir.pages)),
        ("regions", record_projection(ir.regions)),
        ("elements", record_projection(ir.elements, normalized_element)),
        (
            "evidence",
            record_projection(
                ir.evidence,
                normalized_evidence,
                omitted_ids=dropped_evidence_ids,
            ),
        ),
        ("text_rules", record_projection(ir.text_rules)),
        ("text_runs", record_projection(ir.text_runs)),
        ("relationships", record_projection(ir.relationships)),
        ("concerns", record_projection(ir.concerns)),
    )
    header = _sha256_json(
        {
            "ir_version": ir.ir_version,
            "id": ir.id,
            "source_sha256": ir.source_sha256,
        }
    )
    return (
        header,
        collections,
        tuple(
            (owner_id, *semantic_closures[owner_id])
            for owner_id in sorted(semantic_closures)
        ),
    )


def _context_free_ir_delta_is_closed(
    base: tuple[Any, ...],
    alternate: tuple[Any, ...],
    deferred_owner_ids: set[str],
) -> bool:
    if (
        type(base) is not tuple
        or type(alternate) is not tuple
        or len(base) != 3
        or len(alternate) != 3
        or base[:2] != alternate[:2]
        or not deferred_owner_ids
    ):
        return False
    try:
        base_closures = {value[0]: value[1:] for value in base[2]}
        alternate_closures = {value[0]: value[1:] for value in alternate[2]}
    except (IndexError, TypeError):
        return False
    if set(base_closures) != set(alternate_closures):
        return False
    if set(base_closures) != deferred_owner_ids:
        return False
    for owner_id in base_closures:
        base_closure = base_closures[owner_id]
        alternate_closure = alternate_closures[owner_id]
        if (
            len(base_closure) != 4
            or len(alternate_closure) != 4
            or base_closure[0] != alternate_closure[0]
            or base_closure[1] != "derived"
            or alternate_closure[1] != "ocr"
            or len(base_closure[3]) != len(alternate_closure[3])
        ):
            return False
        ledger_mode = base_closure[0]
        base_owner_evidence = base_closure[2]
        alternate_owner_evidence = alternate_closure[2]
        if ledger_mode == "empty":
            if not (
                len(base_owner_evidence) == len(alternate_owner_evidence) == 1
                and base_owner_evidence[0][0] == "derived"
                and alternate_owner_evidence[0][0] == "ocr"
                and base_owner_evidence[0][1]
                != alternate_owner_evidence[0][1]
            ):
                return False
        elif ledger_mode in {"nonempty", "nonempty_deduplicated"}:
            if not (
                len(base_owner_evidence) == 2
                and len(alternate_owner_evidence) == 1
                and base_owner_evidence[0][0] == "derived"
                and base_owner_evidence[1][0] == "ocr"
                and alternate_owner_evidence[0][0] == "ocr"
                and base_owner_evidence[1][1]
                == alternate_owner_evidence[0][1]
                and base_owner_evidence[0][1]
                != base_owner_evidence[1][1]
            ):
                return False
        else:
            return False
        for base_child, alternate_child in zip(
            base_closure[3],
            alternate_closure[3],
            strict=True,
        ):
            if (
                len(base_child) != 5
                or len(alternate_child) != 5
                or base_child[0] != alternate_child[0]
                or base_child[1] == alternate_child[1]
                or base_child[3] == alternate_child[3]
                or base_child[4] == alternate_child[4]
                or len(base_child[2]) != len(alternate_child[2])
                or any(
                    left == right
                    for left, right in zip(
                        base_child[2],
                        alternate_child[2],
                        strict=True,
                    )
                )
            ):
                return False
    return True


def _stable_running_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_sha256_json(parts)[:20]}"


def _public_item_payload(item: ContentItem) -> dict[str, Any]:
    dumped = item.model_dump(mode="json")
    return {
        key: dumped[key]
        for key in item.model_fields_set
        if key in dumped and dumped[key] is not None
    }


def _predecessor_item_payload(
    item: ContentItem,
    predecessor_type: str,
) -> dict[str, Any]:
    payload = _public_item_payload(item)
    for key in _RUNNING_MARKER_KEYS:
        payload.pop(key, None)
    payload["type"] = predecessor_type
    return payload


def _layout_predecessor_item_payload(item: ContentItem) -> dict[str, Any]:
    """Return the exact public item used for the primary IR rebuild."""

    return item.model_dump(mode="json", exclude_unset=True)


def _context_free_visual_ocr_predecessor_is_closed(
    item: ContentItem,
) -> bool:
    """Admit one exact P03 visual-source compatibility alternative."""

    extras = item.model_extra or {}
    forbidden_owners = {
        "form_group",
        "layout_forms_projected",
        "outline_group",
        "outline_items",
        "layout_outline_structure_projected",
        *_RUNNING_MARKER_KEYS,
    }
    contains_ids = extras.get("contains_ids")
    contained_items = extras.get("contained_items")
    if not (
        item.table_evidence is None
        and item.running_region is None
        and item.type.casefold() in {"image", "chart", "diagram"}
        and extras.get("content_type") == item.type.casefold()
        and extras.get("layout_visual_relationships_projected") is True
        and item.source == "derived"
        and item.value == ""
        and item.md
        == (
            f"[{item.type.casefold().capitalize()} detected; "
            "no reliable text extracted.]"
        )
        and item.bbox is not None
        and item.bbox.width > 0
        and item.bbox.height > 0
        and type(extras.get("include_ocr_in_primary")) is bool
        and not forbidden_owners.intersection(item.model_fields_set)
        and _context_free_visual_ledger_mode_payload(extras) is not None
        and type(contains_ids) is list
        and bool(contains_ids)
        and len(contains_ids) == len(set(contains_ids))
        and type(contained_items) is list
        and len(contained_items) == len(contains_ids)
    ):
        return False

    for contained_id, contained in zip(
        contains_ids,
        contained_items,
        strict=True,
    ):
        if (
            type(contained_id) is not str
            or not contained_id
            or type(contained) is not dict
            or contained.get("id") != contained_id
            or contained.get("contained_by") != item.id
            or contained.get("type") != "visual_text"
            or contained.get("presentation_role") != "subordinate"
            or contained.get("relationship_type") != "contains"
            or contained.get("relationship_basis") != "graph_and_geometry"
            or type(contained.get("relationship_id")) is not str
            or not contained["relationship_id"]
            or type(contained.get("value")) is not str
            or not contained["value"].strip()
        ):
            return False

    return bool(_context_free_visual_source_sensitive_children(item))


def _context_free_visual_source_sensitive_children(
    item: ContentItem,
) -> tuple[tuple[str, int], ...]:
    extras = item.model_extra or {}
    source_sensitive: list[tuple[str, int]] = []
    for field in (
        "annotation",
        "annotations",
        "axis",
        "axes",
        "legend",
        "legends",
        "alternative",
        "alternatives",
        "source_note",
        "source_notes",
        "footnote",
        "footnotes",
    ):
        raw_children = extras.get(field)
        children = (
            raw_children
            if type(raw_children) is list
            else [raw_children]
        )
        for child_index, child in enumerate(children):
            if (
                type(child) is dict
                and child
                and "source" not in child
                and not {
                    "caption_generated",
                    "embedded_images",
                    "engine",
                    "evidence_methods",
                }.intersection(child)
            ):
                source_sensitive.append((field, child_index))
    return tuple(source_sensitive)


def _safe_layout_note_target(value: Any) -> str | None:
    if type(value) is not str or not value:
        return None
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        return None
    if (
        len(encoded) > _LAYOUT_NOTE_MAX_URI_BYTES
        or any(ord(character) < 0x21 or ord(character) > 0x7E for character in value)
    ):
        return None
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        return None
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.netloc
        or hostname is None
        or "\\" in value
        or parsed.username is not None
        or parsed.password is not None
        or (port is not None and not (0 < port <= 65535))
    ):
        return None
    return value


def _layout_note_basis_is_closed(item: ContentItem) -> bool:
    """Validate the exact public proof carried by a P03-US03 note basis."""

    extras = item.model_extra or {}
    basis = extras.get("relationship_basis")
    if basis not in (
        {"graph_and_geometry"}
        | _LAYOUT_NOTE_NONLINK_BASES
        | _LAYOUT_NOTE_LINK_BASES
    ):
        return False
    if item.source not in {"native", "ocr", "mixed"}:
        return False
    if type(item.value) is not str or not item.value.strip():
        return False
    try:
        if len(item.value.encode("utf-8")) > _LAYOUT_NOTE_MAX_VALUE_BYTES:
            return False
    except UnicodeEncodeError:
        return False

    links_present = "links" in extras
    links = extras.get("links")
    if basis in _LAYOUT_NOTE_NONLINK_BASES:
        if links_present:
            return False
        return basis != "ocr_and_geometry" or item.source == "ocr"

    # A declared graph relationship may independently carry the same bounded
    # source-visible link evidence.  Annotation/link bases require it.
    if not links_present:
        return basis == "graph_and_geometry"
    if (
        type(links) is not list
        or not links
        or len(links) > _LAYOUT_NOTE_MAX_LINKS
    ):
        return False
    seen: set[tuple[str, str]] = set()
    for link in links:
        if type(link) is not dict or set(link) != {"kind", "target"}:
            return False
        kind = link.get("kind")
        target = link.get("target")
        if (
            type(kind) is not str
            or kind not in {"hyperlink", "source_link", "statlink"}
            or _safe_layout_note_target(target) != target
            or target not in item.value
            or (kind, target) in seen
        ):
            return False
        seen.add((kind, target))
    return True


def _contains_running_region_remnant(value: Any) -> bool:
    if isinstance(value, BaseModel):
        return _contains_running_region_remnant(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        if _RUNNING_MARKER_KEYS.intersection(value) or any(
            isinstance(key, str)
            and key.startswith(
                ("running_region", "layout_running_region", "page_identity")
            )
            for key in value
        ):
            return True
        return any(
            _contains_running_region_remnant(member) for member in value.values()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_running_region_remnant(member) for member in value)
    return False


def _model_bbox_payload(
    value: BoundingBox | RunningRegionBoundingBox,
) -> dict[str, Any]:
    return {
        "x": float(value.x),
        "y": float(value.y),
        "width": float(value.width),
        "height": float(value.height),
        "unit": value.unit,
    }


def _same_bbox(
    left: BoundingBox | RunningRegionBoundingBox,
    right: BoundingBox | RunningRegionBoundingBox,
) -> bool:
    return _model_bbox_payload(left) == _model_bbox_payload(right)


def _bounded_extracted_text(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("extracted running-region text differs")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("extracted running-region text is not Unicode") from exc
    if (
        len(encoded) > _MAX_EXTRACTED_CONTRIBUTION_BYTES
        or value != value.strip()
        or unicodedata.normalize("NFC", value) != value
    ):
        raise ValueError("extracted running-region text is unsafe or oversized")
    for character in value:
        point = ord(character)
        if (
            unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
            or 0xFDD0 <= point <= 0xFDEF
            or point & 0xFFFF in {0xFFFE, 0xFFFF}
        ):
            raise ValueError(
                "extracted running-region text contains an unsafe character"
            )
    return value


def _canonical_views_from_blocks(
    page: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    blocks = page.get("blocks")
    if not isinstance(blocks, list) or any(
        not isinstance(block, Mapping) for block in blocks
    ):
        raise ValueError("canonical running-region page blocks differ")
    block_ids = [block.get("id") for block in blocks]
    if any(
        not isinstance(block_id, str) or not block_id for block_id in block_ids
    ) or len(block_ids) != len(set(block_ids)):
        raise ValueError("canonical running-region block IDs differ")
    included = [block for block in blocks if block.get("omission_reason") is None]
    scoped: dict[str, list[str]] = {"body": [], "header": [], "footer": []}
    for block in included:
        scope = block.get("scope")
        if scope not in scoped:
            raise ValueError("canonical running-region block scope differs")
        scoped[scope].append(str(block["id"]))
    by_id = {str(block["id"]): block for block in included}

    def render(ids: Sequence[str], field: str) -> str:
        values: list[str] = []
        for block_id in ids:
            value = by_id[block_id].get(field)
            if not isinstance(value, str):
                raise ValueError("canonical running-region block scalar differs")
            stripped = value.strip()
            if stripped:
                values.append(stripped)
        return "\n\n".join(values).rstrip() + "\n" if values else ""

    view_ids = {"full": [str(block["id"]) for block in included], **scoped}
    return {
        name: {
            "block_ids": ids,
            "markdown": render(ids, "markdown"),
            "text": render(ids, "text"),
        }
        for name, ids in view_ids.items()
    }


def _validate_canonical_page_views(page: Mapping[str, Any]) -> None:
    for name, expected in _canonical_views_from_blocks(page).items():
        value = page.get(name)
        if not isinstance(value, Mapping) or dict(value) != expected:
            raise ValueError(f"canonical running-region {name} view differs")


def _canonical_document_views(
    pages: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name in ("full", "body", "header", "footer"):
        block_ids: list[str] = []
        markdown_pages: list[str] = []
        text_pages: list[str] = []
        for page in pages:
            view = page.get(name)
            if not isinstance(view, Mapping) or set(view) != {
                "block_ids",
                "markdown",
                "text",
            }:
                raise ValueError("canonical running-region page view differs")
            ids = view.get("block_ids")
            markdown = view.get("markdown")
            text = view.get("text")
            if (
                not isinstance(ids, list)
                or any(not isinstance(value, str) or not value for value in ids)
                or not isinstance(markdown, str)
                or not isinstance(text, str)
            ):
                raise ValueError("canonical running-region page view differs")
            block_ids.extend(ids)
            if stripped := markdown.strip():
                markdown_pages.append(stripped)
            if stripped := text.strip():
                text_pages.append(stripped)

        def render(values: Sequence[str]) -> str:
            return "\n\n".join(values).rstrip() + "\n" if values else ""

        result[name] = {
            "block_ids": block_ids,
            "markdown": render(markdown_pages),
            "text": render(text_pages),
        }
    return result


def _canonical_ir_id(prefix: str, *parts: Any) -> str:
    """Reproduce the public-to-IR identity used by canonical presentation."""

    encoded = json.dumps(
        parts,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:20]}"


def _canonical_item_primary_id(
    document_id: str,
    page_index: int,
    item_offset: int,
    item: ContentItem,
) -> str:
    legacy_id = item.id.strip()
    item_identity: tuple[Any, ...] = (
        ("legacy_id", legacy_id)
        if legacy_id
        else (
            "fallback",
            item_offset,
            item.type,
            item.reading_order,
            item.value,
            item.bbox.model_dump(mode="json") if item.bbox is not None else None,
        )
    )
    return _canonical_ir_id(
        "el",
        document_id,
        page_index,
        item_identity,
    )


def _canonical_table_text(item: ContentItem) -> str:
    """Render the strict P04 row projection as canonical semantic text."""

    rows = (item.model_extra or {}).get("rows")
    if type(rows) is not list or any(
        type(row) is not list or any(type(cell) is not str for cell in row)
        for row in rows
    ):
        raise ValueError("marked table canonical rows differ")
    return "\n".join(
        "\t".join(cell.strip() for cell in row).rstrip() for row in rows
    ).strip()


def _canonical_plain_value(value: Any) -> str:
    """Render the public scalar using canonical presentation's plain rules."""

    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        lines: list[str] = []
        for key in sorted(value, key=str):
            rendered = _canonical_plain_value(value[key])
            if rendered:
                lines.append(f"{key}: {rendered}")
        return "\n".join(lines).strip()
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        if all(
            isinstance(row, Sequence)
            and not isinstance(row, (str, bytes, bytearray))
            for row in value
        ):
            return "\n".join(
                "\t".join(_canonical_plain_value(cell) for cell in row).rstrip()
                for row in value
            ).strip()
        return "\n".join(
            rendered
            for member in value
            if (rendered := _canonical_plain_value(member))
        ).strip()
    return str(value).strip()


def _canonical_nested_outputs(raw_items: Any) -> tuple[str, str] | None:
    if type(raw_items) is not list or not raw_items:
        return None
    markdown_values: list[str] = []
    text_values: list[str] = []
    for raw_item in raw_items:
        if type(raw_item) is not dict or raw_item.get("accepted") is False:
            continue
        markdown = raw_item.get("md")
        markdown_value = (
            markdown.strip()
            if type(markdown) is str and markdown.strip()
            else _canonical_plain_value(
                raw_item.get("text", raw_item.get("value"))
            )
        )
        text_value = _canonical_plain_value(
            raw_item.get("text", raw_item.get("value"))
        )
        if markdown_value:
            markdown_values.append(markdown_value)
        if text_value:
            text_values.append(text_value)
    if not markdown_values and not text_values:
        return None
    return "\n\n".join(markdown_values), "\n\n".join(text_values)


def _canonical_public_item_output(item: ContentItem) -> tuple[str, str]:
    """Return content directly authorized by a public primary item."""

    extras = item.model_extra or {}
    item_type = item.type.casefold()
    value = _canonical_plain_value(item.value)
    markdown = item.md.strip() if isinstance(item.md, str) else ""
    if item_type == "table":
        raw_html = extras.get("html")
        if type(raw_html) is not str:
            raise ValueError("marked table canonical Markdown differs")
        return raw_html.strip(), _canonical_table_text(item)
    if item_type == "heading":
        if markdown:
            return markdown, value or markdown
        try:
            level = min(max(int(extras.get("level") or 1), 1), 6)
        except (TypeError, ValueError):
            level = 1
        return (f"{'#' * level} {value}" if value else ""), value
    if item_type == "code" and value:
        language = str(extras.get("language") or "").strip()
        return f"```{language}\n{value}\n```", value
    if item_type == "formula" and value:
        return f"$$\n{value}\n$$", value
    if item_type in {"header", "footer"}:
        nested = _canonical_nested_outputs(extras.get("items"))
        if nested is not None:
            return nested
    return markdown or value, value or markdown


def _canonical_expected_primary_id(
    document_id: str,
    page_index: int,
    item_offset: int,
    item: ContentItem,
) -> str:
    if item.running_region is not None:
        return item.running_region.source_element_id
    extras = item.model_extra or {}
    outline_group = extras.get("outline_group")
    if type(outline_group) is dict and (
        outline_group.get("anchor_public_item_id") == item.id
        and type(outline_group.get("canonical_primary_element_id")) is str
    ):
        return outline_group["canonical_primary_element_id"]
    form_group = extras.get("form_group")
    if type(form_group) is dict and (
        form_group.get("anchor_public_item_id") == item.id
        and type(form_group.get("anchor_element_id")) is str
    ):
        return form_group["anchor_element_id"]
    if re.fullmatch(r"el-[0-9a-f]{20}", item.id.strip()):
        return item.id.strip()
    return _canonical_item_primary_id(
        document_id,
        page_index,
        item_offset,
        item,
    )


def _context_free_inert_raw_group_owner_is_closed(
    item: ContentItem,
    primary_id: str,
) -> bool:
    """Limit inert raw-group replay to legacy text or an exact inert form anchor."""

    if item.table_evidence is not None or not primary_id:
        return False
    if item.type.casefold() == "text":
        return True
    extras = item.model_extra or {}
    form_group = extras.get("form_group")
    return (
        item.type.casefold() == "heading"
        and extras.get("layout_forms_projected") is True
        and type(form_group) is dict
        and form_group.get("canonical_mode") == "inert"
        and form_group.get("anchor_public_item_id") == item.id
        and form_group.get("anchor_element_id") == primary_id
        and form_group.get("contributor_public_item_ids") == [item.id]
        and form_group.get("contributor_element_ids") == [primary_id]
    )


def _canonical_expected_block_id(
    page_id: str,
    primary_id: str,
    item: ContentItem,
) -> str:
    if item.running_region is not None:
        return item.running_region.canonical_block_id
    outline_group = (item.model_extra or {}).get("outline_group")
    if type(outline_group) is dict and (
        outline_group.get("canonical_primary_element_id") == primary_id
        and type(outline_group.get("canonical_block_id")) is str
    ):
        return outline_group["canonical_block_id"]
    return _canonical_ir_id(
        "pb",
        "1.0",
        "canonical-presentation-v1",
        page_id,
        primary_id,
    )


def _canonical_sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_visible_page_label(value: str) -> str:
    if _VISIBLE_INTEGER_RE.fullmatch(value):
        return value
    if match := _VISIBLE_FRACTION_RE.fullmatch(value):
        current, total = int(match.group(1)), int(match.group(2))
        if current <= total:
            return f"{current}/{total}"
    if match := _VISIBLE_PAGE_OF_RE.fullmatch(value):
        current, total = int(match.group(1)), int(match.group(2))
        if current <= total:
            return f"{current} of {total}"
    if match := _VISIBLE_PIPE_RE.fullmatch(value):
        return match.group(1)
    raise ValueError("visible page identity is outside the closed grammar")


def _validate_running_references(
    values: list[str],
    *,
    allow_empty: bool,
) -> list[str]:
    if (not allow_empty and not values) or len(values) > 64:
        raise ValueError("running-region reference count differs")
    if len(values) != len(set(values)):
        raise ValueError("running-region references repeat")
    for value in values:
        _bounded_running_string(value)
    return values


def _validate_running_path(values: list[str | int]) -> list[str | int]:
    if len(values) > 16:
        raise ValueError("running-region public path exceeds its cap")
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise ValueError("running-region public path differs")
        if isinstance(value, str):
            _bounded_running_string(value)
        elif value < 0:
            raise ValueError("running-region public path index differs")
    return values


def _validate_concern_codes(
    values: list[str],
    *,
    allowed: frozenset[str] = _RUNNING_CONCERN_CODES,
) -> list[str]:
    if len(values) > 64 or values != sorted(set(values)):
        raise ValueError("running-region concern codes differ")
    if any(value not in allowed for value in values):
        raise ValueError("running-region concern code is unknown")
    return values


class OutputFormat(str, Enum):
    JSON = "json"
    MARKDOWN = "markdown"
    TEXT = "text"


class BoundingBox(ApiModel):
    """A top-left-origin bounding box in PDF points or image pixels."""

    x: float
    y: float
    width: float = Field(ge=0)
    height: float = Field(ge=0)
    unit: Literal["pt", "px"] = "pt"


class RunningRegionBoundingBox(StrictApiModel):
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    unit: Literal["pt"] = "pt"

    @field_validator("x", "y", "width", "height", mode="before")
    @classmethod
    def validate_numeric_input(cls, value: Any) -> Any:
        return _strict_number(value)

    @model_validator(mode="after")
    def validate_geometry(self) -> RunningRegionBoundingBox:
        if not all(
            math.isfinite(value) for value in (self.x, self.y, self.width, self.height)
        ):
            raise ValueError("running-region bbox values must be finite")
        return self


class RunningRegionConfidence(StrictApiModel):
    scope: Literal["deterministic_rule", "source_metadata", "unavailable"]
    score: float | None = Field(default=None, ge=0, le=1)
    unavailable_reason: str | None = None

    @field_validator("score", mode="before")
    @classmethod
    def validate_score_input(cls, value: Any) -> Any:
        return _strict_number(value, nullable=True)

    @model_validator(mode="after")
    def validate_state(self) -> RunningRegionConfidence:
        if self.score is None:
            if self.scope != "unavailable" or self.unavailable_reason not in {
                "page_identity_source_unavailable",
                "page_identity_display_fallback_physical",
            }:
                raise ValueError("running-region unavailable confidence differs")
        elif (
            not math.isfinite(self.score)
            or self.scope not in {"deterministic_rule", "source_metadata"}
            or self.unavailable_reason is not None
        ):
            raise ValueError("running-region scored confidence differs")
        return self


class PageIdentityEvidenceSource(StrictApiModel):
    method: Literal[
        "native_printed_label",
        "embedded_pdf_label",
        "legacy_display_fallback",
        "physical_page_index",
    ]
    reader: Literal["pdfplumber", "pypdfium2", "configured_predecessor"]
    page_index: StrictInt = Field(ge=1, le=100)
    public_item_id: str | None
    public_path: list[str | int]
    element_id: str | None
    bbox_id: str | None
    evidence_ids: list[str]
    source_object_ids: list[str]

    @field_validator("public_path")
    @classmethod
    def validate_public_path(cls, value: list[str | int]) -> list[str | int]:
        return _validate_running_path(value)

    @field_validator("evidence_ids", "source_object_ids")
    @classmethod
    def validate_references(cls, value: list[str]) -> list[str]:
        return _validate_running_references(value, allow_empty=True)

    @model_validator(mode="after")
    def validate_binding(self) -> PageIdentityEvidenceSource:
        nullable = (self.public_item_id, self.element_id, self.bbox_id)
        attached = all(isinstance(value, str) and value for value in nullable)
        detached = all(value is None for value in nullable)
        for value in nullable:
            if isinstance(value, str):
                _bounded_running_string(value)
        if self.method == "native_printed_label":
            if (
                self.reader != "pdfplumber"
                or len(self.evidence_ids) != 1
                or not self.source_object_ids
                or not (attached or detached)
                or (
                    attached
                    and (
                        len(self.public_path) != 4
                        or self.public_path[0] != "pages"
                        or self.public_path[1] != self.page_index - 1
                        or self.public_path[2] != "items"
                        or isinstance(self.public_path[3], bool)
                        or not isinstance(self.public_path[3], int)
                    )
                )
                or (detached and self.public_path)
            ):
                raise ValueError("native page-label evidence binding differs")
        elif self.method == "embedded_pdf_label":
            if (
                self.reader != "pypdfium2"
                or not detached
                or self.public_path
                or len(self.evidence_ids) != 1
                or not self.source_object_ids
            ):
                raise ValueError("embedded page-label evidence binding differs")
        elif self.method == "legacy_display_fallback":
            if (
                self.reader != "configured_predecessor"
                or not detached
                or self.public_path
                or self.evidence_ids
                or len(self.source_object_ids) != 1
            ):
                raise ValueError("legacy page-label evidence binding differs")
        elif (
            self.reader != "configured_predecessor"
            or not detached
            or self.public_path
            or self.evidence_ids
            or self.source_object_ids
        ):
            raise ValueError("physical page-label evidence binding differs")
        return self


class PageIdentity(StrictApiModel):
    schema_version: Literal["1.0"]
    policy_id: Literal["p03-running-regions-page-identity-v1"]
    page_id: str
    physical_page_index: StrictInt = Field(ge=1, le=100)
    embedded_label: str | None
    detected_printed_label: str | None
    visible_text: str | None
    display_label: str
    display_source: Literal[
        "detected_printed_label",
        "embedded_label",
        "legacy_display_fallback",
        "physical",
    ]
    evidence_bbox: RunningRegionBoundingBox | None
    evidence_source: PageIdentityEvidenceSource
    confidence: RunningRegionConfidence
    concern_codes: list[str]

    @model_validator(mode="after")
    def validate_identity(self) -> PageIdentity:
        _bounded_running_string(self.page_id)
        _bounded_label_string(self.display_label, maximum_bytes=256)
        for value in (self.embedded_label, self.detected_printed_label):
            if value is not None:
                _bounded_label_string(value, maximum_bytes=256)
        if self.visible_text is not None:
            _bounded_label_string(self.visible_text, maximum_bytes=512)
        _validate_concern_codes(
            self.concern_codes, allowed=_PAGE_IDENTITY_CONCERN_CODES
        )
        if self.evidence_source.page_index != self.physical_page_index:
            raise ValueError("page identity evidence page differs")
        detected = self.detected_printed_label is not None
        if detected != (self.visible_text is not None) or detected != (
            self.evidence_bbox is not None
        ):
            raise ValueError("detected page identity evidence is partial")
        if detected and _normalize_visible_page_label(self.visible_text or "") != (
            self.detected_printed_label
        ):
            raise ValueError("detected page identity normalization differs")
        conflict = (
            self.embedded_label is not None
            and self.detected_printed_label is not None
            and self.embedded_label != self.detected_printed_label
        )
        if conflict:
            if (
                self.display_source != "embedded_label"
                or self.display_label != self.embedded_label
                or "page_identity_source_conflict" not in self.concern_codes
            ):
                raise ValueError("page identity conflict precedence differs")
        elif detected:
            if (
                self.display_source != "detected_printed_label"
                or self.display_label != self.detected_printed_label
                or "page_identity_detected_label_ambiguous" in self.concern_codes
            ):
                raise ValueError("detected page identity precedence differs")
        elif self.embedded_label is not None:
            if (
                self.display_source != "embedded_label"
                or self.display_label != self.embedded_label
            ):
                raise ValueError("embedded page identity precedence differs")
        elif self.display_source not in {"legacy_display_fallback", "physical"}:
            raise ValueError("page identity fallback differs")
        expected_evidence_method = (
            "native_printed_label"
            if detected
            else "embedded_pdf_label"
            if self.display_source == "embedded_label"
            else "legacy_display_fallback"
            if self.display_source == "legacy_display_fallback"
            else "physical_page_index"
        )
        if self.evidence_source.method != expected_evidence_method:
            raise ValueError("page identity display/evidence provenance differs")
        if self.display_source == "physical" and self.display_label != str(
            self.physical_page_index
        ):
            raise ValueError("physical page identity label differs")
        expected_scope = (
            "source_metadata"
            if self.display_source == "embedded_label"
            else "deterministic_rule"
            if self.display_source == "detected_printed_label"
            else "unavailable"
        )
        if self.confidence.scope != expected_scope:
            raise ValueError("page identity confidence scope differs")
        if expected_scope != "unavailable" and self.confidence.score != 1.0:
            raise ValueError("page identity confidence score differs")
        if expected_scope == "unavailable":
            expected_reason = (
                "page_identity_display_fallback_physical"
                if self.display_source == "physical"
                else "page_identity_source_unavailable"
            )
            if self.confidence.unavailable_reason != expected_reason:
                raise ValueError("page identity fallback confidence differs")
        if conflict != ("page_identity_source_conflict" in self.concern_codes):
            raise ValueError("page identity conflict concern differs")
        if _strict_model_json_size(self) > 64 * 1024:
            raise ValueError("page identity exceeds its byte cap")
        return self


class RunningRegionDescriptor(StrictApiModel):
    id: str
    page_id: str
    physical_page_index: StrictInt = Field(ge=1, le=100)
    role: Literal["header", "footer", "navigation_top", "navigation_bottom"]
    canonical_scope: Literal["header", "footer"]
    source_public_item_id: str
    source_public_path: list[str | int]
    source_element_id: str
    predecessor_type: str
    predecessor_item_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bbox_id: str
    bbox: RunningRegionBoundingBox
    evidence_ids: list[str]
    source_object_ids: list[str]
    source_method: Literal[
        "trusted_layout_role",
        "cross_page_repetition",
        "boundary_navigation",
        "printed_label_boundary",
        "effective_boundary_cluster",
        "extracted_source_contribution",
    ]
    repetition_group_id: str | None
    repetition_page_indexes: list[StrictInt]
    confidence: RunningRegionConfidence
    concern_codes: list[str]
    canonical_block_id: str

    @model_validator(mode="after")
    def validate_descriptor(self) -> RunningRegionDescriptor:
        for value in (
            self.id,
            self.page_id,
            self.source_public_item_id,
            self.source_element_id,
            self.predecessor_type,
            self.bbox_id,
            self.canonical_block_id,
        ):
            _bounded_running_string(value)
        _validate_running_path(self.source_public_path)
        if (
            len(self.source_public_path) != 4
            or self.source_public_path[0] != "pages"
            or self.source_public_path[1] != self.physical_page_index - 1
            or self.source_public_path[2] != "items"
            or isinstance(self.source_public_path[3], bool)
            or not isinstance(self.source_public_path[3], int)
        ):
            raise ValueError("running-region public path root differs")
        _validate_running_references(self.evidence_ids, allow_empty=False)
        _validate_running_references(self.source_object_ids, allow_empty=False)
        _validate_concern_codes(self.concern_codes)
        expected_scope = (
            "header" if self.role in {"header", "navigation_top"} else "footer"
        )
        if self.canonical_scope != expected_scope:
            raise ValueError("running-region role/scope differs")
        if self.source_method == "trusted_layout_role" and self.role not in {
            "header",
            "footer",
        }:
            raise ValueError("trusted running-region role differs")
        if self.source_method == "boundary_navigation" and self.role not in {
            "navigation_top",
            "navigation_bottom",
        }:
            raise ValueError("navigation running-region role differs")
        if self.source_method == "printed_label_boundary" and self.role not in {
            "header",
            "footer",
        }:
            raise ValueError("printed-label running-region role differs")
        if self.source_method == "effective_boundary_cluster" and self.role != "footer":
            raise ValueError("effective running-region role differs")
        if self.source_method in {
            "cross_page_repetition",
            "extracted_source_contribution",
        } and self.role not in {"header", "footer"}:
            raise ValueError("repeated/extracted running-region role differs")
        if (
            self.source_method == "extracted_source_contribution"
            and len(self.evidence_ids) != 1
        ):
            raise ValueError("extracted running-region evidence differs")
        pages = self.repetition_page_indexes
        if (
            len(pages) > 100
            or pages != sorted(set(pages))
            or any(value < 1 or value > 100 for value in pages)
        ):
            raise ValueError("running-region repetition membership differs")
        if self.repetition_group_id is None:
            if pages or self.source_method == "cross_page_repetition":
                raise ValueError("running-region repetition identity is partial")
        else:
            _bounded_running_string(self.repetition_group_id)
            if len(pages) < 2 or self.physical_page_index not in pages:
                raise ValueError("running-region repetition membership differs")
        if (
            self.confidence.scope != "deterministic_rule"
            or self.confidence.score != 1.0
        ):
            raise ValueError("running-region confidence differs")
        if _strict_model_json_size(self) > 256 * 1024:
            raise ValueError("running-region descriptor exceeds its byte cap")
        return self


class RunningRegionsProcessingSummary(StrictApiModel):
    policy_id: Literal["p03-running-regions-page-identity-v1"]
    status: Literal["projected", "unavailable", "not_applicable", "failed_closed"]
    reason: (
        Literal[
            "running_region_source_evidence_unavailable",
            "running_region_source_limit",
            "running_region_input_not_applicable",
            "running_region_projection_failed_closed",
        ]
        | None
    )
    source_page_count: StrictInt = Field(ge=0, le=100)
    identity_count: StrictInt = Field(ge=0, le=100)
    detected_label_count: StrictInt = Field(ge=0, le=100)
    embedded_label_count: StrictInt = Field(ge=0, le=100)
    legacy_fallback_count: StrictInt = Field(ge=0, le=100)
    candidate_count: StrictInt = Field(ge=0, le=10_000)
    comparison_count: StrictInt = Field(ge=0, le=65_536)
    running_region_count: StrictInt = Field(ge=0, le=2_048)
    header_count: StrictInt = Field(ge=0, le=2_048)
    footer_count: StrictInt = Field(ge=0, le=2_048)
    top_navigation_count: StrictInt = Field(ge=0, le=2_048)
    bottom_navigation_count: StrictInt = Field(ge=0, le=2_048)
    concern_count: StrictInt = Field(ge=0, le=256)
    extraction_ms: float = Field(ge=0)
    projection_ms: float = Field(ge=0)
    total_ms: float = Field(ge=0)

    @field_validator("extraction_ms", "projection_ms", "total_ms", mode="before")
    @classmethod
    def validate_duration_input(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("running-region duration differs")
        return value

    @model_validator(mode="after")
    def validate_summary(self) -> RunningRegionsProcessingSummary:
        expected_reasons = {
            "projected": {None},
            "unavailable": {
                "running_region_source_evidence_unavailable",
                "running_region_source_limit",
            },
            "not_applicable": {"running_region_input_not_applicable"},
            "failed_closed": {"running_region_projection_failed_closed"},
        }[self.status]
        if self.reason not in expected_reasons:
            raise ValueError("running-region summary reason differs")
        timings = (self.extraction_ms, self.projection_ms, self.total_ms)
        if not all(
            math.isfinite(value) and value == round(value, 3) for value in timings
        ) or self.total_ms != round(self.extraction_ms + self.projection_ms, 3):
            raise ValueError("running-region summary timing differs")
        if self.extraction_ms > 2_000 or self.projection_ms > 2_000:
            raise ValueError("running-region summary deadline differs")
        if self.status == "projected":
            if self.source_page_count != self.identity_count or (
                self.detected_label_count
                + self.embedded_label_count
                + self.legacy_fallback_count
                != self.identity_count
            ):
                raise ValueError("running-region identity counts differ")
            if (
                self.header_count
                + self.footer_count
                + self.top_navigation_count
                + self.bottom_navigation_count
                != self.running_region_count
            ):
                raise ValueError("running-region role counts differ")
        elif (
            any(
                getattr(self, name)
                for name in (
                    "source_page_count",
                    "identity_count",
                    "detected_label_count",
                    "embedded_label_count",
                    "legacy_fallback_count",
                    "candidate_count",
                    "comparison_count",
                    "running_region_count",
                    "header_count",
                    "footer_count",
                    "top_navigation_count",
                    "bottom_navigation_count",
                )
            )
            or self.concern_count > 1
        ):
            raise ValueError("nonprojecting running-region counts differ")
        return self


class ProjectedRunningRegionConcern(StrictApiModel):
    code: Literal[
        "running_region_source_evidence_unavailable",
        "running_region_source_limit",
        "running_region_candidate_limit",
        "running_region_geometry_ambiguous",
        "running_region_repetition_ambiguous",
        "running_region_navigation_ambiguous",
        "running_region_ownership_conflict",
        "page_identity_embedded_label_invalid",
        "page_identity_detected_label_ambiguous",
        "page_identity_source_conflict",
        "page_identity_display_unsafe",
        "running_region_canonical_custody_invalid",
        "running_region_projection_failed_closed",
        "running_region_concerns_truncated",
    ]
    source_ref: str
    count: StrictInt = Field(ge=1)
    cap: StrictInt = Field(ge=1)
    exception_class: str | None

    @model_validator(mode="after")
    def validate_concern(self) -> ProjectedRunningRegionConcern:
        if (
            self.source_ref != "document"
            and re.fullmatch(r"page:[1-9][0-9]*", self.source_ref) is None
        ):
            raise ValueError("running-region concern source differs")
        if self.count > self.cap:
            raise ValueError("running-region concern count exceeds its cap")
        expected_cap = (
            _MAX_CONCERNS_PER_DOCUMENT
            if self.source_ref == "document"
            else _MAX_CONCERNS_PER_PAGE
        )
        if self.cap != expected_cap:
            raise ValueError("running-region concern cap differs")
        if self.exception_class is not None:
            raise ValueError("projected running-region exception must be content-free")
        return self


class NonprojectingRunningRegionConcern(StrictApiModel):
    code: Literal[
        "running_region_source_evidence_unavailable",
        "running_region_source_limit",
        "running_region_canonical_custody_invalid",
        "running_region_projection_failed_closed",
    ]


class TableBoundingBox(StrictTableApiModel):
    """Exact top-left P04 table geometry in PDF points."""

    x: TableNonNegativeNumber
    y: TableNonNegativeNumber
    width: TablePositiveNumber
    height: TablePositiveNumber
    unit: Literal["pt"]

    @model_validator(mode="after")
    def validate_geometry(self) -> TableBoundingBox:
        if not all(
            _table_number_is_finite(value)
            for value in (self.x, self.y, self.width, self.height)
        ):
            raise ValueError("table bbox values must be finite")
        return self


class TableConfidenceDimensions(StrictTableApiModel):
    text: TableConfidenceNumber | None
    geometry: TableConfidenceNumber | None
    structure: TableConfidenceNumber | None
    header: TableConfidenceNumber | None

    @model_validator(mode="after")
    def validate_confidence(self) -> TableConfidenceDimensions:
        values = (self.text, self.geometry, self.structure, self.header)
        if any(value is not None and not math.isfinite(value) for value in values):
            raise ValueError("table confidence values must be finite")
        return self

    @model_serializer(mode="wrap")
    def serialize_required_nulls(self, handler: Any, _info: Any):
        serialized = handler(self)
        if type(serialized) is not dict:
            raise ValueError("table confidence serialization differs")
        serialized.update(
            {
                "text": self.text,
                "geometry": self.geometry,
                "structure": self.structure,
                "header": self.header,
            }
        )
        return serialized


class TableCell(StrictTableApiModel):
    """Exact 16-key cell projection authoritative only for valid P04 tables."""

    id: TableSha256
    row: StrictInt = Field(ge=0, lt=_TABLE_MAX_ROWS)
    column: StrictInt = Field(ge=0, lt=_TABLE_MAX_COLUMNS)
    row_span: StrictInt = Field(ge=1, le=_TABLE_MAX_ROWS)
    col_span: StrictInt = Field(ge=1, le=_TABLE_MAX_COLUMNS)
    text: str = Field(max_length=_TABLE_MAX_CELL_BYTES)
    column_header: bool
    row_header: bool
    row_section: bool
    bbox: TableBoundingBox | None
    source: Literal["native", "ocr"]
    page_index: StrictInt = Field(ge=1, le=1_000_000)
    evidence_ids: list[TableSha256] = Field(
        min_length=1,
        max_length=_TABLE_MAX_REFERENCES,
    )
    source_object_ids: list[TableSha256] = Field(
        min_length=1,
        max_length=_TABLE_MAX_REFERENCES,
    )
    span_decision_id: TableSha256 | None
    confidence_dimensions: TableConfidenceDimensions

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _bounded_table_text(
            value,
            maximum_bytes=_TABLE_MAX_CELL_BYTES,
            allow_empty=True,
        )

    @field_validator("evidence_ids", "source_object_ids")
    @classmethod
    def validate_references(cls, value: list[str]) -> list[str]:
        return _validate_table_hashes(value, allow_empty=False)

    @model_serializer(mode="wrap")
    def serialize_required_nulls(self, handler: Any, _info: Any):
        serialized = handler(self)
        if type(serialized) is not dict:
            raise ValueError("table cell serialization differs")
        serialized["bbox"] = (
            None if self.bbox is None else self.bbox.model_dump(mode="json")
        )
        serialized["span_decision_id"] = self.span_decision_id
        serialized["confidence_dimensions"] = {
            "text": self.confidence_dimensions.text,
            "geometry": self.confidence_dimensions.geometry,
            "structure": self.confidence_dimensions.structure,
            "header": self.confidence_dimensions.header,
        }
        return serialized


class TableGrid(StrictTableApiModel):
    row_count: StrictInt = Field(ge=1, le=_TABLE_MAX_ROWS)
    column_count: StrictInt = Field(ge=1, le=_TABLE_MAX_COLUMNS)
    cell_ids: list[TableSha256] = Field(max_length=_TABLE_MAX_CELLS)

    @model_validator(mode="after")
    def validate_grid(self) -> TableGrid:
        if self.row_count * self.column_count > _TABLE_MAX_CELLS:
            raise ValueError("table grid exceeds its slot cap")
        if len(self.cell_ids) != len(set(self.cell_ids)):
            raise ValueError("table grid cell IDs repeat")
        return self


class TableSlot(StrictTableApiModel):
    id: TableSha256
    row: StrictInt = Field(ge=0, lt=_TABLE_MAX_ROWS)
    column: StrictInt = Field(ge=0, lt=_TABLE_MAX_COLUMNS)
    kind: Literal["anchor", "explicit_blank", "covered"]
    cell_id: TableSha256 | None
    covered_by_cell_id: TableSha256 | None

    @model_validator(mode="after")
    def validate_owner_shape(self) -> TableSlot:
        if self.kind == "covered":
            if self.cell_id is not None or self.covered_by_cell_id is None:
                raise ValueError("covered table slot ownership differs")
        elif self.cell_id is None or self.covered_by_cell_id is not None:
            raise ValueError("anchor table slot ownership differs")
        return self

    @model_serializer(mode="wrap")
    def serialize_required_nulls(self, handler: Any, _info: Any):
        serialized = handler(self)
        if type(serialized) is not dict:
            raise ValueError("table slot serialization differs")
        serialized["cell_id"] = self.cell_id
        serialized["covered_by_cell_id"] = self.covered_by_cell_id
        return serialized


class TableSourceObject(StrictTableApiModel):
    """Exact Docling source variant retained unchanged by sidecar v1.1."""

    id: TableSha256
    engine: Literal["docling"]
    object_type: Literal["table_cell", "table_geometry", "table_grid"]
    page_index: StrictInt = Field(ge=1, le=1_000_000)
    raw_ref: str = Field(min_length=1, max_length=256)
    content_sha256: TableSha256

    @field_validator("raw_ref")
    @classmethod
    def validate_raw_ref(cls, value: str) -> str:
        _bounded_table_text(value, maximum_bytes=256, allow_empty=False)
        try:
            encoded = value.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError("table source reference must be ASCII") from exc
        components = value[2:].split("/") if value.startswith("#/") else []
        if (
            len(encoded) > 256
            or "\\" in value
            or not components
            or any(
                not component
                or component in {".", ".."}
                or any(not 0x21 <= ord(character) <= 0x7E for character in component)
                for component in components
            )
        ):
            raise ValueError("table source reference differs")
        return value


class TablePdfplumberWord(StrictTableApiModel):
    """One exact, source-retained pdfplumber word observation."""

    id: TableSha256
    text: str = Field(max_length=_TABLE_MAX_CELL_BYTES)
    bbox: TableBoundingBox
    font_name: str = Field(
        min_length=1,
        max_length=_TABLE_MAX_FONT_NAME_BYTES,
    )
    bold: bool

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        validated = _bounded_table_text(
            value,
            maximum_bytes=_TABLE_MAX_CELL_BYTES,
            allow_empty=False,
        )
        if not validated.strip():
            raise ValueError("table word text must not be blank")
        return validated

    @field_validator("font_name")
    @classmethod
    def validate_font_name(cls, value: str) -> str:
        validated = _bounded_table_text(
            value,
            maximum_bytes=_TABLE_MAX_FONT_NAME_BYTES,
            allow_empty=False,
        )
        if any(
            ord(character) < 0x20 or ord(character) == 0x7F
            for character in validated
        ):
            raise ValueError("table font metadata contains an unsafe control")
        return validated

    @model_validator(mode="after")
    def validate_bold_derivation(self) -> TablePdfplumberWord:
        if self.bold is not ("bold" in self.font_name.casefold()):
            raise ValueError("table word bold derivation differs")
        return self


class TablePdfplumberSourceObject(StrictTableApiModel):
    """Exact source-bound recovery variant; it never fabricates a raw ref."""

    id: TableSha256
    engine: Literal["pdfplumber"]
    object_type: Literal["table_word_set"]
    page_index: StrictInt = Field(ge=1, le=1_000_000)
    raw_ref: Literal[None]
    role: Literal["header", "body_control", "bottom_row"]
    target_row: StrictInt = Field(ge=0, lt=_TABLE_MAX_ROWS)
    target_column: StrictInt = Field(ge=0, lt=_TABLE_MAX_COLUMNS)
    words: list[TablePdfplumberWord] = Field(
        min_length=1,
        max_length=_TABLE_MAX_WORDS_PER_SOURCE,
    )
    content_sha256: TableSha256

    @model_validator(mode="after")
    def validate_word_set(self) -> TablePdfplumberSourceObject:
        word_ids = [word.id for word in self.words]
        geometries = [
            (
                word.bbox.y,
                word.bbox.x,
                word.bbox.height,
                word.bbox.width,
            )
            for word in self.words
        ]
        if len(word_ids) != len(set(word_ids)):
            raise ValueError("table word identities repeat")
        if len(geometries) != len(set(geometries)):
            raise ValueError("table word geometry repeats")
        if geometries != sorted(geometries):
            raise ValueError("table word physical order differs")
        return self

    @model_serializer(mode="wrap")
    def serialize_required_raw_ref(self, handler: Any, _info: Any):
        serialized = handler(self)
        if type(serialized) is not dict:
            raise ValueError("table pdfplumber source serialization differs")
        serialized["raw_ref"] = None
        return serialized


TableSourceObjectVariant = Annotated[
    TableSourceObject | TablePdfplumberSourceObject,
    Field(discriminator="engine"),
]


class TableEvidenceRecord(StrictTableApiModel):
    id: TableSha256
    method: Literal[
        "native_text",
        "ocr_text",
        "vector_rule",
        "source_grid",
        "embedded_grid",
        "model_structure",
        "recovered_structure",
        "derived_comparison",
    ]
    dimension: Literal[
        "text",
        "geometry",
        "structure",
        "header",
        "ownership",
        "continuation",
    ]
    page_index: StrictInt = Field(ge=1, le=1_000_000)
    bbox: TableBoundingBox | None
    source_object_ids: list[TableSha256] = Field(
        min_length=1,
        max_length=_TABLE_MAX_REFERENCES,
    )
    confidence: TableConfidenceNumber
    content_sha256: TableSha256

    @field_validator("source_object_ids")
    @classmethod
    def validate_references(cls, value: list[str]) -> list[str]:
        return _validate_table_hashes(value, allow_empty=False)

    @field_validator("confidence")
    @classmethod
    def validate_confidence(
        cls, value: TableConfidenceNumber
    ) -> TableConfidenceNumber:
        if not math.isfinite(value):
            raise ValueError("table confidence must be finite")
        return value

    @model_serializer(mode="wrap")
    def serialize_required_bbox(self, handler: Any, _info: Any):
        serialized = handler(self)
        if type(serialized) is not dict:
            raise ValueError("table evidence record serialization differs")
        if self.bbox is None:
            serialized["bbox"] = None
        return serialized


class TableSpanDecision(StrictTableApiModel):
    id: TableSha256
    cell_id: TableSha256
    claimed_row_span: StrictInt = Field(ge=1, le=_TABLE_MAX_ROWS)
    claimed_col_span: StrictInt = Field(ge=1, le=_TABLE_MAX_COLUMNS)
    emitted_row_span: StrictInt = Field(ge=1, le=_TABLE_MAX_ROWS)
    emitted_col_span: StrictInt = Field(ge=1, le=_TABLE_MAX_COLUMNS)
    outcome: Literal["supported", "refused", "ambiguous"]
    evidence_ids: list[TableSha256] = Field(
        max_length=_TABLE_MAX_REFERENCES,
    )
    concern_codes: list[
        Literal[
            "table_ambiguous_border_evidence",
            "table_malformed_source_evidence",
            "table_resource_limit_exceeded",
            "table_source_cell_bbox_unresolved",
            "table_source_cell_grid_unresolved",
            "table_source_form_grid_topology_unresolved",
            "table_source_header_ownership_unresolved",
            "table_source_provenance_unresolved",
            "table_source_rotation_mapping_unresolved",
            "table_source_row_boundary_unresolved",
            "table_source_span_evidence_unresolved",
        ]
    ] = Field(max_length=_TABLE_MAX_REFERENCES)

    @field_validator("evidence_ids")
    @classmethod
    def validate_references(cls, value: list[str]) -> list[str]:
        return _validate_table_hashes(value, allow_empty=True)

    @field_validator("concern_codes")
    @classmethod
    def validate_concerns(cls, value: list[str]) -> list[str]:
        return _validate_table_concerns(value)


class TableRepresentationCustody(StrictTableApiModel):
    serializer_policy_id: Literal["p04-table-grid-serializer-v1"]
    grid_shape: list[StrictInt] = Field(min_length=2, max_length=2)
    cells_sha256: TableSha256
    rows_sha256: TableSha256
    html_sha256: TableSha256
    markdown_sha256: TableSha256
    csv_sha256: TableSha256

    @field_validator("grid_shape")
    @classmethod
    def validate_grid_shape(cls, value: list[int]) -> list[int]:
        if (
            value[0] < 1
            or value[0] > _TABLE_MAX_ROWS
            or value[1] < 1
            or value[1] > _TABLE_MAX_COLUMNS
            or value[0] * value[1] > _TABLE_MAX_CELLS
        ):
            raise ValueError("table custody grid shape differs")
        return value


class TableCandidateScore(StrictTableApiModel):
    candidate_id: TableSha256
    engine: Literal["docling", "pdfplumber", "unknown"]
    total: TableConfidenceNumber
    geometry: TableConfidenceNumber
    grid: TableConfidenceNumber
    cell_coverage: TableConfidenceNumber
    text_coverage: TableConfidenceNumber
    spans: TableConfidenceNumber
    provenance: TableConfidenceNumber
    bbox: TableBoundingBox | None
    row_count: StrictInt = Field(ge=0, le=_TABLE_MAX_ROWS)
    column_count: StrictInt = Field(ge=0, le=_TABLE_MAX_COLUMNS)
    content_sha256: TableSha256
    candidate: dict[str, Any]

    @model_validator(mode="after")
    def validate_score(self) -> TableCandidateScore:
        if type(self.candidate) is not dict or any(
            type(key) is not str or key.startswith("_p04_")
            for key in self.candidate
        ):
            raise ValueError("table retained candidate differs")
        for value in (
            self.total,
            self.geometry,
            self.grid,
            self.cell_coverage,
            self.text_coverage,
            self.spans,
            self.provenance,
        ):
            if not math.isfinite(value):
                raise ValueError("table candidate score must be finite")
        return self


class TableReconciliation(StrictTableApiModel):
    cluster_id: TableSha256
    candidate_ids: list[TableSha256] = Field(
        min_length=1,
        max_length=128,
    )
    selected_candidate_id: TableSha256 | None
    outcome: Literal[
        "singleton",
        "selected",
        "duplicate_collapsed",
        "unresolved",
        "malformed_fallback",
    ]
    absolute_threshold: TableConfidenceNumber
    selection_margin: TableConfidenceNumber
    scores: list[TableCandidateScore] = Field(min_length=1, max_length=128)
    evidence_ids: list[TableSha256] = Field(max_length=_TABLE_MAX_REFERENCES)
    concern_codes: list[str] = Field(max_length=_TABLE_MAX_REFERENCES)

    @field_validator("candidate_ids")
    @classmethod
    def validate_candidate_ids(cls, value: list[str]) -> list[str]:
        return _validate_table_hashes(value, allow_empty=False)

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, value: list[str]) -> list[str]:
        return _validate_table_hashes(value, allow_empty=True)

    @field_validator("concern_codes")
    @classmethod
    def validate_concerns(cls, value: list[str]) -> list[str]:
        return _validate_table_concerns(value)

    @model_validator(mode="after")
    def validate_decision(self) -> TableReconciliation:
        score_ids = [score.candidate_id for score in self.scores]
        if score_ids != self.candidate_ids:
            raise ValueError("table reconciliation score identities differ")
        if self.selected_candidate_id is not None and (
            self.selected_candidate_id not in self.candidate_ids
        ):
            raise ValueError("table reconciliation winner differs")
        if self.outcome == "unresolved" and self.selected_candidate_id is not None:
            raise ValueError("unresolved table reconciliation has a winner")
        if self.outcome != "unresolved" and self.selected_candidate_id is None:
            raise ValueError("resolved table reconciliation lacks a winner")
        return self


class TableCandidateGate(StrictTableApiModel):
    decision_id: TableSha256
    candidate_id: TableSha256
    outcome: Literal[
        "canonical_table",
        "form",
        "key_value",
        "chart",
        "visual",
        "unresolved",
        "structural_failure",
    ]
    owner_item_ids: list[str] = Field(max_length=_TABLE_MAX_REFERENCES)
    feature_scores: dict[str, TableConfidenceNumber]
    evidence_ids: list[TableSha256] = Field(max_length=_TABLE_MAX_REFERENCES)
    concern_codes: list[str] = Field(max_length=_TABLE_MAX_REFERENCES)

    @field_validator("owner_item_ids")
    @classmethod
    def validate_owner_ids(cls, value: list[str]) -> list[str]:
        if value != sorted(set(value)):
            raise ValueError("table gate owner identities differ")
        for identifier in value:
            _bounded_table_text(identifier, maximum_bytes=256, allow_empty=False)
        return value

    @field_validator("feature_scores")
    @classmethod
    def validate_features(
        cls, value: dict[str, int | float]
    ) -> dict[str, int | float]:
        if type(value) is not dict or set(value) != _TABLE_GATE_FEATURE_KEYS:
            raise ValueError("table gate feature scores differ")
        for key, score in value.items():
            _bounded_table_text(key, maximum_bytes=64, allow_empty=False)
            if not math.isfinite(score):
                raise ValueError("table gate feature score must be finite")
        return value

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, value: list[str]) -> list[str]:
        return _validate_table_hashes(value, allow_empty=True)

    @field_validator("concern_codes")
    @classmethod
    def validate_concerns(cls, value: list[str]) -> list[str]:
        return _validate_table_concerns(value)


class TableContinuation(StrictTableApiModel):
    merge_id: TableSha256
    outcome: Literal["page_local", "merged", "unresolved", "ineligible"]
    source_table_ids: list[TableSha256] = Field(
        min_length=1,
        max_length=32,
    )
    continued_from: TableSha256 | None
    page_indexes: list[StrictInt] = Field(min_length=1, max_length=32)
    signal_ids: list[TableSha256] = Field(max_length=_TABLE_MAX_REFERENCES)
    repeated_header_cell_ids: list[TableSha256] = Field(
        max_length=_TABLE_MAX_REFERENCES,
    )
    evidence_ids: list[TableSha256] = Field(max_length=_TABLE_MAX_REFERENCES)
    concern_codes: list[str] = Field(max_length=_TABLE_MAX_REFERENCES)

    @field_validator(
        "source_table_ids",
        "signal_ids",
        "repeated_header_cell_ids",
        "evidence_ids",
    )
    @classmethod
    def validate_hashes(cls, value: list[str]) -> list[str]:
        return _validate_table_hashes(value, allow_empty=True)

    @field_validator("page_indexes")
    @classmethod
    def validate_pages(cls, value: list[int]) -> list[int]:
        if (
            value != sorted(set(value))
            or any(page < 1 or page > 1_000_000 for page in value)
        ):
            raise ValueError("table continuation pages differ")
        return value

    @field_validator("concern_codes")
    @classmethod
    def validate_concerns(cls, value: list[str]) -> list[str]:
        return _validate_table_concerns(value)

    @model_validator(mode="after")
    def validate_decision(self) -> TableContinuation:
        if (
            self.continued_from is not None
            and self.continued_from not in self.source_table_ids
        ):
            raise ValueError("table continuation predecessor differs")
        if any(
            second != first + 1
            for first, second in zip(
                self.page_indexes,
                self.page_indexes[1:],
            )
        ):
            raise ValueError("table continuation pages are not adjacent")
        if self.outcome in ("merged", "page_local") and (
            len(self.source_table_ids) < 2
            or len(self.page_indexes) < 2
            or len(self.signal_ids) < 2
            or self.concern_codes
        ):
            raise ValueError("supported table continuation differs")
        if self.outcome == "merged" and self.continued_from is None:
            raise ValueError("merged table continuation lacks its predecessor")
        if self.outcome == "unresolved" and (
            "table_continuation_ambiguous" not in self.concern_codes
        ):
            raise ValueError("unresolved table continuation lacks its concern")
        if self.outcome == "ineligible" and (
            "table_continuation_incompatible" not in self.concern_codes
            and "table_resource_limit_exceeded" not in self.concern_codes
        ):
            raise ValueError("ineligible table continuation lacks its concern")
        return self


class TableEvidence(StrictTableApiModel):
    """Exact 17-key Phase 04 evidence sidecar."""

    policy_id: Literal["p04-table-evidence-v1"]
    version: Literal["1.1"]
    scope: list[
        Literal["P04-US01", "P04-US02", "P04-US04", "P04-US03"]
    ] = Field(min_length=1, max_length=4)
    status: Literal["valid", "unresolved", "structural_failure"]
    table_id: TableSha256
    candidate_id: TableSha256
    page_index: StrictInt = Field(ge=1, le=1_000_000)
    grid: TableGrid
    slots: list[TableSlot] = Field(max_length=_TABLE_MAX_CELLS)
    source_objects: list[TableSourceObjectVariant] = Field(
        min_length=1,
        max_length=_TABLE_MAX_CELLS,
    )
    evidence: list[TableEvidenceRecord] = Field(
        min_length=1,
        max_length=_TABLE_MAX_CELLS,
    )
    span_decisions: list[TableSpanDecision] = Field(max_length=_TABLE_MAX_CELLS)
    representation_custody: TableRepresentationCustody
    reconciliation: TableReconciliation | None
    gate: TableCandidateGate | None
    continuation: TableContinuation | None
    concerns: list[str] = Field(max_length=_TABLE_MAX_REFERENCES)

    @model_validator(mode="before")
    @classmethod
    def preflight_raw_sidecar(cls, value: Any) -> Any:
        if type(value) is dict:
            _preflight_raw_table_sidecar(value)
        return value

    @field_validator("concerns")
    @classmethod
    def validate_concerns(cls, value: list[str]) -> list[str]:
        return _validate_table_concerns(value)

    @model_serializer(mode="wrap")
    def serialize_required_nulls(self, handler: Any, _info: Any):
        serialized = handler(self)
        if type(serialized) is not dict:
            raise ValueError("table evidence serialization differs")
        serialized["reconciliation"] = (
            None
            if self.reconciliation is None
            else self.reconciliation.model_dump(mode="json")
        )
        serialized["gate"] = (
            None if self.gate is None else self.gate.model_dump(mode="json")
        )
        serialized["continuation"] = (
            None
            if self.continuation is None
            else self.continuation.model_dump(mode="json")
        )
        serialized_slots = serialized.get("slots")
        if type(serialized_slots) is list and len(serialized_slots) == len(
            self.slots
        ):
            for serialized_slot, slot in zip(
                serialized_slots,
                self.slots,
                strict=True,
            ):
                if type(serialized_slot) is dict:
                    serialized_slot["cell_id"] = slot.cell_id
                    serialized_slot["covered_by_cell_id"] = (
                        slot.covered_by_cell_id
                    )
        return serialized

    @model_validator(mode="after")
    def validate_sidecar_shape(self) -> TableEvidence:
        expected_scope = ["P04-US01"]
        if self.reconciliation is not None:
            expected_scope.append("P04-US02")
        if self.gate is not None:
            if self.reconciliation is None:
                raise ValueError("table gate requires reconciliation")
            expected_scope.append("P04-US04")
        if self.continuation is not None:
            if self.gate is None:
                raise ValueError("table continuation requires gate")
            expected_scope.append("P04-US03")
        if self.scope != expected_scope:
            raise ValueError("table evidence scope differs")
        source_ids = [source.id for source in self.source_objects]
        recovery_sources = [
            source
            for source in self.source_objects
            if isinstance(source, TablePdfplumberSourceObject)
        ]
        evidence_ids = [record.id for record in self.evidence]
        decision_ids = [decision.id for decision in self.span_decisions]
        cell_ids = self.grid.cell_ids
        if not _table_ids_are_strictly_increasing(source_ids):
            raise ValueError("table source object identities differ")
        if not _table_ids_are_strictly_increasing(evidence_ids):
            raise ValueError("table evidence identities differ")
        if len(decision_ids) != len(set(decision_ids)):
            raise ValueError("table span decision identities repeat")
        if any(source.page_index != self.page_index for source in self.source_objects):
            raise ValueError("table source object page differs")
        if len(recovery_sources) > _TABLE_MAX_RECOVERY_SOURCE_OBJECTS:
            raise ValueError("table recovery source count exceeds its cap")
        recovery_targets = [
            (source.role, source.target_row, source.target_column)
            for source in recovery_sources
        ]
        if len(recovery_targets) != len(set(recovery_targets)):
            raise ValueError("table recovery source target repeats")
        if any(
            source.target_row >= self.grid.row_count
            or source.target_column >= self.grid.column_count
            for source in recovery_sources
        ):
            raise ValueError("table recovery source target differs")
        if any(
            (source.role == "header" and source.target_row != 0)
            or (source.role == "body_control" and source.target_row != 1)
            or (
                source.role == "bottom_row"
                and source.target_row != self.grid.row_count - 1
            )
            for source in recovery_sources
        ):
            raise ValueError("table recovery source role target differs")
        if any(record.page_index != self.page_index for record in self.evidence):
            raise ValueError("table evidence page differs")
        source_id_set = set(source_ids)
        if any(
            not set(record.source_object_ids) <= source_id_set
            for record in self.evidence
        ):
            raise ValueError("table evidence source reference differs")
        evidence_id_set = set(evidence_ids)
        if any(
            not set(decision.evidence_ids) <= evidence_id_set
            for decision in self.span_decisions
        ):
            raise ValueError("table span evidence reference differs")
        has_candidate_grid = self.status == "valid" or (
            self.status == "unresolved"
            and self.reconciliation is not None
            and self.reconciliation.outcome == "unresolved"
            and bool(cell_ids)
        )
        if has_candidate_grid:
            if (
                self.representation_custody.grid_shape
                != [self.grid.row_count, self.grid.column_count]
                or not cell_ids
                or len(self.slots)
                != self.grid.row_count * self.grid.column_count
            ):
                raise ValueError("valid table grid projection is incomplete")
        elif (
            self.grid.cell_ids
            or self.slots
            or self.span_decisions
            or not self.concerns
        ):
            raise ValueError("nonvalid table diagnostic carries authority")
        return self


OfficeFallbackFiniteFloat = Annotated[float, Field(allow_inf_nan=False)]


def _validate_office_fallback_transform(
    transform: Sequence[float],
    *,
    width: int,
    height: int,
) -> None:
    """Reject singular/overflowing matrices and non-finite render projections."""

    a, b, c, d, e, f = transform
    diagonal_product = a * d
    cross_product = b * c
    determinant = diagonal_product - cross_product
    if (
        not math.isfinite(diagonal_product)
        or not math.isfinite(cross_product)
        or not math.isfinite(determinant)
        or abs(determinant) <= 1e-12
    ):
        raise ValueError("Office fallback transform is not invertible")
    for x, y in (
        (0.0, 0.0),
        (float(width), 0.0),
        (0.0, float(height)),
        (float(width), float(height)),
    ):
        projected_x = a * x + c * y + e
        projected_y = b * x + d * y + f
        if not math.isfinite(projected_x) or not math.isfinite(projected_y):
            raise ValueError("Office fallback transform result is not finite")


class OfficeFallbackRelationship(StrictApiModel):
    id: str = Field(min_length=1, max_length=128)
    type: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    source_id: str = Field(min_length=1, max_length=128)
    target_id: str = Field(min_length=1, max_length=128)


class OfficeFallbackRenderedItem(StrictApiModel):
    """One bounded visual observation retained under a native Office item."""

    id: str = Field(min_length=1, max_length=128)
    type: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    text: str = Field(min_length=1, max_length=65_536)
    origin: Literal["rendered"]
    evidence_method: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    relationships: list[OfficeFallbackRelationship] = Field(
        default_factory=list,
        max_length=16_384,
    )
    concerns: list[str] = Field(default_factory=list, max_length=1_024)

    @model_validator(mode="after")
    def validate_concerns(self) -> OfficeFallbackRenderedItem:
        if self.concerns != sorted(set(self.concerns)) or any(
            re.fullmatch(r"^[a-z][a-z0-9_]{1,63}$", value) is None
            for value in self.concerns
        ):
            raise ValueError("Office fallback concern codes differ")
        return self


class OfficeFallbackRendererMetadata(StrictApiModel):
    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    image_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    width: int = Field(ge=1, le=8_192)
    height: int = Field(ge=1, le=8_192)


class OfficeVisualFallback(StrictApiModel):
    """Closed, additive native-first Office render reconciliation sidecar."""

    schema_version: Literal["1.0"]
    status: Literal["merged", "unavailable"]
    reason: str | None = Field(
        default=None,
        pattern=r"^office_[a-z0-9_]{2,72}$",
    )
    native_authority: Literal[True]
    placeholder_id: str = Field(min_length=1, max_length=128)
    source_part: str = Field(min_length=1, max_length=512)
    source_xml_path: str | None = Field(default=None, max_length=4_096)
    logical_index: int = Field(ge=1, le=1_000_000)
    logical_label: str = Field(min_length=1, max_length=256)
    renderer: OfficeFallbackRendererMetadata | None = None
    transform: list[OfficeFallbackFiniteFloat] | None = Field(
        default=None,
        min_length=6,
        max_length=6,
    )
    transform_source_unit: Literal["px"] | None = None
    transform_target_unit: Literal["pt", "logical"] | None = None
    items: list[OfficeFallbackRenderedItem] = Field(
        default_factory=list,
        max_length=256,
    )

    @model_validator(mode="after")
    def validate_state(self) -> OfficeVisualFallback:
        if self.status == "merged":
            if (
                self.reason is not None
                or self.renderer is None
                or self.transform is None
                or self.transform_source_unit != "px"
                or self.transform_target_unit is None
            ):
                raise ValueError("merged Office fallback state is incomplete")
            _validate_office_fallback_transform(
                self.transform,
                width=self.renderer.width,
                height=self.renderer.height,
            )
        elif (
            self.reason is None
            or self.renderer is not None
            or self.transform is not None
            or self.transform_source_unit is not None
            or self.transform_target_unit is not None
            or self.items
        ):
            raise ValueError("unavailable Office fallback state differs")
        item_ids = [item.id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("Office fallback rendered item identity repeats")
        relationship_ids = [
            relationship.id
            for item in self.items
            for relationship in item.relationships
        ]
        if len(relationship_ids) != len(set(relationship_ids)):
            raise ValueError("Office fallback relationship identity repeats")
        known_items = set(item_ids)
        if any(
            relationship.source_id not in known_items
            or relationship.target_id not in known_items
            for item in self.items
            for relationship in item.relationships
        ):
            raise ValueError("Office fallback relationship endpoint is unknown")
        return self


class OfficeFallbackProcessingSummary(StrictApiModel):
    schema_version: Literal["1.0"]
    status: Literal["completed", "completed_with_concerns"]
    rendered_region_count: int = Field(ge=0, le=1_000)
    merged_item_count: int = Field(ge=0, le=256_000)
    deduplicated_item_count: int = Field(ge=0, le=256_000)
    failed_region_count: int = Field(ge=0, le=1_000_000)
    native_authority: Literal[True]

    @model_validator(mode="after")
    def validate_status(self) -> OfficeFallbackProcessingSummary:
        if (self.status == "completed") != (self.failed_region_count == 0):
            raise ValueError("Office fallback processing status differs")
        return self


class ContentItem(ApiModel):
    """One normalized document item in reading order.

    Type-specific properties such as ``level``, ``rows``, ``cells``, ``html``,
    ``csv``, ``ordered``, and nested OCR ``items`` are allowed as extensions.
    """

    id: str
    type: str
    reading_order: int = Field(ge=0)
    value: Any | None = None
    md: str | None = None
    bbox: BoundingBox | None = None
    source: Literal["native", "ocr", "mixed", "derived"] | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    layout_running_region_projected: SkipJsonSchema[Literal[True] | None] = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    running_region_policy: SkipJsonSchema[
        Literal["p03-running-regions-page-identity-v1"] | None
    ] = Field(default=None, exclude_if=lambda value: value is None)
    running_region: SkipJsonSchema[RunningRegionDescriptor | None] = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    table_evidence: TableEvidence | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    table_continuation: TableContinuation | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    visual_structure: VisualStructure | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description=(
            "Default-off, source-grounded Phase 05 chart or diagram semantics. "
            "The sidecar is absent when its owning schema feature is disabled."
        ),
    )
    office_chart: OfficeChartStructure | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description=(
            "Default-off native PPTX/XLSX chart evidence admitted through "
            "the Phase 05 chart validation and serialization boundary."
        ),
    )
    office_visual_fallback: OfficeVisualFallback | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description=(
            "Default-off, bounded Office-render evidence reconciled beneath "
            "the authoritative native placeholder."
        ),
    )
    visual_model_evidence: VisualModelEvidenceBundle | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description=(
            "Default-off Phase 06 observations accepted through independent "
            "Phase 05 grounding and merged without replacing source evidence."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def preflight_marked_table_item(cls, value: Any) -> Any:
        if (
            type(value) is dict
            and value.get("table_evidence") is not None
            and _bounded_table_json_size(value, _TABLE_MAX_ITEM_BYTES) is None
        ):
            raise ValueError("table item exceeds its byte cap")
        return value

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> dict[str, Any]:
        schema = handler(core_schema)
        cell_reference = handler.generate_json_schema.generate_inner(
            TableCell.__pydantic_core_schema__
        )
        properties = schema.setdefault("properties", {})
        properties["cells"] = {
            "description": (
                "Legacy unmarked cell payloads remain additive and unchanged. "
                "When table_evidence.status is valid, every member is the exact "
                "closed TableCell schema."
            ),
            "type": "array",
            "items": {},
            "x-p04-valid-items": dict(cell_reference),
        }
        schema.setdefault("allOf", []).append(
            {
                "if": {
                    "required": ["table_evidence"],
                    "properties": {
                        "table_evidence": {
                            "type": "object",
                            "required": ["status"],
                            "properties": {"status": {"const": "valid"}},
                        }
                    },
                },
                "then": {
                    "required": ["cells"],
                    "properties": {
                        "cells": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": _TABLE_MAX_CELLS,
                            "items": dict(cell_reference),
                        }
                    },
                },
            }
        )
        return schema

    @model_validator(mode="after")
    def validate_running_region_sidecar(self) -> ContentItem:
        values = (
            self.layout_running_region_projected,
            self.running_region_policy,
            self.running_region,
        )
        if any(value is not None for value in values) and not all(
            value is not None for value in values
        ):
            raise ValueError("running-region public sidecar is partial")
        return self

    @model_validator(mode="after")
    def validate_layout_note_and_candidate_caption_owner(self) -> ContentItem:
        extras = self.model_extra or {}
        owner_payload = {
            "type": self.type,
            "value": self.value,
            "rows": extras.get("rows"),
            "row_count": extras.get("row_count"),
            "column_count": extras.get("column_count"),
            "table_candidate_gate": extras.get("table_candidate_gate"),
            "table_candidate_gate_reasons": extras.get(
                "table_candidate_gate_reasons"
            ),
            "table_candidate_gate_sources": extras.get(
                "table_candidate_gate_sources"
            ),
        }
        note_marker = extras.get("layout_source_notes_projected")
        if note_marker is not None and (
            note_marker is not True
            or not is_source_note_owner_item(owner_payload)
        ):
            raise ValueError("source-note projection owner differs")
        if self.type.casefold() == "table_candidate" and (
            "caption_ids" in extras or "caption_of" in extras
        ) and not is_eligible_unresolved_table_candidate(owner_payload):
            raise ValueError("table-candidate caption owner differs")
        return self

    @model_validator(mode="after")
    def validate_visual_structure_sidecar(self) -> ContentItem:
        structure = self.visual_structure
        if structure is None:
            if "visual_structure" in self.model_fields_set:
                raise ValueError("visual structure marker must not be null")
            return self
        if self.type not in {"chart", "diagram"}:
            raise ValueError("visual structure requires a chart or diagram item")
        if structure.region.kind != self.type:
            raise ValueError("visual structure kind differs from its public item")
        public_concerns = (self.model_extra or {}).get("parse_concerns", [])
        if structure.fallback.active and structure.fallback.predecessor_concern not in public_concerns:
            raise ValueError("visual fallback predecessor concern is unavailable")
        if (
            not structure.fallback.active
            and structure.fallback.predecessor_concern in public_concerns
        ):
            raise ValueError("authoritative visual retains its fallback concern")
        if structure.region.kind == "diagram":
            from app.services.visual_diagram_topology import (
                validate_raster_diagram_item_contract,
            )

            validate_raster_diagram_item_contract(
                self.model_dump(mode="python", exclude_none=True),
                structure,
            )
        return self

    @model_validator(mode="after")
    def validate_visual_model_evidence_sidecar(self) -> ContentItem:
        bundle = self.visual_model_evidence
        if bundle is None:
            if "visual_model_evidence" in self.model_fields_set:
                raise ValueError("visual-model evidence marker must not be null")
            return self
        if self.type not in {"image", "chart", "diagram"}:
            raise ValueError("visual-model evidence requires a visual item")
        if bundle.public_item_id != self.id:
            raise ValueError("visual-model evidence owner differs")
        structure = self.visual_structure
        if structure is not None and bundle.region_id != structure.region.id:
            raise ValueError("visual-model evidence region differs")
        return self

    @model_validator(mode="after")
    def validate_office_visual_fallback_sidecar(self) -> ContentItem:
        fallback = self.office_visual_fallback
        if fallback is None:
            if "office_visual_fallback" in self.model_fields_set:
                raise ValueError("Office visual fallback marker must not be null")
            return self
        if fallback.placeholder_id != self.id:
            raise ValueError("Office visual fallback owner differs")
        return self

    @model_validator(mode="after")
    def validate_table_sidecar(self) -> ContentItem:
        if self.table_evidence is None:
            if "table_evidence" in self.model_fields_set:
                raise ValueError("table evidence marker must not be null")
            return self
        if self.type != "table":
            raise ValueError("table evidence requires a table item")
        cells = (self.model_extra or {}).get("cells")
        has_candidate_grid = self.table_evidence.status == "valid" or (
            self.table_evidence.status == "unresolved"
            and self.table_evidence.reconciliation is not None
            and self.table_evidence.reconciliation.outcome == "unresolved"
            and bool(self.table_evidence.grid.cell_ids)
        )
        if has_candidate_grid:
            if type(cells) is not list or not cells or len(cells) > _TABLE_MAX_CELLS:
                raise ValueError("valid table cells differ")
            validated_cells: list[TableCell] = []
            for cell in cells:
                if type(cell) is not dict:
                    raise ValueError("valid table cell must be an exact object")
                validated_cells.append(TableCell.model_validate(cell))
            validated_cell_ids = [cell.id for cell in validated_cells]
            if validated_cell_ids != self.table_evidence.grid.cell_ids:
                raise ValueError("valid table cell identity order differs")
            for cell in validated_cells:
                if (
                    cell.page_index != self.table_evidence.page_index
                    or cell.row + cell.row_span > self.table_evidence.grid.row_count
                    or cell.column + cell.col_span
                    > self.table_evidence.grid.column_count
                ):
                    raise ValueError("valid table cell grid binding differs")
        else:
            extras = self.model_extra or {}
            row_count = extras.get("row_count")
            column_count = extras.get("column_count")
            rows = extras.get("rows")
            value = self.value
            if (
                type(cells) is not list
                or len(cells) > _TABLE_MAX_CELLS
                or type(row_count) is not int
                or row_count
                != self.table_evidence.representation_custody.grid_shape[0]
                or type(column_count) is not int
                or column_count
                != self.table_evidence.representation_custody.grid_shape[1]
                or type(rows) is not list
                or len(rows) != row_count
                or any(
                    type(row) is not list
                    or len(row) != column_count
                    or any(type(member) is not str for member in row)
                    for row in rows
                )
                or type(value) is not list
                or value != rows
                or type(extras.get("html")) is not str
                or self.md != extras.get("html")
                or type(extras.get("csv")) is not str
            ):
                raise ValueError("nonvalid table predecessor projection differs")
        return self

    @model_validator(mode="after")
    def validate_derived_table_continuation(self) -> ContentItem:
        continuation = self.table_continuation
        if continuation is None:
            return self
        if (
            self.type != "table"
            or self.table_evidence is not None
            or continuation.outcome != "merged"
        ):
            raise ValueError("derived table continuation marker differs")
        extras = self.model_extra or {}
        source_ids = extras.get("derived_from_table_ids")
        if (
            type(source_ids) is not list
            or sorted(source_ids) != continuation.source_table_ids
            or extras.get("continued_from") != continuation.continued_from
        ):
            raise ValueError("derived table continuation sources differ")
        return self


class PageResult(ApiModel):
    """Extraction result for one physical PDF page or raster frame."""

    page_index: int = Field(ge=1)
    page_number: int | str
    page_label: str
    page_width: float = Field(gt=0)
    page_height: float = Field(gt=0)
    unit: Literal["pt", "px", "logical"] = "pt"
    success: bool = True
    items: list[ContentItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    page_identity: SkipJsonSchema[PageIdentity | None] = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )


class DocumentMetadata(ApiModel):
    filename: str
    mime_type: str = "application/pdf"
    sha256: str
    page_count: int = Field(ge=0)


class ProcessingMetadata(ApiModel):
    engine: str
    ocr_engine: str
    ocr_languages: list[str] = Field(default_factory=list)
    duration_ms: int = Field(ge=0)
    running_regions: SkipJsonSchema[RunningRegionsProcessingSummary | None] = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    office_fallback: OfficeFallbackProcessingSummary | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description=(
            "Default-off aggregate for bounded native-first Office visual "
            "fallback reconciliation."
        ),
    )


class OpaqueRawGroupCustodyRecord(StrictTableApiModel):
    """One exact raw group/member edge retained without raw content."""

    record_id: str = Field(pattern=_CUSTODY_RECORD_ID_PATTERN)
    record_order: StrictInt = Field(ge=0)
    page_index: StrictInt = Field(ge=1)
    edge_kind: Literal[
        "group_membership",
        "group_reference",
        "root_reading_order",
    ]
    owner_order: StrictInt = Field(ge=0)
    owner_element_id: str | None = Field(
        default=None,
        pattern=_CUSTODY_ELEMENT_ID_PATTERN,
    )
    owner_raw_ref: str = Field(pattern=_CUSTODY_OWNER_REF_PATTERN)
    raw_slot_index: StrictInt = Field(ge=0)
    raw_target_slot_index: StrictInt | None = Field(
        default=None,
        ge=0,
        le=_CUSTODY_MAX_RECORDS,
    )
    raw_assertion_sha256: TableSha256
    member_element_id: str = Field(pattern=_CUSTODY_ELEMENT_ID_PATTERN)
    member_raw_ref: str = Field(pattern=_CUSTODY_RAW_REF_PATTERN)
    member_type: str = Field(pattern=_CUSTODY_ELEMENT_TYPE_PATTERN)
    member_content_basis: Literal["public_ir", "opaque_group_empty"]
    member_content_sha256: TableSha256
    group_element_id: str = Field(pattern=_CUSTODY_ELEMENT_ID_PATTERN)
    group_raw_ref: str = Field(pattern=_CUSTODY_GROUP_REF_PATTERN)
    group_type: Literal["group", "list"]
    counterpart_element_id: str = Field(pattern=_CUSTODY_ELEMENT_ID_PATTERN)
    counterpart_raw_ref: str = Field(pattern=_CUSTODY_RAW_REF_PATTERN)
    counterpart_type: str = Field(pattern=_CUSTODY_ELEMENT_TYPE_PATTERN)
    counterpart_content_basis: Literal["public_ir", "opaque_group_empty"]
    counterpart_content_sha256: TableSha256
    relationship_id: str = Field(pattern=_CUSTODY_RELATIONSHIP_ID_PATTERN)
    relationship_type: Literal[
        "contains",
        "caption_of",
        "source_note_of",
        "footnote_of",
        "legend_of",
        "axis_of",
        "reading_before",
        "alternative_of",
        "annotation_of",
        "references",
        "label_of",
        "value_of",
        "control_of",
        "key_of",
        "form_overlay_of",
        "outline_parent_of",
        "outline_next",
        "outline_continuation_of",
    ]
    relationship_field: str = Field(pattern=_CUSTODY_FIELD_PATTERN)
    normalized_relationship_field: str = Field(pattern=_CUSTODY_FIELD_PATTERN)
    normalization_outcome: Literal[
        "normalized_edge",
        "merged_edge",
        "root_reading_order",
    ]
    normalized_assertion_count: StrictInt = Field(
        ge=1,
        le=_CUSTODY_MAX_RECORDS,
    )
    normalized_relationship_sha256: TableSha256
    normalized_evidence_count: StrictInt = Field(ge=0, le=65_536)
    source_element_id: str = Field(pattern=_CUSTODY_ELEMENT_ID_PATTERN)
    source_raw_ref: str = Field(pattern=_CUSTODY_RAW_REF_PATTERN)
    source_type: str = Field(pattern=_CUSTODY_ELEMENT_TYPE_PATTERN)
    source_content_basis: Literal["public_ir", "opaque_group_empty"]
    source_content_sha256: TableSha256
    target_element_id: str = Field(pattern=_CUSTODY_ELEMENT_ID_PATTERN)
    target_raw_ref: str = Field(pattern=_CUSTODY_RAW_REF_PATTERN)
    target_type: str = Field(pattern=_CUSTODY_ELEMENT_TYPE_PATTERN)
    target_content_basis: Literal["public_ir", "opaque_group_empty"]
    target_content_sha256: TableSha256

    @model_validator(mode="after")
    def validate_closed_edge(self) -> OpaqueRawGroupCustodyRecord:
        from app.services.opaque_group_custody import (
            empty_group_content_sha256,
            stable_id,
        )

        if (
            self.group_raw_ref == self.counterpart_raw_ref
            or self.group_element_id == self.counterpart_element_id
            or self.source_element_id == self.target_element_id
            or {self.source_element_id, self.target_element_id}
            != {self.group_element_id, self.counterpart_element_id}
        ):
            raise ValueError("canonical source custody endpoint binding differs")
        expected_raw_refs = (
            (self.group_raw_ref, self.counterpart_raw_ref)
            if self.source_element_id == self.group_element_id
            else (self.counterpart_raw_ref, self.group_raw_ref)
        )
        if (self.source_raw_ref, self.target_raw_ref) != expected_raw_refs:
            raise ValueError("canonical source custody raw endpoint binding differs")
        endpoint_bindings = {
            self.source_raw_ref: (
                self.source_element_id,
                self.source_type,
                self.source_content_basis,
                self.source_content_sha256,
            ),
            self.target_raw_ref: (
                self.target_element_id,
                self.target_type,
                self.target_content_basis,
                self.target_content_sha256,
            ),
        }
        if endpoint_bindings.get(self.group_raw_ref, ())[:2] != (
            self.group_element_id,
            self.group_type,
        ):
            raise ValueError("canonical source custody group endpoint differs")
        if endpoint_bindings.get(self.counterpart_raw_ref) != (
            self.counterpart_element_id,
            self.counterpart_type,
            self.counterpart_content_basis,
            self.counterpart_content_sha256,
        ):
            raise ValueError("canonical source custody counterpart endpoint differs")
        if endpoint_bindings.get(self.member_raw_ref) != (
            self.member_element_id,
            self.member_type,
            self.member_content_basis,
            self.member_content_sha256,
        ):
            raise ValueError("canonical source custody member endpoint differs")
        owner_binding = {
            self.group_raw_ref: self.group_element_id,
            self.counterpart_raw_ref: self.counterpart_element_id,
        }
        type_binding = {
            self.group_raw_ref: self.group_type,
            self.counterpart_raw_ref: self.counterpart_type,
        }
        if (
            owner_binding.get(self.member_raw_ref) != self.member_element_id
            or type_binding.get(self.member_raw_ref) != self.member_type
        ):
            raise ValueError("canonical source custody raw member binding differs")
        for raw_ref, element_type, basis, digest in (
            (
                self.source_raw_ref,
                self.source_type,
                self.source_content_basis,
                self.source_content_sha256,
            ),
            (
                self.target_raw_ref,
                self.target_type,
                self.target_content_basis,
                self.target_content_sha256,
            ),
        ):
            if basis == "opaque_group_empty":
                if (
                    not raw_ref.startswith("#/groups/")
                    or element_type not in {"group", "list"}
                    or digest != empty_group_content_sha256(element_type)
                ):
                    raise ValueError(
                        "canonical source custody empty-group content differs"
                    )
            elif basis != "public_ir":
                raise ValueError("canonical source custody content basis differs")

        root_owner = self.owner_raw_ref in {"#/body", "#/furniture"}
        nested_reference_field = re.fullmatch(
            r"(?:graph\.cells\[[0-9]+\]\.item_ref|"
            r"data\.table_cells\[[0-9]+\]\.ref|"
            r"annotations\[[0-9]+\]\.chart_data\.table_cells"
            r"\[[0-9]+\]\.ref|"
            r"meta\.tabular_chart\.chart_data\.table_cells"
            r"\[[0-9]+\]\.ref)",
            self.relationship_field,
        ) is not None
        if root_owner:
            if (
                self.owner_element_id is not None
                or self.edge_kind != "root_reading_order"
                or self.relationship_field
                != f"{self.owner_raw_ref[2:]}.children.reading_order"
                or self.raw_target_slot_index != self.raw_slot_index + 1
                or self.member_element_id != self.target_element_id
                or self.member_raw_ref != self.target_raw_ref
                or self.relationship_type != "reading_before"
                or self.normalization_outcome != "root_reading_order"
            ):
                raise ValueError("canonical source custody root order differs")
        elif (
            owner_binding.get(self.owner_raw_ref) != self.owner_element_id
            or self.owner_element_id == self.member_element_id
            or (
                self.raw_target_slot_index is not None
                and not nested_reference_field
            )
            or self.edge_kind == "root_reading_order"
            or self.normalization_outcome == "root_reading_order"
        ):
            raise ValueError("canonical source custody raw owner binding differs")
        if (self.edge_kind == "group_membership") != (
            self.owner_raw_ref == self.group_raw_ref
            and self.relationship_field == "children"
        ):
            raise ValueError("canonical source custody edge kind differs")
        if self.edge_kind == "group_reference" and root_owner:
            raise ValueError("canonical source custody edge kind differs")

        child_source_fields = {
            "captions": "caption_of",
            "caption": "caption_of",
            "source_notes": "source_note_of",
            "source_note": "source_note_of",
            "footnotes": "footnote_of",
            "footnote": "footnote_of",
            "legends": "legend_of",
            "legend": "legend_of",
            "axes": "axis_of",
            "axis": "axis_of",
            "alternatives": "alternative_of",
            "alternative": "alternative_of",
            "annotations": "annotation_of",
            "comments": "annotation_of",
        }
        if not root_owner:
            if self.relationship_field == "parent":
                valid_field = (
                    self.relationship_type == "contains"
                    and self.source_raw_ref == self.member_raw_ref
                    and self.target_raw_ref == self.owner_raw_ref
                )
            elif self.relationship_field == "children":
                valid_field = self.relationship_type in {
                    "contains",
                    "caption_of",
                    "source_note_of",
                    "footnote_of",
                }
                if self.relationship_type == "contains":
                    valid_field = valid_field and (
                        self.source_raw_ref == self.owner_raw_ref
                        and self.target_raw_ref == self.member_raw_ref
                    )
                else:
                    valid_field = valid_field and (
                        self.source_raw_ref == self.member_raw_ref
                        and self.target_raw_ref == self.owner_raw_ref
                    )
            elif self.relationship_field == "references":
                valid_field = (
                    self.relationship_type == "references"
                    and self.source_raw_ref == self.owner_raw_ref
                    and self.target_raw_ref == self.member_raw_ref
                )
            elif nested_reference_field:
                valid_field = (
                    self.relationship_type == "contains"
                    and self.source_raw_ref == self.owner_raw_ref
                    and self.target_raw_ref == self.member_raw_ref
                )
            else:
                expected_type = child_source_fields.get(self.relationship_field)
                valid_field = (
                    expected_type == self.relationship_type
                    and self.source_raw_ref == self.member_raw_ref
                    and self.target_raw_ref == self.owner_raw_ref
                )
            if not valid_field:
                raise ValueError(
                    "canonical source custody field/direction differs"
                )
        if self.relationship_id != stable_id(
            "rel",
            self.relationship_type,
            self.source_element_id,
            self.target_element_id,
            self.normalized_relationship_field,
        ):
            raise ValueError("canonical source custody relationship ID differs")
        if self.normalization_outcome in {
            "normalized_edge",
            "root_reading_order",
        } and self.normalized_relationship_field != self.relationship_field:
            raise ValueError(
                "canonical source custody normalization field differs"
            )
        if _bounded_table_json_size(self, _CUSTODY_MAX_RECORD_BYTES) is None:
            raise ValueError("canonical source custody record exceeds its byte cap")
        return self


class CanonicalSourceCustody(StrictTableApiModel):
    """Closed diagnostic-only custody for opaque raw Docling groups."""

    policy_id: Literal["p04-opaque-raw-group-custody-v1"]
    schema_version: Literal["1.0"]
    authority: Literal["diagnostic_only"]
    source_sha256: TableSha256
    # The custody sealer is allowed to construct an intermediate sidecar
    # before the terminal canonical splice.  A marked ParseResult below
    # requires this to be a literal digest and bind its final canonical view.
    canonical_presentation_sha256: TableSha256 | None = None
    record_count: StrictInt = Field(ge=0, le=_CUSTODY_MAX_RECORDS)
    records_sha256: TableSha256
    records: list[OpaqueRawGroupCustodyRecord] = Field(
        max_length=_CUSTODY_MAX_RECORDS,
    )

    @model_validator(mode="after")
    def validate_closed_graph(self) -> CanonicalSourceCustody:
        if self.record_count != len(self.records):
            raise ValueError("canonical source custody record count differs")
        order = [
            (
                record.owner_order,
                record.relationship_field,
                record.raw_slot_index,
                (
                    record.raw_target_slot_index
                    if record.raw_target_slot_index is not None
                    else -1
                ),
                record.relationship_id,
            )
            for record in self.records
        ]
        if (
            [record.record_order for record in self.records]
            != list(range(len(self.records)))
            or order != sorted(order)
        ):
            raise ValueError("canonical source custody order differs")
        if len({record.record_id for record in self.records}) != len(self.records):
            raise ValueError("canonical source custody record identity repeats")
        from app.services.opaque_group_custody import record_id

        if any(
            record.record_id
            != record_id(
                record.model_dump(mode="json", exclude={"record_id"}),
                self.source_sha256,
            )
            for record in self.records
        ):
            raise ValueError("canonical source custody record ID differs")
        memberships: dict[
            tuple[str, str],
            list[tuple[int, int | None]],
        ] = {}
        group_bindings: dict[str, tuple[str, str, str, str, int]] = {}
        raw_endpoint_bindings: dict[str, tuple[str, str, str, str, int]] = {}
        public_element_raw_refs: dict[str, str] = {}
        relationship_bindings: dict[str, tuple[Any, ...]] = {}
        records_by_relationship: dict[
            str,
            list[OpaqueRawGroupCustodyRecord],
        ] = {}
        for record in self.records:
            memberships.setdefault(
                (record.owner_raw_ref, record.relationship_field), []
            ).append(
                (record.raw_slot_index, record.raw_target_slot_index)
            )
            group_endpoint = (
                (
                    record.source_content_basis,
                    record.source_content_sha256,
                )
                if record.source_raw_ref == record.group_raw_ref
                else (
                    record.target_content_basis,
                    record.target_content_sha256,
                )
            )
            binding = (
                record.group_element_id,
                record.group_type,
                *group_endpoint,
                record.page_index,
            )
            if (
                record.group_raw_ref in group_bindings
                and group_bindings[record.group_raw_ref] != binding
            ):
                raise ValueError("canonical source custody group binding differs")
            group_bindings[record.group_raw_ref] = binding
            for (
                raw_ref,
                element_id,
                element_type,
                content_basis,
                content_sha256,
            ) in (
                (
                    record.source_raw_ref,
                    record.source_element_id,
                    record.source_type,
                    record.source_content_basis,
                    record.source_content_sha256,
                ),
                (
                    record.target_raw_ref,
                    record.target_element_id,
                    record.target_type,
                    record.target_content_basis,
                    record.target_content_sha256,
                ),
            ):
                endpoint_binding = (
                    element_id,
                    element_type,
                    content_basis,
                    content_sha256,
                    record.page_index,
                )
                if (
                    raw_ref in raw_endpoint_bindings
                    and raw_endpoint_bindings[raw_ref] != endpoint_binding
                ):
                    raise ValueError(
                        "canonical source custody raw endpoint differs"
                    )
                raw_endpoint_bindings[raw_ref] = endpoint_binding
                if content_basis == "public_ir":
                    if (
                        element_id in public_element_raw_refs
                        and public_element_raw_refs[element_id] != raw_ref
                    ):
                        raise ValueError(
                            "canonical source custody public raw binding differs"
                        )
                    public_element_raw_refs[element_id] = raw_ref
            relationship_binding = (
                record.relationship_type,
                record.normalized_relationship_field,
                record.normalized_relationship_sha256,
                record.normalized_evidence_count,
                record.normalized_assertion_count,
                record.source_element_id,
                record.target_element_id,
                record.source_raw_ref,
                record.target_raw_ref,
            )
            if (
                record.relationship_id in relationship_bindings
                and relationship_bindings[record.relationship_id]
                != relationship_binding
            ):
                raise ValueError(
                    "canonical source custody normalized relationship differs"
                )
            relationship_bindings[record.relationship_id] = relationship_binding
            records_by_relationship.setdefault(record.relationship_id, []).append(
                record
            )
        if any(len(indexes) != len(set(indexes)) for indexes in memberships.values()):
            raise ValueError("canonical source custody raw slot order differs")
        for relationship_records in records_by_relationship.values():
            if any(
                record.normalized_assertion_count
                != len(relationship_records)
                for record in relationship_records
            ):
                raise ValueError(
                    "canonical source custody normalized assertion count differs"
                )
            root_records = [
                record
                for record in relationship_records
                if record.normalization_outcome == "root_reading_order"
            ]
            if root_records:
                if len(root_records) != len(relationship_records) or any(
                    record.edge_kind != "root_reading_order"
                    or record.normalized_relationship_field
                    != record.relationship_field
                    for record in root_records
                ):
                    raise ValueError(
                        "canonical source custody root normalization differs"
                    )
                continue
            normalized = [
                record
                for record in relationship_records
                if record.normalization_outcome == "normalized_edge"
            ]
            merged = [
                record
                for record in relationship_records
                if record.normalization_outcome == "merged_edge"
            ]
            if (
                len(normalized) != 1
                or len(normalized) + len(merged) != len(relationship_records)
                or normalized[0].normalized_relationship_field
                != normalized[0].relationship_field
                or any(
                    record.normalized_relationship_field
                    != normalized[0].normalized_relationship_field
                    for record in merged
                )
            ):
                raise ValueError(
                    "canonical source custody normalization outcome differs"
                )
        from app.services.opaque_group_custody import records_sha256

        if self.records_sha256 != records_sha256(
            [record.model_dump(mode="json") for record in self.records]
        ):
            raise ValueError("canonical source custody records digest differs")
        if _bounded_table_json_size(self, _CUSTODY_MAX_DOCUMENT_BYTES) is None:
            raise ValueError("canonical source custody exceeds its document byte cap")
        return self


class ParseResult(ApiModel):
    schema_version: str = "1.0"
    document: DocumentMetadata
    pages: list[PageResult]
    processing: ProcessingMetadata
    warnings: list[str] = Field(default_factory=list)
    running_region_concerns: SkipJsonSchema[
        list[ProjectedRunningRegionConcern | NonprojectingRunningRegionConcern]
    ] = Field(
        default_factory=list,
        exclude_if=lambda value: not value,
    )
    canonical_source_custody: CanonicalSourceCustody | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )

    @model_validator(mode="wrap")
    @classmethod
    def validate_table_resource_envelope(cls, value: Any, handler: Any) -> Any:
        # Reject callback-bearing/custom raw mappings before touching any of
        # their methods.  An already validated ParseResult is the only
        # non-exact-dict input admitted to this wrapper.
        if (
            isinstance(value, Mapping)
            and type(value) is not dict
            and not isinstance(value, cls)
        ):
            raise ValueError("parse result raw mapping shape differs")
        raw_aggregate_bytes = _preflight_raw_table_document(value)
        _preflight_raw_marked_canonical(value)
        raw_custody_bytes = _preflight_raw_canonical_source_custody(value)
        if (
            raw_aggregate_bytes is not None
            and raw_custody_bytes is not None
            and raw_aggregate_bytes + raw_custody_bytes
            > _TABLE_MAX_DOCUMENT_SIDECAR_BYTES
        ):
            raise ValueError(
                "table evidence and canonical source custody exceed their "
                "document byte cap"
            )
        result = handler(value)
        if not isinstance(result, cls):
            return result

        marked: list[TableEvidence] = []
        item_ids: set[str] = set()
        table_ids: set[str] = set()
        candidate_ids: set[str] = set()
        duplicate_item_id = False
        invalid_reading_order = False
        visual_region_ids: set[str] = set()
        visual_evidence_ids: set[str] = set()
        visual_model_observation_ids: set[str] = set()
        has_visual_structure = False
        for page in result.pages:
            if [item.reading_order for item in page.items] != list(
                range(len(page.items))
            ):
                invalid_reading_order = True
            for item in page.items:
                if "_p04_predecessor_snapshot" in (item.model_extra or {}):
                    raise ValueError(
                        "private P04 predecessor snapshot reached the API"
                    )
                if item.id in item_ids:
                    duplicate_item_id = True
                item_ids.add(item.id)
                structure = item.visual_structure
                if structure is not None:
                    has_visual_structure = True
                    if item.bbox is None:
                        raise ValueError("visual structure owner bbox is unavailable")
                    public_box = item.bbox
                    region_box = structure.region.page_bbox
                    if (
                        region_box.unit != page.unit
                        or public_box.unit != page.unit
                        or any(
                            abs(left - right) > 1e-6
                            for left, right in (
                                (region_box.x, public_box.x),
                                (region_box.y, public_box.y),
                                (region_box.width, public_box.width),
                                (region_box.height, public_box.height),
                            )
                        )
                    ):
                        raise ValueError("visual structure region bbox differs")
                    if structure.region.id in visual_region_ids:
                        raise ValueError("visual region identity repeats")
                    visual_region_ids.add(structure.region.id)
                    for record in structure.evidence:
                        if record.id in visual_evidence_ids:
                            raise ValueError("visual evidence identity repeats")
                        visual_evidence_ids.add(record.id)
                        provenance = record.provenance
                        if (
                            provenance.public_item_id != item.id
                            or provenance.page_index != page.page_index
                        ):
                            raise ValueError(
                                "visual evidence public ownership differs"
                            )
                model_bundle = item.visual_model_evidence
                if model_bundle is not None:
                    if model_bundle.page_index != page.page_index:
                        raise ValueError("visual-model evidence page differs")
                    if structure is not None:
                        allowed_evidence = {
                            record.id for record in structure.evidence
                        }
                        if any(
                            not set(observation.evidence_ids) <= allowed_evidence
                            for observation in model_bundle.observations
                        ):
                            raise ValueError(
                                "visual-model evidence leaves Phase 05 evidence"
                            )
                    for observation in model_bundle.observations:
                        if observation.id in visual_model_observation_ids:
                            raise ValueError(
                                "visual-model observation identity repeats"
                            )
                        visual_model_observation_ids.add(observation.id)
                office_fallback = item.office_visual_fallback
                if office_fallback is not None and (
                    office_fallback.logical_index != page.page_index
                    or office_fallback.logical_label != page.page_label
                    or (
                        office_fallback.status == "merged"
                        and office_fallback.transform_target_unit != page.unit
                    )
                ):
                    raise ValueError("Office fallback page binding differs")
                evidence = item.table_evidence
                if evidence is None:
                    continue
                if (
                    evidence.table_id in table_ids
                    or evidence.candidate_id in candidate_ids
                ):
                    raise ValueError("marked table document identity repeats")
                table_ids.add(evidence.table_id)
                candidate_ids.add(evidence.candidate_id)
                marked.append(evidence)

        if (marked or has_visual_structure) and (
            duplicate_item_id or invalid_reading_order
        ):
            raise ValueError("marked item identity/order differs")
        if marked and raw_aggregate_bytes is None:
            aggregate_bytes = 0
            for evidence in marked:
                marker_bytes = _bounded_table_json_size(
                    evidence,
                    _TABLE_MAX_SIDECAR_BYTES,
                )
                if marker_bytes is None:
                    raise ValueError("table evidence exceeds its byte cap")
                aggregate_bytes += marker_bytes
                if aggregate_bytes > _TABLE_MAX_DOCUMENT_SIDECAR_BYTES:
                    raise ValueError(
                        "table evidence document aggregate exceeds its byte cap"
                    )
            custody_bytes = (
                _bounded_table_json_size(
                    result.canonical_source_custody,
                    _CUSTODY_MAX_DOCUMENT_BYTES,
                )
                if result.canonical_source_custody is not None
                else None
            )
            if custody_bytes is None:
                raise ValueError(
                    "marked table canonical source custody is absent or oversized"
                )
            if (
                aggregate_bytes + custody_bytes
                > _TABLE_MAX_DOCUMENT_SIDECAR_BYTES
            ):
                raise ValueError(
                    "table evidence and canonical source custody exceed their "
                    "document byte cap"
                )
        return result

    @model_validator(mode="before")
    @classmethod
    def validate_projected_numeric_inputs(cls, value: Any) -> Any:
        """Keep security-relevant projected numbers out of coercive paths."""

        if not isinstance(value, Mapping):
            return value
        public_pages = value.get("pages")
        has_marked_table = False
        if isinstance(public_pages, list):
            for page in public_pages:
                if not isinstance(page, Mapping):
                    continue
                items = page.get("items")
                if isinstance(items, list) and any(
                    isinstance(item, Mapping)
                    and "_p04_predecessor_snapshot" in item
                    for item in items
                ):
                    raise ValueError("private P04 predecessor snapshot reached the API")
                if isinstance(items, list) and any(
                    isinstance(item, Mapping)
                    and item.get("table_evidence") is not None
                    for item in items
                ):
                    has_marked_table = True
        processing = value.get("processing")
        summary = (
            processing.get("running_regions")
            if isinstance(processing, Mapping)
            else None
        )
        if (
            not has_marked_table
            and (
                not isinstance(summary, Mapping)
                or summary.get("status") != "projected"
            )
        ):
            return value
        document = value.get("document")
        pages = value.get("pages")
        if not isinstance(document, Mapping) or not isinstance(pages, list):
            raise ValueError("projected running-region document shape differs")
        page_count = document.get("page_count")
        if isinstance(page_count, bool) or not isinstance(page_count, int):
            raise ValueError("projected document page count is not strict")
        for page_offset, page in enumerate(pages):
            if not isinstance(page, Mapping):
                raise ValueError("projected public page differs")
            page_index = page.get("page_index")
            if isinstance(page_index, bool) or not isinstance(page_index, int):
                raise ValueError("projected public page index is not strict")
            for field in ("page_width", "page_height"):
                number = _strict_number(page.get(field))
                if not _table_number_is_finite(number) or number <= 0:
                    raise ValueError("projected public page geometry differs")
            page_number = page.get("page_number")
            if isinstance(page_number, bool) or not isinstance(page_number, (int, str)):
                raise ValueError("projected public page number differs")
            items = page.get("items")
            if not isinstance(items, list):
                raise ValueError("projected public items differ")
            for item in items:
                if not isinstance(item, Mapping):
                    raise ValueError("projected public item differs")
                reading_order = item.get("reading_order")
                if isinstance(reading_order, bool) or not isinstance(
                    reading_order, int
                ):
                    raise ValueError("projected item reading order is not strict")
                confidence = item.get("confidence")
                if confidence is not None:
                    numeric_confidence = _strict_number(confidence)
                    if (
                        not _table_number_is_finite(numeric_confidence)
                        or not 0 <= numeric_confidence <= 1
                    ):
                        raise ValueError("projected item confidence differs")
                bbox = item.get("bbox")
                if bbox is not None:
                    if not isinstance(bbox, Mapping):
                        raise ValueError("projected item bbox differs")
                    for field in ("x", "y", "width", "height"):
                        coordinate = _strict_number(bbox.get(field))
                        if not _table_number_is_finite(coordinate):
                            raise ValueError("projected item bbox differs")
                    if bbox.get("width") < 0 or bbox.get("height") < 0:
                        raise ValueError("projected item bbox differs")
            for item in items:
                descriptor = item.get("running_region")
                if not isinstance(descriptor, Mapping):
                    continue
                predecessor_type = descriptor.get("predecessor_type")
                if not isinstance(predecessor_type, str):
                    continue
                if descriptor.get("source_method") == "extracted_source_contribution":
                    path = descriptor.get("source_public_path")
                    if (
                        not isinstance(path, list)
                        or path[:3] != ["pages", page_offset, "items"]
                        or len(path) != 4
                        or isinstance(path[3], bool)
                        or not isinstance(path[3], int)
                        or not 0 <= path[3] < len(items)
                    ):
                        continue
                    owner = items[path[3]]
                    if not isinstance(owner, Mapping):
                        continue
                    raw_payload = {
                        key: member
                        for key, member in owner.items()
                        if member is not None
                    }
                    typed_payload = _public_item_payload(
                        ContentItem.model_validate(owner)
                    )
                else:
                    raw_payload = {
                        key: member
                        for key, member in item.items()
                        if member is not None and key not in _RUNNING_MARKER_KEYS
                    }
                    raw_payload["type"] = predecessor_type
                    typed_payload = _predecessor_item_payload(
                        ContentItem.model_validate(item),
                        predecessor_type,
                    )
                if _strict_json_bytes(raw_payload) != _strict_json_bytes(typed_payload):
                    raise ValueError("projected predecessor compact item differs")
        return value

    @model_validator(mode="after")
    def validate_running_region_concerns(self) -> ParseResult:
        summary = self.processing.running_regions
        if summary is None:
            if (
                self.running_region_concerns
                or "running_region_concerns" in self.model_fields_set
                or "running_regions" in self.processing.model_fields_set
            ):
                raise ValueError("running-region fields require a summary")
            if _contains_running_region_remnant(self.model_extra or {}):
                raise ValueError("summary-free output retains running-region fields")
            if _contains_running_region_remnant(self.document.model_extra or {}):
                raise ValueError("summary-free document retains running-region fields")
            if _contains_running_region_remnant(self.processing.model_extra or {}):
                raise ValueError(
                    "summary-free processing retains running-region fields"
                )
            for page in self.pages:
                if (
                    page.page_identity is not None
                    or "page_identity" in page.model_fields_set
                    or _contains_running_region_remnant(page.model_extra or {})
                ):
                    raise ValueError("summary-free page retains running-region fields")
                for item in page.items:
                    if (
                        _RUNNING_MARKER_KEYS.intersection(item.model_fields_set)
                        or _contains_running_region_remnant(item.model_extra or {})
                        or _contains_running_region_remnant(item.value)
                    ):
                        raise ValueError(
                            "summary-free item retains running-region fields"
                        )
            return self
        if len(self.running_region_concerns) != summary.concern_count:
            raise ValueError("running-region concern count differs")
        if summary.status == "projected":
            if any(
                not isinstance(value, ProjectedRunningRegionConcern)
                for value in self.running_region_concerns
            ):
                raise ValueError("projected running-region concern shape differs")
            identities = [
                (value.source_ref, value.code)
                for value in self.running_region_concerns
                if isinstance(value, ProjectedRunningRegionConcern)
            ]
            if identities != sorted(identities) or len(identities) != len(
                set(identities)
            ):
                raise ValueError("projected running-region concern order differs")
            if any(
                value.source_ref.startswith("page:")
                and int(value.source_ref.split(":", 1)[1]) > len(self.pages)
                for value in self.running_region_concerns
                if isinstance(value, ProjectedRunningRegionConcern)
            ):
                raise ValueError("projected running-region concern page differs")
            if (
                not _SHA256_RE.fullmatch(self.document.sha256)
                or self.document.page_count != len(self.pages)
                or summary.source_page_count != len(self.pages)
                or summary.identity_count != len(self.pages)
                or any(page.page_identity is None for page in self.pages)
            ):
                raise ValueError("projected page/document coverage differs")
            expected_indexes = list(range(1, len(self.pages) + 1))
            if [page.page_index for page in self.pages] != expected_indexes:
                raise ValueError("projected physical page order differs")
            canonical_raw = (self.model_extra or {}).get("canonical_presentation")
            if not isinstance(canonical_raw, Mapping):
                raise ValueError("projected canonical presentation is absent")
            from app.services.presentation import CanonicalPresentation

            canonical = CanonicalPresentation.model_validate(canonical_raw)
            if len(canonical.pages) != len(self.pages):
                raise ValueError("projected canonical page coverage differs")
            canonical_raw_pages = canonical_raw.get("pages")
            if not isinstance(canonical_raw_pages, list):
                raise ValueError("projected canonical pages differ")
            for raw_page in canonical_raw_pages:
                if not isinstance(raw_page, Mapping):
                    raise ValueError("projected canonical page differs")
                _validate_canonical_page_views(raw_page)
            expected_document_views = _canonical_document_views(canonical_raw_pages)
            if any(
                canonical_raw.get(name) != expected
                for name, expected in expected_document_views.items()
            ):
                raise ValueError("projected canonical document views differ")
            if _contains_running_region_remnant(
                {
                    key: member
                    for key, member in (self.model_extra or {}).items()
                    if key != "canonical_presentation"
                }
            ):
                raise ValueError("projected output has an unknown running-region field")
            if any(
                _contains_running_region_remnant(model.model_extra or {})
                for model in (self.document, self.processing)
            ):
                raise ValueError(
                    "projected metadata has an unknown running-region field"
                )

            canonical_by_index = {page.page_index: page for page in canonical.pages}
            display_counts = {
                "detected_printed_label": 0,
                "embedded_label": 0,
                "legacy_display_fallback": 0,
                "physical": 0,
            }
            visible_concerns: dict[tuple[str, str], int] = {}
            public_item_ids: set[str] = set()
            descriptors: list[
                tuple[ContentItem, RunningRegionDescriptor, int, int]
            ] = []
            descriptor_ids: set[str] = set()
            source_element_ids: set[str] = set()
            repetition_groups: dict[str, list[RunningRegionDescriptor]] = {}
            role_counts = {
                "header": 0,
                "footer": 0,
                "navigation_top": 0,
                "navigation_bottom": 0,
            }
            extracted_document_count = 0

            def charge_visible(code: str, page_index: int) -> None:
                key = (f"page:{page_index}", code)
                visible_concerns[key] = visible_concerns.get(key, 0) + 1

            for page, canonical_page in zip(self.pages, canonical.pages, strict=True):
                identity = page.page_identity
                if identity is None or identity.physical_page_index != page.page_index:
                    raise ValueError("projected page identity index differs")
                if (
                    page.unit != "pt"
                    or canonical_page.page_index != page.page_index
                    or canonical_page.page_id != identity.page_id
                    or canonical_page.page_number != page.page_number
                    or canonical_page.page_label != page.page_label
                    or canonical_page.page_identity != identity
                ):
                    raise ValueError("projected public/canonical page custody differs")
                display_counts[identity.display_source] += 1
                for code in identity.concern_codes:
                    charge_visible(code, page.page_index)
                if (
                    identity.detected_printed_label is None
                    and identity.embedded_label is None
                ):
                    try:
                        safe_legacy = _bounded_label_string(
                            page.page_label,
                            maximum_bytes=256,
                        )
                    except ValueError:
                        safe_legacy = None
                    if safe_legacy is not None:
                        if (
                            identity.display_source != "legacy_display_fallback"
                            or identity.display_label != safe_legacy
                        ):
                            raise ValueError(
                                "projected legacy page identity precedence differs"
                            )
                    elif (
                        identity.display_source != "physical"
                        or identity.display_label != str(page.page_index)
                    ):
                        raise ValueError(
                            "projected physical page identity precedence differs"
                        )
                    elif (
                        page.page_label not in (None, "")
                        and "page_identity_display_unsafe" not in identity.concern_codes
                    ):
                        raise ValueError(
                            "projected unsafe page label lacks its concern"
                        )

                evidence = identity.evidence_source
                if identity.evidence_bbox is not None:
                    box = identity.evidence_bbox
                    if (
                        box.x + box.width > page.page_width
                        or box.y + box.height > page.page_height
                    ):
                        raise ValueError("page identity evidence bbox exceeds its page")
                    expected_evidence_id = _stable_running_id(
                        "label-candidate",
                        _RUNNING_POLICY_ID,
                        self.document.sha256,
                        page.page_index,
                        evidence.source_object_ids,
                        _model_bbox_payload(box),
                    )
                    if evidence.evidence_ids != [expected_evidence_id]:
                        raise ValueError("page identity source candidate ID differs")
                    if evidence.public_path:
                        position = evidence.public_path[3]
                        if position >= len(page.items):
                            raise ValueError("page identity public owner is absent")
                        owner = page.items[position]
                        owner_text = owner.value
                        if owner_text is None:
                            owner_text = owner.md
                        if (
                            owner.id != evidence.public_item_id
                            or owner_text != identity.visible_text
                            or owner.bbox is None
                            or not _same_bbox(owner.bbox, box)
                        ):
                            raise ValueError("page identity public owner differs")
                        if owner.running_region is not None and (
                            owner.running_region.source_element_id
                            != evidence.element_id
                            or owner.running_region.bbox_id != evidence.bbox_id
                        ):
                            raise ValueError("page identity marked owner differs")
                elif identity.display_source == "embedded_label":
                    expected_evidence_id = _stable_running_id(
                        "embedded-page-label",
                        _RUNNING_POLICY_ID,
                        self.document.sha256,
                        page.page_index,
                        identity.embedded_label,
                    )
                    expected_source_id = (
                        f"pypdfium2:{self.document.sha256}:page:"
                        f"{page.page_index}:embedded_label"
                    )
                    if evidence.evidence_ids != [
                        expected_evidence_id
                    ] or evidence.source_object_ids != [expected_source_id]:
                        raise ValueError("embedded page identity source differs")
                elif identity.display_source == "legacy_display_fallback":
                    expected_source_id = (
                        f"configured-predecessor:{self.document.sha256}:page:"
                        f"{page.page_index}:page_label"
                    )
                    actual_source_id = (
                        evidence.source_object_ids[0]
                        if len(evidence.source_object_ids) == 1
                        else ""
                    )
                    if (
                        evidence.source_object_ids != [expected_source_id]
                        or (match := _LEGACY_SOURCE_RE.fullmatch(actual_source_id))
                        is None
                        or (
                            match.group(1) != self.document.sha256
                            or int(match.group(2)) != page.page_index
                        )
                    ):
                        raise ValueError("legacy page identity source differs")

                extracted_items: list[tuple[ContentItem, RunningRegionDescriptor]] = []
                extracted_suffix_started = False
                for position, item in enumerate(page.items):
                    if not item.id or item.id in public_item_ids:
                        raise ValueError("projected public item ID differs")
                    public_item_ids.add(item.id)
                    marker_fields = _RUNNING_MARKER_KEYS.intersection(
                        item.model_fields_set
                    )
                    if _contains_running_region_remnant(item.model_extra or {}):
                        raise ValueError("projected item has an unknown sidecar")
                    if not marker_fields:
                        if extracted_suffix_started:
                            raise ValueError(
                                "extracted running-region suffix is not contiguous"
                            )
                        continue
                    if marker_fields != _RUNNING_MARKER_KEYS or (
                        item.layout_running_region_projected is not True
                        or item.running_region_policy != _RUNNING_POLICY_ID
                        or item.running_region is None
                    ):
                        raise ValueError("projected running-region sidecar is partial")
                    descriptor = item.running_region
                    extracted = (
                        descriptor.source_method == "extracted_source_contribution"
                    )
                    if extracted:
                        extracted_suffix_started = True
                        extracted_document_count += 1
                        extracted_items.append((item, descriptor))
                    elif extracted_suffix_started:
                        raise ValueError(
                            "direct running region follows extracted suffix"
                        )
                    if (
                        descriptor.id in descriptor_ids
                        or descriptor.source_element_id in source_element_ids
                    ):
                        raise ValueError("projected running-region ownership repeats")
                    descriptor_ids.add(descriptor.id)
                    source_element_ids.add(descriptor.source_element_id)
                    descriptors.append((item, descriptor, page.page_index, position))
                    role_counts[descriptor.role] += 1
                    for code in descriptor.concern_codes:
                        charge_visible(code, page.page_index)
                    if descriptor.repetition_group_id is not None:
                        repetition_groups.setdefault(
                            descriptor.repetition_group_id, []
                        ).append(descriptor)
                    elif extracted:
                        raise ValueError(
                            "extracted running region lacks repetition custody"
                        )
                if len(extracted_items) > _MAX_EXTRACTED_REGIONS_PER_PAGE:
                    raise ValueError("page extracted running-region cap exceeded")
                if len([value for value in page.items if value.running_region]) > (
                    _MAX_RUNNING_REGIONS_PER_PAGE
                ):
                    raise ValueError("page running-region cap exceeded")
                if extracted_items:
                    ids = [descriptor.id for _item, descriptor in extracted_items]
                    if ids != sorted(ids):
                        raise ValueError("extracted running-region order differs")
                    predecessor_ranks = [
                        item.reading_order
                        for item in page.items
                        if item.running_region is None
                        or item.running_region.source_method
                        != "extracted_source_contribution"
                    ]
                    start = max(predecessor_ranks, default=-1) + 1
                    if [item.reading_order for item, _ in extracted_items] != list(
                        range(start, start + len(extracted_items))
                    ):
                        raise ValueError(
                            "extracted running-region reading ranks differ"
                        )

            if extracted_document_count > _MAX_EXTRACTED_REGIONS_PER_DOCUMENT:
                raise ValueError("document extracted running-region cap exceeded")
            if len(repetition_groups) > _MAX_REPETITION_GROUPS_PER_DOCUMENT:
                raise ValueError("document repetition-group cap exceeded")
            for members in repetition_groups.values():
                member_pages = sorted(
                    {member.physical_page_index for member in members}
                )
                if len(member_pages) != len(members) or any(
                    member.repetition_page_indexes != member_pages for member in members
                ):
                    raise ValueError("repetition group membership differs")

            canonical_blocks = {
                block.id: block for page in canonical.pages for block in page.blocks
            }
            for item, descriptor, page_index, position in descriptors:
                page = self.pages[page_index - 1]
                expected_type = (
                    "header"
                    if descriptor.role in {"header", "navigation_top"}
                    else "footer"
                )
                if (
                    page.page_identity is None
                    or descriptor.page_id != page.page_identity.page_id
                ):
                    raise ValueError("running-region descriptor page differs")
                if (
                    descriptor.physical_page_index != page_index
                    or item.type != expected_type
                    or item.bbox is None
                    or not _same_bbox(item.bbox, descriptor.bbox)
                    or descriptor.bbox.x + descriptor.bbox.width > page.page_width
                    or descriptor.bbox.y + descriptor.bbox.height > page.page_height
                ):
                    raise ValueError("running-region public owner differs")
                path_position = descriptor.source_public_path[3]
                if path_position >= len(page.items):
                    raise ValueError("running-region public path is absent")
                owner = page.items[path_position]
                if descriptor.source_method == "extracted_source_contribution":
                    text = _bounded_extracted_text(item.value)
                    if (
                        item.md != text
                        or item.source != "native"
                        or item.confidence != 1.0
                        or path_position >= position
                        or owner is item
                        or _RUNNING_MARKER_KEYS.intersection(owner.model_fields_set)
                        or owner.id != descriptor.source_public_item_id
                        or owner.type != descriptor.predecessor_type
                        or descriptor.predecessor_item_sha256
                        != _sha256_json(_public_item_payload(owner))
                    ):
                        raise ValueError("extracted running-region custody differs")
                    stable_parts: tuple[Any, ...] = (
                        _RUNNING_POLICY_ID,
                        self.document.sha256,
                        page_index,
                        descriptor.source_public_item_id,
                        descriptor.source_object_ids,
                        descriptor.evidence_ids,
                        descriptor.bbox_id,
                        descriptor.role,
                    )
                    if item.id != _stable_running_id(
                        "running-region-item", *stable_parts
                    ):
                        raise ValueError("extracted running-region item ID differs")
                else:
                    if (
                        owner is not item
                        or descriptor.source_public_item_id != item.id
                        or descriptor.predecessor_item_sha256
                        != _sha256_json(
                            _predecessor_item_payload(item, descriptor.predecessor_type)
                        )
                    ):
                        raise ValueError("direct running-region custody differs")
                    stable_parts = (
                        _RUNNING_POLICY_ID,
                        self.document.sha256,
                        page_index,
                        descriptor.source_element_id,
                        descriptor.bbox_id,
                        descriptor.role,
                    )
                if descriptor.id != _stable_running_id("running-region", *stable_parts):
                    raise ValueError("running-region stable ID differs")
                block = canonical_blocks.get(descriptor.canonical_block_id)
                canonical_page = canonical_by_index[page_index]
                if (
                    block is None
                    or block.page_id != descriptor.page_id
                    or block.primary_element_id != descriptor.source_element_id
                    or block.primary_element_type != item.type
                    or block.scope != descriptor.canonical_scope
                    or block.omission_reason is not None
                    or not block.contributing_element_ids
                    or block.contributing_element_ids[0] != descriptor.source_element_id
                    or descriptor.canonical_block_id in canonical_page.body.block_ids
                    or canonical_page.full.block_ids.count(
                        descriptor.canonical_block_id
                    )
                    != 1
                    or getattr(
                        canonical_page, descriptor.canonical_scope
                    ).block_ids.count(descriptor.canonical_block_id)
                    != 1
                ):
                    raise ValueError("running-region canonical custody differs")

            if (
                len(descriptors) != summary.running_region_count
                or display_counts["detected_printed_label"]
                != summary.detected_label_count
                or display_counts["embedded_label"] != summary.embedded_label_count
                or display_counts["legacy_display_fallback"]
                + display_counts["physical"]
                != summary.legacy_fallback_count
                or role_counts["header"] != summary.header_count
                or role_counts["footer"] != summary.footer_count
                or role_counts["navigation_top"] != summary.top_navigation_count
                or role_counts["navigation_bottom"] != summary.bottom_navigation_count
            ):
                raise ValueError("projected processing counts differ")
            concern_records = {
                (value.source_ref, value.code): value
                for value in self.running_region_concerns
                if isinstance(value, ProjectedRunningRegionConcern)
            }
            if any(
                key not in concern_records or concern_records[key].count < count
                for key, count in visible_concerns.items()
            ):
                raise ValueError("projected concern correlation differs")
            if sum(value.count for value in concern_records.values()) > (
                _MAX_CONCERNS_PER_DOCUMENT
            ):
                raise ValueError("projected concern document cap differs")
            page_occurrences: dict[str, int] = {}
            for value in concern_records.values():
                page_occurrences[value.source_ref] = (
                    page_occurrences.get(value.source_ref, 0) + value.count
                )
            if any(
                source_ref != "document" and count > _MAX_CONCERNS_PER_PAGE
                for source_ref, count in page_occurrences.items()
            ):
                raise ValueError("projected concern page cap differs")
            return self
        if any(
            not isinstance(value, NonprojectingRunningRegionConcern)
            for value in self.running_region_concerns
        ):
            raise ValueError("nonprojecting running-region concern shape differs")
        allowed = {
            "unavailable": {summary.reason},
            "not_applicable": set(),
            "failed_closed": {
                "running_region_canonical_custody_invalid",
                "running_region_projection_failed_closed",
            },
        }[summary.status]
        if any(value.code not in allowed for value in self.running_region_concerns):
            raise ValueError("nonprojecting running-region concern code differs")
        if (summary.concern_count == 0) != (
            "running_region_concerns" not in self.model_fields_set
        ):
            raise ValueError("nonprojecting concern presence differs")
        if _contains_running_region_remnant(self.model_extra or {}) or any(
            _contains_running_region_remnant(model.model_extra or {})
            for model in (self.document, self.processing)
        ):
            raise ValueError("nonprojecting output retains running-region extras")
        if any(
            page.page_identity is not None
            or "page_identity" in page.model_fields_set
            or _contains_running_region_remnant(page.model_extra or {})
            or any(
                _RUNNING_MARKER_KEYS.intersection(item.model_fields_set)
                or _contains_running_region_remnant(item.model_extra or {})
                or _contains_running_region_remnant(item.value)
                for item in page.items
            )
            for page in self.pages
        ):
            raise ValueError("nonprojecting output retains running-region sidecars")
        return self

    @model_validator(mode="after")
    def validate_table_evidence_custody(
        self,
        info: ValidationInfo,
    ) -> ParseResult:
        follow_up = self._validate_table_evidence_custody_impl(info.context)
        if follow_up is not None:
            if (
                info.context is not None
                or type(follow_up) is not _TableContextFreeValidationContext
            ):
                raise ValueError(
                    "marked table context-free validation recursion differs"
                )
            if self._validate_table_evidence_custody_impl(follow_up) is not None:
                raise ValueError(
                    "marked table context-free validation recursion differs"
                )
        return self

    def _validate_table_evidence_custody_impl(
        self,
        validation_context: Any,
    ) -> _TableContextFreeValidationContext | None:
        marked_items: list[tuple[PageResult, ContentItem]] = []
        for page in self.pages:
            for item in page.items:
                if "_p04_predecessor_snapshot" in (item.model_extra or {}):
                    raise ValueError(
                        "private P04 predecessor snapshot reached the API"
                    )
                if item.table_evidence is not None:
                    marked_items.append((page, item))
        if not marked_items:
            if (
                self.canonical_source_custody is not None
                or "canonical_source_custody" in self.model_fields_set
            ):
                raise ValueError(
                    "canonical source custody requires a literal table marker"
                )
            return None
        if self.canonical_source_custody is None:
            raise ValueError("marked table canonical source custody is absent")
        expected_page_indexes = list(range(1, len(self.pages) + 1))
        if (
            self.document.page_count != len(self.pages)
            or [page.page_index for page in self.pages] != expected_page_indexes
        ):
            raise ValueError("marked table page/document coverage differs")
        if _SHA256_RE.fullmatch(self.document.sha256) is None:
            raise ValueError("marked table document identity differs")

        from app.services.table_semantics import validate_table_semantics

        for page, item in marked_items:
            evidence = item.table_evidence

            def fits_page(box: Any) -> bool:
                return box is None or (
                    box.unit == "pt"
                    and all(
                        _table_number_is_finite(number)
                        for number in (box.x, box.y, box.width, box.height)
                    )
                    and box.x + box.width <= page.page_width
                    and box.y + box.height <= page.page_height
                )

            valid_cell_geometry = True
            valid_recovery_geometry = True
            if evidence is not None:
                valid_recovery_geometry = all(
                    fits_page(word.bbox)
                    for source in evidence.source_objects
                    if isinstance(source, TablePdfplumberSourceObject)
                    for word in source.words
                )
            if evidence is not None and (
                evidence.status == "valid"
                or evidence.status == "unresolved"
                and evidence.reconciliation is not None
                and evidence.reconciliation.outcome == "unresolved"
                and bool(evidence.grid.cell_ids)
            ):
                cells = (item.model_extra or {}).get("cells")
                valid_cell_geometry = isinstance(cells, list) and all(
                    raw_cell.get("bbox") is None
                    or (
                        raw_cell["bbox"]["x"] + raw_cell["bbox"]["width"]
                        <= page.page_width
                        and raw_cell["bbox"]["y"]
                        + raw_cell["bbox"]["height"]
                        <= page.page_height
                    )
                    for raw_cell in cells
                )
            if (
                evidence is None
                or page.unit != "pt"
                or not _table_number_is_finite(page.page_width)
                or not _table_number_is_finite(page.page_height)
                or evidence.page_index != page.page_index
                or not fits_page(item.bbox)
                or not all(fits_page(record.bbox) for record in evidence.evidence)
                or not valid_recovery_geometry
                or not valid_cell_geometry
                or not validate_table_semantics(
                    item.model_dump(mode="json"),
                    self.document.sha256,
                )
            ):
                raise ValueError("marked table topology or custody differs")

        extras = self.model_extra or {}
        if "canonical_presentation" not in extras:
            raise ValueError("marked table canonical presentation is absent")
        canonical_raw = extras.get("canonical_presentation")
        if not isinstance(canonical_raw, Mapping):
            raise ValueError("marked table canonical presentation differs")

        from app.services.presentation import CanonicalPresentation

        canonical = CanonicalPresentation.model_validate(canonical_raw)
        custody = self.canonical_source_custody
        if (
            custody is None
            or custody.canonical_presentation_sha256 is None
            or custody.canonical_presentation_sha256
            != _canonical_presentation_sha256(canonical_raw)
        ):
            raise ValueError(
                "canonical source custody canonical presentation digest differs"
            )
        canonical_indexes = [page.page_index for page in canonical.pages]
        expected_indexes = [page.page_index for page in self.pages]
        if canonical_indexes != expected_indexes:
            raise ValueError("marked table canonical page coverage differs")

        trusted_baseline = _trusted_table_baseline_from_context(
            validation_context
        )
        trusted_custody_identity = (
            _trusted_table_custody_identity_from_context(
                validation_context
            )
        )
        trusted_custody_relationship_ids = (
            _trusted_table_custody_relationship_ids_from_context(
                validation_context
            )
        )
        context_free_validation = _table_context_free_validation_from_context(
            validation_context,
            self,
        )
        if (
            type(validation_context) is _TrustedTableValidationContext
            and trusted_baseline is None
        ):
            raise ValueError("trusted table validation context differs")
        if (
            type(validation_context) is _TableContextFreeValidationContext
            and context_free_validation is None
        ):
            raise ValueError(
                "marked table context-free validation context differs"
            )
        if trusted_baseline is not None and context_free_validation is not None:
            raise ValueError("marked table validation contexts overlap")
        trusted_non_target_positions: set[tuple[int, int]] = set()
        trusted_nonvalid_target_positions: set[tuple[int, int]] = set()
        trusted_blocks_by_position: dict[tuple[int, int], Any] = {}
        trusted_target_blocks_by_position: dict[tuple[int, int], Any] = {}
        if trusted_baseline is not None:
            if (
                trusted_baseline.canonical_source_custody is not None
                or any(
                    item.table_evidence is not None
                    for page in trusted_baseline.pages
                    for item in page.items
                )
            ):
                raise ValueError("trusted P03 baseline carries table authority")

            def exact_model_payload(model: BaseModel) -> bytes:
                return _strict_json_bytes(
                    model.model_dump(mode="json", exclude_unset=True)
                )

            def stable_result_extras(result: ParseResult) -> dict[str, Any]:
                return {
                    key: member
                    for key, member in (result.model_extra or {}).items()
                    if key != "canonical_presentation"
                }

            if (
                self.schema_version != trusted_baseline.schema_version
                or exact_model_payload(self.document)
                != exact_model_payload(trusted_baseline.document)
                or exact_model_payload(self.processing)
                != exact_model_payload(trusted_baseline.processing)
                or _strict_json_bytes(self.warnings)
                != _strict_json_bytes(trusted_baseline.warnings)
                or _strict_json_bytes(
                    [
                        value.model_dump(mode="json", exclude_unset=True)
                        for value in self.running_region_concerns
                    ]
                )
                != _strict_json_bytes(
                    [
                        value.model_dump(mode="json", exclude_unset=True)
                        for value in trusted_baseline.running_region_concerns
                    ]
                )
                or _strict_json_bytes(stable_result_extras(self))
                != _strict_json_bytes(stable_result_extras(trusted_baseline))
                or len(self.pages) != len(trusted_baseline.pages)
            ):
                raise ValueError("trusted P03 baseline document differs")

            for page, baseline_page in zip(
                self.pages,
                trusted_baseline.pages,
                strict=True,
            ):
                page_payload = page.model_dump(
                    mode="json",
                    exclude_unset=True,
                    exclude={"items"},
                )
                baseline_page_payload = baseline_page.model_dump(
                    mode="json",
                    exclude_unset=True,
                    exclude={"items"},
                )
                if (
                    _strict_json_bytes(page_payload)
                    != _strict_json_bytes(baseline_page_payload)
                    or len(page.items) != len(baseline_page.items)
                ):
                    raise ValueError("trusted P03 baseline page differs")
                for item_offset, (item, baseline_item) in enumerate(
                    zip(page.items, baseline_page.items, strict=True)
                ):
                    position = (page.page_index, item_offset)
                    if item.table_evidence is not None:
                        if (
                            baseline_item.table_evidence is not None
                            or item.id != baseline_item.id
                            or item.type != baseline_item.type
                            or item.reading_order != baseline_item.reading_order
                            or (
                                item.bbox.model_dump(mode="json")
                                if item.bbox is not None
                                else None
                            )
                            != (
                                baseline_item.bbox.model_dump(mode="json")
                                if baseline_item.bbox is not None
                                else None
                            )
                        ):
                            raise ValueError(
                                "trusted P03 baseline table locator differs"
                            )
                        if item.table_evidence.status in {
                            "unresolved",
                            "structural_failure",
                        }:
                            item_payload = item.model_dump(
                                mode="json",
                                exclude_unset=True,
                            )
                            baseline_item_payload = baseline_item.model_dump(
                                mode="json",
                                exclude_unset=True,
                            )
                            item_payload.pop("table_evidence", None)
                            baseline_item_payload.pop("table_evidence", None)
                            if _strict_json_bytes(item_payload) != (
                                _strict_json_bytes(baseline_item_payload)
                            ):
                                raise ValueError(
                                    "trusted P03 baseline nonvalid table "
                                    "representation differs"
                                )
                            trusted_nonvalid_target_positions.add(position)
                        continue
                    if exact_model_payload(item) != exact_model_payload(
                        baseline_item
                    ):
                        raise ValueError(
                            "trusted P03 baseline non-target item differs"
                        )
                    # The P04 terminal splice normally restores an unchanged
                    # P03 non-target block byte-for-byte.  Visual and
                    # running-region overlays are the two exceptions: their
                    # public projection can intentionally narrow predecessor
                    # child authority at the table seam.  Do not grandfather
                    # those canonical blocks through the private baseline;
                    # require the complete public overlay contract below.
                    item_extras = item.model_extra or {}
                    if not (
                        item_extras.get(
                            "layout_visual_relationships_projected"
                        )
                        is True
                        or item.running_region is not None
                    ):
                        trusted_non_target_positions.add(position)

            trusted_canonical_raw = (
                trusted_baseline.model_extra or {}
            ).get("canonical_presentation")
            if not isinstance(trusted_canonical_raw, Mapping):
                raise ValueError("trusted P03 baseline canonical is absent")
            trusted_canonical = CanonicalPresentation.model_validate(
                trusted_canonical_raw
            )
            if [page.page_index for page in trusted_canonical.pages] != (
                expected_indexes
            ):
                raise ValueError("trusted P03 baseline canonical pages differ")
            for baseline_page, baseline_canonical_page in zip(
                trusted_baseline.pages,
                trusted_canonical.pages,
                strict=True,
            ):
                if len(baseline_page.items) != len(
                    baseline_canonical_page.blocks
                ):
                    raise ValueError(
                        "trusted P03 baseline canonical coverage differs"
                    )
                for item_offset, baseline_block in enumerate(
                    baseline_canonical_page.blocks
                ):
                    position = (baseline_page.page_index, item_offset)
                    if position in trusted_non_target_positions:
                        trusted_blocks_by_position[position] = baseline_block
                    elif position in trusted_nonvalid_target_positions:
                        trusted_target_blocks_by_position[position] = (
                            baseline_block
                        )

        document_id = _canonical_ir_id("doc", self.document.sha256)
        canonical_pages = {page.page_index: page for page in canonical.pages}
        public_items_by_primary: dict[str, ContentItem] = {}
        blocks_by_primary: dict[str, Any] = {}
        trusted_blocks_by_primary: dict[str, Any] = {}
        trusted_target_blocks_by_primary: dict[str, Any] = {}
        expected_primary_ids: list[str] = []
        for page in self.pages:
            canonical_page = canonical_pages[page.page_index]
            expected_page_id = (
                page.page_identity.page_id
                if (
                    self.processing.running_regions is not None
                    and self.processing.running_regions.status == "projected"
                    and page.page_identity is not None
                )
                else _canonical_ir_id(
                    "page",
                    document_id,
                    page.page_index,
                )
            )
            if (
                canonical_page.page_id != expected_page_id
                or type(canonical_page.page_number) is not type(page.page_number)
                or canonical_page.page_number != page.page_number
                or canonical_page.page_label != page.page_label
                or (
                    canonical_page.page_identity.model_dump(mode="json")
                    if canonical_page.page_identity is not None
                    else None
                )
                != (
                    page.page_identity.model_dump(mode="json")
                    if page.page_identity is not None
                    else None
                )
            ):
                raise ValueError("marked table canonical page binding differs")
            if len(canonical_page.blocks) != len(page.items):
                raise ValueError("marked table canonical block coverage differs")
            for item_offset, (item, block) in enumerate(
                zip(page.items, canonical_page.blocks, strict=True)
            ):
                primary_id = _canonical_expected_primary_id(
                    document_id,
                    page.page_index,
                    item_offset,
                    item,
                )
                expected_block_id = _canonical_expected_block_id(
                    expected_page_id,
                    primary_id,
                    item,
                )
                expected_scope = (
                    item.type.casefold()
                    if item.type.casefold() in {"header", "footer"}
                    else "body"
                )
                if (
                    block.id != expected_block_id
                    or block.page_id != expected_page_id
                    or block.primary_element_id != primary_id
                    or block.primary_element_type != item.type
                    or block.scope != expected_scope
                ):
                    raise ValueError("marked table canonical block binding differs")
                if primary_id in public_items_by_primary:
                    raise ValueError("marked table canonical primary binding repeats")
                public_items_by_primary[primary_id] = item
                blocks_by_primary[primary_id] = block
                expected_primary_ids.append(primary_id)

                position = (page.page_index, item_offset)
                trusted_block = trusted_blocks_by_position.get(position)
                if trusted_block is not None:
                    if (
                        trusted_block.id != block.id
                        or trusted_block.page_id != block.page_id
                        or trusted_block.primary_element_id != primary_id
                        or trusted_block.primary_element_type != block.primary_element_type
                        or trusted_block.scope != block.scope
                    ):
                        raise ValueError(
                            "trusted P03 baseline canonical binding differs"
                        )
                    trusted_blocks_by_primary[primary_id] = trusted_block
                trusted_target_block = trusted_target_blocks_by_position.get(
                    position
                )
                if trusted_target_block is not None:
                    if (
                        trusted_target_block.id != block.id
                        or trusted_target_block.page_id != block.page_id
                        or trusted_target_block.primary_element_id != primary_id
                        or trusted_target_block.primary_element_type
                        != block.primary_element_type
                        or trusted_target_block.scope != block.scope
                    ):
                        raise ValueError(
                            "trusted P03 baseline table canonical binding differs"
                        )
                    trusted_target_blocks_by_primary[primary_id] = (
                        trusted_target_block
                    )

        actual_primary_ids = [
            block.primary_element_id
            for page in canonical.pages
            for block in page.blocks
        ]
        if actual_primary_ids != expected_primary_ids:
            raise ValueError("marked table canonical block order differs")
        if len(trusted_blocks_by_primary) != len(trusted_non_target_positions):
            raise ValueError("trusted P03 baseline canonical coverage differs")
        if len(trusted_target_blocks_by_primary) != len(
            trusted_nonvalid_target_positions
        ):
            raise ValueError("trusted P03 baseline table coverage differs")

        context_free_owner_records: dict[
            tuple[int, int],
            tuple[Any, ...],
        ] = {}
        context_free_inert_records: dict[
            tuple[int, int],
            tuple[Any, ...],
        ] = {}
        if context_free_validation is not None:
            for record in context_free_validation.deferred_owners:
                if (
                    type(record) is not tuple
                    or len(record) != 8
                    or type(record[0]) is not int
                    or type(record[1]) is not int
                    or type(record[2]) is not str
                    or type(record[3]) is not str
                    or type(record[4]) is not str
                    or type(record[5]) is not str
                    or type(record[6]) is not tuple
                    or record[7]
                    not in {"empty", "nonempty", "nonempty_deduplicated"}
                ):
                    raise ValueError(
                        "marked table context-free owner record differs"
                    )
                (
                    page_index,
                    item_offset,
                    public_id,
                    primary_id,
                    _base,
                    _actual,
                    source_sensitive_children,
                    ledger_mode,
                ) = record
                position = (page_index, item_offset)
                if (
                    position in context_free_owner_records
                    or not 1 <= page_index <= len(self.pages)
                    or not 0 <= item_offset < len(
                        self.pages[page_index - 1].items
                    )
                ):
                    raise ValueError(
                        "marked table context-free owner position differs"
                    )
                item = self.pages[page_index - 1].items[item_offset]
                if (
                    item.id != public_id
                    or public_items_by_primary.get(primary_id) is not item
                    or not _context_free_visual_ocr_predecessor_is_closed(item)
                    or source_sensitive_children
                    != _context_free_visual_source_sensitive_children(item)
                    or ledger_mode
                    != _context_free_visual_ledger_mode_payload(
                        item.model_extra or {}
                    )
                ):
                    raise ValueError(
                        "marked table context-free owner binding differs"
                    )
                context_free_owner_records[position] = record
            if (
                len(context_free_validation.inert_remnants)
                > _MAX_CONTEXT_FREE_INERT_REMNANTS
            ):
                raise ValueError(
                    "marked table context-free inert-remnant cap differs"
                )
            for record in context_free_validation.inert_remnants:
                if (
                    type(record) is not tuple
                    or len(record) != 8
                    or type(record[0]) is not int
                    or type(record[1]) is not int
                    or type(record[2]) is not str
                    or type(record[3]) is not str
                    or type(record[4]) is not str
                    or type(record[5]) is not str
                    or type(record[6]) is not str
                    or type(record[7]) is not str
                ):
                    raise ValueError(
                        "marked table context-free inert-remnant record differs"
                    )
                (
                    page_index,
                    item_offset,
                    public_id,
                    primary_id,
                    _base,
                    _actual,
                    _relationship_id,
                    _excluded_id,
                ) = record
                position = (page_index, item_offset)
                if (
                    position in context_free_inert_records
                    or position in context_free_owner_records
                    or not 1 <= page_index <= len(self.pages)
                    or not 0 <= item_offset < len(
                        self.pages[page_index - 1].items
                    )
                ):
                    raise ValueError(
                        "marked table context-free inert-remnant position differs"
                    )
                item = self.pages[page_index - 1].items[item_offset]
                if (
                    item.id != public_id
                    or public_items_by_primary.get(primary_id) is not item
                    or not _context_free_inert_raw_group_owner_is_closed(
                        item,
                        primary_id,
                    )
                ):
                    raise ValueError(
                        "marked table context-free inert-remnant binding differs"
                    )
                context_free_inert_records[position] = record

        def public_predecessor_payload(
            page: PageResult,
            item_offset: int,
            item: ContentItem,
        ) -> dict[str, Any]:
            if item.running_region is not None:
                return _predecessor_item_payload(
                    item,
                    item.running_region.predecessor_type,
                )
            payload = _layout_predecessor_item_payload(item)
            if (
                item.table_evidence is not None
                and item.table_evidence.status
                in {"unresolved", "structural_failure"}
            ):
                payload.pop("table_evidence", None)
            if (page.page_index, item_offset) in context_free_owner_records:
                payload["source"] = "ocr"
            return payload

        public_payload = {
            "document": {"sha256": self.document.sha256},
            "pages": [
                {
                    "page_index": page.page_index,
                    "page_number": page.page_number,
                    "page_label": page.page_label,
                    "page_width": page.page_width,
                    "page_height": page.page_height,
                    "unit": page.unit,
                    "success": page.success,
                    "items": [
                        public_predecessor_payload(
                            page,
                            item_offset,
                            item,
                        )
                        for item_offset, item in enumerate(page.items)
                    ],
                    "warnings": list(page.warnings),
                }
                for page in self.pages
            ],
        }
        try:
            from app.services.ir import DocumentIR, build_document_ir
            from app.services.presentation import (
                _build_canonical_presentation_from_validated,
            )

            public_ir = build_document_ir(public_payload)
            if type(public_ir) is not DocumentIR:
                raise ValueError(
                    "marked table reconstructed public IR differs"
                )
            predecessor_canonical = (
                _build_canonical_presentation_from_validated(public_ir)
            )
        except Exception as exc:
            raise ValueError("marked table canonical IR binding differs") from exc
        public_ir_projection: tuple[Any, ...] | None = None
        if context_free_validation is not None:
            deferred_owner_ids = {
                record[3]
                for record in context_free_validation.deferred_owners
            }
            source_sensitive_owners = {
                record[3]: (record[7], record[6])
                for record in context_free_validation.deferred_owners
            }
            public_ir_projection = _context_free_ir_identity_projection(
                public_ir,
                source_sensitive_owners,
            )
            ir_delta_is_closed = (
                _context_free_ir_delta_is_closed(
                    context_free_validation.base_ir_projection,
                    public_ir_projection,
                    deferred_owner_ids,
                )
                if deferred_owner_ids
                else context_free_validation.base_ir_projection
                == public_ir_projection
            )
            if not ir_delta_is_closed:
                raise ValueError(
                    "marked table context-free semantic-child closure differs"
                )
        known_element_ids = {element.id for element in public_ir.elements}
        known_element_ids.update(expected_primary_ids)
        public_relationships_by_endpoint: dict[str, list[Any]] = {}
        for relationship in public_ir.relationships:
            for endpoint_id in {
                relationship.source_id,
                relationship.target_id,
            }:
                public_relationships_by_endpoint.setdefault(
                    endpoint_id,
                    [],
                ).append(relationship)
        reconstructed_by_primary: dict[str, Any] = {}
        predecessor_blocks_by_primary: dict[str, Any] = {}
        ir_elements_by_id = {element.id: element for element in public_ir.elements}
        if custody is None or custody.source_sha256 != self.document.sha256:
            raise ValueError("canonical source custody document binding differs")
        if trusted_custody_identity is not None and (
            custody.policy_id,
            custody.schema_version,
            custody.authority,
            custody.source_sha256,
            custody.canonical_presentation_sha256,
            custody.record_count,
            custody.records_sha256,
        ) != trusted_custody_identity:
            raise ValueError("trusted table canonical source custody differs")
        all_custody_relationship_ids = {
            record.relationship_id for record in custody.records
        }
        all_custody_endpoint_ids = {
            endpoint_id
            for record in custody.records
            for endpoint_id in (
                record.member_element_id,
                record.group_element_id,
                record.counterpart_element_id,
                record.source_element_id,
                record.target_element_id,
            )
        }
        if trusted_custody_identity is not None and (
            trusted_custody_relationship_ids is None
            or tuple(sorted(all_custody_relationship_ids))
            != trusted_custody_relationship_ids
        ):
            raise ValueError("trusted table canonical source custody differs")

        public_relationship_ids = {
            relationship.id for relationship in public_ir.relationships
        }
        from app.services.opaque_group_custody import (
            empty_group_content_sha256,
            member_content_sha256,
            stable_id,
        )

        ir_pages_by_id = {page.id: page for page in public_ir.pages}
        content_digest_cache: dict[str, str] = {}

        def public_content_digest(element: Any) -> str:
            digest = content_digest_cache.get(element.id)
            if digest is None:
                digest = member_content_sha256(element)
                content_digest_cache[element.id] = digest
            return digest

        def validate_endpoint(
            *,
            element_id: str,
            raw_ref: str,
            element_type: str,
            basis: str,
            digest: str,
            page_index: int,
            label: str,
        ) -> None:
            element = ir_elements_by_id.get(element_id)
            if element is None:
                if (
                    element_id
                    != stable_id("el", public_ir.id, "raw_ref", raw_ref)
                    or not raw_ref.startswith("#/groups/")
                    or element_type not in {"group", "list"}
                    or basis != "opaque_group_empty"
                    or digest != empty_group_content_sha256(element_type)
                ):
                    raise ValueError(
                        f"canonical source custody raw {label} differs"
                    )
                return
            ir_page = ir_pages_by_id.get(element.page_id)
            if (
                ir_page is None
                or page_index != ir_page.page_index
                or element.type != element_type
                or basis != "public_ir"
                or digest != public_content_digest(element)
            ):
                raise ValueError(
                    f"canonical source custody {label} binding differs"
                )

        for record in custody.records:
            if not 1 <= record.page_index <= len(self.pages):
                raise ValueError("canonical source custody page binding differs")
            validate_endpoint(
                element_id=record.source_element_id,
                raw_ref=record.source_raw_ref,
                element_type=record.source_type,
                basis=record.source_content_basis,
                digest=record.source_content_sha256,
                page_index=record.page_index,
                label="source",
            )
            validate_endpoint(
                element_id=record.target_element_id,
                raw_ref=record.target_raw_ref,
                element_type=record.target_type,
                basis=record.target_content_basis,
                digest=record.target_content_sha256,
                page_index=record.page_index,
                label="target",
            )
            public_group = ir_elements_by_id.get(record.group_element_id)
            if public_group is None:
                if record.group_element_id != stable_id(
                    "el",
                    public_ir.id,
                    "raw_ref",
                    record.group_raw_ref,
                ):
                    raise ValueError("canonical source custody group ID differs")
            elif public_group.type != record.group_type:
                raise ValueError("canonical source custody public group differs")
            if (
                record.relationship_id in public_relationship_ids
            ):
                raise ValueError(
                    "diagnostic canonical source custody carries authority"
                )
        if len(public_ir.pages) != len(self.pages):
            raise ValueError("marked table canonical IR page coverage differs")
        for page, ir_page, predecessor_page in zip(
            self.pages,
            public_ir.pages,
            predecessor_canonical.pages,
            strict=True,
        ):
            if len(ir_page.presentation_element_ids) != len(page.items):
                raise ValueError("marked table canonical IR block coverage differs")
            if len(predecessor_page.blocks) != len(page.items):
                raise ValueError("marked table canonical IR block coverage differs")
            for item_offset, (item, reconstructed_id, predecessor_block) in enumerate(
                zip(
                    page.items,
                    ir_page.presentation_element_ids,
                    predecessor_page.blocks,
                    strict=True,
                )
            ):
                primary_id = _canonical_expected_primary_id(
                    document_id,
                    page.page_index,
                    item_offset,
                    item,
                )
                reconstructed = ir_elements_by_id.get(reconstructed_id)
                if reconstructed is None:
                    raise ValueError("marked table canonical IR element differs")
                reconstructed_by_primary[primary_id] = reconstructed
                predecessor_blocks_by_primary[primary_id] = predecessor_block

        from app.services.presentation import (
            _table_output_from_selected_children,
        )

        for primary_id, item in public_items_by_primary.items():
            caption_ids = (item.model_extra or {}).get("caption_ids")
            if (
                item.table_evidence is None
                or item.table_evidence.status == "valid"
                or type(caption_ids) is not list
                or not caption_ids
            ):
                continue
            owner_element = reconstructed_by_primary[primary_id]
            predecessor_block = predecessor_blocks_by_primary[primary_id]
            declared_children = [
                ir_elements_by_id[relationship.target_id]
                for relationship in public_ir.relationships
                if relationship.type.value == "contains"
                and relationship.source_id == owner_element.id
                and relationship.target_id in ir_elements_by_id
            ]
            selected_ids = set(predecessor_block.contributing_element_ids)
            selected_children = [
                child
                for child in declared_children
                if child.id in selected_ids
            ]
            try:
                markdown, text = _table_output_from_selected_children(
                    owner_element,
                    selected_children,
                    declared_children,
                    {},
                    {},
                    {},
                )
            except Exception as exc:
                raise ValueError(
                    "marked table nonvalid predecessor reconstruction differs"
                ) from exc
            predecessor_blocks_by_primary[primary_id] = (
                predecessor_block.model_copy(
                    update={"markdown": markdown, "text": text}
                )
            )

        def predecessor_block_identity(
            block: Any,
        ) -> tuple[str, str]:
            payload = block.model_dump(mode="json")
            stable_payload = dict(payload)
            stable_payload.pop("relationship_ids", None)
            stable_payload.pop("excluded_contributions", None)
            return _sha256_json(payload), _sha256_json(stable_payload)

        if context_free_validation is not None:
            base_predecessor_blocks = {
                record[0]: (record[1], record[2])
                for record in context_free_validation.base_predecessor_blocks
                if type(record) is tuple
                and len(record) == 3
                and type(record[0]) is str
                and type(record[1]) is str
                and type(record[2]) is str
            }
            deferred_primary_ids = {
                record[3]
                for record in context_free_validation.deferred_owners
            }
            if set(base_predecessor_blocks) != set(expected_primary_ids):
                raise ValueError(
                    "marked table context-free predecessor coverage differs"
                )
            for primary_id in expected_primary_ids:
                full_hash, stable_hash = predecessor_block_identity(
                    predecessor_blocks_by_primary[primary_id]
                )
                base_full_hash, base_stable_hash = base_predecessor_blocks[
                    primary_id
                ]
                if primary_id in deferred_primary_ids:
                    if (
                        stable_hash != base_stable_hash
                        or full_hash == base_full_hash
                    ):
                        raise ValueError(
                            "marked table context-free predecessor delta differs"
                        )
                elif (
                    full_hash != base_full_hash
                    or stable_hash != base_stable_hash
                ):
                    raise ValueError(
                        "marked table context-free nondeferred predecessor differs"
                    )

        # P01 raw-group custody remains diagnostic-only.  It can never
        # authorize canonical relationships or exclusions during public,
        # context-free validation.  The terminal producer removes this audit
        # layer using its already-frozen trusted P03 graph before serializing
        # a table-enabled result.
        marked_table_primary_ids = {
            primary_id
            for primary_id, item in public_items_by_primary.items()
            if item.table_evidence is not None
        }
        marked_table_endpoint_ids = set(marked_table_primary_ids)
        for primary_id in marked_table_primary_ids:
            marked_table_endpoint_ids.update(
                predecessor_blocks_by_primary[
                    primary_id
                ].contributing_element_ids
            )
        table_ir_elements = tuple(
            sorted(
                (
                    element_id,
                    _sha256_json(
                        ir_elements_by_id[element_id].model_dump(mode="json")
                    ),
                )
                for element_id in marked_table_endpoint_ids
                if element_id in ir_elements_by_id
            )
        )
        table_ir_relationships = tuple(
            sorted(
                (
                    relationship.id,
                    _sha256_json(relationship.model_dump(mode="json")),
                )
                for relationship in public_ir.relationships
                if {
                    relationship.source_id,
                    relationship.target_id,
                }
                & marked_table_endpoint_ids
            )
        )
        table_ir_relationship_ids = {
            relationship_id
            for relationship_id, _digest in table_ir_relationships
        }
        table_ir_evidence_ids = {
            evidence_id
            for element_id in marked_table_endpoint_ids
            if element_id in ir_elements_by_id
            for evidence_id in ir_elements_by_id[element_id].evidence_ids
        }
        table_ir_evidence_ids.update(
            evidence_id
            for relationship in public_ir.relationships
            if relationship.id in table_ir_relationship_ids
            for evidence_id in relationship.evidence_ids
        )
        ir_evidence_by_id = {
            record.id: record for record in public_ir.evidence
        }
        if not table_ir_evidence_ids <= set(ir_evidence_by_id):
            raise ValueError("marked table IR evidence closure differs")
        table_ir_evidence = tuple(
            sorted(
                (
                    evidence_id,
                    _sha256_json(
                        ir_evidence_by_id[evidence_id].model_dump(mode="json")
                    ),
                )
                for evidence_id in table_ir_evidence_ids
                if evidence_id in ir_evidence_by_id
            )
        )
        table_ir_bbox_ids = {
            bbox_id
            for element_id in marked_table_endpoint_ids
            if element_id in ir_elements_by_id
            for bbox_id in ir_elements_by_id[element_id].bbox_ids
        }
        table_ir_bbox_ids.update(
            record.bbox_id
            for evidence_id, record in ir_evidence_by_id.items()
            if evidence_id in table_ir_evidence_ids
            and record.bbox_id is not None
        )
        ir_bboxes_by_id = {bbox.id: bbox for bbox in public_ir.bboxes}
        if not table_ir_bbox_ids <= set(ir_bboxes_by_id):
            raise ValueError("marked table IR bbox closure differs")
        table_ir_bboxes = tuple(
            sorted(
                (
                    bbox_id,
                    _sha256_json(
                        ir_bboxes_by_id[bbox_id].model_dump(mode="json")
                    ),
                )
                for bbox_id in table_ir_bbox_ids
                if bbox_id in ir_bboxes_by_id
            )
        )
        if context_free_validation is not None and (
            table_ir_bboxes != context_free_validation.table_ir_bboxes
            or table_ir_elements != context_free_validation.table_ir_elements
            or table_ir_evidence != context_free_validation.table_ir_evidence
            or table_ir_relationships
            != context_free_validation.table_ir_relationships
        ):
            raise ValueError(
                "marked table context-free table IR closure differs"
            )

        projection_overlay_keys = {
            "caption_ids",
            "caption_of",
            "contains_ids",
            "contained_items",
            "footnote_ids",
            "footnote_of",
            "layout_source_notes_projected",
            "layout_visual_relationships_projected",
            "relationship_basis",
            "relationship_id",
            "relationship_type",
            "source_note_ids",
            "source_note_of",
        }

        def block_contract(block: Any) -> tuple[Any, ...]:
            relationship_ids = list(block.relationship_ids)
            exclusions = [
                exclusion.model_dump(mode="json")
                for exclusion in block.excluded_contributions
            ]
            return (
                block.markdown,
                block.text,
                list(block.contributing_element_ids),
                relationship_ids,
                exclusions,
                block.omission_reason,
                block.suppressed_by_element_id,
            )

        public_primary_by_public_id = {
            item.id: primary_id
            for primary_id, item in public_items_by_primary.items()
        }
        page_index_by_primary = {
            _canonical_expected_primary_id(
                document_id,
                page.page_index,
                item_offset,
                item,
            ): page.page_index
            for page in self.pages
            for item_offset, item in enumerate(page.items)
        }
        item_offset_by_primary = {
            _canonical_expected_primary_id(
                document_id,
                page.page_index,
                item_offset,
                item,
            ): item_offset
            for page in self.pages
            for item_offset, item in enumerate(page.items)
        }
        exact_primary_ids: set[str] = set()
        trusted_non_target_primary_ids = set(trusted_blocks_by_primary)
        for primary_id, block in blocks_by_primary.items():
            canonical_custody_ids = {
                relationship_id
                for relationship_id in block.relationship_ids
                if relationship_id in all_custody_relationship_ids
            }
            canonical_custody_ids.update(
                relationship_id
                for exclusion in block.excluded_contributions
                for relationship_id in exclusion.relationship_ids
                if relationship_id in all_custody_relationship_ids
            )
            if canonical_custody_ids:
                raise ValueError(
                    "diagnostic canonical source custody carries authority"
                )
        deferred_context_free_owners: list[tuple[Any, ...]] = []
        deferred_context_free_inert_remnants: list[tuple[Any, ...]] = []
        validated_context_free_primary_ids: set[str] = set()
        validated_context_free_inert_primary_ids: set[str] = set()
        context_free_records_by_primary = {
            record[3]: record
            for record in context_free_validation.deferred_owners
        } if context_free_validation is not None else {}
        context_free_inert_records_by_primary = {
            record[3]: record
            for record in context_free_validation.inert_remnants
        } if context_free_validation is not None else {}
        for primary_id, trusted_block in trusted_blocks_by_primary.items():
            block = blocks_by_primary.get(primary_id)
            if (
                block is None
                or block_contract(block) != block_contract(trusted_block)
            ):
                raise ValueError(
                    "trusted P03 baseline non-target canonical block differs "
                    f"for {primary_id}"
                )
            exact_primary_ids.add(primary_id)
        for primary_id, trusted_block in trusted_target_blocks_by_primary.items():
            block = blocks_by_primary.get(primary_id)
            actual_contract = block_contract(block) if block is not None else None
            trusted_contract = block_contract(trusted_block)
            if (
                actual_contract is None
                or tuple(actual_contract[index] for index in (0, 1, 2, 5, 6))
                != tuple(trusted_contract[index] for index in (0, 1, 2, 5, 6))
            ):
                raise ValueError(
                    "trusted P03 baseline table canonical block differs "
                    f"for {primary_id}"
                )

        declared_replacement_primary_ids: set[str] = set()
        for declared_item in public_items_by_primary.values():
            declared_extras = declared_item.model_extra or {}
            raw_form_group = declared_extras.get("form_group")
            if (
                type(raw_form_group) is dict
                and raw_form_group.get("canonical_mode") == "replace"
            ):
                declared_replacement_primary_ids.update(
                    value
                    for value in raw_form_group.get(
                        "contributor_element_ids", []
                    )
                    if type(value) is str
                )
            raw_outline_group = declared_extras.get("outline_group")
            if type(raw_outline_group) is dict:
                for name in (
                    "member_element_ids",
                    "continuation_element_ids",
                    "canonical_contributor_element_ids",
                ):
                    declared_replacement_primary_ids.update(
                        value
                        for value in raw_outline_group.get(name, [])
                        if type(value) is str
                    )

        canonical_relationship_block_uses: dict[str, list[str]] = {}
        canonical_relationship_exclusion_uses: dict[
            str,
            list[tuple[str, str, str]],
        ] = {}
        canonical_excluded_endpoint_uses: dict[
            str,
            list[tuple[str, str, str]],
        ] = {}
        canonical_contributor_ids: set[str] = set()
        for block_primary_id, canonical_block in blocks_by_primary.items():
            canonical_contributor_ids.update(
                canonical_block.contributing_element_ids
            )
            for relationship_id in canonical_block.relationship_ids:
                canonical_relationship_block_uses.setdefault(
                    relationship_id,
                    [],
                ).append(block_primary_id)
            for exclusion in canonical_block.excluded_contributions:
                for relationship_id in exclusion.relationship_ids:
                    use = (
                        block_primary_id,
                        exclusion.element_id,
                        exclusion.reason,
                    )
                    canonical_relationship_exclusion_uses.setdefault(
                        relationship_id,
                        [],
                    ).append(use)
                    canonical_excluded_endpoint_uses.setdefault(
                        exclusion.element_id,
                        [],
                    ).append(
                        (
                            block_primary_id,
                            relationship_id,
                            exclusion.reason,
                        )
                    )
        table_forbidden_endpoint_ids = set(marked_table_endpoint_ids)
        for primary_id in marked_table_primary_ids:
            marked_block = blocks_by_primary[primary_id]
            table_forbidden_endpoint_ids.update(
                marked_block.contributing_element_ids
            )
            table_forbidden_endpoint_ids.update(
                exclusion.element_id
                for exclusion in marked_block.excluded_contributions
            )

        bounded_raw_ref_identity_cache: dict[
            str,
            dict[str, tuple[str, ...]],
        ] = {}

        def bounded_raw_ref_identities(
            collection: str,
        ) -> dict[str, tuple[str, ...]]:
            """Return the complete bounded raw-ref identity map once."""

            cached = bounded_raw_ref_identity_cache.get(collection)
            if cached is not None:
                return cached
            if collection not in {"groups", "texts"}:
                raise ValueError(
                    "marked table bounded raw-ref collection differs"
                )
            gathered: dict[str, list[str]] = {}
            for ordinal in range(_MAX_CONTEXT_FREE_RAW_REF_ORDINALS):
                raw_ref = f"#/{collection}/{ordinal}"
                element_id = stable_id(
                    "el",
                    document_id,
                    "raw_ref",
                    raw_ref,
                )
                gathered.setdefault(element_id, []).append(raw_ref)
            frozen = {
                element_id: tuple(raw_refs)
                for element_id, raw_refs in gathered.items()
            }
            bounded_raw_ref_identity_cache[collection] = frozen
            return frozen

        def inert_raw_group_remnant_record(
            primary_id: str,
            item: ContentItem,
            actual_contract: tuple[Any, ...],
            predecessor_contract: tuple[Any, ...],
        ) -> tuple[Any, ...] | None:
            differing_fields = {
                index
                for index, (actual, expected) in enumerate(
                    zip(
                        actual_contract,
                        predecessor_contract,
                        strict=True,
                    )
                )
                if actual != expected
            }
            if (
                differing_fields != {3, 4}
                or primary_id in marked_table_primary_ids
                or not _context_free_inert_raw_group_owner_is_closed(
                    item,
                    primary_id,
                )
                or actual_contract[5] is not None
                or actual_contract[6] is not None
            ):
                return None
            actual_relationships = actual_contract[3]
            predecessor_relationships = predecessor_contract[3]
            if (
                type(actual_relationships) is not list
                or type(predecessor_relationships) is not list
                or len(actual_relationships)
                != len(predecessor_relationships) + 1
            ):
                return None
            relationship_candidates = [
                relationship_id
                for relationship_id in actual_relationships
                if relationship_id not in predecessor_relationships
                and [
                    value
                    for value in actual_relationships
                    if value != relationship_id
                ]
                == predecessor_relationships
            ]
            if len(relationship_candidates) != 1:
                return None
            relationship_id = relationship_candidates[0]

            actual_exclusions = actual_contract[4]
            predecessor_exclusions = predecessor_contract[4]
            if (
                type(actual_exclusions) is not list
                or type(predecessor_exclusions) is not list
                or len(actual_exclusions) != len(predecessor_exclusions) + 1
            ):
                return None
            exclusion_candidates = [
                exclusion
                for exclusion_offset, exclusion in enumerate(actual_exclusions)
                if actual_exclusions[:exclusion_offset]
                + actual_exclusions[exclusion_offset + 1 :]
                == predecessor_exclusions
            ]
            if len(exclusion_candidates) != 1:
                return None
            exclusion = exclusion_candidates[0]
            if (
                type(exclusion) is not dict
                or set(exclusion)
                != {"element_id", "reason", "relationship_ids"}
                or exclusion.get("reason") != "evidence_only_relationship"
                or exclusion.get("relationship_ids") != [relationship_id]
                or type(exclusion.get("element_id")) is not str
                or re.fullmatch(
                    _CUSTODY_ELEMENT_ID_PATTERN,
                    exclusion["element_id"],
                )
                is None
            ):
                return None
            excluded_id = exclusion["element_id"]
            from app.services.opaque_group_custody import stable_id

            group_raw_refs = bounded_raw_ref_identities("groups").get(
                excluded_id,
                (),
            )

            if (
                len(group_raw_refs) != 1
                or relationship_id
                != stable_id(
                    "rel",
                    "contains",
                    excluded_id,
                    primary_id,
                    "children",
                )
                or canonical_relationship_block_uses.get(relationship_id)
                != [primary_id]
                or canonical_relationship_exclusion_uses.get(relationship_id)
                != [
                    (
                        primary_id,
                        excluded_id,
                        "evidence_only_relationship",
                    )
                ]
                or excluded_id in known_element_ids
                or excluded_id in canonical_contributor_ids
                or excluded_id in table_forbidden_endpoint_ids
                or excluded_id in all_custody_endpoint_ids
                or relationship_id in all_custody_relationship_ids
            ):
                return None
            return (
                page_index_by_primary[primary_id],
                item_offset_by_primary[primary_id],
                item.id,
                primary_id,
                _sha256_json(predecessor_contract),
                _sha256_json(actual_contract),
                relationship_id,
                excluded_id,
            )

        def visual_ocr_inert_remnants_are_closed(
            primary_id: str,
            item: ContentItem,
            actual_contract: tuple[Any, ...],
            expected_contract: tuple[Any, ...],
            context_record: tuple[Any, ...],
        ) -> bool:
            """Close inert raw-text edges after the alternate IR proof."""

            if (
                context_free_validation is None
                or type(actual_contract) is not tuple
                or type(expected_contract) is not tuple
                or context_record[7]
                not in {"nonempty", "nonempty_deduplicated"}
                or _sha256_json(actual_contract) != context_record[5]
                or context_record[4] == context_record[5]
                or _sha256_json(expected_contract)
                in {context_record[4], context_record[5]}
            ):
                return False
            differing_fields = {
                index
                for index, (actual, expected) in enumerate(
                    zip(
                        actual_contract,
                        expected_contract,
                        strict=True,
                    )
                )
                if actual != expected
            }
            if differing_fields != {3, 4}:
                return False

            actual_relationships = actual_contract[3]
            expected_relationships = expected_contract[3]
            if (
                type(actual_relationships) is not list
                or type(expected_relationships) is not list
                or len(set(actual_relationships))
                != len(actual_relationships)
                or len(set(expected_relationships))
                != len(expected_relationships)
            ):
                return False
            expected_relationship_set = set(expected_relationships)
            extra_relationship_ids = [
                relationship_id
                for relationship_id in actual_relationships
                if relationship_id not in expected_relationship_set
            ]
            extra_relationship_id_set = set(extra_relationship_ids)
            if (
                not extra_relationship_ids
                or len(extra_relationship_id_set)
                != len(extra_relationship_ids)
                or [
                    relationship_id
                    for relationship_id in actual_relationships
                    if relationship_id not in extra_relationship_id_set
                ]
                != expected_relationships
            ):
                return False

            actual_exclusions = actual_contract[4]
            expected_exclusions = expected_contract[4]
            if (
                type(actual_exclusions) is not list
                or type(expected_exclusions) is not list
            ):
                return False
            extra_exclusions = [
                exclusion
                for exclusion in actual_exclusions
                if type(exclusion) is dict
                and type(exclusion.get("relationship_ids")) is list
                and bool(
                    set(exclusion["relationship_ids"])
                    & extra_relationship_id_set
                )
            ]
            if (
                len(extra_exclusions) != len(extra_relationship_ids)
                or [
                    exclusion
                    for exclusion in actual_exclusions
                    if exclusion not in extra_exclusions
                ]
                != expected_exclusions
            ):
                return False

            diagnostics = (item.model_extra or {}).get("items")
            if type(diagnostics) is not list:
                return False
            accepted_occurrences = [
                diagnostic
                for diagnostic in diagnostics
                if type(diagnostic) is dict
                and diagnostic.get("accepted") is True
            ]
            if len(accepted_occurrences) != len(extra_relationship_ids):
                return False
            for diagnostic in accepted_occurrences:
                bbox = diagnostic.get("bbox")
                confidence = diagnostic.get("confidence")
                if (
                    set(diagnostic)
                    != {
                        "accepted",
                        "bbox",
                        "confidence",
                        "rejection_reason",
                        "source",
                        "text",
                        "value",
                        "word_count",
                    }
                    or diagnostic.get("source") != "ocr"
                    or diagnostic.get("rejection_reason") is not None
                    or type(diagnostic.get("text")) is not str
                    or not diagnostic["text"].strip()
                    or diagnostic.get("value") != diagnostic["text"]
                    or type(diagnostic.get("word_count")) is not int
                    or diagnostic["word_count"] < 1
                    or type(confidence) not in {int, float}
                    or isinstance(confidence, bool)
                    or not math.isfinite(confidence)
                    or not 0.0 <= confidence <= 1.0
                    or type(bbox) is not dict
                    or set(bbox)
                    != {
                        "h",
                        "height",
                        "unit",
                        "w",
                        "width",
                        "x",
                        "y",
                    }
                    or bbox.get("unit") != "pt"
                    or bbox.get("w") != bbox.get("width")
                    or bbox.get("h") != bbox.get("height")
                    or any(
                        type(bbox.get(field)) not in {int, float}
                        or isinstance(bbox.get(field), bool)
                        or not math.isfinite(bbox[field])
                        for field in ("x", "y", "width", "height")
                    )
                    or bbox["width"] <= 0
                    or bbox["height"] <= 0
                ):
                    return False

            bounded_text_identities = bounded_raw_ref_identities("texts")
            contained_raw_ordinals = sorted(
                int(raw_refs[0].rsplit("/", 1)[1])
                for contained_id in (
                    (item.model_extra or {}).get("contains_ids") or []
                )
                if len(
                    raw_refs := bounded_text_identities.get(
                        contained_id,
                        (),
                    )
                )
                == 1
            )
            if not contained_raw_ordinals:
                return False
            ordered_bindings: list[tuple[int, str, str]] = []
            seen_endpoints: set[str] = set()
            for exclusion in extra_exclusions:
                if (
                    set(exclusion)
                    != {"element_id", "reason", "relationship_ids"}
                    or exclusion.get("reason")
                    != "evidence_only_relationship"
                    or type(exclusion.get("element_id")) is not str
                    or type(exclusion.get("relationship_ids")) is not list
                    or len(exclusion["relationship_ids"]) != 1
                    or exclusion["relationship_ids"][0]
                    not in extra_relationship_id_set
                ):
                    return False
                endpoint_id = exclusion["element_id"]
                relationship_id = exclusion["relationship_ids"][0]
                raw_refs = bounded_text_identities.get(endpoint_id, ())
                if len(raw_refs) != 1:
                    return False
                ordinal = int(raw_refs[0].rsplit("/", 1)[1])
                if (
                    endpoint_id in seen_endpoints
                    or not contained_raw_ordinals[0]
                    < ordinal
                    < contained_raw_ordinals[-1]
                    or relationship_id
                    != stable_id(
                        "rel",
                        "contains",
                        primary_id,
                        endpoint_id,
                        "parent",
                    )
                    or canonical_relationship_block_uses.get(
                        relationship_id
                    )
                    != [primary_id]
                    or canonical_relationship_exclusion_uses.get(
                        relationship_id
                    )
                    != [
                        (
                            primary_id,
                            endpoint_id,
                            "evidence_only_relationship",
                        )
                    ]
                    or canonical_excluded_endpoint_uses.get(endpoint_id)
                    != [
                        (
                            primary_id,
                            relationship_id,
                            "evidence_only_relationship",
                        )
                    ]
                    or endpoint_id in known_element_ids
                    or endpoint_id in canonical_contributor_ids
                    or endpoint_id in table_forbidden_endpoint_ids
                    or endpoint_id in all_custody_endpoint_ids
                    or relationship_id in public_relationship_ids
                    or relationship_id in all_custody_relationship_ids
                ):
                    return False
                seen_endpoints.add(endpoint_id)
                ordered_bindings.append(
                    (ordinal, endpoint_id, relationship_id)
                )
            if (
                {binding[2] for binding in ordered_bindings}
                != extra_relationship_id_set
                or len({binding[0] for binding in ordered_bindings})
                != len(ordered_bindings)
            ):
                return False

            # The public ledger intentionally exposes no raw reference.  Keep
            # one deterministic occurrence ordering while the private context
            # pins the complete first-pass contract on this exact object.
            ordered_bindings.sort(key=lambda binding: binding[0])
            return len(ordered_bindings) == len(accepted_occurrences)

        def assert_manual_contract(
            primary_id: str,
            *,
            markdown: str,
            text: str,
            contributors: Sequence[str],
            relationships: Sequence[str],
            exclusions: Sequence[Mapping[str, Any]],
            omission_reason: str | None = None,
            suppressed_by_element_id: str | None = None,
            label: str = "exact graph",
            context_free_visual_owner: ContentItem | None = None,
        ) -> None:
            block = blocks_by_primary.get(primary_id)
            expected_contract = (
                markdown,
                text,
                list(contributors),
                list(relationships),
                [dict(value) for value in exclusions],
                omission_reason,
                suppressed_by_element_id,
            )
            actual_contract = (
                block_contract(block) if block is not None else None
            )
            context_free_record = context_free_records_by_primary.get(
                primary_id
            )
            if actual_contract != expected_contract:
                differing_fields = (
                    [
                        index
                        for index, (actual, expected) in enumerate(
                            zip(
                                actual_contract,
                                expected_contract,
                                strict=True,
                            )
                        )
                        if actual != expected
                    ]
                    if actual_contract is not None
                    else []
                )
                if (
                    validation_context is None
                    and context_free_visual_owner is not None
                    and set(differing_fields) == {3, 4}
                    and primary_id not in marked_table_primary_ids
                    and _context_free_visual_ocr_predecessor_is_closed(
                        context_free_visual_owner
                    )
                    and primary_id not in {
                        record[3] for record in deferred_context_free_owners
                    }
                ):
                    deferred_context_free_owners.append(
                        (
                            page_index_by_primary[primary_id],
                            item_offset_by_primary[primary_id],
                            context_free_visual_owner.id,
                            primary_id,
                            _sha256_json(expected_contract),
                            _sha256_json(actual_contract),
                            _context_free_visual_source_sensitive_children(
                                context_free_visual_owner
                            ),
                            _context_free_visual_ledger_mode_payload(
                                context_free_visual_owner.model_extra or {}
                            ),
                        )
                    )
                    exact_primary_ids.add(primary_id)
                    return
                if (
                    context_free_visual_owner is not None
                    and context_free_record is not None
                    and visual_ocr_inert_remnants_are_closed(
                        primary_id,
                        context_free_visual_owner,
                        actual_contract,
                        expected_contract,
                        context_free_record,
                    )
                ):
                    validated_context_free_primary_ids.add(primary_id)
                    exact_primary_ids.add(primary_id)
                    return
                raise ValueError(
                    f"marked table canonical {label} differs for {primary_id} "
                    f"at {differing_fields}"
                )
            if (
                context_free_visual_owner is not None
                and context_free_record is not None
                and (
                    context_free_record[4] == context_free_record[5]
                    or _sha256_json(expected_contract)
                    != context_free_record[5]
                    or _sha256_json(actual_contract)
                    != context_free_record[5]
                )
            ):
                raise ValueError(
                    "marked table context-free layout contract differs"
                )
            if (
                context_free_visual_owner is not None
                and context_free_record is not None
            ):
                validated_context_free_primary_ids.add(primary_id)
            exact_primary_ids.add(primary_id)

        for primary_id, block in blocks_by_primary.items():
            if primary_id in trusted_non_target_primary_ids:
                continue
            item = public_items_by_primary[primary_id]
            item_extras = item.model_extra or {}
            predecessor_block = predecessor_blocks_by_primary[primary_id]
            has_semantic_overlay = bool(
                projection_overlay_keys.intersection(item_extras)
                or primary_id in declared_replacement_primary_ids
                or item.running_region is not None
                or type(item_extras.get("outline_group")) is dict
                or (
                    type(item_extras.get("form_group")) is dict
                    and item_extras["form_group"].get("canonical_mode")
                    == "replace"
                )
            )
            if has_semantic_overlay:
                continue
            actual_contract = block_contract(block)
            predecessor_contract = block_contract(predecessor_block)
            if (
                predecessor_block.primary_element_id != primary_id
                or actual_contract != predecessor_contract
            ):
                inert_record = inert_raw_group_remnant_record(
                    primary_id,
                    item,
                    actual_contract,
                    predecessor_contract,
                )
                context_free_inert_record = (
                    context_free_inert_records_by_primary.get(primary_id)
                )
                if (
                    inert_record is not None
                    and validation_context is None
                    and context_free_inert_record is None
                    and len(deferred_context_free_inert_remnants)
                    < _MAX_CONTEXT_FREE_INERT_REMNANTS
                ):
                    deferred_context_free_inert_remnants.append(inert_record)
                    exact_primary_ids.add(primary_id)
                    continue
                if (
                    inert_record is not None
                    and context_free_inert_record is not None
                    and inert_record == context_free_inert_record
                    and inert_record[4] != inert_record[5]
                ):
                    validated_context_free_inert_primary_ids.add(primary_id)
                    exact_primary_ids.add(primary_id)
                    continue
                differing_fields = [
                    index
                    for index, (actual, expected) in enumerate(
                        zip(
                            actual_contract,
                            predecessor_contract,
                            strict=True,
                        )
                    )
                    if actual != expected
                ]
                raise ValueError(
                    "marked table canonical exact graph differs for "
                    f"{primary_id} at {differing_fields}"
                )
            exact_primary_ids.add(primary_id)

        inert_records_for_closure = (
            deferred_context_free_inert_remnants
            if validation_context is None
            else list(context_free_validation.inert_remnants)
            if context_free_validation is not None
            else []
        )
        if inert_records_for_closure:
            excluded_ids = {
                record[7] for record in inert_records_for_closure
            }
            if len(excluded_ids) != 1:
                raise ValueError(
                    "marked table context-free inert-remnant group differs"
                )
            excluded_id = next(iter(excluded_ids))
            expected_endpoint_uses = sorted(
                (
                    record[3],
                    record[6],
                    "evidence_only_relationship",
                )
                for record in inert_records_for_closure
            )
            if sorted(
                canonical_excluded_endpoint_uses.get(excluded_id, [])
            ) != expected_endpoint_uses:
                raise ValueError(
                    "marked table context-free inert-remnant use differs"
                )

        public_document_payload: dict[str, Any] | None = None
        outline_primaries: set[str] = set()
        outline_consumed_primaries: set[str] = set()
        form_replace_primaries: set[str] = set()
        form_consumed_primaries: set[str] = set()
        for primary_id, item in public_items_by_primary.items():
            if primary_id in trusted_non_target_primary_ids:
                continue
            extras = item.model_extra or {}
            raw_outline = extras.get("outline_group")
            if type(raw_outline) is dict and (
                raw_outline.get("anchor_public_item_id") == item.id
            ):
                if public_document_payload is None:
                    public_document_payload = self.model_dump(
                        mode="json",
                        exclude_unset=True,
                    )
                try:
                    from app.services.outline_structure import (
                        PublicOutlineContinuation,
                        PublicOutlineGroup,
                        PublicOutlineItem,
                        _render_outline,
                        _validate_public_anchor as validate_public_outline_anchor,
                    )

                    outline = PublicOutlineGroup.model_validate(raw_outline)
                    raw_outline_items = extras.get("outline_items")
                    raw_outline_continuations = extras.get(
                        "outline_continuations"
                    )
                    if type(raw_outline_items) is not list or type(
                        raw_outline_continuations
                    ) is not list:
                        raise ValueError("outline records differ")
                    outline_items = [
                        PublicOutlineItem.model_validate(value)
                        for value in raw_outline_items
                    ]
                    outline_continuations = [
                        PublicOutlineContinuation.model_validate(value)
                        for value in raw_outline_continuations
                    ]
                    raw_public_anchor = public_document_payload["pages"][
                        page_index_by_primary[primary_id] - 1
                    ]["items"][item_offset_by_primary[primary_id]]
                    validate_public_outline_anchor(
                        public_document_payload,
                        raw_public_anchor,
                        blocks_by_primary[primary_id].model_dump(
                            mode="json",
                            exclude_none=True,
                        ),
                    )

                    predecessor_included_blocks = [
                        candidate
                        for predecessor_page in predecessor_canonical.pages
                        for candidate in predecessor_page.blocks
                        if candidate.omission_reason is None
                    ]
                    target_ids = {
                        primary_id,
                        *outline.member_element_ids,
                        *outline.continuation_element_ids,
                    }
                    owners: dict[str, list[Any]] = {
                        target_id: [] for target_id in target_ids
                    }
                    for candidate in predecessor_included_blocks:
                        for contributor_id in candidate.contributing_element_ids:
                            if contributor_id in owners:
                                owners[contributor_id].append(candidate)
                    if any(len(candidates) != 1 for candidates in owners.values()):
                        raise ValueError("outline predecessor ownership differs")
                    selected_block_ids = {
                        candidates[0].id for candidates in owners.values()
                    }
                    selected_blocks = [
                        candidate
                        for candidate in predecessor_included_blocks
                        if candidate.id in selected_block_ids
                    ]
                    anchor_blocks = [
                        candidate
                        for candidate in selected_blocks
                        if candidate.primary_element_id == primary_id
                    ]
                    if len(anchor_blocks) != 1 or anchor_blocks[0].scope != "body":
                        raise ValueError("outline anchor ownership differs")

                    predecessor_blocks_by_id = {
                        candidate.primary_element_id: candidate
                        for candidate in predecessor_included_blocks
                    }
                    outline_markdown, outline_text = _render_outline(
                        group_id=outline.id,
                        sequence_kind=outline.sequence_kind,
                        marker_style=outline.marker_style,
                        nodes=[
                            {
                                "id": value.id,
                                "raw_marker": value.raw_marker,
                                "body_text": value.body_text,
                                "level": value.level,
                                "ordinal": value.ordinal,
                                "parent_id": value.parent_id,
                            }
                            for value in outline_items
                        ],
                        continuations=[
                            {
                                "element_id": value.element_id,
                                "target_node_id": value.target_node_id,
                            }
                            for value in outline_continuations
                        ],
                        continuation_markdown={
                            value.element_id: predecessor_blocks_by_id[
                                value.element_id
                            ].markdown
                            for value in outline_continuations
                        },
                        continuation_text={
                            value.element_id: predecessor_blocks_by_id[
                                value.element_id
                            ].text
                            for value in outline_continuations
                        },
                    )
                except Exception as exc:
                    raise ValueError(
                        "marked table canonical outline custody differs"
                    ) from exc
                block = blocks_by_primary[primary_id]
                expected_outline_contributors: list[str] = []
                expected_outline_relationship_ids = set(
                    outline.relationship_ids
                )
                predecessor_primary_ids: list[str] = []
                for selected_block in selected_blocks:
                    predecessor_primary_ids.append(
                        selected_block.primary_element_id
                    )
                    expected_outline_relationship_ids.update(
                        selected_block.relationship_ids
                    )
                    for contributor_id in (
                        selected_block.contributing_element_ids
                    ):
                        if contributor_id not in expected_outline_contributors:
                            expected_outline_contributors.append(contributor_id)
                if primary_id in expected_outline_contributors:
                    expected_outline_contributors.remove(primary_id)
                expected_outline_contributors.insert(0, primary_id)
                ordered_outline_relationship_ids = sorted(
                    expected_outline_relationship_ids
                )
                if (
                    outline.canonical_primary_element_id != primary_id
                    or outline.canonical_block_id != block.id
                    or outline.canonical_contributor_element_ids
                    != expected_outline_contributors
                    or outline.canonical_relationship_ids
                    != ordered_outline_relationship_ids
                    or _canonical_sha256_text(outline_markdown)
                    != outline.canonical_markdown_sha256
                    or _canonical_sha256_text(outline_text)
                    != outline.canonical_text_sha256
                    or not predecessor_primary_ids
                    or predecessor_primary_ids[0] != primary_id
                    or any(
                        contributor_id not in public_items_by_primary
                        or page_index_by_primary[contributor_id]
                        != page_index_by_primary[primary_id]
                        for contributor_id in predecessor_primary_ids
                    )
                ):
                    raise ValueError(
                        "marked table canonical outline custody differs"
                    )
                if (
                    primary_id in outline_primaries
                    or primary_id in outline_consumed_primaries
                    or primary_id in form_replace_primaries
                    or primary_id in form_consumed_primaries
                ):
                    raise ValueError(
                        "marked table canonical outline replacement overlaps"
                    )
                assert_manual_contract(
                    primary_id,
                    markdown=outline_markdown,
                    text=outline_text,
                    contributors=expected_outline_contributors,
                    relationships=ordered_outline_relationship_ids,
                    exclusions=[],
                    label="outline exact graph",
                )
                outline_primaries.add(primary_id)
                for contributor_id in predecessor_primary_ids[1:]:
                    if (
                        contributor_id in outline_consumed_primaries
                        or contributor_id in outline_primaries
                        or contributor_id in form_replace_primaries
                        or contributor_id in form_consumed_primaries
                    ):
                        raise ValueError(
                            "marked table canonical outline replacement overlaps"
                        )
                    assert_manual_contract(
                        contributor_id,
                        markdown="",
                        text="",
                        contributors=[],
                        relationships=ordered_outline_relationship_ids,
                        exclusions=[
                            {
                                "element_id": primary_id,
                                "reason": "already_claimed",
                                "relationship_ids": (
                                    ordered_outline_relationship_ids
                                ),
                            }
                        ],
                        omission_reason="consumed_by_relationship",
                        suppressed_by_element_id=primary_id,
                        label="outline replacement closure",
                    )
                    outline_consumed_primaries.add(contributor_id)

            raw_form = extras.get("form_group")
            if type(raw_form) is dict and raw_form.get("canonical_mode") == "replace":
                try:
                    from app.services.form_semantics import (
                        PublicFormGroup,
                        _stable_id as stable_form_id,
                        render_form_group_semantics,
                    )

                    form_group = PublicFormGroup.model_validate(raw_form)
                    rendering = render_form_group_semantics(
                        reconstructed_by_primary[primary_id]
                    )
                    raw_form_relationships = extras.get("relationships")
                    if type(raw_form_relationships) is not list:
                        raise ValueError("form relationships differ")
                    rendered_relationship_id_set = set(
                        rendering.relationship_ids
                        if rendering is not None
                        else ()
                    )
                    expected_form_relationship_ids: list[str] = []
                    for raw_relationship in raw_form_relationships:
                        if (
                            type(raw_relationship) is not dict
                            or raw_relationship.get("id")
                            not in rendered_relationship_id_set
                        ):
                            continue
                        expected_relationship_id = stable_form_id(
                            "form-rel",
                            self.document.sha256,
                            form_group.page_index,
                            raw_relationship.get("type"),
                            raw_relationship.get("source_id"),
                            raw_relationship.get("target_id"),
                        )
                        if raw_relationship.get("id") != expected_relationship_id:
                            raise ValueError("form relationship ID differs")
                        expected_form_relationship_ids.append(
                            expected_relationship_id
                        )
                    if expected_form_relationship_ids != list(
                        rendering.relationship_ids
                        if rendering is not None
                        else ()
                    ):
                        raise ValueError("form relationship order differs")
                except Exception as exc:
                    raise ValueError(
                        "marked table canonical form custody differs"
                    ) from exc
                block = blocks_by_primary[primary_id]
                if rendering is None:
                    raise ValueError("marked table canonical form custody differs")
                expected_form_contributors = [
                    primary_id,
                    *(
                        contributor_id
                        for contributor_id in rendering.contributor_element_ids
                        if contributor_id != primary_id
                    ),
                ]
                if (
                    form_group.anchor_element_id != primary_id
                    or rendering.anchor_element_id != primary_id
                    or form_group.page_index != page_index_by_primary[primary_id]
                    or form_group.contributor_element_ids
                    != list(rendering.contributor_element_ids)
                    or [
                        public_items_by_primary[contributor_id].id
                        for contributor_id in rendering.contributor_element_ids
                        if contributor_id in public_items_by_primary
                    ]
                    != form_group.contributor_public_item_ids
                    or len(
                        set(rendering.contributor_element_ids)
                        & set(public_items_by_primary)
                    )
                    != len(rendering.contributor_element_ids)
                    or any(
                        page_index_by_primary[contributor_id]
                        != page_index_by_primary[primary_id]
                        for contributor_id in rendering.contributor_element_ids
                    )
                    or block_contract(block)
                    != (
                        rendering.markdown,
                        rendering.text,
                        expected_form_contributors,
                        list(rendering.relationship_ids),
                        [],
                        None,
                        None,
                    )
                ):
                    raise ValueError("marked table canonical form custody differs")
                known_element_ids.update(rendering.contributor_element_ids)
                form_replace_primaries.add(primary_id)
                exact_primary_ids.add(primary_id)
                for contributor_id in rendering.contributor_element_ids:
                    if contributor_id == primary_id:
                        continue
                    if (
                        contributor_id in form_consumed_primaries
                        or contributor_id in form_replace_primaries
                        or contributor_id in outline_primaries
                        or contributor_id in outline_consumed_primaries
                    ):
                        raise ValueError(
                            "marked table canonical form replacement overlaps"
                        )
                    assert_manual_contract(
                        contributor_id,
                        markdown="",
                        text="",
                        contributors=[],
                        relationships=list(rendering.relationship_ids),
                        exclusions=[
                            {
                                "element_id": primary_id,
                                "reason": "already_claimed",
                                "relationship_ids": list(
                                    rendering.relationship_ids
                                ),
                            }
                        ],
                        omission_reason="consumed_by_relationship",
                        suppressed_by_element_id=primary_id,
                        label="form replacement closure",
                    )
                    form_consumed_primaries.add(contributor_id)
            elif type(raw_form) is dict and raw_form.get("canonical_mode") == "inert":
                try:
                    from app.services.form_semantics import (
                        PublicFormGroup,
                        _stable_id as stable_form_id,
                        render_form_group_semantics,
                    )

                    form_group = PublicFormGroup.model_validate(raw_form)
                    inert_anchor = reconstructed_by_primary[primary_id].model_copy(
                        deep=True
                    )
                    inert_legacy = inert_anchor.properties.get("legacy_item")
                    if type(inert_legacy) is not dict:
                        raise ValueError("form inert legacy item differs")
                    replacement_group = inert_legacy.get("form_group")
                    if type(replacement_group) is not dict:
                        raise ValueError("form inert group differs")
                    replacement_group["canonical_mode"] = "replace"
                    rendering = render_form_group_semantics(inert_anchor)
                    raw_form_relationships = extras.get("relationships")
                    if type(raw_form_relationships) is not list:
                        raise ValueError("form relationships differ")
                    rendered_relationship_id_set = set(
                        rendering.relationship_ids
                        if rendering is not None
                        else ()
                    )
                    expected_form_relationship_ids: list[str] = []
                    for raw_relationship in raw_form_relationships:
                        if (
                            type(raw_relationship) is not dict
                            or raw_relationship.get("id")
                            not in rendered_relationship_id_set
                        ):
                            continue
                        expected_relationship_id = stable_form_id(
                            "form-rel",
                            self.document.sha256,
                            form_group.page_index,
                            raw_relationship.get("type"),
                            raw_relationship.get("source_id"),
                            raw_relationship.get("target_id"),
                        )
                        if raw_relationship.get("id") != expected_relationship_id:
                            raise ValueError("form relationship ID differs")
                        expected_form_relationship_ids.append(
                            expected_relationship_id
                        )
                    if expected_form_relationship_ids != list(
                        rendering.relationship_ids
                        if rendering is not None
                        else ()
                    ):
                        raise ValueError("form relationship order differs")
                except Exception as exc:
                    raise ValueError(
                        "marked table canonical inert form custody differs"
                    ) from exc
                if (
                    rendering is None
                    or form_group.anchor_element_id != primary_id
                    or rendering.anchor_element_id != primary_id
                    or form_group.page_index != page_index_by_primary[primary_id]
                    or form_group.contributor_element_ids
                    != list(rendering.contributor_element_ids)
                    or [
                        public_items_by_primary[contributor_id].id
                        for contributor_id in rendering.contributor_element_ids
                        if contributor_id in public_items_by_primary
                    ]
                    != form_group.contributor_public_item_ids
                    or len(
                        set(rendering.contributor_element_ids)
                        & set(public_items_by_primary)
                    )
                    != len(rendering.contributor_element_ids)
                    or any(
                        page_index_by_primary[contributor_id]
                        != page_index_by_primary[primary_id]
                        for contributor_id in rendering.contributor_element_ids
                    )
                ):
                    raise ValueError(
                        "marked table canonical inert form custody differs"
                    )
                exact_primary_ids.add(primary_id)
            elif "form_group" in extras:
                raise ValueError(
                    "marked table canonical form custody differs"
                )

        def stable_layout_relationship_id(
            story: str,
            relationship_type: str,
            source_id: str,
            target_id: str,
        ) -> str:
            digest = hashlib.sha256(
                (
                    f"{story}\0{relationship_type}\0"
                    f"{source_id}\0{target_id}"
                ).encode("utf-8")
            ).hexdigest()
            return f"layout-rel-{digest[:20]}"

        def exact_layout_descriptor(
            raw: Any,
            *,
            story: str,
            relationship_type: str,
            source_id: str,
            target_id: str,
        ) -> dict[str, str]:
            expected = {
                "id": stable_layout_relationship_id(
                    story,
                    relationship_type,
                    source_id,
                    target_id,
                ),
                "type": relationship_type,
                "source_id": source_id,
                "target_id": target_id,
            }
            if type(raw) is not dict or raw != expected:
                raise ValueError(
                    "marked table canonical layout relationship differs"
                )
            return expected

        def exact_projection_counterpart(
            *,
            public_id: str,
            owner_primary_id: str,
            owner_public_id: str,
            descriptor: Mapping[str, str],
            item_type: str,
            owner_field: str,
            label: str,
            source_note: bool = False,
        ) -> str:
            counterpart_primary_id = public_primary_by_public_id.get(public_id)
            if counterpart_primary_id is None:
                raise ValueError(
                    f"marked table canonical {label} public owner differs"
                )
            counterpart = public_items_by_primary[counterpart_primary_id]
            counterpart_extras = counterpart.model_extra or {}
            if (
                counterpart.type.casefold() != item_type
                or page_index_by_primary[counterpart_primary_id]
                != page_index_by_primary[owner_primary_id]
                or counterpart_extras.get(owner_field) != owner_public_id
                or counterpart_extras.get("relationship_id")
                != descriptor["id"]
                or counterpart_extras.get("relationship_type")
                != descriptor["type"]
                or (
                    _layout_note_basis_is_closed(counterpart)
                    if source_note
                    else counterpart_extras.get("relationship_basis")
                    == "graph_and_geometry"
                )
                is not True
            ):
                raise ValueError(
                    f"marked table canonical {label} public owner differs"
                )
            return counterpart_primary_id

        def merged_exclusions(
            values: Sequence[Mapping[str, Any]],
        ) -> list[dict[str, Any]]:
            grouped: dict[tuple[str, str], set[str]] = {}
            for value in values:
                element_id = value.get("element_id")
                reason = value.get("reason")
                relationship_ids = value.get("relationship_ids")
                if (
                    type(element_id) is not str
                    or type(reason) is not str
                    or type(relationship_ids) is not list
                    or any(type(member) is not str for member in relationship_ids)
                ):
                    raise ValueError(
                        "marked table canonical layout exclusion differs"
                    )
                grouped.setdefault((element_id, reason), set()).update(
                    relationship_ids
                )
            return [
                {
                    "element_id": element_id,
                    "reason": reason,
                    "relationship_ids": sorted(relationship_ids),
                }
                for (element_id, reason), relationship_ids in sorted(
                    grouped.items()
                )
            ]

        def projected_visual_caption_source_id(
            caption: ContentItem,
            owner_public_id: str,
        ) -> str:
            if re.fullmatch(
                r"layout-caption-[0-9a-f]{20}", caption.id
            ) is None:
                return public_primary_by_public_id[caption.id]
            if caption.bbox is None:
                raise ValueError(
                    "marked table canonical visual-caption source differs"
                )
            normalized_text = re.sub(
                r"\s+",
                " ",
                str(caption.value or ""),
            ).strip().casefold()
            caption_box = _model_bbox_payload(caption.bbox)
            matched_ref: str | None = None
            for ordinal in range(_MAX_CONTEXT_FREE_RAW_REF_ORDINALS):
                raw_ref = f"#/texts/{ordinal}"
                digest = hashlib.sha256(
                    json.dumps(
                        (
                            "P03-US02",
                            "caption",
                            owner_public_id,
                            [raw_ref],
                            normalized_text,
                            caption_box,
                        ),
                        sort_keys=True,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        default=str,
                    ).encode("utf-8")
                ).hexdigest()
                if caption.id != f"layout-caption-{digest[:20]}":
                    continue
                if matched_ref is not None:
                    raise ValueError(
                        "marked table canonical visual-caption source repeats"
                    )
                matched_ref = raw_ref
            if matched_ref is None:
                raise ValueError(
                    "marked table canonical visual-caption source differs"
                )
            return _canonical_ir_id(
                "el",
                document_id,
                "raw_ref",
                matched_ref,
            )

        def projected_source_note_source_id(
            note: ContentItem,
            owner_public_id: str,
            candidate_sources: Mapping[str, str],
        ) -> str:
            """Recover one bounded raw-text identity from a P03 note proof."""

            note_extras = note.model_extra or {}
            if (
                note_extras.get("relationship_basis")
                != "graph_and_geometry"
                or re.fullmatch(r"layout-note-[0-9a-f]{20}", note.id)
                is None
                or type(note.value) is not str
                or not note.value.strip()
                or note.bbox is None
            ):
                raise ValueError(
                    "marked table canonical source-note source differs"
                )
            normalized_text = re.sub(
                r"\s+",
                " ",
                note.value,
            ).strip().casefold()
            note_box = _model_bbox_payload(note.bbox)
            matches: list[str] = []
            for element_id, raw_ref in candidate_sources.items():
                digest = hashlib.sha256(
                    json.dumps(
                        (
                            "P03-US03",
                            "source-note",
                            owner_public_id,
                            [raw_ref],
                            normalized_text,
                            note_box,
                        ),
                        sort_keys=True,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        default=str,
                    ).encode("utf-8")
                ).hexdigest()
                if note.id != f"layout-note-{digest[:20]}":
                    continue
                matches.append(element_id)
            if len(matches) != 1:
                raise ValueError(
                    "marked table canonical source-note source differs"
                )
            return matches[0]

        custody_endpoint_ids = {
            endpoint_id
            for record in custody.records
            for endpoint_id in (
                record.member_element_id,
                record.group_element_id,
                record.counterpart_element_id,
                record.source_element_id,
                record.target_element_id,
            )
        }
        layout_counterpart_owners: dict[str, str] = {}
        for owner_primary_id in expected_primary_ids:
            owner = public_items_by_primary[owner_primary_id]
            owner_extras = owner.model_extra or {}
            visual_projection = (
                owner_extras.get("layout_visual_relationships_projected")
                is True
            )
            note_projection = (
                owner_extras.get("layout_source_notes_projected") is True
            )
            caption_ids = owner_extras.get("caption_ids")
            table_caption_projection = (
                (
                    owner.type.casefold() == "table"
                    or is_eligible_unresolved_table_candidate(
                        {
                            "type": owner.type,
                            "value": owner.value,
                            "rows": owner_extras.get("rows"),
                            "row_count": owner_extras.get("row_count"),
                            "column_count": owner_extras.get(
                                "column_count"
                            ),
                            "table_candidate_gate": owner_extras.get(
                                "table_candidate_gate"
                            ),
                            "table_candidate_gate_reasons": owner_extras.get(
                                "table_candidate_gate_reasons"
                            ),
                            "table_candidate_gate_sources": owner_extras.get(
                                "table_candidate_gate_sources"
                            ),
                        }
                    )
                )
                and type(caption_ids) is list
                and bool(caption_ids)
                and not visual_projection
            )
            if not (
                visual_projection
                or note_projection
                or table_caption_projection
            ):
                continue
            if visual_projection and owner.type.casefold() not in {
                "image",
                "chart",
                "diagram",
            }:
                raise ValueError(
                    "marked table canonical visual projection differs"
                )
            raw_relationships = owner_extras.get("relationships")
            if type(raw_relationships) is not list:
                raise ValueError(
                    "marked table canonical layout relationships differ"
                )
            raw_layout_relationships = [
                value
                for value in raw_relationships
                if type(value) is dict
                and type(value.get("id")) is str
                and value["id"].startswith("layout-rel-")
            ]
            if len(raw_layout_relationships) != len(raw_relationships):
                raise ValueError(
                    "marked table canonical layout relationships differ"
                )

            raw_caption_ids = owner_extras.get("caption_ids", [])
            raw_caption_of = owner_extras.get("caption_of", [])
            raw_contains_ids = owner_extras.get("contains_ids", [])
            raw_source_note_ids = owner_extras.get("source_note_ids", [])
            raw_footnote_ids = owner_extras.get("footnote_ids", [])
            for values in (
                raw_caption_ids,
                raw_caption_of,
                raw_contains_ids,
                raw_source_note_ids,
                raw_footnote_ids,
            ):
                if type(values) is not list or any(
                    type(value) is not str or not value for value in values
                ) or len(values) != len(set(values)):
                    raise ValueError(
                        "marked table canonical layout ownership differs"
                    )
            if raw_caption_of != raw_caption_ids:
                raise ValueError(
                    "marked table canonical caption ownership differs"
                )
            has_visual_relationships = bool(raw_contains_ids) or bool(
                raw_caption_ids
            )
            if (
                has_visual_relationships != visual_projection
                and not table_caption_projection
            ):
                raise ValueError(
                    "marked table canonical visual projection differs"
                )
            if (bool(raw_source_note_ids) or bool(raw_footnote_ids)) != note_projection:
                raise ValueError(
                    "marked table canonical source-note projection differs"
                )

            expected_layout_descriptors: list[dict[str, str]] = []
            linked_captions: list[tuple[str, ContentItem, dict[str, str]]] = []
            for public_caption_id in raw_caption_ids:
                story = "P03-US02" if visual_projection else "P03-US01"
                descriptor = exact_layout_descriptor(
                    raw_layout_relationships[
                        len(expected_layout_descriptors)
                    ],
                    story=story,
                    relationship_type="caption_of",
                    source_id=public_caption_id,
                    target_id=owner.id,
                )
                expected_layout_descriptors.append(descriptor)
                caption_primary_id = exact_projection_counterpart(
                    public_id=public_caption_id,
                    owner_primary_id=owner_primary_id,
                    owner_public_id=owner.id,
                    descriptor=descriptor,
                    item_type="caption",
                    owner_field="caption_of",
                    label="caption",
                )
                if (
                    caption_primary_id in layout_counterpart_owners
                    and layout_counterpart_owners[caption_primary_id]
                    != owner_primary_id
                ):
                    raise ValueError(
                        "marked table canonical layout ownership repeats"
                    )
                layout_counterpart_owners[caption_primary_id] = owner_primary_id
                linked_captions.append(
                    (
                        caption_primary_id,
                        public_items_by_primary[caption_primary_id],
                        descriptor,
                    )
                )

            for contained_id in raw_contains_ids:
                descriptor = exact_layout_descriptor(
                    raw_layout_relationships[
                        len(expected_layout_descriptors)
                    ],
                    story="P03-US02",
                    relationship_type="contains",
                    source_id=owner.id,
                    target_id=contained_id,
                )
                expected_layout_descriptors.append(descriptor)

            contained_items = owner_extras.get("contained_items", [])
            if raw_contains_ids:
                if type(contained_items) is not list or [
                    value.get("id") if type(value) is dict else None
                    for value in contained_items
                ] != raw_contains_ids:
                    raise ValueError(
                        "marked table canonical contained-item custody differs"
                    )
                for raw_contained, descriptor in zip(
                    contained_items,
                    expected_layout_descriptors[len(raw_caption_ids) :],
                    strict=True,
                ):
                    if (
                        raw_contained.get("type") != "visual_text"
                        or raw_contained.get("content_type") != "visual_text"
                        or type(raw_contained.get("page_index")) is not int
                        or raw_contained.get("page_index")
                        != page_index_by_primary[owner_primary_id]
                        or raw_contained.get("md")
                        != raw_contained.get("value")
                        or raw_contained.get("source")
                        not in {"native", "ocr"}
                        or raw_contained.get("presentation_role") != "subordinate"
                        or raw_contained.get("contained_by") != owner.id
                        or raw_contained.get("relationship_id")
                        != descriptor["id"]
                        or raw_contained.get("relationship_type") != "contains"
                        or raw_contained.get("relationship_basis")
                        != "graph_and_geometry"
                    ):
                        raise ValueError(
                            "marked table canonical contained-item custody differs"
                        )
            elif "contained_items" in owner_extras:
                raise ValueError(
                    "marked table canonical contained-item custody differs"
                )

            linked_notes: list[tuple[str, ContentItem, dict[str, str]]] = []
            for relationship_type, public_note_ids, owner_field, item_type in (
                (
                    "source_note_of",
                    raw_source_note_ids,
                    "source_note_of",
                    "source_note",
                ),
                (
                    "footnote_of",
                    raw_footnote_ids,
                    "footnote_of",
                    "footnote",
                ),
            ):
                for public_note_id in public_note_ids:
                    descriptor = exact_layout_descriptor(
                        raw_layout_relationships[
                            len(expected_layout_descriptors)
                        ],
                        story="P03-US03",
                        relationship_type=relationship_type,
                        source_id=public_note_id,
                        target_id=owner.id,
                    )
                    expected_layout_descriptors.append(descriptor)
                    note_primary_id = exact_projection_counterpart(
                        public_id=public_note_id,
                        owner_primary_id=owner_primary_id,
                        owner_public_id=owner.id,
                        descriptor=descriptor,
                        item_type=item_type,
                        owner_field=owner_field,
                        label="source-note",
                        source_note=True,
                    )
                    if (
                        note_primary_id in layout_counterpart_owners
                        and layout_counterpart_owners[note_primary_id]
                        != owner_primary_id
                    ):
                        raise ValueError(
                            "marked table canonical layout ownership repeats"
                        )
                    layout_counterpart_owners[note_primary_id] = owner_primary_id
                    linked_notes.append(
                        (
                            note_primary_id,
                            public_items_by_primary[note_primary_id],
                            descriptor,
                        )
                    )
            if expected_layout_descriptors != raw_layout_relationships:
                raise ValueError(
                    "marked table canonical layout relationship order differs"
                )
            if owner_primary_id in trusted_non_target_primary_ids:
                continue

            trusted_nonvalid_table_target = (
                owner_primary_id in trusted_target_blocks_by_primary
                and trusted_custody_relationship_ids is not None
            )
            predecessor_block = predecessor_blocks_by_primary[owner_primary_id]
            expected_base_block = (
                trusted_target_blocks_by_primary[owner_primary_id]
                if trusted_nonvalid_table_target
                else predecessor_block
            )
            base_exclusions = [
                value.model_dump(mode="json")
                for value in expected_base_block.excluded_contributions
            ]
            expected_relationship_ids = list(
                expected_base_block.relationship_ids
            )
            expected_exclusions = list(base_exclusions)
            expected_contributors = list(
                expected_base_block.contributing_element_ids
            )
            expected_markdown = expected_base_block.markdown
            expected_text = expected_base_block.text
            if trusted_nonvalid_table_target:
                # The terminal producer freezes the exact sidecar before
                # issuing this private context.  Those pinned IDs have only
                # negative authority: remove them from the already-validated
                # P03 target graph, while every other P03 relationship and
                # exclusion remains required byte-for-byte.
                diagnostic_ids = set(trusted_custody_relationship_ids)
                expected_relationship_ids = [
                    relationship_id
                    for relationship_id in expected_relationship_ids
                    if relationship_id not in diagnostic_ids
                ]
                retained_exclusions: list[dict[str, Any]] = []
                for exclusion in expected_exclusions:
                    relationship_ids = [
                        relationship_id
                        for relationship_id in exclusion["relationship_ids"]
                        if relationship_id not in diagnostic_ids
                    ]
                    if relationship_ids:
                        retained_exclusions.append(
                            {
                                **exclusion,
                                "relationship_ids": relationship_ids,
                            }
                        )
                expected_exclusions = retained_exclusions

            if visual_projection:
                reconstructed_owner_id = reconstructed_by_primary[
                    owner_primary_id
                ].id
                if reconstructed_owner_id != owner_primary_id:
                    raise ValueError(
                        "marked table canonical visual IR identity differs"
                    )
                expected_exclusions = []
                incident_relationships = [
                    relationship
                    for relationship in public_ir.relationships
                    if relationship.type.value != "reading_before"
                    and reconstructed_owner_id
                    in {relationship.source_id, relationship.target_id}
                ]
                incident_ids = {value.id for value in incident_relationships}
                for _caption_primary, caption_item, _descriptor in linked_captions:
                    raw_caption_id = projected_visual_caption_source_id(
                        caption_item,
                        owner.id,
                    )
                    relationship_id = _canonical_ir_id(
                        "rel",
                        "contains",
                        owner_primary_id,
                        raw_caption_id,
                        "parent",
                    )
                    if relationship_id in incident_ids:
                        continue
                    incident_ids.add(relationship_id)
                    expected_exclusions.append(
                        {
                            "element_id": raw_caption_id,
                            "reason": "evidence_only_relationship",
                            "relationship_ids": [relationship_id],
                        }
                    )
                for contained_id in raw_contains_ids:
                    synthesized_relationship_id = _canonical_ir_id(
                        "rel",
                        "contains",
                        owner_primary_id,
                        contained_id,
                        "parent",
                    )
                    target_relationships = public_relationships_by_endpoint.get(
                        contained_id,
                        [],
                    )
                    if contained_id in ir_elements_by_id:
                        owner_target_contains = [
                            relationship
                            for relationship in target_relationships
                            if relationship.type.value == "contains"
                            and relationship.source_id == owner_primary_id
                            and relationship.target_id == contained_id
                        ]
                        pair_contains = [
                            relationship
                            for relationship in target_relationships
                            if relationship.type.value == "contains"
                            and {
                                relationship.source_id,
                                relationship.target_id,
                            }
                            == {owner_primary_id, contained_id}
                        ]
                        if (
                            len(owner_target_contains) != 1
                            or pair_contains != owner_target_contains
                        ):
                            raise ValueError(
                                "marked table canonical visual containment differs"
                            )
                        relationship_id = owner_target_contains[0].id
                    else:
                        if (
                            target_relationships
                            or contained_id in marked_table_endpoint_ids
                            or contained_id in custody_endpoint_ids
                        ):
                            raise ValueError(
                                "marked table canonical visual containment custody differs"
                            )
                        relationship_id = synthesized_relationship_id
                    if relationship_id in incident_ids:
                        continue
                    incident_ids.add(relationship_id)
                    expected_exclusions.append(
                        {
                            "element_id": contained_id,
                            "reason": "evidence_only_relationship",
                            "relationship_ids": [relationship_id],
                        }
                    )
                for relationship in incident_relationships:
                    related_id = (
                        relationship.target_id
                        if relationship.source_id == reconstructed_owner_id
                        else relationship.source_id
                    )
                    expected_exclusions.append(
                        {
                            "element_id": related_id,
                            "reason": "evidence_only_relationship",
                            "relationship_ids": [relationship.id],
                        }
                    )
                expected_relationship_ids = sorted(
                    incident_ids
                    | {value["id"] for value in expected_layout_descriptors}
                )
                expected_exclusions = merged_exclusions(expected_exclusions)
                expected_contributors = [owner_primary_id]
                content_type = owner_extras.get("content_type")
                include_primary_ocr = owner_extras.get(
                    "include_ocr_in_primary"
                )
                if (
                    type(content_type) is not str
                    or content_type.casefold() != owner.type.casefold()
                    or type(include_primary_ocr) is not bool
                    or any(
                        key in owner_extras
                        for key in (
                            "caption",
                            "caption_source",
                            "caption_generated",
                            "caption_confidence",
                        )
                    )
                ):
                    raise ValueError(
                        "marked table canonical visual primary differs"
                    )
                from app.services.layout import (
                    _grounded_proven_visual_owner_output,
                    _grounded_primary_ocr,
                    _independent_visual_native_child_outputs,
                )

                raw_owner = owner.model_dump(
                    mode="json",
                    exclude_unset=True,
                )
                owner_page_index = page_index_by_primary[owner_primary_id]
                primary_text, expected_visual_source, _proof_reason = (
                    _grounded_proven_visual_owner_output(
                        raw_owner,
                        source_document_identity=self.document.sha256,
                        page_index=owner_page_index,
                    )
                )
                fallback_children: list[str] = []
                if not primary_text:
                    fallback = _independent_visual_native_child_outputs(
                        raw_owner,
                        source_document_identity=self.document.sha256,
                        page_index=owner_page_index,
                    )
                    filtered_owner = fallback.get("owner_output")
                    filtered_source = fallback.get("owner_source")
                    raw_children = fallback.get("children")
                    if isinstance(filtered_owner, str) and filtered_owner:
                        primary_text = filtered_owner
                        expected_visual_source = (
                            filtered_source
                            if filtered_source in {"native", "ocr"}
                            else None
                        )
                    if isinstance(raw_children, list):
                        fallback_children = [
                            child["value"]
                            for child in raw_children
                            if isinstance(child, dict)
                            and isinstance(child.get("value"), str)
                            and child["value"]
                        ]
                    if not primary_text:
                        primary_text, _reason, _count, _backed = (
                            _grounded_primary_ocr(raw_owner)
                        )
                        expected_visual_source = (
                            "ocr" if primary_text else None
                        )
                canonical_parts = [
                    *([primary_text] if primary_text else []),
                    *fallback_children,
                ]
                expected_visual_markdown = "\n\n".join(canonical_parts).strip()
                if not expected_visual_markdown:
                    expected_visual_markdown = (
                        f"[{content_type.capitalize()} detected; "
                        "no reliable text extracted.]"
                    )
                if primary_text:
                    expected_public_source = expected_visual_source or "derived"
                    if (
                        type(owner.value) is not str
                        or owner.value != primary_text
                        or owner.md != primary_text
                        or owner.source != expected_public_source
                    ):
                        raise ValueError(
                            "marked table canonical visual primary differs"
                        )
                elif fallback_children:
                    if (
                        type(owner.value) is not str
                        or type(owner.md) is not str
                        or owner.source not in {"native", "ocr", "derived"}
                    ):
                        raise ValueError(
                            "marked table canonical visual fallback differs"
                        )
                else:
                    expected_public_markdown = (
                        f"[{content_type.capitalize()} detected; "
                        "no reliable text extracted.]"
                    )
                    if (
                        owner.value != ""
                        or owner.md != expected_public_markdown
                        or owner.source != "derived"
                    ):
                        raise ValueError(
                            "marked table canonical visual primary differs"
                        )
                expected_markdown = expected_visual_markdown
                expected_text = expected_visual_markdown
            else:
                expected_relationship_id_set = set(expected_relationship_ids)
                expected_relationship_id_set.update(
                    descriptor["id"]
                    for _primary, _item, descriptor in linked_notes
                )
                bounded_text_identities = bounded_raw_ref_identities("texts")
                owner_candidate_note_sources = {
                    exclusion.element_id: raw_refs[0]
                    for exclusion in blocks_by_primary[
                        owner_primary_id
                    ].excluded_contributions
                    if exclusion.reason == "evidence_only_relationship"
                    and len(
                        raw_refs := bounded_text_identities.get(
                            exclusion.element_id,
                            (),
                        )
                    )
                    == 1
                }
                hidden_source_ids: set[str] = set()
                for _note_primary_id, note_item, _descriptor in linked_notes:
                    if (note_item.model_extra or {}).get(
                        "relationship_basis"
                    ) != "graph_and_geometry":
                        continue
                    hidden_source_id = projected_source_note_source_id(
                        note_item,
                        owner.id,
                        owner_candidate_note_sources,
                    )
                    containment_relationship_id = _canonical_ir_id(
                        "rel",
                        "contains",
                        owner_primary_id,
                        hidden_source_id,
                        "parent",
                    )
                    exact_exclusion_use = (
                        owner_primary_id,
                        hidden_source_id,
                        "evidence_only_relationship",
                    )
                    if (
                        hidden_source_id in hidden_source_ids
                        or hidden_source_id in known_element_ids
                        or hidden_source_id in canonical_contributor_ids
                        or hidden_source_id in custody_endpoint_ids
                        or containment_relationship_id
                        in public_relationship_ids
                        or containment_relationship_id
                        in all_custody_relationship_ids
                        or canonical_relationship_block_uses.get(
                            containment_relationship_id
                        )
                        != [owner_primary_id]
                        or canonical_relationship_exclusion_uses.get(
                            containment_relationship_id
                        )
                        != [exact_exclusion_use]
                        or canonical_excluded_endpoint_uses.get(
                            hidden_source_id
                        )
                        != [
                            (
                                owner_primary_id,
                                containment_relationship_id,
                                "evidence_only_relationship",
                            )
                        ]
                    ):
                        raise ValueError(
                            "marked table canonical source-note containment "
                            "differs"
                        )
                    hidden_source_ids.add(hidden_source_id)
                    expected_relationship_id_set.add(
                        containment_relationship_id
                    )
                    expected_exclusions.append(
                        {
                            "element_id": hidden_source_id,
                            "reason": "evidence_only_relationship",
                            "relationship_ids": [
                                containment_relationship_id
                            ],
                        }
                    )
                expected_relationship_ids = sorted(
                    expected_relationship_id_set
                )
                expected_exclusions = merged_exclusions(
                    expected_exclusions
                )

            if table_caption_projection:
                caption_markdown: list[str] = []
                caption_text: list[str] = []
                caption_primary_ids: list[str] = []
                for caption_primary_id, caption_item, _descriptor in linked_captions:
                    if (
                        caption_primary_id != caption_item.id
                        or re.fullmatch(
                            r"el-[0-9a-f]{20}", caption_primary_id
                        )
                        is None
                        or caption_item.bbox is None
                        or owner.bbox is None
                    ):
                        raise ValueError(
                            "marked table canonical table-caption custody differs"
                        )
                    caption_box = _model_bbox_payload(caption_item.bbox)
                    owner_box = _model_bbox_payload(owner.bbox)
                    from app.services.layout import _external_caption_geometry

                    if _external_caption_geometry(
                        caption_box,
                        owner_box,
                    ) != (True, "graph_and_geometry"):
                        raise ValueError(
                            "marked table canonical table-caption geometry differs"
                        )
                    caption_relationship_id = _canonical_ir_id(
                        "rel",
                        "caption_of",
                        caption_primary_id,
                        owner_primary_id,
                        "children",
                    )
                    containment_relationship_id = _canonical_ir_id(
                        "rel",
                        "contains",
                        owner_primary_id,
                        caption_primary_id,
                        "parent",
                    )
                    assert_manual_contract(
                        caption_primary_id,
                        markdown="",
                        text="",
                        contributors=[],
                        relationships=[caption_relationship_id],
                        exclusions=[
                            {
                                "element_id": owner_primary_id,
                                "reason": "already_claimed",
                                "relationship_ids": [
                                    caption_relationship_id
                                ],
                            }
                        ],
                        omission_reason="consumed_by_relationship",
                        suppressed_by_element_id=owner_primary_id,
                        label="table-caption closure",
                    )
                    if trusted_nonvalid_table_target:
                        continue
                    caption_output = _canonical_public_item_output(caption_item)
                    if caption_output[0]:
                        caption_markdown.append(caption_output[0])
                    if caption_output[1]:
                        caption_text.append(caption_output[1])
                    caption_primary_ids.append(caption_primary_id)
                    expected_relationship_ids.extend(
                        [caption_relationship_id, containment_relationship_id]
                    )
                    expected_exclusions.append(
                        {
                            "element_id": caption_primary_id,
                            "reason": "evidence_only_relationship",
                            "relationship_ids": [
                                containment_relationship_id
                            ],
                        }
                    )
                if not trusted_nonvalid_table_target:
                    expected_contributors = [
                        owner_primary_id,
                        *caption_primary_ids,
                        *(
                            value
                            for value in predecessor_block.contributing_element_ids
                            if value != owner_primary_id
                        ),
                    ]
                    expected_relationship_ids = sorted(
                        set(expected_relationship_ids)
                    )
                    expected_exclusions = merged_exclusions(
                        expected_exclusions
                    )
                    expected_markdown = "\n\n".join(
                        [*caption_markdown, predecessor_block.markdown]
                    ).strip()
                    expected_text = "\n\n".join(
                        [*caption_text, predecessor_block.text]
                    ).strip()

            assert_manual_contract(
                owner_primary_id,
                markdown=expected_markdown,
                text=expected_text,
                contributors=expected_contributors,
                relationships=expected_relationship_ids,
                exclusions=expected_exclusions,
                omission_reason=(
                    None
                    if visual_projection
                    else expected_base_block.omission_reason
                ),
                suppressed_by_element_id=(
                    None
                    if visual_projection
                    else expected_base_block.suppressed_by_element_id
                ),
                label="layout overlay",
                context_free_visual_owner=(
                    owner if visual_projection else None
                ),
            )
            for counterpart_primary_id, counterpart_item, descriptor in (
                *(
                    linked_captions
                    if visual_projection
                    else []
                ),
                *linked_notes,
            ):
                counterpart_markdown, counterpart_text = (
                    _canonical_public_item_output(counterpart_item)
                )
                assert_manual_contract(
                    counterpart_primary_id,
                    markdown=counterpart_markdown,
                    text=counterpart_text,
                    contributors=[counterpart_primary_id],
                    relationships=[descriptor["id"]],
                    exclusions=[],
                    label="layout counterpart",
                )

        for primary_id, item in public_items_by_primary.items():
            if (
                primary_id in trusted_non_target_primary_ids
                or item.running_region is None
            ):
                continue
            running_markdown, running_text = _canonical_public_item_output(item)
            assert_manual_contract(
                primary_id,
                markdown=running_markdown,
                text=running_text,
                contributors=[primary_id],
                relationships=[],
                exclusions=[],
                label="running-region overlay",
            )

        if exact_primary_ids != set(expected_primary_ids):
            raise ValueError("marked table canonical exact overlay differs")

        for block in blocks_by_primary.values():
            if any(
                element_id not in known_element_ids
                for element_id in block.contributing_element_ids
            ):
                raise ValueError("marked table canonical contribution binding differs")
            for exclusion in block.excluded_contributions:
                if (
                    exclusion.element_id not in known_element_ids
                    and exclusion.reason != "evidence_only_relationship"
                ):
                    raise ValueError("marked table canonical exclusion binding differs")
        for _public_page, item in marked_items:
            primary_id = next(
                primary
                for primary, public_item in public_items_by_primary.items()
                if public_item is item
            )
            block = blocks_by_primary[primary_id]
            if (
                block.scope != "body"
                or block.omission_reason is not None
            ):
                raise ValueError("marked table canonical content custody differs")
        if context_free_validation is not None:
            if (
                deferred_context_free_owners
                or deferred_context_free_inert_remnants
                or validated_context_free_primary_ids
                != set(context_free_records_by_primary)
                or validated_context_free_inert_primary_ids
                != set(context_free_inert_records_by_primary)
            ):
                raise ValueError(
                    "marked table context-free validation coverage differs"
                )
            return None
        if (
            deferred_context_free_owners
            or deferred_context_free_inert_remnants
        ):
            ordered_deferred_owners = tuple(
                sorted(deferred_context_free_owners)
            )
            ordered_inert_remnants = tuple(
                sorted(deferred_context_free_inert_remnants)
            )
            public_ir_projection = _context_free_ir_identity_projection(
                public_ir,
                {
                    record[3]: (record[7], record[6])
                    for record in ordered_deferred_owners
                },
            )
            return _TableContextFreeValidationContext(
                _TABLE_CONTEXT_FREE_VALIDATION_TOKEN,
                self,
                self.document.sha256,
                ordered_deferred_owners,
                ordered_inert_remnants,
                public_ir_projection,
                tuple(
                    (
                        primary_id,
                        *predecessor_block_identity(
                            predecessor_blocks_by_primary[primary_id]
                        ),
                    )
                    for primary_id in expected_primary_ids
                ),
                table_ir_bboxes,
                table_ir_elements,
                table_ir_evidence,
                table_ir_relationships,
            )
        return None


class ApiError(ApiModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(ApiModel):
    error: ApiError
