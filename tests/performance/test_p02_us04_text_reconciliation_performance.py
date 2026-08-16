from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.benchmarks.text_reconciliation_metrics import (
    CATASTROPHE_CASE_ID,
    EXPECTED_ACTUAL_CATASTROPHE_CHART_LEGACY_ITEM_ID,
    EXPECTED_ACTUAL_CATASTROPHE_CHART_OWNER_ELEMENT_ID,
    EXPECTED_ACTUAL_CATASTROPHE_CHART_RUN_IDS,
    EXPECTED_ACTUAL_CATASTROPHE_OWNER_LINKED_RUNS,
    EXPECTED_ACTUAL_CATASTROPHE_OWNERLESS_RUN_IDS,
    EXPECTED_ACTUAL_CATASTROPHE_OWNERLESS_RUNS,
    EXPECTED_ACTUAL_CATASTROPHE_PROSE_LEGACY_ITEM_ID,
    EXPECTED_ACTUAL_CATASTROPHE_PROSE_OWNER_ELEMENT_ID,
    EXPECTED_ACTUAL_CATASTROPHE_PROSE_RUN_TEXT,
    EXPECTED_ACTUAL_CATASTROPHE_SELECTED_OWNERLESS_RUNS,
    EXPECTED_ACTUAL_CATASTROPHE_UNCHANGED_RUNS,
    EXPECTED_ACTUAL_CATASTROPHE_UNRESOLVED_RUNS,
    EXPECTED_ACTUAL_RENDER_TEST_ONLY_OUTCOMES,
    EXPECTED_RETAINED_SHA256,
    HEALTHY_OVERHEAD_TARGET_PERCENT,
    PRODUCTION_PRESENTATION_CODE,
    _combined_healthy_ceiling,
    _collect,
    _fixture_limitations,
    _font_run_id_from_trace,
    _measure_deterministic,
    _nearest_rank,
    _prepare_actual_p02_us03_case,
    _projection_reconciliation_traces,
    _reconciliation_operation,
    _report_coverage,
    _retained_inputs,
    _synthetic_groups,
)


WORKSPACE = Path(__file__).resolve().parents[2]


def _assert_ordered_distribution(distribution: dict[str, float]) -> None:
    assert distribution["p50"] > 0
    assert (
        distribution["p50"]
        <= distribution["p95"]
        <= distribution["max"]
    )


def test_reconciliation_metric_percentiles_use_nearest_rank() -> None:
    values = [5.0, 1.0, 4.0, 2.0, 3.0]

    assert _nearest_rank(values, 0.50) == 3.0
    assert _nearest_rank(values, 0.95) == 5.0
    with pytest.raises(ValueError, match="at least one"):
        _nearest_rank([], 0.95)
    with pytest.raises(ValueError, match="percentile"):
        _nearest_rank(values, 0.0)
    with pytest.raises(ValueError, match="finite"):
        _nearest_rank([math.inf], 0.95)


def test_reconciliation_measurement_rejects_structural_drift() -> None:
    counter = 0

    def changing() -> dict[str, int]:
        nonlocal counter
        counter += 1
        return {"counter": counter}

    with pytest.raises(RuntimeError, match="measured samples"):
        _measure_deterministic(changing, warmups=0, samples=2)

    payload, durations = _measure_deterministic(
        lambda: {"status": "unchanged"},
        warmups=1,
        samples=2,
    )
    assert payload == {"status": "unchanged"}
    assert len(durations) == 2
    assert all(duration >= 0 for duration in durations)


def test_retained_phase_2_artifacts_form_a_hash_bound_ceiling() -> None:
    retained = _retained_inputs(WORKSPACE)
    ceiling = _combined_healthy_ceiling(retained, 0.25)

    assert retained["retained_p02_us03_ceiling_percent"] > 0
    assert all(
        len(identity["sha256"]) == 64
        for identity in retained["identities"].values()
    )
    assert {
        key: value["sha256"]
        for key, value in retained["identities"].items()
    } == EXPECTED_RETAINED_SHA256
    assert ceiling["arithmetic_ceiling_percent"] == pytest.approx(
        retained["retained_p02_us03_ceiling_percent"] + 0.25
    )
    assert ceiling["observed_paired_full_parser_percentile"] is False
    assert (
        ceiling["arithmetic_ceiling_percent"]
        <= HEALTHY_OVERHEAD_TARGET_PERCENT
    )
    assert ceiling["passes_target"] is True


def test_fixture_limitations_are_measured_and_not_promoted() -> None:
    retained = _retained_inputs(WORKSPACE)
    limitations = _fixture_limitations(WORKSPACE, retained)

    assert limitations["approved_corpus_case_count"] == 15
    assert limitations["approved_scanned_candidate_count"] == 0
    assert limitations["approved_mixed_native_scanned_candidate_count"] == 0
    assert limitations["actual_production_ocr_win_fixture_available"] is False
    assert limitations[
        "reviewed_typed_false_duplicate_candidate_registry_available"
    ] is False
    assert limitations["actual_renderer_evidence_upstream_kind"] == (
        "deterministic_test_only_recovery_refusal"
    )
    overlap = limitations["actual_renderer_candidate_target_overlap"]
    assert len(overlap) == EXPECTED_ACTUAL_RENDER_TEST_ONLY_OUTCOMES
    assert all(
        row["source_bbox_area_overlap"] < 0.80
        and row["passes_policy_minimum"] is False
        for row in overlap
    )


def test_actual_inputs_are_unmodified_production_reports() -> None:
    retained = _retained_inputs(WORKSPACE)
    target = _prepare_actual_p02_us03_case(
        WORKSPACE,
        "catastrophe-recap",
    )
    healthy = _prepare_actual_p02_us03_case(WORKSPACE, "finance-10k")

    assert target["audit_report_sha256"] == (
        retained["p02_us03"]["target"]["audit_report_sha256"]
    )
    assert target["recovery_report_sha256"] == (
        retained["p02_us03"]["target"]["production_recovery_report_sha256"]
    )
    assert len(target["recovery"]["runs"]) == 29
    assert target["recovery_ownership"]["owner_linked_run_count"] == (
        EXPECTED_ACTUAL_CATASTROPHE_OWNER_LINKED_RUNS
    )
    assert target["recovery_ownership"]["ownerless_run_count"] == (
        EXPECTED_ACTUAL_CATASTROPHE_OWNERLESS_RUNS
    )
    assert (
        set(
            target["recovery_ownership"][
                "owner_linked_run_evidence_ids"
            ]
        )
        .isdisjoint(
            target["recovery_ownership"][
                "ownerless_run_evidence_ids"
            ]
        )
    )
    assert target["selective"]["known_span_count"] == 0
    assert healthy["audit"]["findings"] == []
    assert healthy["recovery"]["runs"] == []
    assert healthy["selective"]["known_span_count"] == 0


def test_actual_catastrophe_reconciliation_reentry_is_byte_stable() -> None:
    from app.services.text_reconciliation import reconcile_document_ir

    prepared = _prepare_actual_p02_us03_case(
        WORKSPACE,
        CATASTROPHE_CASE_ID,
    )
    first = reconcile_document_ir(prepared["p02_us03_ir"])
    before = first.model_dump_json()

    second = reconcile_document_ir(first)

    assert second is first
    assert second.model_dump_json() == before
    assert sum(
        concern.code
        in {
            "pdf_text_reconciliation_selected",
            "pdf_text_reconciliation_unresolved",
        }
        for concern in second.concerns
    ) == 29
    assert sum(
        concern.code == "pdf_text_reconciliation_complete"
        for concern in second.concerns
    ) == 1


def test_synthetic_controls_are_separate_bounded_groups() -> None:
    groups, expected = _synthetic_groups()

    assert len(groups) == 10
    assert sum(len(group["candidates"]) for group in groups) == 19
    assert len({group["group_id"] for group in groups}) == len(groups)
    assert list(expected.values()).count("selected") == 2
    assert list(expected.values()).count("unchanged") == 4
    assert list(expected.values()).count("unresolved") == 4
    assert all(
        candidate["provenance"]["source_sha256"] == "a" * 64
        for group in groups
        for candidate in group["candidates"]
    )


def test_rich_schema_coverage_rejects_nonfinite_decision_values() -> None:
    groups, _expected = _synthetic_groups()
    input_groups = {
        str(group["group_id"]): group for group in groups
    }
    report = _reconciliation_operation(groups)

    assert _report_coverage(report, input_groups)["schema_coverage"] == 1.0
    report["outcomes"][0]["decisions"][0][
        "candidate_target_overlap"
    ] = math.inf
    coverage = _report_coverage(report, input_groups)

    assert coverage["evidence_coverage"] < 1.0
    assert coverage["schema_coverage"] < 1.0


def test_rich_schema_coverage_rejects_duplicate_decision_ids() -> None:
    groups, _expected = _synthetic_groups()
    input_groups = {
        str(group["group_id"]): group for group in groups
    }
    report = _reconciliation_operation(groups)
    first_decision = report["outcomes"][0]["decisions"][0]
    report["outcomes"][0]["decisions"].append(dict(first_decision))

    coverage = _report_coverage(report, input_groups)

    assert coverage["evidence_coverage"] < 1.0
    assert coverage["schema_coverage"] < 1.0


def test_trace_collection_includes_ownerless_ir_diagnostics_once() -> None:
    projected_trace = {
        "group_id": "linked-group",
        "span_id": "linked-span",
        "owner_element_id": "linked-owner",
        "page_index": 1,
        "status": "selected",
        "reason_code": "deterministic_font_evidence",
        "selected_text": "linked",
        "selected_candidate_ids": ["linked-candidate"],
        "decisions": [{"candidate_id": "linked-candidate"}],
    }
    ownerless_trace = {
        "group_id": "ownerless-group",
        "span_id": "ownerless-span",
        "owner_element_id": "ownerless-element",
        "page_index": 1,
        "status": "selected",
        "reason_code": "deterministic_font_evidence",
        "selected_text": "ownerless",
        "selected_candidate_ids": ["ownerless-candidate"],
        "decisions": [{"candidate_id": "ownerless-candidate"}],
    }
    projection = {
        "pages": [
            {
                "items": [
                    {
                        "id": "linked-owner",
                        "text_reconciliation": [projected_trace],
                    }
                ]
            }
        ]
    }
    ir = SimpleNamespace(
        elements=[
            SimpleNamespace(
                id="linked-alternative",
                properties={"text_reconciliation": projected_trace},
            ),
            SimpleNamespace(
                id="ownerless-element",
                properties={"text_reconciliation": ownerless_trace},
            ),
        ]
    )

    traces = _projection_reconciliation_traces(projection, ir)

    assert [trace["group_id"] for trace in traces] == [
        "linked-group",
        "ownerless-group",
    ]
    assert traces[0]["decisions"] == projected_trace["decisions"]
    assert traces[0]["trace_location"] == "legacy_projection"
    assert traces[0]["trace_locations"] == [
        "legacy_projection",
        "ir_element",
    ]
    assert traces[1]["trace_location"] == "ir_element"
    assert traces[1]["trace_locations"] == ["ir_element"]


def test_reconciliation_metrics_cover_actual_and_bounded_control_inputs() -> (
    None
):
    metrics = _collect(WORKSPACE, warmups=0, samples=2)
    summary = metrics["summary"]

    assert metrics["record_kind"] == (
        "p02_us04_text_reconciliation_component_metrics"
    )
    assert metrics["method"]["warmups_per_scenario"] == 0
    assert metrics["method"]["samples_per_scenario"] == 2
    assert metrics["method"]["observed_paired_full_parser_percentile"] is False
    assert summary["actual_production_case_count"] == 15
    assert summary["exact_source_hash_count"] == 15
    assert summary["actual_catastrophe_case_count"] == 1
    assert summary["actual_catastrophe_recovery_run_count"] == 29
    assert summary["actual_catastrophe_owner_linked_run_count"] == (
        EXPECTED_ACTUAL_CATASTROPHE_OWNER_LINKED_RUNS
    )
    assert summary["actual_catastrophe_ownerless_run_count"] == (
        EXPECTED_ACTUAL_CATASTROPHE_OWNERLESS_RUNS
    )
    assert summary["actual_catastrophe_terminal_group_count"] == 29
    assert summary[
        "actual_catastrophe_linked_alternative_selected_count"
    ] == EXPECTED_ACTUAL_CATASTROPHE_UNCHANGED_RUNS
    assert summary["actual_catastrophe_legacy_projection_trace_count"] == (
        EXPECTED_ACTUAL_CATASTROPHE_OWNER_LINKED_RUNS
    )
    assert summary[
        "actual_catastrophe_ownerless_ir_only_trace_count"
    ] == EXPECTED_ACTUAL_CATASTROPHE_OWNERLESS_RUNS
    assert summary["actual_catastrophe_unchanged_count"] == (
        EXPECTED_ACTUAL_CATASTROPHE_UNCHANGED_RUNS
    )
    assert summary["actual_catastrophe_unresolved_count"] == (
        EXPECTED_ACTUAL_CATASTROPHE_UNRESOLVED_RUNS
    )
    assert summary[
        "actual_catastrophe_owner_linked_unresolved_count"
    ] == (
        EXPECTED_ACTUAL_CATASTROPHE_OWNER_LINKED_RUNS
        - EXPECTED_ACTUAL_CATASTROPHE_UNCHANGED_RUNS
    )
    assert summary[
        "actual_catastrophe_ownerless_unresolved_count"
    ] == EXPECTED_ACTUAL_CATASTROPHE_OWNERLESS_RUNS
    assert summary["actual_catastrophe_selected_ownerless_count"] == (
        EXPECTED_ACTUAL_CATASTROPHE_SELECTED_OWNERLESS_RUNS
    )
    assert summary[
        "actual_catastrophe_canonical_presentation_unchanged"
    ] is True
    assert summary[
        "actual_catastrophe_element_content_and_role_unchanged"
    ] is True
    assert summary["actual_catastrophe_target_sentence_exact"] is True
    assert summary[
        "retained_p02_us02_catastrophe_reviewed_region_count"
    ] == 24
    assert summary[
        "retained_p02_us02_catastrophe_reviewed_regions_exact"
    ] is True
    assert summary["healthy_control_count"] == 14
    assert summary["healthy_flag_on_exact_parity_count"] == 14
    assert summary["flag_off_exact_parity_count"] == 15
    assert summary["flag_on_round_trip_exact_count"] == 15
    assert summary["actual_reentry_exact_count"] == 15
    assert summary["authenticated_manifest_reentry_exact_count"] == 1
    assert (
        summary["actual_catastrophe_reentry_terminal_group_count"]
        == 29
    )
    assert summary["actual_catastrophe_reentry_manifest_count"] == 1
    assert summary["actual_evidence_identity_exact_count"] == 15
    assert summary["actual_evidence_core_unchanged_count"] == 15
    assert summary[
        "actual_element_content_and_role_unchanged_count"
    ] == 15
    assert summary[
        "actual_canonical_presentation_unchanged_count"
    ] == 15
    assert summary["deterministic_synthetic_group_count"] == 10
    assert summary["deterministic_synthetic_terminal_counts"] == {
        "selected": 2,
        "unchanged": 4,
        "unresolved": 4,
    }
    assert summary["actual_renderer_test_only_group_count"] == 4
    assert summary["actual_renderer_test_only_unresolved_count"] == 4
    assert summary["actual_production_ocr_win_fixture_available"] is False
    assert summary[
        "reviewed_typed_false_duplicate_candidate_registry_available"
    ] is False
    assert summary["reason_coverage"] == 1.0
    assert summary["evidence_coverage"] == 1.0
    assert summary["schema_coverage"] == 1.0
    assert summary["alternative_retention"] == 1.0
    assert summary["canonical_duplicate_count"] == 0
    assert summary["alternate_canonical_leak_count"] == 0
    assert summary["selection_surface_disagreement_count"] == 0
    assert summary["unretained_decision_evidence_id_count"] == 0
    assert summary["semantic_completion_count"] == 0
    assert summary["pre_post_custody_match"] is True
    assert summary["max_isolated_peak_rss_increment_bytes"] >= 0
    for key in (
        "actual_production_reconciliation_latency_ms",
        "actual_catastrophe_reconciliation_latency_ms",
        "healthy_reconciliation_latency_ms",
    ):
        _assert_ordered_distribution(summary[key])
    _assert_ordered_distribution(
        summary["healthy_reconciliation_additive_overhead_percent"]
    )

    ceiling = summary["combined_healthy_p95_ceiling_reference"]
    assert ceiling["observed_paired_full_parser_percentile"] is False
    assert ceiling["arithmetic_ceiling_percent"] <= 10.0
    assert ceiling["passes_target"] is True
    assert metrics["environment"]["compatible"] is True
    assert all(
        len(binding["sha256"]) == 64
        for binding in metrics["code_bindings"].values()
    )
    assert set(metrics["code_bindings"]) == {
        "text_reconciliation",
        "ir",
        "presentation",
        "metrics_runner",
    }
    assert metrics["code_bindings"]["presentation"]["path"] == (
        PRODUCTION_PRESENTATION_CODE
    )

    actual_cases = metrics["actual_production_inputs"]
    assert len(actual_cases) == 15
    assert all(
        case["actual_production_input"] is True
        and case["sample_count"] == 2
        and case["warmup_count"] == 0
        and case["structurally_deterministic"] is True
        and case["reconciliation_reentry"]["exact"] is True
        and case["reconciliation_reentry"]["same_object_on_reentry"]
        is True
        and case["peak_rss_after_bytes"] > 0
        and len(case["latency_samples_ms"]) == 2
        for case in actual_cases
    )
    catastrophe = next(
        case
        for case in actual_cases
        if case["case_id"] == CATASTROPHE_CASE_ID
    )
    assert catastrophe["result"]["trace_count"] == 29
    assert catastrophe["result"]["legacy_projection_trace_count"] == 26
    assert catastrophe["result"]["ir_only_trace_count"] == 3
    assert catastrophe["result"]["evidence_identity_exact"] is True
    assert catastrophe["result"]["evidence_core_unchanged"] is True
    assert catastrophe["result"][
        "element_content_and_role_unchanged"
    ] is True
    assert catastrophe["result"][
        "canonical_presentation_unchanged"
    ] is True
    assert set(
        catastrophe["result"][
            "font_recovery_trace_run_evidence_ids"
        ]
    ) == {
        *catastrophe["recovery_ownership"][
            "owner_linked_run_evidence_ids"
        ],
        *catastrophe["recovery_ownership"][
            "ownerless_run_evidence_ids"
        ],
    }
    assert len(
        {
            trace["group_id"]
            for trace in catastrophe["result"]["traces"]
        }
    ) == 29
    assert catastrophe["result"]["trace_coverage"][
        "evidence_coverage"
    ] == 1.0
    assert catastrophe["result"]["unretained_decision_evidence_ids"] == []
    assert catastrophe["result"]["selection_surface_disagreements"] == []
    assert {
        trace["status"] for trace in catastrophe["result"]["traces"]
    } == {"unchanged", "unresolved"}
    assert sum(
        trace["status"] == "unchanged"
        for trace in catastrophe["result"]["traces"]
    ) == EXPECTED_ACTUAL_CATASTROPHE_UNCHANGED_RUNS
    assert sum(
        trace["status"] == "unresolved"
        for trace in catastrophe["result"]["traces"]
    ) == EXPECTED_ACTUAL_CATASTROPHE_UNRESOLVED_RUNS
    assert all(
        trace["reason_code"] and trace["decisions"]
        for trace in catastrophe["result"]["traces"]
    )
    resolution = catastrophe["catastrophe_policy_resolution"]
    assert resolution["prose_run_text"] == (
        EXPECTED_ACTUAL_CATASTROPHE_PROSE_RUN_TEXT
    )
    assert resolution["prose_owner_element_id"] == (
        EXPECTED_ACTUAL_CATASTROPHE_PROSE_OWNER_ELEMENT_ID
    )
    assert resolution["prose_legacy_item_id"] == (
        EXPECTED_ACTUAL_CATASTROPHE_PROSE_LEGACY_ITEM_ID
    )
    assert set(resolution["chart_run_ids"]) == (
        EXPECTED_ACTUAL_CATASTROPHE_CHART_RUN_IDS
    )
    assert resolution["chart_owner_element_id"] == (
        EXPECTED_ACTUAL_CATASTROPHE_CHART_OWNER_ELEMENT_ID
    )
    assert resolution["chart_legacy_item_id"] == (
        EXPECTED_ACTUAL_CATASTROPHE_CHART_LEGACY_ITEM_ID
    )
    assert set(resolution["pinned_ownerless_run_ids"]) == (
        EXPECTED_ACTUAL_CATASTROPHE_OWNERLESS_RUN_IDS
    )
    assert set(resolution["already_primary_unchanged_run_ids"]) == set(
        EXPECTED_ACTUAL_CATASTROPHE_PROSE_RUN_TEXT
    )
    assert set(resolution["owner_linked_unresolved_run_ids"]) == (
        EXPECTED_ACTUAL_CATASTROPHE_CHART_RUN_IDS
    )
    assert set(resolution["ownerless_unresolved_run_ids"]) == (
        EXPECTED_ACTUAL_CATASTROPHE_OWNERLESS_RUN_IDS
    )
    assert resolution["selected_ownerless_run_ids"] == []
    traces_by_run = {
        run_id: trace
        for trace in catastrophe["result"]["traces"]
        if (run_id := _font_run_id_from_trace(trace)) is not None
    }
    retained_recovery_runs = {
        str(run["evidence_id"]): run
        for run in _prepare_actual_p02_us03_case(
            WORKSPACE,
            CATASTROPHE_CASE_ID,
        )["recovery"]["runs"]
    }
    assert set(traces_by_run) == {
        *EXPECTED_ACTUAL_CATASTROPHE_PROSE_RUN_TEXT,
        *EXPECTED_ACTUAL_CATASTROPHE_CHART_RUN_IDS,
        *EXPECTED_ACTUAL_CATASTROPHE_OWNERLESS_RUN_IDS,
    }
    assert set(retained_recovery_runs) == set(traces_by_run)
    for run_id, trace in traces_by_run.items():
        decisions = {
            decision["candidate_id"]: decision
            for decision in trace["decisions"]
        }
        assert decisions[f"font:{run_id}"]["text"] == (
            retained_recovery_runs[run_id]["recovered_text"]
        )
        assert decisions[f"native:{run_id}"]["text"] == (
            retained_recovery_runs[run_id]["original_text"]
        )
    for run_id in EXPECTED_ACTUAL_CATASTROPHE_PROSE_RUN_TEXT:
        trace = traces_by_run[run_id]
        assert trace["owner_element_id"] == (
            EXPECTED_ACTUAL_CATASTROPHE_PROSE_OWNER_ELEMENT_ID
        )
        assert {
            source["item_id"]
            for source in trace["trace_sources"]
            if source["trace_location"] == "legacy_projection"
        } == {EXPECTED_ACTUAL_CATASTROPHE_PROSE_LEGACY_ITEM_ID}
    for run_id in EXPECTED_ACTUAL_CATASTROPHE_CHART_RUN_IDS:
        trace = traces_by_run[run_id]
        assert trace["owner_element_id"] == (
            EXPECTED_ACTUAL_CATASTROPHE_CHART_OWNER_ELEMENT_ID
        )
        assert {
            source["item_id"]
            for source in trace["trace_sources"]
            if source["trace_location"] == "legacy_projection"
        } == {EXPECTED_ACTUAL_CATASTROPHE_CHART_LEGACY_ITEM_ID}
    for run_id in EXPECTED_ACTUAL_CATASTROPHE_OWNERLESS_RUN_IDS:
        trace = traces_by_run[run_id]
        assert trace["trace_locations"] == ["ir_element"]
        assert all(
            source["trace_location"] != "legacy_projection"
            for source in trace["trace_sources"]
        )

    healthy = [
        case for case in actual_cases if case["case_id"] != CATASTROPHE_CASE_ID
    ]
    assert len(healthy) == 14
    assert all(
        case["result"]["trace_count"] == 0
        and case["result"]["ir_sha256"]
        == case["input_ir_fingerprint"]["sha256"]
        for case in healthy
    )

    actual_renderer = metrics["actual_renderer_test_only_upstream"]
    assert actual_renderer["actual_production_upstream_input"] is False
    assert actual_renderer["actual_pdfium_render"] is True
    assert actual_renderer["actual_local_tesseract"] is True
    assert actual_renderer["upstream_variant_kind"] == (
        "deterministic_test_only_recovery_refusal"
    )
    assert [
        row["audit_run_index"] for row in actual_renderer["input_trace"]
    ] == [1, 2, 3, 4]
    assert actual_renderer["reciprocal_overlap_gate_count"] == 4
    assert len(actual_renderer["outcomes"]) == 4
    assert all(
        outcome["status"] == "unresolved"
        for outcome in actual_renderer["outcomes"]
    )

    synthetic = metrics["deterministic_synthetic_controls"]
    assert synthetic["actual_production_input"] is False
    assert synthetic["group_count"] == 10
    assert synthetic["candidate_count"] == 19
    assert synthetic["observed_terminal_counts"] == {
        "selected": 2,
        "unchanged": 4,
        "unresolved": 4,
    }
    assert synthetic["coverage"]["evidence_coverage"] == 1.0
    assert synthetic["coverage"]["schema_coverage"] == 1.0
    assert {
        concern["group_id"] for concern in synthetic["concerns"]
    } == {
        "synthetic-03-dependent_bad_layer",
        "synthetic-04-low_margin",
        "synthetic-05-partial_overlap",
        "synthetic-06-mixed_script",
    }
