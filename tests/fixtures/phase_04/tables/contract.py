"""Closed readiness contracts for P04-US01 table evidence.

This package is test-only.  It distinguishes exact source truth from bounded,
source-reviewed denominators and makes every unsupported dimension fail closed
instead of filling missing cells, spans, bboxes, or provenance with guesses.
"""

from __future__ import annotations

import math
import re
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


POLICY_ID = "p04-table-evidence-v1"
SIDECAR_VERSION = "1.1"

TABLE_LIMITS = MappingProxyType(
    {
        "maximum_rows_per_table": 4_096,
        "maximum_columns_per_table": 256,
        "maximum_cells_per_table": 65_536,
        "maximum_cell_text_utf8_bytes": 16 * 1_024,
        "maximum_concerns_per_table": 64,
        "maximum_oracle_tables": 64,
        "maximum_evidence_ids_per_record": 64,
        "maximum_source_object_ids_per_record": 64,
        "maximum_identity_utf8_bytes": 256,
        "maximum_reference_utf8_bytes": 256,
        "maximum_portable_path_utf8_bytes": 256,
        "maximum_table_sidecar_bytes": 8 * 1_024 * 1_024,
        "maximum_phase04_sidecars_per_document_bytes": 64 * 1_024 * 1_024,
        "maximum_span_fidelity_page_seconds": 0.500,
        "maximum_span_fidelity_document_seconds": 5.000,
        "maximum_table_stage_p95_overhead_ratio": 0.10,
        "maximum_peak_rss_delta_bytes": 64 * 1_024 * 1_024,
    }
)

Dimension = Literal[
    "table_count",
    "row_count_including_header",
    "visual_row_count",
    "data_row_count",
    "column_count",
    "cell_count",
    "repeated_value_count",
    "false_span_count",
    "supported_col_span",
    "supported_row_span",
    "stub_only_section_row_count",
    "logical_wrapped_row_count",
    "cell_bbox_count",
    "cell_provenance_count",
    "header_ownership",
    "row_boundary",
    "rotation_mapping",
    "form_grid_topology",
]

CONCERN_CODES = (
    "table_source_cell_grid_unresolved",
    "table_source_span_evidence_unresolved",
    "table_source_cell_bbox_unresolved",
    "table_source_provenance_unresolved",
    "table_source_header_ownership_unresolved",
    "table_source_row_boundary_unresolved",
    "table_source_rotation_mapping_unresolved",
    "table_source_form_grid_topology_unresolved",
    "table_ambiguous_border_evidence",
    "table_malformed_source_evidence",
    "table_resource_limit_exceeded",
)
ConcernCode = Literal[
    "table_source_cell_grid_unresolved",
    "table_source_span_evidence_unresolved",
    "table_source_cell_bbox_unresolved",
    "table_source_provenance_unresolved",
    "table_source_header_ownership_unresolved",
    "table_source_row_boundary_unresolved",
    "table_source_rotation_mapping_unresolved",
    "table_source_form_grid_topology_unresolved",
    "table_ambiguous_border_evidence",
    "table_malformed_source_evidence",
    "table_resource_limit_exceeded",
]

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_FIXTURE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_PORTABLE_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _bounded_safe_string(
    value: str,
    *,
    field_name: str,
    maximum_utf8_bytes: int,
    allow_line_breaks: bool = False,
    allow_empty: bool = False,
    require_trimmed: bool = True,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if not value and not allow_empty:
        raise ValueError(f"{field_name} must be non-empty")
    if require_trimmed and value.strip() != value:
        raise ValueError(f"{field_name} must be non-empty with no outer whitespace")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{field_name} is not valid UTF-8 text") from error
    if len(encoded) > maximum_utf8_bytes:
        raise ValueError(f"{field_name} exceeds the UTF-8 byte limit")
    allowed_controls = {"\n", "\r", "\t"} if allow_line_breaks else set()
    if any((ord(character) < 32 or ord(character) == 127) and character not in allowed_controls for character in value):
        raise ValueError(f"{field_name} contains an unsafe control character")
    return value


def _bounded_identifier(value: str, *, field_name: str, fixture: bool = False) -> str:
    value = _bounded_safe_string(
        value,
        field_name=field_name,
        maximum_utf8_bytes=TABLE_LIMITS["maximum_identity_utf8_bytes"],
    )
    pattern = _FIXTURE_ID if fixture else _ID
    if not pattern.fullmatch(value):
        raise ValueError(f"{field_name} must be a stable lowercase identifier")
    return value


def validate_fixture_identifier(value: str) -> str:
    return _bounded_identifier(value, field_name="fixture_id", fixture=True)


def _bounded_reference(value: str, *, field_name: str) -> str:
    return _bounded_safe_string(
        value,
        field_name=field_name,
        maximum_utf8_bytes=TABLE_LIMITS["maximum_reference_utf8_bytes"],
    )


def validate_portable_workspace_path(value: str) -> str:
    """Validate one canonical, relative, slash-separated evidence path."""

    value = _bounded_safe_string(
        value,
        field_name="evidence path",
        maximum_utf8_bytes=TABLE_LIMITS["maximum_portable_path_utf8_bytes"],
    )
    if "\\" in value or ".." in value:
        raise ValueError("evidence paths cannot contain backslashes or traversal")
    parts = value.split("/")
    if value.startswith("/") or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("evidence paths must be canonical portable workspace paths")
    if any(not _PORTABLE_PATH_SEGMENT.fullmatch(part) for part in parts):
        raise ValueError("evidence path contains a non-portable segment")
    if PurePosixPath(value).as_posix() != value:
        raise ValueError("evidence paths must be canonical portable workspace paths")
    return value


def resolve_workspace_path(workspace: Path, portable_path: str) -> Path:
    """Resolve a validated path while rejecting symlink escape from workspace."""

    relative = validate_portable_workspace_path(portable_path)
    root = workspace.resolve(strict=True)
    candidate = (root / relative).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("evidence path resolves outside the workspace") from error
    return candidate


_EXPECTED_LIMIT_BY_DIMENSION: dict[str, int] = {
    "table_count": TABLE_LIMITS["maximum_oracle_tables"],
    "row_count_including_header": TABLE_LIMITS["maximum_rows_per_table"],
    "visual_row_count": TABLE_LIMITS["maximum_rows_per_table"],
    "data_row_count": TABLE_LIMITS["maximum_rows_per_table"],
    "column_count": TABLE_LIMITS["maximum_columns_per_table"],
    "cell_count": TABLE_LIMITS["maximum_cells_per_table"],
    "repeated_value_count": TABLE_LIMITS["maximum_cells_per_table"],
    "false_span_count": TABLE_LIMITS["maximum_cells_per_table"],
    "supported_col_span": TABLE_LIMITS["maximum_cells_per_table"],
    "supported_row_span": TABLE_LIMITS["maximum_cells_per_table"],
    "stub_only_section_row_count": TABLE_LIMITS["maximum_rows_per_table"],
    "logical_wrapped_row_count": TABLE_LIMITS["maximum_rows_per_table"],
    "cell_bbox_count": TABLE_LIMITS["maximum_cells_per_table"],
    "cell_provenance_count": TABLE_LIMITS["maximum_cells_per_table"],
    "header_ownership": TABLE_LIMITS["maximum_cells_per_table"],
    "row_boundary": TABLE_LIMITS["maximum_rows_per_table"],
    "rotation_mapping": TABLE_LIMITS["maximum_cells_per_table"],
    "form_grid_topology": TABLE_LIMITS["maximum_cells_per_table"],
}
_EXPECTED_UNIT_BY_DIMENSION = {
    "table_count": "tables",
    "row_count_including_header": "rows",
    "visual_row_count": "rows",
    "data_row_count": "rows",
    "column_count": "columns",
    "cell_count": "cells",
    "repeated_value_count": "values",
    "false_span_count": "spans",
    "supported_col_span": "spans",
    "supported_row_span": "spans",
    "stub_only_section_row_count": "rows",
    "logical_wrapped_row_count": "rows",
    "cell_bbox_count": "cells",
    "cell_provenance_count": "cells",
    "header_ownership": "cells",
    "row_boundary": "rows",
    "rotation_mapping": "cells",
    "form_grid_topology": "cells",
}


class ClosedFixtureModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class FiniteBBox(ClosedFixtureModel):
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    unit: Literal["pt"] = "pt"
    tolerance_pt: float = Field(default=0.0, ge=0, le=5)

    @field_validator("x", "y", "width", "height", "tolerance_pt", mode="before")
    @classmethod
    def finite_numbers_only(cls, value: Any) -> Any:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise ValueError("table bbox values must be finite real numbers")
        return value


class SourceIdentity(ClosedFixtureModel):
    case_id: str
    path: str
    size_bytes: int = Field(gt=0)
    sha256: str
    page_count: int = Field(gt=0)
    page_width_pt: float = Field(gt=0)
    page_height_pt: float = Field(gt=0)
    custody: Literal["public-redistributable"]
    review_path: str
    custody_limitation: str

    @field_validator("case_id")
    @classmethod
    def valid_case_id(cls, value: str) -> str:
        return _bounded_identifier(value, field_name="case_id")

    @field_validator("sha256")
    @classmethod
    def valid_sha256(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("source identity requires lowercase SHA-256")
        return value

    @field_validator("path", "review_path")
    @classmethod
    def portable_workspace_path(cls, value: str) -> str:
        return validate_portable_workspace_path(value)

    @field_validator("custody_limitation")
    @classmethod
    def safe_custody_limitation(cls, value: str) -> str:
        return _bounded_safe_string(
            value,
            field_name="custody limitation",
            maximum_utf8_bytes=512,
        )

    @field_validator("page_width_pt", "page_height_pt", mode="before")
    @classmethod
    def finite_page_size(cls, value: Any) -> Any:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise ValueError("page dimensions must be finite")
        return value


class FailClosedConcern(ClosedFixtureModel):
    code: ConcernCode
    dimension: Dimension
    reason: str = Field(min_length=1, max_length=512)

    @field_validator("reason")
    @classmethod
    def safe_reason(cls, value: str) -> str:
        return _bounded_safe_string(
            value, field_name="concern reason", maximum_utf8_bytes=512
        )


class ReviewedDenominator(ClosedFixtureModel):
    denominator_id: str
    dimension: Dimension
    expected: int = Field(ge=0)
    unit: Literal["tables", "rows", "columns", "cells", "values", "spans"]
    members: tuple[int, ...] = Field(
        default=(), max_length=TABLE_LIMITS["maximum_cells_per_table"]
    )
    evidence_basis: Literal[
        "p00_source_truth",
        "reviewed_native_text",
        "reviewed_vector_geometry",
        "reviewed_visual_render",
        "reviewed_source_comparison",
    ]
    qualification: str = Field(min_length=1, max_length=512)

    @field_validator("denominator_id")
    @classmethod
    def valid_denominator_id(cls, value: str) -> str:
        return _bounded_identifier(value, field_name="denominator_id")

    @field_validator("qualification")
    @classmethod
    def safe_qualification(cls, value: str) -> str:
        return _bounded_safe_string(
            value, field_name="denominator qualification", maximum_utf8_bytes=512
        )

    @model_validator(mode="after")
    def validate_members(self) -> Self:
        maximum_expected = _EXPECTED_LIMIT_BY_DIMENSION[self.dimension]
        if self.expected > maximum_expected:
            raise ValueError("denominator expected value exceeds its readiness limit")
        if self.unit != _EXPECTED_UNIT_BY_DIMENSION[self.dimension]:
            raise ValueError("denominator unit differs from its dimension")
        if self.dimension in {"supported_col_span", "supported_row_span"}:
            if self.unit != "spans" or len(self.members) != self.expected:
                raise ValueError("span denominators require one width per expected span")
            member_limit = TABLE_LIMITS[
                "maximum_columns_per_table"
                if self.dimension == "supported_col_span"
                else "maximum_rows_per_table"
            ]
            if any(value < 2 or value > member_limit for value in self.members):
                raise ValueError("span denominator member is outside readiness limits")
        elif self.members:
            raise ValueError("non-span denominators cannot carry span members")
        return self


class CellTruth(ClosedFixtureModel):
    cell_id: str
    row: int = Field(ge=0, lt=TABLE_LIMITS["maximum_rows_per_table"])
    column: int = Field(ge=0, lt=TABLE_LIMITS["maximum_columns_per_table"])
    row_span: int = Field(ge=1, le=TABLE_LIMITS["maximum_rows_per_table"])
    col_span: int = Field(ge=1, le=TABLE_LIMITS["maximum_columns_per_table"])
    text: str
    bbox: FiniteBBox
    column_header: bool
    row_header: bool
    evidence_basis: tuple[
        Literal["visible_text", "vector_grid", "p00_source_truth", "synthetic"], ...
    ] = Field(min_length=1, max_length=4)
    source_ref: str

    @field_validator("cell_id")
    @classmethod
    def valid_cell_id(cls, value: str) -> str:
        return _bounded_identifier(value, field_name="cell_id")

    @field_validator("text")
    @classmethod
    def bounded_text(cls, value: str) -> str:
        return _bounded_safe_string(
            value,
            field_name="cell text",
            maximum_utf8_bytes=TABLE_LIMITS["maximum_cell_text_utf8_bytes"],
            allow_line_breaks=True,
            allow_empty=True,
            require_trimmed=False,
        )

    @field_validator("source_ref")
    @classmethod
    def bounded_source_ref(cls, value: str) -> str:
        return _bounded_reference(value, field_name="source_ref")


class SourceObjectTruth(ClosedFixtureModel):
    id: str
    engine: Literal["synthetic"]
    object_type: Literal["visible_text", "vector_rule", "source_grid"]
    page_index: int = Field(ge=0)
    raw_ref: str
    content_sha256: str

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        return _bounded_identifier(value, field_name="source_object_id")

    @field_validator("raw_ref")
    @classmethod
    def valid_raw_ref(cls, value: str) -> str:
        return _bounded_reference(value, field_name="raw_ref")

    @field_validator("content_sha256")
    @classmethod
    def valid_content_sha256(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("source object requires lowercase SHA-256")
        return value


class EvidenceTruth(ClosedFixtureModel):
    id: str
    method: Literal["native_text", "vector_rule", "source_grid", "derived_comparison"]
    dimension: Literal["text", "geometry", "structure", "header", "ownership"]
    page_index: int = Field(ge=0)
    bbox: FiniteBBox | None
    source_object_ids: tuple[str, ...] = Field(
        min_length=1,
        max_length=TABLE_LIMITS["maximum_source_object_ids_per_record"],
    )
    confidence: float = Field(ge=0, le=1)
    content_sha256: str

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        return _bounded_identifier(value, field_name="evidence_id")

    @field_validator("source_object_ids")
    @classmethod
    def valid_source_object_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("evidence source-object identities must be unique")
        return tuple(
            _bounded_identifier(value, field_name="source_object_id") for value in values
        )

    @field_validator("confidence", mode="before")
    @classmethod
    def finite_confidence(cls, value: Any) -> Any:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise ValueError("evidence confidence must be finite")
        return value

    @field_validator("content_sha256")
    @classmethod
    def valid_content_sha256(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("evidence requires lowercase SHA-256")
        return value


class SpanDecisionTruth(ClosedFixtureModel):
    id: str
    cell_id: str
    claimed_row_span: int = Field(ge=1, le=TABLE_LIMITS["maximum_rows_per_table"])
    claimed_col_span: int = Field(ge=1, le=TABLE_LIMITS["maximum_columns_per_table"])
    emitted_row_span: int = Field(ge=1, le=TABLE_LIMITS["maximum_rows_per_table"])
    emitted_col_span: int = Field(ge=1, le=TABLE_LIMITS["maximum_columns_per_table"])
    outcome: Literal["supported", "refused", "ambiguous"]
    evidence_ids: tuple[str, ...] = Field(
        max_length=TABLE_LIMITS["maximum_evidence_ids_per_record"]
    )
    concern_codes: tuple[ConcernCode, ...] = Field(
        max_length=TABLE_LIMITS["maximum_concerns_per_table"]
    )

    @field_validator("id", "cell_id")
    @classmethod
    def valid_ids(cls, value: str) -> str:
        return _bounded_identifier(value, field_name="span decision identifier")

    @field_validator("evidence_ids")
    @classmethod
    def valid_evidence_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("span evidence identities must be unique")
        return tuple(_bounded_identifier(value, field_name="evidence_id") for value in values)

    @field_validator("concern_codes")
    @classmethod
    def unique_concern_codes(
        cls, values: tuple[ConcernCode, ...]
    ) -> tuple[ConcernCode, ...]:
        if len(values) != len(set(values)):
            raise ValueError("span concern codes must be unique")
        return values

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        is_claim = self.claimed_row_span > 1 or self.claimed_col_span > 1
        if not is_claim:
            raise ValueError("span decisions are only recorded for claims above one")
        if self.outcome == "supported":
            if (self.emitted_row_span, self.emitted_col_span) != (
                self.claimed_row_span,
                self.claimed_col_span,
            ):
                raise ValueError("supported span emission must equal its claim")
            if len(self.evidence_ids) < 2 or self.concern_codes:
                raise ValueError("supported spans require two evidence records and no concern")
        else:
            if (self.emitted_row_span, self.emitted_col_span) != (1, 1):
                raise ValueError("refused or ambiguous span claims emit unit spans")
            if not self.concern_codes:
                raise ValueError("refused or ambiguous spans require a concern")
        return self


class ReviewedRowTruth(ClosedFixtureModel):
    row_id: str
    source_table_row_index: int = Field(
        ge=0, lt=TABLE_LIMITS["maximum_rows_per_table"]
    )
    values: tuple[str, ...] = Field(
        min_length=1, max_length=TABLE_LIMITS["maximum_columns_per_table"]
    )
    bbox: FiniteBBox
    evidence_basis: Literal["reviewed_native_text"]
    qualification: str = Field(min_length=1, max_length=512)
    role: Literal["column_header", "body"] = "body"
    source_refs: tuple[str, ...] = Field(
        default=(), max_length=TABLE_LIMITS["maximum_columns_per_table"]
    )

    @field_validator("row_id")
    @classmethod
    def valid_row_id(cls, value: str) -> str:
        return _bounded_identifier(value, field_name="row_id")

    @field_validator("values")
    @classmethod
    def bounded_row_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(
            _bounded_safe_string(
                value,
                field_name="reviewed row cell text",
                maximum_utf8_bytes=TABLE_LIMITS["maximum_cell_text_utf8_bytes"],
                allow_line_breaks=True,
                allow_empty=True,
                require_trimmed=False,
            )
            for value in values
        )

    @field_validator("qualification")
    @classmethod
    def safe_qualification(cls, value: str) -> str:
        return _bounded_safe_string(
            value, field_name="row qualification", maximum_utf8_bytes=512
        )

    @field_validator("source_refs")
    @classmethod
    def valid_source_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_bounded_reference(value, field_name="source_ref") for value in values)

    @model_validator(mode="after")
    def validate_source_refs(self) -> Self:
        if self.source_refs and len(self.source_refs) != len(self.values):
            raise ValueError("reviewed row source refs must address every supplied value")
        return self


class ReviewedSourceObservation(ClosedFixtureModel):
    observation_id: str
    kind: Literal["visible_text", "vector_region", "row_boundary"]
    physical_page: int = Field(gt=0)
    bbox: FiniteBBox
    text: str | None = None
    source_ref: str
    evidence_basis: Literal[
        "reviewed_native_text", "reviewed_vector_geometry", "reviewed_visual_render"
    ]
    qualification: str = Field(min_length=1, max_length=512)

    @field_validator("observation_id")
    @classmethod
    def valid_observation_id(cls, value: str) -> str:
        return _bounded_identifier(value, field_name="observation_id")

    @field_validator("source_ref")
    @classmethod
    def valid_source_ref(cls, value: str) -> str:
        return _bounded_reference(value, field_name="source_ref")

    @field_validator("text")
    @classmethod
    def valid_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _bounded_safe_string(
            value,
            field_name="observation text",
            maximum_utf8_bytes=TABLE_LIMITS["maximum_cell_text_utf8_bytes"],
            allow_line_breaks=True,
        )

    @field_validator("qualification")
    @classmethod
    def safe_qualification(cls, value: str) -> str:
        return _bounded_safe_string(
            value, field_name="observation qualification", maximum_utf8_bytes=512
        )

    @model_validator(mode="after")
    def validate_kind(self) -> Self:
        if self.kind == "visible_text" and self.text is None:
            raise ValueError("visible-text observations require exact text")
        if self.kind != "visible_text" and self.text is not None:
            raise ValueError("geometry-only observations cannot claim text")
        return self

class ExactTableTruth(ClosedFixtureModel):
    oracle_id: str
    case_id: str
    physical_page: int = Field(gt=0)
    table_bbox: FiniteBBox
    row_count: int = Field(gt=0)
    column_count: int = Field(gt=0)
    cell_count: int = Field(gt=0)
    header_row_count: int = Field(ge=0)
    repeated_value: str | None = None
    repeated_value_count: int = Field(default=0, ge=0)
    cells: tuple[CellTruth, ...] = Field(
        max_length=TABLE_LIMITS["maximum_cells_per_table"]
    )
    source_truth_path: str
    source_truth_sha256: str

    @field_validator("oracle_id", "case_id")
    @classmethod
    def valid_ids(cls, value: str) -> str:
        return _bounded_identifier(value, field_name="table identifier")

    @field_validator("source_truth_path")
    @classmethod
    def valid_source_truth_path(cls, value: str) -> str:
        return validate_portable_workspace_path(value)

    @field_validator("repeated_value")
    @classmethod
    def valid_repeated_value(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _bounded_safe_string(
            value,
            field_name="repeated value",
            maximum_utf8_bytes=TABLE_LIMITS["maximum_cell_text_utf8_bytes"],
            allow_line_breaks=True,
            allow_empty=True,
            require_trimmed=False,
        )

    @model_validator(mode="after")
    def validate_exact_grid(self) -> Self:
        if self.row_count > TABLE_LIMITS["maximum_rows_per_table"]:
            raise ValueError("table row limit exceeded")
        if self.column_count > TABLE_LIMITS["maximum_columns_per_table"]:
            raise ValueError("table column limit exceeded")
        if self.cell_count > TABLE_LIMITS["maximum_cells_per_table"]:
            raise ValueError("table cell limit exceeded")
        if self.row_count * self.column_count != self.cell_count:
            raise ValueError("exact table must declare one explicit cell per grid slot")
        if len(self.cells) != self.cell_count:
            raise ValueError("exact cell denominator differs from supplied truth")
        if self.header_row_count > self.row_count:
            raise ValueError("header row count exceeds the declared grid")
        if self.repeated_value_count > self.cell_count:
            raise ValueError("repeated-value denominator exceeds exact cells")
        occupied: set[tuple[int, int]] = set()
        ids: set[str] = set()
        for cell in self.cells:
            if cell.cell_id in ids:
                raise ValueError("duplicate cell identity")
            ids.add(cell.cell_id)
            if cell.row + cell.row_span > self.row_count:
                raise ValueError("cell row span exceeds the declared grid")
            if cell.column + cell.col_span > self.column_count:
                raise ValueError("cell column span exceeds the declared grid")
            for row in range(cell.row, cell.row + cell.row_span):
                for column in range(cell.column, cell.column + cell.col_span):
                    if (row, column) in occupied:
                        raise ValueError("overlapping cells are not exact source truth")
                    occupied.add((row, column))
        if len(occupied) != self.cell_count:
            raise ValueError("exact table contains uncovered grid slots")
        observed = sum(cell.text == self.repeated_value for cell in self.cells)
        if observed != self.repeated_value_count:
            raise ValueError("repeated-value denominator differs from exact cells")
        if not _SHA256.fullmatch(self.source_truth_sha256):
            raise ValueError("source truth requires a lowercase SHA-256")
        return self


class QualifiedTableDenominator(ClosedFixtureModel):
    oracle_id: str
    case_id: str
    physical_page: int = Field(gt=0)
    region_id: str
    region_bbox: FiniteBBox | None
    review_state: Literal["source_qualified", "unresolved"]
    canonical_action: Literal[
        "score_reviewed_dimensions",
        "retain_candidate_with_concern",
    ]
    denominators: tuple[ReviewedDenominator, ...] = Field(
        default=(), max_length=TABLE_LIMITS["maximum_concerns_per_table"]
    )
    reviewed_rows: tuple[ReviewedRowTruth, ...] = Field(
        default=(), max_length=TABLE_LIMITS["maximum_rows_per_table"]
    )
    reviewed_source_objects: tuple[ReviewedSourceObservation, ...] = Field(
        default=(), max_length=TABLE_LIMITS["maximum_source_object_ids_per_record"]
    )
    unresolved_dimensions: tuple[Dimension, ...] = Field(
        default=(), max_length=TABLE_LIMITS["maximum_concerns_per_table"]
    )
    required_concerns: tuple[FailClosedConcern, ...] = Field(
        default=(), max_length=TABLE_LIMITS["maximum_concerns_per_table"]
    )
    evidence_path: str

    @field_validator("oracle_id", "case_id", "region_id")
    @classmethod
    def valid_ids(cls, value: str) -> str:
        return _bounded_identifier(value, field_name="qualified table identifier")

    @field_validator("evidence_path")
    @classmethod
    def valid_evidence_path(cls, value: str) -> str:
        return validate_portable_workspace_path(value)

    @model_validator(mode="after")
    def validate_qualifications(self) -> Self:
        if len(self.required_concerns) > TABLE_LIMITS["maximum_concerns_per_table"]:
            raise ValueError("table concern limit exceeded")
        dimensions = [item.dimension for item in self.denominators]
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("one table cannot declare duplicate denominator dimensions")
        denominator_ids = [item.denominator_id for item in self.denominators]
        if len(denominator_ids) != len(set(denominator_ids)):
            raise ValueError("denominator identities must be unique within a table")
        if set(dimensions) & set(self.unresolved_dimensions):
            raise ValueError("a dimension cannot be both scored and unresolved")
        concern_dimensions = {item.dimension for item in self.required_concerns}
        if len(self.unresolved_dimensions) != len(set(self.unresolved_dimensions)):
            raise ValueError("unresolved dimensions must be unique")
        if len(self.required_concerns) != len(concern_dimensions):
            raise ValueError("each unresolved dimension requires exactly one concern")
        if set(self.unresolved_dimensions) != concern_dimensions:
            raise ValueError("every unresolved dimension requires one fail-closed concern")
        column_claim = next(
            (item.expected for item in self.denominators if item.dimension == "column_count"),
            None,
        )
        if column_claim is not None and any(
            len(row.values) != column_claim for row in self.reviewed_rows
        ):
            raise ValueError("reviewed source row differs from the column denominator")
        row_ids = [row.row_id for row in self.reviewed_rows]
        row_indexes = [row.source_table_row_index for row in self.reviewed_rows]
        if len(row_ids) != len(set(row_ids)) or len(row_indexes) != len(set(row_indexes)):
            raise ValueError("reviewed source rows must have unique identities and indexes")
        observation_ids = [item.observation_id for item in self.reviewed_source_objects]
        if len(observation_ids) != len(set(observation_ids)):
            raise ValueError("reviewed source observations must have unique identities")
        if any(
            item.physical_page != self.physical_page
            for item in self.reviewed_source_objects
        ):
            raise ValueError("reviewed source observation points to a different page")
        if self.canonical_action == "retain_candidate_with_concern":
            if not self.unresolved_dimensions or not self.required_concerns:
                raise ValueError("unresolved candidates require explicit concerns")
        if self.review_state == "unresolved" and self.canonical_action != (
            "retain_candidate_with_concern"
        ):
            raise ValueError("unresolved source structure cannot be scored as truth")
        return self


class P04Us01Oracle(ClosedFixtureModel):
    sidecar_version: Literal["1.1"]
    policy_id: Literal["p04-table-evidence-v1"]
    story_id: Literal["P04-US01"]
    sources: tuple[SourceIdentity, ...] = Field(
        max_length=TABLE_LIMITS["maximum_oracle_tables"]
    )
    exact_tables: tuple[ExactTableTruth, ...] = Field(
        max_length=TABLE_LIMITS["maximum_oracle_tables"]
    )
    qualified_tables: tuple[QualifiedTableDenominator, ...] = Field(
        max_length=TABLE_LIMITS["maximum_oracle_tables"]
    )

    @model_validator(mode="after")
    def validate_complete_oracle(self) -> Self:
        source_ids = [source.case_id for source in self.sources]
        required = {
            "catastrophe-recap",
            "finance-10k",
            "postal-10k",
            "clinical-study",
            "ny-timetable",
            "insurance-acord",
        }
        if set(source_ids) != required or len(source_ids) != len(required):
            raise ValueError("US01 requires exactly the six reviewed source identities")
        tables = (*self.exact_tables, *self.qualified_tables)
        if len(tables) > TABLE_LIMITS["maximum_oracle_tables"]:
            raise ValueError("oracle table limit exceeded")
        if len({table.oracle_id for table in tables}) != len(tables):
            raise ValueError("oracle table identities must be unique")
        sources = {source.case_id: source for source in self.sources}
        for table in tables:
            source = sources.get(table.case_id)
            if source is None or table.physical_page > source.page_count:
                raise ValueError("table points outside its reviewed source")
            bbox = table.table_bbox if isinstance(table, ExactTableTruth) else table.region_bbox
            if bbox is not None and (
                bbox.x + bbox.width > source.page_width_pt + bbox.tolerance_pt
                or bbox.y + bbox.height > source.page_height_pt + bbox.tolerance_pt
            ):
                raise ValueError("table bbox exceeds its reviewed source page")
            if isinstance(table, QualifiedTableDenominator):
                for reviewed_row in table.reviewed_rows:
                    row_bbox = reviewed_row.bbox
                    if (
                        row_bbox.x + row_bbox.width
                        > source.page_width_pt + row_bbox.tolerance_pt
                        or row_bbox.y + row_bbox.height
                        > source.page_height_pt + row_bbox.tolerance_pt
                    ):
                        raise ValueError("reviewed source row exceeds its source page")
                for observation in table.reviewed_source_objects:
                    observed_bbox = observation.bbox
                    if (
                        observed_bbox.x + observed_bbox.width
                        > source.page_width_pt + observed_bbox.tolerance_pt
                        or observed_bbox.y + observed_bbox.height
                        > source.page_height_pt + observed_bbox.tolerance_pt
                    ):
                        raise ValueError(
                            "reviewed source observation exceeds its source page"
                        )
            else:
                for cell in table.cells:
                    cell_bbox = cell.bbox
                    if (
                        cell_bbox.x < table.table_bbox.x - cell_bbox.tolerance_pt
                        or cell_bbox.y < table.table_bbox.y - cell_bbox.tolerance_pt
                        or cell_bbox.x + cell_bbox.width
                        > table.table_bbox.x
                        + table.table_bbox.width
                        + cell_bbox.tolerance_pt
                        or cell_bbox.y + cell_bbox.height
                        > table.table_bbox.y
                        + table.table_bbox.height
                        + cell_bbox.tolerance_pt
                    ):
                        raise ValueError("exact cell bbox exceeds its reviewed table")
        exhibit = [table for table in self.exact_tables if table.oracle_id == "exhibit-7"]
        if len(exhibit) != 1:
            raise ValueError("US01 requires one exact Exhibit 7 oracle")
        exact = exhibit[0]
        if (
            exact.row_count,
            exact.column_count,
            exact.cell_count,
            exact.repeated_value,
            exact.repeated_value_count,
        ) != (6, 5, 30, "United States", 5):
            raise ValueError("Exhibit 7 exact denominator changed")
        return self


def validate_oracle(value: Any) -> P04Us01Oracle:
    """Strictly validate one readiness oracle without coercing input values."""

    return P04Us01Oracle.model_validate(value, strict=True)
