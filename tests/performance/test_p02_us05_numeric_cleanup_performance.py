from __future__ import annotations

import math
from pathlib import Path

import pytest

from tests.benchmarks.numeric_cleanup_metrics import (
    EXPECTED_NUMERIC_CLEANUP_POLICY_SHA256,
    EXPECTED_RETAINED_CATASTROPHE_OUTPUT_SHA256,
    EXPECTED_RETAINED_P02_US04_METRICS_SHA256,
    HEALTHY_OVERHEAD_TARGET_PERCENT,
    NUMERIC_CLEANUP_POLICY,
    RETAINED_CATASTROPHE_OUTPUT,
    RETAINED_P02_US04_METRICS,
    _collect,
    _input_identities,
    _measure_deterministic,
    _nearest_rank,
    bound_cases,
    digest_cases,
    numeric_control_cases,
    retained_catastrophe_binding,
)


WORKSPACE = Path(__file__).resolve().parents[2]


def _assert_distribution(distribution: dict[str, float]) -> None:
    assert distribution["p50"] >= 0
    assert (
        distribution["p50"]
        <= distribution["p95"]
        <= distribution["max"]
    )


def test_numeric_cleanup_metric_percentiles_use_nearest_rank() -> None:
    values = [5.0, 1.0, 4.0, 2.0, 3.0]

    assert _nearest_rank(values, 0.50) == 3.0
    assert _nearest_rank(values, 0.95) == 5.0
    with pytest.raises(ValueError, match="at least one"):
        _nearest_rank([], 0.95)
    with pytest.raises(ValueError, match="percentile"):
        _nearest_rank(values, 0.0)
    with pytest.raises(ValueError, match="finite"):
        _nearest_rank([math.inf], 0.95)


def test_numeric_cleanup_measurement_rejects_structural_drift() -> None:
    counter = 0

    def changing() -> dict[str, int]:
        nonlocal counter
        counter += 1
        return {"counter": counter}

    with pytest.raises(RuntimeError, match="structural drift"):
        _measure_deterministic(changing, warmups=0, samples=2)

    payload, durations, rss = _measure_deterministic(
        lambda: {"status": "stable"},
        warmups=1,
        samples=2,
    )
    assert payload == {"status": "stable"}
    assert len(durations) == 2
    assert all(duration >= 0 for duration in durations)
    assert rss >= 0


def test_retained_catastrophe_metric_binding_is_hash_and_geometry_exact() -> (
    None
):
    binding = retained_catastrophe_binding(WORKSPACE)

    assert binding["artifact"]["sha256"] == (
        EXPECTED_RETAINED_CATASTROPHE_OUTPUT_SHA256
    )
    assert binding["matching_diagnostic_surface_count"] == 2
    assert binding["word_count"] == 12
    assert binding["bbox"] == {
        "x": 125.021,
        "y": 562.51,
        "w": 417.2,
        "h": 4.6,
        "width": 417.2,
        "height": 4.6,
        "unit": "pt",
    }


def test_metric_fixture_matrix_covers_all_policy_classes() -> None:
    digests = digest_cases()
    controls = numeric_control_cases()
    bounds = bound_cases()

    assert len(digests) == 35
    assert {
        (str(case["label"]).upper(), int(case["length"]))
        for case in digests
        if str(case["label"]).upper()
        in {"HASH", "CHECKSUM", "DIGEST", "FINGERPRINT"}
    } == {
        (label, length)
        for label in ("HASH", "CHECKSUM", "DIGEST", "FINGERPRINT")
        for length in (32, 40, 56, 64, 96, 128)
    }
    assert {
        int(case["length"])
        for case in digests
        if str(case["label"]).upper().startswith(("MD5", "SHA"))
    } == {32, 40, 56, 64, 96, 128}
    assert {
        case["case_id"] for case in controls
    } >= {
        "iso_date_and_time",
        "money",
        "percentages",
        "page_numbers",
        "ordinary_numeric_list",
        "decimal_digest_length_after_hash_label",
        "bare_known_length_hex",
        "generic_id",
        "lowercase_candidate",
        "unicode_confusable_candidate",
        "mixed_ordinary_alphanumeric",
    }
    assert {case["case_id"] for case in bounds} == {
        "line_character_limit",
        "line_token_limit",
        "fragment_count_limit",
        "candidate_character_limit",
    }


def test_metric_input_custody_binds_production_policy_tests_and_history() -> (
    None
):
    identities = _input_identities(WORKSPACE)

    assert identities[RETAINED_CATASTROPHE_OUTPUT]["sha256"] == (
        EXPECTED_RETAINED_CATASTROPHE_OUTPUT_SHA256
    )
    assert identities[RETAINED_P02_US04_METRICS]["sha256"] == (
        EXPECTED_RETAINED_P02_US04_METRICS_SHA256
    )
    assert identities[NUMERIC_CLEANUP_POLICY]["sha256"] == (
        EXPECTED_NUMERIC_CLEANUP_POLICY_SHA256
    )
    assert all(
        len(identity["sha256"]) == 64 and identity["size_bytes"] > 0
        for identity in identities.values()
    )
    assert {
        "app/services/ocr.py",
        "app/services/selective_span_ocr.py",
        "app/services/pipeline.py",
        "app/config.py",
        ".env.example",
        "README.md",
        (
            "tests/regression/phase_02/"
            "test_p02_us05_numeric_cleanup_adversarial_review.py"
        ),
    }.issubset(identities)


def test_numeric_cleanup_metrics_cover_acceptance_and_resource_bounds() -> None:
    result = _collect(WORKSPACE, warmups=1, samples=3)
    metrics = result["metrics"]

    assert result["schema_version"] == "1.0"
    assert result["record_kind"] == (
        "p02_us05_numeric_cleanup_component_metrics"
    )
    assert result["custody"]["pre_post_input_identity_match"] is True
    assert metrics["observed_year_token_count"] == 12
    assert metrics["observed_years_exact"] is True
    assert metrics["observed_48_digit_false_join_count"] == 0
    assert metrics["flag_off_observed_legacy_exact"] is True
    assert metrics["sequential_year_token_count"] == 12
    assert metrics["sequential_years_exact"] is True
    assert metrics["flag_off_sequential_legacy_exact"] is True
    assert metrics["approved_digest_case_count"] == 35
    assert metrics["approved_digest_join_count"] == 35
    assert metrics[
        "approved_digest_flag_off_compatibility_count"
    ] == 35
    assert metrics["numeric_control_exact_count"] == (
        metrics["numeric_control_case_count"]
    )
    assert (
        metrics["bound_fail_closed_count"]
        == metrics["bound_case_count"]
        == 4
    )
    assert metrics["semantic_output_size_bytes"] > 0
    assert len(metrics["semantic_output_sha256"]) == 64
    assert metrics["hosted_model_request_count"] == 0
    assert metrics["hosted_model_token_count"] == 0
    assert metrics["hosted_model_cost_usd"] == 0.0

    for key in (
        "target_cleanup_latency_ms",
        "approved_digest_cleanup_latency_ms",
        "healthy_numeric_cleanup_latency_ms",
        "resource_bound_cleanup_latency_ms",
    ):
        _assert_distribution(metrics[key])

    assert metrics["resource_bound_cleanup_latency_ms"]["p95"] < 250.0
    assert metrics["max_isolated_peak_rss_increment_bytes"] < 64 * 1024 * 1024
    ceiling = metrics["combined_healthy_p95_ceiling_reference"]
    assert ceiling["observed_paired_full_parser_percentile"] is False
    assert ceiling["target_percent"] == HEALTHY_OVERHEAD_TARGET_PERCENT
    assert ceiling["arithmetic_ceiling_percent"] <= (
        HEALTHY_OVERHEAD_TARGET_PERCENT
    )
    assert ceiling["passes_target"] is True


def test_metric_semantic_results_are_deterministic_across_collections() -> None:
    first = _collect(WORKSPACE, warmups=0, samples=1)
    second = _collect(WORKSPACE, warmups=0, samples=1)

    assert first["semantic_results"] == second["semantic_results"]
    assert first["metrics"]["semantic_output_sha256"] == (
        second["metrics"]["semantic_output_sha256"]
    )
    assert first["metrics"]["semantic_output_size_bytes"] == (
        second["metrics"]["semantic_output_size_bytes"]
    )
    assert first["run_inputs"] == second["run_inputs"]
