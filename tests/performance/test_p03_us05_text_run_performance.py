"""Bounded performance and metrics-harness checks for P03-US05."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from tests.benchmarks import text_run_semantics_metrics as metrics


def test_fixed_inputs_settings_and_local_only_policy_are_exact() -> None:
    custody = metrics._source_custody(metrics.WORKSPACE)

    assert set(custody) == {
        "purchase-agreement",
        "postal-10k",
        "finance-10k",
        "uber-earnings",
    }
    assert all(record["exact_match"] for record in custody.values())
    assert metrics.M0_REFERENCE == {
        "label": "M0_reference_context_not_paired_predecessor",
        "wall_seconds": 6.18,
        "peak_rss_mib": 1_401.0,
    }
    assert metrics.HOSTED_USAGE == {
        "hosted_requests": 0,
        "hosted_tokens": 0,
        "hosted_cost_usd": 0,
    }
    assert metrics._settings_delta() == {
        "changed_fields": ["layout_text_run_semantics_enabled"],
        "flag_off": {"layout_text_run_semantics_enabled": False},
        "flag_on": {"layout_text_run_semantics_enabled": True},
        "accepted_predecessor_flags_enabled": True,
    }
    disabled = metrics._settings(False)
    enabled = metrics._settings(True)
    assert disabled.layout_table_captions_enabled is True
    assert disabled.layout_visual_relationships_enabled is True
    assert disabled.layout_source_notes_enabled is True
    assert disabled.layout_relationship_order_enabled is True
    assert disabled.layout_text_run_semantics_enabled is False
    assert enabled.layout_text_run_semantics_enabled is True


def test_paired_gate_uses_current_predecessor_and_dual_ceilings() -> None:
    off = [
        {
            "wall_seconds": 10.0,
            "peak_rss_bytes": 1_000,
        }
        for _ in range(5)
    ]
    on = [
        {"wall_seconds": 9.0, "peak_rss_bytes": 900},
        {"wall_seconds": 9.0, "peak_rss_bytes": 900},
        {"wall_seconds": 9.0, "peak_rss_bytes": 900},
        {"wall_seconds": 9.0, "peak_rss_bytes": 900},
        {"wall_seconds": 10.7, "peak_rss_bytes": 1_100},
    ]

    summary = metrics._paired_performance_summary(off, on)

    assert summary["pair_count"] == 5
    assert summary["quantile_method"] == "empirical_p95_inclusive"
    assert summary["gate_value"] == (
        "p95_of_clipped_nonnegative_paired_overhead"
    )
    assert summary["paired_signed_wall_seconds_deltas"] == [
        -1.0,
        -1.0,
        -1.0,
        -1.0,
        0.7,
    ]
    assert summary["paired_nonnegative_overhead_seconds"] == [
        0.0,
        0.0,
        0.0,
        0.0,
        0.7,
    ]
    assert summary["p95_signed_delta_seconds"] == pytest.approx(0.36)
    assert summary["p95_nonnegative_overhead_seconds"] == pytest.approx(
        0.56
    )
    assert summary["current_paired_predecessor_p95_seconds"] == 10.0
    assert summary["five_percent_ceiling_seconds"] == 0.5
    assert summary["absolute_ceiling_seconds"] == 0.309
    assert summary["effective_ceiling_seconds"] == 0.309
    assert summary["within_five_percent_ceiling"] is False
    assert summary["within_absolute_ceiling"] is False
    assert summary["within_both_ceilings"] is False
    assert summary["m0_reference"] == metrics.M0_REFERENCE
    assert [metrics._paired_states(index) for index in range(5)] == [
        (False, True),
        (True, False),
        (False, True),
        (True, False),
        (False, True),
    ]


def test_artifact_semantic_digest_excludes_only_run_metadata() -> None:
    first = {
        "story": "P03-US05",
        "generated_at": "2026-07-31T00:00:00+00:00",
        "semantic_sha256": "first",
        "aggregate": {"deleted_logical_group_count": 6},
    }
    second = {
        **first,
        "generated_at": "2026-08-01T00:00:00+00:00",
        "semantic_sha256": "second",
    }

    assert metrics._canonical_json(
        metrics._artifact_semantic_payload(first)
    ) == metrics._canonical_json(
        metrics._artifact_semantic_payload(second)
    )
    changed = {
        **second,
        "aggregate": {"deleted_logical_group_count": 5},
    }
    assert metrics._canonical_json(
        metrics._artifact_semantic_payload(first)
    ) != metrics._canonical_json(
        metrics._artifact_semantic_payload(changed)
    )


def test_warm_source_extraction_meets_latency_memory_and_size_gates() -> None:
    measured = metrics.generate_extraction_metrics()

    assert measured["warmup_count"] == 2
    assert measured["sample_count"] == 20
    assert len(measured["samples_seconds"]) == 20
    assert measured["quantile_method"] == "empirical_p95_inclusive"
    assert measured["timing_tracemalloc_enabled"] is False
    assert measured["allocation_measured_in_separate_call"] is True
    assert measured["gc_collection_outside_timed_interval"] is True
    assert 0 < measured["p50_seconds"] <= measured["p95_seconds"]
    assert measured["p95_seconds"] <= measured["max_seconds"]
    assert (
        measured["p95_seconds"]
        <= measured["p95_ceiling_seconds"]
        == 0.150
    )
    assert measured["within_p95_ceiling"] is True
    assert (
        measured["peak_allocated_bytes"]
        < measured["peak_allocation_ceiling_bytes"]
        == 64 * 1024 * 1024
    )
    assert measured["within_peak_allocation_ceiling"] is True
    assert (
        measured["report_size_bytes"]
        <= measured["report_size_ceiling_bytes"]
        == 8 * 1024 * 1024
    )
    assert measured["within_report_size_ceiling"] is True
    assert measured["usable"] is True
    assert measured["semantic_deterministic"] is True
    assert measured["character_count"] == 3_338
    assert measured["candidate_rule_count"] == 13
    assert measured["retained_rule_count"] == 13
    assert measured["run_count"] > 0
    assert {
        key: measured[key] for key in metrics.HOSTED_USAGE
    } == metrics.HOSTED_USAGE


def test_warm_association_projection_meets_latency_memory_and_size_gates(
) -> None:
    measured = metrics.generate_projection_metrics()

    assert measured["warmup_count"] == 2
    assert measured["sample_count"] == 20
    assert len(measured["samples_seconds"]) == 20
    assert measured["quantile_method"] == "empirical_p95_inclusive"
    assert measured["timing_tracemalloc_enabled"] is False
    assert measured["allocation_measured_in_separate_call"] is True
    assert measured["gc_collection_outside_timed_interval"] is True
    assert 0 < measured["p50_seconds"] <= measured["p95_seconds"]
    assert measured["p95_seconds"] <= measured["max_seconds"]
    assert (
        measured["p95_seconds"]
        <= measured["p95_ceiling_seconds"]
        == 0.050
    )
    assert measured["within_p95_ceiling"] is True
    assert (
        measured["peak_allocated_bytes"]
        < measured["peak_allocation_ceiling_bytes"]
        == 32 * 1024 * 1024
    )
    assert measured["within_peak_allocation_ceiling"] is True
    assert (
        measured["projected_ir_size_bytes"]
        <= measured["projected_ir_size_ceiling_bytes"]
        == 8 * 1024 * 1024
    )
    assert measured["within_projected_ir_size_ceiling"] is True
    assert measured["run_count"] > 0
    assert measured["rule_count"] == 13
    assert measured["semantic_deterministic"] is True
    assert measured["predecessor_unmodified"] is True
    assert measured["repeated_projection_idempotent"] is True
    assert {
        key: measured[key] for key in metrics.HOSTED_USAGE
    } == metrics.HOSTED_USAGE


def test_exact_maximum_completes_and_maximum_plus_one_fails_closed() -> None:
    measured = metrics.generate_boundary_metrics()

    assert measured["boundary"] == "maximum_rules_per_run"
    assert (
        measured["exact_maximum"]
        == metrics.semantics.MAX_RULES_PER_RUN
        == 64
    )
    assert measured["maximum_plus_one"] == 65
    assert measured["exact_usable"] is True
    assert measured["exact_rule_link_count"] == 64
    assert measured["exact_completed"] is True
    assert (
        measured["elapsed_seconds"]
        <= measured["ceiling_seconds"]
        == 0.250
    )
    assert measured["within_ceiling"] is True
    assert measured["maximum_plus_one_usable"] is True
    assert measured["maximum_plus_one_refusal_code"] is None
    assert measured["maximum_plus_one_page_status"] == "unavailable"
    assert measured["maximum_plus_one_page_concern_code"] == (
        "text_run_rule_limit"
    )
    assert measured["maximum_plus_one_run_count"] == 0
    assert measured["maximum_plus_one_rule_count"] == 0
    assert measured["maximum_plus_one_elapsed_seconds"] <= 0.250
    assert measured["maximum_plus_one_within_ceiling"] is True
    assert measured["maximum_plus_one_failed_closed"] is True
    assert len(measured["exact_fixture_sha256"]) == 64
    assert len(measured["maximum_plus_one_fixture_sha256"]) == 64


def _fake_snapshot(
    calls: list[tuple[str, bool]],
    case: str,
    enabled: bool,
) -> dict[str, Any]:
    calls.append((case, enabled))
    base_seconds = 6.0 if case == "purchase-agreement" else 20.0
    base_rss = 1_000_000 if case == "purchase-agreement" else 2_000_000
    return {
        "case": case,
        "enabled": enabled,
        "wall_seconds": base_seconds + (0.1 if enabled else 0.0),
        "peak_rss_bytes": base_rss + (10_000 if enabled else 0),
        "extractor_call_count": 1 if enabled else 0,
        "semantic_json_sha256": hashlib.sha256(
            f"{case}:{enabled}".encode()
        ).hexdigest(),
        "flag_off_projection_absent": not enabled,
        **metrics.HOSTED_USAGE,
    }


def test_paired_harness_runs_five_alternating_purchase_and_uber_pairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, bool]] = []

    def snapshot(
        _workspace: Path,
        case: str,
        enabled: bool,
    ) -> dict[str, Any]:
        return _fake_snapshot(calls, case, enabled)

    monkeypatch.setattr(metrics, "_fresh_snapshot", snapshot)

    measured = metrics.generate_paired_parser_metrics(repeats=5)

    expected_order = [
        ["off", "on"],
        ["on", "off"],
        ["off", "on"],
        ["on", "off"],
        ["off", "on"],
    ]
    purchase = measured["purchase_parser_budget"]
    assert purchase["execution_order"] == expected_order
    assert purchase["all_flag_off_extractor_counts_zero"] is True
    assert purchase["all_flag_on_extractor_counts_one"] is True
    assert purchase["flag_off_semantic_deterministic"] is True
    assert purchase["flag_on_semantic_deterministic"] is True
    parser_gate = purchase["paired_performance"]
    assert parser_gate["pair_count"] == 5
    assert parser_gate["p95_nonnegative_overhead_seconds"] == 0.1
    assert parser_gate["within_five_percent_ceiling"] is True
    assert parser_gate["within_absolute_ceiling"] is True
    assert parser_gate["within_both_ceilings"] is True

    uber = measured["uber_memory_guard"]
    assert uber["execution_order"] == expected_order
    memory = uber["memory_guard"]
    assert memory["pair_count"] == 5
    assert memory["process_model"] == "fresh_process_per_flag_state"
    assert memory["all_measurements_positive"] is True
    assert len(memory["flag_off_peak_rss_bytes"]) == 5
    assert len(memory["flag_on_peak_rss_bytes"]) == 5
    assert len(calls) == 20


def test_synthetic_custody_worker_cli_and_atomic_output(
    tmp_path: Path,
) -> None:
    custody = metrics._synthetic_fixture_custody()

    assert tuple(custody) == metrics.SYNTHETIC_FIXTURE_IDS
    assert all(
        len(record["payload_sha256"]) == 64
        and record["payload_sha256"]
        == hashlib.sha256(
            metrics._canonical_json(record["payload"]).encode("utf-8")
        ).hexdigest()
        for record in custody.values()
    )
    limits = custody["synthetic:p03-us05:limits-v1"]["payload"]
    assert limits["exact_maximum"] == 64
    assert limits["maximum_plus_one"] == 65
    assert len(limits["exact_source_sha256"]) == 64
    assert len(limits["maximum_plus_one_source_sha256"]) == 64

    output = tmp_path / "nested" / "artifact.json"
    metrics._write_json_atomic(output, {"answer": 41})
    assert output.read_text(encoding="utf-8") == (
        '{\n  "answer": 41\n}\n'
    )
    assert not list(output.parent.glob("*.tmp"))

    command = metrics._worker_command(
        metrics.WORKSPACE,
        "purchase-agreement",
        True,
        output,
    )
    assert command[-8:] == [
        "--workspace",
        str(metrics.WORKSPACE),
        "--worker-case",
        "purchase-agreement",
        "--worker-enabled",
        "true",
        "--output",
        str(output),
    ]
    parsed = metrics._parse_args(
        [
            "--worker-case",
            "uber-earnings",
            "--worker-enabled",
            "false",
            "--output",
            str(output),
        ]
    )
    assert parsed.worker_case == "uber-earnings"
    assert parsed.worker_enabled == "false"
    assert parsed.output == output
    assert metrics.DEFAULT_ARTIFACT_RELATIVE_PATH == Path(
        "tracker/phase-03-layout/evidence/"
        "P03-US05-text-run-metrics.json"
    )


def test_worker_cli_rejects_incomplete_modes() -> None:
    with pytest.raises(SystemExit):
        metrics._parse_args(["--worker-case", "purchase-agreement"])
    with pytest.raises(SystemExit):
        metrics._parse_args(["--worker-enabled", "true"])


def test_limit_fixture_manifest_is_deterministic() -> None:
    first = metrics._synthetic_fixture_custody()
    second = json.loads(json.dumps(metrics._synthetic_fixture_custody()))

    assert first == second
