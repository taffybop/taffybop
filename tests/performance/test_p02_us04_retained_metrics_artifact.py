from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pytest

from tests.benchmarks.text_reconciliation_metrics import (
    CATASTROPHE_CASE_ID,
    DEFAULT_OUTPUT,
    EXPECTED_ACTUAL_CATASTROPHE_CHART_LEGACY_ITEM_ID,
    EXPECTED_ACTUAL_CATASTROPHE_CHART_OWNER_ELEMENT_ID,
    EXPECTED_ACTUAL_CATASTROPHE_CHART_RUN_IDS,
    EXPECTED_ACTUAL_CATASTROPHE_OWNERLESS_RUN_IDS,
    EXPECTED_ACTUAL_CATASTROPHE_PROSE_LEGACY_ITEM_ID,
    EXPECTED_ACTUAL_CATASTROPHE_PROSE_OWNER_ELEMENT_ID,
    EXPECTED_ACTUAL_CATASTROPHE_PROSE_RUN_TEXT,
    EXPECTED_CASE_IDS,
    EXPECTED_RETAINED_SHA256,
    _code_bindings,
    _font_run_id_from_trace,
    _prepare_actual_p02_us03_case,
)


WORKSPACE = Path(__file__).resolve().parents[2]
ARTIFACT = WORKSPACE / DEFAULT_OUTPUT
EXPECTED_ARTIFACT_SHA256 = (
    "e877a82921b16a071afaade99d4d72fdf6ebfc9e4bb49260bb9c7c08205c1479"
)
PHASE03_SUCCESSOR_OWNED_CODE_BINDINGS = frozenset({"ir", "presentation"})


@pytest.fixture(scope="module")
def metrics() -> dict[str, Any]:
    raw = ARTIFACT.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == EXPECTED_ARTIFACT_SHA256
    payload = json.loads(raw)
    assert isinstance(payload, dict)
    return payload


def _assert_distribution(distribution: dict[str, float]) -> None:
    assert all(
        math.isfinite(value) and value >= 0
        for value in distribution.values()
    )
    assert (
        distribution["p50"]
        <= distribution["p95"]
        <= distribution["max"]
    )


def test_retained_metrics_bind_exact_inputs_code_and_sampling(
    metrics: dict[str, Any],
) -> None:
    assert metrics["record_kind"] == (
        "p02_us04_text_reconciliation_component_metrics"
    )
    assert metrics["schema_version"] == "1.0"
    assert metrics["method"]["warmups_per_scenario"] == 2
    assert metrics["method"]["samples_per_scenario"] == 10
    assert metrics["method"][
        "observed_paired_full_parser_percentile"
    ] is False
    assert metrics["environment"]["compatible"] is True
    retained_bindings = metrics["code_bindings"]
    current_bindings = _code_bindings(WORKSPACE)
    assert isinstance(retained_bindings, dict)
    assert retained_bindings.keys() == current_bindings.keys()
    changed_since_seal: set[str] = set()
    for name, retained in retained_bindings.items():
        assert isinstance(retained, dict)
        assert retained["path"] == current_bindings[name]["path"]
        assert len(str(retained["sha256"])) == 64
        assert int(retained["size_bytes"]) > 0
        if retained != current_bindings[name]:
            changed_since_seal.add(name)
    # The immutable artifact authenticates the original bindings. Phase 03
    # successor stories extend only the shared IR and presentation surfaces;
    # the US04-owned reconciliation implementation remains live-bound.
    assert changed_since_seal == PHASE03_SUCCESSOR_OWNED_CODE_BINDINGS
    assert {
        key: value["sha256"]
        for key, value in metrics["input_bindings"].items()
    } == EXPECTED_RETAINED_SHA256

    actual_cases = metrics["actual_production_inputs"]
    assert tuple(case["case_id"] for case in actual_cases) == (
        EXPECTED_CASE_IDS
    )
    assert all(
        case["warmup_count"] == 2
        and case["sample_count"] == 10
        and len(case["latency_samples_ms"]) == 10
        and case["structurally_deterministic"] is True
        and case["flag_off_parity"]["exact"] is True
        and case["flag_on_integration"]["exact"] is True
        and case["reconciliation_reentry"]["exact"] is True
        and case["reconciliation_reentry"]["same_object_on_reentry"]
        is True
        and case["peak_rss_after_bytes"] > 0
        and case["peak_rss_increment_bytes"] >= 0
        for case in actual_cases
    )
    for case in actual_cases:
        _assert_distribution(case["latency_ms"])
        assert all(
            math.isfinite(value) and value >= 0
            for value in case["latency_samples_ms"]
        )

    synthetic = metrics["deterministic_synthetic_controls"]
    renderer = metrics["actual_renderer_test_only_upstream"]
    for measured in (synthetic, renderer):
        assert measured["warmup_count"] == 2
        assert measured["sample_count"] == 10
        assert len(measured["latency_samples_ms"]) == 10
        assert measured["structurally_deterministic"] is True
        assert measured["peak_rss_after_bytes"] > 0
        assert measured["peak_rss_increment_bytes"] >= 0
        _assert_distribution(measured["latency_ms"])


def test_retained_catastrophe_profile_is_exact_and_evidence_bound(
    metrics: dict[str, Any],
) -> None:
    catastrophe = next(
        case
        for case in metrics["actual_production_inputs"]
        if case["case_id"] == CATASTROPHE_CASE_ID
    )
    result = catastrophe["result"]
    policy = catastrophe["catastrophe_policy_resolution"]
    prose_ids = set(EXPECTED_ACTUAL_CATASTROPHE_PROSE_RUN_TEXT)
    chart_ids = set(EXPECTED_ACTUAL_CATASTROPHE_CHART_RUN_IDS)
    ownerless_ids = set(EXPECTED_ACTUAL_CATASTROPHE_OWNERLESS_RUN_IDS)
    all_run_ids = prose_ids | chart_ids | ownerless_ids

    assert result["trace_count"] == 29
    assert result["legacy_projection_trace_count"] == 26
    assert result["ir_only_trace_count"] == 3
    assert policy["prose_run_text"] == (
        EXPECTED_ACTUAL_CATASTROPHE_PROSE_RUN_TEXT
    )
    assert policy["prose_owner_element_id"] == (
        EXPECTED_ACTUAL_CATASTROPHE_PROSE_OWNER_ELEMENT_ID
    )
    assert policy["prose_legacy_item_id"] == (
        EXPECTED_ACTUAL_CATASTROPHE_PROSE_LEGACY_ITEM_ID
    )
    assert set(policy["already_primary_unchanged_run_ids"]) == prose_ids
    assert set(policy["chart_run_ids"]) == chart_ids
    assert policy["chart_owner_element_id"] == (
        EXPECTED_ACTUAL_CATASTROPHE_CHART_OWNER_ELEMENT_ID
    )
    assert policy["chart_legacy_item_id"] == (
        EXPECTED_ACTUAL_CATASTROPHE_CHART_LEGACY_ITEM_ID
    )
    assert set(policy["owner_linked_unresolved_run_ids"]) == chart_ids
    assert set(policy["pinned_ownerless_run_ids"]) == ownerless_ids
    assert set(policy["ownerless_unresolved_run_ids"]) == ownerless_ids
    assert policy["selected_ownerless_run_ids"] == []
    assert policy["unchanged_count"] == 2
    assert policy["unresolved_count"] == 27
    assert policy["selected_ownerless_count"] == 0

    ownership = catastrophe["recovery_ownership"]
    assert set(ownership["owner_linked_run_evidence_ids"]) == (
        prose_ids | chart_ids
    )
    assert set(ownership["ownerless_run_evidence_ids"]) == ownerless_ids
    bindings = {
        binding["run_evidence_id"]: binding
        for binding in catastrophe["font_decision_evidence_bindings"]
    }
    traces = {
        run_id: trace
        for trace in result["traces"]
        if (run_id := _font_run_id_from_trace(trace)) is not None
    }
    retained_runs = {
        str(run["evidence_id"]): run
        for run in _prepare_actual_p02_us03_case(
            WORKSPACE,
            CATASTROPHE_CASE_ID,
        )["recovery"]["runs"]
    }
    assert set(bindings) == set(traces) == set(retained_runs) == all_run_ids

    for run_id, trace in traces.items():
        decisions = trace["decisions"]
        assert len(decisions) == 2
        assert len(
            {decision["candidate_id"] for decision in decisions}
        ) == 2
        decisions_by_id = {
            decision["candidate_id"]: decision for decision in decisions
        }
        font = decisions_by_id[f"font:{run_id}"]
        native = decisions_by_id[f"native:{run_id}"]
        assert font["text"] == retained_runs[run_id]["recovered_text"]
        assert native["text"] == retained_runs[run_id]["original_text"]
        assert font["evidence_ids"] == bindings[run_id][
            "font_evidence_ids"
        ]
        assert native["evidence_ids"] == bindings[run_id][
            "native_evidence_ids"
        ]

        legacy_item_ids = {
            source["item_id"]
            for source in trace["trace_sources"]
            if source["trace_location"] == "legacy_projection"
        }
        if run_id in prose_ids:
            assert trace["status"] == "unchanged"
            assert trace["reason_code"] == "deterministic_font_evidence"
            assert trace["selected_text"] == (
                EXPECTED_ACTUAL_CATASTROPHE_PROSE_RUN_TEXT[run_id]
            )
            assert trace["selected_candidate_ids"] == [f"font:{run_id}"]
            assert trace["owner_element_id"] == (
                EXPECTED_ACTUAL_CATASTROPHE_PROSE_OWNER_ELEMENT_ID
            )
            assert legacy_item_ids == {
                EXPECTED_ACTUAL_CATASTROPHE_PROSE_LEGACY_ITEM_ID
            }
        elif run_id in chart_ids:
            assert trace["status"] == "unresolved"
            assert trace["reason_code"] == "replacement_range_ambiguous"
            assert trace["selected_text"] is None
            assert trace["selected_candidate_ids"] == []
            assert trace["owner_element_id"] == (
                EXPECTED_ACTUAL_CATASTROPHE_CHART_OWNER_ELEMENT_ID
            )
            assert legacy_item_ids == {
                EXPECTED_ACTUAL_CATASTROPHE_CHART_LEGACY_ITEM_ID
            }
        else:
            assert run_id in ownerless_ids
            assert trace["status"] == "unresolved"
            assert trace["reason_code"] == "replacement_range_ambiguous"
            assert trace["selected_text"] is None
            assert trace["selected_candidate_ids"] == []
            assert trace["trace_locations"] == ["ir_element"]
            assert legacy_item_ids == set()

    assert result["evidence_identity_exact"] is True
    assert result["evidence_core_unchanged"] is True
    assert result["element_content_and_role_unchanged"] is True
    assert result["canonical_presentation_unchanged"] is True
    assert result["selection_surface_disagreements"] == []
    assert result["unretained_decision_evidence_ids"] == []
    assert result["semantic_completion_count"] == 0
    assert result["canonical_duplicate_block_id_count"] == 0
    assert result["alternate_canonical_leak_count"] == 0
    assert set(result["target_sentence_counts"].values()) == {1}

    reentry = catastrophe["reconciliation_reentry"]
    assert reentry["exact"] is True
    assert reentry["same_object_on_reentry"] is True
    assert reentry["first_terminal_concern_count"] == 29
    assert reentry["second_terminal_concern_count"] == 29
    assert reentry["first_manifest_count"] == 1
    assert reentry["second_manifest_count"] == 1


def test_retained_summary_and_bounded_controls_pass(
    metrics: dict[str, Any],
) -> None:
    summary = metrics["summary"]
    assert summary["actual_production_case_count"] == 15
    assert summary["exact_source_hash_count"] == 15
    assert summary["healthy_control_count"] == 14
    assert summary["healthy_flag_on_exact_parity_count"] == 14
    assert summary["flag_off_exact_parity_count"] == 15
    assert summary["flag_on_round_trip_exact_count"] == 15
    assert summary["actual_reentry_exact_count"] == 15
    assert summary["authenticated_manifest_reentry_exact_count"] == 1
    assert summary["actual_catastrophe_reentry_terminal_group_count"] == 29
    assert summary["actual_catastrophe_reentry_manifest_count"] == 1
    assert summary["actual_catastrophe_unchanged_count"] == 2
    assert summary["actual_catastrophe_unresolved_count"] == 27
    assert summary["actual_catastrophe_owner_linked_unresolved_count"] == 24
    assert summary["actual_catastrophe_ownerless_unresolved_count"] == 3
    assert summary["actual_catastrophe_selected_ownerless_count"] == 0
    assert summary["actual_catastrophe_target_sentence_exact"] is True
    assert summary["actual_evidence_identity_exact_count"] == 15
    assert summary["actual_evidence_core_unchanged_count"] == 15
    assert (
        summary["actual_element_content_and_role_unchanged_count"] == 15
    )
    assert summary["actual_canonical_presentation_unchanged_count"] == 15
    assert summary["pre_post_custody_match"] is True

    for key in (
        "reason_coverage",
        "evidence_coverage",
        "schema_coverage",
        "alternative_retention",
    ):
        assert summary[key] == 1.0
    for key in (
        "canonical_duplicate_count",
        "alternate_canonical_leak_count",
        "selection_surface_disagreement_count",
        "unretained_decision_evidence_id_count",
        "semantic_completion_count",
    ):
        assert summary[key] == 0

    ceiling = summary["combined_healthy_p95_ceiling_reference"]
    assert ceiling["observed_paired_full_parser_percentile"] is False
    assert ceiling["arithmetic_ceiling_percent"] == pytest.approx(
        ceiling["retained_p02_us03_arithmetic_ceiling_percent"]
        + ceiling["reconciliation_p95_percent"]
    )
    assert ceiling["arithmetic_ceiling_percent"] <= 10.0
    assert ceiling["passes_target"] is True

    synthetic = metrics["deterministic_synthetic_controls"]
    assert synthetic["actual_production_input"] is False
    assert synthetic["scenario_count"] == 9
    assert synthetic["group_count"] == 10
    assert synthetic["candidate_count"] == 19
    assert synthetic["observed_terminal_counts"] == {
        "selected": 2,
        "unchanged": 4,
        "unresolved": 4,
    }
    assert synthetic["coverage"]["schema_coverage"] == 1.0
    assert synthetic["coverage"]["semantic_completion_count"] == 0

    renderer = metrics["actual_renderer_test_only_upstream"]
    assert renderer["actual_production_upstream_input"] is False
    assert renderer["upstream_variant_kind"] == (
        "deterministic_test_only_recovery_refusal"
    )
    assert renderer["actual_pdfium_render"] is True
    assert renderer["actual_local_tesseract"] is True
    assert renderer["group_count"] == 4
    assert renderer["candidate_count"] == 8
    assert renderer["reciprocal_overlap_gate_count"] == 4
    assert [
        row["audit_run_index"] for row in renderer["input_trace"]
    ] == [1, 2, 3, 4]
    assert len(renderer["outcomes"]) == 4
    assert all(
        outcome["status"] == "unresolved"
        for outcome in renderer["outcomes"]
    )
