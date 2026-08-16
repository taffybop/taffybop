"""Executable campaign/artifact contract for P03-US08 metrics readiness."""

from __future__ import annotations

import gc
import hashlib
import json
import multiprocessing
import os
import signal
import sys
import time
import tracemalloc
import weakref
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from tests.benchmarks import running_region_metrics as metrics
from tests.fixtures.phase_03.running_regions import contract as readiness
from tests.fixtures.phase_03.running_regions import oracle as frozen_oracle

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# These paths are not members of the frozen P03-US08 86-path manifest. The
# hardened renewal governs them separately and only for Phase 04 table work.
PHASE_04_TABLE_ONLY_RENEWAL_PATHS = frozenset(
    {
        "app/services/table_semantics.py",
        "frontend/lib/table-semantics.ts",
        "frontend/tests/p04-us01-table-readiness.test.mts",
        "frontend/tests/p04-us01-table-span-fidelity.test.mts",
        "frontend/tests/p04-tables.test.mts",
    }
)
PHASE_04_TABLE_READINESS_IDENTITY = {
    "path": "frontend/tests/p04-us01-table-readiness.test.mts",
    "size_bytes": 2_156,
    "sha256": "ffc15e1ed0511b20a34bdead5342345b521f25e644b705806e2d9060a7d1f817",
}


def _assert_repository_code_is_frozen_or_phase_04_table_only(
    repository_code: set[str],
) -> None:
    outside_frozen_manifest = repository_code - metrics.REQUIRED_CODE_PATHS
    assert outside_frozen_manifest <= PHASE_04_TABLE_ONLY_RENEWAL_PATHS, (
        "app/frontend code outside frozen P03 custody and the exact separately "
        "governed Phase 04 table-only paths: "
        f"{sorted(outside_frozen_manifest - PHASE_04_TABLE_ONLY_RENEWAL_PATHS)}"
    )


@pytest.fixture(autouse=True)
def _frozen_offline_dependency_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for field, value in metrics.OFFLINE_ENVIRONMENT.items():
        monkeypatch.setenv(field, value)


def _file_identity(path: str, marker: str = "b") -> dict[str, Any]:
    return {"path": path, "size_bytes": 1, "sha256": marker * 64}


def _output_identity(marker: str = "c") -> dict[str, Any]:
    return {"size_bytes": 1, "sha256": marker * 64}


def _assert_process_and_group_gone(
    process_id: int,
    group_id: int,
    *,
    timeout_seconds: float = 2.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        process_gone = False
        group_gone = False
        try:
            os.kill(process_id, 0)
        except ProcessLookupError:
            process_gone = True
        except PermissionError:
            pass
        try:
            os.killpg(group_id, 0)
        except ProcessLookupError:
            group_gone = True
        except PermissionError:
            pass
        if process_gone and group_gone:
            return
        time.sleep(0.01)
    pytest.fail("worker descendant or process group survived bounded cleanup")


def _code_custody() -> dict[str, Any]:
    records = {
        path: {
            "path": path,
            "size_bytes": 1,
            "sha256": f"{index + 1:064x}",
        }
        for index, path in enumerate(sorted(metrics.REQUIRED_CODE_PATHS))
    }
    return metrics.build_code_custody(records, records)


def _dependency_custody() -> dict[str, Any]:
    return {
        "manifests": {
            path: _file_identity(path, "d")
            for path in metrics.DEPENDENCY_MANIFEST_PATHS
        },
        "python_packages": {
            distribution: {
                "distribution": distribution,
                "version": "1.0",
            }
            for distribution in metrics.DEPENDENCY_REQUIRED_PYTHON_PACKAGES
        },
        "local_tools": {
            name: {"name": name, "version": "1.0"}
            for name in metrics.DEPENDENCY_REQUIRED_LOCAL_TOOLS
        },
        "runtime": {"python_version": "3.13.5", "platform": "darwin"},
        "offline_environment": dict(metrics.OFFLINE_ENVIRONMENT),
    }


def _output_sizes() -> dict[str, Any]:
    paired: dict[str, list[dict[str, Any]]] = {
        target_id: [] for target_id in metrics.PERFORMANCE_TARGETS
    }
    for target_id, pair_index, state in metrics.PAIRED_WORKER_PLAN:
        paired[target_id].append(
            {
                "target_id": target_id,
                "pair_index": pair_index,
                "state": state,
                "variants": {
                    variant: _output_identity() for variant in metrics.OUTPUT_VARIANTS
                },
            }
        )
    return {
        "paired_samples": paired,
        "source_reports": {
            target_id: _output_identity("e")
            for target_id in metrics.PERFORMANCE_TARGETS
        },
        "isolated_projection_outputs": {
            target_id: _output_identity("f")
            for target_id in metrics.PERFORMANCE_TARGETS
        },
        "maximum_page_identity_json_bytes": 1,
        "maximum_running_descriptor_json_bytes": 1,
        "maximum_source_report_json_bytes": 1,
        "all_within_limits": True,
    }


def _measurement() -> dict[str, Any]:
    return {
        "performance_cases": list(metrics.PERFORMANCE_TARGETS),
        "pair_count_per_case": metrics.PAIRED_REPEAT_COUNT,
        "worker_process_count": metrics.PAIRED_WORKER_COUNT,
        "isolated_latency_warmups": metrics.ISOLATED_LATENCY_WARMUPS,
        "isolated_latency_samples": metrics.ISOLATED_LATENCY_SAMPLES,
        "isolated_allocation_warmups": metrics.ISOLATED_ALLOCATION_WARMUPS,
        "isolated_allocation_samples": metrics.ISOLATED_ALLOCATION_SAMPLES,
        "whole_parser_clock": metrics.WHOLE_PARSER_CLOCK,
        "whole_parser_scope": metrics.WHOLE_PARSER_SCOPE,
        "execution_order_policy": metrics.EXECUTION_ORDER_POLICY,
        "cache_disclaimer": metrics.CACHE_DISCLAIMER,
        "maximum_page_workload": dict(metrics.MAXIMUM_PAGE_WORKLOAD),
    }


def _policy() -> dict[str, Any]:
    return {
        "policy_id": metrics.POLICY_ID,
        "quantile_method": metrics.QUANTILE_METHOD,
        "quantile_formula": metrics.QUANTILE_FORMULA,
        "paired_fixed_ceilings_seconds": dict(metrics.PAIRED_FIXED_CEILINGS_SECONDS),
        "relative_ceiling_fraction": 0.05,
        "peak_rss_delta_ceiling_bytes": metrics.PEAK_RSS_DELTA_CEILING_BYTES,
        "source_extraction_p95_ceiling_seconds": (
            metrics.ISOLATED_SOURCE_EXTRACTION_P95_SECONDS
        ),
        "projection_p95_ceiling_seconds": (metrics.ISOLATED_PROJECTION_P95_SECONDS),
        "peak_allocation_ceiling_bytes": metrics.PEAK_ALLOCATION_CEILING_BYTES,
        "source_report_size_ceiling_bytes": int(
            metrics.RESOURCE_LIMITS["report_json_bytes"]
        ),
        "timing_paths_removed": list(metrics.TIMING_PATHS_REMOVED),
        "source_report_timing_paths_removed": list(
            metrics.SOURCE_REPORT_TIMING_PATHS_REMOVED
        ),
        "artifact_semantic_fields_removed": list(
            metrics.ARTIFACT_SEMANTIC_FIELDS_REMOVED
        ),
    }


def _settings_delta() -> dict[str, Any]:
    off = dict(frozen_oracle.PREDECESSOR_CONFIGURATION)
    off["layout_running_regions_enabled"] = False
    on = {**off, "layout_running_regions_enabled": True}
    return {
        "changed_fields": ["layout_running_regions_enabled"],
        "flag_off": off,
        "flag_on": on,
        "flag_off_sha256": hashlib.sha256(
            metrics._canonical_json(off).encode("utf-8")
        ).hexdigest(),
        "flag_on_sha256": hashlib.sha256(
            metrics._canonical_json(on).encode("utf-8")
        ).hexdigest(),
        "predecessor_flags_match": True,
    }


def _input_custody() -> dict[str, Any]:
    identities = deepcopy(frozen_oracle.SOURCE_IDENTITIES)
    return {
        "corpus_registry": deepcopy(frozen_oracle.CORPUS_REGISTRY_CUSTODY),
        "pre": deepcopy(identities),
        "post": deepcopy(identities),
        "source_count": len(identities),
        "page_count": sum(item["page_count"] for item in identities.values()),
        "total_size_bytes": sum(item["size_bytes"] for item in identities.values()),
        "all_expected_match": True,
        "pre_post_match": True,
    }


def _predecessor_custody() -> dict[str, Any]:
    outputs = deepcopy(frozen_oracle.PREDECESSOR_OUTPUT_IDENTITIES)
    return {
        "root": frozen_oracle.PREDECESSOR_OUTPUT_ROOT,
        "outputs": outputs,
        "configuration": deepcopy(frozen_oracle.PREDECESSOR_CONFIGURATION),
        "output_count": len(outputs),
        "total_size_bytes": sum(item["size_bytes"] for item in outputs.values()),
        "all_expected_match": True,
    }


def _component_custodies(code: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name, path in metrics.COMPONENT_PATHS.items():
        identity = code["post"][path]
        expected = metrics.COMPONENT_EXPECTED_SEMANTIC_SHA256[name]
        result[name] = {
            **identity,
            "semantic_sha256": expected,
            "expected_semantic_sha256": expected,
            "match": True,
        }
    return result


def _isolated_stage(stage: str, latency: float) -> dict[str, Any]:
    targets: dict[str, dict[str, Any]] = {}
    for target_id in metrics.PERFORMANCE_TARGETS:
        output_marker = "e" if stage == "source_extraction" else "f"
        measured_outputs = [
            {
                "measurement_kind": measurement_kind,
                "sample_index": sample_index,
                "output_identity": _output_identity(output_marker),
                "maximum_page_identity_json_bytes": (
                    None if stage == "source_extraction" else 1
                ),
                "maximum_running_descriptor_json_bytes": (
                    None if stage == "source_extraction" else 1
                ),
            }
            for measurement_kind, sample_count in (
                ("latency", metrics.ISOLATED_LATENCY_SAMPLES),
                ("allocation", metrics.ISOLATED_ALLOCATION_SAMPLES),
            )
            for sample_index in range(sample_count)
        ]
        summary = {
            "stage": stage,
            "target_id": target_id,
            "page_count": frozen_oracle.SOURCE_IDENTITIES[target_id]["page_count"],
            "comparison_count": (None if stage == "source_extraction" else 100),
            "maximum_page_comparisons": (None if stage == "source_extraction" else 50),
            "latency_p95_seconds": latency,
            "peak_allocation_bytes": 4_096,
            "passed": True,
        }
        targets[target_id] = {
            "protocol": readiness.isolated_measurement_protocol(stage, target_id),
            "latency_seconds": [latency] * metrics.ISOLATED_LATENCY_SAMPLES,
            "allocation_bytes": [4_096] * metrics.ISOLATED_ALLOCATION_SAMPLES,
            "warmup_successes": [True]
            * (metrics.ISOLATED_LATENCY_WARMUPS + metrics.ISOLATED_ALLOCATION_WARMUPS),
            "measured_output_successes": [True]
            * (metrics.ISOLATED_LATENCY_SAMPLES + metrics.ISOLATED_ALLOCATION_SAMPLES),
            "measured_outputs": measured_outputs,
            "report_sizes": (
                [1]
                * (
                    metrics.ISOLATED_LATENCY_SAMPLES
                    + metrics.ISOLATED_ALLOCATION_SAMPLES
                )
                if stage == "source_extraction"
                else []
            ),
            "predecessor_unchanged": (None if stage == "source_extraction" else True),
            "idempotent": None if stage == "source_extraction" else True,
            "retained_output": _output_identity(output_marker),
            "summary": summary,
        }
    return {"targets": targets, "all_pass": True}


def _deadline_record(name: str, hook: str | None = None) -> dict[str, Any]:
    limit = float(metrics.DEADLINE_LIMITS_SECONDS[name])
    return {
        "name": name,
        "production_hook": hook or f"production.{name}",
        "limit_seconds": limit,
        "limit_ns": round(limit * 1_000_000_000),
        "maximum_plus_one_delta_ns": 1_000,
        "exact_accepted": True,
        "maximum_plus_one_refused": True,
        "exact_clock_calls": 2,
        "maximum_plus_one_clock_calls": 2,
        "exact_outcome": "accepted",
        "maximum_plus_one_outcome": "refused:ReadinessContractError",
        "passed": True,
    }


def _maximum_page_execution() -> dict[str, Any]:
    hook = "production.project_maximum_page"
    return {
        "workload": dict(metrics.MAXIMUM_PAGE_WORKLOAD),
        "resource_accounting_hook": "production.account_maximum_page",
        "page_deadline_hook": hook,
        "accounted_workload": dict(metrics.MAXIMUM_PAGE_WORKLOAD),
        "resource_accounting_accepted": True,
        "page_deadline": _deadline_record("projection_page_deadline", hook=hook),
        "passed": True,
    }


def _resource_boundaries() -> dict[str, Any]:
    cases = {
        counter: {
            "counter": counter,
            "production_hook": f"production.validate_{counter}",
            "limit": int(metrics.RESOURCE_LIMITS[counter]),
            "exact_observed": int(metrics.RESOURCE_LIMITS[counter]),
            "exact_accepted": True,
            "maximum_plus_one_observed": int(metrics.RESOURCE_LIMITS[counter]) + 1,
            "maximum_plus_one_refused": True,
            "exact_outcome": "accepted",
            "maximum_plus_one_outcome": "refused:ReadinessContractError",
            "passed": True,
        }
        for counter in metrics.RESOURCE_COUNTERS
    }
    return {
        "cases": cases,
        "maximum_page_execution": _maximum_page_execution(),
        "all_pass": True,
    }


def _deadline_boundaries() -> dict[str, Any]:
    return {
        "cases": {
            name: _deadline_record(name) for name in metrics.DEADLINE_LIMITS_SECONDS
        },
        "all_pass": True,
    }


def _paired_parser() -> dict[str, Any]:
    runner_pid = 1_000
    plan = [dict(item) for item in readiness.paired_worker_plan()]
    workers: list[dict[str, Any]] = []
    for work in plan:
        enabled = work["state"] == "on"
        raw_rss = 1_010 if enabled else 1_000
        workers.append(
            {
                **work,
                "pid": 2_000 + work["worker_index"],
                "parent_pid": runner_pid,
                "wall_seconds": 10.1 if enabled else 10.0,
                "raw_ru_maxrss": raw_rss,
                "platform": "darwin",
                "exit_code": 0,
                "source_match": True,
                "code_match": True,
                "custody_match": True,
                "imports_loaded_before_timing": True,
                "settings_loaded_before_timing": True,
                "source_verified_before_timing": True,
                "timing_clock": metrics.WHOLE_PARSER_CLOCK,
                "timing_scope": metrics.WHOLE_PARSER_SCOPE,
                "output_variants": {
                    variant: _output_identity() for variant in metrics.OUTPUT_VARIANTS
                },
                "rss_bytes": raw_rss,
            }
        )
    targets: dict[str, Any] = {}
    for target_id in metrics.PERFORMANCE_TARGETS:
        off = [
            item
            for item in workers
            if item["target_id"] == target_id and item["state"] == "off"
        ]
        on = [
            item
            for item in workers
            if item["target_id"] == target_id and item["state"] == "on"
        ]
        targets[target_id] = json.loads(
            metrics._canonical_json(
                metrics._paired_performance_summary(
                    target_id,
                    off_seconds=[item["wall_seconds"] for item in off],
                    on_seconds=[item["wall_seconds"] for item in on],
                    off_rss_bytes=[item["rss_bytes"] for item in off],
                    on_rss_bytes=[item["rss_bytes"] for item in on],
                )
            )
        )
    return {
        "runner_pid": runner_pid,
        "worker_plan": plan,
        "workers": workers,
        "targets": targets,
        "all_pass": True,
    }


def _quality() -> dict[str, Any]:
    return {
        "reviewed_page_count": 30,
        "page_identity_exact_count": 30,
        "page_identity_denominator": 30,
        "running_region_exact_count": 47,
        "running_region_denominator": 47,
        "pairwise_order_exact_count": 47,
        "pairwise_order_denominator": 47,
        "manufacturing_header_exact_count": 3,
        "manufacturing_header_denominator": 3,
        "manufacturing_fused_contribution_exact": True,
        "manufacturing_public_owner_unchanged": True,
        "manufacturing_source_reconstruction_exact": True,
        "esg_cluster_exact": True,
        "false_printed_label_promotions": 0,
        "duplicate_canonical_contributions": 0,
        "missing_canonical_contributions": 0,
        "legacy_identity_mismatches": 0,
        "determinism_failures": 0,
        "all_pass": True,
    }


def _control_matrix() -> dict[str, Any]:
    cases: dict[str, Any] = {}
    for case_id, expected in metrics._CONTROL_EXPECTATIONS.items():
        cases[case_id] = {
            "case_id": case_id,
            "page_count": expected["page_count"],
            "expected_detected_labels": expected["detected_labels"],
            "observed_detected_labels": expected["detected_labels"],
            "expected_running_regions": expected["running_regions"],
            "observed_running_regions": expected["running_regions"],
            "legacy_identity_match": True,
            "flag_off_byte_match": True,
            "canonical_body_match": True,
            "canonical_full_match": True,
            "passed": True,
        }
    return {"cases": cases, "all_pass": True}


def _comparison_ledgers() -> dict[str, Any]:
    return {
        "targets": {
            target_id: {
                "target_id": target_id,
                "page_count": frozen_oracle.SOURCE_IDENTITIES[target_id]["page_count"],
                "comparison_count": 100,
                "maximum_page_comparisons": 50,
                "page_ceiling": int(metrics.RESOURCE_LIMITS["comparisons_per_page"]),
                "document_ceiling": int(
                    metrics.RESOURCE_LIMITS["comparisons_per_document"]
                ),
                "instrumentation_untimed": True,
                "indexed_algorithm": True,
                "passed": True,
            }
            for target_id in metrics.PERFORMANCE_TARGETS
        },
        "all_pass": True,
    }


def _rollback() -> dict[str, Any]:
    return {field: True for field in metrics.ROLLBACK_FIELDS}


def _aggregate(*, failure_free: bool) -> dict[str, Any]:
    result = {
        field: True
        for field in metrics.AGGREGATE_FIELDS
        if field not in {"failure_free", "all_pass"}
    }
    result["failure_free"] = failure_free
    result["all_pass"] = failure_free
    return result


def _artifact_candidate(
    *,
    status: str = "final_measurement_candidate",
    retained_path: str | None = None,
    failures: list[dict[str, Any]] | None = None,
    prior_failed_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    failure_records = failures or []
    code = _code_custody()
    components = _component_custodies(code)
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "record_kind": "p03_us08_running_region_metrics",
        "story": "P03-US08",
        "status": status,
        "generated_at": "2026-08-01T00:00:00+00:00",
        "retained_path": retained_path or str(metrics.FINAL_ARTIFACT_RELATIVE_PATH),
        "measurement": _measurement(),
        "policy": _policy(),
        "settings_delta": _settings_delta(),
        "m0_reference": json.loads(metrics._canonical_json(metrics.M0_ARTIFACT)),
        "input_custody": _input_custody(),
        "predecessor_custody": _predecessor_custody(),
        **components,
        "code_sha256": code,
        "dependency_custody": _dependency_custody(),
        "source_extraction": _isolated_stage("source_extraction", 0.001),
        "running_region_projection": _isolated_stage(
            "running_region_projection", 0.001
        ),
        "resource_boundaries": _resource_boundaries(),
        "deadline_boundaries": _deadline_boundaries(),
        "paired_parser": _paired_parser(),
        "quality": _quality(),
        "control_matrix": _control_matrix(),
        "comparison_ledgers": _comparison_ledgers(),
        "output_sizes": _output_sizes(),
        "rollback": _rollback(),
        "prior_failed_candidates": prior_failed_candidates or [],
        "failures": failure_records,
        "aggregate": _aggregate(failure_free=not failure_records),
        **metrics.HOSTED_USAGE,
    }
    assert set(payload) == set(metrics.ARTIFACT_TOP_LEVEL_FIELDS) - {"semantic_sha256"}
    return payload


def _observed_code_files(candidate: dict[str, Any]) -> dict[str, Any]:
    custody = candidate.get("code_sha256")
    if not isinstance(custody, dict) or not isinstance(custody.get("post"), dict):
        return {}
    return deepcopy(custody["post"])


def _write_required_repository_files(repository_root: Path) -> dict[str, Any]:
    for index, relative_path in enumerate(sorted(metrics.REQUIRED_CODE_PATHS)):
        path = repository_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"required-file-{index}:{relative_path}\n".encode())
    for relative_path in metrics.DEPENDENCY_MANIFEST_PATHS:
        source = PROJECT_ROOT / relative_path
        destination = repository_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    frozen_paths = [
        metrics.M0_ARTIFACT["path"],
        frozen_oracle.CORPUS_REGISTRY_CUSTODY["path"],
        *(identity["path"] for identity in frozen_oracle.SOURCE_IDENTITIES.values()),
        *(
            str(
                Path(frozen_oracle.PREDECESSOR_OUTPUT_ROOT)
                / case_id
                / "our-output.json"
            )
            for case_id in frozen_oracle.PREDECESSOR_OUTPUT_IDENTITIES
        ),
    ]
    for relative_path in frozen_paths:
        source = PROJECT_ROOT / relative_path
        destination = repository_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.link(source, destination)
    return metrics.collect_code_file_identities(repository_root)


def _bind_candidate_to_repository_code(
    candidate: dict[str, Any],
    observed_code_files: dict[str, Any],
    *,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    code = metrics.build_code_custody(
        observed_code_files,
        observed_code_files,
    )
    candidate["code_sha256"] = code
    candidate.update(_component_custodies(code))
    if repository_root is not None:
        candidate["dependency_custody"] = metrics.collect_dependency_custody(
            repository_root
        )
    return candidate


def _observed_input_files(_candidate: dict[str, Any]) -> dict[str, Any]:
    custody = _input_custody()
    return {
        "corpus_registry": {
            field: custody["corpus_registry"][field]
            for field in metrics.CODE_FILE_IDENTITY_FIELDS
        },
        "sources": {
            case_id: {
                field: identity[field] for field in metrics.CODE_FILE_IDENTITY_FIELDS
            }
            for case_id, identity in custody["post"].items()
        },
    }


def _seal_metrics_artifact(
    candidate: dict[str, Any],
    *,
    existing_paths: tuple[str, ...] | list[str] = (),
    observed_prior_artifacts: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return metrics._seal_metrics_artifact_with_observations(
        candidate,
        existing_paths=existing_paths,
        observed_code_files=_observed_code_files(candidate),
        observed_dependency_custody=_dependency_custody(),
        observed_input_custody=_observed_input_files(candidate),
        observed_m0_identity={
            field: metrics.M0_ARTIFACT[field]
            for field in metrics.CODE_FILE_IDENTITY_FIELDS
        },
        observed_predecessor_outputs=deepcopy(_predecessor_custody()["outputs"]),
        observed_prior_artifacts=observed_prior_artifacts or {},
    )


def _validate_metrics_artifact(
    artifact: dict[str, Any],
    *,
    existing_paths: tuple[str, ...] | list[str] = (),
    observed_prior_artifacts: dict[str, dict[str, Any]] | None = None,
) -> None:
    metrics._validate_metrics_artifact_with_observations(
        artifact,
        existing_paths=existing_paths,
        observed_code_files=_observed_code_files(artifact),
        observed_dependency_custody=_dependency_custody(),
        observed_input_custody=_observed_input_files(artifact),
        observed_m0_identity={
            field: metrics.M0_ARTIFACT[field]
            for field in metrics.CODE_FILE_IDENTITY_FIELDS
        },
        observed_predecessor_outputs=deepcopy(_predecessor_custody()["outputs"]),
        observed_prior_artifacts=observed_prior_artifacts or {},
    )


def _paired_output_prefix(campaign: dict[str, Any]) -> dict[str, Any]:
    samples: dict[str, list[dict[str, Any]]] = {}
    for worker in campaign["workers"]:
        samples.setdefault(worker["target_id"], []).append(
            {
                "target_id": worker["target_id"],
                "pair_index": worker["pair_index"],
                "state": worker["state"],
                "variants": deepcopy(worker["output_variants"]),
            }
        )
    return samples


def _failed_paired_candidate(
    completed_worker_count: int,
    *,
    failure_type: str = "worker_exit",
    retained_path: str = (
        "tracker/phase-03-layout/evidence/"
        "P03-US08-running-region-metrics-attempt-01-failed.json"
    ),
    prior_failed_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    full = _paired_parser()
    failed_work = full["worker_plan"][completed_worker_count]
    failure = {
        "type": failure_type,
        "stage": "paired_parser",
        "target_id": failed_work["target_id"],
        "pair_index": failed_work["pair_index"],
        "state": failed_work["state"],
    }
    candidate = _artifact_candidate(
        status="failed_measurement_candidate",
        retained_path=retained_path,
        failures=[failure],
        prior_failed_candidates=prior_failed_candidates,
    )
    candidate["paired_parser"] = {
        "runner_pid": full["runner_pid"],
        "worker_plan": full["worker_plan"][:completed_worker_count],
        "workers": full["workers"][:completed_worker_count],
        "targets": {},
        "all_pass": False,
    }
    candidate["output_sizes"]["paired_samples"] = _paired_output_prefix(
        candidate["paired_parser"]
    )
    candidate["aggregate"]["paired_parser"] = False
    candidate["aggregate"]["output_sizes"] = False
    candidate["aggregate"]["all_pass"] = False
    return candidate


def _failed_stage_candidate(
    stage: str,
    failed_target: str,
) -> dict[str, Any]:
    candidate = _artifact_candidate(
        status="failed_measurement_candidate",
        retained_path=(
            "tracker/phase-03-layout/evidence/"
            "P03-US08-running-region-metrics-attempt-01-failed.json"
        ),
        failures=[
            {
                "type": "stage_failed",
                "stage": stage,
                "target_id": failed_target,
                "pair_index": None,
                "state": None,
            }
        ],
    )
    target_index = metrics.PERFORMANCE_TARGETS.index(failed_target)
    future_targets = metrics.PERFORMANCE_TARGETS[target_index + 1 :]
    if stage in {"source_extraction", "running_region_projection"}:
        ceiling = (
            metrics.ISOLATED_SOURCE_EXTRACTION_P95_SECONDS
            if stage == "source_extraction"
            else metrics.ISOLATED_PROJECTION_P95_SECONDS
        )
        target = candidate[stage]["targets"][failed_target]
        target["latency_seconds"] = [ceiling + 0.001] * len(target["latency_seconds"])
        target["summary"]["latency_p95_seconds"] = ceiling + 0.001
        target["summary"]["passed"] = False
        candidate[stage]["all_pass"] = False
        output_field = (
            "source_reports"
            if stage == "source_extraction"
            else "isolated_projection_outputs"
        )
        for target_id in future_targets:
            candidate[stage]["targets"].pop(target_id)
            candidate["output_sizes"][output_field].pop(target_id)
            if stage == "running_region_projection":
                candidate["comparison_ledgers"]["targets"].pop(target_id)
        if future_targets:
            candidate["output_sizes"]["all_within_limits"] = True
            candidate["aggregate"]["output_sizes"] = False
            if stage == "running_region_projection":
                candidate["comparison_ledgers"]["all_pass"] = False
                candidate["aggregate"]["comparison_ledgers"] = False
    elif stage == "comparison_ledgers":
        target = candidate[stage]["targets"][failed_target]
        target["instrumentation_untimed"] = False
        target["passed"] = False
        candidate[stage]["all_pass"] = False
        for target_id in future_targets:
            candidate[stage]["targets"].pop(target_id)
    else:
        raise AssertionError(stage)
    candidate["aggregate"][stage] = False
    candidate["aggregate"]["all_pass"] = False
    return candidate


def _refresh_paired_summaries(paired: dict[str, Any]) -> None:
    summaries: dict[str, Any] = {}
    for target_id in metrics.PERFORMANCE_TARGETS:
        by_state = {
            state: [
                worker
                for worker in paired["workers"]
                if worker["target_id"] == target_id and worker["state"] == state
            ]
            for state in ("off", "on")
        }
        summaries[target_id] = json.loads(
            metrics._canonical_json(
                metrics._paired_performance_summary(
                    target_id,
                    off_seconds=[worker["wall_seconds"] for worker in by_state["off"]],
                    on_seconds=[worker["wall_seconds"] for worker in by_state["on"]],
                    off_rss_bytes=[worker["rss_bytes"] for worker in by_state["off"]],
                    on_rss_bytes=[worker["rss_bytes"] for worker in by_state["on"]],
                )
            )
        )
    paired["targets"] = summaries
    paired["all_pass"] = all(summary["passed"] for summary in summaries.values())


def _failed_complete_paired_gate_candidate(
    failed_target: str,
    gate: str,
) -> dict[str, Any]:
    candidate = _artifact_candidate(
        status="failed_measurement_candidate",
        retained_path=(
            "tracker/phase-03-layout/evidence/"
            "P03-US08-running-region-metrics-attempt-01-failed.json"
        ),
        failures=[
            {
                "type": "stage_failed",
                "stage": "paired_parser",
                "target_id": failed_target,
                "pair_index": None,
                "state": None,
            }
        ],
    )
    paired = candidate["paired_parser"]
    for worker in paired["workers"]:
        if worker["target_id"] != failed_target or worker["state"] != "on":
            continue
        if gate == "latency":
            worker["wall_seconds"] = 20.0
        elif gate == "rss":
            rss = 1_000 + metrics.PEAK_RSS_DELTA_CEILING_BYTES + 1
            worker["raw_ru_maxrss"] = rss
            worker["rss_bytes"] = rss
        else:
            raise AssertionError(gate)
    _refresh_paired_summaries(paired)
    candidate["aggregate"]["paired_parser"] = False
    candidate["aggregate"]["all_pass"] = False
    return candidate


def _failed_output_size_candidate(
    reported_target: str | None = "uber-earnings",
    *,
    failed_target: str = "uber-earnings",
) -> dict[str, Any]:
    candidate = _artifact_candidate(
        status="failed_measurement_candidate",
        retained_path=(
            "tracker/phase-03-layout/evidence/"
            "P03-US08-running-region-metrics-attempt-01-failed.json"
        ),
        failures=[
            {
                "type": "stage_failed",
                "stage": "output_sizes",
                "target_id": reported_target,
                "pair_index": None,
                "state": None,
            }
        ],
    )
    over_limit = int(metrics.RESOURCE_LIMITS["page_identity_json_bytes"]) + 1
    measured = candidate["running_region_projection"]["targets"][failed_target][
        "measured_outputs"
    ][0]
    measured["maximum_page_identity_json_bytes"] = over_limit
    candidate["output_sizes"]["maximum_page_identity_json_bytes"] = over_limit
    candidate["output_sizes"]["all_within_limits"] = False
    candidate["aggregate"]["output_sizes"] = False

    target_index = metrics.PERFORMANCE_TARGETS.index(failed_target)
    retained_targets = set(metrics.PERFORMANCE_TARGETS[: target_index + 1])
    future_targets = set(metrics.PERFORMANCE_TARGETS) - retained_targets
    for stage in ("source_extraction", "running_region_projection"):
        for target_id in future_targets:
            candidate[stage]["targets"].pop(target_id)
        candidate[stage]["all_pass"] = True
    for target_id in future_targets:
        candidate["comparison_ledgers"]["targets"].pop(target_id)
    candidate["comparison_ledgers"]["all_pass"] = True
    for target_id in future_targets:
        candidate["output_sizes"]["source_reports"].pop(target_id)
        candidate["output_sizes"]["isolated_projection_outputs"].pop(target_id)
        candidate["output_sizes"]["paired_samples"].pop(target_id)

    paired = candidate["paired_parser"]
    paired["worker_plan"] = [
        work for work in paired["worker_plan"] if work["target_id"] in retained_targets
    ]
    paired["workers"] = [
        worker
        for worker in paired["workers"]
        if worker["target_id"] in retained_targets
    ]
    for target_id in future_targets:
        paired["targets"].pop(target_id)
    paired["all_pass"] = True
    return candidate


def test_authoritative_constants_and_exact_twenty_worker_plan_are_reused() -> None:
    assert metrics.PERFORMANCE_TARGETS == ("uber-earnings", "ny-timetable")
    assert metrics.PAIRED_REPEAT_COUNT == 5
    assert metrics.PAIRED_WORKER_COUNT == 20
    assert metrics.PAIRED_FIXED_CEILINGS_SECONDS == {
        "uber-earnings": 1.4575,
        "ny-timetable": 2.3380,
    }
    assert metrics.PEAK_RSS_DELTA_CEILING_BYTES == 64 * 1024 * 1024
    assert metrics.PEAK_ALLOCATION_CEILING_BYTES == 64 * 1024 * 1024
    assert metrics.ISOLATED_SOURCE_EXTRACTION_P95_SECONDS == 0.250
    assert metrics.ISOLATED_PROJECTION_P95_SECONDS == 0.050
    assert (
        metrics.ISOLATED_LATENCY_WARMUPS,
        metrics.ISOLATED_LATENCY_SAMPLES,
    ) == (2, 20)
    assert (
        metrics.ISOLATED_ALLOCATION_WARMUPS,
        metrics.ISOLATED_ALLOCATION_SAMPLES,
    ) == (1, 5)
    assert metrics.PAIRED_WORKER_PLAN == readiness.PAIRED_CASES
    assert (
        tuple(
            (record["target_id"], record["pair_index"], record["state"])
            for record in readiness.paired_worker_plan()
        )
        == metrics.PAIRED_WORKER_PLAN
    )
    assert [metrics._paired_states(index) for index in range(5)] == [
        (False, True),
        (True, False),
        (False, True),
        (True, False),
        (False, True),
    ]
    with pytest.raises(readiness.ReadinessContractError):
        metrics._paired_states(5)
    with pytest.raises(readiness.ReadinessContractError):
        metrics._paired_states(True)


def test_named_maximum_page_workload_is_authoritative_exact_and_closed() -> None:
    assert metrics.MAXIMUM_PAGE_FIXTURE_ID == (
        "synthetic:p03-us08:maximum-page-performance-v1"
    )
    assert metrics.MAXIMUM_PAGE_WORKLOAD is readiness.MAXIMUM_PAGE_WORKLOAD
    assert metrics.MAXIMUM_PAGE_WORKLOAD_FIELDS is (
        readiness.MAXIMUM_PAGE_WORKLOAD_FIELDS
    )
    assert dict(metrics.MAXIMUM_PAGE_WORKLOAD) == {
        "fixture_id": metrics.MAXIMUM_PAGE_FIXTURE_ID,
        "policy_id": metrics.POLICY_ID,
        "physical_page_index": 1,
        "source_character_count": 500_000,
        "source_word_count": 100_000,
        "label_candidate_count": 64,
        "boundary_candidate_count": 512,
        "accepted_running_region_count": 64,
        "extracted_contribution_count": 8,
        "extracted_intervals_per_contribution": 8,
        "extracted_residual_plan_bytes": 16_384,
        "indexed_comparison_count": 4_096,
        "concern_count": 64,
        "deadline_seconds": 0.250,
    }
    metrics.validate_maximum_page_workload(metrics.MAXIMUM_PAGE_WORKLOAD)

    off_by_one = dict(metrics.MAXIMUM_PAGE_WORKLOAD)
    off_by_one["indexed_comparison_count"] += 1
    with pytest.raises(readiness.ReadinessContractError, match="differs"):
        metrics.validate_maximum_page_workload(off_by_one)

    unknown = {**metrics.MAXIMUM_PAGE_WORKLOAD, "unknown": True}
    with pytest.raises(readiness.ReadinessContractError, match="keys"):
        metrics.validate_maximum_page_workload(unknown)


def test_code_sha256_manifest_schema_is_closed_and_pre_post_bound() -> None:
    assert metrics.CODE_CUSTODY_FIELDS is readiness.CODE_CUSTODY_FIELDS
    assert metrics.CODE_CUSTODY_RECORD_FIELDS is (readiness.CODE_CUSTODY_RECORD_FIELDS)
    custody = _code_custody()
    metrics.validate_code_custody(custody)
    assert set(custody) == set(metrics.CODE_CUSTODY_FIELDS)
    assert custody["pre_post_match"] is True
    assert (
        custody["manifest_sha256"]
        == hashlib.sha256(
            metrics._canonical_json(custody["post"]).encode("utf-8")
        ).hexdigest()
    )

    record_unknown = deepcopy(custody)
    path = next(iter(record_unknown["post"]))
    record_unknown["post"][path]["unknown"] = True
    with pytest.raises(readiness.ReadinessContractError, match="keys"):
        metrics.validate_code_custody(record_unknown)

    wrong_manifest = {**custody, "manifest_sha256": "f" * 64}
    with pytest.raises(readiness.ReadinessContractError, match="manifest"):
        metrics.validate_code_custody(wrong_manifest)

    different_post = {path: _file_identity(path, "a") for path in custody["post"]}
    mismatch = metrics.build_code_custody(custody["pre"], different_post)
    assert mismatch["pre_post_match"] is False
    final = _artifact_candidate()
    final["code_sha256"] = mismatch
    with pytest.raises(readiness.ReadinessContractError, match="custody"):
        _seal_metrics_artifact(final)


def test_dependency_custody_schema_has_exact_members_and_closed_records() -> None:
    assert metrics.DEPENDENCY_CUSTODY_FIELDS is (readiness.DEPENDENCY_CUSTODY_FIELDS)
    assert metrics.DEPENDENCY_MANIFEST_PATHS is (readiness.DEPENDENCY_MANIFEST_PATHS)
    assert metrics.DEPENDENCY_REQUIRED_PYTHON_PACKAGES is (
        readiness.DEPENDENCY_REQUIRED_PYTHON_PACKAGES
    )
    assert metrics.DEPENDENCY_REQUIRED_LOCAL_TOOLS is (
        readiness.DEPENDENCY_REQUIRED_LOCAL_TOOLS
    )
    custody = _dependency_custody()
    metrics.validate_dependency_custody(custody)

    missing_manifest = deepcopy(custody)
    missing_manifest["manifests"].pop("uv.lock")
    with pytest.raises(readiness.ReadinessContractError, match="manifest set"):
        metrics.validate_dependency_custody(missing_manifest)

    package_unknown = deepcopy(custody)
    package_unknown["python_packages"]["docling"]["unknown"] = True
    with pytest.raises(readiness.ReadinessContractError, match="keys"):
        metrics.validate_dependency_custody(package_unknown)

    changed_offline = deepcopy(custody)
    changed_offline["offline_environment"]["HF_HUB_OFFLINE"] = "0"
    with pytest.raises(readiness.ReadinessContractError, match="offline"):
        metrics.validate_dependency_custody(changed_offline)


def test_output_sizes_schema_closes_order_variants_identities_and_caps() -> None:
    assert metrics.OUTPUT_SIZES_FIELDS is readiness.OUTPUT_SIZES_FIELDS
    assert metrics.OUTPUT_SAMPLE_FIELDS is readiness.OUTPUT_SAMPLE_FIELDS
    assert metrics.OUTPUT_VARIANTS is readiness.OUTPUT_VARIANTS
    assert metrics.OUTPUT_IDENTITY_FIELDS is readiness.OUTPUT_IDENTITY_FIELDS
    output_sizes = _output_sizes()
    metrics.validate_output_sizes(output_sizes, complete=True)

    unknown = {**output_sizes, "unknown": True}
    with pytest.raises(readiness.ReadinessContractError, match="keys"):
        metrics.validate_output_sizes(unknown, complete=True)

    incomplete = deepcopy(output_sizes)
    for field in (
        "paired_samples",
        "source_reports",
        "isolated_projection_outputs",
    ):
        incomplete[field].pop("ny-timetable")
    metrics.validate_output_sizes(incomplete, complete=False)
    with pytest.raises(readiness.ReadinessContractError, match="incomplete"):
        metrics.validate_output_sizes(incomplete, complete=True)

    wrong_order = deepcopy(output_sizes)
    wrong_order["paired_samples"]["uber-earnings"][:2] = reversed(
        wrong_order["paired_samples"]["uber-earnings"][:2]
    )
    with pytest.raises(readiness.ReadinessContractError, match="order"):
        metrics.validate_output_sizes(wrong_order, complete=True)

    missing_variant = deepcopy(output_sizes)
    sample = missing_variant["paired_samples"]["uber-earnings"][0]
    sample["variants"].pop("raw_json")
    with pytest.raises(readiness.ReadinessContractError, match="variant"):
        metrics.validate_output_sizes(missing_variant, complete=True)

    identity_unknown = deepcopy(output_sizes)
    identity_unknown["source_reports"]["uber-earnings"]["unknown"] = True
    with pytest.raises(readiness.ReadinessContractError, match="keys"):
        metrics.validate_output_sizes(identity_unknown, complete=True)

    over_cap = deepcopy(output_sizes)
    over_cap["maximum_source_report_json_bytes"] = (
        int(metrics.RESOURCE_LIMITS["report_json_bytes"]) + 1
    )
    over_cap["all_within_limits"] = False
    metrics.validate_output_sizes(over_cap, complete=False)
    with pytest.raises(readiness.ReadinessContractError, match="exceed"):
        metrics.validate_output_sizes(over_cap, complete=True)


def test_nearest_rank_has_no_interpolation_and_rejects_invalid_samples() -> None:
    assert metrics._inclusive_p95([1, 2, 3, 4, 5]) == 5
    assert metrics._inclusive_p95(list(range(1, 21))) == 19
    assert metrics.QUANTILE_FORMULA == ("sorted(samples)[ceil(0.95 * n) - 1]")
    for samples in ([], [-0.1], [float("inf")], [True]):
        with pytest.raises(readiness.ReadinessContractError):
            metrics._inclusive_p95(samples)  # type: ignore[arg-type]


def test_quality_adjacency_uses_stable_logical_header_body_footer_order() -> None:
    items = [
        {"id": "body-1"},
        {
            "id": "footer",
            "running_region": {"role": "navigation_bottom"},
        },
        {"id": "body-2"},
        {
            "id": "synthetic-header",
            "running_region": {"role": "header"},
        },
    ]
    assert [item["id"] for item in metrics._logical_page_items(items)] == [
        "synthetic-header",
        "body-1",
        "body-2",
        "footer",
    ]
    with pytest.raises(metrics.MetricsExecutionError):
        metrics._logical_page_items([{"id": "valid"}, "invalid"])


def test_paired_summary_uses_clipping_dual_ceiling_and_pairwise_rss() -> None:
    summary = metrics._paired_performance_summary(
        "uber-earnings",
        off_seconds=[10.0] * 5,
        on_seconds=[9.0, 9.0, 9.0, 9.0, 10.7],
        off_rss_bytes=[1_000, 2_000, 1_000, 2_000, 1_000],
        on_rss_bytes=[1_100, 1_000, 1_300, 1_500, 1_050],
    )

    assert summary["signed_seconds"] == pytest.approx((-1.0, -1.0, -1.0, -1.0, 0.7))
    assert summary["clipped_seconds"] == pytest.approx((0.0, 0.0, 0.0, 0.0, 0.7))
    assert summary["overhead_p95_seconds"] == pytest.approx(0.7)
    assert summary["off_p95_seconds"] == 10.0
    assert summary["relative_ceiling_seconds"] == 0.5
    assert summary["fixed_ceiling_seconds"] == 1.4575
    assert summary["effective_ceiling_seconds"] == 0.5
    assert summary["rss_delta_bytes"] == (100, 0, 300, 0, 50)
    assert summary["peak_rss_delta_bytes"] == 300
    assert summary["passed"] is False


def test_ru_maxrss_normalization_is_platform_exact_and_closed() -> None:
    assert metrics._rss_bytes_from_maxrss(123, platform_name="darwin") == 123
    assert metrics._rss_bytes_from_maxrss(123, platform_name="linux") == 125_952
    for raw, platform in ((True, "darwin"), (-1, "linux"), (1, "freebsd")):
        with pytest.raises(readiness.ReadinessContractError):
            metrics._rss_bytes_from_maxrss(raw, platform_name=platform)  # type: ignore[arg-type]


def test_semantic_normalizers_remove_exactly_ten_plus_one_plus_two_fields() -> None:
    document = {
        "processing": {
            "duration_ms": 12,
            "form_semantics": {
                "extraction_ms": 1.0,
                "projection_ms": 2.0,
                "total_ms": 3.0,
                "preserved": "form",
            },
            "outline_structure": {
                "extraction_ms": 4.0,
                "projection_ms": 5.0,
                "total_ms": 9.0,
                "preserved": "outline",
            },
            "running_regions": {
                "extraction_ms": 6.0,
                "projection_ms": 7.0,
                "total_ms": 13.0,
                "preserved": "running",
            },
            "other": {"duration_ms": 99},
        },
        "duration_ms": 88,
    }
    normalized = metrics._semantic_payload(document)

    assert metrics.TIMING_PATHS_REMOVED == (
        "processing.duration_ms",
        "processing.form_semantics.extraction_ms",
        "processing.form_semantics.projection_ms",
        "processing.form_semantics.total_ms",
        "processing.outline_structure.extraction_ms",
        "processing.outline_structure.projection_ms",
        "processing.outline_structure.total_ms",
        "processing.running_regions.extraction_ms",
        "processing.running_regions.projection_ms",
        "processing.running_regions.total_ms",
    )
    assert normalized == {
        "processing": {
            "form_semantics": {"preserved": "form"},
            "outline_structure": {"preserved": "outline"},
            "running_regions": {"preserved": "running"},
            "other": {"duration_ms": 99},
        },
        "duration_ms": 88,
    }
    assert metrics._report_semantic_payload(
        {"extraction_ms": 1.0, "projection_ms": 2.0, "preserved": True}
    ) == {"projection_ms": 2.0, "preserved": True}
    artifact = {
        "generated_at": "first",
        "semantic_sha256": "a" * 64,
        "measurement": {"generated_at": "preserved"},
    }
    assert metrics._artifact_semantic_payload(artifact) == {
        "measurement": {"generated_at": "preserved"}
    }


def test_timing_profile_is_exact_releases_outputs_and_never_traces() -> None:
    class Payload:
        pass

    preparation_count = 0
    operation_count = 0
    references: list[weakref.ReferenceType[Payload]] = []
    ticks = iter(
        value
        for index in range(metrics.ISOLATED_LATENCY_SAMPLES)
        for value in (index * 2_000_000, index * 2_000_000 + 1_000_000)
    )

    def prepare() -> None:
        nonlocal preparation_count
        preparation_count += 1

    def operation(_prepared: None) -> Payload:
        nonlocal operation_count
        operation_count += 1
        assert tracemalloc.is_tracing() is False
        if operation_count > metrics.ISOLATED_LATENCY_WARMUPS:
            assert gc.isenabled() is False
        return Payload()

    profile = metrics._profile_timing(
        prepare,
        operation,
        observe_result=lambda result: references.append(weakref.ref(result)),
        clock_ns=lambda: next(ticks),
    )
    gc.collect()

    assert preparation_count == operation_count == 22
    assert len(references) == 22
    assert all(reference() is None for reference in references)
    assert profile.warmup_count == 2
    assert profile.sample_count == 20
    assert profile.samples_seconds == (0.001,) * 20
    assert profile.p95_seconds == 0.001
    assert profile.timing_tracemalloc_enabled is False
    assert profile.as_dict()["quantile_formula"] == metrics.QUANTILE_FORMULA

    tracemalloc.start()
    try:
        with pytest.raises(metrics.MetricsExecutionError, match="disabled"):
            metrics._profile_timing(prepare, operation)
    finally:
        tracemalloc.stop()


def test_timing_profile_restores_gc_state_after_success_and_error() -> None:
    initially_enabled = gc.isenabled()
    calls = 0

    def successful(_prepared: None) -> object:
        nonlocal calls
        calls += 1
        if calls > metrics.ISOLATED_LATENCY_WARMUPS:
            assert gc.isenabled() is False
        return object()

    metrics._profile_timing(lambda: None, successful)
    assert gc.isenabled() is initially_enabled

    calls = 0

    def failing(_prepared: None) -> object:
        nonlocal calls
        calls += 1
        if calls > metrics.ISOLATED_LATENCY_WARMUPS:
            assert gc.isenabled() is False
            raise RuntimeError("timed failure")
        return object()

    with pytest.raises(RuntimeError, match="timed failure"):
        metrics._profile_timing(lambda: None, failing)
    assert gc.isenabled() is initially_enabled


def test_allocation_profile_is_separate_resets_tracer_and_releases_outputs() -> None:
    class Payload:
        def __init__(self) -> None:
            self.data = bytearray(4_096)

    preparation_count = 0
    operation_count = 0
    references: list[weakref.ReferenceType[Payload]] = []

    def prepare() -> None:
        nonlocal preparation_count
        preparation_count += 1

    def operation(_prepared: None) -> Payload:
        nonlocal operation_count
        operation_count += 1
        return Payload()

    profile = metrics._profile_allocation(
        prepare,
        operation,
        observe_result=lambda result: references.append(weakref.ref(result)),
    )
    gc.collect()

    assert preparation_count == operation_count == 6
    assert len(references) == 6
    assert all(reference() is None for reference in references)
    assert profile.warmup_count == 1
    assert profile.sample_count == 5
    assert len(profile.peak_allocated_samples_bytes) == 5
    assert min(profile.peak_allocated_samples_bytes) >= 4_096
    assert profile.peak_allocated_bytes == max(profile.peak_allocated_samples_bytes)
    assert profile.peak_allocated_bytes <= metrics.PEAK_ALLOCATION_CEILING_BYTES
    assert profile.timing_claim is False
    assert tracemalloc.is_tracing() is False


def test_resource_boundary_interface_invokes_one_production_hook_twice() -> None:
    limit = int(metrics.RESOURCE_LIMITS["label_utf8_bytes"])
    calls: list[int] = []

    def production(payload: str) -> int:
        calls.append(len(payload.encode("utf-8")))
        return readiness.validate_resource_payload("label_utf8_bytes", payload)

    result = metrics.exercise_production_boundary(
        "label_utf8_bytes",
        exact_payload="é" * (limit // 2),
        maximum_plus_one_payload=("é" * (limit // 2)) + "x",
        measure=lambda payload: len(payload.encode("utf-8")),
        production_validator=production,
        production_hook="production.normalize_page_label",
        is_expected_refusal=lambda exc: isinstance(
            exc, readiness.ReadinessContractError
        ),
    )

    assert calls == [limit, limit + 1]
    assert result.exact_accepted is True
    assert result.maximum_plus_one_refused is True
    assert result.passed is True
    assert result.as_dict()["production_hook"] == ("production.normalize_page_label")


def test_resource_boundary_interface_does_not_mislabel_unexpected_errors() -> None:
    limit = int(metrics.RESOURCE_LIMITS["label_utf8_bytes"])

    def broken(_payload: str) -> None:
        raise RuntimeError("implementation bug")

    with pytest.raises(metrics.MetricsExecutionError, match="non-refusal"):
        metrics.exercise_production_boundary(
            "label_utf8_bytes",
            exact_payload="x" * limit,
            maximum_plus_one_payload="x" * (limit + 1),
            measure=len,
            production_validator=broken,
            production_hook="production.broken",
            is_expected_refusal=lambda exc: isinstance(
                exc, readiness.ReadinessContractError
            ),
        )


def test_deadline_interface_uses_exact_and_one_microsecond_over_clocks() -> None:
    calls: list[tuple[int, int]] = []

    def production(clock: Any) -> float:
        start = clock()
        finish = clock()
        calls.append((start, finish))
        return readiness.validate_deadline_window(
            "projection_page_deadline",
            start / 1_000_000_000,
            finish / 1_000_000_000,
        )

    result = metrics.exercise_production_deadline(
        "projection_page_deadline",
        production_operation=production,
        production_hook="production.project_page",
        is_expected_refusal=lambda exc: isinstance(
            exc, readiness.ReadinessContractError
        ),
    )

    assert len(calls) == 2
    assert calls[0][1] - calls[0][0] == 250_000_000
    assert calls[1][1] - calls[1][0] == 250_001_000
    assert result.limit_ns == 250_000_000
    assert result.maximum_plus_one_delta_ns == 1_000
    assert result.exact_accepted is True
    assert result.maximum_plus_one_refused is True
    assert result.exact_clock_calls == result.maximum_plus_one_clock_calls == 2
    assert result.passed is True


def test_named_maximum_page_payload_executes_both_production_hooks() -> None:
    accounting_calls: list[dict[str, Any]] = []
    deadline_calls: list[tuple[str, int]] = []

    def account(workload: Any) -> dict[str, Any]:
        detached = dict(workload)
        accounting_calls.append(detached)
        return detached

    def project(workload: Any, clock: Any) -> float:
        assert dict(workload) == dict(metrics.MAXIMUM_PAGE_WORKLOAD)
        start = clock()
        finish = clock()
        deadline_calls.append((workload["fixture_id"], finish - start))
        return readiness.validate_deadline_window(
            "projection_page_deadline",
            start / 1_000_000_000,
            finish / 1_000_000_000,
        )

    result = metrics.execute_maximum_page_workload(
        resource_accountant=account,
        resource_accounting_hook="production.account_maximum_page",
        page_operation=project,
        page_deadline_hook="production.project_maximum_page",
        is_expected_refusal=lambda exc: isinstance(
            exc, readiness.ReadinessContractError
        ),
    )

    assert accounting_calls == [dict(metrics.MAXIMUM_PAGE_WORKLOAD)]
    assert deadline_calls == [
        (metrics.MAXIMUM_PAGE_FIXTURE_ID, 250_000_000),
        (metrics.MAXIMUM_PAGE_FIXTURE_ID, 250_001_000),
    ]
    assert result.passed is True
    metrics.validate_maximum_page_execution(result.as_dict())

    def fabricated_account(workload: Any) -> dict[str, Any]:
        result = dict(workload)
        result["indexed_comparison_count"] -= 1
        return result

    with pytest.raises(metrics.MetricsExecutionError, match="accounting result"):
        metrics.execute_maximum_page_workload(
            resource_accountant=fabricated_account,
            resource_accounting_hook="production.fabricated",
            page_operation=project,
            page_deadline_hook="production.project_maximum_page",
            is_expected_refusal=lambda exc: isinstance(
                exc, readiness.ReadinessContractError
            ),
        )


def test_paired_campaign_executes_exact_order_once_without_retry() -> None:
    def worker(work: Any) -> dict[str, Any]:
        enabled = work["state"] == "on"
        return {
            "wall_seconds": 10.1 if enabled else 10.0,
            "raw_ru_maxrss": 1_010 if enabled else 1_000,
            "platform": "darwin",
            "exit_code": 0,
            "source_match": True,
            "code_match": True,
            "custody_match": True,
            "imports_loaded_before_timing": True,
            "settings_loaded_before_timing": True,
            "source_verified_before_timing": True,
            "timing_clock": metrics.WHOLE_PARSER_CLOCK,
            "timing_scope": metrics.WHOLE_PARSER_SCOPE,
            "output_variants": {
                variant: _output_identity() for variant in metrics.OUTPUT_VARIANTS
            },
        }

    campaign = metrics.run_paired_campaign(worker)
    summaries = campaign["targets"]

    assert campaign["worker_plan"] == list(readiness.paired_worker_plan())
    assert len(campaign["workers"]) == 20
    pids = [record["pid"] for record in campaign["workers"]]
    assert len(set(pids)) == 20
    assert os.getpid() not in pids
    assert all(record["parent_pid"] == os.getpid() for record in campaign["workers"])
    assert set(summaries) == set(metrics.PERFORMANCE_TARGETS)
    assert all(
        summary["overhead_p95_seconds"] == pytest.approx(0.1)
        for summary in summaries.values()
    )
    assert all(summary["peak_rss_delta_bytes"] == 10 for summary in summaries.values())
    assert all(summary["passed"] is True for summary in summaries.values())

    calls = multiprocessing.get_context("fork").Value("i", 0)

    def failing_worker(work: Any) -> dict[str, Any]:
        with calls.get_lock():
            calls.value += 1
        if work["worker_index"] == 3:
            raise RuntimeError("secret source text must not escape")
        return worker(work)

    with pytest.raises(metrics.PairedCampaignFailure) as captured:
        metrics.run_paired_campaign(failing_worker)
    failure = captured.value
    assert calls.value == 4
    assert len(failure.campaign["workers"]) == 3
    assert failure.campaign["worker_plan"] == list(readiness.paired_worker_plan()[:3])
    assert failure.failure == {
        "type": "worker_exit",
        "stage": "paired_parser",
        "target_id": "uber-earnings",
        "pair_index": 1,
        "state": "off",
    }
    assert "secret source text" not in json.dumps(
        {"campaign": failure.campaign, "failure": failure.failure}
    )

    failed_candidate = _artifact_candidate(
        status="failed_measurement_candidate",
        retained_path=(
            "tracker/phase-03-layout/evidence/"
            "P03-US08-running-region-metrics-attempt-01-failed.json"
        ),
        failures=[failure.failure],
    )
    failed_candidate["paired_parser"] = failure.campaign
    failed_candidate["output_sizes"]["paired_samples"] = _paired_output_prefix(
        failure.campaign
    )
    failed_candidate["aggregate"]["paired_parser"] = False
    failed_candidate["aggregate"]["output_sizes"] = False
    failed_candidate["aggregate"]["all_pass"] = False
    sealed_failure = _seal_metrics_artifact(failed_candidate)
    assert sealed_failure["failures"] == [failure.failure]


def test_paired_timeout_kills_a_sigterm_ignoring_child_without_losing_custody() -> None:
    def ignores_sigterm(_work: Any) -> dict[str, Any]:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        time.sleep(60)
        return {}

    started = time.monotonic()
    with pytest.raises(metrics.PairedCampaignFailure) as captured:
        metrics.run_paired_campaign(
            ignores_sigterm,
            worker_timeout_seconds=0.1,
        )
    elapsed = time.monotonic() - started
    assert elapsed < 3.0
    assert captured.value.campaign["workers"] == []
    assert captured.value.failure == {
        "type": "worker_timeout",
        "stage": "paired_parser",
        "target_id": "uber-earnings",
        "pair_index": 0,
        "state": "off",
    }


@pytest.mark.parametrize("failed_target", metrics.PERFORMANCE_TARGETS)
@pytest.mark.parametrize("gate", ["latency", "rss"])
def test_complete_paired_gate_failure_is_retained_as_target_scoped_stage_failure(
    failed_target: str,
    gate: str,
) -> None:
    sealed = _seal_metrics_artifact(
        _failed_complete_paired_gate_candidate(failed_target, gate)
    )
    loaded = metrics._load_strict_json(metrics._artifact_bytes(sealed))
    _validate_metrics_artifact(loaded)
    assert len(loaded["paired_parser"]["workers"]) == (metrics.PAIRED_WORKER_COUNT)
    assert loaded["failures"] == [
        {
            "type": "stage_failed",
            "stage": "paired_parser",
            "target_id": failed_target,
            "pair_index": None,
            "state": None,
        }
    ]
    assert loaded["paired_parser"]["targets"][failed_target]["passed"] is False


def test_complete_paired_gate_failure_rejects_contradictory_failure_custody() -> None:
    wrong_target = _failed_complete_paired_gate_candidate(
        "uber-earnings",
        "latency",
    )
    wrong_target["failures"][0]["target_id"] = "ny-timetable"
    with pytest.raises(
        readiness.ReadinessContractError,
        match="stage failure target",
    ):
        _seal_metrics_artifact(wrong_target)

    incomplete = _failed_complete_paired_gate_candidate(
        "uber-earnings",
        "rss",
    )
    incomplete["paired_parser"]["worker_plan"].pop()
    incomplete["paired_parser"]["workers"].pop()
    with pytest.raises(readiness.ReadinessContractError, match="paired"):
        _seal_metrics_artifact(incomplete)

    worker_failure = _failed_complete_paired_gate_candidate(
        "uber-earnings",
        "latency",
    )
    worker_failure["failures"][0].update(
        {
            "type": "worker_timeout",
            "pair_index": 0,
            "state": "off",
        }
    )
    with pytest.raises(
        readiness.ReadinessContractError,
        match="complete successful plan",
    ):
        _seal_metrics_artifact(worker_failure)


def test_paired_worker_wire_refuses_oversized_result_without_hanging() -> None:
    oversized_value = "x" * (metrics.PAIRED_WORKER_WIRE_CAP_BYTES + 1)
    empty_wire = metrics._bounded_canonical_json_bytes(
        {"result": ""},
        maximum_bytes=metrics.PAIRED_WORKER_WIRE_CAP_BYTES,
    )
    exact_value = "x" * (metrics.PAIRED_WORKER_WIRE_CAP_BYTES - len(empty_wire))
    exact_wire = metrics._bounded_canonical_json_bytes(
        {"result": exact_value},
        maximum_bytes=metrics.PAIRED_WORKER_WIRE_CAP_BYTES,
    )
    assert len(exact_wire) == metrics.PAIRED_WORKER_WIRE_CAP_BYTES

    def oversized_worker(_work: Any) -> dict[str, Any]:
        return {
            "wall_seconds": 0.001,
            "raw_ru_maxrss": 1,
            "platform": oversized_value,
            "exit_code": 0,
            "source_match": True,
            "code_match": True,
            "custody_match": True,
            "imports_loaded_before_timing": True,
            "settings_loaded_before_timing": True,
            "source_verified_before_timing": True,
            "timing_clock": metrics.WHOLE_PARSER_CLOCK,
            "timing_scope": metrics.WHOLE_PARSER_SCOPE,
            "output_variants": {
                variant: _output_identity() for variant in metrics.OUTPUT_VARIANTS
            },
        }

    started = time.monotonic()
    with pytest.raises(metrics.PairedCampaignFailure) as captured:
        metrics.run_paired_campaign(
            oversized_worker,
            worker_timeout_seconds=1.0,
        )
    assert time.monotonic() - started < 3.0
    assert captured.value.campaign["workers"] == []
    assert captured.value.failure["type"] == "worker_result_invalid"
    with pytest.raises(metrics.MetricsExecutionError, match="byte cap"):
        metrics._bounded_canonical_json_bytes(
            {"result": exact_value + "x"},
            maximum_bytes=metrics.PAIRED_WORKER_WIRE_CAP_BYTES,
        )


def test_paired_runtime_does_not_invent_an_output_variant_size_policy_cap() -> None:
    reported_size = int(metrics.RESOURCE_LIMITS["report_json_bytes"]) + 1

    def worker(work: Any) -> dict[str, Any]:
        enabled = work["state"] == "on"
        return {
            "wall_seconds": 10.1 if enabled else 10.0,
            "raw_ru_maxrss": 1_010 if enabled else 1_000,
            "platform": "darwin",
            "exit_code": 0,
            "source_match": True,
            "code_match": True,
            "custody_match": True,
            "imports_loaded_before_timing": True,
            "settings_loaded_before_timing": True,
            "source_verified_before_timing": True,
            "timing_clock": metrics.WHOLE_PARSER_CLOCK,
            "timing_scope": metrics.WHOLE_PARSER_SCOPE,
            "output_variants": {
                variant: {
                    "size_bytes": reported_size,
                    "sha256": "d" * 64,
                }
                for variant in metrics.OUTPUT_VARIANTS
            },
        }

    campaign = metrics.run_paired_campaign(worker)
    assert campaign["all_pass"] is True
    assert all(
        identity["size_bytes"] == reported_size
        for record in campaign["workers"]
        for identity in record["output_variants"].values()
    )


def test_paired_timeout_kills_sigterm_ignoring_descendant_process_tree() -> None:
    context = multiprocessing.get_context("fork")
    worker_group = context.Value("q", 0)
    descendant_pid = context.Value("q", 0)

    def forks_descendant(_work: Any) -> dict[str, Any]:
        with worker_group.get_lock():
            worker_group.value = os.getpgrp()
        child = os.fork()
        if child == 0:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            time.sleep(60)
            os._exit(0)
        with descendant_pid.get_lock():
            descendant_pid.value = child
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        time.sleep(60)
        return {}

    try:
        started = time.monotonic()
        with pytest.raises(metrics.PairedCampaignFailure) as captured:
            metrics.run_paired_campaign(
                forks_descendant,
                worker_timeout_seconds=0.1,
            )
        assert time.monotonic() - started < 3.0
        assert captured.value.failure["type"] == "worker_timeout"
        assert worker_group.value > 0
        assert descendant_pid.value > 0
        _assert_process_and_group_gone(
            descendant_pid.value,
            worker_group.value,
        )
    finally:
        if worker_group.value > 0 and worker_group.value != os.getpgrp():
            try:
                os.killpg(worker_group.value, signal.SIGKILL)
            except (PermissionError, ProcessLookupError):
                pass


def test_closed_artifact_is_semantically_sealed_and_unknown_keys_refuse() -> None:
    sealed = _seal_metrics_artifact(_artifact_candidate())

    assert set(sealed) == set(metrics.ARTIFACT_TOP_LEVEL_FIELDS)
    assert sealed["semantic_sha256"] == metrics._artifact_semantic_sha256(sealed)
    _validate_metrics_artifact(sealed)

    timestamp_changed = {**sealed, "generated_at": "2026-08-02T00:00:00+00:00"}
    assert (
        metrics._artifact_semantic_sha256(timestamp_changed)
        == (sealed["semantic_sha256"])
    )
    sample_changed = json.loads(json.dumps(sealed))
    sample_changed["measurement"]["pair_count_per_case"] = 4
    assert (
        metrics._artifact_semantic_sha256(sample_changed) != (sealed["semantic_sha256"])
    )
    with pytest.raises(readiness.ReadinessContractError, match="protocol|digest"):
        _validate_metrics_artifact(sample_changed)

    unknown = _artifact_candidate()
    unknown["unknown"] = True
    with pytest.raises(readiness.ReadinessContractError, match="keys"):
        _seal_metrics_artifact(unknown)


def test_every_policy_required_nested_artifact_section_refuses_empty() -> None:
    candidate = _artifact_candidate()
    assert set(metrics._MAPPING_ARTIFACT_FIELDS) == {
        "measurement",
        "policy",
        "settings_delta",
        "m0_reference",
        "input_custody",
        "predecessor_custody",
        "oracle_custody",
        "contract_custody",
        "synthetic_fixture_custody",
        "code_sha256",
        "dependency_custody",
        "source_extraction",
        "running_region_projection",
        "resource_boundaries",
        "deadline_boundaries",
        "paired_parser",
        "quality",
        "control_matrix",
        "comparison_ledgers",
        "output_sizes",
        "rollback",
        "aggregate",
    }
    for field in sorted(metrics._MAPPING_ARTIFACT_FIELDS):
        empty = deepcopy(candidate)
        empty[field] = {}
        with pytest.raises(
            readiness.ReadinessContractError,
            match="keys|differs|incomplete|object",
        ):
            _seal_metrics_artifact(empty)

    prior_unknown = deepcopy(candidate)
    prior_unknown["prior_failed_candidates"] = [{}]
    with pytest.raises(readiness.ReadinessContractError, match="keys"):
        _seal_metrics_artifact(prior_unknown)

    failure_unknown = deepcopy(candidate)
    failure_unknown["failures"] = [{}]
    with pytest.raises(readiness.ReadinessContractError, match="keys"):
        _seal_metrics_artifact(failure_unknown)

    hosted_boolean = deepcopy(candidate)
    hosted_boolean["hosted_requests"] = False
    with pytest.raises(readiness.ReadinessContractError, match="hosted"):
        _seal_metrics_artifact(hosted_boolean)


def test_coordinated_nested_fabrications_cannot_create_a_final_artifact() -> None:
    candidate = _artifact_candidate()

    shortened = deepcopy(candidate)
    source = shortened["source_extraction"]
    source["targets"]["uber-earnings"]["latency_seconds"].pop()
    source["targets"]["uber-earnings"]["report_sizes"].pop()
    source["targets"]["uber-earnings"]["summary"]["passed"] = False
    source["all_pass"] = False
    shortened["aggregate"]["source_extraction"] = False
    shortened["aggregate"]["all_pass"] = False
    with pytest.raises(
        readiness.ReadinessContractError,
        match="allocation samples|final aggregate",
    ):
        _seal_metrics_artifact(shortened)

    duplicate_pid = deepcopy(candidate)
    workers = duplicate_pid["paired_parser"]["workers"]
    workers[1]["pid"] = workers[0]["pid"]
    with pytest.raises(readiness.ReadinessContractError, match="process custody"):
        _seal_metrics_artifact(duplicate_pid)

    detached_output = deepcopy(candidate)
    detached_output["output_sizes"]["paired_samples"]["uber-earnings"][0]["variants"][
        "raw_json"
    ]["sha256"] = "7" * 64
    with pytest.raises(
        readiness.ReadinessContractError,
        match="output identity|output global-prefix binding",
    ):
        _seal_metrics_artifact(detached_output)

    coordinated_source_drift = deepcopy(candidate)
    for phase in ("pre", "post"):
        coordinated_source_drift["input_custody"][phase]["uber-earnings"]["sha256"] = (
            "0" * 64
        )
    coordinated_source_drift["input_custody"]["all_expected_match"] = True
    with pytest.raises(readiness.ReadinessContractError, match="algebra"):
        _seal_metrics_artifact(coordinated_source_drift)

    coordinated_component_drift = deepcopy(candidate)
    component = coordinated_component_drift["oracle_custody"]
    component["semantic_sha256"] = "0" * 64
    component["expected_semantic_sha256"] = "0" * 64
    component["match"] = True
    with pytest.raises(readiness.ReadinessContractError, match="match algebra"):
        _seal_metrics_artifact(coordinated_component_drift)

    coordinated_settings_drift = deepcopy(candidate)
    settings = coordinated_settings_drift["settings_delta"]
    settings["flag_off"]["layout_forms_enabled"] = False
    settings["flag_on"]["layout_forms_enabled"] = False
    settings["flag_off_sha256"] = hashlib.sha256(
        metrics._canonical_json(settings["flag_off"]).encode("utf-8")
    ).hexdigest()
    settings["flag_on_sha256"] = hashlib.sha256(
        metrics._canonical_json(settings["flag_on"]).encode("utf-8")
    ).hexdigest()
    settings["predecessor_flags_match"] = False
    with pytest.raises(readiness.ReadinessContractError, match="settings custody"):
        _seal_metrics_artifact(coordinated_settings_drift)

    shrunk_denominator = deepcopy(candidate)
    quality = shrunk_denominator["quality"]
    quality["page_identity_exact_count"] = 29
    quality["page_identity_denominator"] = 29
    with pytest.raises(readiness.ReadinessContractError, match="quality aggregate"):
        _seal_metrics_artifact(shrunk_denominator)

    over_comparison_cap = deepcopy(candidate)
    ledger = over_comparison_cap["comparison_ledgers"]
    target = ledger["targets"]["uber-earnings"]
    target["comparison_count"] = target["document_ceiling"] + 1
    target["passed"] = False
    ledger["all_pass"] = False
    over_comparison_cap["aggregate"]["comparison_ledgers"] = False
    over_comparison_cap["aggregate"]["all_pass"] = False
    with pytest.raises(readiness.ReadinessContractError, match="final aggregate"):
        _seal_metrics_artifact(over_comparison_cap)

    generic_aggregate = deepcopy(candidate)
    generic_aggregate["aggregate"] = {"all_pass": True}
    with pytest.raises(readiness.ReadinessContractError, match="keys"):
        _seal_metrics_artifact(generic_aggregate)


def test_failed_paired_output_cannot_retain_samples_beyond_one_worker() -> None:
    candidate = _failed_paired_candidate(1)
    candidate["output_sizes"]["paired_samples"] = _output_sizes()["paired_samples"]
    with pytest.raises(readiness.ReadinessContractError, match="paired output"):
        _seal_metrics_artifact(candidate)


def test_zero_worker_failure_cannot_skip_to_timetable_output() -> None:
    candidate = _failed_paired_candidate(0)
    candidate["output_sizes"]["paired_samples"] = {
        "ny-timetable": [deepcopy(_output_sizes()["paired_samples"]["ny-timetable"][0])]
    }
    with pytest.raises(readiness.ReadinessContractError, match="paired output"):
        _seal_metrics_artifact(candidate)


@pytest.mark.parametrize(
    ("stage", "output_field", "aggregate_field"),
    [
        ("source_extraction", "source_reports", "source_extraction"),
        (
            "running_region_projection",
            "isolated_projection_outputs",
            "running_region_projection",
        ),
    ],
)
def test_failed_isolated_stage_cannot_retain_a_future_target_output(
    stage: str,
    output_field: str,
    aggregate_field: str,
) -> None:
    candidate = _artifact_candidate(
        status="failed_measurement_candidate",
        retained_path=(
            "tracker/phase-03-layout/evidence/"
            "P03-US08-running-region-metrics-attempt-01-failed.json"
        ),
        failures=[
            {
                "type": "stage_failed",
                "stage": stage,
                "target_id": "ny-timetable",
                "pair_index": None,
                "state": None,
            }
        ],
    )
    candidate[stage]["targets"].pop("ny-timetable")
    candidate[stage]["all_pass"] = False
    candidate["aggregate"][aggregate_field] = False
    candidate["aggregate"]["all_pass"] = False
    assert "ny-timetable" in candidate["output_sizes"][output_field]
    with pytest.raises(readiness.ReadinessContractError, match="target coverage"):
        _seal_metrics_artifact(candidate)


@pytest.mark.parametrize(
    "stage",
    [
        "source_extraction",
        "running_region_projection",
        "comparison_ledgers",
    ],
)
def test_failed_target_must_be_the_final_retained_stage_target(
    stage: str,
) -> None:
    candidate = _artifact_candidate(
        status="failed_measurement_candidate",
        retained_path=(
            "tracker/phase-03-layout/evidence/"
            "P03-US08-running-region-metrics-attempt-01-failed.json"
        ),
        failures=[
            {
                "type": "stage_failed",
                "stage": stage,
                "target_id": "uber-earnings",
                "pair_index": None,
                "state": None,
            }
        ],
    )
    if stage in {"source_extraction", "running_region_projection"}:
        ceiling = (
            metrics.ISOLATED_SOURCE_EXTRACTION_P95_SECONDS
            if stage == "source_extraction"
            else metrics.ISOLATED_PROJECTION_P95_SECONDS
        )
        target = candidate[stage]["targets"]["uber-earnings"]
        target["latency_seconds"] = [ceiling + 0.001] * len(target["latency_seconds"])
        target["summary"]["latency_p95_seconds"] = ceiling + 0.001
        target["summary"]["passed"] = False
        candidate[stage]["all_pass"] = False
    else:
        target = candidate[stage]["targets"]["uber-earnings"]
        target["comparison_count"] = target["document_ceiling"] + 1
        target["passed"] = False
        projection_summary = candidate["running_region_projection"]["targets"][
            "uber-earnings"
        ]["summary"]
        projection_summary["comparison_count"] = target["comparison_count"]
        candidate[stage]["all_pass"] = False
    candidate["aggregate"][stage] = False
    candidate["aggregate"]["all_pass"] = False

    assert "ny-timetable" in candidate[stage]["targets"]
    with pytest.raises(readiness.ReadinessContractError, match="target prefix"):
        _seal_metrics_artifact(candidate)


@pytest.mark.parametrize(
    "stage",
    [
        "source_extraction",
        "running_region_projection",
        "comparison_ledgers",
    ],
)
@pytest.mark.parametrize("failed_target", metrics.PERFORMANCE_TARGETS)
def test_stage_failure_target_prefix_survives_sorted_json_round_trip(
    stage: str,
    failed_target: str,
) -> None:
    sealed = _seal_metrics_artifact(_failed_stage_candidate(stage, failed_target))
    loaded = metrics._load_strict_json(metrics._artifact_bytes(sealed))
    _validate_metrics_artifact(loaded)
    prefix_length = metrics.PERFORMANCE_TARGETS.index(failed_target) + 1
    assert set(loaded[stage]["targets"]) == set(
        metrics.PERFORMANCE_TARGETS[:prefix_length]
    )


def test_final_projection_failure_keeps_complete_successful_comparison_ledger() -> None:
    candidate = _failed_stage_candidate(
        "running_region_projection",
        metrics.PERFORMANCE_TARGETS[-1],
    )

    metrics._retain_first_failure_prefix(
        candidate["failures"][0],
        source_extraction=candidate["source_extraction"],
        running_region_projection=candidate["running_region_projection"],
        paired_parser=candidate["paired_parser"],
        comparison_ledgers=candidate["comparison_ledgers"],
        output_sizes=candidate["output_sizes"],
    )

    assert set(candidate["comparison_ledgers"]["targets"]) == set(
        metrics.PERFORMANCE_TARGETS
    )
    assert candidate["comparison_ledgers"]["all_pass"] is True
    _seal_metrics_artifact(candidate)


@pytest.mark.parametrize("reported_target", ["ny-timetable", None])
def test_output_size_failure_is_bound_to_first_measured_target(
    reported_target: str | None,
) -> None:
    candidate = _failed_output_size_candidate(reported_target)

    with pytest.raises(
        readiness.ReadinessContractError,
        match="failure target|stage failure identity",
    ):
        _seal_metrics_artifact(candidate)

    sealed = _seal_metrics_artifact(_failed_output_size_candidate())
    assert sealed["failures"][0]["target_id"] == "uber-earnings"
    assert tuple(sealed["source_extraction"]["targets"]) == ("uber-earnings",)
    assert {worker["target_id"] for worker in sealed["paired_parser"]["workers"]} == {
        "uber-earnings"
    }


@pytest.mark.parametrize("failed_target", metrics.PERFORMANCE_TARGETS)
def test_output_size_failure_target_prefix_survives_sorted_json_round_trip(
    failed_target: str,
) -> None:
    sealed = _seal_metrics_artifact(
        _failed_output_size_candidate(
            failed_target,
            failed_target=failed_target,
        )
    )
    loaded = metrics._load_strict_json(metrics._artifact_bytes(sealed))
    _validate_metrics_artifact(loaded)
    prefix_length = metrics.PERFORMANCE_TARGETS.index(failed_target) + 1
    expected_targets = set(metrics.PERFORMANCE_TARGETS[:prefix_length])
    assert set(loaded["output_sizes"]["paired_samples"]) == expected_targets


def test_output_failure_still_rejects_reordered_sequence_ledger() -> None:
    candidate = _failed_output_size_candidate(
        "ny-timetable",
        failed_target="ny-timetable",
    )
    samples = candidate["output_sizes"]["paired_samples"]["uber-earnings"]
    samples[0], samples[1] = samples[1], samples[0]
    with pytest.raises(readiness.ReadinessContractError, match="sample order"):
        _seal_metrics_artifact(candidate)


@pytest.mark.parametrize("future_scope", ["isolated_and_output", "paired"])
def test_output_size_failure_rejects_future_target_evidence(
    future_scope: str,
) -> None:
    candidate = _failed_output_size_candidate()
    full = _artifact_candidate()
    if future_scope == "isolated_and_output":
        for stage in ("source_extraction", "running_region_projection"):
            candidate[stage]["targets"]["ny-timetable"] = deepcopy(
                full[stage]["targets"]["ny-timetable"]
            )
        candidate["comparison_ledgers"]["targets"]["ny-timetable"] = deepcopy(
            full["comparison_ledgers"]["targets"]["ny-timetable"]
        )
        candidate["output_sizes"]["source_reports"]["ny-timetable"] = deepcopy(
            full["output_sizes"]["source_reports"]["ny-timetable"]
        )
        candidate["output_sizes"]["isolated_projection_outputs"]["ny-timetable"] = (
            deepcopy(
                full["output_sizes"]["isolated_projection_outputs"]["ny-timetable"]
            )
        )
    else:
        paired = candidate["paired_parser"]
        paired["worker_plan"] = deepcopy(full["paired_parser"]["worker_plan"])
        paired["workers"] = deepcopy(full["paired_parser"]["workers"])
        paired["targets"] = deepcopy(full["paired_parser"]["targets"])
        candidate["output_sizes"]["paired_samples"] = deepcopy(
            full["output_sizes"]["paired_samples"]
        )

    with pytest.raises(readiness.ReadinessContractError, match="target prefix"):
        _seal_metrics_artifact(candidate)


def test_isolated_ledger_retains_all_twenty_five_outputs_in_exact_order() -> None:
    for stage in ("source_extraction", "running_region_projection"):
        record = _isolated_stage(stage, 0.001)["targets"]["uber-earnings"]
        assert len(record["measured_outputs"]) == 25
        assert [
            (item["measurement_kind"], item["sample_index"])
            for item in record["measured_outputs"]
        ] == [
            ("latency", index) for index in range(metrics.ISOLATED_LATENCY_SAMPLES)
        ] + [
            ("allocation", index)
            for index in range(metrics.ISOLATED_ALLOCATION_SAMPLES)
        ]


def test_missing_allocation_output_and_reordered_outputs_are_rejected() -> None:
    missing = _artifact_candidate()
    missing["source_extraction"]["targets"]["uber-earnings"]["measured_outputs"].pop()
    with pytest.raises(readiness.ReadinessContractError, match="output coverage"):
        _seal_metrics_artifact(missing)

    reordered = _artifact_candidate()
    outputs = reordered["running_region_projection"]["targets"]["uber-earnings"][
        "measured_outputs"
    ]
    outputs[0], outputs[1] = outputs[1], outputs[0]
    with pytest.raises(readiness.ReadinessContractError, match="output order"):
        _seal_metrics_artifact(reordered)


@pytest.mark.parametrize(
    "field",
    [
        "maximum_source_report_json_bytes",
        "maximum_page_identity_json_bytes",
        "maximum_running_descriptor_json_bytes",
    ],
)
def test_output_maxima_are_grounded_in_measured_records(field: str) -> None:
    candidate = _artifact_candidate()
    candidate["output_sizes"][field] = 0
    with pytest.raises(readiness.ReadinessContractError, match="grounded maximum"):
        _seal_metrics_artifact(candidate)


def test_comparison_maximum_and_projection_cross_binding_are_exact() -> None:
    impossible = _artifact_candidate()
    impossible["comparison_ledgers"]["targets"]["uber-earnings"].update(
        {"comparison_count": 0, "maximum_page_comparisons": 50}
    )
    with pytest.raises(readiness.ReadinessContractError, match="algebra"):
        _seal_metrics_artifact(impossible)

    detached = _artifact_candidate()
    detached["comparison_ledgers"]["targets"]["uber-earnings"]["comparison_count"] = 99
    with pytest.raises(readiness.ReadinessContractError, match="algebra"):
        _seal_metrics_artifact(detached)

    assert metrics._comparison_counts_are_coherent(0, 0, 0) is True
    assert metrics._comparison_counts_are_coherent(0, 1, 1) is False


@pytest.mark.parametrize(
    ("field", "hostile"),
    [
        ("type", "<script>/Users/victim/.ssh/id_rsa\n\x00"),
        ("stage", "https://attacker.invalid/?token=secret\r\nX: injected"),
    ],
)
def test_failure_type_and_stage_are_closed_content_free_enums(
    field: str,
    hostile: str,
) -> None:
    candidate = _failed_paired_candidate(1)
    candidate["failures"][0][field] = hostile
    with pytest.raises(readiness.ReadinessContractError, match="failure enum"):
        _seal_metrics_artifact(candidate)


def test_failure_record_cannot_contradict_a_complete_successful_campaign() -> None:
    candidate = _artifact_candidate(
        status="failed_measurement_candidate",
        retained_path=(
            "tracker/phase-03-layout/evidence/"
            "P03-US08-running-region-metrics-attempt-01-failed.json"
        ),
        failures=[
            {
                "type": "worker_exit",
                "stage": "paired_parser",
                "target_id": "uber-earnings",
                "pair_index": 2,
                "state": "on",
            }
        ],
    )
    with pytest.raises(readiness.ReadinessContractError, match="contradicts"):
        _seal_metrics_artifact(candidate)


@pytest.mark.parametrize("boundary", ["resource", "deadline"])
def test_boundary_outcome_strings_are_bound_to_acceptance_flags(
    boundary: str,
) -> None:
    if boundary == "resource":
        records = _resource_boundaries()
        record = records["cases"][next(iter(records["cases"]))]

        def validate() -> None:
            metrics.validate_resource_boundaries(records, complete=True)

    else:
        records = _deadline_boundaries()
        record = records["cases"][next(iter(records["cases"]))]

        def validate() -> None:
            metrics.validate_deadline_boundaries(records, complete=True)

    record["exact_outcome"] = "refused:ReadinessContractError"
    with pytest.raises(readiness.ReadinessContractError, match="outcome"):
        validate()

    record["exact_outcome"] = "accepted"
    record["maximum_plus_one_outcome"] = "accepted"
    with pytest.raises(readiness.ReadinessContractError, match="outcome"):
        validate()


@pytest.mark.parametrize(
    "case",
    [
        "resource",
        "deadline",
        "maximum_page",
        "isolated_bool",
        "isolated_nullable_bool",
        "quality",
        "control",
        "comparison",
        "rollback",
    ],
)
def test_false_gate_witnesses_still_require_exact_boolean_types(case: str) -> None:
    with pytest.raises(readiness.ReadinessContractError, match="Boolean"):
        if case == "resource":
            value = _resource_boundaries()
            next(iter(value["cases"].values()))["exact_accepted"] = "yes"
            metrics.validate_resource_boundaries(value, complete=False)
        elif case == "deadline":
            value = _deadline_boundaries()
            next(iter(value["cases"].values()))["exact_accepted"] = "yes"
            metrics.validate_deadline_boundaries(value, complete=False)
        elif case == "maximum_page":
            value = _maximum_page_execution()
            value["resource_accounting_accepted"] = "yes"
            metrics.validate_maximum_page_execution(value)
        elif case == "isolated_bool":
            value = _isolated_stage("running_region_projection", 0.001)
            value["targets"]["uber-earnings"]["idempotent"] = "yes"
            metrics.validate_isolated_stage(
                value, stage="running_region_projection", complete=False
            )
        elif case == "isolated_nullable_bool":
            value = _isolated_stage("source_extraction", 0.001)
            value["targets"]["uber-earnings"]["idempotent"] = "yes"
            metrics.validate_isolated_stage(
                value, stage="source_extraction", complete=False
            )
        elif case == "quality":
            value = _quality()
            value["manufacturing_fused_contribution_exact"] = "yes"
            metrics.validate_quality(value)
        elif case == "control":
            value = _control_matrix()
            next(iter(value["cases"].values()))["legacy_identity_match"] = "yes"
            metrics.validate_control_matrix(value, complete=False)
        elif case == "comparison":
            projection = _isolated_stage("running_region_projection", 0.001)
            value = _comparison_ledgers()
            next(iter(value["targets"].values()))["instrumentation_untimed"] = "yes"
            metrics.validate_comparison_ledgers(
                value,
                complete=False,
                projection_targets=projection["targets"],
            )
        else:
            value = _rollback()
            value["flag_off_byte_identical"] = []
            metrics.validate_rollback(value)


def test_final_sealing_observes_exact_repository_bytes_and_rejects_forgery(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    observed = _write_required_repository_files(repository_root)
    exact = _bind_candidate_to_repository_code(
        _artifact_candidate(),
        observed,
        repository_root=repository_root,
    )
    sealed = metrics.seal_metrics_artifact(
        exact,
        repository_root=repository_root,
    )
    metrics.validate_metrics_artifact(
        sealed,
        repository_root=repository_root,
    )

    runner_path = "tests/benchmarks/running_region_metrics.py"
    (repository_root / runner_path).write_bytes(b"changed-after-seal\n")
    with pytest.raises(readiness.ReadinessContractError, match="observed code"):
        metrics.validate_metrics_artifact(
            sealed,
            repository_root=repository_root,
        )

    forged_root = tmp_path / "forged-repository"
    forged_root.mkdir()
    actual = _write_required_repository_files(forged_root)
    forged_records = deepcopy(actual)
    component_paths = set(metrics.COMPONENT_PATHS.values())
    for path, identity in forged_records.items():
        if path not in component_paths:
            identity["size_bytes"] = 1
            identity["sha256"] = "0" * 64
    forged = _artifact_candidate()
    forged_code = metrics.build_code_custody(forged_records, forged_records)
    forged["code_sha256"] = forged_code
    forged.update(_component_custodies(forged_code))
    forged["dependency_custody"] = metrics.collect_dependency_custody(forged_root)
    with pytest.raises(readiness.ReadinessContractError, match="observed code"):
        metrics.seal_metrics_artifact(
            forged,
            repository_root=forged_root,
        )
    with pytest.raises(TypeError, match="observed_code_files"):
        metrics.seal_metrics_artifact(
            forged,
            repository_root=forged_root,
            observed_code_files=deepcopy(forged_records),  # type: ignore[call-arg]
        )

    removed = _bind_candidate_to_repository_code(
        _artifact_candidate(),
        actual,
        repository_root=forged_root,
    )
    runner_path = "tests/benchmarks/running_region_metrics.py"
    removed["code_sha256"]["pre"].pop(runner_path)
    removed["code_sha256"]["post"].pop(runner_path)
    removed["code_sha256"]["manifest_sha256"] = hashlib.sha256(
        metrics._canonical_json(removed["code_sha256"]["post"]).encode("utf-8")
    ).hexdigest()
    with pytest.raises(readiness.ReadinessContractError, match="file set"):
        metrics.seal_metrics_artifact(
            removed,
            repository_root=forged_root,
        )


def test_retained_validation_binds_exact_bytes_and_writer_still_refuses_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    observed = _write_required_repository_files(repository_root)
    sealed = metrics.seal_metrics_artifact(
        _bind_candidate_to_repository_code(
            _artifact_candidate(),
            observed,
            repository_root=repository_root,
        ),
        repository_root=repository_root,
    )
    relative_path = PurePosixPath(sealed["retained_path"])
    destination = repository_root.joinpath(*relative_path.parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    retained_bytes = metrics._artifact_bytes(sealed)
    destination.write_bytes(retained_bytes)

    metrics.validate_metrics_artifact(
        sealed,
        repository_root=repository_root,
    )

    compact_bytes = json.dumps(
        sealed,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    assert json.loads(compact_bytes) == sealed
    assert compact_bytes != retained_bytes
    destination.write_bytes(compact_bytes)
    with pytest.raises(
        readiness.ReadinessContractError,
        match="retained metrics artifact binding",
    ):
        metrics.validate_metrics_artifact(
            sealed,
            repository_root=repository_root,
        )
    destination.write_bytes(retained_bytes)

    unbound = deepcopy(sealed)
    unbound["generated_at"] = "2026-08-03T00:00:00+00:00"
    assert unbound["semantic_sha256"] == metrics._artifact_semantic_sha256(unbound)
    with pytest.raises(
        readiness.ReadinessContractError,
        match="retained metrics artifact binding",
    ):
        metrics.validate_metrics_artifact(
            unbound,
            repository_root=repository_root,
        )

    original_validator = metrics._validate_metrics_artifact_with_observations

    def replace_retained_after_validation(*args: Any, **kwargs: Any) -> None:
        original_validator(*args, **kwargs)
        replacement = destination.with_name(f".{destination.name}.replacement")
        replacement.write_bytes(b'{"replacement":true}\n')
        os.replace(replacement, destination)

    monkeypatch.setattr(
        metrics,
        "_validate_metrics_artifact_with_observations",
        replace_retained_after_validation,
    )
    with pytest.raises(
        (metrics.MetricsExecutionError, readiness.ReadinessContractError),
        match="changed during validation",
    ):
        metrics.validate_metrics_artifact(
            sealed,
            repository_root=repository_root,
        )
    monkeypatch.setattr(
        metrics,
        "_validate_metrics_artifact_with_observations",
        original_validator,
    )
    destination.write_bytes(retained_bytes)

    with pytest.raises(
        readiness.ReadinessContractError,
        match="overwrite custody",
    ):
        metrics.write_artifact_exclusive(
            destination,
            sealed,
            repository_root=repository_root,
        )
    assert destination.read_bytes() == retained_bytes


def test_public_dependency_custody_is_observed_not_claimed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    observed_code = _write_required_repository_files(repository_root)
    candidate = _bind_candidate_to_repository_code(
        _artifact_candidate(),
        observed_code,
        repository_root=repository_root,
    )
    sealed = metrics.seal_metrics_artifact(
        candidate,
        repository_root=repository_root,
    )
    assert sealed["dependency_custody"] == metrics.collect_dependency_custody(
        repository_root
    )

    forged = deepcopy(candidate)
    forged["dependency_custody"]["python_packages"]["docling"]["version"] = (
        "999.0-forged"
    )
    with pytest.raises(readiness.ReadinessContractError, match="observed dependency"):
        metrics.seal_metrics_artifact(
            forged,
            repository_root=repository_root,
        )

    manifest = repository_root / metrics.DEPENDENCY_MANIFEST_PATHS[0]
    manifest.write_bytes(manifest.read_bytes() + b"\n# drift\n")
    with pytest.raises(readiness.ReadinessContractError, match="observed dependency"):
        metrics.validate_metrics_artifact(
            sealed,
            repository_root=repository_root,
        )

    missing_root = tmp_path / "missing-manifest"
    missing_root.mkdir()
    missing_code = _write_required_repository_files(missing_root)
    missing_candidate = _bind_candidate_to_repository_code(
        _artifact_candidate(),
        missing_code,
        repository_root=missing_root,
    )
    (missing_root / metrics.DEPENDENCY_MANIFEST_PATHS[0]).unlink()
    with pytest.raises(metrics.MetricsExecutionError, match="manifest"):
        metrics.seal_metrics_artifact(
            missing_candidate,
            repository_root=missing_root,
        )

    offline_root = tmp_path / "offline-environment"
    offline_root.mkdir()
    offline_code = _write_required_repository_files(offline_root)
    offline_candidate = _bind_candidate_to_repository_code(
        _artifact_candidate(),
        offline_code,
        repository_root=offline_root,
    )
    offline_field = next(iter(metrics.OFFLINE_ENVIRONMENT))
    monkeypatch.delenv(offline_field)
    with pytest.raises(metrics.MetricsExecutionError, match="offline"):
        metrics.seal_metrics_artifact(
            offline_candidate,
            repository_root=offline_root,
        )


def test_repository_collectors_enforce_per_file_total_and_stability_caps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _write_required_repository_files(repository_root)

    code_path = repository_root / "app/config.py"
    code_path.write_bytes(b"c" * metrics.MAX_CODE_CUSTODY_FILE_BYTES)
    at_cap = metrics.collect_code_file_identities(repository_root)
    assert at_cap["app/config.py"]["size_bytes"] == (
        metrics.MAX_CODE_CUSTODY_FILE_BYTES
    )
    code_path.write_bytes(b"c" * (metrics.MAX_CODE_CUSTODY_FILE_BYTES + 1))
    with pytest.raises(metrics.MetricsExecutionError, match="byte cap"):
        metrics.collect_code_file_identities(repository_root)
    code_path.write_bytes(b"restored\n")

    exact_code = metrics.collect_code_file_identities(repository_root)
    exact_code_total = sum(identity["size_bytes"] for identity in exact_code.values())
    extra_path = "tests/extra-custody.py"
    extra = repository_root / extra_path
    extra.write_bytes(b"x")
    with monkeypatch.context() as bounded:
        bounded.setattr(
            metrics,
            "MAX_CODE_CUSTODY_TOTAL_BYTES",
            exact_code_total,
        )
        metrics.collect_code_file_identities(repository_root)
        with pytest.raises(metrics.MetricsExecutionError, match="total byte cap"):
            metrics.collect_code_file_identities(
                repository_root,
                paths=(*sorted(metrics.REQUIRED_CODE_PATHS), extra_path),
            )

    manifest_path = repository_root / metrics.DEPENDENCY_MANIFEST_PATHS[0]
    manifest_path.write_bytes(b"m" * metrics.MAX_DEPENDENCY_MANIFEST_BYTES)
    manifest_at_cap = metrics.collect_dependency_custody(repository_root)
    assert (
        manifest_at_cap["manifests"][metrics.DEPENDENCY_MANIFEST_PATHS[0]]["size_bytes"]
        == metrics.MAX_DEPENDENCY_MANIFEST_BYTES
    )
    manifest_path.write_bytes(b"m" * (metrics.MAX_DEPENDENCY_MANIFEST_BYTES + 1))
    with pytest.raises(metrics.MetricsExecutionError, match="byte cap"):
        metrics.collect_dependency_custody(repository_root)
    manifest_path.write_bytes(
        (PROJECT_ROOT / metrics.DEPENDENCY_MANIFEST_PATHS[0]).read_bytes()
    )

    exact_dependencies = metrics.collect_dependency_custody(repository_root)
    manifest_total = sum(
        identity["size_bytes"] for identity in exact_dependencies["manifests"].values()
    )
    with monkeypatch.context() as bounded:
        bounded.setattr(
            metrics,
            "MAX_DEPENDENCY_MANIFEST_TOTAL_BYTES",
            manifest_total,
        )
        metrics.collect_dependency_custody(repository_root)
        manifest_path.write_bytes(manifest_path.read_bytes() + b"x")
        with pytest.raises(metrics.MetricsExecutionError, match="total byte cap"):
            metrics.collect_dependency_custody(repository_root)
    manifest_path.write_bytes(
        (PROJECT_ROOT / metrics.DEPENDENCY_MANIFEST_PATHS[0]).read_bytes()
    )

    real_snapshot = metrics._file_descriptor_snapshot
    snapshot_calls = 0

    def unstable_snapshot(
        descriptor: int,
    ) -> tuple[int, int, int, int, int, int, int]:
        nonlocal snapshot_calls
        snapshot_calls += 1
        observed = real_snapshot(descriptor)
        if snapshot_calls == 2:
            return (*observed[:-1], observed[-1] + 1)
        return observed

    with monkeypatch.context() as unstable:
        unstable.setattr(
            metrics,
            "_file_descriptor_snapshot",
            unstable_snapshot,
        )
        with pytest.raises(metrics.MetricsExecutionError, match="changed"):
            metrics.collect_code_file_identities(repository_root)


_REPOSITORY_REBIND_CASES = (
    (
        "input",
        frozen_oracle.CORPUS_REGISTRY_CUSTODY["path"],
        int(frozen_oracle.CORPUS_REGISTRY_CUSTODY["size_bytes"]) + 32,
    ),
    ("code", "app/services/tables.py", metrics.MAX_CODE_CUSTODY_FILE_BYTES),
    (
        "manifest",
        "frontend/package.json",
        metrics.MAX_DEPENDENCY_MANIFEST_BYTES,
    ),
    (
        "prior",
        (
            "tracker/phase-03-layout/evidence/"
            "P03-US08-running-region-metrics-attempt-01-failed.json"
        ),
        metrics.PRIOR_ARTIFACT_READ_CAP_BYTES,
    ),
)


@pytest.mark.parametrize(
    ("category", "relative_path", "maximum_bytes"),
    _REPOSITORY_REBIND_CASES,
)
def test_repository_reader_rejects_persistent_atomic_file_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    category: str,
    relative_path: str,
    maximum_bytes: int,
) -> None:
    repository_root = tmp_path / f"file-replacement-{category}"
    repository_root.mkdir()
    victim = repository_root / relative_path
    victim.parent.mkdir(parents=True, exist_ok=True)
    original = f"original-{category}\n".encode()
    replacement_bytes = f"replacement-{category}\n".encode()
    victim.write_bytes(original)
    replacement = victim.with_name(f".{victim.name}.replacement")
    replacement.write_bytes(replacement_bytes)
    real_pread = metrics.os.pread
    replaced = False

    def replacing_pread(descriptor: int, count: int, offset: int) -> bytes:
        nonlocal replaced
        if not replaced:
            replacement.replace(victim)
            replaced = True
        return real_pread(descriptor, count, offset)

    with monkeypatch.context() as swapping:
        swapping.setattr(metrics.os, "pread", replacing_pread)
        with pytest.raises(metrics.MetricsExecutionError, match="changed"):
            metrics._read_bounded_regular_repository_file(
                repository_root.resolve(),
                PurePosixPath(relative_path),
                maximum_bytes=maximum_bytes,
                error=f"{category} repository read",
            )
    assert replaced is True
    assert victim.read_bytes() == replacement_bytes


@pytest.mark.parametrize(
    ("category", "relative_path", "maximum_bytes"),
    _REPOSITORY_REBIND_CASES,
)
def test_repository_reader_rejects_persistent_parent_directory_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    category: str,
    relative_path: str,
    maximum_bytes: int,
) -> None:
    repository_root = tmp_path / f"directory-replacement-{category}"
    repository_root.mkdir()
    victim = repository_root / relative_path
    victim.parent.mkdir(parents=True, exist_ok=True)
    original = f"original-{category}\n".encode()
    replacement_bytes = f"replacement-{category}\n".encode()
    victim.write_bytes(original)
    moved_parent = repository_root / f".moved-parent-{category}"
    staged_parent = repository_root / f".staged-parent-{category}"
    staged_parent.mkdir()
    (staged_parent / victim.name).write_bytes(replacement_bytes)
    parent = victim.parent
    real_pread = metrics.os.pread
    replaced = False

    def replacing_pread(descriptor: int, count: int, offset: int) -> bytes:
        nonlocal replaced
        if not replaced:
            parent.rename(moved_parent)
            staged_parent.rename(parent)
            replaced = True
        return real_pread(descriptor, count, offset)

    with monkeypatch.context() as swapping:
        swapping.setattr(metrics.os, "pread", replacing_pread)
        with pytest.raises(metrics.MetricsExecutionError, match="changed"):
            metrics._read_bounded_regular_repository_file(
                repository_root.resolve(),
                PurePosixPath(relative_path),
                maximum_bytes=maximum_bytes,
                error=f"{category} repository read",
            )
    assert replaced is True
    assert victim.read_bytes() == replacement_bytes


def test_repository_reader_refuses_fifo_and_open_time_symlink_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fifo_root = tmp_path / "fifo"
    fifo_root.mkdir()
    _write_required_repository_files(fifo_root)
    victim_relative = "app/config.py"
    fifo = fifo_root / victim_relative
    fifo.unlink()
    os.mkfifo(fifo)
    started = time.monotonic()
    with pytest.raises(metrics.MetricsExecutionError, match="regular repository"):
        metrics.collect_code_file_identities(fifo_root)
    assert time.monotonic() - started < 1.0

    swap_root = tmp_path / "swap"
    swap_root.mkdir()
    _write_required_repository_files(swap_root)
    victim = swap_root / victim_relative
    outside = tmp_path / "outside-code.py"
    outside.write_bytes(b"outside\n")
    real_open = metrics.os.open
    swapped = False

    def swapping_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if path == "config.py" and dir_fd is not None and not swapped:
            victim.unlink()
            victim.symlink_to(outside)
            swapped = True
        return real_open(path, flags, mode, dir_fd=dir_fd)

    with monkeypatch.context() as swapping:
        swapping.setattr(metrics.os, "open", swapping_open)
        with pytest.raises(
            metrics.MetricsExecutionError,
            match="regular repository",
        ):
            metrics.collect_code_file_identities(swap_root)
    assert swapped is True


def test_local_tool_probe_enforces_output_cap_and_eof_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "tesseract"
    python = PROJECT_ROOT / ".venv/bin/python"

    def write_probe(body: str) -> None:
        executable.write_text(f"#!{python}\n{body}\n", encoding="utf-8")
        executable.chmod(0o755)

    exact_version_bytes = metrics.LOCAL_TOOL_PROBE_OUTPUT_CAP_BYTES - len("tesseract ")
    write_probe(
        f"import sys\nsys.stdout.write('tesseract ' + '1' * {exact_version_bytes})"
    )
    monkeypatch.setattr(metrics.shutil, "which", lambda _name: str(executable))
    exact_version = metrics._probe_local_tool_version("tesseract")
    assert len(exact_version.encode("utf-8")) == exact_version_bytes

    write_probe(
        f"import sys\nsys.stdout.write('tesseract ' + '1' * {exact_version_bytes + 1})"
    )
    with pytest.raises(metrics.MetricsExecutionError, match="output byte cap"):
        metrics._probe_local_tool_version("tesseract")

    write_probe("import os, time\nos.close(1)\nos.close(2)\ntime.sleep(60)")
    monkeypatch.setattr(metrics, "LOCAL_TOOL_PROBE_TIMEOUT_SECONDS", 0.1)
    started = time.monotonic()
    with pytest.raises(metrics.MetricsExecutionError, match="timed out after EOF"):
        metrics._probe_local_tool_version("tesseract")
    assert time.monotonic() - started < 3.0


def test_local_tool_probe_kills_descendants_that_hold_output_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "tesseract"
    pid_file = tmp_path / "probe-pids.txt"
    python = PROJECT_ROOT / ".venv/bin/python"
    executable.write_text(
        f"#!{python}\n"
        "import os, signal, time\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        f"with open({str(pid_file)!r}, 'w', encoding='utf-8') as stream:\n"
        "    stream.write(f'{os.getpid()} {child}')\n"
        "os._exit(0)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setattr(metrics.shutil, "which", lambda _name: str(executable))
    monkeypatch.setattr(metrics, "LOCAL_TOOL_PROBE_TIMEOUT_SECONDS", 2.0)

    process_group = 0
    descendant = 0
    try:
        started = time.monotonic()
        with pytest.raises(metrics.MetricsExecutionError, match="timed out"):
            metrics._probe_local_tool_version("tesseract")
        assert time.monotonic() - started < 5.0
        process_group, descendant = (
            int(value) for value in pid_file.read_text(encoding="utf-8").split()
        )
        _assert_process_and_group_gone(descendant, process_group)
    finally:
        if process_group > 0 and process_group != os.getpgrp():
            try:
                os.killpg(process_group, signal.SIGKILL)
            except (PermissionError, ProcessLookupError):
                pass


def test_successful_local_tool_probe_also_kills_background_descendants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "tesseract"
    pid_file = tmp_path / "successful-probe-pids.txt"
    python = PROJECT_ROOT / ".venv/bin/python"
    executable.write_text(
        f"#!{python}\n"
        "import os, signal, time\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    os.close(1)\n"
        "    os.close(2)\n"
        "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        f"with open({str(pid_file)!r}, 'w', encoding='utf-8') as stream:\n"
        "    stream.write(f'{os.getpid()} {child}')\n"
        "print('tesseract 9.9.9', flush=True)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setattr(metrics.shutil, "which", lambda _name: str(executable))
    monkeypatch.setattr(metrics, "LOCAL_TOOL_PROBE_TIMEOUT_SECONDS", 2.0)

    process_group = 0
    descendant = 0
    try:
        assert metrics._probe_local_tool_version("tesseract") == "9.9.9"
        process_group, descendant = (
            int(value) for value in pid_file.read_text(encoding="utf-8").split()
        )
        _assert_process_and_group_gone(descendant, process_group)
    finally:
        if process_group > 0 and process_group != os.getpgrp():
            try:
                os.killpg(process_group, signal.SIGKILL)
            except (PermissionError, ProcessLookupError):
                pass


def test_public_source_and_predecessor_custody_rejects_repository_gaps(
    tmp_path: Path,
) -> None:
    m0_root = tmp_path / "missing-m0"
    m0_root.mkdir()
    m0_code = _write_required_repository_files(m0_root)
    m0_candidate = _bind_candidate_to_repository_code(
        _artifact_candidate(),
        m0_code,
        repository_root=m0_root,
    )
    (m0_root / metrics.M0_ARTIFACT["path"]).unlink()
    with pytest.raises(metrics.MetricsExecutionError, match="M0 baseline"):
        metrics.seal_metrics_artifact(
            m0_candidate,
            repository_root=m0_root,
        )

    missing_root = tmp_path / "missing-registry"
    missing_root.mkdir()
    missing_code = _write_required_repository_files(missing_root)
    missing_candidate = _bind_candidate_to_repository_code(
        _artifact_candidate(),
        missing_code,
        repository_root=missing_root,
    )
    registry_path = frozen_oracle.CORPUS_REGISTRY_CUSTODY["path"]
    (missing_root / registry_path).unlink()
    with pytest.raises(metrics.MetricsExecutionError, match="corpus registry"):
        metrics.seal_metrics_artifact(
            missing_candidate,
            repository_root=missing_root,
        )

    drift_root = tmp_path / "coordinated-source-drift"
    drift_root.mkdir()
    drift_code = _write_required_repository_files(drift_root)
    drift_candidate = _bind_candidate_to_repository_code(
        _artifact_candidate(),
        drift_code,
        repository_root=drift_root,
    )
    case_id = "catastrophe-recap"
    source_identity = frozen_oracle.SOURCE_IDENTITIES[case_id]
    source_path = drift_root / source_identity["path"]
    source_path.unlink()
    drifted_bytes = b"x" * source_identity["size_bytes"]
    source_path.write_bytes(drifted_bytes)
    drifted_sha256 = hashlib.sha256(drifted_bytes).hexdigest()
    for phase in ("pre", "post"):
        drift_candidate["input_custody"][phase][case_id]["sha256"] = drifted_sha256
    with pytest.raises(metrics.MetricsExecutionError, match="source PDF custody"):
        metrics.seal_metrics_artifact(
            drift_candidate,
            repository_root=drift_root,
        )

    symlink_root = tmp_path / "symlinked-predecessor"
    symlink_root.mkdir()
    symlink_code = _write_required_repository_files(symlink_root)
    symlink_candidate = _bind_candidate_to_repository_code(
        _artifact_candidate(),
        symlink_code,
        repository_root=symlink_root,
    )
    predecessor_path = (
        Path(frozen_oracle.PREDECESSOR_OUTPUT_ROOT) / case_id / "our-output.json"
    )
    linked_output = symlink_root / predecessor_path
    linked_output.unlink()
    linked_output.symlink_to(PROJECT_ROOT / predecessor_path)
    with pytest.raises(metrics.MetricsExecutionError, match="predecessor output"):
        metrics.seal_metrics_artifact(
            symlink_candidate,
            repository_root=symlink_root,
        )


def test_final_sealing_observes_explicit_extra_code_paths(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    observed = _write_required_repository_files(repository_root)
    extra_path = "tests/stories/phase_03/test_p03_us08_extra_security.py"
    extra = repository_root / extra_path
    extra.parent.mkdir(parents=True, exist_ok=True)
    extra.write_bytes(b"extra-security-test\n")
    explicit_paths = (*sorted(metrics.REQUIRED_CODE_PATHS), extra_path)
    observed = metrics.collect_code_file_identities(
        repository_root,
        paths=explicit_paths,
    )
    candidate = _bind_candidate_to_repository_code(
        _artifact_candidate(),
        observed,
        repository_root=repository_root,
    )

    with pytest.raises(readiness.ReadinessContractError, match="observed code"):
        metrics.seal_metrics_artifact(
            candidate,
            repository_root=repository_root,
        )
    metrics.seal_metrics_artifact(
        candidate,
        repository_root=repository_root,
        code_paths=explicit_paths,
    )


def test_default_code_custody_closes_parser_frontend_and_frozen_policy() -> None:
    ignored_build_directories = {".next", "coverage", "dist", "node_modules"}
    code_suffixes = {".mjs", ".mts", ".py", ".ts", ".tsx"}
    repository_code = {
        str(path.relative_to(PROJECT_ROOT))
        for top_level in ("app", "frontend")
        for path in (PROJECT_ROOT / top_level).rglob("*")
        if path.is_file()
        and path.suffix in code_suffixes
        and not ignored_build_directories.intersection(path.parts)
    }
    planned_running_region_code = {
        "app/services/running_regions.py",
        "frontend/lib/running-regions.ts",
        "frontend/tests/p03-us08-running-regions.test.mts",
    }
    fixed_us08_closure = {
        "tests/benchmarks/running_region_metrics.py",
        "tests/contract/test_p03_us08_api_model_strictness.py",
        "tests/contract/test_p03_us08_running_region_contract.py",
        "tests/fixtures/phase_03/running_regions/contract.py",
        "tests/fixtures/phase_03/running_regions/oracle.py",
        "tests/fixtures/phase_03/running_regions/synthetic.py",
        "tests/performance/test_p03_us08_running_region_metrics_contract.py",
        "tests/regression/phase_03/test_p03_us08_real_running_regions.py",
        "tests/stories/phase_03/test_p03_us08_running_regions.py",
        "frontend/app/globals.css",
        "frontend/tests/workspace-layout.test.mts",
        (
            "tracker/phase-03-layout/decisions/"
            "P03-running-regions-and-page-identity-policy.md"
        ),
    }

    assert len(metrics.REQUIRED_CODE_PATHS) == 86
    assert len(metrics.REQUIRED_CODE_PATHS) <= metrics.MAX_CODE_CUSTODY_FILES
    assert len(PHASE_04_TABLE_ONLY_RENEWAL_PATHS) == 5
    assert metrics.REQUIRED_CODE_PATHS.isdisjoint(
        PHASE_04_TABLE_ONLY_RENEWAL_PATHS
    )
    _assert_repository_code_is_frozen_or_phase_04_table_only(repository_code)
    assert planned_running_region_code <= metrics.REQUIRED_CODE_PATHS
    assert fixed_us08_closure <= metrics.REQUIRED_CODE_PATHS
    assert "app/services/tables.py" in metrics.REQUIRED_CODE_PATHS
    assert {
        path for path in metrics.REQUIRED_CODE_PATHS if path.startswith("tracker/")
    } == {
        (
            "tracker/phase-03-layout/decisions/"
            "P03-running-regions-and-page-identity-policy.md"
        )
    }
    assert {
        path
        for path in metrics.REQUIRED_CODE_PATHS
        if path.startswith("tests/stories/")
    } == {"tests/stories/phase_03/test_p03_us08_running_regions.py"}

    readiness_path = PHASE_04_TABLE_READINESS_IDENTITY["path"]
    readiness_bytes = (PROJECT_ROOT / readiness_path).read_bytes()
    assert {
        "path": readiness_path,
        "size_bytes": len(readiness_bytes),
        "sha256": hashlib.sha256(readiness_bytes).hexdigest(),
    } == PHASE_04_TABLE_READINESS_IDENTITY


@pytest.mark.parametrize(
    "sixth_path",
    [
        "app/services/table_semantics_helpers.py",
        "frontend/lib/table-semantics-helper.ts",
    ],
)
def test_phase_04_table_only_renewal_refuses_a_sixth_code_path(
    sixth_path: str,
) -> None:
    repository_code = (
        set(metrics.REQUIRED_CODE_PATHS)
        | set(PHASE_04_TABLE_ONLY_RENEWAL_PATHS)
        | {sixth_path}
    )

    with pytest.raises(AssertionError, match="outside frozen P03 custody"):
        _assert_repository_code_is_frozen_or_phase_04_table_only(repository_code)


@pytest.mark.parametrize(
    "relative_path",
    [
        "app/services/tables.py",
        (
            "tracker/phase-03-layout/decisions/"
            "P03-running-regions-and-page-identity-policy.md"
        ),
    ],
)
def test_default_code_custody_refuses_tables_and_policy_drift(
    tmp_path: Path,
    relative_path: str,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    observed = _write_required_repository_files(repository_root)
    sealed = metrics.seal_metrics_artifact(
        _bind_candidate_to_repository_code(
            _artifact_candidate(),
            observed,
            repository_root=repository_root,
        ),
        repository_root=repository_root,
    )

    changed_path = repository_root / relative_path
    changed_path.write_bytes(changed_path.read_bytes() + b"drift\n")
    changed = metrics.collect_code_file_identities(repository_root)
    assert changed[relative_path] != observed[relative_path]
    with pytest.raises(readiness.ReadinessContractError, match="observed code"):
        metrics.validate_metrics_artifact(
            sealed,
            repository_root=repository_root,
        )


def test_prior_failure_ledger_requires_exact_observed_coverage() -> None:
    first_path = (
        "tracker/phase-03-layout/evidence/"
        "P03-US08-running-region-metrics-attempt-01-failed.json"
    )
    observed = {
        first_path: {
            "size_bytes": 10,
            "sha256": "9" * 64,
            "status": "failed_measurement_candidate",
            "semantic_sha256": "8" * 64,
        }
    }
    prior = [{"path": first_path, **observed[first_path]}]
    second_path = first_path.replace("attempt-01", "attempt-02")

    fabricated = _failed_paired_candidate(
        1,
        retained_path=second_path,
        prior_failed_candidates=prior,
    )
    with pytest.raises(readiness.ReadinessContractError, match="coverage"):
        _seal_metrics_artifact(fabricated)

    omitted = _failed_paired_candidate(1, retained_path=second_path)
    with pytest.raises(readiness.ReadinessContractError, match="coverage"):
        _seal_metrics_artifact(
            omitted,
            existing_paths=[first_path],
            observed_prior_artifacts=observed,
        )

    without_identity = _failed_paired_candidate(1)
    with pytest.raises(readiness.ReadinessContractError, match="observed identity"):
        _seal_metrics_artifact(
            without_identity,
            existing_paths=[first_path],
        )


def test_public_seal_discovers_all_prior_attempts_and_rejects_omission(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    observed_code = _write_required_repository_files(repository_root)
    first_path = (
        "tracker/phase-03-layout/evidence/"
        "P03-US08-running-region-metrics-attempt-01-failed.json"
    )
    first = _bind_candidate_to_repository_code(
        _failed_paired_candidate(1, retained_path=first_path),
        observed_code,
        repository_root=repository_root,
    )
    sealed_first = metrics._seal_metrics_artifact_with_observations(
        first,
        observed_code_files=observed_code,
        observed_dependency_custody=deepcopy(first["dependency_custody"]),
        observed_input_custody=_observed_input_files(first),
        observed_m0_identity={
            field: first["m0_reference"][field]
            for field in metrics.CODE_FILE_IDENTITY_FIELDS
        },
        observed_predecessor_outputs=deepcopy(first["predecessor_custody"]["outputs"]),
        observed_prior_artifacts={},
    )
    first_file = repository_root / first_path
    first_file.parent.mkdir(parents=True, exist_ok=True)
    first_file.write_bytes(metrics._artifact_bytes(sealed_first))

    assert metrics.discover_existing_metrics_artifact_paths(repository_root) == (
        first_path,
    )
    prior_observations = metrics.collect_prior_artifact_identities(
        repository_root,
        [first_path],
    )
    prior_records = [{"path": first_path, **prior_observations[first_path]}]
    second_path = first_path.replace("attempt-01", "attempt-02")
    second = _bind_candidate_to_repository_code(
        _failed_paired_candidate(
            1,
            retained_path=second_path,
            prior_failed_candidates=prior_records,
        ),
        observed_code,
        repository_root=repository_root,
    )
    sealed_second = metrics.seal_metrics_artifact(
        second,
        repository_root=repository_root,
        expected_existing_paths=[first_path],
    )
    assert sealed_second["retained_path"] == second_path

    omitted = _bind_candidate_to_repository_code(
        _failed_paired_candidate(1, retained_path=second_path),
        observed_code,
        repository_root=repository_root,
    )
    with pytest.raises(readiness.ReadinessContractError, match="coverage"):
        metrics.seal_metrics_artifact(
            omitted,
            repository_root=repository_root,
        )
    with pytest.raises(readiness.ReadinessContractError, match="discovery"):
        metrics.seal_metrics_artifact(
            second,
            repository_root=repository_root,
            expected_existing_paths=[],
        )

    second_file = repository_root / second_path
    second_file.write_bytes(metrics._artifact_bytes(sealed_second))
    sequential_observations = metrics.collect_prior_artifact_identities(
        repository_root,
        [first_path, second_path],
    )
    sequential_records = [
        {"path": path, **sequential_observations[path]}
        for path in (first_path, second_path)
    ]
    final_candidate = _bind_candidate_to_repository_code(
        _artifact_candidate(prior_failed_candidates=sequential_records),
        observed_code,
        repository_root=repository_root,
    )
    sealed_final = metrics.seal_metrics_artifact(
        final_candidate,
        repository_root=repository_root,
        expected_existing_paths=[first_path, second_path],
    )
    assert sealed_final["prior_failed_candidates"] == sequential_records


def test_historical_attempts_keep_closed_code_and_dependency_epochs(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    code_epoch_a = _write_required_repository_files(repository_root)
    first_path = (
        "tracker/phase-03-layout/evidence/"
        "P03-US08-running-region-metrics-attempt-01-failed.json"
    )
    first_candidate = _bind_candidate_to_repository_code(
        _failed_paired_candidate(1, retained_path=first_path),
        code_epoch_a,
        repository_root=repository_root,
    )
    sealed_first = metrics.seal_metrics_artifact(
        first_candidate,
        repository_root=repository_root,
    )
    first_bytes = metrics._artifact_bytes(sealed_first)
    first_file = repository_root / first_path
    first_file.parent.mkdir(parents=True, exist_ok=True)
    first_file.write_bytes(first_bytes)

    tables_path = repository_root / "app/services/tables.py"
    tables_path.write_bytes(tables_path.read_bytes() + b"epoch-b\n")
    dependency_path = repository_root / "frontend/package.json"
    dependency_path.write_bytes(dependency_path.read_bytes() + b"\n")
    code_epoch_b = metrics.collect_code_file_identities(repository_root)
    dependency_epoch_b = metrics.collect_dependency_custody(repository_root)
    assert (
        code_epoch_b["app/services/tables.py"]
        != (code_epoch_a["app/services/tables.py"])
    )
    assert (
        dependency_epoch_b["manifests"]["frontend/package.json"]
        != (sealed_first["dependency_custody"]["manifests"]["frontend/package.json"])
    )

    first_observations = metrics.collect_prior_artifact_identities(
        repository_root,
        [first_path],
    )
    first_records = [{"path": first_path, **first_observations[first_path]}]
    second_path = first_path.replace("attempt-01", "attempt-02")
    second_candidate = _bind_candidate_to_repository_code(
        _failed_paired_candidate(
            1,
            retained_path=second_path,
            prior_failed_candidates=first_records,
        ),
        code_epoch_b,
        repository_root=repository_root,
    )
    sealed_second = metrics.seal_metrics_artifact(
        second_candidate,
        repository_root=repository_root,
        expected_existing_paths=[first_path],
    )
    second_file = repository_root / second_path
    second_file.write_bytes(metrics._artifact_bytes(sealed_second))

    sequential_observations = metrics.collect_prior_artifact_identities(
        repository_root,
        [first_path, second_path],
    )
    sequential_records = [
        {"path": path, **sequential_observations[path]}
        for path in (first_path, second_path)
    ]
    final_candidate = _bind_candidate_to_repository_code(
        _artifact_candidate(prior_failed_candidates=sequential_records),
        code_epoch_b,
        repository_root=repository_root,
    )
    sealed_final = metrics.seal_metrics_artifact(
        final_candidate,
        repository_root=repository_root,
        expected_existing_paths=[first_path, second_path],
    )
    assert sealed_final["code_sha256"] == second_candidate["code_sha256"]
    assert sealed_final["dependency_custody"] == dependency_epoch_b

    closed_tamper = deepcopy(sealed_first)
    closed_tables_identity = {
        "path": "app/services/tables.py",
        "size_bytes": 17,
        "sha256": "7" * 64,
    }
    for phase in ("pre", "post"):
        closed_tamper["code_sha256"][phase]["app/services/tables.py"] = deepcopy(
            closed_tables_identity
        )
    closed_tamper["code_sha256"]["manifest_sha256"] = metrics._sha256_json(
        closed_tamper["code_sha256"]["post"]
    )
    closed_tamper["semantic_sha256"] = metrics._artifact_semantic_sha256(closed_tamper)
    first_file.write_bytes(metrics._artifact_bytes(closed_tamper))
    metrics.collect_prior_artifact_identities(repository_root, [first_path])
    with pytest.raises(
        readiness.ReadinessContractError,
        match="prior failed candidate",
    ):
        metrics.collect_prior_artifact_identities(
            repository_root,
            [first_path, second_path],
        )

    invalid_dependency = deepcopy(sealed_first)
    invalid_dependency["dependency_custody"]["manifests"]["frontend/package.json"][
        "path"
    ] = "frontend/not-package.json"
    invalid_dependency["semantic_sha256"] = metrics._artifact_semantic_sha256(
        invalid_dependency
    )
    first_file.write_bytes(metrics._artifact_bytes(invalid_dependency))
    with pytest.raises(readiness.ReadinessContractError, match="path differs"):
        metrics.collect_prior_artifact_identities(repository_root, [first_path])


def test_prior_attempt_discovery_requires_full_semantic_artifacts(
    tmp_path: Path,
) -> None:
    first_path = (
        "tracker/phase-03-layout/evidence/"
        "P03-US08-running-region-metrics-attempt-01-failed.json"
    )

    minimal_root = tmp_path / "minimal"
    minimal_root.mkdir()
    _write_required_repository_files(minimal_root)
    minimal = {
        "generated_at": "2026-08-01T00:00:00+00:00",
        "status": "failed_measurement_candidate",
        "retained_path": first_path,
        "semantic_sha256": "0" * 64,
    }
    minimal["semantic_sha256"] = metrics._artifact_semantic_sha256(minimal)
    minimal_file = minimal_root / first_path
    minimal_file.parent.mkdir(parents=True, exist_ok=True)
    minimal_file.write_bytes(metrics._artifact_bytes(minimal))
    with pytest.raises(readiness.ReadinessContractError, match="keys"):
        metrics.collect_prior_artifact_identities(minimal_root, [first_path])

    malformed_root = tmp_path / "malformed"
    malformed_root.mkdir()
    malformed_code = _write_required_repository_files(malformed_root)
    malformed_candidate = _bind_candidate_to_repository_code(
        _failed_paired_candidate(1, retained_path=first_path),
        malformed_code,
        repository_root=malformed_root,
    )
    malformed = metrics.seal_metrics_artifact(
        malformed_candidate,
        repository_root=malformed_root,
    )
    malformed["quality"]["manufacturing_fused_contribution_exact"] = "yes"
    malformed["semantic_sha256"] = metrics._artifact_semantic_sha256(malformed)
    malformed_file = malformed_root / first_path
    malformed_file.parent.mkdir(parents=True, exist_ok=True)
    malformed_file.write_bytes(metrics._artifact_bytes(malformed))
    with pytest.raises(readiness.ReadinessContractError, match="Boolean"):
        metrics.collect_prior_artifact_identities(
            malformed_root,
            [first_path],
        )


def test_prior_attempt_json_is_strict_and_exclusive_writer_exact(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    observed_code = _write_required_repository_files(repository_root)
    first_path = (
        "tracker/phase-03-layout/evidence/"
        "P03-US08-running-region-metrics-attempt-01-failed.json"
    )
    candidate = _bind_candidate_to_repository_code(
        _failed_paired_candidate(1, retained_path=first_path),
        observed_code,
        repository_root=repository_root,
    )
    sealed = metrics.seal_metrics_artifact(
        candidate,
        repository_root=repository_root,
    )
    raw = metrics._artifact_bytes(sealed)
    artifact_file = repository_root / first_path
    artifact_file.parent.mkdir(parents=True, exist_ok=True)

    schema_line = b'  "schema_version": "1.0",\n'
    assert raw.count(schema_line) == 1
    artifact_file.write_bytes(raw.replace(schema_line, schema_line * 2, 1))
    with pytest.raises(metrics.MetricsExecutionError, match="strict JSON"):
        metrics.collect_prior_artifact_identities(
            repository_root,
            [first_path],
        )

    cost_line = b'  "hosted_cost_usd": 0,\n'
    assert raw.count(cost_line) == 1
    artifact_file.write_bytes(raw.replace(cost_line, b'  "hosted_cost_usd": NaN,\n', 1))
    with pytest.raises(metrics.MetricsExecutionError, match="strict JSON"):
        metrics.collect_prior_artifact_identities(
            repository_root,
            [first_path],
        )

    compact = json.dumps(
        sealed,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    artifact_file.write_bytes(compact)
    with pytest.raises(metrics.MetricsExecutionError, match="writer bytes"):
        metrics.collect_prior_artifact_identities(
            repository_root,
            [first_path],
        )


def test_prior_attempt_reader_accepts_cap_and_rejects_cap_plus_one(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    observed_code = _write_required_repository_files(repository_root)
    first_path = (
        "tracker/phase-03-layout/evidence/"
        "P03-US08-running-region-metrics-attempt-01-failed.json"
    )
    candidate = _bind_candidate_to_repository_code(
        _failed_paired_candidate(1, retained_path=first_path),
        observed_code,
        repository_root=repository_root,
    )
    sealed = metrics.seal_metrics_artifact(
        candidate,
        repository_root=repository_root,
    )
    boundary_artifact = deepcopy(sealed)
    boundary_case = next(
        iter(boundary_artifact["resource_boundaries"]["cases"].values())
    )
    boundary_case["production_hook"] = "x"
    boundary_artifact["semantic_sha256"] = metrics._artifact_semantic_sha256(
        boundary_artifact
    )
    boundary_raw = metrics._artifact_bytes(boundary_artifact)
    assert len(boundary_raw) < metrics.PRIOR_ARTIFACT_READ_CAP_BYTES
    boundary_case["production_hook"] += "x" * (
        metrics.PRIOR_ARTIFACT_READ_CAP_BYTES - len(boundary_raw)
    )
    boundary_artifact["semantic_sha256"] = metrics._artifact_semantic_sha256(
        boundary_artifact
    )
    at_cap = metrics._artifact_bytes(boundary_artifact)
    assert len(at_cap) == metrics.PRIOR_ARTIFACT_READ_CAP_BYTES
    artifact_file = repository_root / first_path
    artifact_file.parent.mkdir(parents=True, exist_ok=True)
    artifact_file.write_bytes(at_cap)
    observed = metrics.collect_prior_artifact_identities(
        repository_root,
        [first_path],
    )
    assert observed[first_path]["size_bytes"] == (metrics.PRIOR_ARTIFACT_READ_CAP_BYTES)

    over_cap_artifact = deepcopy(boundary_artifact)
    over_cap_case = next(
        iter(over_cap_artifact["resource_boundaries"]["cases"].values())
    )
    over_cap_case["production_hook"] += "x"
    over_cap_artifact["semantic_sha256"] = metrics._artifact_semantic_sha256(
        over_cap_artifact
    )
    over_cap = metrics._artifact_bytes(over_cap_artifact)
    assert len(over_cap) == metrics.PRIOR_ARTIFACT_READ_CAP_BYTES + 1
    artifact_file.write_bytes(over_cap)
    with pytest.raises(metrics.MetricsExecutionError, match="byte cap"):
        metrics.collect_prior_artifact_identities(
            repository_root,
            [first_path],
        )


def test_metrics_artifact_discovery_rejects_gaps_and_symlinked_evidence(
    tmp_path: Path,
) -> None:
    gap_root = tmp_path / "gap-repository"
    gap_evidence = gap_root / "tracker/phase-03-layout/evidence"
    gap_evidence.mkdir(parents=True)
    gap_path = gap_evidence / "P03-US08-running-region-metrics-attempt-02-failed.json"
    gap_path.write_bytes(b"{}\n")
    with pytest.raises(metrics.MetricsExecutionError, match="sequence"):
        metrics.discover_existing_metrics_artifact_paths(gap_root)

    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    (repository_root / "tracker/phase-03-layout").mkdir(parents=True)
    outside = tmp_path / "outside-evidence"
    outside.mkdir()
    (repository_root / "tracker/phase-03-layout/evidence").symlink_to(
        outside,
        target_is_directory=True,
    )
    with pytest.raises(metrics.MetricsExecutionError, match="symlink"):
        metrics.discover_existing_metrics_artifact_paths(repository_root)


def test_failed_artifact_attempts_are_monotonic_and_never_relabelled() -> None:
    existing = [
        (
            "tracker/phase-03-layout/evidence/"
            "P03-US08-running-region-metrics-attempt-01-failed.json"
        )
    ]
    path = metrics.next_failed_artifact_relative_path(existing)
    assert str(path) == (
        "tracker/phase-03-layout/evidence/"
        "P03-US08-running-region-metrics-attempt-02-failed.json"
    )
    observed = {
        existing[0]: {
            "size_bytes": 1,
            "sha256": "9" * 64,
            "status": "failed_measurement_candidate",
            "semantic_sha256": "8" * 64,
        }
    }
    prior = [{"path": existing[0], **observed[existing[0]]}]
    candidate = _failed_paired_candidate(
        1,
        retained_path=str(path),
        prior_failed_candidates=prior,
    )
    failed = _seal_metrics_artifact(
        candidate,
        existing_paths=existing,
        observed_prior_artifacts=observed,
    )
    assert failed["status"] == "failed_measurement_candidate"
    assert failed["retained_path"].endswith("attempt-02-failed.json")
    with pytest.raises(readiness.ReadinessContractError):
        _seal_metrics_artifact(
            {**failed, "status": "final_measurement_candidate"},
            existing_paths=existing,
            observed_prior_artifacts=observed,
        )


def test_exclusive_writer_preserves_existing_raw_artifact(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    observed = _write_required_repository_files(repository_root)
    artifact = metrics.seal_metrics_artifact(
        _bind_candidate_to_repository_code(
            _artifact_candidate(),
            observed,
            repository_root=repository_root,
        ),
        repository_root=repository_root,
    )
    path = repository_root / metrics.FINAL_ARTIFACT_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    identity = metrics.write_artifact_exclusive(
        path,
        artifact,
        repository_root=repository_root,
    )
    retained = path.read_bytes()
    assert identity == {
        "path": str(metrics.FINAL_ARTIFACT_RELATIVE_PATH),
        "size_bytes": len(retained),
        "sha256": hashlib.sha256(retained).hexdigest(),
    }
    assert json.loads(retained) == artifact

    with pytest.raises(readiness.ReadinessContractError, match="overwrite"):
        metrics.write_artifact_exclusive(
            path,
            artifact,
            repository_root=repository_root,
        )
    assert path.read_bytes() == retained


def test_exclusive_writer_rejects_parent_directory_swap_without_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    observed = _write_required_repository_files(repository_root)
    artifact = metrics.seal_metrics_artifact(
        _bind_candidate_to_repository_code(
            _artifact_candidate(),
            observed,
            repository_root=repository_root,
        ),
        repository_root=repository_root,
    )
    destination = repository_root / metrics.FINAL_ARTIFACT_RELATIVE_PATH
    evidence = destination.parent
    evidence.mkdir(parents=True, exist_ok=True)
    moved_evidence = tmp_path / "moved-evidence"
    outside = tmp_path / "outside"
    outside.mkdir()
    real_open = metrics.os.open
    swapped = False

    def swapping_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if (
            not swapped
            and isinstance(path, str)
            and path.startswith(f".{destination.name}.")
            and flags & os.O_CREAT
        ):
            evidence.rename(moved_evidence)
            evidence.symlink_to(outside, target_is_directory=True)
            swapped = True
        return real_open(path, flags, mode, dir_fd=dir_fd)

    with monkeypatch.context() as swapping:
        swapping.setattr(metrics.os, "open", swapping_open)
        with pytest.raises(
            readiness.ReadinessContractError,
            match="directory binding",
        ):
            metrics.write_artifact_exclusive(
                destination,
                artifact,
                repository_root=repository_root,
            )

    assert swapped is True
    assert list(outside.iterdir()) == []
    assert not (moved_evidence / destination.name).exists()
    assert not any(
        entry.name.startswith(f".{destination.name}.")
        for entry in moved_evidence.iterdir()
    )


def test_exclusive_writer_cleanup_preserves_replacement_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    observed = _write_required_repository_files(repository_root)
    artifact = metrics.seal_metrics_artifact(
        _bind_candidate_to_repository_code(
            _artifact_candidate(),
            observed,
            repository_root=repository_root,
        ),
        repository_root=repository_root,
    )
    destination = repository_root / metrics.FINAL_ARTIFACT_RELATIVE_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    replacement = b"concurrent-user-file\n"
    real_binding_check = metrics._repository_directory_binding_matches
    replaced = False

    def replace_before_binding_check(
        root: Path,
        relative: Any,
        expected: Any,
    ) -> bool:
        nonlocal replaced
        destination.unlink()
        destination.write_bytes(replacement)
        replaced = True
        assert real_binding_check(root, relative, expected) is True
        return False

    with monkeypatch.context() as replacing:
        replacing.setattr(
            metrics,
            "_repository_directory_binding_matches",
            replace_before_binding_check,
        )
        with pytest.raises(
            readiness.ReadinessContractError,
            match="directory binding",
        ):
            metrics.write_artifact_exclusive(
                destination,
                artifact,
                repository_root=repository_root,
            )

    assert replaced is True
    assert destination.read_bytes() == replacement
    assert not any(
        entry.name.startswith(f".{destination.name}.")
        for entry in destination.parent.iterdir()
    )


def test_exclusive_writer_final_reopen_refuses_replacement_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    observed = _write_required_repository_files(repository_root)
    artifact = metrics.seal_metrics_artifact(
        _bind_candidate_to_repository_code(
            _artifact_candidate(),
            observed,
            repository_root=repository_root,
        ),
        repository_root=repository_root,
    )
    destination = repository_root / metrics.FINAL_ARTIFACT_RELATIVE_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    replacement = b"replacement-at-final-reopen\n"
    real_open = metrics.os.open
    replaced = False

    def replacing_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal replaced
        if (
            not replaced
            and path == destination.name
            and dir_fd is not None
            and not flags & os.O_CREAT
        ):
            destination.unlink()
            destination.write_bytes(replacement)
            replaced = True
        return real_open(path, flags, mode, dir_fd=dir_fd)

    with monkeypatch.context() as replacing:
        replacing.setattr(metrics.os, "open", replacing_open)
        with pytest.raises(
            metrics.MetricsExecutionError,
            match="retained destination identity",
        ):
            metrics.write_artifact_exclusive(
                destination,
                artifact,
                repository_root=repository_root,
            )

    assert replaced is True
    assert destination.read_bytes() == replacement
    assert not any(
        entry.name.startswith(f".{destination.name}.")
        for entry in destination.parent.iterdir()
    )


def test_exclusive_writer_accepts_cap_and_rejects_cap_plus_one(
    tmp_path: Path,
) -> None:
    retained_path = (
        "tracker/phase-03-layout/evidence/"
        "P03-US08-running-region-metrics-attempt-01-failed.json"
    )
    exact_root = tmp_path / "exact-repository"
    exact_root.mkdir()
    exact_code = _write_required_repository_files(exact_root)
    exact_artifact = metrics.seal_metrics_artifact(
        _bind_candidate_to_repository_code(
            _failed_paired_candidate(1, retained_path=retained_path),
            exact_code,
            repository_root=exact_root,
        ),
        repository_root=exact_root,
    )
    boundary_case = next(iter(exact_artifact["resource_boundaries"]["cases"].values()))
    boundary_case["production_hook"] = "x"
    exact_artifact["semantic_sha256"] = metrics._artifact_semantic_sha256(
        exact_artifact
    )
    initial = metrics._artifact_bytes(exact_artifact)
    assert len(initial) < metrics.ARTIFACT_WRITE_CAP_BYTES
    boundary_case["production_hook"] += "x" * (
        metrics.ARTIFACT_WRITE_CAP_BYTES - len(initial)
    )
    exact_artifact["semantic_sha256"] = metrics._artifact_semantic_sha256(
        exact_artifact
    )
    exact_bytes = metrics._artifact_bytes(exact_artifact)
    assert len(exact_bytes) == metrics.ARTIFACT_WRITE_CAP_BYTES

    exact_destination = exact_root / retained_path
    exact_destination.parent.mkdir(parents=True, exist_ok=True)
    identity = metrics.write_artifact_exclusive(
        exact_destination,
        exact_artifact,
        repository_root=exact_root,
    )
    assert identity["size_bytes"] == metrics.ARTIFACT_WRITE_CAP_BYTES
    observed = metrics.collect_prior_artifact_identities(
        exact_root,
        [retained_path],
    )
    assert observed[retained_path]["size_bytes"] == (metrics.ARTIFACT_WRITE_CAP_BYTES)

    over_root = tmp_path / "over-repository"
    over_root.mkdir()
    _write_required_repository_files(over_root)
    over_artifact = deepcopy(exact_artifact)
    over_case = next(iter(over_artifact["resource_boundaries"]["cases"].values()))
    over_case["production_hook"] += "x"
    over_artifact["semantic_sha256"] = metrics._artifact_semantic_sha256(over_artifact)
    assert len(metrics._artifact_bytes(over_artifact)) == (
        metrics.ARTIFACT_WRITE_CAP_BYTES + 1
    )
    over_destination = over_root / retained_path
    over_destination.parent.mkdir(parents=True, exist_ok=True)
    with pytest.raises(readiness.ReadinessContractError, match="write byte cap"):
        metrics.write_artifact_exclusive(
            over_destination,
            over_artifact,
            repository_root=over_root,
        )
    assert not over_destination.exists()
    assert not any(
        entry.name.startswith(f".{over_destination.name}.")
        for entry in over_destination.parent.iterdir()
    )


def test_output_identity_uses_compact_utf8_canonical_json() -> None:
    value = {"z": "é", "a": [1, 2]}
    encoded = metrics._canonical_json(value).encode("utf-8")
    assert metrics.output_identity(value) == {
        "size_bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def test_json_recursion_and_unpaired_surrogates_are_normalized() -> None:
    nested: Any = None
    for _ in range(2_000):
        nested = [nested]
    with pytest.raises(metrics.MetricsExecutionError, match="JSON"):
        metrics._strict_detach(nested)
    with pytest.raises(metrics.MetricsExecutionError, match="semantic JSON"):
        metrics._artifact_semantic_sha256(
            {
                "generated_at": "2026-08-01T00:00:00+00:00",
                "semantic_sha256": "0" * 64,
                "nested": nested,
            }
        )

    deeply_nested_json = b"[" * 20_000 + b"null" + b"]" * 20_000
    with pytest.raises(metrics.MetricsExecutionError, match="strict JSON"):
        metrics._load_strict_json(deeply_nested_json)

    invalid_unicode = {"invalid": "\ud800"}
    unicode_surfaces = (
        lambda: metrics._canonical_json(invalid_unicode),
        lambda: metrics._strict_detach(invalid_unicode),
        lambda: metrics._sha256_json(invalid_unicode),
        lambda: metrics._artifact_bytes(invalid_unicode),
        lambda: metrics._bounded_artifact_bytes(
            invalid_unicode,
            maximum_bytes=metrics.ARTIFACT_WRITE_CAP_BYTES,
        ),
        lambda: metrics.output_identity(invalid_unicode),
    )
    for operation in unicode_surfaces:
        with pytest.raises(metrics.MetricsExecutionError, match="encoding"):
            operation()

    candidate = _artifact_candidate()
    candidate["generated_at"] = "\ud800"
    with pytest.raises(metrics.MetricsExecutionError, match="encoding"):
        _seal_metrics_artifact(candidate)


def test_production_flag_off_adapter_has_exact_call_shape_and_no_us08_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import pipeline

    case_id = "uber-earnings"
    running_region_module = "app.services.running_regions"
    monkeypatch.delitem(sys.modules, running_region_module, raising=False)
    source, predecessor = metrics._load_verified_source_and_predecessor(
        PROJECT_ROOT,
        case_id,
    )
    assert running_region_module not in sys.modules

    calls: list[tuple[bytes, str, bool]] = []

    def parse_document(
        observed_source: bytes,
        filename: str,
        settings: Any,
    ) -> dict[str, Any]:
        assert running_region_module not in sys.modules
        calls.append(
            (
                observed_source,
                filename,
                settings.layout_running_regions_enabled,
            )
        )
        return deepcopy(predecessor)

    monkeypatch.setattr(pipeline, "parse_document", parse_document)
    monkeypatch.setattr(
        metrics,
        "collect_code_file_identities",
        lambda _root: {"stable": True},
    )
    result = metrics.production_paired_worker(
        {"target_id": case_id, "state": "off"},
        repository_root=PROJECT_ROOT,
    )

    assert calls == [
        (
            source,
            Path(frozen_oracle.SOURCE_IDENTITIES[case_id]["path"]).name,
            False,
        )
    ]
    assert running_region_module not in sys.modules
    assert result["source_match"] is True
    assert result["code_match"] is True
    assert result["custody_match"] is True
    assert result["imports_loaded_before_timing"] is True
    assert set(result["output_variants"]) == set(metrics.OUTPUT_VARIANTS)

    drifted = deepcopy(predecessor)
    drifted["pages"][0]["items"][0]["value"] += " drift"
    with pytest.raises(
        metrics.MetricsExecutionError,
        match="predecessor semantic bytes",
    ):
        metrics._validate_flag_off_worker_output(drifted, predecessor)


@pytest.fixture(scope="module")
def _projected_uber_case() -> tuple[bytes, dict[str, Any], dict[str, Any], Any]:
    from app.services import running_regions

    source, predecessor, predecessor_ir = metrics._load_production_case(
        PROJECT_ROOT,
        "uber-earnings",
    )
    authority = running_regions.prepare_source_projection_authority(
        {
            "public": predecessor,
            "ir": predecessor_ir.model_dump(mode="json", exclude_none=True),
        },
        source,
    )
    projected, _ = running_regions.project_running_regions(
        deepcopy(predecessor),
        deepcopy(predecessor_ir),
        authority,
    )
    return source, predecessor, metrics._production_json(projected), running_regions


def test_production_flag_on_adapter_binds_exact_oracles_and_custody(
    monkeypatch: pytest.MonkeyPatch,
    _projected_uber_case: tuple[
        bytes,
        dict[str, Any],
        dict[str, Any],
        Any,
    ],
) -> None:
    from app.services import pipeline

    source, _predecessor, projected, running_regions = _projected_uber_case
    running_region_module = "app.services.running_regions"
    monkeypatch.delitem(sys.modules, running_region_module, raising=False)
    calls: list[tuple[bytes, str, bool]] = []

    def parse_document(
        observed_source: bytes,
        filename: str,
        settings: Any,
    ) -> dict[str, Any]:
        assert running_region_module not in sys.modules
        calls.append(
            (
                observed_source,
                filename,
                settings.layout_running_regions_enabled,
            )
        )
        sys.modules[running_region_module] = running_regions
        return deepcopy(projected)

    monkeypatch.setattr(pipeline, "parse_document", parse_document)
    monkeypatch.setattr(
        metrics,
        "collect_code_file_identities",
        lambda _root: {"stable": True},
    )
    result = metrics.production_paired_worker(
        {"target_id": "uber-earnings", "state": "on"},
        repository_root=PROJECT_ROOT,
    )

    assert calls == [
        (
            source,
            Path(frozen_oracle.SOURCE_IDENTITIES["uber-earnings"]["path"]).name,
            True,
        )
    ]
    assert result["source_match"] is True
    assert result["code_match"] is True
    assert result["custody_match"] is True
    assert result["imports_loaded_before_timing"] is True
    assert running_region_module in sys.modules


def test_production_json_retains_projected_summary_explicit_null_reason(
    _projected_uber_case: tuple[
        bytes,
        dict[str, Any],
        dict[str, Any],
        Any,
    ],
) -> None:
    from app.models import ParseResult

    _source, _predecessor, projected, _running_regions = _projected_uber_case
    typed = ParseResult.model_validate(projected)

    compact = metrics._production_json(typed)

    assert compact["processing"]["running_regions"]["reason"] is None
    identities = [page["page_identity"] for page in compact["pages"]]
    assert all("embedded_label" in identity for identity in identities)
    assert any(identity["embedded_label"] is None for identity in identities)
    assert all(
        "unavailable_reason" in identity["confidence"] for identity in identities
    )
    assert any(
        identity["confidence"]["unavailable_reason"] is None for identity in identities
    )
    descriptors = [
        item["running_region"]
        for page in compact["pages"]
        for item in page["items"]
        if "running_region" in item
    ]
    assert descriptors
    assert all("repetition_group_id" in descriptor for descriptor in descriptors)
    assert all(
        "unavailable_reason" in descriptor["confidence"] for descriptor in descriptors
    )
    readiness.validate_projected_document(compact)


def test_production_json_keeps_flag_off_compact_predecessor_exact() -> None:
    from app.models import ParseResult

    _source, predecessor, _predecessor_ir = metrics._load_production_case(
        PROJECT_ROOT,
        "uber-earnings",
    )
    materialized = deepcopy(predecessor)
    materialized["pages"][1]["items"][22]["confidence"] = None

    typed = ParseResult.model_validate(materialized)

    assert metrics._production_json(typed) == predecessor


@pytest.mark.parametrize(
    "invalid_state",
    (
        "failed_closed",
        "unavailable",
        "no_op",
        "identity_drift",
        "canonical_drift",
    ),
)
def test_flag_on_adapter_rejects_nonprojected_or_drifted_outputs(
    invalid_state: str,
    _projected_uber_case: tuple[
        bytes,
        dict[str, Any],
        dict[str, Any],
        Any,
    ],
) -> None:
    _source, predecessor, projected, _running_regions = _projected_uber_case
    invalid = deepcopy(projected)
    if invalid_state in {"failed_closed", "unavailable"}:
        invalid["processing"]["running_regions"]["status"] = invalid_state
        invalid["processing"]["running_regions"]["reason"] = invalid_state
    elif invalid_state == "no_op":
        invalid = deepcopy(predecessor)
    elif invalid_state == "identity_drift":
        invalid["pages"][0]["page_identity"]["semantic_sha256"] = "0" * 64
    else:
        invalid["canonical_presentation"]["pages"][0]["body"]["block_ids"].append(
            "drift"
        )

    with pytest.raises(metrics.MetricsExecutionError):
        metrics._validate_flag_on_worker_output(
            invalid,
            predecessor,
            case_id="uber-earnings",
        )


@pytest.mark.parametrize(
    ("profiler", "measurement_kind"),
    (
        (metrics._profile_timing, "latency"),
        (metrics._profile_allocation, "allocation"),
    ),
)
def test_isolated_profiles_release_full_output_before_next_sample(
    profiler: Any,
    measurement_kind: str,
) -> None:
    class WeakEnvelope(dict[str, Any]):
        pass

    prior_outputs: list[weakref.ReferenceType[WeakEnvelope]] = []
    measured_outputs: list[dict[str, Any]] = []
    report_sizes: list[int] = []
    observer = metrics._isolated_output_observer(
        stage="source_extraction",
        measurement_kind=measurement_kind,
        skip=(
            metrics.ISOLATED_LATENCY_WARMUPS
            if measurement_kind == "latency"
            else metrics.ISOLATED_ALLOCATION_WARMUPS
        ),
        measured_outputs=measured_outputs,
        report_sizes=report_sizes,
        expected_report=frozen_oracle.SOURCE_REPORTS["uber-earnings"],
    )

    def operation(_prepared: None) -> WeakEnvelope:
        if prior_outputs:
            gc.collect()
            assert prior_outputs[-1]() is None
        result = WeakEnvelope(
            source_report=deepcopy(frozen_oracle.SOURCE_REPORTS["uber-earnings"])
        )
        prior_outputs.append(weakref.ref(result))
        return result

    profiler(lambda: None, operation, observe_result=observer)
    gc.collect()
    assert prior_outputs[-1]() is None
    assert len(measured_outputs) == (
        metrics.ISOLATED_LATENCY_SAMPLES
        if measurement_kind == "latency"
        else metrics.ISOLATED_ALLOCATION_SAMPLES
    )
    assert len(report_sizes) == len(measured_outputs)


def test_clean_interpreter_worker_failure_retains_exact_empty_prefix() -> None:
    command = metrics._clean_worker_command(
        PROJECT_ROOT,
        readiness.paired_worker_plan()[0],
        fail=True,
    )
    assert command[:3] == [
        sys.executable,
        "-m",
        "tests.benchmarks.running_region_metrics",
    ]
    assert "--internal-paired-worker" in command
    assert command[-1] == "--internal-fail-worker"

    with pytest.raises(metrics.PairedCampaignFailure) as captured:
        metrics.run_clean_interpreter_paired_campaign(
            repository_root=PROJECT_ROOT,
            worker_timeout_seconds=10.0,
            fail_worker_index=0,
        )
    assert captured.value.campaign == {
        "runner_pid": os.getpid(),
        "worker_plan": [],
        "workers": [],
        "targets": {},
        "all_pass": False,
    }
    assert captured.value.failure == {
        "type": "worker_exit",
        "stage": "paired_parser",
        "target_id": "uber-earnings",
        "pair_index": 0,
        "state": "off",
    }


def test_production_candidate_uses_first_frozen_failure_and_seal_does_not_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _isolated_stage("source_extraction", 0.001)
    failed_target = source["targets"]["uber-earnings"]
    failed_latency = metrics.ISOLATED_SOURCE_EXTRACTION_P95_SECONDS + 0.001
    failed_target["latency_seconds"] = [
        failed_latency
    ] * metrics.ISOLATED_LATENCY_SAMPLES
    failed_target["summary"]["latency_p95_seconds"] = failed_latency
    failed_target["summary"]["passed"] = False
    source["all_pass"] = False
    projection = _isolated_stage("running_region_projection", 0.001)
    isolated_sizes = _output_sizes()

    monkeypatch.setattr(
        metrics,
        "_run_production_isolated_stages",
        lambda _root: (
            deepcopy(source),
            deepcopy(projection),
            _comparison_ledgers(),
            deepcopy(isolated_sizes),
        ),
    )
    monkeypatch.setattr(
        metrics,
        "_run_production_boundaries",
        lambda: (_resource_boundaries(), _deadline_boundaries()),
    )
    monkeypatch.setattr(
        metrics,
        "_run_production_quality_and_controls",
        lambda _root: (_quality(), _control_matrix(), _rollback()),
    )

    def pairing_must_not_run(**_kwargs: Any) -> dict[str, Any]:
        pytest.fail("pairing ran after an earlier frozen-stage failure")

    monkeypatch.setattr(
        metrics,
        "run_clean_interpreter_paired_campaign",
        pairing_must_not_run,
    )
    existing_before = metrics.discover_existing_metrics_artifact_paths(PROJECT_ROOT)
    candidate = metrics.build_production_metrics_candidate(PROJECT_ROOT)

    assert candidate["failures"] == [
        {
            "type": "stage_failed",
            "stage": "source_extraction",
            "target_id": "uber-earnings",
            "pair_index": None,
            "state": None,
        }
    ]
    assert candidate["paired_parser"]["worker_plan"] == []
    assert candidate["paired_parser"]["workers"] == []
    assert candidate["quality"]["running_region_denominator"] == 47

    destination = PROJECT_ROOT / candidate["retained_path"]
    assert not destination.exists()
    sealed = metrics.seal_metrics_artifact(
        candidate,
        repository_root=PROJECT_ROOT,
        expected_existing_paths=existing_before,
    )
    assert sealed["semantic_sha256"] == metrics._artifact_semantic_sha256(sealed)
    assert not destination.exists()
    assert (
        metrics.discover_existing_metrics_artifact_paths(PROJECT_ROOT)
        == existing_before
    )


def test_retained_final_artifact_matches_current_repository_custody() -> None:
    relative_path = PurePosixPath(str(metrics.FINAL_ARTIFACT_RELATIVE_PATH))
    destination = PROJECT_ROOT.joinpath(*relative_path.parts)
    if not destination.exists():
        pytest.skip("the retained final campaign artifact has not been written")
    raw = metrics._read_bounded_regular_repository_file(
        PROJECT_ROOT,
        relative_path,
        maximum_bytes=metrics.ARTIFACT_WRITE_CAP_BYTES,
        error="retained final metrics artifact differs",
    )
    artifact = metrics._load_strict_json(
        raw,
        error="retained final metrics artifact is not strict JSON",
    )
    assert isinstance(artifact, dict)
    metrics.validate_metrics_artifact(
        artifact,
        repository_root=PROJECT_ROOT,
    )
    assert artifact["status"] == "final_measurement_candidate"
    assert artifact["aggregate"]["all_pass"] is True
    assert artifact["failures"] == []
    assert artifact["semantic_sha256"] == metrics._artifact_semantic_sha256(artifact)
    assert {
        field: artifact[field]
        for field in ("hosted_requests", "hosted_tokens", "hosted_cost_usd")
    } == metrics.HOSTED_USAGE
