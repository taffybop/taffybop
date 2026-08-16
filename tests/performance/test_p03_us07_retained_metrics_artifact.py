"""Custody and quality gate for the retained P03-US07 metrics artifact."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from tests.benchmarks import outline_structure_metrics as metrics

WORKSPACE = Path(__file__).resolve().parents[2]
ARTIFACT = WORKSPACE / metrics.DEFAULT_ARTIFACT_RELATIVE_PATH
EXPECTED_ARTIFACT_SHA256 = (
    "cbfe68a90a225adc9896435f7197389998df8ddddfca2ae94f8a917807490765"
)
P03_US08_SUCCESSOR_OWNED_INPUTS = frozenset(
    {
        ".env.example",
        "README.md",
        "pyproject.toml",
        "uv.lock",
        "app/config.py",
        "app/models.py",
        "app/services/ir.py",
        "app/services/layout.py",
        "app/services/pipeline.py",
        "app/services/presentation.py",
        "app/services/serializer.py",
        "frontend/app/clearleaf-workspace.tsx",
        "frontend/lib/canonical-presentation.ts",
        "frontend/lib/normalize-document-json.ts",
        "frontend/lib/serialize-output.ts",
        "frontend/lib/types.ts",
        "frontend/package-lock.json",
    }
)
PHASE03_EXIT_SUCCESSOR_OWNED_INPUTS = frozenset(
    {
        "app/services/outline_structure.py",
        "tests/performance/test_p03_us07_outline_performance.py",
    }
)
POST_US07_SUCCESSOR_OWNED_INPUTS = (
    P03_US08_SUCCESSOR_OWNED_INPUTS | PHASE03_EXIT_SUCCESSOR_OWNED_INPUTS
)

pytestmark = pytest.mark.skipif(
    not ARTIFACT.is_file(),
    reason="P03-US07 retained metrics are written during story closure",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact() -> dict[str, Any]:
    raw = ARTIFACT.read_bytes()
    assert EXPECTED_ARTIFACT_SHA256 is not None, (
        "seal EXPECTED_ARTIFACT_SHA256 after the final reviewed measurement"
    )
    assert len(EXPECTED_ARTIFACT_SHA256) == 64
    assert hashlib.sha256(raw).hexdigest() == EXPECTED_ARTIFACT_SHA256
    payload = json.loads(raw)
    assert isinstance(payload, dict)
    return payload


def _assert_zero_hosted_usage(value: Any) -> None:
    if isinstance(value, Mapping):
        hosted_keys = set(metrics.HOSTED_USAGE) & set(value)
        for key in hosted_keys:
            assert value[key] == 0
        for child in value.values():
            _assert_zero_hosted_usage(child)
    elif isinstance(value, list):
        for child in value:
            _assert_zero_hosted_usage(child)


def test_retained_artifact_binds_raw_semantic_code_and_source_custody() -> None:
    artifact = _artifact()

    assert artifact["schema_version"] == "1.0"
    assert artifact["record_kind"] == "p03_us07_outline_metrics"
    assert artifact["story"] == "P03-US07"
    assert artifact["status"] == "final_measurement_candidate"
    assert artifact["retained_path"] == str(metrics.DEFAULT_ARTIFACT_RELATIVE_PATH)
    datetime.fromisoformat(artifact["generated_at"])
    assert (
        artifact["semantic_sha256"]
        == hashlib.sha256(
            metrics._canonical_json(
                metrics._artifact_semantic_payload(artifact)
            ).encode("utf-8")
        ).hexdigest()
    )

    code_records = artifact["code_sha256"]
    assert set(code_records) == set(metrics.FINAL_CODE_PATHS)
    assert POST_US07_SUCCESSOR_OWNED_INPUTS < set(code_records)
    changed_since_seal: set[str] = set()
    for relative, record in code_records.items():
        assert record["path"] == relative
        assert record["size_bytes"] > 0
        assert len(record["sha256"]) == 64
        path = WORKSPACE / relative
        assert path.is_file()
        current = {
            "path": relative,
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        if current != record:
            changed_since_seal.add(relative)
        if relative not in POST_US07_SUCCESSOR_OWNED_INPUTS:
            assert current == record

    assert changed_since_seal <= POST_US07_SUCCESSOR_OWNED_INPUTS
    assert PHASE03_EXIT_SUCCESSOR_OWNED_INPUTS <= changed_since_seal

    assert set(artifact["input_custody"]) == set(metrics.SOURCE_IDENTITIES)
    for case, expected in metrics.SOURCE_IDENTITIES.items():
        custody = artifact["input_custody"][case]
        assert custody["expected"] == expected
        assert custody["exact_match"] is True
        observed = custody["observed"]
        for key in ("path", "size_bytes", "sha256", "page_count"):
            assert observed[key] == expected[key]
        source = WORKSPACE / expected["path"]
        assert source.stat().st_size == expected["size_bytes"]
        assert _sha256(source) == expected["sha256"]


def test_retained_predecessor_oracle_contract_and_dependency_custody() -> None:
    artifact = _artifact()

    predecessor = artifact["predecessor_custody"]
    us06 = predecessor["p03_us06_artifact"]
    assert us06["path"] == str(metrics.PREDECESSOR_ARTIFACT_RELATIVE_PATH)
    assert us06["size_bytes"] == metrics.PREDECESSOR_ARTIFACT_SIZE_BYTES
    assert us06["raw_sha256"] == metrics.PREDECESSOR_ARTIFACT_RAW_SHA256
    assert us06["sha256"] == metrics.PREDECESSOR_ARTIFACT_RAW_SHA256
    assert us06["semantic_sha256"] == (metrics.PREDECESSOR_ARTIFACT_SEMANTIC_SHA256)
    assert us06["story"] == "P03-US06"
    assert us06["status"] == "final_measurement_candidate"
    assert predecessor["configured_predecessor_definition"] == (
        "all P03-US01-US06 flags enabled with US07 disabled"
    )
    assert set(predecessor["reviewed_value_custody"]) == set(
        metrics.PREDECESSOR_IDENTITIES
    )
    assert all(
        value["exact_match"] for value in predecessor["reviewed_value_custody"].values()
    )

    m0 = artifact["m0_reference"]
    assert m0["path"] == str(metrics.M0_ARTIFACT_RELATIVE_PATH)
    assert m0["size_bytes"] == metrics.M0_ARTIFACT_SIZE_BYTES
    assert m0["sha256"] == metrics.M0_ARTIFACT_RAW_SHA256
    assert m0["cases"] == metrics.M0_REFERENCES
    assert m0["role"] == "historical_context_not_paired_predecessor"

    oracle = artifact["oracle_custody"]
    assert oracle["oracle_payload_sha256"] == metrics.oracle_sha256()
    assert oracle["source_identities_exact"] is True
    assert oracle["reviewed_counts"] == metrics.REVIEWED_COUNTS
    assert len(oracle["canonical_expectations_sha256"]) == 64
    assert oracle["settlement_addendum"]["size_bytes"] > 0
    assert set(oracle["frozen_phase_00_records"]) == {
        "case_review",
        "comparison_report",
    }
    assert artifact["contract_custody"]["policy_id"] == metrics.POLICY_ID

    synthetic = artifact["synthetic_fixture_custody"]
    assert synthetic["fixture_count"] == len(metrics.SYNTHETIC_FIXTURES)
    assert synthetic["required_capability_count"] == len(
        metrics.REQUIRED_SYNTHETIC_COVERAGE
    )
    assert synthetic["thresholds"] == dict(metrics.SYNTHETIC_THRESHOLDS)
    assert synthetic["fixture_hashes"] == metrics.fixture_hashes()
    assert synthetic["registry_sha256"] == metrics.registry_sha256()
    assert synthetic["self_check_passed"] is True

    dependency = artifact["dependency_custody"]
    assert set(dependency["dependency_manifests"]) == set(
        metrics.DEPENDENCY_MANIFEST_PATHS
    )
    assert set(dependency["python_packages"]) == set(
        metrics.LOCAL_PACKAGE_DISTRIBUTIONS
    )
    assert dependency["local_tool_identity"]["tesseract"]["version"].startswith(
        "tesseract "
    )
    assert dependency["local_tool_identity"]["python_version"]


def test_retained_isolated_profiles_and_all_22_resource_gates_pass() -> None:
    artifact = _artifact()

    assert set(artifact["source_extraction"]) == set(metrics.PAIRED_CASES)
    for case, measured in artifact["source_extraction"].items():
        assert measured["case"] == case
        assert measured["profile"] == "isolated_native_outline_extraction"
        assert measured["warmup_count"] == 2
        assert measured["sample_count"] == 20
        assert len(measured["samples_seconds"]) == 20
        assert measured["quantile_method"] == ("empirical_p95_inclusive_nearest_rank")
        assert measured["timing_tracemalloc_enabled"] is False
        assert measured["timing_results_retained"] is False
        assert measured["gc_collection_outside_timed_interval"] is True
        assert measured["allocation_measured_in_separate_call"] is True
        assert measured["allocation_sample_count"] == 5
        assert len(measured["peak_allocated_samples_bytes"]) == 5
        assert measured["p95_seconds"] <= (
            measured["p95_ceiling_seconds"] == metrics.EXTRACTION_CEILINGS_SECONDS[case]
        )
        assert measured["within_p95_ceiling"] is True
        assert measured["peak_allocated_bytes"] <= 64 * 1024 * 1024
        assert measured["within_peak_allocation_ceiling"] is True
        assert measured["report_size_bytes"] <= 8 * 1024 * 1024
        assert measured["within_report_size_ceiling"] is True
        assert measured["semantic_deterministic"] is True
        assert measured["source_sha256_exact"] is True
        assert measured["source_report_exact"] is True
        assert measured["reviewed_counts"] == metrics.SOURCE_REPORTS[case]["counts"]

    assert set(artifact["outline_projection"]) == set(metrics.PAIRED_CASES)
    for case, measured in artifact["outline_projection"].items():
        assert measured["case"] == case
        assert measured["profile"] == "isolated_outline_projection"
        assert measured["warmup_count"] == 2
        assert measured["sample_count"] == 20
        assert len(measured["samples_seconds"]) == 20
        assert measured["timing_tracemalloc_enabled"] is False
        assert measured["timing_results_retained"] is False
        assert measured["allocation_measured_in_separate_call"] is True
        assert measured["p95_seconds"] <= (
            measured["p95_ceiling_seconds"] == metrics.PROJECTION_CEILING_SECONDS
        )
        assert measured["within_p95_ceiling"] is True
        assert measured["peak_allocated_bytes"] <= 64 * 1024 * 1024
        assert measured["within_peak_allocation_ceiling"] is True
        assert measured["semantic_deterministic"] is True
        assert measured["predecessor_unmodified"] is True
        assert measured["repeated_projection_idempotent"] is True
        assert measured["comparison_instrumentation_separate_from_timing"] is True
        assert measured["maximum_comparisons_on_page"] > 0
        assert measured["comparison_ceiling_per_page"] == 65_536
        assert measured["within_comparison_ceiling"] is True
        assert measured["instrumented_projection_semantically_equal"] is True
        assert measured["outline_summary"] == (metrics.EXPECTED_OUTLINE_SUMMARIES[case])
        assert measured["outline_summary_exact"] is True

    resources = artifact["resource_boundaries"]
    assert resources["boundary_count"] == 22
    assert set(resources["boundaries"]) == set(metrics._PRODUCTION_LIMIT_ATTRIBUTES)
    assert resources["all_exact_accepted"] is True
    assert resources["all_maximum_plus_one_refused"] is True
    assert resources["all_production_limits_exact"] is True
    assert resources["all_within_boundary_ceiling"] is True
    for name, record in resources["boundaries"].items():
        assert record["registry_limit"] == metrics.SYNTHETIC_THRESHOLDS[name]
        assert record["production_limit"] == record["registry_limit"]
        assert record["exact_observed"] == record["registry_limit"]
        assert record["exact_accepted"] is True
        assert record["maximum_plus_one_observed"] == (record["registry_limit"] + 1)
        assert record["maximum_plus_one_refused"] is True
        assert record["boundary_ceiling_seconds_each"] == 0.250
        assert record["within_boundary_ceiling"] is True

    deadlines = artifact["deadline_boundaries"]
    assert deadlines["deadline_count"] == 3
    assert deadlines["all_exact_accepted"] is True
    assert deadlines["all_maximum_plus_one_refused"] is True
    assert deadlines["all_production_limits_exact"] is True


def test_retained_paired_parser_controls_rollback_and_order_are_exact() -> None:
    artifact = _artifact()
    paired = artifact["paired_parser"]

    assert paired["pair_count_per_case"] == 5
    assert paired["performance_cases"] == list(metrics.PAIRED_CASES)
    expected_order = [
        ["off", "on"],
        ["on", "off"],
        ["off", "on"],
        ["on", "off"],
        ["off", "on"],
    ]
    for case, record in paired["cases"].items():
        assert case in metrics.PAIRED_CASES
        assert record["execution_order"] == expected_order
        assert len(record["flag_off_samples"]) == 5
        assert len(record["flag_on_samples"]) == 5
        assert record["all_flag_off_extractor_counts_zero"] is True
        assert record["all_flag_on_extractor_counts_one"] is True
        assert record["all_flag_off_projection_absent"] is True
        assert record["all_flag_on_processing_summaries_present"] is True
        assert record["all_flag_on_outline_summaries_exact"] is True
        assert record["flag_off_semantic_deterministic"] is True
        assert record["flag_on_first_three_semantic_deterministic"] is True
        assert record["flag_on_all_semantic_deterministic"] is True
        assert record["flag_on_outline_semantic_deterministic"] is True
        assert record["all_samples_forms_predecessor_present"] is True
        assert record["all_samples_zero_hosted_usage"] is True
        performance = record["paired_performance"]
        assert performance["pair_count"] == 5
        assert performance["process_model"] == "fresh_process_per_flag_state"
        assert performance["execution_order_alternated"] is True
        assert (
            performance["p95_nonnegative_overhead_seconds"]
            <= (performance["five_percent_ceiling_seconds"])
        )
        assert (
            performance["p95_nonnegative_overhead_seconds"]
            <= (metrics.PAIRED_ABSOLUTE_CEILINGS_SECONDS[case])
        )
        assert performance["within_five_percent_ceiling"] is True
        assert performance["within_absolute_ceiling"] is True
        assert performance["within_both_ceilings"] is True
        assert performance["maximum_peak_rss_delta_bytes"] <= 64 * 1024 * 1024
        assert performance["within_peak_rss_delta_ceiling"] is True

    controls = artifact["control_matrix"]
    assert set(controls["targets"]) == set(metrics.PAIRED_CASES)
    assert controls["all_targets_exact"] is True
    assert controls["all_real_controls_pass"] is True
    for case, target in controls["targets"].items():
        assert target["outline_exact"] is True
        assert target["form_predecessor_exact"] is True
        assert target["form_summary"] == metrics.EXPECTED_FORM_SUMMARIES[case]
    assert controls["finance_non_target"]["zero_false_outlines"] is True
    assert controls["synthetic_registry"]["fixture_count"] == len(
        metrics.SYNTHETIC_FIXTURES
    )
    assert controls["synthetic_registry"]["self_check_passed"] is True
    assert controls["synthetic_registry"]["reader_check_passed"] is True

    order = artifact["relationship_order_retention"]
    assert order["top_level_expected"] == 40
    assert order["top_level_matched"] == 40
    assert order["nested_expected"] == 1
    assert order["nested_matched"] == 1
    assert order["total_expected"] == 41
    assert order["total_matched"] == 41
    assert order["all_pass"] is True

    rollback = artifact["rollback"]
    assert rollback == {
        "rollback_value": False,
        "only_us07_setting_toggled": True,
        "all_flag_off_extractor_counts_zero": True,
        "all_flag_off_projection_absent": True,
        "all_repeated_projections_idempotent": True,
        "configured_predecessor_flags_unchanged": True,
    }
    aggregate = artifact["aggregate"]
    assert all(
        value is True
        for key, value in aggregate.items()
        if key not in metrics.HOSTED_USAGE
        and key not in {"relationship_order_expected", "relationship_order_matched"}
    )
    assert aggregate["relationship_order_expected"] == 41
    assert aggregate["relationship_order_matched"] == 41


def test_retained_output_sizes_measurement_policy_and_hosted_usage_are_exact() -> None:
    artifact = _artifact()

    measurement = artifact["measurement"]
    assert measurement["performance_cases"] == list(metrics.PAIRED_CASES)
    assert measurement["pair_count_per_case"] == 5
    assert measurement["worker_process_count"] == 20
    assert measurement["quantile_formula"] == ("sorted(samples)[ceil(0.95 * n) - 1]")
    assert measurement["timing_and_traced_allocation_measured_separately"] is True
    assert measurement["timing_outputs_released_between_samples"] is True
    assert measurement["pre_post_code_custody_match"] is True
    assert measurement["pre_post_source_custody_match"] is True

    policy = artifact["policy"]
    assert policy["policy_id"] == metrics.POLICY_ID
    assert policy["feature_flag"] == "PARSER_LAYOUT_OUTLINE_STRUCTURE_ENABLED"
    assert policy["default_enabled"] is False
    assert policy["rollback_value"] is False
    assert policy["source_extraction_p95_ceiling_seconds"] == (
        metrics.EXTRACTION_CEILINGS_SECONDS
    )
    assert policy["projection_p95_ceiling_seconds"] == 0.050
    assert policy["isolated_peak_allocation_ceiling_bytes"] == 64 * 1024 * 1024
    assert policy["maximum_boundary_ceiling_seconds"] == 0.250
    assert policy["paired_absolute_ceiling_seconds"] == (
        metrics.PAIRED_ABSOLUTE_CEILINGS_SECONDS
    )
    assert policy["paired_percent_ceiling"] == 5.0
    assert policy["peak_rss_delta_ceiling_bytes"] == 64 * 1024 * 1024
    assert policy["semantic_timing_paths_removed"] == list(metrics.TIMING_PATHS_REMOVED)
    assert policy["resource_limits"] == dict(metrics.SYNTHETIC_THRESHOLDS)

    assert set(artifact["output_sizes"]) == set(metrics.PAIRED_CASES)
    for states in artifact["output_sizes"].values():
        assert set(states) == {"off", "on"}
        for samples in states.values():
            assert len(samples) == 5
            assert all(
                value > 0
                for sample in samples
                for key, value in sample.items()
                if key.endswith("_size_bytes")
            )
            assert all(
                len(value) == 64
                for sample in samples
                for key, value in sample.items()
                if key.endswith("_sha256")
            )
    _assert_zero_hosted_usage(artifact)
