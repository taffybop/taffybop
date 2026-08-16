"""Custody, quality, and resource gate for retained P03-US04 evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from tests.benchmarks.layout_reading_order_metrics import (
    ALL_CASES,
    CODE_PATHS,
    EXPECTED_INPUTS,
    PERFORMANCE_CASES,
    PHASE_02_PERFORMANCE_BASELINES,
    REVIEWED_CASES,
    _artifact_semantic_payload,
    _canonical_json,
)


WORKSPACE = Path(__file__).resolve().parents[2]
ARTIFACT = (
    WORKSPACE
    / "tracker"
    / "phase-03-layout"
    / "evidence"
    / "P03-US04-reading-order-metrics.json"
)
EXPECTED_ARTIFACT_SHA256 = (
    "826af5de42950c11e4fa2bcbf8a24f5adc2ad2c62d7a09cb760c4e08bc591154"
)
EXPECTED_SEMANTIC_SHA256 = (
    "46cef72e08707cc57fd54834c7ff4369a59558b4e2de1a47155da23b66803ab1"
)

# Later Phase 03 stories deliberately extend shared surfaces.  The retained
# raw artifact pins their US04 state; current-tree equality remains mandatory
# for US04-owned policy, implementation, harnesses, and tests.
P03_SUCCESSOR_OWNED_INPUTS = frozenset(
    {
        ".env.example",
        "README.md",
        "app/config.py",
        "app/models.py",
        "app/services/ir.py",
        "app/services/layout.py",
        "app/services/pipeline.py",
        "app/services/presentation.py",
        "app/services/serializer.py",
        "app/services/source_text_alignment.py",
        "frontend/app/clearleaf-workspace.tsx",
        "frontend/lib/canonical-presentation.ts",
        "frontend/lib/normalize-document-json.ts",
        "frontend/lib/serialize-output.ts",
        "frontend/lib/types.ts",
    }
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact() -> dict[str, Any]:
    raw = ARTIFACT.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == EXPECTED_ARTIFACT_SHA256
    return json.loads(raw)


def test_retained_artifact_binds_final_code_inputs_and_digest() -> None:
    artifact = _artifact()

    assert artifact["schema_version"] == "1.0"
    assert artifact["story"] == "P03-US04"
    assert artifact["semantic_sha256"] == EXPECTED_SEMANTIC_SHA256
    semantic_digest = hashlib.sha256(
        _canonical_json(_artifact_semantic_payload(artifact)).encode("utf-8")
    ).hexdigest()
    assert semantic_digest == EXPECTED_SEMANTIC_SHA256

    code_records = artifact["code_sha256"]
    assert set(code_records) == set(CODE_PATHS)
    assert P03_SUCCESSOR_OWNED_INPUTS < set(code_records)
    for relative, expected_sha256 in code_records.items():
        assert len(expected_sha256) == 64
        if relative in P03_SUCCESSOR_OWNED_INPUTS:
            continue
        path = WORKSPACE / relative
        assert path.is_file()
        assert _sha256(path) == expected_sha256

    assert set(artifact["cases"]) == set(ALL_CASES)
    assert set(artifact["input_custody"]) == set(ALL_CASES)
    for case_name, expected in EXPECTED_INPUTS.items():
        custody = artifact["input_custody"][case_name]
        assert custody["expected"] == expected
        assert custody["exact_match"] is True
        observed = custody["observed"]
        source = WORKSPACE / observed["path"]
        assert source.stat().st_size == observed["size_bytes"]
        assert observed["size_bytes"] == expected["size_bytes"]
        assert _sha256(source) == observed["sha256"]
        assert observed["sha256"] == expected["sha256"]


def test_retained_reviewed_quality_and_rollback_are_exact() -> None:
    artifact = _artifact()
    reviewed_expected = 0
    reviewed_matched = 0

    assert artifact["oracle"]["fixed_pair_count"] == 41
    assert artifact["oracle"]["top_level_pair_count"] == 40
    assert artifact["oracle"]["nested_pair_count"] == 1
    assert artifact["oracle"]["reviewed_case_count"] == len(REVIEWED_CASES)

    for case_name in ALL_CASES:
        case = artifact["cases"][case_name]
        expected_pairs = 5 if case_name in PERFORMANCE_CASES else 1
        assert case["pair_count"] == expected_pairs
        assert len(case["execution_order"]) == expected_pairs
        assert case["flag_off"]["enabled"] is False
        assert case["flag_on"]["enabled"] is True
        assert case["flag_off"]["hosted_requests"] == 0
        assert case["flag_on"]["hosted_requests"] == 0
        assert case["sample_consistency"][
            "all_flag_off_quality_valid"
        ] is True
        assert case["sample_consistency"][
            "all_flag_on_quality_valid"
        ] is True

        quality = case["quality"]
        assert quality["all_flag_off_sample_quality_valid"] is True
        assert quality["all_flag_on_sample_quality_valid"] is True
        assert quality["all_keyed_mutation_within_policy"] is True
        assert quality["flag_off_semantic_deterministic"] is True
        assert quality["flag_on_semantic_deterministic"] is True
        assert quality["json"]["all_flag_off_round_trip_equal"] is True
        assert quality["json"]["all_flag_on_round_trip_equal"] is True
        assert quality["json"][
            "keyed_items_equal_outside_accepted_corrections"
        ] is True
        assert quality["canonical"][
            "keyed_blocks_equal_outside_accepted_corrections"
        ] is True
        assert quality["canonical"][
            "all_flag_off_order_matches_public"
        ] is True
        assert quality["canonical"][
            "all_flag_on_order_matches_public"
        ] is True
        assert quality["markdown"][
            "all_flag_off_matches_canonical"
        ] is True
        assert quality["markdown"][
            "all_flag_on_matches_canonical"
        ] is True
        assert quality["rollback"][
            "all_flag_off_samples_projection_absent"
        ] is True
        assert quality["rollback"][
            "flag_off_settings_equal_exact_us03_predecessor"
        ] is True
        assert quality["rollback"]["only_us04_setting_toggled"] is True

        order = quality["order"]
        assert order["all_flag_on_ids_unique"] is True
        assert order["all_flag_on_ranks_contiguous"] is True
        assert order["all_flag_on_samples_match_oracle"] is True
        reviewed_expected += order["reviewed_pair_expected"]
        reviewed_matched += order["reviewed_pair_matched"]

    assert reviewed_expected == 41
    assert reviewed_matched == 41
    aggregate = artifact["aggregate"]
    assert aggregate["reviewed_pair_expected"] == 41
    assert aggregate["reviewed_pair_matched"] == 41
    assert aggregate["reviewed_pair_recall"] == 1.0
    assert aggregate["all_flag_off_rollback_exact"] is True
    assert aggregate["rollback_exact"] is True
    assert aggregate["all_keyed_mutation_within_policy"] is True
    assert aggregate["finance_exact_semantic_flag_parity"] is True
    assert aggregate["finance_exact_markdown_flag_parity"] is True
    assert aggregate["all_json_round_trip_exact"] is True
    assert aggregate["all_markdown_matches_canonical"] is True
    assert aggregate["all_canonical_order_matches_public"] is True

    rollback = artifact["rollback"]
    assert rollback["overflow_anchor_count"] == 513
    assert rollback["anchor_limit"] == 512
    assert rollback["exact_predecessor_restored"] is True
    assert rollback["repeated_projection_idempotent"] is True
    assert rollback["concerns_sanitized"] is True
    assert rollback["concern_codes"] == ["relationship_order_page_limit"]


def test_retained_performance_resources_and_dependency_custody() -> None:
    artifact = _artifact()

    for case_name, baseline in PHASE_02_PERFORMANCE_BASELINES.items():
        performance = artifact["cases"][case_name][
            "paired_performance"
        ]
        assert performance["pair_count"] == 5
        assert performance["execution_order_alternated"] is True
        assert performance["process_model"] == (
            "fresh_process_per_flag_state"
        )
        assert performance["quantile_method"] == (
            "empirical_p95_inclusive"
        )
        assert len(performance["flag_off_wall_seconds"]) == 5
        assert len(performance["flag_on_wall_seconds"]) == 5
        assert len(
            performance["paired_nonnegative_overhead_seconds"]
        ) == 5
        assert performance["phase_02_baseline_seconds"] == (
            baseline["wall_seconds"]
        )
        assert performance["five_percent_ceiling_seconds"] == (
            baseline["five_percent_ceiling_seconds"]
        )
        assert performance["p95_nonnegative_overhead_seconds"] <= (
            performance["five_percent_ceiling_seconds"]
        )
        assert performance["within_five_percent_ceiling"] is True

    stage = artifact["layout_stage"]
    assert stage["warmup_count"] == 5
    assert stage["sample_count"] == 100
    assert stage["anchor_count"] == 64
    assert stage["exact_order"] is True
    assert stage["p95_seconds"] <= stage["p95_ceiling_seconds"] == 0.05
    assert stage["peak_allocated_bytes"] < (
        stage["peak_allocation_ceiling_bytes"]
    )
    assert stage["within_p95_ceiling"] is True
    assert stage["within_peak_allocation_ceiling"] is True

    boundary = artifact["maximum_boundary"]
    assert boundary["anchor_count"] == boundary["anchor_limit"] == 512
    assert boundary["exact_order"] is True
    assert boundary["contiguous_reading_order"] is True
    assert boundary["elapsed_seconds"] <= boundary["ceiling_seconds"] == 0.25
    assert boundary["within_ceiling"] is True

    aggregate = artifact["aggregate"]
    assert aggregate["performance_p95_within_five_percent"] is True
    assert aggregate["stage_p95_within_50ms"] is True
    assert aggregate["stage_peak_allocation_within_32mib"] is True
    assert aggregate["maximum_boundary_within_250ms"] is True
    assert aggregate["hosted_requests"] == 0
    assert aggregate["hosted_tokens"] == 0
    assert aggregate["hosted_cost_usd"] == 0

    custody = artifact["dependency_custody"]
    assert custody["python_packages"] == {
        "docling": "2.114.0",
        "docling-core": "2.88.0",
        "pdfplumber": "0.11.10",
        "pydantic": "2.13.4",
    }
    assert custody["tesseract"]["version"] == "tesseract 5.5.3"
    assert custody["tesseract"]["size_bytes"] == 69_184
    assert len(custody["tesseract"]["sha256"]) == 64
    for relative, expected_sha256 in custody[
        "dependency_manifest_sha256"
    ].items():
        assert len(expected_sha256) == 64
        assert _sha256(WORKSPACE / relative) == expected_sha256
