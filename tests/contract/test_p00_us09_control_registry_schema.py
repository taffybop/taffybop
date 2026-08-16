"""Strict contract gates for the P00-US09 benchmark-control registry."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from tests.benchmarks.contracts import CONTRACT_VERSION
from tests.benchmarks.control_registry import (
    CONTROL_REGISTRY_ID,
    CONTROL_ROLE_ORDER,
    EXPECTED_BEHAVIOR_BY_ROLE,
    BenchmarkControlRegistry,
    CaseGapRow,
    CaseReportBinding,
    ClaimLocatorRef,
    ControlAssignment,
    ControlRole,
    ExpectedBehavior,
    GapControlSet,
    ReviewBatchBinding,
    SourceBinding,
    build_benchmark_control_registry,
)
from tests.benchmarks.corpus_registry import load_corpus_registry
from tests.benchmarks.reviewed_claim_inventory import (
    BATCH_A_EVIDENCE_PATH,
    BATCH_B_EVIDENCE_PATH,
    BATCH_C_EVIDENCE_PATH,
    load_reviewed_claim_batch_a,
    load_reviewed_claim_batch_b,
    load_reviewed_claim_batch_c,
)


WORKSPACE = Path(__file__).resolve().parents[2]
CORPUS_REGISTRY_PATH = (
    WORKSPACE
    / "tracker"
    / "phase-00-baseline"
    / "evidence"
    / "P00-US04-corpus-registry.json"
)
SHA256_PATTERN = "^[0-9a-f]{64}$"


@pytest.fixture(scope="module")
def registry_payload() -> dict[str, Any]:
    corpus_registry = load_corpus_registry(CORPUS_REGISTRY_PATH)
    review_batches = (
        load_reviewed_claim_batch_a(
            WORKSPACE / BATCH_A_EVIDENCE_PATH,
            WORKSPACE,
            corpus_registry,
        ),
        load_reviewed_claim_batch_b(
            WORKSPACE / BATCH_B_EVIDENCE_PATH,
            WORKSPACE,
            corpus_registry,
        ),
        load_reviewed_claim_batch_c(
            WORKSPACE / BATCH_C_EVIDENCE_PATH,
            WORKSPACE,
            corpus_registry,
        ),
    )
    return build_benchmark_control_registry(
        WORKSPACE,
        corpus_registry,
        review_batches,
    ).model_dump(mode="json")


def _set_path(
    payload: dict[str, Any],
    path: tuple[str | int, ...],
    value: object,
) -> None:
    target: Any = payload
    for segment in path[:-1]:
        target = target[segment]
    target[path[-1]] = value


def test_control_registry_schema_is_strict_versioned_and_count_bounded(
    registry_payload: dict[str, Any],
) -> None:
    models = (
        SourceBinding,
        ReviewBatchBinding,
        CaseReportBinding,
        ClaimLocatorRef,
        ControlAssignment,
        GapControlSet,
        CaseGapRow,
        BenchmarkControlRegistry,
    )
    assert all(
        model.model_json_schema()["additionalProperties"] is False
        for model in models
    )

    schema = BenchmarkControlRegistry.model_json_schema()
    properties = schema["properties"]
    assert properties["schema_version"]["const"] == CONTRACT_VERSION
    assert properties["registry_id"]["const"] == CONTROL_REGISTRY_ID
    assert properties["reviewed_claim_count"]["const"] == 210
    assert properties["gap_owner_count"]["const"] == 25
    assert properties["role_assignment_count"]["const"] == 100
    assert properties["case_gap_row_count"]["const"] == 109
    assert properties["review_batches"]["minItems"] == 3
    assert properties["review_batches"]["maxItems"] == 3
    assert properties["case_reports"]["minItems"] == 15
    assert properties["case_reports"]["maxItems"] == 15
    assert properties["gap_controls"]["minItems"] == 25
    assert properties["gap_controls"]["maxItems"] == 25
    assert properties["case_gap_rows"]["minItems"] == 109
    assert properties["case_gap_rows"]["maxItems"] == 109
    assert (
        schema["$defs"]["GapControlSet"]["properties"]["assignments"]["minItems"]
        == 4
    )
    assert (
        schema["$defs"]["GapControlSet"]["properties"]["assignments"]["maxItems"]
        == 4
    )

    registry = BenchmarkControlRegistry.model_validate(registry_payload)
    assert registry.schema_version == CONTRACT_VERSION
    assert registry.registry_id == CONTROL_REGISTRY_ID
    assert len(registry.review_batches) == 3
    assert len(registry.case_reports) == 15
    assert len(registry.gap_controls) == registry.gap_owner_count == 25
    assert len(registry.case_gap_rows) == registry.case_gap_row_count == 109
    assert (
        sum(len(control.assignments) for control in registry.gap_controls)
        == registry.role_assignment_count
        == 100
    )


def test_registry_wire_fields_are_explicit_and_complete(
    registry_payload: dict[str, Any],
) -> None:
    assert set(registry_payload) == {
        "schema_version",
        "registry_id",
        "corpus_registry_sha256",
        "reviewed_claim_count",
        "gap_owner_count",
        "role_assignment_count",
        "case_gap_row_count",
        "matrix_source",
        "review_batches",
        "case_reports",
        "gap_controls",
        "case_gap_rows",
    }
    assert set(registry_payload["matrix_source"]) == {"path", "sha256"}
    assert set(registry_payload["review_batches"][0]) == {
        "batch_id",
        "evidence_path",
        "evidence_file_sha256",
        "semantic_sha256",
        "claim_count",
    }
    assert set(registry_payload["case_reports"][0]) == {
        "case_id",
        "report_path",
        "report_sha256",
        "mapped_gap_row_count",
    }
    assert set(registry_payload["gap_controls"][0]) == {
        "matrix_row_index",
        "matrix_row_sha256",
        "gap_id",
        "primary_story_id",
        "secondary_stories",
        "story_action",
        "dedicated_test_anchor",
        "milestone",
        "assignments",
    }
    assert set(registry_payload["gap_controls"][0]["assignments"][0]) == {
        "assignment_id",
        "role",
        "expected_behavior",
        "evidence",
        "rationale",
    }
    assert set(
        registry_payload["gap_controls"][0]["assignments"][0]["evidence"]
    ) == {"case_id", "claim_id", "region_id"}
    assert set(registry_payload["case_gap_rows"][0]) == {
        "row_id",
        "case_id",
        "report_row_index",
        "gap_id",
        "raw_row_sha256",
        "origin",
        "mapped_capability",
        "exact_evidence",
        "exact_source_region",
        "why_reusable",
        "claim_locator",
    }


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("schema_version", "2.0"),
        ("registry_id", "p00-us09-control-registry"),
        ("reviewed_claim_count", 209),
        ("gap_owner_count", 24),
        ("role_assignment_count", 99),
        ("case_gap_row_count", 108),
    ],
)
def test_registry_rejects_wrong_version_identity_and_declared_counts(
    registry_payload: dict[str, Any],
    field: str,
    invalid: object,
) -> None:
    payload = deepcopy(registry_payload)
    payload[field] = invalid

    with pytest.raises(ValidationError):
        BenchmarkControlRegistry.model_validate(payload)


@pytest.mark.parametrize(
    "collection",
    [
        "review_batches",
        "case_reports",
        "gap_controls",
        "case_gap_rows",
    ],
)
def test_registry_rejects_missing_finite_members(
    registry_payload: dict[str, Any],
    collection: str,
) -> None:
    payload = deepcopy(registry_payload)
    payload[collection].pop()

    with pytest.raises(ValidationError):
        BenchmarkControlRegistry.model_validate(payload)


def test_control_enums_and_expected_behaviors_are_closed() -> None:
    schema = BenchmarkControlRegistry.model_json_schema()["$defs"]
    assert schema["ControlRole"]["enum"] == [
        member.value for member in ControlRole
    ]
    assert schema["ExpectedBehavior"]["enum"] == [
        member.value for member in ExpectedBehavior
    ]
    assert CONTROL_ROLE_ORDER == tuple(ControlRole)
    assert tuple(EXPECTED_BEHAVIOR_BY_ROLE) == CONTROL_ROLE_ORDER
    assert tuple(EXPECTED_BEHAVIOR_BY_ROLE.values()) == tuple(ExpectedBehavior)


@pytest.mark.parametrize(
    ("path", "invalid"),
    [
        (("gap_controls", 0, "assignments", 0, "role"), "positive"),
        (
            (
                "gap_controls",
                0,
                "assignments",
                0,
                "expected_behavior",
            ),
            "assert_exact_match",
        ),
    ],
)
def test_registry_rejects_unknown_control_enums(
    registry_payload: dict[str, Any],
    path: tuple[str | int, ...],
    invalid: str,
) -> None:
    payload = deepcopy(registry_payload)
    _set_path(payload, path, invalid)

    with pytest.raises(ValidationError):
        BenchmarkControlRegistry.model_validate(payload)


def test_registry_rejects_mismatched_role_and_expected_behavior(
    registry_payload: dict[str, Any],
) -> None:
    payload = deepcopy(registry_payload)
    payload["gap_controls"][0]["assignments"][0]["expected_behavior"] = (
        ExpectedBehavior.ASSERT_RELATED_SUPPORTED_BEHAVIOR.value
    )

    with pytest.raises(
        ValidationError,
        match="expected_behavior must match the control role",
    ):
        BenchmarkControlRegistry.model_validate(payload)


def test_registry_rejects_missing_duplicate_and_out_of_order_roles(
    registry_payload: dict[str, Any],
) -> None:
    missing = deepcopy(registry_payload)
    missing["gap_controls"][0]["assignments"].pop()
    with pytest.raises(ValidationError):
        BenchmarkControlRegistry.model_validate(missing)

    duplicate = deepcopy(registry_payload)
    duplicate_assignment = duplicate["gap_controls"][0]["assignments"][1]
    duplicate_assignment["role"] = ControlRole.TARGET.value
    duplicate_assignment["expected_behavior"] = (
        ExpectedBehavior.ASSERT_SUPPORTED_CAPABILITY.value
    )
    with pytest.raises(
        ValidationError,
        match="control assignments must contain all roles in order",
    ):
        BenchmarkControlRegistry.model_validate(duplicate)

    out_of_order = deepcopy(registry_payload)
    assignments = out_of_order["gap_controls"][0]["assignments"]
    assignments[0], assignments[1] = assignments[1], assignments[0]
    with pytest.raises(
        ValidationError,
        match="control assignments must contain all roles in order",
    ):
        BenchmarkControlRegistry.model_validate(out_of_order)


def test_registry_rejects_duplicate_assignments_owners_claims_and_rows(
    registry_payload: dict[str, Any],
) -> None:
    duplicate_assignment = deepcopy(registry_payload)
    assignments = duplicate_assignment["gap_controls"][0]["assignments"]
    assignments[1]["assignment_id"] = assignments[0]["assignment_id"]
    with pytest.raises(
        ValidationError,
        match="control assignment IDs must be unique",
    ):
        BenchmarkControlRegistry.model_validate(duplicate_assignment)

    duplicate_claim = deepcopy(registry_payload)
    assignments = duplicate_claim["gap_controls"][0]["assignments"]
    assignments[1]["evidence"] = deepcopy(assignments[0]["evidence"])
    with pytest.raises(
        ValidationError,
        match="gap control quartet must use four distinct claims",
    ):
        BenchmarkControlRegistry.model_validate(duplicate_claim)

    duplicate_owner = deepcopy(registry_payload)
    duplicate_owner["gap_controls"][1]["gap_id"] = (
        duplicate_owner["gap_controls"][0]["gap_id"]
    )
    with pytest.raises(ValidationError, match="gap owners must be unique"):
        BenchmarkControlRegistry.model_validate(duplicate_owner)

    duplicate_row = deepcopy(registry_payload)
    duplicate_row["case_gap_rows"][1]["row_id"] = (
        duplicate_row["case_gap_rows"][0]["row_id"]
    )
    with pytest.raises(ValidationError, match="case-gap row IDs must be unique"):
        BenchmarkControlRegistry.model_validate(duplicate_row)


def test_registry_rejects_unknown_fields_and_missing_required_fields(
    registry_payload: dict[str, Any],
) -> None:
    top_extra = deepcopy(registry_payload)
    top_extra["generated_at"] = "2026-07-29"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        BenchmarkControlRegistry.model_validate(top_extra)

    nested_extra = deepcopy(registry_payload)
    nested_extra["case_gap_rows"][0]["confidence"] = 1.0
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        BenchmarkControlRegistry.model_validate(nested_extra)

    missing_top = deepcopy(registry_payload)
    del missing_top["matrix_source"]
    with pytest.raises(ValidationError):
        BenchmarkControlRegistry.model_validate(missing_top)

    missing_nested = deepcopy(registry_payload)
    del missing_nested["gap_controls"][0]["assignments"][0]["rationale"]
    with pytest.raises(ValidationError):
        BenchmarkControlRegistry.model_validate(missing_nested)


@pytest.mark.parametrize(
    ("path", "invalid"),
    [
        (("gap_controls", 0, "gap_id"), "gap-benchmark-001"),
        (("gap_controls", 0, "primary_story_id"), "US04"),
        (
            ("gap_controls", 0, "assignments", 0, "assignment_id"),
            "P00-US09 assignment 1",
        ),
        (
            (
                "gap_controls",
                0,
                "assignments",
                0,
                "evidence",
                "claim_id",
            ),
            "P00-US06:claim",
        ),
        (("case_reports", 0, "case_id"), "Catastrophe Recap"),
        (("case_gap_rows", 0, "row_id"), "p00-us09:"),
    ],
)
def test_registry_rejects_malformed_stable_gap_and_story_ids(
    registry_payload: dict[str, Any],
    path: tuple[str | int, ...],
    invalid: str,
) -> None:
    payload = deepcopy(registry_payload)
    _set_path(payload, path, invalid)

    with pytest.raises(ValidationError):
        BenchmarkControlRegistry.model_validate(payload)


@pytest.mark.parametrize(
    ("path", "invalid"),
    [
        (("corpus_registry_sha256",), "0" * 63),
        (("matrix_source", "sha256"), "A" * 64),
        (("review_batches", 0, "evidence_file_sha256"), "g" * 64),
        (("review_batches", 0, "semantic_sha256"), ""),
        (("case_reports", 0, "report_sha256"), "1" * 65),
        (("gap_controls", 0, "matrix_row_sha256"), "not-a-hash"),
        (("case_gap_rows", 0, "raw_row_sha256"), "F" * 64),
    ],
)
def test_registry_rejects_malformed_sha256_values(
    registry_payload: dict[str, Any],
    path: tuple[str | int, ...],
    invalid: str,
) -> None:
    payload = deepcopy(registry_payload)
    _set_path(payload, path, invalid)

    with pytest.raises(ValidationError):
        BenchmarkControlRegistry.model_validate(payload)


@pytest.mark.parametrize(
    ("path", "invalid"),
    [
        (("matrix_source", "path"), "/tmp/gap-to-story-matrix.md"),
        (
            ("review_batches", 0, "evidence_path"),
            "../evidence/batch-a.json",
        ),
        (
            ("case_reports", 0, "report_path"),
            "tracker/../reviews/catastrophe-recap.md",
        ),
        (
            ("case_reports", 0, "report_path"),
            r"tracker\reviews\catastrophe-recap.md",
        ),
        (("matrix_source", "path"), "./tracker/gap-to-story-matrix.md"),
        (("matrix_source", "path"), "C:/tracker/gap-to-story-matrix.md"),
    ],
)
def test_registry_rejects_nonportable_source_paths(
    registry_payload: dict[str, Any],
    path: tuple[str | int, ...],
    invalid: str,
) -> None:
    payload = deepcopy(registry_payload)
    _set_path(payload, path, invalid)

    with pytest.raises(ValidationError):
        BenchmarkControlRegistry.model_validate(payload)


def test_case_gap_rows_accept_only_the_two_frozen_source_shapes(
    registry_payload: dict[str, Any],
) -> None:
    registry = BenchmarkControlRegistry.model_validate(registry_payload)
    evidence_rows = [
        row
        for row in registry.case_gap_rows
        if row.exact_evidence is not None
    ]
    source_region_rows = [
        row
        for row in registry.case_gap_rows
        if row.exact_source_region is not None
    ]

    assert evidence_rows
    assert source_region_rows
    assert all(
        row.exact_source_region is None and row.why_reusable is None
        for row in evidence_rows
    )
    assert all(
        row.origin is None
        and row.exact_evidence is None
        and row.why_reusable is not None
        for row in source_region_rows
    )

    missing_evidence = deepcopy(registry_payload)
    missing_evidence["case_gap_rows"][0]["exact_evidence"] = None
    with pytest.raises(
        ValidationError,
        match="case-gap row must retain one recognized table schema",
    ):
        BenchmarkControlRegistry.model_validate(missing_evidence)

    mixed_shapes = deepcopy(registry_payload)
    source_region_index = next(
        index
        for index, row in enumerate(mixed_shapes["case_gap_rows"])
        if row["exact_source_region"] is not None
    )
    mixed_shapes["case_gap_rows"][source_region_index]["exact_evidence"] = (
        "ambiguous duplicate evidence column"
    )
    with pytest.raises(
        ValidationError,
        match="case-gap row must retain one recognized table schema",
    ):
        BenchmarkControlRegistry.model_validate(mixed_shapes)

    incomplete_source_region = deepcopy(registry_payload)
    incomplete_source_region["case_gap_rows"][source_region_index][
        "why_reusable"
    ] = None
    with pytest.raises(
        ValidationError,
        match="case-gap row must retain one recognized table schema",
    ):
        BenchmarkControlRegistry.model_validate(incomplete_source_region)


def test_case_gap_claim_locator_must_retain_its_row_case(
    registry_payload: dict[str, Any],
) -> None:
    payload = deepcopy(registry_payload)
    payload["case_gap_rows"][0]["claim_locator"]["case_id"] = (
        payload["case_reports"][1]["case_id"]
    )

    with pytest.raises(
        ValidationError,
        match="case-gap claim locator must use the row case_id",
    ):
        BenchmarkControlRegistry.model_validate(payload)
