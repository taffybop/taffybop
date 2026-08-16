"""Readiness-only contracts for P04-US01 table evidence.

These tests intentionally do not import production configuration, extraction,
serialization, API, or frontend code. They freeze policy/fixture boundaries;
passing them is not evidence that P04-US01 is implemented, In Progress, or
Done.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.fixtures.phase_04.tables.contract import (
    CONCERN_CODES,
    POLICY_ID,
    SIDECAR_VERSION,
    TABLE_LIMITS,
    CellTruth,
    FiniteBBox,
)


WORKSPACE = Path(__file__).resolve().parents[2]
POLICY_PATH = (
    WORKSPACE
    / "tracker"
    / "phase-04-tables"
    / "decisions"
    / "P04-table-evidence-policy.md"
)

EXPECTED_FLAGS = (
    "PARSER_TABLES_SPAN_FIDELITY_ENABLED",
    "PARSER_TABLES_EVIDENCE_RECONCILIATION_ENABLED",
    "PARSER_TABLES_CANDIDATE_GATE_ENABLED",
    "PARSER_TABLES_MULTI_PAGE_MERGE_ENABLED",
)
EXPECTED_LIMITS = {
    "maximum_rows_per_table": 4_096,
    "maximum_columns_per_table": 256,
    "maximum_cells_per_table": 65_536,
    "maximum_cell_text_utf8_bytes": 16_384,
    "maximum_concerns_per_table": 64,
    "maximum_oracle_tables": 64,
    "maximum_evidence_ids_per_record": 64,
    "maximum_source_object_ids_per_record": 64,
    "maximum_identity_utf8_bytes": 256,
    "maximum_reference_utf8_bytes": 256,
    "maximum_portable_path_utf8_bytes": 256,
    "maximum_table_sidecar_bytes": 8_388_608,
    "maximum_phase04_sidecars_per_document_bytes": 67_108_864,
    "maximum_span_fidelity_page_seconds": 0.500,
    "maximum_span_fidelity_document_seconds": 5.000,
    "maximum_table_stage_p95_overhead_ratio": 0.10,
    "maximum_peak_rss_delta_bytes": 67_108_864,
}


def _policy() -> str:
    return POLICY_PATH.read_text(encoding="utf-8")


def _normalized_policy() -> str:
    return " ".join(_policy().split())


def _cell(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "cell_id": "fixture-cell",
        "row": 0,
        "column": 0,
        "row_span": 1,
        "col_span": 1,
        "text": "United States",
        "bbox": {
            "x": 10.0,
            "y": 20.0,
            "width": 30.0,
            "height": 8.0,
            "unit": "pt",
            "tolerance_pt": 0.0,
        },
        "column_header": False,
        "row_header": False,
        "evidence_basis": ("visible_text", "vector_grid"),
        "source_ref": "fixture-object-1",
    }
    value.update(overrides)
    return value


def test_policy_freezes_identity_scope_and_four_default_off_flags() -> None:
    policy = _policy()

    assert POLICY_ID == "p04-table-evidence-v1"
    assert SIDECAR_VERSION == "1.1"
    assert "P04-US01\nentered In Progress on 2026-08-04" in policy
    assert "P04-US01 oracle, synthetic controls, limits" in policy
    assert "did not start P04-US02, P04-US04, or P04-US03" in policy
    assert "is not itself\ncompletion evidence" in policy
    for flag in EXPECTED_FLAGS:
        assert policy.count(f"`{flag}`") == 1
    assert policy.count("| `false` |") == 4


def test_policy_freezes_dependencies_stage_order_and_exact_rollback() -> None:
    policy = _normalized_policy()

    assert "evidence reconciliation |" in policy
    assert "span fidelity and evidence reconciliation" in policy
    assert "span fidelity, evidence reconciliation, and candidate gate" in policy
    assert "finish source-text alignment" in policy
    assert "replay and validate table semantics" in policy
    assert "exact predecessor result" in policy
    assert "restores the complete predecessor page/table/canonical closure" in policy


def test_policy_freezes_closed_slot_span_representation_and_fail_closed_rules() -> None:
    policy = _normalized_policy()

    required_fragments = (
        "Unknown keys fail the affected table closed",
        "`anchor`, `explicit_blank`, or `covered`",
        "cannot be confused with an absent value created by a span",
        "Repetition, blank text, engine preference, or visual proximity alone",
        "single semantic grid",
        "CSV is not claimed to encode span semantics",
        "Any shape, cell-text, header, span, or hash disagreement",
        "never expose raw cell text",
        "Only adjacent, US04-gated, structurally valid page-local tables",
        "cannot enter the accuracy numerator or denominator",
        "form-owned vector grid",
        "cannot be canonicalized by P04-US01",
    )
    for fragment in required_fragments:
        assert fragment in policy


def test_readiness_limits_are_exact_and_immutable() -> None:
    assert dict(TABLE_LIMITS) == EXPECTED_LIMITS
    with pytest.raises(TypeError):
        TABLE_LIMITS["maximum_rows_per_table"] = 1  # type: ignore[index]

    policy = _policy()
    for rendered in (
        "4,096 rows",
        "256 columns",
        "65,536 cells",
        "16,384",
        "67,108,864",
        "8,388,608",
        "0.500-second page",
        "5.000-second document",
    ):
        assert rendered in policy

    normalized = " ".join(policy.split())
    assert (
        "maximum-of-five nonnegative enabled-minus-disabled "
        "candidate-window RSS-growth delta"
    ) in normalized
    assert (
        "p04-us01-worker-max-parse-and-output-current-hwm-growth-v3"
    ) in policy
    assert (
        "p04-us01-paired-nonnegative-enabled-minus-disabled-worker-"
        "phase04-output-complete-peak-rss-increment-v3"
    ) in policy
    assert "p95 overhead ratio of `0.10`" in normalized
    assert "contain no `..`" in policy
    assert "following symlinks" in normalized


def test_fixture_models_are_strict_closed_finite_and_text_bounded() -> None:
    cell = CellTruth.model_validate(_cell(), strict=True)
    assert cell.text == "United States"
    assert cell.evidence_basis == ("visible_text", "vector_grid")

    with pytest.raises(ValidationError, match="extra_forbidden"):
        CellTruth.model_validate(_cell(unexpected=True), strict=True)
    with pytest.raises(ValidationError, match="greater than or equal|finite"):
        FiniteBBox.model_validate(
            {
                "x": float("nan"),
                "y": 0.0,
                "width": 1.0,
                "height": 1.0,
                "unit": "pt",
                "tolerance_pt": 0.0,
            },
            strict=True,
        )
    with pytest.raises(ValidationError, match="byte limit"):
        CellTruth.model_validate(
            _cell(text="x" * (TABLE_LIMITS["maximum_cell_text_utf8_bytes"] + 1)),
            strict=True,
        )


def test_concern_vocabulary_is_bounded_and_fail_closed() -> None:
    assert len(CONCERN_CODES) <= TABLE_LIMITS["maximum_concerns_per_table"]
    assert len(CONCERN_CODES) == len(set(CONCERN_CODES))
    assert {
        "table_source_cell_grid_unresolved",
        "table_source_span_evidence_unresolved",
        "table_source_cell_bbox_unresolved",
        "table_source_provenance_unresolved",
        "table_source_header_ownership_unresolved",
        "table_source_row_boundary_unresolved",
        "table_resource_limit_exceeded",
    }.issubset(CONCERN_CODES)
