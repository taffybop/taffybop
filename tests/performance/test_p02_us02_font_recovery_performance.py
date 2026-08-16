from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.benchmarks.font_recovery_metrics import (
    _collect,
    _nearest_rank,
)


WORKSPACE = Path(__file__).resolve().parents[2]
RETAINED_METRICS = (
    WORKSPACE
    / "tracker"
    / "phase-02-text-integrity"
    / "evidence"
    / "P02-US02-font-recovery-metrics.json"
)


def test_font_recovery_metric_percentiles_use_nearest_rank() -> None:
    values = [5.0, 1.0, 4.0, 2.0, 3.0]

    assert _nearest_rank(values, 0.50) == 3.0
    assert _nearest_rank(values, 0.95) == 5.0
    with pytest.raises(ValueError, match="at least one"):
        _nearest_rank([], 0.95)
    with pytest.raises(ValueError, match="percentile"):
        _nearest_rank(values, 0.0)


def test_recovery_metrics_cover_real_corpus_and_stay_within_budget() -> None:
    metrics = _collect(WORKSPACE, warmups=1, samples=2)
    summary = metrics["summary"]

    assert summary["case_count"] == 15
    assert summary["deterministic_case_count"] == 15
    assert summary["healthy_case_count"] == 14
    assert summary["healthy_short_circuit_count"] == 14
    assert summary["healthy_rewrite_count"] == 0
    assert summary["catastrophe_font_count"] == 2
    assert summary["catastrophe_run_count"] == 29
    assert summary["catastrophe_glyph_count"] == 150
    assert summary["catastrophe_grounding_rate"] == 1.0
    assert summary["catastrophe_target_sentence_exact"] is True
    assert summary["catastrophe_reviewed_regions_exact"] is True
    assert summary["max_isolated_peak_rss_increment_bytes"] >= 0

    ceiling = summary["combined_healthy_p95_ceiling_reference"]
    assert ceiling["observed_paired_full_parser_percentile"] is False
    assert ceiling["arithmetic_ceiling_percent"] <= 10.0
    assert ceiling["passes_target"] is True

    catastrophe = next(
        case
        for case in metrics["cases"]
        if case["case_id"] == "catastrophe-recap"
    )
    assert len(catastrophe["per_font_latency"]) == 2
    assert all(
        font["fonts_recovered"] == 1
        and font["run_count"] > 0
        and font["recovered_glyph_count"] > 0
        and font["deterministic"] is True
        for font in catastrophe["per_font_latency"]
    )


def test_retained_recovery_metrics_preserve_complete_glyph_evidence() -> None:
    metrics = json.loads(RETAINED_METRICS.read_text(encoding="utf-8"))

    assert metrics["record_kind"] == (
        "p02_us02_font_recovery_component_metrics"
    )
    assert metrics["method"]["warmups_per_case"] == 2
    assert metrics["method"]["samples_per_case"] == 10
    assert metrics["summary"]["case_count"] == 15
    assert metrics["summary"]["deterministic_case_count"] == 15
    assert metrics["summary"]["healthy_short_circuit_count"] == 14
    assert metrics["summary"]["healthy_rewrite_count"] == 0

    catastrophe = next(
        case
        for case in metrics["cases"]
        if case["case_id"] == "catastrophe-recap"
    )
    correctness = catastrophe["correctness"]
    assert len(correctness["per_run"]) == 29
    assert len(correctness["per_glyph"]) == 150
    assert len({row["evidence_id"] for row in correctness["per_glyph"]}) == 150
    assert all(row["grounded"] for row in correctness["per_glyph"])
    assert correctness["reviewed_region_count"] == 24
    assert correctness["reviewed_region_exact_match_count"] == 24
    assert correctness["target_sentence_exact"] is True

    healthy = [
        case
        for case in metrics["cases"]
        if case["case_id"] != "catastrophe-recap"
    ]
    assert len(healthy) == 14
    assert all(
        case["source_sha256"]
        and case["short_circuited"]
        and case["rewrite_count"] == 0
        and case["deterministic"]
        for case in healthy
    )
