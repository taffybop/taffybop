"""Performance-contract checks for P03-US06 form semantics."""

from __future__ import annotations

from copy import deepcopy
import gc
import hashlib
from pathlib import Path
import tracemalloc
from types import SimpleNamespace
from typing import Any
import weakref

import pytest

from tests.benchmarks import form_semantics_metrics as metrics


def test_fixed_sources_settings_and_local_only_policy_are_exact() -> None:
    custody = metrics._source_custody(metrics.WORKSPACE)

    assert set(custody) == {
        "insurance-acord",
        "component-datasheet",
    }
    assert all(record["exact_match"] for record in custody.values())
    assert metrics.M0_REFERENCES == {
        "insurance-acord": {
            "label": "M0_reference_context_not_paired_predecessor",
            "wall_seconds": 9.06,
            "peak_rss_mib": 1_401.1,
        },
        "component-datasheet": {
            "label": "M0_reference_context_not_paired_predecessor",
            "wall_seconds": 10.56,
            "peak_rss_mib": 1_840.3,
        },
    }
    assert metrics.HOSTED_USAGE == {
        "hosted_requests": 0,
        "hosted_tokens": 0,
        "hosted_cost_usd": 0,
    }
    assert metrics._settings_delta() == {
        "changed_fields": ["layout_forms_enabled"],
        "flag_off": {"layout_forms_enabled": False},
        "flag_on": {"layout_forms_enabled": True},
        "accepted_predecessor_flags_enabled": True,
    }
    disabled = metrics._settings(False)
    enabled = metrics._settings(True)
    assert disabled.layout_table_captions_enabled is True
    assert disabled.layout_visual_relationships_enabled is True
    assert disabled.layout_source_notes_enabled is True
    assert disabled.layout_relationship_order_enabled is True
    assert disabled.layout_text_run_semantics_enabled is True
    assert disabled.layout_forms_enabled is False
    assert enabled.layout_forms_enabled is True


def test_source_custody_observes_page_count_instead_of_copying_expected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(metrics, "_observed_pdf_page_count", lambda _source: 99)

    custody = metrics._source_custody(
        metrics.WORKSPACE,
        ("insurance-acord",),
    )["insurance-acord"]

    assert custody["expected"]["page_count"] == 1
    assert custody["observed"]["page_count"] == 99
    assert custody["exact_match"] is False


def test_inclusive_p95_is_the_policy_nearest_rank_not_interpolation() -> None:
    assert metrics._inclusive_p95(list(range(1, 21))) == 19
    assert metrics._inclusive_p95([1, 2, 3, 4, 5]) == 5
    assert metrics._inclusive_p95([4.0]) == 4.0
    with pytest.raises(ValueError, match="p95 requires"):
        metrics._inclusive_p95([])


def test_semantic_determinism_removes_exactly_four_timing_paths() -> None:
    payload = {
        "processing": {
            "duration_ms": 12,
            "form_semantics": {
                "extraction_ms": 1.0,
                "projection_ms": 2.0,
                "total_ms": 3.0,
                "preserved": "semantic",
            },
            "other": {"duration_ms": 99},
        },
        "duration_ms": 88,
    }

    assert metrics._semantic_payload(payload) == {
        "processing": {
            "form_semantics": {"preserved": "semantic"},
            "other": {"duration_ms": 99},
        },
        "duration_ms": 88,
    }
    assert metrics.TIMING_PATHS_REMOVED == (
        "processing.duration_ms",
        "processing.form_semantics.extraction_ms",
        "processing.form_semantics.projection_ms",
        "processing.form_semantics.total_ms",
    )


def test_timing_profile_verifies_tracing_and_releases_sample_outputs() -> None:
    class Payload:
        pass

    references: list[weakref.ReferenceType[Payload]] = []
    samples = metrics._profile_timing(
        Payload,
        warmup_count=0,
        sample_count=3,
        after_sample=lambda result: references.append(weakref.ref(result)),
    )
    gc.collect()

    assert len(samples) == 3
    assert all(reference() is None for reference in references)

    tracemalloc.start()
    try:
        with pytest.raises(RuntimeError, match="requires tracemalloc"):
            metrics._profile_timing(
                Payload,
                warmup_count=0,
                sample_count=1,
            )
    finally:
        tracemalloc.stop()


def test_rss_normalization_is_platform_exact() -> None:
    assert metrics._rss_bytes_from_maxrss(123, platform_name="darwin") == 123
    assert metrics._rss_bytes_from_maxrss(123, platform_name="linux") == (
        123 * 1_024
    )


def test_paired_gate_uses_current_predecessor_dual_ceilings_and_rss() -> None:
    off = [
        {"wall_seconds": 10.0, "peak_rss_bytes": 1_000}
        for _ in range(5)
    ]
    on = [
        {"wall_seconds": 9.0, "peak_rss_bytes": 900},
        {"wall_seconds": 9.0, "peak_rss_bytes": 900},
        {"wall_seconds": 9.0, "peak_rss_bytes": 900},
        {"wall_seconds": 9.0, "peak_rss_bytes": 900},
        {"wall_seconds": 10.7, "peak_rss_bytes": 1_100},
    ]

    summary = metrics._paired_performance_summary(
        "insurance-acord",
        off,
        on,
    )

    assert summary["pair_count"] == 5
    assert summary["quantile_method"] == (
        "empirical_p95_inclusive_nearest_rank"
    )
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
    assert summary["p95_signed_delta_seconds"] == pytest.approx(0.7)
    assert summary["p95_nonnegative_overhead_seconds"] == pytest.approx(0.7)
    assert summary["current_paired_predecessor_p95_seconds"] == 10.0
    assert summary["five_percent_ceiling_seconds"] == 0.5
    assert summary["absolute_ceiling_seconds"] == 0.453
    assert summary["effective_ceiling_seconds"] == 0.453
    assert summary["within_both_ceilings"] is False
    assert summary["maximum_peak_rss_delta_bytes"] == 100
    assert summary["within_peak_rss_delta_ceiling"] is True
    assert [metrics._paired_states(index) for index in range(5)] == [
        (False, True),
        (True, False),
        (False, True),
        (True, False),
        (False, True),
    ]

    with pytest.raises(ValueError, match="exactly 5 pairs"):
        metrics._paired_performance_summary(
            "insurance-acord",
            off[:-1],
            on[:-1],
        )
    with pytest.raises(ValueError, match="exactly 5 pairs"):
        metrics._paired_performance_summary(
            "insurance-acord",
            [*off, off[0]],
            [*on, on[0]],
        )


def test_comparison_capture_observes_immediate_accounting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    predecessor = object()
    evidence = SimpleNamespace(
        pages=(SimpleNamespace(page_index=1),),
    )
    original_account = metrics.semantics._ProjectionBudget.account_comparisons

    def project(candidate: object, _evidence: object) -> object:
        budget = metrics.semantics._ProjectionBudget(
            started_at=metrics.time.perf_counter(),
            comparisons_by_page={},
        )
        budget.account_comparisons(1, 7)
        return candidate

    monkeypatch.setattr(metrics.semantics, "project_form_semantics", project)
    comparisons, projected = metrics._capture_projection_comparisons(
        predecessor,  # type: ignore[arg-type]
        evidence,  # type: ignore[arg-type]
    )

    assert comparisons == {1: 7}
    assert projected is predecessor
    assert metrics.semantics._ProjectionBudget.account_comparisons is (
        original_account
    )


@pytest.mark.parametrize(
    ("case", "ceiling"),
    [
        ("insurance-acord", 0.150),
        ("component-datasheet", 0.300),
    ],
)
def test_real_extraction_meets_latency_allocation_and_size_gates(
    case: str,
    ceiling: float,
) -> None:
    measured = metrics.generate_extraction_metrics(case)

    assert measured["warmup_count"] == 2
    assert measured["sample_count"] == 20
    assert len(measured["samples_seconds"]) == 20
    assert measured["clock"] == "time.perf_counter_ns"
    assert measured["timing_tracemalloc_enabled"] is False
    assert measured["timing_tracemalloc_state_verified"] is True
    assert measured["timing_results_retained"] is False
    assert measured["gc_collection_outside_timed_interval"] is True
    assert measured["allocation_measured_in_separate_call"] is True
    assert measured["allocation_warmup_count"] == 1
    assert measured["allocation_sample_count"] == 5
    assert len(measured["peak_allocated_samples_bytes"]) == 5
    assert measured["tracemalloc_reset_between_samples"] is True
    assert 0 < measured["p50_seconds"] <= measured["p95_seconds"]
    assert measured["p95_seconds"] <= measured["max_seconds"]
    assert measured["p95_ceiling_seconds"] == ceiling
    assert measured["within_p95_ceiling"] is True
    assert measured["peak_allocation_ceiling_bytes"] == 64 * 1024 * 1024
    assert measured["within_peak_allocation_ceiling"] is True
    assert measured["report_size_ceiling_bytes"] == 8 * 1024 * 1024
    assert measured["within_report_size_ceiling"] is True
    assert measured["semantic_deterministic"] is True
    assert measured["source_sha256_exact"] is True
    assert measured["page_count"] == metrics.SOURCE_IDENTITIES[case][
        "page_count"
    ]
    assert {
        key: measured[key] for key in metrics.HOSTED_USAGE
    } == metrics.HOSTED_USAGE


@pytest.mark.parametrize(
    "case",
    ["insurance-acord", "component-datasheet"],
)
def test_real_projection_meets_latency_and_allocation_gates(case: str) -> None:
    measured = metrics.generate_projection_metrics(case)

    assert measured["warmup_count"] == 2
    assert measured["sample_count"] == 20
    assert len(measured["samples_seconds"]) == 20
    assert measured["clock"] == "time.perf_counter_ns"
    assert measured["timing_tracemalloc_enabled"] is False
    assert measured["timing_tracemalloc_state_verified"] is True
    assert measured["timing_results_retained"] is False
    assert measured["allocation_measured_in_separate_call"] is True
    assert measured["allocation_warmup_count"] == 1
    assert measured["allocation_sample_count"] == 5
    assert len(measured["peak_allocated_samples_bytes"]) == 5
    assert measured["p95_ceiling_seconds"] == 0.050
    assert measured["within_p95_ceiling"] is True
    assert measured["peak_allocation_ceiling_bytes"] == 64 * 1024 * 1024
    assert measured["within_peak_allocation_ceiling"] is True
    assert measured["semantic_deterministic"] is True
    assert measured["predecessor_unmodified"] is True
    assert measured["repeated_projection_idempotent"] is True
    assert measured["comparison_instrumentation_separate_from_timing"] is True
    assert measured["comparison_ceiling_per_page"] == 65_536
    assert measured["within_comparison_ceiling"] is True
    assert all(
        0 <= count <= 65_536
        for count in measured["comparisons_by_page"].values()
    )
    if case == "insurance-acord":
        assert measured["comparisons_by_page"][1] > 0
    else:
        assert measured["comparisons_by_page"][2] > 0
        assert measured["comparisons_by_page"][3] > 0
    assert measured["instrumented_projection_semantically_equal"] is True
    assert measured["role_counts"]["group"] > 0
    assert {
        key: measured[key] for key in metrics.HOSTED_USAGE
    } == metrics.HOSTED_USAGE


def test_exact_maximum_and_maximum_plus_one_projector_are_bounded() -> None:
    measured = metrics.generate_boundary_metrics()

    assert measured["boundary"] == "maximum_groups_per_page"
    assert measured["construction_timed"] is False
    assert (
        measured["exact_maximum"]
        == metrics.MAX_FORM_GROUPS_PER_PAGE
        == 256
    )
    assert measured["maximum_plus_one"] == 257
    assert measured["exact_completed"] is True
    assert measured["exact_role_counts"]["group"] == 256
    assert measured["exact_role_counts"]["control"] == 256
    assert measured["maximum_plus_one_failed_closed"] is True
    assert measured["maximum_plus_one_concern_codes"] == [
        "form_projection_failed_closed"
    ]
    assert measured["ceiling_seconds_each"] == 0.250
    assert measured["exact_within_ceiling"] is True
    assert measured["maximum_plus_one_within_ceiling"] is True
    assert measured["within_ceiling"] is True


def _fake_snapshot(
    calls: list[tuple[str, bool]],
    case: str,
    enabled: bool,
) -> dict[str, Any]:
    calls.append((case, enabled))
    base_seconds = 10.0 if case == "insurance-acord" else 12.0
    base_rss = 1_000_000 if case == "insurance-acord" else 2_000_000
    return {
        "case": case,
        "enabled": enabled,
        "wall_seconds": base_seconds + (0.1 if enabled else 0.0),
        "peak_rss_bytes": base_rss + (10_000 if enabled else 0),
        "extractor_call_count": 1 if enabled else 0,
        "semantic_json_sha256": hashlib.sha256(
            f"{case}:{enabled}".encode()
        ).hexdigest(),
        "semantic_json_size_bytes": 100 + int(enabled),
        "raw_json_sha256": hashlib.sha256(
            f"raw:{case}:{enabled}".encode()
        ).hexdigest(),
        "raw_json_size_bytes": 110 + int(enabled),
        "markdown_sha256": hashlib.sha256(
            f"markdown:{case}:{enabled}".encode()
        ).hexdigest(),
        "markdown_size_bytes": 120 + int(enabled),
        "flag_off_projection_absent": not enabled,
        "processing_has_form_summary": enabled,
        "form_summary": (
            metrics.EXPECTED_FORM_SUMMARIES[case]
            if enabled
            else {
                key: 0
                for key in metrics.EXPECTED_FORM_SUMMARIES[case]
            }
        ),
        **metrics.HOSTED_USAGE,
    }


def test_paired_harness_runs_five_alternating_pairs_for_both_cases(
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

    assert measured["pair_count_per_case"] == 5
    assert measured["performance_cases"] == list(metrics.PAIRED_CASES)
    expected_order = [
        ["off", "on"],
        ["on", "off"],
        ["off", "on"],
        ["on", "off"],
        ["off", "on"],
    ]
    for case in metrics.PAIRED_CASES:
        record = measured["cases"][case]
        assert record["execution_order"] == expected_order
        assert record["all_flag_off_extractor_counts_zero"] is True
        assert record["all_flag_on_extractor_counts_one"] is True
        assert record["all_flag_off_projection_absent"] is True
        assert record["all_flag_on_processing_summaries_present"] is True
        assert record["all_flag_on_form_summaries_exact"] is True
        assert record["flag_off_semantic_deterministic"] is True
        assert record["flag_on_first_three_semantic_deterministic"] is True
        assert record["flag_on_all_semantic_deterministic"] is True
        assert record["all_samples_zero_hosted_usage"] is True
        paired = record["paired_performance"]
        assert paired["pair_count"] == 5
        assert paired["p95_nonnegative_overhead_seconds"] == 0.1
        assert paired["within_five_percent_ceiling"] is True
        assert paired["within_absolute_ceiling"] is True
        assert paired["within_both_ceilings"] is True
        assert paired["within_peak_rss_delta_ceiling"] is True
    assert len(calls) == 20


def test_paired_harness_rejects_any_count_other_than_exactly_five(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_snapshot(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("invalid pair count must fail before workers run")

    monkeypatch.setattr(metrics, "_fresh_snapshot", unexpected_snapshot)
    for repeats in (4, 6):
        with pytest.raises(ValueError, match="exactly 5 repeats"):
            metrics.generate_paired_parser_metrics(repeats=repeats)
        with pytest.raises(ValueError, match="exactly 5 repeats"):
            metrics.generate_preliminary_metrics(repeats=repeats)
        with pytest.raises(ValueError, match="exactly 5 repeats"):
            metrics.generate_artifact(repeats=repeats)


def test_final_artifact_custody_collectors_bind_live_inputs() -> None:
    code = metrics._code_custody()
    predecessor = metrics._predecessor_custody()
    oracle = metrics._oracle_custody()
    synthetic = metrics._synthetic_fixture_custody()
    dependency = metrics._dependency_custody()
    boundary = metrics._boundary_fixture_custody()

    assert tuple(code) == metrics.FINAL_CODE_PATHS
    assert all(len(record["sha256"]) == 64 for record in code.values())
    assert predecessor["raw_sha256"] == (
        metrics.PREDECESSOR_ARTIFACT_RAW_SHA256
    )
    assert predecessor["semantic_sha256"] == (
        metrics.PREDECESSOR_ARTIFACT_SEMANTIC_SHA256
    )
    assert predecessor["relationship_order_retention_all_pass"] is True
    assert oracle["source_identities_exact"] is True
    assert oracle["acord_reviewed_counts"]["total_relationship_count"] == 216
    assert oracle["component_reviewed_counts"]["total_relationship_count"] == 80
    assert synthetic["fixture_count"] == len(synthetic["fixture_hashes"]) == 25
    assert synthetic["required_capability_count"] >= 33
    assert synthetic["self_check_passed"] is True
    assert dependency["python_packages"]["docling"] == "2.114.0"
    assert dependency["python_packages"]["pdfplumber"] == "0.11.10"
    assert dependency["local_tool_identity"]["tesseract"]["version"].startswith(
        "tesseract "
    )
    assert boundary["cases"]["exact_maximum"]["group_count"] == 256
    assert boundary["cases"]["maximum_plus_one"]["group_count"] == 257


def test_final_artifact_envelope_binds_custody_rollback_and_semantic_hash(
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
    paired = metrics.generate_paired_parser_metrics()
    extraction = {
        case: {
            "within_p95_ceiling": True,
            "within_peak_allocation_ceiling": True,
            "within_report_size_ceiling": True,
        }
        for case in metrics.PAIRED_CASES
    }
    projection = {
        case: {
            "within_p95_ceiling": True,
            "within_peak_allocation_ceiling": True,
            "within_comparison_ceiling": True,
            "repeated_projection_idempotent": True,
        }
        for case in metrics.PAIRED_CASES
    }
    preliminary = {
        "input_custody": {
            case: {"exact_match": True} for case in metrics.PAIRED_CASES
        },
        "settings_delta": metrics._settings_delta(),
        "isolated_extraction": extraction,
        "isolated_projection": projection,
        "maximum_boundary": {
            "exact_within_ceiling": True,
            "maximum_plus_one_within_ceiling": True,
            "maximum_plus_one_failed_closed": True,
        },
        "paired_parser": paired,
    }

    artifact = metrics._build_final_artifact_envelope(
        preliminary,
        code_custody={"code.py": {"sha256": "a" * 64}},
        dependency_custody={"python_packages": {"example": "1"}},
        predecessor_custody={"semantic_sha256": "b" * 64},
        oracle_custody={"oracle_payload_sha256": "c" * 64},
        synthetic_fixture_custody={"registry_sha256": "d" * 64},
        generated_at="2026-07-31T00:00:00+00:00",
    )

    assert artifact["schema_version"] == "1.0"
    assert artifact["record_kind"] == "p03_us06_form_metrics"
    assert artifact["measurement"]["pair_count_per_case"] == 5
    assert artifact["measurement"]["worker_process_count"] == 20
    assert artifact["code_sha256"] == {
        "code.py": {"sha256": "a" * 64}
    }
    assert artifact["rollback"] == {
        "rollback_value": False,
        "only_us06_setting_toggled": True,
        "all_flag_off_extractor_counts_zero": True,
        "all_flag_off_projection_absent": True,
        "all_repeated_projections_idempotent": True,
        "maximum_plus_one_page_failed_closed": True,
    }
    assert artifact["aggregate"]["paired_parser_within_both_ceilings"] is True
    assert len(artifact["output_sizes"]["insurance-acord"]["off"]) == 5
    assert artifact["semantic_sha256"] == hashlib.sha256(
        metrics._canonical_json(
            metrics._artifact_semantic_payload(artifact)
        ).encode("utf-8")
    ).hexdigest()
    changed_time = deepcopy(artifact)
    changed_time["generated_at"] = "2099-01-01T00:00:00+00:00"
    assert metrics._artifact_semantic_payload(changed_time) == (
        metrics._artifact_semantic_payload(artifact)
    )


def test_worker_cli_and_atomic_preliminary_output(tmp_path: Path) -> None:
    output = tmp_path / "nested" / "preliminary.json"
    metrics._write_json_atomic(output, {"answer": 41})
    assert output.read_text(encoding="utf-8") == (
        '{\n  "answer": 41\n}\n'
    )
    assert not list(output.parent.glob("*.tmp"))

    command = metrics._worker_command(
        metrics.WORKSPACE,
        "insurance-acord",
        True,
        output,
    )
    assert command[-8:] == [
        "--workspace",
        str(metrics.WORKSPACE),
        "--worker-case",
        "insurance-acord",
        "--worker-enabled",
        "true",
        "--output",
        str(output),
    ]
    parsed = metrics._parse_args(
        [
            "--worker-case",
            "component-datasheet",
            "--worker-enabled",
            "false",
            "--output",
            str(output),
        ]
    )
    assert parsed.worker_case == "component-datasheet"
    assert parsed.worker_enabled == "false"
    assert parsed.output == output
    assert metrics.DEFAULT_ARTIFACT_RELATIVE_PATH == Path(
        "tracker/phase-03-layout/evidence/P03-US06-form-metrics.json"
    )

    final = metrics._parse_args(
        ["--final-artifact", "--output", str(output)]
    )
    assert final.final_artifact is True
    assert final.repeats == 5


def test_worker_cli_rejects_incomplete_or_implicit_output_modes() -> None:
    with pytest.raises(SystemExit):
        metrics._parse_args(["--worker-case", "insurance-acord"])
    with pytest.raises(SystemExit):
        metrics._parse_args(["--worker-enabled", "true"])
    with pytest.raises(SystemExit):
        metrics._parse_args([])
    with pytest.raises(SystemExit):
        metrics._parse_args(
            ["--repeats", "6", "--output", "candidate.json"]
        )
    with pytest.raises(SystemExit):
        metrics._parse_args(
            [
                "--worker-case",
                "insurance-acord",
                "--worker-enabled",
                "true",
                "--final-artifact",
                "--output",
                "worker.json",
            ]
        )
