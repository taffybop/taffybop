from __future__ import annotations

import math
from pathlib import Path

import pytest

from tests.benchmarks.selective_span_ocr_metrics import (
    EXPECTED_ENG_TRAINEDDATA_SHA256,
    EXPECTED_ENG_TRAINEDDATA_SIZE_BYTES,
    EXPECTED_TESSERACT_VERSION,
    _candidate_evidence_rows,
    _collect,
    _conservative_healthy_p95_ceiling,
    _measure_deterministic,
    _nearest_rank,
    _reference_tesseract_binding,
    _retained_overhead_inputs,
)


WORKSPACE = Path(__file__).resolve().parents[2]


def test_selective_span_metric_percentiles_use_nearest_rank() -> None:
    values = [5.0, 1.0, 4.0, 2.0, 3.0]

    assert _nearest_rank(values, 0.50) == 3.0
    assert _nearest_rank(values, 0.95) == 5.0
    with pytest.raises(ValueError, match="at least one"):
        _nearest_rank([], 0.95)
    with pytest.raises(ValueError, match="percentile"):
        _nearest_rank(values, 0.0)
    with pytest.raises(ValueError, match="finite"):
        _nearest_rank([math.inf], 0.95)


def test_retained_us01_us02_metrics_form_a_hash_bound_ceiling() -> None:
    retained = _retained_overhead_inputs(WORKSPACE)
    ceiling = _conservative_healthy_p95_ceiling(WORKSPACE, 0.25)

    assert retained["audit_p95_percent"] > 0
    assert retained["recovery_p95_percent"] >= 0
    assert len(retained["p02_us01_metrics"]["sha256"]) == 64
    assert len(retained["p02_us02_metrics"]["sha256"]) == 64
    assert ceiling["arithmetic_ceiling_percent"] == pytest.approx(
        retained["audit_p95_percent"]
        + retained["recovery_p95_percent"]
        + 0.25
    )
    assert ceiling["observed_paired_full_parser_percentile"] is False
    assert ceiling["passes_target"] is True


def test_component_measurement_rejects_nondeterministic_payloads() -> None:
    counter = 0

    def changing() -> dict[str, int]:
        nonlocal counter
        counter += 1
        return {"counter": counter}

    with pytest.raises(RuntimeError, match="measured samples"):
        _measure_deterministic(changing, warmups=0, samples=2)

    payload, durations = _measure_deterministic(
        lambda: {"terminal_status": "no_targets"},
        warmups=1,
        samples=2,
    )
    assert payload == {"terminal_status": "no_targets"}
    assert len(durations) == 2
    assert all(duration >= 0 for duration in durations)


def test_real_ocr_environment_matches_the_accepted_policy_binding() -> None:
    binding = _reference_tesseract_binding()

    assert binding["version"] == EXPECTED_TESSERACT_VERSION
    assert (
        binding["traineddata_size_bytes"]
        == EXPECTED_ENG_TRAINEDDATA_SIZE_BYTES
    )
    assert (
        binding["traineddata_sha256"]
        == EXPECTED_ENG_TRAINEDDATA_SHA256
    )
    assert binding["language"] == "eng"
    assert binding["traineddata_path"].endswith("/eng.traineddata")
    assert binding["policy_binding_passed"] is True


def test_selective_span_ocr_metrics_cover_targets_neighbors_and_controls() -> (
    None
):
    metrics = _collect(WORKSPACE, warmups=0, samples=2)
    summary = metrics["summary"]

    assert metrics["record_kind"] == (
        "p02_us03_selective_span_ocr_component_metrics"
    )
    assert summary["case_count"] == 15
    assert summary["exact_source_hash_count"] == 15
    assert summary["deterministic_scenario_count"] == 16
    assert summary["real_production_scenario_count"] == 1
    assert summary["real_production_warmup_count"] == 0
    assert summary["real_production_sample_count"] == 2
    assert summary["real_production_structurally_deterministic"] is True
    assert summary["real_production_measured_target_execution_count"] == 8
    assert summary["unresolved_target_opportunity_count"] == 8
    assert summary["unresolved_target_terminal_outcome_count"] == 8
    assert summary["unresolved_target_terminal_coverage"] == 1.0
    assert summary["healthy_neighbor_span_count"] == 25
    assert summary["healthy_neighbor_render_count"] == 0
    assert summary["healthy_control_count"] == 14
    assert summary["healthy_control_render_call_count"] == 0
    assert summary["healthy_control_rendered_span_count"] == 0
    assert summary["healthy_control_rendered_pixel_count"] == 0
    assert summary["healthy_control_rendered_area_points2"] == 0
    assert summary["candidate_count"] == 4
    assert summary["candidate_evidence_complete_count"] == 4
    assert summary["candidate_evidence_completeness"] == 1.0
    assert summary["unique_candidate_evidence_count"] == 4
    assert summary["token_count"] == 4
    assert summary["unique_token_evidence_count"] == 4
    assert summary["mocked_selective_rendered_span_count"] == 4
    assert summary["mocked_selective_rendered_area_points2"] > 0
    assert 0 < summary["mocked_selective_rendered_page_area_ratio"] <= 0.05
    assert summary["mocked_selective_rendered_pixel_count"] > 0
    assert summary["maximum_selective_crop_pixel_count"] <= 4_000_000
    assert summary["real_production_target_opportunity_count"] == 4
    assert summary["real_production_terminal_outcome_count"] == 4
    assert summary["real_production_terminal_coverage"] == 1.0
    assert summary["real_production_healthy_neighbor_render_count"] == 0
    assert summary["real_production_candidate_count"] == 4
    assert (
        summary["real_production_candidate_evidence_complete_count"] == 4
    )
    assert summary["real_production_token_count"] == 4
    assert summary["real_production_unique_candidate_evidence_count"] == 4
    assert summary["real_production_unique_token_evidence_count"] == 4
    assert summary["real_production_rendered_span_count"] == 4
    assert summary["real_production_rendered_area_points2"] > 0
    assert (
        0
        < summary["real_production_rendered_page_area_ratio"]
        <= 0.05
    )
    assert summary["real_production_rendered_pixel_count"] > 0
    assert (
        summary["real_production_maximum_crop_pixel_count"] <= 4_000_000
    )
    assert summary["real_production_latency_ms"]["p50"] > 0
    assert (
        summary["real_production_latency_ms"]["p50"]
        <= summary["real_production_latency_ms"]["p95"]
        <= summary["real_production_latency_ms"]["max"]
    )
    assert summary["real_production_report_elapsed_ms"]["p50"] > 0
    assert (
        summary["real_production_report_elapsed_ms"]["p50"]
        <= summary["real_production_report_elapsed_ms"]["p95"]
        <= summary["real_production_report_elapsed_ms"]["max"]
    )
    assert summary["real_production_observed_peak_rss_bytes"] > 0
    assert (
        summary["real_production_observed_peak_rss_increment_bytes"] >= 0
    )
    assert (
        summary["accepted_tesseract_version"]
        == EXPECTED_TESSERACT_VERSION
    )
    assert (
        summary["accepted_eng_traineddata_size_bytes"]
        == EXPECTED_ENG_TRAINEDDATA_SIZE_BYTES
    )
    assert (
        summary["accepted_eng_traineddata_sha256"]
        == EXPECTED_ENG_TRAINEDDATA_SHA256
    )
    assert summary["broad_page_render_count"] == 0
    assert summary["document_model_invocation_count"] == 0
    assert summary["max_isolated_peak_rss_increment_bytes"] >= 0

    ceiling = summary["combined_healthy_p95_ceiling_reference"]
    assert ceiling["observed_paired_full_parser_percentile"] is False
    assert ceiling["arithmetic_ceiling_percent"] <= 10.0
    assert ceiling["passes_target"] is True

    target = metrics["target"]
    success = target["mocked_selective_execution"]
    soft_failure = target["ocr_unavailable_soft_failure"]
    real_production = target["real_production_path"]
    real_worker_binding = target["real_production_worker_binding"]
    assert success["report"]["status"] == "complete"
    assert success["report"]["rendered_span_count"] == 4
    assert soft_failure["report"]["status"] == "partial"
    assert soft_failure["report"]["rendered_span_count"] == 0
    assert {
        outcome["reason_code"]
        for outcome in soft_failure["report"]["outcomes"]
    } == {"selective_ocr_unavailable"}
    assert all(
        row["complete"]
        for row in _candidate_evidence_rows(success["report"])
    )
    assert real_production["measurement_kind"] == (
        "isolated_real_pdfium_tesseract_production_path"
    )
    assert real_production["warmup_count"] == 0
    assert real_production["sample_count"] == 2
    assert real_production["structurally_deterministic"] is True
    assert len(real_production["structural_report_sha256"]) == 64
    assert len(real_production["latency_samples_ms"]) == 2
    assert len(real_production["report_elapsed_samples_ms"]) == 2
    assert real_production["latency_ms"]["p50"] == min(
        real_production["latency_samples_ms"]
    )
    assert real_production["latency_ms"]["p95"] == max(
        real_production["latency_samples_ms"]
    )
    assert real_production["report_elapsed_ms"]["p50"] == min(
        real_production["report_elapsed_samples_ms"]
    )
    assert real_production["report_elapsed_ms"]["p95"] == max(
        real_production["report_elapsed_samples_ms"]
    )
    assert real_production["observed_peak_rss_bytes"] > 0
    assert real_production["mocked"] is False
    assert real_production["actual_pdfium_render"] is True
    assert real_production["actual_local_tesseract"] is True
    assert real_production["candidate_selection_invoked"] is False
    assert real_worker_binding["case_id"] == target["case_id"]
    assert (
        real_worker_binding["source_sha256"] == target["source_sha256"]
    )
    assert (
        real_worker_binding["audit_report_sha256"]
        == target["audit_report_sha256"]
    )
    assert (
        real_worker_binding["benchmark_recovery_variant_sha256"]
        == target["benchmark_recovery_variant_sha256"]
    )
    assert real_production["report"]["status"] == "complete"
    assert real_production["report"]["rendered_span_count"] == 4
    assert len(real_production["outcome_evidence"]) == 4
    assert len(real_production["candidate_evidence"]) == 4
    assert all(
        row["complete"] for row in real_production["candidate_evidence"]
    )
    assert all(
        outcome["terminal_status"] == "candidate"
        and outcome["terminal_reason_code"] is None
        and outcome["candidate_evidence_ids"]
        and outcome["token_evidence_ids"]
        and outcome["attempt"]["status"] == "completed"
        and outcome["attempt"]["transform_valid"] is True
        and outcome["cost"]["requested_dpi"] == 360.0
        and outcome["cost"]["actual_dpi_x"] == pytest.approx(360.0)
        and outcome["cost"]["actual_dpi_y"] == pytest.approx(360.0)
        and outcome["cost"]["pixel_count"]
        == (
            outcome["cost"]["pixel_width"]
            * outcome["cost"]["pixel_height"]
        )
        and len(outcome["cost"]["crop_to_page_transform"]) == 6
        and len(outcome["cost"]["page_to_crop_transform"]) == 6
        and outcome["cost"]["passes_attempted"]
        == ["standard", "sparse"]
        and outcome["cost"]["passes_completed"]
        == ["standard", "sparse"]
        and outcome["cost"]["engine_version"] == "tesseract 5.5.3"
        and outcome["cost"]["languages"] == ["eng"]
        for outcome in real_production["outcome_evidence"]
    )
    binding = real_production["tesseract_binding"]
    assert binding["version"] == EXPECTED_TESSERACT_VERSION
    assert (
        binding["traineddata_size_bytes"]
        == EXPECTED_ENG_TRAINEDDATA_SIZE_BYTES
    )
    assert (
        binding["traineddata_sha256"]
        == EXPECTED_ENG_TRAINEDDATA_SHA256
    )

    assert len(metrics["healthy_controls"]) == 14
    assert all(
        len(control["source_sha256"]) == 64
        and control["report"]["known_span_count"] == 0
        and control["instrumentation"]["render_call_count"] == 0
        and control["deterministic"]
        for control in metrics["healthy_controls"]
    )
