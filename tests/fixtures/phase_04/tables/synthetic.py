"""Material executable synthetic controls for P04-US01 readiness."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from tests.fixtures.phase_04.tables.contract import (
    TABLE_LIMITS,
    CellTruth,
    ClosedFixtureModel,
    ConcernCode,
    EvidenceTruth,
    FiniteBBox,
    SourceObjectTruth,
    SpanDecisionTruth,
    validate_fixture_identifier,
)


REQUIRED_SYNTHETIC_COVERAGE = (
    "repeated_values_without_span",
    "legitimate_colspan",
    "legitimate_rowspan",
    "ambiguous_border_refusal",
    "visual_wrap_one_logical_row",
    "blank_stub_section_cells",
    "rotated_multiline_headers",
    "bottom_boundary_completeness",
    "partial_grid_refusal",
    "decorative_form_rule_refusal",
    "duplicate_position_refusal",
    "overlapping_span_refusal",
    "negative_index_refusal",
    "nonfinite_bbox_refusal",
    "resource_boundaries",
    "html_escaping",
    "flag_off_identity",
)


class SyntheticFixtureDefinition(ClosedFixtureModel):
    fixture_id: str
    purpose: str = Field(min_length=1, max_length=512)
    covers: tuple[str, ...] = Field(min_length=1, max_length=8)
    expected_action: Literal[
        "canonical", "fail_closed", "validation_error", "identity"
    ]

    @field_validator("fixture_id")
    @classmethod
    def valid_fixture_id(cls, value: str) -> str:
        return validate_fixture_identifier(value)

    @field_validator("covers")
    @classmethod
    def valid_coverage_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("synthetic coverage identities must be unique")
        return tuple(validate_fixture_identifier(value) for value in values)

    @field_validator("purpose")
    @classmethod
    def safe_purpose(cls, value: str) -> str:
        if value.strip() != value or any(ord(character) < 32 for character in value):
            raise ValueError("synthetic purpose must be safe single-line text")
        if len(value.encode("utf-8")) > 512:
            raise ValueError("synthetic purpose exceeds the UTF-8 byte limit")
        return value


class SyntheticGrid(ClosedFixtureModel):
    fixture_id: str
    row_count: int = Field(gt=0, le=TABLE_LIMITS["maximum_rows_per_table"])
    column_count: int = Field(
        gt=0, le=TABLE_LIMITS["maximum_columns_per_table"]
    )
    cells: tuple[CellTruth, ...] = Field(
        max_length=TABLE_LIMITS["maximum_cells_per_table"]
    )
    source_objects: tuple[SourceObjectTruth, ...] = Field(
        default=(), max_length=TABLE_LIMITS["maximum_source_object_ids_per_record"]
    )
    evidence: tuple[EvidenceTruth, ...] = Field(
        default=(), max_length=TABLE_LIMITS["maximum_evidence_ids_per_record"]
    )
    span_decisions: tuple[SpanDecisionTruth, ...] = Field(
        default=(), max_length=TABLE_LIMITS["maximum_cells_per_table"]
    )
    expected_action: Literal["canonical", "fail_closed"]
    required_concern: ConcernCode | None = None

    @field_validator("fixture_id")
    @classmethod
    def valid_fixture_id(cls, value: str) -> str:
        return validate_fixture_identifier(value)

    @model_validator(mode="after")
    def validate_grid(self) -> Self:
        if self.row_count * self.column_count > TABLE_LIMITS["maximum_cells_per_table"]:
            raise ValueError("synthetic cell limit exceeded")
        cell_ids = [cell.cell_id for cell in self.cells]
        if len(cell_ids) != len(set(cell_ids)):
            raise ValueError("synthetic cell identities must be unique")
        occupied: set[tuple[int, int]] = set()
        for cell in self.cells:
            if cell.row + cell.row_span > self.row_count:
                raise ValueError("synthetic row span exceeds the grid")
            if cell.column + cell.col_span > self.column_count:
                raise ValueError("synthetic column span exceeds the grid")
            for row in range(cell.row, cell.row + cell.row_span):
                for column in range(cell.column, cell.column + cell.col_span):
                    if (row, column) in occupied:
                        raise ValueError("synthetic cells overlap")
                    occupied.add((row, column))

        source_ids = [item.id for item in self.source_objects]
        evidence_ids = [item.id for item in self.evidence]
        decision_ids = [item.id for item in self.span_decisions]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("synthetic source-object identities must be unique")
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("synthetic evidence identities must be unique")
        if len(decision_ids) != len(set(decision_ids)):
            raise ValueError("synthetic span-decision identities must be unique")
        source_id_set = set(source_ids)
        evidence_by_id = {item.id: item for item in self.evidence}
        for item in self.evidence:
            if not set(item.source_object_ids) <= source_id_set:
                raise ValueError("evidence refers to an absent source object")
        decisions_by_cell: dict[str, list[SpanDecisionTruth]] = {}
        for decision in self.span_decisions:
            if decision.cell_id not in cell_ids:
                raise ValueError("span decision refers to an absent cell")
            if not set(decision.evidence_ids) <= set(evidence_ids):
                raise ValueError("span decision refers to absent evidence")
            decisions_by_cell.setdefault(decision.cell_id, []).append(decision)
            if decision.outcome == "supported":
                linked = [evidence_by_id[item] for item in decision.evidence_ids]
                if {item.dimension for item in linked} < {"geometry", "structure"}:
                    raise ValueError(
                        "supported span requires addressable geometry and structure evidence"
                    )
                linked_source_ids = {
                    source_id
                    for item in linked
                    for source_id in item.source_object_ids
                }
                if len(linked_source_ids) < 2:
                    raise ValueError(
                        "supported span requires two independently addressable source objects"
                    )
        for cell in self.cells:
            decisions = decisions_by_cell.get(cell.cell_id, [])
            if cell.row_span > 1 or cell.col_span > 1:
                if len(decisions) != 1 or decisions[0].outcome != "supported":
                    raise ValueError("every emitted span requires one supported decision")
                if (
                    decisions[0].emitted_row_span,
                    decisions[0].emitted_col_span,
                ) != (cell.row_span, cell.col_span):
                    raise ValueError("span decision differs from emitted cell geometry")
            elif decisions:
                raise ValueError("unit cells cannot carry supported span decisions")

        if self.expected_action == "canonical":
            if self.required_concern is not None:
                raise ValueError("canonical synthetic controls cannot require refusal")
            if len(occupied) != self.row_count * self.column_count:
                raise ValueError("canonical synthetic grid has uncovered slots")
        elif self.required_concern is None:
            raise ValueError("fail-closed controls require a closed concern")
        return self


class FlagOffWitness(ClosedFixtureModel):
    fixture_id: Literal["flag_off_identity"]
    flags: tuple[tuple[str, Literal[False]], ...] = Field(min_length=4, max_length=4)
    fixture_load_count: Literal[0]
    phase04_stage_call_count: Literal[0]
    predecessor_sha256: str
    output_sha256: str

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        expected_flags = {
            "PARSER_TABLES_SPAN_FIDELITY_ENABLED",
            "PARSER_TABLES_EVIDENCE_RECONCILIATION_ENABLED",
            "PARSER_TABLES_CANDIDATE_GATE_ENABLED",
            "PARSER_TABLES_MULTI_PAGE_MERGE_ENABLED",
        }
        if {name for name, value in self.flags if value is False} != expected_flags:
            raise ValueError("flag-off witness requires all four exact false flags")
        if self.predecessor_sha256 != self.output_sha256:
            raise ValueError("flag-off output must equal the exact predecessor bytes")
        return self


class ResourceBoundaryWitness(ClosedFixtureModel):
    counter: Literal[
        "rows",
        "columns",
        "cells",
        "cell_text_utf8_bytes",
        "concerns",
        "evidence_ids",
        "source_object_ids",
        "identity_utf8_bytes",
        "reference_utf8_bytes",
        "portable_path_utf8_bytes",
        "table_sidecar_bytes",
        "document_sidecars_bytes",
        "span_page_seconds",
        "span_document_seconds",
        "p95_overhead_ratio",
        "peak_rss_delta_bytes",
    ]
    limit: float = Field(gt=0)
    observed: float = Field(gt=0)

    def execute(self) -> bool:
        return self.observed <= self.limit


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _cell(
    fixture_id: str,
    row: int,
    column: int,
    text: str,
    *,
    row_span: int = 1,
    col_span: int = 1,
    column_header: bool | None = None,
    row_header: bool = False,
) -> CellTruth:
    stable_id = fixture_id.replace("_", "-")
    return CellTruth(
        cell_id=f"{stable_id}-r{row}-c{column}",
        row=row,
        column=column,
        row_span=row_span,
        col_span=col_span,
        text=text,
        bbox=FiniteBBox(
            x=float(column * 50),
            y=float(row * 20),
            width=float(50 * col_span),
            height=float(20 * row_span),
        ),
        column_header=row == 0 if column_header is None else column_header,
        row_header=row_header,
        evidence_basis=("synthetic",),
        source_ref=f"synthetic:{fixture_id}:{row}:{column}",
    )


def _span_evidence(
    fixture_id: str,
    cell: CellTruth,
) -> tuple[
    tuple[SourceObjectTruth, ...],
    tuple[EvidenceTruth, ...],
    tuple[SpanDecisionTruth, ...],
]:
    stable_id = fixture_id.replace("_", "-")
    grid_id = f"{stable_id}-source-grid"
    rules_id = f"{stable_id}-vector-rules"
    structure_id = f"{stable_id}-structure-evidence"
    geometry_id = f"{stable_id}-geometry-evidence"
    source_objects = (
        SourceObjectTruth(
            id=grid_id,
            engine="synthetic",
            object_type="source_grid",
            page_index=0,
            raw_ref=f"synthetic:{fixture_id}:source-grid",
            content_sha256=_digest(f"{fixture_id}:source-grid"),
        ),
        SourceObjectTruth(
            id=rules_id,
            engine="synthetic",
            object_type="vector_rule",
            page_index=0,
            raw_ref=f"synthetic:{fixture_id}:vector-rules",
            content_sha256=_digest(f"{fixture_id}:vector-rules"),
        ),
    )
    evidence = (
        EvidenceTruth(
            id=structure_id,
            method="source_grid",
            dimension="structure",
            page_index=0,
            bbox=cell.bbox,
            source_object_ids=(grid_id,),
            confidence=1.0,
            content_sha256=_digest(f"{fixture_id}:structure:{cell.cell_id}"),
        ),
        EvidenceTruth(
            id=geometry_id,
            method="vector_rule",
            dimension="geometry",
            page_index=0,
            bbox=cell.bbox,
            source_object_ids=(rules_id,),
            confidence=1.0,
            content_sha256=_digest(f"{fixture_id}:geometry:{cell.cell_id}"),
        ),
    )
    decisions = (
        SpanDecisionTruth(
            id=f"{stable_id}-span-decision",
            cell_id=cell.cell_id,
            claimed_row_span=cell.row_span,
            claimed_col_span=cell.col_span,
            emitted_row_span=cell.row_span,
            emitted_col_span=cell.col_span,
            outcome="supported",
            evidence_ids=(structure_id, geometry_id),
            concern_codes=(),
        ),
    )
    return source_objects, evidence, decisions


def _header_evidence(
    fixture_id: str,
    bbox: FiniteBBox,
) -> tuple[tuple[SourceObjectTruth, ...], tuple[EvidenceTruth, ...]]:
    stable_id = fixture_id.replace("_", "-")
    object_id = f"{stable_id}-rotation-object"
    return (
        (
            SourceObjectTruth(
                id=object_id,
                engine="synthetic",
                object_type="visible_text",
                page_index=0,
                raw_ref=f"synthetic:{fixture_id}:rotation-90",
                content_sha256=_digest(f"{fixture_id}:rotation-90"),
            ),
        ),
        (
            EvidenceTruth(
                id=f"{stable_id}-header-evidence",
                method="derived_comparison",
                dimension="header",
                page_index=0,
                bbox=bbox,
                source_object_ids=(object_id,),
                confidence=1.0,
                content_sha256=_digest(f"{fixture_id}:multiline-header"),
            ),
        ),
    )


def _grid(
    fixture_id: str,
    row_count: int,
    column_count: int,
    cells: tuple[CellTruth, ...],
    *,
    expected_action: Literal["canonical", "fail_closed"] = "canonical",
    required_concern: ConcernCode | None = None,
    source_objects: tuple[SourceObjectTruth, ...] = (),
    evidence: tuple[EvidenceTruth, ...] = (),
    span_decisions: tuple[SpanDecisionTruth, ...] = (),
) -> SyntheticGrid:
    return SyntheticGrid(
        fixture_id=fixture_id,
        row_count=row_count,
        column_count=column_count,
        cells=cells,
        source_objects=source_objects,
        evidence=evidence,
        span_decisions=span_decisions,
        expected_action=expected_action,
        required_concern=required_concern,
    )


def _canonical_grid(fixture_id: str) -> SyntheticGrid:
    if fixture_id == "repeated_values_without_span":
        cells = tuple(
            _cell(fixture_id, row, column, "Same" if column == 0 else str(row))
            for row in range(3)
            for column in range(2)
        )
        return _grid(fixture_id, 3, 2, cells)
    if fixture_id == "legitimate_colspan":
        anchor = _cell(fixture_id, 0, 0, "Years ended", col_span=3)
        source_objects, evidence, decisions = _span_evidence(fixture_id, anchor)
        return _grid(
            fixture_id,
            2,
            3,
            (
                anchor,
                *tuple(
                    _cell(fixture_id, 1, column, str(2025 - column))
                    for column in range(3)
                ),
            ),
            source_objects=source_objects,
            evidence=evidence,
            span_decisions=decisions,
        )
    if fixture_id == "legitimate_rowspan":
        anchor = _cell(fixture_id, 0, 0, "Region", row_span=2)
        source_objects, evidence, decisions = _span_evidence(fixture_id, anchor)
        return _grid(
            fixture_id,
            2,
            2,
            (
                anchor,
                _cell(fixture_id, 0, 1, "2025"),
                _cell(fixture_id, 1, 1, "10", column_header=False),
            ),
            source_objects=source_objects,
            evidence=evidence,
            span_decisions=decisions,
        )
    if fixture_id == "visual_wrap_one_logical_row":
        return _grid(
            fixture_id,
            2,
            2,
            (
                _cell(fixture_id, 0, 0, "Account"),
                _cell(fixture_id, 0, 1, "Amount"),
                _cell(
                    fixture_id,
                    1,
                    0,
                    "Common stock and additional\npaid-in capital",
                    column_header=False,
                ),
                _cell(fixture_id, 1, 1, "73,812", column_header=False),
            ),
        )
    if fixture_id == "blank_stub_section_cells":
        return _grid(
            fixture_id,
            2,
            3,
            (
                _cell(fixture_id, 0, 0, "Measure"),
                _cell(fixture_id, 0, 1, "Control"),
                _cell(fixture_id, 0, 2, "Treatment"),
                _cell(fixture_id, 1, 0, "M (SD)", column_header=False, row_header=True),
                _cell(fixture_id, 1, 1, "", column_header=False),
                _cell(fixture_id, 1, 2, "", column_header=False),
            ),
        )
    if fixture_id == "rotated_multiline_headers":
        cells = (
            _cell(fixture_id, 0, 0, "Station\n(stop)"),
            _cell(fixture_id, 0, 1, "Train 101\nWeekday"),
            _cell(fixture_id, 0, 2, "Train 203\nExpress"),
            _cell(fixture_id, 1, 0, "Albany", column_header=False, row_header=True),
            _cell(fixture_id, 1, 1, "3:01", column_header=False),
            _cell(fixture_id, 1, 2, "3:32", column_header=False),
        )
        source_objects, evidence = _header_evidence(fixture_id, cells[0].bbox)
        return _grid(
            fixture_id,
            2,
            3,
            cells,
            source_objects=source_objects,
            evidence=evidence,
        )
    if fixture_id == "bottom_boundary_completeness":
        return _grid(
            fixture_id,
            3,
            2,
            (
                _cell(fixture_id, 0, 0, "Acronym"),
                _cell(fixture_id, 0, 1, "Definition"),
                _cell(fixture_id, 1, 0, "FEHB", column_header=False),
                _cell(fixture_id, 1, 1, "Federal Employees Health Benefits", column_header=False),
                _cell(fixture_id, 2, 0, "FERS", column_header=False),
                _cell(fixture_id, 2, 1, "Federal Employees Retirement System", column_header=False),
            ),
        )
    if fixture_id == "html_escaping":
        return _grid(
            fixture_id,
            2,
            2,
            (
                _cell(fixture_id, 0, 0, "<script>alert(1)</script>"),
                _cell(fixture_id, 0, 1, "<img src=x onerror=alert(1)>"),
                _cell(fixture_id, 1, 0, "AT&T", column_header=False),
                _cell(fixture_id, 1, 1, 'javascript:alert("x")', column_header=False),
            ),
        )
    raise KeyError(f"unknown canonical synthetic fixture: {fixture_id}")


def _fail_closed_grid(fixture_id: str) -> SyntheticGrid:
    if fixture_id == "ambiguous_border_refusal":
        return _grid(
            fixture_id,
            2,
            2,
            (
                _cell(fixture_id, 0, 0, "Q1"),
                _cell(fixture_id, 0, 1, "Q2"),
                _cell(fixture_id, 1, 0, "10", column_header=False),
            ),
            expected_action="fail_closed",
            required_concern="table_ambiguous_border_evidence",
        )
    if fixture_id == "partial_grid_refusal":
        return _grid(
            fixture_id,
            3,
            3,
            (
                _cell(fixture_id, 0, 0, "A"),
                _cell(fixture_id, 0, 1, "B"),
                _cell(fixture_id, 0, 2, "C"),
                _cell(fixture_id, 1, 0, "1", column_header=False),
                _cell(fixture_id, 2, 2, "9", column_header=False),
            ),
            expected_action="fail_closed",
            required_concern="table_ambiguous_border_evidence",
        )
    if fixture_id == "decorative_form_rule_refusal":
        return _grid(
            fixture_id,
            3,
            2,
            (
                _cell(fixture_id, 0, 0, "POLICY NUMBER"),
                _cell(fixture_id, 0, 1, "________________"),
                _cell(fixture_id, 1, 0, "CLAIMS MADE", column_header=False),
                _cell(fixture_id, 1, 1, "[ ]", column_header=False),
                _cell(fixture_id, 2, 0, "OCCURRENCE", column_header=False),
                _cell(fixture_id, 2, 1, "[ ]", column_header=False),
            ),
            expected_action="fail_closed",
            required_concern="table_source_form_grid_topology_unresolved",
        )
    raise KeyError(f"unknown fail-closed synthetic fixture: {fixture_id}")


_CANONICAL_FIXTURES = {
    "repeated_values_without_span",
    "legitimate_colspan",
    "legitimate_rowspan",
    "visual_wrap_one_logical_row",
    "blank_stub_section_cells",
    "rotated_multiline_headers",
    "bottom_boundary_completeness",
    "html_escaping",
}
_FAIL_CLOSED_FIXTURES = {
    "ambiguous_border_refusal",
    "partial_grid_refusal",
    "decorative_form_rule_refusal",
}
_VALIDATION_ERROR_FIXTURES = {
    "duplicate_position_refusal",
    "overlapping_span_refusal",
    "negative_index_refusal",
    "nonfinite_bbox_refusal",
    "resource_boundaries",
}


SYNTHETIC_FIXTURES = tuple(
    SyntheticFixtureDefinition(
        fixture_id=fixture_id,
        purpose=f"Executable P04-US01 readiness control: {fixture_id}.",
        covers=(fixture_id,),
        expected_action=(
            "canonical"
            if fixture_id in _CANONICAL_FIXTURES
            else (
                "fail_closed"
                if fixture_id in _FAIL_CLOSED_FIXTURES
                else "identity" if fixture_id == "flag_off_identity" else "validation_error"
            )
        ),
    )
    for fixture_id in REQUIRED_SYNTHETIC_COVERAGE
)


def build_synthetic_fixture(fixture_id: str) -> SyntheticGrid:
    known = {fixture.fixture_id: fixture for fixture in SYNTHETIC_FIXTURES}
    if fixture_id not in known:
        raise KeyError(f"unknown synthetic table fixture: {fixture_id}")
    action = known[fixture_id].expected_action
    if action in {"validation_error", "identity"}:
        raise ValueError(f"{action} fixtures use their dedicated builder")
    return (
        _canonical_grid(fixture_id)
        if action == "canonical"
        else _fail_closed_grid(fixture_id)
    )


def build_invalid_payload(fixture_id: str) -> dict[str, Any]:
    base: dict[str, Any] = {
        "fixture_id": fixture_id,
        "row_count": 1,
        "column_count": 1,
        "cells": [_cell(fixture_id, 0, 0, "value").model_dump(mode="python")],
        "source_objects": (),
        "evidence": (),
        "span_decisions": (),
        "expected_action": "canonical",
        "required_concern": None,
    }
    cell = base["cells"][0]
    if fixture_id == "negative_index_refusal":
        cell["row"] = -1
    elif fixture_id == "nonfinite_bbox_refusal":
        cell["bbox"]["x"] = float("nan")
    elif fixture_id == "duplicate_position_refusal":
        base["cells"] = [cell, dict(cell)]
        base["cells"][1]["cell_id"] = "duplicate-position-refusal-second"
    elif fixture_id == "overlapping_span_refusal":
        base["row_count"] = 2
        base["column_count"] = 2
        anchor = _cell(fixture_id, 0, 0, "Merged", col_span=2)
        source_objects, evidence, decisions = _span_evidence(fixture_id, anchor)
        base["cells"] = [
            anchor.model_dump(mode="python"),
            _cell(fixture_id, 0, 1, "Collision").model_dump(mode="python"),
            _cell(fixture_id, 1, 0, "A", column_header=False).model_dump(mode="python"),
            _cell(fixture_id, 1, 1, "B", column_header=False).model_dump(mode="python"),
        ]
        base["source_objects"] = tuple(
            item.model_dump(mode="python") for item in source_objects
        )
        base["evidence"] = tuple(item.model_dump(mode="python") for item in evidence)
        base["span_decisions"] = tuple(
            item.model_dump(mode="python") for item in decisions
        )
    elif fixture_id == "resource_boundaries":
        base["row_count"] = TABLE_LIMITS["maximum_rows_per_table"] + 1
    else:
        raise KeyError(f"unknown invalid synthetic fixture: {fixture_id}")
    return base


def build_flag_off_witness(predecessor: bytes = b'{"pages":[]}') -> FlagOffWitness:
    digest = hashlib.sha256(predecessor).hexdigest()
    return FlagOffWitness(
        fixture_id="flag_off_identity",
        flags=(
            ("PARSER_TABLES_SPAN_FIDELITY_ENABLED", False),
            ("PARSER_TABLES_EVIDENCE_RECONCILIATION_ENABLED", False),
            ("PARSER_TABLES_CANDIDATE_GATE_ENABLED", False),
            ("PARSER_TABLES_MULTI_PAGE_MERGE_ENABLED", False),
        ),
        fixture_load_count=0,
        phase04_stage_call_count=0,
        predecessor_sha256=digest,
        output_sha256=digest,
    )


_RESOURCE_KEY_BY_COUNTER = {
    "rows": "maximum_rows_per_table",
    "columns": "maximum_columns_per_table",
    "cells": "maximum_cells_per_table",
    "cell_text_utf8_bytes": "maximum_cell_text_utf8_bytes",
    "concerns": "maximum_concerns_per_table",
    "evidence_ids": "maximum_evidence_ids_per_record",
    "source_object_ids": "maximum_source_object_ids_per_record",
    "identity_utf8_bytes": "maximum_identity_utf8_bytes",
    "reference_utf8_bytes": "maximum_reference_utf8_bytes",
    "portable_path_utf8_bytes": "maximum_portable_path_utf8_bytes",
    "table_sidecar_bytes": "maximum_table_sidecar_bytes",
    "document_sidecars_bytes": "maximum_phase04_sidecars_per_document_bytes",
    "span_page_seconds": "maximum_span_fidelity_page_seconds",
    "span_document_seconds": "maximum_span_fidelity_document_seconds",
    "p95_overhead_ratio": "maximum_table_stage_p95_overhead_ratio",
    "peak_rss_delta_bytes": "maximum_peak_rss_delta_bytes",
}


def build_resource_boundary_witness(
    counter: str,
    *,
    overflow: bool,
) -> ResourceBoundaryWitness:
    key = _RESOURCE_KEY_BY_COUNTER[counter]
    limit = float(TABLE_LIMITS[key])
    increment = 1e-6 if isinstance(TABLE_LIMITS[key], float) else 1.0
    return ResourceBoundaryWitness(
        counter=counter,
        limit=limit,
        observed=limit + increment * int(overflow),
    )


def registry_sha256() -> str:
    payload = json.dumps(
        [fixture.model_dump(mode="json") for fixture in SYNTHETIC_FIXTURES],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def self_check() -> None:
    fixture_ids = tuple(fixture.fixture_id for fixture in SYNTHETIC_FIXTURES)
    if fixture_ids != REQUIRED_SYNTHETIC_COVERAGE or len(set(fixture_ids)) != len(
        fixture_ids
    ):
        raise ValueError("synthetic fixture coverage drifted")
    for fixture in SYNTHETIC_FIXTURES:
        if fixture.expected_action in {"canonical", "fail_closed"}:
            built = build_synthetic_fixture(fixture.fixture_id)
            if built.expected_action != fixture.expected_action:
                raise ValueError("synthetic fixture action drifted")
        elif fixture.expected_action == "identity":
            build_flag_off_witness()
    if len(registry_sha256()) != 64:
        raise ValueError("synthetic registry identity is invalid")
