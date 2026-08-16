"""Executable acceptance guard for the time-bounded P03-US08 exception."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import traceback
from copy import deepcopy
from datetime import date
from pathlib import Path
from textwrap import indent
from typing import Any

import pytest

from app.config import Settings
from tests.benchmarks import running_region_metrics as metrics
from tests.fixtures.phase_03.running_regions import contract as readiness
from tests.fixtures.phase_03.running_regions import performance_exception as exception
from tests.fixtures.phase_latency import p03_continuity

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEMANTIC_ISOLATION_TERMINAL_LEAF_PATHS = (
    exception.SEMANTIC_ISOLATION_PHASE04_US01_STORY_GATE_PATH,
    exception.SEMANTIC_ISOLATION_PHASE04_FOCUSED_GATE_PATH,
    exception.SEMANTIC_ISOLATION_PHASE04_VERIFICATION_PATH,
    exception.SEMANTIC_ISOLATION_PHASE04_PRODUCTION_SECURITY_REVIEW_PATH,
    exception.SEMANTIC_ISOLATION_PHASE04_METRICS_CUSTODY_REVIEW_PATH,
    exception.SEMANTIC_ISOLATION_PHASE04_TERMINAL_APPROVAL_PATH,
)
SEMANTIC_ISOLATION_PENDING_TERMINAL_ERROR = (
    "semantic-isolation P04-US01 final-code story gate is absent or unreadable"
)
WAIVER_RAW_SHA256 = (
    "1fe75bc3d749730938653030052d463340eb2e856b810e0586e9afb12e9a72c8"
)
WAIVER_SIZE_BYTES = 4_873
DECISION_RAW_SHA256 = (
    "7bea63acad8403e442362edd8aabe0f4db084e6abd0cdd59e2b148b40a8b0d25"
)
DECISION_SIZE_BYTES = 3_476
RENEWAL_WAIVER_RAW_SHA256 = (
    "9e5761d53c8769daca3c2c59f37bfc99b1db12f89f28410e2b8667583a4e58d1"
)
RENEWAL_WAIVER_SIZE_BYTES = 5_236
RENEWAL_DECISION_RAW_SHA256 = (
    "6c1ac4c74a97f847122dd38877c6e44466795eddf1b73b26c84850ef775137e0"
)
RENEWAL_DECISION_SIZE_BYTES = 3_456
PHASE04_RENEWAL_WAIVER_RAW_SHA256 = (
    "5abc6cac91184bbd515ea855f49d168c614b53299f4415a29517e38441b9e02b"
)
PHASE04_RENEWAL_WAIVER_SIZE_BYTES = 6_007
PHASE04_RENEWAL_DECISION_RAW_SHA256 = (
    "951f9e2a73fecdb6fa591a807af882fec334b26d9c63fdbcee16d92b96b42aad"
)
PHASE04_RENEWAL_DECISION_SIZE_BYTES = 4_242
HARDENED_PHASE04_RENEWAL_WAIVER_RAW_SHA256 = (
    "5d0ac8411fd785eda1db1cbc01d2082ea09d65482ddba4796982cf0f60db4655"
)
HARDENED_PHASE04_RENEWAL_WAIVER_SIZE_BYTES = 22_113
HARDENED_PHASE04_RENEWAL_DECISION_RAW_SHA256 = (
    "bb3107b29f5a01876a64ee0179e1bff32b16bb93ecffa51da2f54c2d65510682"
)
HARDENED_PHASE04_RENEWAL_DECISION_SIZE_BYTES = 25_343


@pytest.fixture(autouse=True)
def _frozen_offline_dependency_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for field, value in metrics.OFFLINE_ENVIRONMENT.items():
        monkeypatch.setenv(field, value)


def _load_json(path: Path) -> dict[str, Any]:
    value = metrics._load_strict_json(
        path.read_bytes(),
        error=f"{path.name} is not strict JSON",
    )
    assert isinstance(value, dict)
    return value


def _waiver() -> dict[str, Any]:
    return _load_json(PROJECT_ROOT / exception.WAIVER_PATH)


def _path_entry_exists(path: Path) -> bool:
    """Observe path entries without treating dangling symlinks as absent."""

    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _validate_complete_terminal_chain_or_assert_pending(
    repository_root: Path,
    *,
    today: date | None = None,
) -> dict[str, Any] | None:
    """Validate a complete terminal chain or prove the all-absent pre-freeze."""

    present = tuple(
        str(path)
        for path in SEMANTIC_ISOLATION_TERMINAL_LEAF_PATHS
        if _path_entry_exists(repository_root / path)
    )
    if not present:
        with pytest.raises(
            readiness.ReadinessContractError,
            match=re.escape(SEMANTIC_ISOLATION_PENDING_TERMINAL_ERROR),
        ):
            exception.validate_performance_exception(
                repository_root,
                today=today,
            )
        return None

    if len(present) != len(SEMANTIC_ISOLATION_TERMINAL_LEAF_PATHS):
        missing = tuple(
            str(path)
            for path in SEMANTIC_ISOLATION_TERMINAL_LEAF_PATHS
            if str(path) not in present
        )
        raise AssertionError(
            "semantic-isolation terminal chain is partial; "
            f"present={present!r}; missing={missing!r}"
        )

    return exception.validate_performance_exception(
        repository_root,
        today=today,
    )


def _semantic_terminal_upstream() -> dict[str, Any]:
    identity = {
        "path": "synthetic",
        "raw_sha256": "a" * 64,
        "size_bytes": 1,
    }
    return {
        "decision": {**identity, "path": "decision"},
        "focused_test": {**identity, "path": "focused-test"},
        "guard": {**identity, "path": "guard"},
        "renewal": {
            **identity,
            "path": "renewal",
            "semantic_sha256": "b" * 64,
        },
        "p04_us01_story_gate": {
            **identity,
            "path": "p04-us01-story-gate",
            "semantic_sha256": "0" * 64,
        },
        "focused_gate_execution": {
            **identity,
            "path": "focused-gate",
            "semantic_sha256": "c" * 64,
        },
        "verification": {
            **identity,
            "path": "verification",
            "semantic_sha256": "d" * 64,
        },
        "production_security_review": {
            **identity,
            "path": "production-security-review",
            "semantic_sha256": "e" * 64,
        },
        "metrics_custody_review": {
            **identity,
            "path": "metrics-custody-review",
            "semantic_sha256": "f" * 64,
        },
    }


def _semantic_verification_upstream() -> dict[str, Any]:
    upstream = _semantic_terminal_upstream()
    upstream.pop("verification")
    upstream.pop("production_security_review")
    upstream.pop("metrics_custody_review")
    return upstream


def _semantic_terminal_review_identities(
    upstream: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    return {
        "production_security": deepcopy(
            upstream["production_security_review"]
        ),
        "metrics_custody": deepcopy(upstream["metrics_custody_review"]),
    }


def _semantic_terminal_reviewers() -> dict[str, str]:
    return {
        "production_security": "independent-production-security",
        "metrics_custody": "independent-metrics-custody",
    }


def _semantic_terminal_review_dates() -> dict[str, str]:
    return {
        "production_security": "2026-08-05",
        "metrics_custody": "2026-08-05",
    }


def _semantic_gate_inputs() -> dict[str, dict[str, Any]]:
    return {
        "tests/fixtures/phase_04/tables/oracle.py": {
            "path": "tests/fixtures/phase_04/tables/oracle.py",
            "raw_sha256": "9" * 64,
            "size_bytes": 90,
        }
    }


def _semantic_terminal_approval(
    renewal: dict[str, Any],
    upstream: dict[str, Any],
) -> dict[str, Any]:
    empty_findings = {
        "blocking_findings": [],
        "compatibility_findings": [],
        "correctness_findings": [],
        "custody_findings": [],
        "major_findings": [],
        "performance_findings": [],
        "security_findings": [],
    }
    return {
        "approved_on": "2026-08-05",
        "operative": True,
        "phase05_authorized": False,
        "production_use_authorized": False,
        "record_kind": (
            "p03_us08_phase04_tables_semantic_isolation_independent_approval"
        ),
        "renewal_id": renewal["renewal_id"],
        "reviews": [
            {
                "disposition": "APPROVED",
                "evidence_reviewed": [
                    "compatibility",
                    "correctness",
                    "production_code",
                    "resources",
                    "rollback",
                    "security",
                ],
                "independent": True,
                "review_role": "production_security",
                "review_artifact_identity": deepcopy(
                    upstream["production_security_review"]
                ),
                "reviewer_id": "independent-production-security",
                "self_review": False,
                **deepcopy(empty_findings),
            },
            {
                "disposition": "APPROVED",
                "evidence_reviewed": [
                    "attempt_48_latency_observation",
                    "custody",
                    "failed_history",
                    "hosted_usage",
                    "latency",
                    "metrics",
                    "peak_rss",
                ],
                "independent": True,
                "review_role": "metrics_custody",
                "review_artifact_identity": deepcopy(
                    upstream["metrics_custody_review"]
                ),
                "reviewer_id": "independent-metrics-custody",
                "self_review": False,
                **deepcopy(empty_findings),
            },
        ],
        "schema_version": "1.0",
        "scope_confirmation": {
            "exception_scope": renewal["exception_scope"],
            "expiry": renewal["expiry"],
            "not_waived": renewal["not_waived"],
            "operational_constraints": renewal["operational_constraints"],
            "phase05_authorized": False,
            "stories_in_dependency_order": renewal["closed_phase04_scope"][
                "stories_in_dependency_order"
            ],
            "strict_final_artifact_present": False,
        },
        "status": "INDEPENDENTLY_APPROVED",
        "upstream_identities": deepcopy(upstream),
    }


def _semantic_terminal_verification(
    *,
    upstream: dict[str, Any],
    production_code: dict[str, dict[str, Any]],
    dependency_custody: dict[str, Any],
    status_owners: dict[str, dict[str, Any]],
    us01_gate_inputs: dict[str, dict[str, Any]],
    protected_manifest_sha256: str = "d" * 64,
    protected_path_count: int = 83,
) -> dict[str, Any]:
    verification = {
        "checks": {
            "all_nonwaived_gates_passed": True,
            "default_off_rollback_verified": True,
            "final_code_identified": True,
            "latency_observation_unchanged": True,
            "metrics_and_custody_review_required": True,
            "production_and_security_review_required": True,
            "p04_us01_gate_inputs_identified": True,
            "strict_final_artifact_present": False,
        },
        "dependency_custody": deepcopy(dependency_custody),
        "dependency_custody_sha256": metrics._sha256_json(dependency_custody),
        "operative": False,
        "phase05_authorized": False,
        "production_code_identities": deepcopy(production_code),
        "production_code_manifest_sha256": metrics._sha256_json(
            production_code
        ),
        "production_use_authorized": False,
        "protected_code_manifest_sha256": protected_manifest_sha256,
        "protected_code_path_count": protected_path_count,
        "record_kind": (
            "p03_us08_phase04_tables_semantic_isolation_verification"
        ),
        "renewal_id": (
            "P03-US08-LATENCY-EXCEPTION-RENEWAL-20260805-"
            "PHASE04-TABLES-SEMANTIC-ISOLATION"
        ),
        "schema_version": "1.0",
        "status": "VERIFIED_AWAITING_INDEPENDENT_APPROVAL",
        "status_owner_identities": deepcopy(status_owners),
        "status_owner_manifest_sha256": metrics._sha256_json(status_owners),
        "upstream_identities": deepcopy(upstream),
        "us01_gate_input_identities": deepcopy(us01_gate_inputs),
        "us01_gate_input_manifest_sha256": metrics._sha256_json(
            us01_gate_inputs
        ),
    }
    verification["semantic_sha256"] = exception.waiver_semantic_sha256(
        verification
    )
    return verification


def _semantic_focused_gate_execution(
    *,
    production_code: dict[str, dict[str, Any]],
    dependency_custody: dict[str, Any],
    status_owners: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    findings = {
        field: [] for field in exception._SEMANTIC_ISOLATION_FINDING_FIELDS
    }
    execution = {
        "commands": [
            {
                "argv": list(exception._SEMANTIC_ISOLATION_FOCUSED_COMMANDS[0]),
                "exit_code": 0,
                "output_sha256": "6" * 64,
                "passed": 0,
                "skipped": 0,
                "warnings": 0,
            },
            {
                "argv": list(exception._SEMANTIC_ISOLATION_FOCUSED_COMMANDS[1]),
                "exit_code": 0,
                "output_sha256": "7" * 64,
                "passed": 723,
                "skipped": 0,
                "warnings": 1,
            },
        ],
        "environment": {
            "dependency_custody_sha256": metrics._sha256_json(
                dependency_custody
            ),
            "offline_environment": dict(metrics.OFFLINE_ENVIRONMENT),
            "phase04_flags": {
                name: False
                for name in exception.EXPECTED_HARDENED_PHASE04_SETTING_ORDER
            },
            "production_code_manifest_sha256": metrics._sha256_json(
                production_code
            ),
            "status_owner_manifest_sha256": metrics._sha256_json(
                status_owners
            ),
        },
        "executed_on": "2026-08-05",
        "findings": findings,
        "record_kind": (
            "p03_us08_phase04_tables_semantic_isolation_focused_gate"
        ),
        "renewal_id": (
            "P03-US08-LATENCY-EXCEPTION-RENEWAL-20260805-"
            "PHASE04-TABLES-SEMANTIC-ISOLATION"
        ),
        "schema_version": "1.0",
        "status": "PASS",
    }
    execution["semantic_sha256"] = exception.waiver_semantic_sha256(execution)
    return execution


def _semantic_us01_story_gate(
    *,
    root: Path,
    production_code: dict[str, dict[str, Any]],
    dependency_custody: dict[str, Any],
    status_owners: dict[str, dict[str, Any]],
    us01_gate_inputs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    findings = {
        field: [] for field in exception._SEMANTIC_ISOLATION_FINDING_FIELDS
    }
    results = {
        "product_correctness_quality": {
            "correctness_passed": True,
            "oracle_semantic_sha256": (
                exception._SEMANTIC_ISOLATION_US01_ORACLE_SEMANTIC_SHA256
            ),
            "quality_passed": True,
            "reviewed_real_document_count": len(
                exception._SEMANTIC_ISOLATION_US01_QUALITY_CASES
            ),
            "reviewed_real_document_ids": list(
                exception._SEMANTIC_ISOLATION_US01_QUALITY_CASES
            ),
            "synthetic_controls_passed": True,
        },
        "production_security": {
            "fail_closed_passed": True,
            "hosted_cost_usd": 0,
            "hosted_requests": 0,
            "hosted_tokens": 0,
            "malformed_input_passed": True,
            "security_passed": True,
        },
        "resource_timeout_output": {
            "allocation_passed": True,
            "deadline_passed": True,
            "memory_passed": True,
            "output_bounds_passed": True,
            "resource_passed": True,
            "timeout_passed": True,
        },
        "api_schema_serializer_compatibility": {
            "api_passed": True,
            "backward_compatibility_passed": True,
            "schema_passed": True,
            "serializer_passed": True,
        },
        "frontend_compatibility": {
            "build_passed": True,
            "bundle_passed": True,
            "lint_passed": True,
            "responsive_check_count": 22,
            "responsive_passed": True,
            "typecheck_passed": True,
            "unit_passed": True,
            "unit_test_count": 105,
        },
        "paired_latency_rss": {
            "case_results": {
                case: {
                    "phase04_peak_rss_ceiling_bytes": 67_108_864,
                    "phase04_peak_rss_delta_bytes": 1_024,
                    "phase04_table_stage_latency_ceiling_ratio": 0.10,
                    "phase04_table_stage_p50_overhead_ratio": 0.01,
                    "phase04_table_stage_p95_overhead_ratio": 0.02,
                    "within_phase04_peak_rss_ceiling": True,
                    "within_phase04_table_stage_latency_ceiling": True,
                }
                for case in sorted(
                    exception._SEMANTIC_ISOLATION_US01_PERFORMANCE_CASES
                )
            },
            "p03_attempt48_exception": {
                "attempt_status": "FAILED",
                "canonical_strict_final_artifact_present": False,
                "maximum_candidate_specific_bound": 0.05,
                "metric": "latency_p95_seconds",
                "observed_seconds": 0.050946750,
                "overrun_fraction": 0.018935,
                "overrun_seconds": 0.000946750,
                "stage": "running_region_projection",
                "strict_ceiling_seconds": 0.05,
                "target_id": "ny-timetable",
            },
            "p03_regression_gates": {
                "active_exception_gate_passed": True,
                "paired_parser_latency_regression_passed": True,
                "source_extraction_latency_regression_passed": True,
                "uber_projection_latency_regression_passed": True,
            },
            "phase04_pair_count": 5,
            "phase04_peak_rss_passed": True,
            "phase04_table_stage_latency_passed": True,
        },
        "rollback_default_off": {
            "default_off_passed": True,
            "phase04_flags": {
                name: False
                for name in exception.EXPECTED_HARDENED_PHASE04_SETTING_ORDER
            },
            "rollback_passed": True,
            "running_region_default_off_passed": True,
        },
        "dependency_custody": {
            "code_custody_passed": True,
            "dependency_changes_observed": False,
            "dependency_custody_sha256": metrics._sha256_json(
                dependency_custody
            ),
            "dependency_integrity_passed": True,
            "input_and_fixture_custody_passed": True,
        },
    }
    gates: dict[str, dict[str, Any]] = {}
    identity_manifest: dict[str, list[dict[str, Any]]] = {}
    for category in exception._SEMANTIC_ISOLATION_US01_GATE_CATEGORIES:
        path = (
            f"{exception.SEMANTIC_ISOLATION_PHASE04_US01_PREAPPROVAL_EVIDENCE_ROOT}/"
            f"{category}.json"
        )
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(
            {"category": category, "status": "PASS"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        target.write_bytes(raw)
        identity = exception._semantic_isolation_file_identity(path, raw)
        identity_manifest[category] = [deepcopy(identity)]
        gates[category] = {
            "artifact_identities": [deepcopy(identity)],
            "commands": [
                {
                    "argv": [
                        ".venv/bin/pytest",
                        "-q",
                        f"tests/stories/phase_04/test_p04_us01_{category}.py",
                    ],
                    "coverage_tags": sorted(
                        exception._SEMANTIC_ISOLATION_US01_COMMAND_COVERAGE[
                            category
                        ]
                    ),
                    "documented_skips": [],
                    "documented_warnings": [],
                    "exit_code": 0,
                    "output_artifact_identity": deepcopy(identity),
                    "output_sha256": identity["raw_sha256"],
                    "passed": 1,
                    "skipped": 0,
                    "warnings": 0,
                }
            ],
            "findings": deepcopy(findings),
            "result": "PASS",
            "results": deepcopy(results[category]),
        }
    gate = {
        "artifact_manifest_sha256": metrics._sha256_json(identity_manifest),
        "environment": {
            "dependency_custody_sha256": metrics._sha256_json(
                dependency_custody
            ),
            "offline_environment": dict(metrics.OFFLINE_ENVIRONMENT),
            "phase04_flags": {
                name: False
                for name in exception.EXPECTED_HARDENED_PHASE04_SETTING_ORDER
            },
            "production_code_manifest_sha256": metrics._sha256_json(
                production_code
            ),
            "status_owner_manifest_sha256": metrics._sha256_json(
                status_owners
            ),
            "us01_gate_input_identities": deepcopy(us01_gate_inputs),
            "us01_gate_input_manifest_sha256": metrics._sha256_json(
                us01_gate_inputs
            ),
        },
        "gates": gates,
        "generated_on": "2026-08-05",
        "phase05_authorized": False,
        "production_use_authorized": False,
        "record_kind": "p04_us01_final_code_gate_execution",
        "renewal_id": (
            "P03-US08-LATENCY-EXCEPTION-RENEWAL-20260805-"
            "PHASE04-TABLES-SEMANTIC-ISOLATION"
        ),
        "schema_version": "1.0",
        "status": "PASS",
        "story_id": "P04-US01",
    }
    gate["semantic_sha256"] = exception.waiver_semantic_sha256(gate)
    return gate


def _semantic_us01_story_gate_identity(
    gate: dict[str, Any],
) -> dict[str, Any]:
    raw = exception._pretty_json_bytes(gate)
    return {
        **exception._semantic_isolation_file_identity(
            str(exception.SEMANTIC_ISOLATION_PHASE04_US01_STORY_GATE_PATH),
            raw,
        ),
        "semantic_sha256": gate["semantic_sha256"],
    }


def _semantic_review_artifact(
    *,
    role: str,
    upstream: dict[str, Any],
    focused_gate: dict[str, Any],
    us01_story_gate: dict[str, Any],
    us01_story_gate_identity: dict[str, Any],
) -> dict[str, Any]:
    evidence = {
        "production_security": [
            "compatibility",
            "correctness",
            "production_code",
            "resources",
            "rollback",
            "security",
        ],
        "metrics_custody": [
            "attempt_48_latency_observation",
            "custody",
            "failed_history",
            "hosted_usage",
            "latency",
            "metrics",
            "peak_rss",
        ],
    }
    review = {
        "disposition": "APPROVED",
        "evidence_reviewed": evidence[role],
        "findings": {
            field: [] for field in exception._SEMANTIC_ISOLATION_FINDING_FIELDS
        },
        "focused_gate_commands_reviewed": deepcopy(focused_gate["commands"]),
        "focused_gate_environment_reviewed": deepcopy(
            focused_gate["environment"]
        ),
        "independent": True,
        "record_kind": (
            "p03_us08_phase04_tables_semantic_isolation_independent_review"
        ),
        "review_role": role,
        "reviewed_on": "2026-08-05",
        "reviewer_id": f"independent-{role.replace('_', '-')}",
        "schema_version": "1.0",
        "self_review": False,
        "upstream_identities": deepcopy(upstream),
        "us01_gate_input_identities_reviewed": deepcopy(
            us01_story_gate["environment"]["us01_gate_input_identities"]
        ),
        "us01_story_gate_identity_reviewed": deepcopy(
            us01_story_gate_identity
        ),
        "us01_story_gate_results_reviewed": deepcopy(
            us01_story_gate["gates"]
        ),
    }
    review["semantic_sha256"] = exception.waiver_semantic_sha256(review)
    return review


def _artifact(record: dict[str, Any]) -> dict[str, Any]:
    return _load_json(PROJECT_ROOT / record["physical_path"])


def _dependency_custody_bridge_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    """Reconstruct the exact historical P04 bridge observation.

    The live phase-latency pyproject adds only a pytest marker.  Historical
    mutation vectors must continue exercising the immutable P04 bridge, while
    the successor guard separately validates that additive marker delta.
    """

    waiver = _waiver()
    historical = deepcopy(
        _artifact(waiver["primary_candidate"])["dependency_custody"]
    )
    current = metrics.collect_dependency_custody(PROJECT_ROOT)
    current["manifests"]["pyproject.toml"] = deepcopy(
        exception.EXPECTED_SEMANTIC_ISOLATION_PHASE04_DEPENDENCY_CUSTODY_BRIDGE[
            "current_manifest_identities"
        ]["pyproject.toml"]
    )
    return historical, current


def _dependency_custody_bridge_test_root(tmp_path: Path) -> Path:
    for path in ("pyproject.toml", "uv.lock"):
        target = tmp_path / path
        raw = (PROJECT_ROOT / path).read_bytes()
        if path == "pyproject.toml":
            assert raw.count(p03_continuity.PYTEST_MARKER_DELTA) == 1
            raw = raw.replace(p03_continuity.PYTEST_MARKER_DELTA, b"", 1)
        target.write_bytes(raw)
    app_root = tmp_path / "app"
    app_root.mkdir()
    (app_root / "__init__.py").write_bytes(b'"""Synthetic app root."""\n')
    return tmp_path


def _set_dependency_bridge_nested_value(
    value: dict[str, Any],
    path: tuple[str, ...],
    replacement: Any,
) -> None:
    current: dict[str, Any] = value
    for part in path[:-1]:
        nested = current[part]
        assert isinstance(nested, dict)
        current = nested
    current[path[-1]] = replacement


def test_semantic_isolation_dependency_custody_bridge_accepts_only_exact_dev_pin(
    tmp_path: Path,
) -> None:
    historical, current = _dependency_custody_bridge_inputs()
    root = _dependency_custody_bridge_test_root(tmp_path)

    tracks = exception._validate_semantic_isolation_dependency_custody_bridge(
        root,
        bridge=deepcopy(
            exception.EXPECTED_SEMANTIC_ISOLATION_PHASE04_DEPENDENCY_CUSTODY_BRIDGE
        ),
        historical_dependency_custody=historical,
        current_dependency_custody=current,
    )

    tracked_paths = {path for path, *_ in tracks}
    assert {"pyproject.toml", "uv.lock"} <= tracked_paths
    assert any(path.startswith("app/") for path in tracked_paths)


def test_semantic_isolation_dependency_custody_bridge_is_explicitly_nonwaiving(
) -> None:
    bridge = (
        exception.EXPECTED_SEMANTIC_ISOLATION_PHASE04_DEPENDENCY_CUSTODY_BRIDGE
    )
    assert bridge["claims"] == {
        "compatibility_gate_waived": False,
        "dependency_custody_gate_waived": False,
        "further_manifest_change_authorized": False,
        "new_resolved_package_authorized": False,
        "runtime_or_production_dependency_change_authorized": False,
    }
    assert bridge["uv_lock_semantic"]["package_count"] == 140
    assert bridge["uv_lock_semantic"]["resolved_package_set_unchanged"] is True
    assert bridge["pyproject_semantic"]["production_dependencies_unchanged"] is True
    assert bridge["runtime_import_policy"] == {
        "direct_app_psutil_imports": [],
        "scanner_authorization_effect": "none",
    }
    assert set(
        exception.EXPECTED_SEMANTIC_ISOLATION_NON_AUTHORITATIVE_STATUS_SUMMARY_PATHS
    ) == {
        "tracker/phase-04-tables/metrics.md",
        "tracker/phase-04-tables/phase-regression.md",
    }
    assert set(
        exception.EXPECTED_SEMANTIC_ISOLATION_NON_AUTHORITATIVE_STATUS_SUMMARY_PATHS
    ) <= set(exception.SEMANTIC_ISOLATION_STATUS_OWNER_PATHS)


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("schema_id",), "open-schema-v2"),
        (("claims", "dependency_custody_gate_waived"), True),
        (("claims", "compatibility_gate_waived"), True),
        (("claims", "further_manifest_change_authorized"), True),
        (("pyproject_semantic", "allowed_dev_requirement"), "psutil>=7"),
        (("uv_lock_semantic", "package_count"), 141),
        (
            ("runtime_import_policy", "scanner_authorization_effect"),
            "authorizing",
        ),
    ],
)
def test_semantic_isolation_dependency_custody_bridge_rejects_record_widening(
    path: tuple[str, ...],
    replacement: Any,
) -> None:
    historical, current = _dependency_custody_bridge_inputs()
    bridge = deepcopy(
        exception.EXPECTED_SEMANTIC_ISOLATION_PHASE04_DEPENDENCY_CUSTODY_BRIDGE
    )
    _set_dependency_bridge_nested_value(bridge, path, replacement)

    with pytest.raises(
        readiness.ReadinessContractError,
        match="dependency custody bridge record differs",
    ):
        exception._validate_semantic_isolation_dependency_custody_bridge(
            PROJECT_ROOT,
            bridge=bridge,
            historical_dependency_custody=historical,
            current_dependency_custody=current,
        )


def test_semantic_isolation_dependency_custody_bridge_rejects_open_record() -> None:
    historical, current = _dependency_custody_bridge_inputs()
    bridge = deepcopy(
        exception.EXPECTED_SEMANTIC_ISOLATION_PHASE04_DEPENDENCY_CUSTODY_BRIDGE
    )
    bridge["extra"] = "open"

    with pytest.raises(
        readiness.ReadinessContractError,
        match="dependency custody bridge keys differ",
    ):
        exception._validate_semantic_isolation_dependency_custody_bridge(
            PROJECT_ROOT,
            bridge=bridge,
            historical_dependency_custody=historical,
            current_dependency_custody=current,
        )


@pytest.mark.parametrize(
    "mutation",
    ["runtime", "required_package", "frontend_manifest"],
)
def test_semantic_isolation_dependency_custody_bridge_rejects_other_custody(
    mutation: str,
) -> None:
    historical, current = _dependency_custody_bridge_inputs()
    if mutation == "runtime":
        current["runtime"]["python_version"] = "0.0.0"
    elif mutation == "required_package":
        current["python_packages"]["docling"]["version"] = "0.0.0"
    else:
        current["manifests"]["frontend/package.json"]["sha256"] = "0" * 64

    with pytest.raises(
        readiness.ReadinessContractError,
        match="dependency custody bridge digest differs",
    ):
        exception._validate_semantic_isolation_dependency_custody_bridge(
            PROJECT_ROOT,
            bridge=deepcopy(
                exception.EXPECTED_SEMANTIC_ISOLATION_PHASE04_DEPENDENCY_CUSTODY_BRIDGE
            ),
            historical_dependency_custody=historical,
            current_dependency_custody=current,
        )


@pytest.mark.parametrize(
    "mutation",
    ["pin", "production_dependency", "lock"],
)
def test_semantic_isolation_dependency_custody_bridge_rejects_manifest_bytes(
    tmp_path: Path,
    mutation: str,
) -> None:
    root = _dependency_custody_bridge_test_root(tmp_path)
    historical, current = _dependency_custody_bridge_inputs()
    if mutation == "pin":
        path = root / "pyproject.toml"
        path.write_bytes(path.read_bytes().replace(b"psutil==7.2.2", b"psutil==7.2.3"))
    elif mutation == "production_dependency":
        path = root / "pyproject.toml"
        path.write_bytes(
            path.read_bytes().replace(
                b'    "fastapi==0.139.2",\n',
                b'    "fastapi==0.139.2",\n    "forged-runtime==1",\n',
            )
        )
    else:
        path = root / "uv.lock"
        path.write_bytes(path.read_bytes() + b"# forged lock bytes\n")

    with pytest.raises(
        readiness.ReadinessContractError,
        match="dependency custody bridge current bytes differ",
    ):
        exception._validate_semantic_isolation_dependency_custody_bridge(
            root,
            bridge=deepcopy(
                exception.EXPECTED_SEMANTIC_ISOLATION_PHASE04_DEPENDENCY_CUSTODY_BRIDGE
            ),
            historical_dependency_custody=historical,
            current_dependency_custody=current,
        )


def test_semantic_isolation_dependency_custody_bridge_rejects_app_import(
    tmp_path: Path,
) -> None:
    root = _dependency_custody_bridge_test_root(tmp_path)
    historical, current = _dependency_custody_bridge_inputs()
    (root / "app" / "runtime.py").write_bytes(b"import psutil\n")

    with pytest.raises(
        readiness.ReadinessContractError,
        match="dependency custody bridge app import differs",
    ):
        exception._validate_semantic_isolation_dependency_custody_bridge(
            root,
            bridge=deepcopy(
                exception.EXPECTED_SEMANTIC_ISOLATION_PHASE04_DEPENDENCY_CUSTODY_BRIDGE
            ),
            historical_dependency_custody=historical,
            current_dependency_custody=current,
        )


def _synthetic_phase05_boundary(
    root: Path,
) -> dict[str, dict[str, Any]]:
    identities: dict[str, dict[str, Any]] = {}
    for path in sorted(exception._SEMANTIC_ISOLATION_PHASE05_BOUNDARY_PATHS):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = (
            b"# Boundary\n\nStatus: Proposed  \n"
            if path.endswith("/README.md") or "/stories/" in path
            else b"# Frozen Phase 05 planning boundary\n"
        )
        target.write_bytes(raw)
        identities[path] = exception._semantic_isolation_file_identity(
            path,
            raw,
        )
    return identities


def _serve_sealed_waiver(
    monkeypatch: pytest.MonkeyPatch,
    waiver: dict[str, Any],
) -> None:
    waiver["semantic_sha256"] = exception.waiver_semantic_sha256(waiver)
    replacement = exception._pretty_json_bytes(waiver)
    original = exception._read_bound_file

    def read_bound_file(
        root: Path,
        path: str,
        *,
        maximum_bytes: int,
        label: str,
    ) -> tuple[bytes, Any]:
        raw, binding = original(
            root,
            path,
            maximum_bytes=maximum_bytes,
            label=label,
        )
        if path == str(exception.WAIVER_PATH):
            return replacement, binding
        return raw, binding

    monkeypatch.setattr(exception, "_read_bound_file", read_bound_file)


def _frontend_with_canonical_table_delegation(
    delegation: str | None = None,
) -> bytes:
    source = (
        PROJECT_ROOT / "frontend/app/clearleaf-workspace.tsx"
    ).read_text(encoding="utf-8")
    fallback_context = (
        exception.EXPECTED_PHASE04_CANONICAL_FORM_BRANCH
        + exception.EXPECTED_PHASE04_CANONICAL_FALLBACK
    )
    replacement = (
        exception.EXPECTED_PHASE04_CANONICAL_FORM_BRANCH
        + (
            exception.EXPECTED_PHASE04_CANONICAL_TABLE_DELEGATION
            if delegation is None
            else delegation
        )
    )
    if source.count(fallback_context) == 1:
        return source.replace(fallback_context, replacement, 1).encode("utf-8")
    assert source.count(replacement) == 1
    return source.encode("utf-8")


_GEOMETRY_RAW_TABLE_SOURCE = '''@dataclass(slots=True)
class RawTable:
    """A text table located on a one-based physical PDF page."""

    page_index: int
    bbox: dict[str, float]
    rows: list[list[str]]
    row_bboxes: list[dict[str, float]]
    parse_concerns: list[str] = field(default_factory=list)
    cell_bboxes: tuple[tuple[dict[str, float] | None, ...], ...] = ()
    geometry_inferred: bool | None = None
'''

_GEOMETRY_CLEAN_TABLE_SOURCE = '''def _clean_table(
    page_index: int,
    table: Any,
    *,
    preserve_cell_geometry: bool = False,
) -> RawTable | None:
    """Extract rows, remove phantom margins, and retain source cell geometry."""

    extracted = table.extract(x_tolerance=2, y_tolerance=2) or []
    table_rows = list(getattr(table, "rows", []))
    row_count = max(len(extracted), len(table_rows))
    if row_count == 0:
        return None
    if preserve_cell_geometry and row_count > 4_096:
        return None

    normalized: list[list[str]] = []
    row_bboxes: list[dict[str, float]] = []
    cell_bboxes: list[list[dict[str, float] | None]] | None = None
    geometry_malformed = False
    if preserve_cell_geometry:
        cell_bboxes = []
    for index in range(row_count):
        values = extracted[index] if index < len(extracted) else []
        normalized.append([_normalize_cell(value) for value in values])
        if index < len(table_rows) and getattr(table_rows[index], "bbox", None):
            row_bboxes.append(_bbox_dict(table_rows[index].bbox))
        else:
            row_bboxes.append(_bbox_dict(table.bbox))
        if preserve_cell_geometry and cell_bboxes is not None:
            raw_cells = (
                getattr(table_rows[index], "cells", ())
                if index < len(table_rows)
                else ()
            )
            if not isinstance(raw_cells, (list, tuple)):
                geometry_malformed = True
                raw_cells = ()
            if len(raw_cells) > 256:
                return None
            geometry_row: list[dict[str, float] | None] = []
            for raw_cell in raw_cells:
                if raw_cell is None:
                    geometry_row.append(None)
                    continue
                if not isinstance(raw_cell, (list, tuple)) or len(raw_cell) != 4:
                    geometry_malformed = True
                    geometry_row.append(None)
                    continue
                try:
                    coordinates = tuple(float(value) for value in raw_cell)
                except (TypeError, ValueError):
                    geometry_malformed = True
                    geometry_row.append(None)
                    continue
                if (
                    any(
                        value != value or abs(value) == float("inf")
                        for value in coordinates
                    )
                    or coordinates[2] <= coordinates[0]
                    or coordinates[3] <= coordinates[1]
                ):
                    geometry_malformed = True
                    geometry_row.append(None)
                    continue
                geometry_row.append(_bbox_dict(coordinates))
            cell_bboxes.append(geometry_row)

    column_count = max((len(row) for row in normalized), default=0)
    if cell_bboxes is not None:
        column_count = max(
            column_count,
            max((len(row) for row in cell_bboxes), default=0),
        )
    if column_count == 0:
        return None
    if preserve_cell_geometry and (
        column_count > 256 or row_count * column_count > 65_536
    ):
        return None
    for row in normalized:
        row.extend([""] * (column_count - len(row)))
    if cell_bboxes is not None:
        for row in cell_bboxes:
            row.extend([None] * (column_count - len(row)))

    # Only trim unsupported empty edge columns. Source geometry makes an
    # explicit blank cell independently retainable.
    has_text = any(cell for row in normalized for cell in row)
    left, right = 0, column_count
    if cell_bboxes is not None:
        while left < right and all(
            not row[left] and cell_bboxes[index][left] is None
            for index, row in enumerate(normalized)
        ):
            left += 1
        while right > left and all(
            not row[right - 1] and cell_bboxes[index][right - 1] is None
            for index, row in enumerate(normalized)
        ):
            right -= 1
        normalized = [row[left:right] for row in normalized]
        cell_bboxes = [row[left:right] for row in cell_bboxes]
    elif has_text:
        while left < right and all(not row[left] for row in normalized):
            left += 1
        while right > left and all(not row[right - 1] for row in normalized):
            right -= 1
        normalized = [row[left:right] for row in normalized]

    kept_rows: list[list[str]] = []
    kept_bboxes: list[dict[str, float]] = []
    kept_cell_bboxes: list[list[dict[str, float] | None]] | None = None
    if cell_bboxes is not None:
        kept_cell_bboxes = []
    preserved_visual_row = False
    for index, (row, bbox) in enumerate(zip(normalized, row_bboxes, strict=True)):
        row_has_text = any(row)
        row_has_geometry = (
            cell_bboxes is not None and any(cell_bboxes[index])
        )
        is_visual_row = not row_has_text and bbox["h"] >= _MIN_VISUAL_ROW_HEIGHT
        if row_has_text or row_has_geometry or is_visual_row:
            kept_rows.append(row)
            kept_bboxes.append(bbox)
            if kept_cell_bboxes is not None and cell_bboxes is not None:
                kept_cell_bboxes.append(cell_bboxes[index])
            preserved_visual_row = preserved_visual_row or is_visual_row

    if not kept_rows:
        return None

    concerns = ["contains_empty_visual_rows"] if preserved_visual_row else []
    if preserve_cell_geometry and geometry_malformed:
        concerns.append("contains_malformed_cell_geometry")
    return RawTable(
        page_index=page_index,
        bbox=_bbox_dict(table.bbox),
        rows=kept_rows,
        row_bboxes=kept_bboxes,
        parse_concerns=concerns,
        cell_bboxes=(
            tuple(tuple(cell for cell in row) for row in kept_cell_bboxes)
            if kept_cell_bboxes is not None and not geometry_malformed
            else ()
        ),
    )
'''

_GEOMETRY_PAGE_CANDIDATES_SOURCE = '''def _page_candidates(
    page: Any,
    page_index: int,
    *,
    preserve_cell_geometry: bool = False,
) -> list[_Candidate]:
    """Run inferred explicit-border extraction plus pdfplumber's standard finder."""

    inferred: list[_Candidate] = []
    for x_boundaries, y_boundaries in _inferred_rule_groups(page):
        settings = {
            "vertical_strategy": "explicit",
            "horizontal_strategy": "explicit",
            "explicit_vertical_lines": x_boundaries,
            "explicit_horizontal_lines": y_boundaries,
            "snap_tolerance": 1.5,
            "join_tolerance": 1.5,
            "intersection_tolerance": 2.5,
            "edge_min_length": 3,
        }
        expected_bbox = (
            min(x_boundaries),
            min(y_boundaries),
            max(x_boundaries),
            max(y_boundaries),
        )
        expected_area = (expected_bbox[2] - expected_bbox[0]) * (
            expected_bbox[3] - expected_bbox[1]
        )
        for table in page.find_tables(settings):
            table_area = (table.bbox[2] - table.bbox[0]) * (
                table.bbox[3] - table.bbox[1]
            )
            intersection = _overlap_area(
                _bbox_dict(expected_bbox), _bbox_dict(table.bbox)
            )
            if min(expected_area, table_area) <= 0 or intersection / min(
                expected_area, table_area
            ) < 0.8:
                continue
            clean = _clean_table(
                page_index,
                table,
                preserve_cell_geometry=preserve_cell_geometry,
            )
            if clean is not None:
                inferred.append(_Candidate(clean, inferred=True))

    # pdfplumber exposes the perimeter of every rectangle as table edges.
    # Large fill-only rectangles are commonly text backgrounds or marked
    # content spans, so letting them participate can turn wrapped paragraphs
    # into ragged one-column tables and crop words at rectangle boundaries.
    standard_page = page.filter(lambda obj: not _is_fill_area_rect(obj))
    standard: list[_Candidate] = []
    for table in standard_page.find_tables():
        clean = _clean_table(
            page_index,
            table,
            preserve_cell_geometry=preserve_cell_geometry,
        )
        if clean is not None and _has_supported_standard_geometry(clean):
            standard.append(_Candidate(clean, inferred=False))

    # Inferred borders intentionally take precedence: default extraction often
    # mistakes filled text backgrounds for extra rows and tiny joints for
    # phantom columns.
    selected: list[_Candidate] = []
    for candidate in sorted(
        inferred,
        key=lambda value: value.table.bbox["w"] * value.table.bbox["h"],
        reverse=True,
    ):
        if not any(_is_duplicate(candidate.table, item.table) for item in selected):
            selected.append(candidate)
    for candidate in standard:
        if not any(_is_duplicate(candidate.table, item.table) for item in selected):
            selected.append(candidate)
    if preserve_cell_geometry:
        for candidate in selected:
            candidate.table.geometry_inferred = candidate.inferred
    return selected
'''

_GEOMETRY_EXTRACT_VECTOR_TABLES_SOURCE = '''def extract_vector_tables(
    pdf_bytes: bytes,
    *,
    preserve_cell_geometry: bool = False,
) -> dict[int, list[RawTable]]:
    """Extract bordered vector tables, keyed by one-based physical page index."""

    if not pdf_bytes:
        raise ValueError("pdf_bytes must not be empty")

    result: dict[int, list[RawTable]] = {}
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            candidates = _page_candidates(
                page,
                page_index,
                preserve_cell_geometry=preserve_cell_geometry,
            )
            tables = sorted(
                (candidate.table for candidate in candidates),
                key=lambda table: (table.bbox["y"], table.bbox["x"]),
            )
            result[page_index] = tables
    return result
'''

_GEOMETRY_TABLE_NODE_SOURCES = {
    "RawTable": _GEOMETRY_RAW_TABLE_SOURCE,
    "_clean_table": _GEOMETRY_CLEAN_TABLE_SOURCE,
    "_page_candidates": _GEOMETRY_PAGE_CANDIDATES_SOURCE,
    "extract_vector_tables": _GEOMETRY_EXTRACT_VECTOR_TABLES_SOURCE,
}


def _replace_top_level_nodes(
    raw: bytes,
    replacements: dict[str, str],
) -> bytes:
    source = raw.decode("utf-8")
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)
    spans: list[tuple[int, int, str]] = []
    for node in tree.body:
        name = getattr(node, "name", None)
        if name not in replacements:
            continue
        decorators = getattr(node, "decorator_list", [])
        start = min(
            [node.lineno, *(value.lineno for value in decorators)]
        ) - 1
        assert node.end_lineno is not None
        spans.append((start, node.end_lineno, replacements[str(name)]))
    assert {getattr(node, "name", None) for node in tree.body} >= set(replacements)
    for start, end, replacement in sorted(spans, reverse=True):
        lines[start:end] = replacement.splitlines(keepends=True)
    return "".join(lines).encode("utf-8")


def _tables_with_geometry_surface(raw: bytes | None = None) -> bytes:
    baseline = (
        (PROJECT_ROOT / "app/services/tables.py").read_bytes()
        if raw is None
        else raw
    )
    if exception._validate_hardened_phase04_tables_surface(baseline) == "geometry":
        return baseline
    return _replace_top_level_nodes(baseline, _GEOMETRY_TABLE_NODE_SOURCES)


def _pipeline_with_vector_geometry(raw: bytes | None = None) -> bytes:
    baseline = (
        (PROJECT_ROOT / "app/services/pipeline.py").read_bytes()
        if raw is None
        else raw
    )
    old = indent(
        exception.EXPECTED_HARDENED_PIPELINE_VECTOR_BASELINE_TRY_SOURCE,
        "    ",
    ).encode("utf-8")
    new = indent(
        exception.EXPECTED_HARDENED_PIPELINE_VECTOR_GEOMETRY_TRY_SOURCE,
        "    ",
    ).encode("utf-8")
    return _replace_once(baseline, old, new)


def _pipeline_with_baseline_table_repair(raw: bytes | None = None) -> bytes:
    candidate = (
        (PROJECT_ROOT / "app/services/pipeline.py").read_bytes()
        if raw is None
        else raw
    )
    candidate = _replace_top_level_nodes(
        candidate,
        {
            "_table_repair_page_indexes": (
                exception.EXPECTED_HARDENED_PIPELINE_TABLE_REPAIR_BASELINE_PAGE_INDEX_SOURCE
            ),
            "_extract_table_repair_words": (
                exception.EXPECTED_HARDENED_PIPELINE_TABLE_REPAIR_BASELINE_EXTRACT_SOURCE
            ),
        },
    )
    old = indent(
        exception.EXPECTED_HARDENED_PIPELINE_TABLE_REPAIR_CANDIDATE_TRY_SOURCE,
        "    ",
    ).encode("utf-8")
    new = indent(
        exception.EXPECTED_HARDENED_PIPELINE_TABLE_REPAIR_BASELINE_TRY_SOURCE,
        "    ",
    ).encode("utf-8")
    return _replace_once(candidate, old, new)


def test_sealed_latency_exception_matches_all_repository_custody() -> None:
    waiver_path = PROJECT_ROOT / exception.WAIVER_PATH
    raw = waiver_path.read_bytes()

    assert len(raw) == WAIVER_SIZE_BYTES
    assert hashlib.sha256(raw).hexdigest() == WAIVER_RAW_SHA256
    continuity = p03_continuity.validate_latency_continuity_renewal(
        PROJECT_ROOT,
        # This is the live repository-custody gate, not a historical fixture.
        # Omit an override so the guard resolves its UTC current date; fixed
        # dates below remain deliberate historical/mutation fixtures.
    )
    assert continuity["strict_current_artifact_pass"] is False
    assert continuity["production_approval"] is False
    waiver = _waiver()
    assert waiver["semantic_sha256"] == (
        "0d3cd13942dd465c537dd7075baf0d2e8b30bc5dd891af55622c07f493610554"
    )
    assert waiver["approval"]["statements"] == list(
        exception.EXPECTED_APPROVAL_STATEMENTS
    )
    assert waiver["failed_history"] == {
        "artifact_count": 55,
        "first_path": (
            "tracker/phase-03-layout/evidence/"
            "P03-US08-running-region-metrics-attempt-01-failed.json"
        ),
        "last_path": (
            "tracker/phase-03-layout/evidence/"
            "P03-US08-running-region-metrics-attempt-55-failed.json"
        ),
        "manifest_sha256": (
            "bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff"
        ),
    }
    renewal_path = PROJECT_ROOT / exception.RENEWAL_WAIVER_PATH
    renewal_raw = renewal_path.read_bytes()
    renewal = _load_json(renewal_path)

    assert len(renewal_raw) == RENEWAL_WAIVER_SIZE_BYTES
    assert hashlib.sha256(renewal_raw).hexdigest() == RENEWAL_WAIVER_RAW_SHA256
    assert renewal["semantic_sha256"] == (
        "c650af287d8010d5a94c4c572f41538e3249c4acf4653531f2e37eab208d39e8"
    )
    assert renewal["approval"]["statement"] == (
        exception.EXPECTED_RENEWAL_APPROVAL_STATEMENT
    )
    assert tuple(renewal["authorized_change"]["differing_paths"]) == (
        exception.EXPECTED_RENEWAL_CODE_DIFFERENCES
    )
    phase04_path = PROJECT_ROOT / exception.PHASE04_RENEWAL_WAIVER_PATH
    phase04_raw = phase04_path.read_bytes()
    phase04 = _load_json(phase04_path)
    assert len(phase04_raw) == PHASE04_RENEWAL_WAIVER_SIZE_BYTES
    assert (
        hashlib.sha256(phase04_raw).hexdigest()
        == PHASE04_RENEWAL_WAIVER_RAW_SHA256
    )
    assert phase04["exception_scope"] == waiver["exception_scope"]
    assert phase04["failed_history"] == waiver["failed_history"]
    assert phase04["not_waived"] == waiver["not_waived"]
    assert phase04["operational_constraints"] == waiver["operational_constraints"]
    assert phase04["authorized_change"]["phase04_only"] is True
    assert phase04["authorized_change"]["running_region_behavior_changed"] is False
    assert phase04["authorized_change"]["running_region_custody_changed"] is False
    hardened_path = PROJECT_ROOT / exception.HARDENED_PHASE04_RENEWAL_WAIVER_PATH
    hardened_raw = hardened_path.read_bytes()
    hardened = _load_json(hardened_path)
    assert len(hardened_raw) == HARDENED_PHASE04_RENEWAL_WAIVER_SIZE_BYTES
    assert (
        hashlib.sha256(hardened_raw).hexdigest()
        == HARDENED_PHASE04_RENEWAL_WAIVER_RAW_SHA256
    )
    assert hardened["exception_scope"] == waiver["exception_scope"]
    assert hardened["failed_history"] == waiver["failed_history"]
    assert hardened["not_waived"] == waiver["not_waived"]
    assert hardened["operational_constraints"] == waiver["operational_constraints"]
    assert hardened["authorized_change"]["phase04_only"] is True
    assert hardened["authorized_change"]["running_region_behavior_changed"] is False
    assert hardened["authorized_change"]["running_region_custody_changed"] is False
    assert hardened["authorized_change"]["sealed_exact_paths"] == {}
    assert tuple(
        hardened["authorized_change"]["protected_surfaces"][
            "app/services/pipeline.py"
        ]["allowed_function_names"]
    ) == tuple(
        sorted(
            exception.EXPECTED_HARDENED_PHASE04_PIPELINE_FUNCTIONS
            | exception.EXPECTED_HARDENED_PHASE04_PIPELINE_EXACT_FUNCTIONS
        )
    )
    assert "_merge_body_items" not in hardened["authorized_change"][
        "protected_surfaces"
    ]["app/services/pipeline.py"]["allowed_function_names"]


def test_live_repository_gate_uses_guard_utc_date_without_backdating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live_calls: list[tuple[Path, dict[str, Any]]] = []

    def capture_live_gate(
        repository_root: Path,
        **kwargs: Any,
    ) -> dict[str, bool]:
        live_calls.append((repository_root, kwargs))
        return {
            "strict_current_artifact_pass": False,
            "production_approval": False,
        }

    monkeypatch.setattr(
        p03_continuity,
        "validate_latency_continuity_renewal",
        capture_live_gate,
    )
    test_sealed_latency_exception_matches_all_repository_custody()
    assert live_calls == [(PROJECT_ROOT, {})]

    utc_calls: list[Any] = []
    real_datetime = exception.datetime

    class CapturingDateTime:
        @staticmethod
        def now(*, tz: Any) -> Any:
            utc_calls.append(tz)
            return real_datetime(2026, 8, 6, tzinfo=tz)

    monkeypatch.setattr(exception, "datetime", CapturingDateTime)
    renewal = _load_json(
        PROJECT_ROOT / exception.SEMANTIC_ISOLATION_PHASE04_RENEWAL_WAIVER_PATH
    )
    exception._semantic_isolation_validate_expiry(
        renewal["expiry"],
        today=None,
    )
    assert utc_calls == [exception.UTC]
    assert renewal["semantic_isolation"]["activation_policy"][
        "live_gate_date_policy"
    ] == {
        "historical_fixed_dates_preserved": True,
        "live_override_supplied": False,
        "timezone": "UTC",
    }


def test_decision_and_all_renewal_candidates_preserve_immutable_ancestry() -> None:
    waiver = _waiver()
    decision_path = PROJECT_ROOT / waiver["decision_identity"]["path"]
    decision_raw = decision_path.read_bytes()

    assert len(decision_raw) == DECISION_SIZE_BYTES
    assert hashlib.sha256(decision_raw).hexdigest() == DECISION_RAW_SHA256
    assert waiver["primary_candidate"]["status"] == "failed_measurement_candidate"
    assert waiver["complete_companion"]["status"] == "final_measurement_candidate"
    assert "post-seal-invalid" in waiver["complete_companion"]["physical_path"]
    assert not (PROJECT_ROOT / metrics.FINAL_ARTIFACT_RELATIVE_PATH).exists()
    renewal = _load_json(PROJECT_ROOT / exception.RENEWAL_WAIVER_PATH)
    renewal_decision = PROJECT_ROOT / renewal["decision_identity"]["path"]
    renewal_decision_raw = renewal_decision.read_bytes()

    assert len(renewal_decision_raw) == RENEWAL_DECISION_SIZE_BYTES
    assert (
        hashlib.sha256(renewal_decision_raw).hexdigest()
        == RENEWAL_DECISION_RAW_SHA256
    )
    assert renewal["original_decision_identity"] == waiver["decision_identity"]
    assert renewal["original_waiver_identity"] == {
        "path": str(exception.WAIVER_PATH),
        "raw_sha256": WAIVER_RAW_SHA256,
        "semantic_sha256": waiver["semantic_sha256"],
        "size_bytes": WAIVER_SIZE_BYTES,
        "waiver_id": waiver["waiver_id"],
    }
    phase04 = _load_json(PROJECT_ROOT / exception.PHASE04_RENEWAL_WAIVER_PATH)
    phase04_decision = PROJECT_ROOT / phase04["decision_identity"]["path"]
    phase04_decision_raw = phase04_decision.read_bytes()
    assert len(phase04_decision_raw) == PHASE04_RENEWAL_DECISION_SIZE_BYTES
    assert (
        hashlib.sha256(phase04_decision_raw).hexdigest()
        == PHASE04_RENEWAL_DECISION_RAW_SHA256
    )
    assert phase04["prior_renewal_identity"] == {
        "path": str(exception.RENEWAL_WAIVER_PATH),
        "raw_sha256": RENEWAL_WAIVER_RAW_SHA256,
        "semantic_sha256": renewal["semantic_sha256"],
        "size_bytes": RENEWAL_WAIVER_SIZE_BYTES,
    }
    hardened = _load_json(
        PROJECT_ROOT / exception.HARDENED_PHASE04_RENEWAL_WAIVER_PATH
    )
    hardened_decision = PROJECT_ROOT / hardened["decision_identity"]["path"]
    hardened_decision_raw = hardened_decision.read_bytes()
    assert (
        len(hardened_decision_raw)
        == HARDENED_PHASE04_RENEWAL_DECISION_SIZE_BYTES
    )
    assert (
        hashlib.sha256(hardened_decision_raw).hexdigest()
        == HARDENED_PHASE04_RENEWAL_DECISION_RAW_SHA256
    )
    assert hardened["prior_renewal_identity"] == {
        "path": str(exception.PHASE04_RENEWAL_WAIVER_PATH),
        "raw_sha256": PHASE04_RENEWAL_WAIVER_RAW_SHA256,
        "semantic_sha256": phase04["semantic_sha256"],
        "size_bytes": PHASE04_RENEWAL_WAIVER_SIZE_BYTES,
    }
    current_code = metrics.collect_code_file_identities(PROJECT_ROOT)
    companion_code = _artifact(waiver["complete_companion"])["code_sha256"][
        "post"
    ]
    observed_companion_differences = {
        path
        for path in current_code
        if current_code[path] != companion_code[path]
    }
    predecessor_differences = set(
        exception.EXPECTED_RENEWED_COMPANION_CODE_DIFFERENCES
    )
    assert predecessor_differences <= observed_companion_differences
    semantic = _load_json(
        PROJECT_ROOT / exception.SEMANTIC_ISOLATION_PHASE04_RENEWAL_WAIVER_PATH
    )
    assert semantic["prior_hardened_renewal_identity"] == {
        "path": str(exception.HARDENED_PHASE04_RENEWAL_WAIVER_PATH),
        **exception.EXPECTED_HARDENED_PHASE04_RENEWAL_WAIVER_IDENTITY,
    }
    assert semantic["status"] == (
        "requester_authorized_pending_independent_approval"
    )
    assert semantic["verification_state"]["operative"] is False
    scope = semantic["closed_phase04_scope"]
    assert "app/models.py" in scope["shared_python_paths"]
    assert (
        "app/services/opaque_group_custody.py"
        in scope["dedicated_python_paths"]
    )


def test_exception_is_exactly_the_near_boundary_projection_observation() -> None:
    scope = _waiver()["exception_scope"]
    renewal = _load_json(PROJECT_ROOT / exception.RENEWAL_WAIVER_PATH)

    assert scope == {
        "candidate_specific": True,
        "maximum_overrun_fraction": 0.05,
        "metric": "latency_p95_seconds",
        "observed_seconds": 0.05094675,
        "overrun_fraction": 0.018935,
        "overrun_seconds": 0.00094675,
        "stage": "running_region_projection",
        "strict_ceiling_seconds": 0.05,
        "target_id": "ny-timetable",
    }
    assert renewal["exception_scope"] == scope
    assert renewal["authorized_change"] == {
        "all_other_required_code_paths_match_original": True,
        "difference_scope": "frontend-only bbox compatibility fix",
        "differing_paths": list(exception.EXPECTED_RENEWAL_CODE_DIFFERENCES),
        "measured_backend_parser_runtime_paths_match_original": True,
        "original_code_manifest_sha256": (
            "30e6025c3d5f02f2797476cb56ecbdb2349ddc0a57b730fc01e35a9667ce1e3f"
        ),
        "original_files": {
            "frontend/lib/running-regions.ts": {
                "path": "frontend/lib/running-regions.ts",
                "sha256": (
                    "73bad8a2ac6ce143ae69f9dc50dc61e955a42c56f0f8476d8bba12de3edf786d"
                ),
                "size_bytes": 49_506,
            },
            "frontend/tests/p03-us08-running-regions.test.mts": {
                "path": "frontend/tests/p03-us08-running-regions.test.mts",
                "sha256": (
                    "20772d1f5a34b4c3834af6b4dea5becacbf91cac33f60dca41bf7ed4fef3549d"
                ),
                "size_bytes": 33_483,
            },
        },
        "renewed_code_manifest_sha256": (
            "b5bfab2739f231a57abddf787a6c566c5fddec5b2128bd4892f3682622a06fcc"
        ),
        "renewed_files": exception.EXPECTED_RENEWAL_FILE_IDENTITIES,
        "required_code_path_count": 86,
    }


def test_running_regions_remain_default_off_with_exact_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiver = _waiver()
    env_example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

    monkeypatch.delenv("PARSER_LAYOUT_RUNNING_REGIONS_ENABLED", raising=False)
    assert "PARSER_LAYOUT_RUNNING_REGIONS_ENABLED=false" in env_example.splitlines()
    assert Settings().layout_running_regions_enabled is False
    assert Settings.from_env().layout_running_regions_enabled is False
    assert waiver["operational_constraints"] == {
        "canonical_strict_final_artifact_present": False,
        "feature_flag": "PARSER_LAYOUT_RUNNING_REGIONS_ENABLED",
        "feature_flag_default": False,
        "rollback": (
            "disable the flag to skip US08 work and return the exact configured "
            "predecessor"
        ),
    }


def test_semantic_isolation_freezes_shared_running_region_surfaces() -> None:
    config = (PROJECT_ROOT / "app/config.py").read_bytes()
    pipeline = (PROJECT_ROOT / "app/services/pipeline.py").read_bytes()
    frontend = (PROJECT_ROOT / "frontend/app/clearleaf-workspace.tsx").read_bytes()

    assert exception._phase04_config_normalized_digest(config) == (
        exception.EXPECTED_PHASE04_CONFIG_NORMALIZED_AST_SHA256
    )
    renewal = _load_json(
        PROJECT_ROOT / exception.SEMANTIC_ISOLATION_PHASE04_RENEWAL_WAIVER_PATH
    )
    isolation = renewal["semantic_isolation"]
    assert exception._semantic_isolation_python_projection(
        pipeline,
        path="app/services/pipeline.py",
    ) == isolation["shared_python_projection_sha256"]["app/services/pipeline.py"]
    assert exception._semantic_isolation_frontend_table_block(frontend)[0] == (
        isolation["shared_frontend_projection_sha256"][
            "frontend/app/clearleaf-workspace.tsx"
        ]
    )
    changed_pipeline = pipeline.replace(
        b'if settings.layout_running_regions_enabled:',
        b'if not settings.layout_running_regions_enabled:',
        1,
    )
    assert changed_pipeline != pipeline
    assert exception._semantic_isolation_python_projection(
        changed_pipeline,
        path="app/services/pipeline.py",
    ) != isolation["shared_python_projection_sha256"]["app/services/pipeline.py"]


def test_semantic_isolation_pins_exact_final_p04_us01_table_candidate() -> None:
    renewal = _load_json(
        PROJECT_ROOT / exception.SEMANTIC_ISOLATION_PHASE04_RENEWAL_WAIVER_PATH
    )
    isolation = renewal["semantic_isolation"]
    assert renewal["schema_version"] == "1.1"
    assert isolation["schema_id"] == (
        "p03-us08-phase04-table-semantic-isolation-v2"
    )
    expected_identities = {
        "app/models.py": dict(
            exception._SEMANTIC_ISOLATION_FINAL_US01_MODELS_IDENTITY
        ),
        "app/services/pipeline.py": dict(
            exception.EXPECTED_CURRENT_FROZEN_P04_US01_PIPELINE_IDENTITY
        ),
        "app/services/table_semantics.py": dict(
            exception.EXPECTED_CURRENT_FROZEN_P04_US01_TABLE_SEMANTICS_IDENTITY
        ),
    }
    assert isolation["final_p04_us01_code_identities"] == expected_identities
    assert isolation["table_semantics_max_ast_nodes"] == 40_000

    for path, identity in expected_identities.items():
        raw = (PROJECT_ROOT / path).read_bytes()
        tree = ast.parse(raw.decode("utf-8"))
        assert identity == {
            "ast_sha256": exception._ast_digest(tree),
            "path": path,
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
        }

    table_raw = (PROJECT_ROOT / "app/services/table_semantics.py").read_bytes()
    table_tree = ast.parse(table_raw.decode("utf-8"))
    assert sum(1 for _ in ast.walk(table_tree)) == 34_865
    assert exception._current_frozen_p04_us01_table_semantics_nodes(
        table_tree
    ) == frozenset(
        exception.EXPECTED_CURRENT_FROZEN_P04_US01_TABLE_SEMANTICS_AST_SHA256
    )
    assert "_orchestrate_docling_table_projection" in (
        exception.EXPECTED_SECOND_ADDITIVE_P04_US01_TABLE_SEMANTICS_ROOTS
    )

    freeze = isolation["p04_us01_administrative_freeze"]
    observed_gate_inputs = (
        exception._semantic_isolation_collect_p04_us01_administrative_freeze(
            PROJECT_ROOT
        )
    )
    assert freeze["excluded_administrative_paths"] == [
        str(exception.SEMANTIC_ISOLATION_GUARD_PATH),
        str(exception.SEMANTIC_ISOLATION_FOCUSED_TEST_PATH),
    ]
    assert freeze["gate_input_identities"] == observed_gate_inputs
    assert freeze["gate_input_count"] == 59 == len(observed_gate_inputs)
    assert freeze["gate_input_total_bytes"] == 4_292_724 == sum(
        identity["size_bytes"] for identity in observed_gate_inputs.values()
    )
    assert freeze["gate_input_manifest_sha256"] == (
        "fd49b22916ffa677ccaf3c50431e8ea896fee6facf848e7435c3c36d86c8d862"
    ) == metrics._sha256_json(observed_gate_inputs)


def test_semantic_isolation_owned_table_root_seal_is_one_exact_site() -> None:
    path = "app/services/table_semantics.py"
    source = (PROJECT_ROOT / path).read_bytes()
    tree = ast.parse(source.decode("utf-8"))
    assignments = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "_OWNED_CANONICAL_TABLE_ROOT_SEAL"
            for target in node.targets
        )
    ]
    assert len(assignments) == 1
    assert exception._ast_digest(assignments[0]) == (
        exception.EXPECTED_OWNED_TABLE_ROOT_SEAL_ASSIGNMENT_AST_SHA256
    )
    exception._semantic_isolation_validate_dedicated_python(source, path=path)

    changed_target = source.replace(
        b"_OWNED_CANONICAL_TABLE_ROOT_SEAL = object()",
        b"_OTHER_TABLE_ROOT_SEAL = object()",
        1,
    )
    assert changed_target != source
    with pytest.raises(readiness.ReadinessContractError, match="ownership seal"):
        exception._semantic_isolation_validate_dedicated_python(
            changed_target,
            path=path,
        )

    duplicate = source + b"\n_OWNED_CANONICAL_TABLE_ROOT_SEAL = object()\n"
    with pytest.raises(readiness.ReadinessContractError, match="ownership seal"):
        exception._semantic_isolation_validate_dedicated_python(
            duplicate,
            path=path,
        )


def test_semantic_isolation_record_is_pending_and_one_way() -> None:
    renewal = _load_json(
        PROJECT_ROOT / exception.SEMANTIC_ISOLATION_PHASE04_RENEWAL_WAIVER_PATH
    )

    assert renewal["status"] == (
        "requester_authorized_pending_independent_approval"
    )
    assert renewal["verification_state"] == {
        "state": "pending_final_code_and_test_identity",
        "independent_approval_required": True,
        "operative": False,
        "production_use_authorized": False,
        "phase05_authorized": False,
    }
    assert renewal["identity_dag"] == {
        "direction": (
            "prior evidence -> decision -> renewal JSON; preapproval US01 "
            "execution evidence -> P04-US01 final-code story gate; (renewal "
            "JSON + guard + focused tests + P04-US01 final-code story gate + "
            "focused gate execution) -> verification -> independent review "
            "artifacts -> terminal approval"
        ),
        "upstream_contains_downstream_digest": False,
        "terminal_independent_approval_present": False,
        "final_retained_metrics_evidence_is_downstream": True,
        "self_or_mutual_hash_authorized": False,
    }
    assert not {
        "guard_identity",
        "focused_test_identity",
        "verification_identity",
        "independent_approval_identity",
    } & set(renewal)

    decision = (
        PROJECT_ROOT / renewal["decision_identity"]["path"]
    ).read_text(encoding="utf-8")
    assert "REQUESTER AUTHORIZED; NOT OPERATIVE" in decision
    assert "independent approval pending" in decision
    assert "cannot be cited as operative custody" in " ".join(decision.split())


def test_semantic_isolation_renewal_rejects_numeric_boolean_substitution() -> None:
    renewal = _load_json(
        PROJECT_ROOT / exception.SEMANTIC_ISOLATION_PHASE04_RENEWAL_WAIVER_PATH
    )
    mutations = []
    verification_state = deepcopy(renewal["verification_state"])
    verification_state["operative"] = 0
    mutations.append((verification_state, renewal["verification_state"]))
    identity_dag = deepcopy(renewal["identity_dag"])
    identity_dag["upstream_contains_downstream_digest"] = 0
    mutations.append((identity_dag, renewal["identity_dag"]))
    activation = deepcopy(renewal["semantic_isolation"]["activation_policy"])
    activation["operative_between_freezes"] = 0
    mutations.append(
        (activation, renewal["semantic_isolation"]["activation_policy"])
    )
    scanner = deepcopy(renewal["semantic_isolation"]["scanner_assurance"])
    scanner["sound_sandbox_claimed"] = 0
    mutations.append(
        (scanner, renewal["semantic_isolation"]["scanner_assurance"])
    )
    flags = deepcopy(renewal["semantic_isolation"]["phase04_flags"])
    flags[next(iter(flags))] = 0
    mutations.append((flags, renewal["semantic_isolation"]["phase04_flags"]))

    for mutated, expected in mutations:
        assert not exception._semantic_isolation_strict_equal(mutated, expected)


@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "command",
        "exit",
        "count",
        "output",
        "environment",
        "finding",
        "status",
        "date",
        "digest",
    ],
)
def test_semantic_isolation_focused_gate_binds_exact_execution(
    mutation: str | None,
) -> None:
    production_code = {
        "app/config.py": {
            "path": "app/config.py",
            "sha256": "1" * 64,
            "size_bytes": 10,
        }
    }
    dependency_custody = {
        "requirements.lock": {"sha256": "2" * 64, "size_bytes": 20}
    }
    status_owners = {
        "tracker/roadmap.md": {
            "path": "tracker/roadmap.md",
            "raw_sha256": "3" * 64,
            "size_bytes": 30,
        }
    }
    execution = _semantic_focused_gate_execution(
        production_code=production_code,
        dependency_custody=dependency_custody,
        status_owners=status_owners,
    )
    if mutation == "command":
        execution["commands"][1]["argv"][-1] = "forged.py"
    elif mutation == "exit":
        execution["commands"][1]["exit_code"] = 1
    elif mutation == "count":
        execution["commands"][1]["passed"] = 0
    elif mutation == "output":
        execution["commands"][1]["output_sha256"] = "not-a-digest"
    elif mutation == "environment":
        execution["environment"]["dependency_custody_sha256"] = "4" * 64
    elif mutation == "finding":
        execution["findings"]["major_findings"] = ["unresolved"]
    elif mutation == "status":
        execution["status"] = "PENDING"
    elif mutation == "date":
        execution["executed_on"] = "2026-08-04"
    elif mutation == "digest":
        execution["semantic_sha256"] = "4" * 64

    if mutation is None:
        exception._semantic_isolation_validate_focused_gate_execution(
            execution,
            expected_dependency_custody=dependency_custody,
            expected_production_code=production_code,
            expected_status_owners=status_owners,
            today=date(2026, 8, 5),
        )
    else:
        with pytest.raises(readiness.ReadinessContractError):
            exception._semantic_isolation_validate_focused_gate_execution(
                execution,
                expected_dependency_custody=dependency_custody,
                expected_production_code=production_code,
                expected_status_owners=status_owners,
                today=date(2026, 8, 5),
            )


@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "missing_category",
        "stale_artifact",
        "failed_result",
        "command_exit",
        "noop_tool",
        "missing_command_coverage",
        "all_skipped",
        "undocumented_skip",
        "skip_reason_mismatch",
        "undocumented_warning",
        "warning_reason_mismatch",
        "output_hash",
        "output_identity",
        "finding",
        "quality_count",
        "quality_case",
        "oracle_digest",
        "frontend_unit_floor",
        "frontend_responsive_floor",
        "latency",
        "quantile_order",
        "rss",
        "p03_exception_bound",
        "dependency",
        "environment",
        "gate_input_drift",
        "gate_input_manifest",
        "numeric_top_boolean",
        "numeric_environment_boolean",
        "numeric_p03_boolean",
        "numeric_rollback_boolean",
        "artifact_manifest",
        "empty_artifact",
        "noncanonical_artifact",
        "downstream_cycle_path",
        "oversize_artifact",
        "artifact_count_budget",
        "artifact_byte_budget",
        "allocation",
        "source_latency",
        "input_custody",
        "date",
        "digest",
    ],
)
def test_semantic_isolation_us01_story_gate_binds_final_code_results(
    tmp_path: Path,
    mutation: str | None,
) -> None:
    production_code = {
        "app/services/tables.py": {
            "path": "app/services/tables.py",
            "sha256": "1" * 64,
            "size_bytes": 10,
        }
    }
    dependency_custody = {
        "uv.lock": {"sha256": "2" * 64, "size_bytes": 20}
    }
    status_owners = {
        "tracker/phase-04-tables/stories/P04-US01.md": {
            "path": "tracker/phase-04-tables/stories/P04-US01.md",
            "raw_sha256": "3" * 64,
            "size_bytes": 30,
        }
    }
    gate_input_path = "tests/fixtures/phase_04/tables/oracle.py"
    gate_input_raw = b"US01 oracle input\n"
    gate_input_target = tmp_path / gate_input_path
    gate_input_target.parent.mkdir(parents=True, exist_ok=True)
    gate_input_target.write_bytes(gate_input_raw)
    us01_gate_inputs = {
        gate_input_path: exception._semantic_isolation_file_identity(
            gate_input_path,
            gate_input_raw,
        )
    }
    gate = _semantic_us01_story_gate(
        root=tmp_path,
        production_code=production_code,
        dependency_custody=dependency_custody,
        status_owners=status_owners,
        us01_gate_inputs=us01_gate_inputs,
    )
    if mutation == "missing_category":
        gate["gates"].pop("production_security")
    elif mutation == "stale_artifact":
        identity = gate["gates"]["production_security"][
            "artifact_identities"
        ][0]
        (tmp_path / identity["path"]).write_bytes(b"changed")
    elif mutation == "failed_result":
        gate["gates"]["production_security"]["result"] = "FAIL"
    elif mutation == "command_exit":
        gate["gates"]["product_correctness_quality"]["commands"][0][
            "exit_code"
        ] = 1
    elif mutation == "noop_tool":
        gate["gates"]["product_correctness_quality"]["commands"][0][
            "argv"
        ] = ["true"]
    elif mutation == "missing_command_coverage":
        gate["gates"]["paired_latency_rss"]["commands"][0][
            "coverage_tags"
        ].pop()
    elif mutation == "all_skipped":
        command = gate["gates"]["product_correctness_quality"]["commands"][0]
        command["passed"] = 0
        command["skipped"] = 1
        command["documented_skips"] = [
            {"count": 1, "reason": "synthetic skip"}
        ]
    elif mutation == "undocumented_skip":
        gate["gates"]["product_correctness_quality"]["commands"][0][
            "skipped"
        ] = 1
    elif mutation == "skip_reason_mismatch":
        command = gate["gates"]["product_correctness_quality"]["commands"][0]
        command["skipped"] = 2
        command["documented_skips"] = [
            {"count": 1, "reason": "only one documented skip"}
        ]
    elif mutation == "undocumented_warning":
        gate["gates"]["product_correctness_quality"]["commands"][0][
            "warnings"
        ] = 1
    elif mutation == "warning_reason_mismatch":
        command = gate["gates"]["product_correctness_quality"]["commands"][0]
        command["warnings"] = 2
        command["documented_warnings"] = [
            {"count": 1, "reason": "only one documented warning"}
        ]
    elif mutation == "output_hash":
        gate["gates"]["product_correctness_quality"]["commands"][0][
            "output_sha256"
        ] = "4" * 64
    elif mutation == "output_identity":
        gate["gates"]["product_correctness_quality"]["commands"][0][
            "output_artifact_identity"
        ]["raw_sha256"] = "4" * 64
    elif mutation == "finding":
        gate["gates"]["production_security"]["findings"][
            "security_findings"
        ] = ["unresolved"]
    elif mutation == "quality_count":
        gate["gates"]["product_correctness_quality"]["results"][
            "reviewed_real_document_count"
        ] = 1
    elif mutation == "quality_case":
        gate["gates"]["product_correctness_quality"]["results"][
            "reviewed_real_document_ids"
        ].pop()
    elif mutation == "oracle_digest":
        gate["gates"]["product_correctness_quality"]["results"][
            "oracle_semantic_sha256"
        ] = "4" * 64
    elif mutation == "frontend_unit_floor":
        gate["gates"]["frontend_compatibility"]["results"][
            "unit_test_count"
        ] = 104
    elif mutation == "frontend_responsive_floor":
        gate["gates"]["frontend_compatibility"]["results"][
            "responsive_check_count"
        ] = 21
    elif mutation == "latency":
        gate["gates"]["paired_latency_rss"]["results"]["case_results"][
            "ny-timetable"
        ]["phase04_table_stage_p95_overhead_ratio"] = 0.11
    elif mutation == "quantile_order":
        gate["gates"]["paired_latency_rss"]["results"]["case_results"][
            "ny-timetable"
        ]["phase04_table_stage_p50_overhead_ratio"] = 0.03
    elif mutation == "rss":
        gate["gates"]["paired_latency_rss"]["results"]["case_results"][
            "finance-10k"
        ]["phase04_peak_rss_delta_bytes"] = 67_108_865
    elif mutation == "p03_exception_bound":
        gate["gates"]["paired_latency_rss"]["results"][
            "p03_attempt48_exception"
        ]["maximum_candidate_specific_bound"] = 0.10
    elif mutation == "dependency":
        gate["gates"]["dependency_custody"]["results"][
            "dependency_custody_sha256"
        ] = "4" * 64
    elif mutation == "environment":
        gate["environment"]["production_code_manifest_sha256"] = "4" * 64
    elif mutation == "gate_input_drift":
        gate_input_target.write_bytes(b"mutated after gate\n")
    elif mutation == "gate_input_manifest":
        gate["environment"]["us01_gate_input_manifest_sha256"] = "4" * 64
    elif mutation == "numeric_top_boolean":
        gate["production_use_authorized"] = 0
    elif mutation == "numeric_environment_boolean":
        gate["environment"]["phase04_flags"] = {
            name: 0
            for name in exception.EXPECTED_HARDENED_PHASE04_SETTING_ORDER
        }
    elif mutation == "numeric_p03_boolean":
        gate["gates"]["paired_latency_rss"]["results"][
            "p03_attempt48_exception"
        ]["canonical_strict_final_artifact_present"] = 0
        gate["gates"]["paired_latency_rss"]["results"][
            "p03_regression_gates"
        ] = {
            name: 1
            for name in gate["gates"]["paired_latency_rss"]["results"][
                "p03_regression_gates"
            ]
        }
    elif mutation == "numeric_rollback_boolean":
        gate["gates"]["rollback_default_off"]["results"]["phase04_flags"] = {
            name: 0
            for name in exception.EXPECTED_HARDENED_PHASE04_SETTING_ORDER
        }
    elif mutation == "artifact_manifest":
        gate["artifact_manifest_sha256"] = "4" * 64
    elif mutation == "empty_artifact":
        gate["gates"]["product_correctness_quality"][
            "artifact_identities"
        ][0]["size_bytes"] = 0
    elif mutation == "noncanonical_artifact":
        gate["gates"]["product_correctness_quality"][
            "artifact_identities"
        ][0]["path"] = (
            f"{exception.SEMANTIC_ISOLATION_PHASE04_US01_PREAPPROVAL_EVIDENCE_ROOT}/"
            "./product-correctness-quality.json"
        )
    elif mutation == "downstream_cycle_path":
        gate["gates"]["product_correctness_quality"][
            "artifact_identities"
        ][0]["path"] = (
            "tracker/phase-04-tables/evidence/P04-US01-final-metrics.json"
        )
    elif mutation == "oversize_artifact":
        gate["gates"]["product_correctness_quality"][
            "artifact_identities"
        ][0]["size_bytes"] = (
            exception._SEMANTIC_ISOLATION_US01_MAXIMUM_ARTIFACT_BYTES + 1
        )
    elif mutation in {"artifact_count_budget", "artifact_byte_budget"}:
        extra_count = 57 if mutation == "artifact_count_budget" else 9
        categories = exception._SEMANTIC_ISOLATION_US01_GATE_CATEGORIES
        for index in range(extra_count):
            category = categories[index % len(categories)]
            gate["gates"][category]["artifact_identities"].append(
                {
                    "path": (
                        f"{exception.SEMANTIC_ISOLATION_PHASE04_US01_PREAPPROVAL_EVIDENCE_ROOT}/"
                        f"extra-{index}.log"
                    ),
                    "raw_sha256": hashlib.sha256(
                        str(index).encode("ascii")
                    ).hexdigest(),
                    "size_bytes": 1,
                }
            )
        if mutation == "artifact_byte_budget":
            for category in categories:
                for identity in gate["gates"][category][
                    "artifact_identities"
                ]:
                    identity["size_bytes"] = (
                        exception._SEMANTIC_ISOLATION_US01_MAXIMUM_ARTIFACT_BYTES
                    )
    elif mutation == "allocation":
        gate["gates"]["resource_timeout_output"]["results"][
            "allocation_passed"
        ] = False
    elif mutation == "source_latency":
        gate["gates"]["paired_latency_rss"]["results"]["p03_regression_gates"][
            "source_extraction_latency_regression_passed"
        ] = False
    elif mutation == "input_custody":
        gate["gates"]["dependency_custody"]["results"][
            "input_and_fixture_custody_passed"
        ] = False
    elif mutation == "date":
        gate["generated_on"] = "2026-08-04"
    elif mutation == "digest":
        gate["semantic_sha256"] = "4" * 64
    if mutation in {
        "empty_artifact",
        "noncanonical_artifact",
        "downstream_cycle_path",
        "oversize_artifact",
        "artifact_count_budget",
        "artifact_byte_budget",
    }:
        gate["artifact_manifest_sha256"] = metrics._sha256_json(
            {
                category: gate["gates"][category]["artifact_identities"]
                for category in exception._SEMANTIC_ISOLATION_US01_GATE_CATEGORIES
            }
        )
    if mutation not in {
        None,
        "stale_artifact",
        "gate_input_drift",
        "digest",
    }:
        gate["semantic_sha256"] = exception.waiver_semantic_sha256(gate)

    if mutation is None:
        tracks = exception._semantic_isolation_validate_us01_story_gate(
            tmp_path,
            gate,
            expected_dependency_custody=dependency_custody,
            expected_production_code=production_code,
            expected_status_owners=status_owners,
            expected_us01_gate_inputs=us01_gate_inputs,
            today=date(2026, 8, 5),
        )
        assert len(tracks) == (
            len(exception._SEMANTIC_ISOLATION_US01_GATE_CATEGORIES)
            + len(us01_gate_inputs)
        )
    else:
        with pytest.raises(readiness.ReadinessContractError):
            exception._semantic_isolation_validate_us01_story_gate(
                tmp_path,
                gate,
                expected_dependency_custody=dependency_custody,
                expected_production_code=production_code,
                expected_status_owners=status_owners,
                expected_us01_gate_inputs=us01_gate_inputs,
                today=date(2026, 8, 5),
            )


def test_us01_gate_input_discovery_includes_nested_fixtures_and_policy(
    tmp_path: Path,
) -> None:
    required = {
        "tests/fixtures/phase_04/tables/direct.json": b"direct",
        "tests/fixtures/phase_04/tables/adversarial/nested.json": b"nested",
        "tests/fixtures/phase_04/tables/__pycache__/ignored.pyc": b"cache",
        "tracker/phase-04-tables/decisions/nested/policy.md": b"policy",
        "tracker/phase-04-tables/README.md": b"readme",
        "tracker/phase-04-tables/backlog.md": b"backlog",
        "tracker/phase-04-tables/metrics.md": b"metrics",
        "tracker/phase-04-tables/phase-regression.md": b"regression",
        "tracker/phase-04-tables/stories/P04-US01.md": b"story",
    }
    for path, raw in required.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)

    discovered = (
        exception._semantic_isolation_discover_additional_us01_gate_inputs(
            tmp_path
        )
    )

    assert "tests/fixtures/phase_04/tables/direct.json" in discovered
    assert (
        "tests/fixtures/phase_04/tables/adversarial/nested.json" in discovered
    )
    assert "tracker/phase-04-tables/decisions/nested/policy.md" in discovered
    assert not any("__pycache__" in path for path in discovered)


@pytest.mark.parametrize("role", ["production_security", "metrics_custody"])
@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "upstream",
        "commands",
        "environment",
        "story_gate_identity",
        "story_gate_results",
        "gate_inputs",
        "finding",
        "identity",
        "date",
        "chronology",
        "digest",
    ],
)
def test_semantic_isolation_review_artifacts_bind_execution_and_findings(
    tmp_path: Path,
    role: str,
    mutation: str | None,
) -> None:
    focused_gate = _semantic_focused_gate_execution(
        production_code={},
        dependency_custody={},
        status_owners={},
    )
    us01_story_gate = _semantic_us01_story_gate(
        root=tmp_path,
        production_code={},
        dependency_custody={},
        status_owners={},
        us01_gate_inputs={
            "tests/fixtures/phase_04/tables/oracle.py": {
                "path": "tests/fixtures/phase_04/tables/oracle.py",
                "raw_sha256": "9" * 64,
                "size_bytes": 1,
            }
        },
    )
    us01_story_gate_identity = _semantic_us01_story_gate_identity(
        us01_story_gate
    )
    upstream = _semantic_terminal_upstream()
    upstream.pop("production_security_review")
    upstream.pop("metrics_custody_review")
    upstream["p04_us01_story_gate"] = deepcopy(us01_story_gate_identity)
    review = _semantic_review_artifact(
        role=role,
        upstream=upstream,
        focused_gate=focused_gate,
        us01_story_gate=us01_story_gate,
        us01_story_gate_identity=us01_story_gate_identity,
    )
    if mutation == "upstream":
        review["upstream_identities"] = {"forged": True}
    elif mutation == "commands":
        review["focused_gate_commands_reviewed"][1]["passed"] += 1
    elif mutation == "environment":
        review["focused_gate_environment_reviewed"][
            "dependency_custody_sha256"
        ] = "4" * 64
    elif mutation == "story_gate_identity":
        review["us01_story_gate_identity_reviewed"]["raw_sha256"] = "4" * 64
    elif mutation == "story_gate_results":
        review["us01_story_gate_results_reviewed"]["paired_latency_rss"][
            "results"
        ]["phase04_table_stage_latency_passed"] = False
    elif mutation == "gate_inputs":
        review["us01_gate_input_identities_reviewed"][
            "tests/fixtures/phase_04/tables/oracle.py"
        ]["raw_sha256"] = "4" * 64
    elif mutation == "finding":
        review["findings"]["security_findings"] = ["unresolved"]
    elif mutation == "identity":
        review["reviewer_id"] = "x"
    elif mutation == "date":
        review["reviewed_on"] = "2026-08-04"
    elif mutation == "chronology":
        us01_story_gate["generated_on"] = "2026-08-06"
    elif mutation == "digest":
        review["semantic_sha256"] = "4" * 64

    if mutation is None:
        exception._semantic_isolation_validate_review_artifact(
            review,
            expected_role=role,
            expected_upstream=upstream,
            focused_gate=focused_gate,
            us01_story_gate=us01_story_gate,
            us01_story_gate_identity=us01_story_gate_identity,
            today=date(2026, 8, 5),
        )
    else:
        with pytest.raises(readiness.ReadinessContractError):
            exception._semantic_isolation_validate_review_artifact(
                review,
                expected_role=role,
                expected_upstream=upstream,
                focused_gate=focused_gate,
                us01_story_gate=us01_story_gate,
                us01_story_gate_identity=us01_story_gate_identity,
                today=date(2026, 8, 5),
            )


def test_semantic_isolation_terminal_verification_pins_exact_freeze() -> None:
    upstream = _semantic_verification_upstream()
    production_code = {
        "app/config.py": {
            "path": "app/config.py",
            "sha256": "1" * 64,
            "size_bytes": 10,
        },
        "frontend/lib/table-semantics.ts": {
            "path": "frontend/lib/table-semantics.ts",
            "sha256": "2" * 64,
            "size_bytes": 20,
        },
    }
    dependency_custody = {
        "requirements.lock": {"sha256": "3" * 64, "size_bytes": 30}
    }
    status_owners = {
        "tracker/roadmap.md": {
            "path": "tracker/roadmap.md",
            "raw_sha256": "5" * 64,
            "size_bytes": 50,
        }
    }
    verification = _semantic_terminal_verification(
        upstream=upstream,
        production_code=production_code,
        dependency_custody=dependency_custody,
        status_owners=status_owners,
        us01_gate_inputs=_semantic_gate_inputs(),
    )

    exception._semantic_isolation_validate_verification_state(
        verification,
        expected_upstream=upstream,
        expected_production_code=production_code,
        expected_dependency_custody=dependency_custody,
        expected_protected_manifest_sha256="d" * 64,
        expected_protected_path_count=83,
        expected_status_owners=status_owners,
        expected_us01_gate_inputs=_semantic_gate_inputs(),
    )


def test_mutated_bytes_fail_terminal_freeze_regardless_of_scanner_outcome() -> None:
    upstream = _semantic_verification_upstream()
    frozen_code = {
        "app/services/pipeline.py": {
            "path": "app/services/pipeline.py",
            "sha256": "1" * 64,
            "size_bytes": 10,
        }
    }
    live_mutated_code = deepcopy(frozen_code)
    live_mutated_code["app/services/pipeline.py"]["sha256"] = "2" * 64
    verification = _semantic_terminal_verification(
        upstream=upstream,
        production_code=frozen_code,
        dependency_custody={},
        status_owners={},
        us01_gate_inputs=_semantic_gate_inputs(),
    )

    assert "scanner_result" not in verification
    with pytest.raises(
        readiness.ReadinessContractError,
        match="production identity differs",
    ):
        exception._semantic_isolation_validate_verification_state(
            verification,
            expected_upstream=upstream,
            expected_production_code=live_mutated_code,
            expected_dependency_custody={},
            expected_protected_manifest_sha256="d" * 64,
            expected_protected_path_count=83,
            expected_status_owners={},
            expected_us01_gate_inputs=_semantic_gate_inputs(),
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("pending", "state differs"),
        ("forged_upstream", "upstream differs"),
        ("stale_production", "production identity differs"),
        ("stale_production_manifest", "production manifest differs"),
        ("stale_dependency", "dependency custody differs"),
        ("stale_dependency_manifest", "dependency custody differs"),
        ("stale_protected_manifest", "protected manifest differs"),
        ("stale_protected_count", "protected manifest differs"),
        ("stale_status_owner", "status-owner identity differs"),
        ("stale_status_owner_manifest", "status-owner identity differs"),
        ("stale_gate_input", "gate-input identity differs"),
        ("stale_gate_input_manifest", "gate-input identity differs"),
        ("numeric_state_boolean", "state differs"),
        ("numeric_check_boolean", "checks differ"),
        ("waived_gate", "checks differ"),
        ("stale_digest", "digest differs"),
    ],
)
def test_semantic_isolation_terminal_verification_rejects_stale_freeze(
    mutation: str,
    message: str,
) -> None:
    upstream = _semantic_verification_upstream()
    production_code = {
        "app/config.py": {
            "path": "app/config.py",
            "sha256": "1" * 64,
            "size_bytes": 10,
        }
    }
    dependency_custody = {
        "requirements.lock": {"sha256": "3" * 64, "size_bytes": 30}
    }
    status_owners = {
        "tracker/roadmap.md": {
            "path": "tracker/roadmap.md",
            "raw_sha256": "5" * 64,
            "size_bytes": 50,
        }
    }
    verification = _semantic_terminal_verification(
        upstream=upstream,
        production_code=production_code,
        dependency_custody=dependency_custody,
        status_owners=status_owners,
        us01_gate_inputs=_semantic_gate_inputs(),
    )
    if mutation == "pending":
        verification["status"] = "PENDING"
    elif mutation == "forged_upstream":
        verification["upstream_identities"] = {"forged": True}
    elif mutation == "stale_production":
        verification["production_code_identities"]["app/config.py"][
            "sha256"
        ] = "4" * 64
    elif mutation == "stale_production_manifest":
        verification["production_code_manifest_sha256"] = "4" * 64
    elif mutation == "stale_dependency":
        verification["dependency_custody"]["requirements.lock"][
            "sha256"
        ] = "4" * 64
    elif mutation == "stale_dependency_manifest":
        verification["dependency_custody_sha256"] = "4" * 64
    elif mutation == "stale_protected_manifest":
        verification["protected_code_manifest_sha256"] = "4" * 64
    elif mutation == "stale_protected_count":
        verification["protected_code_path_count"] = 84
    elif mutation == "stale_status_owner":
        verification["status_owner_identities"]["tracker/roadmap.md"][
            "raw_sha256"
        ] = "4" * 64
    elif mutation == "stale_status_owner_manifest":
        verification["status_owner_manifest_sha256"] = "4" * 64
    elif mutation == "stale_gate_input":
        verification["us01_gate_input_identities"][
            "tests/fixtures/phase_04/tables/oracle.py"
        ]["raw_sha256"] = "4" * 64
    elif mutation == "stale_gate_input_manifest":
        verification["us01_gate_input_manifest_sha256"] = "4" * 64
    elif mutation == "numeric_state_boolean":
        verification["production_use_authorized"] = 0
    elif mutation == "numeric_check_boolean":
        verification["checks"]["all_nonwaived_gates_passed"] = 1
    elif mutation == "waived_gate":
        verification["checks"]["all_nonwaived_gates_passed"] = False
    elif mutation == "stale_digest":
        verification["semantic_sha256"] = "4" * 64

    with pytest.raises(readiness.ReadinessContractError, match=message):
        exception._semantic_isolation_validate_verification_state(
            verification,
            expected_upstream=upstream,
            expected_production_code=production_code,
            expected_dependency_custody=dependency_custody,
            expected_protected_manifest_sha256="d" * 64,
            expected_protected_path_count=83,
            expected_status_owners=status_owners,
            expected_us01_gate_inputs=_semantic_gate_inputs(),
        )


def test_semantic_isolation_terminal_records_fail_closed_between_freezes() -> None:
    renewal = _load_json(
        PROJECT_ROOT / exception.SEMANTIC_ISOLATION_PHASE04_RENEWAL_WAIVER_PATH
    )
    policy = renewal["semantic_isolation"]["activation_policy"]
    assert policy["reissue_after_each_story_or_code_freeze"] is True
    assert policy["operative_between_freezes"] is False
    with pytest.raises(readiness.ReadinessContractError):
        exception._semantic_isolation_validate_focused_gate_execution(
            {},
            expected_dependency_custody={},
            expected_production_code={},
            expected_status_owners={},
            today=date(2026, 8, 5),
        )


def test_semantic_isolation_all_absent_terminal_leaves_are_explicitly_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Path, date | None]] = []

    def validate_pending(
        repository_root: Path,
        *,
        today: date | None = None,
    ) -> dict[str, Any]:
        calls.append((repository_root, today))
        raise readiness.ReadinessContractError(
            SEMANTIC_ISOLATION_PENDING_TERMINAL_ERROR
        )

    monkeypatch.setattr(
        exception,
        "validate_performance_exception",
        validate_pending,
    )

    assert (
        _validate_complete_terminal_chain_or_assert_pending(
            tmp_path,
            today=date(2026, 8, 5),
        )
        is None
    )
    assert calls == [(tmp_path, date(2026, 8, 5))]


@pytest.mark.parametrize(
    "present_indexes",
    ((0,), tuple(range(len(SEMANTIC_ISOLATION_TERMINAL_LEAF_PATHS) - 1))),
    ids=("first-leaf-only", "all-but-approval"),
)
def test_semantic_isolation_partial_terminal_set_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    present_indexes: tuple[int, ...],
) -> None:
    for index in present_indexes:
        path = tmp_path / SEMANTIC_ISOLATION_TERMINAL_LEAF_PATHS[index]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"{}\n")

    validator_called = False

    def unexpected_validation(
        repository_root: Path,
        *,
        today: date | None = None,
    ) -> dict[str, Any]:
        nonlocal validator_called
        del repository_root, today
        validator_called = True
        return {}

    monkeypatch.setattr(
        exception,
        "validate_performance_exception",
        unexpected_validation,
    )

    with pytest.raises(AssertionError, match="terminal chain is partial"):
        _validate_complete_terminal_chain_or_assert_pending(
            tmp_path,
            today=date(2026, 8, 5),
        )
    assert validator_called is False


def test_semantic_isolation_complete_terminal_set_runs_full_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for relative_path in SEMANTIC_ISOLATION_TERMINAL_LEAF_PATHS:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"not strict JSON\n")

    calls: list[tuple[Path, date | None]] = []

    def validate_malformed(
        repository_root: Path,
        *,
        today: date | None = None,
    ) -> dict[str, Any]:
        calls.append((repository_root, today))
        raise readiness.ReadinessContractError("malformed terminal leaf")

    monkeypatch.setattr(
        exception,
        "validate_performance_exception",
        validate_malformed,
    )

    with pytest.raises(
        readiness.ReadinessContractError,
        match="malformed terminal leaf",
    ):
        _validate_complete_terminal_chain_or_assert_pending(
            tmp_path,
            today=date(2026, 8, 5),
        )
    assert calls == [(tmp_path, date(2026, 8, 5))]


def test_public_validation_requires_terminal_freeze_before_final_custody_check(
) -> None:
    guard_source = (
        PROJECT_ROOT
        / "tests/fixtures/phase_03/running_regions/performance_exception.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(guard_source)
    validator = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "validate_performance_exception"
    )
    calls: dict[str, list[int]] = {}
    for call in (node for node in ast.walk(validator) if isinstance(node, ast.Call)):
        if isinstance(call.func, ast.Name):
            name = call.func.id
        elif isinstance(call.func, ast.Attribute):
            name = call.func.attr
        else:
            continue
        calls.setdefault(name, []).append(call.lineno)

    renewal_line = calls["_validate_semantic_isolation_phase04_renewal"][0]
    terminal_line = calls["_validate_semantic_isolation_terminal_approval"][0]
    final_custody_line = max(calls["_collect_repository_custody"])
    assert renewal_line < terminal_line < final_custody_line


def test_terminal_chain_binds_us01_and_focused_before_verification() -> None:
    guard_source = (
        PROJECT_ROOT
        / "tests/fixtures/phase_03/running_regions/performance_exception.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(guard_source)
    validator = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_validate_semantic_isolation_terminal_approval"
    )
    calls: dict[str, list[int]] = {}
    for call in (node for node in ast.walk(validator) if isinstance(node, ast.Call)):
        if isinstance(call.func, ast.Name):
            calls.setdefault(call.func.id, []).append(call.lineno)
    verification_line = calls[
        "_semantic_isolation_validate_verification_state"
    ][0]
    assert (
        calls["_semantic_isolation_validate_us01_story_gate"][0]
        < verification_line
    )
    assert (
        calls["_semantic_isolation_validate_focused_gate_execution"][0]
        < verification_line
    )
    assert (
        verification_line
        < calls["_semantic_isolation_validate_review_artifact"][0]
        < calls["_semantic_isolation_validate_terminal_approval_state"][0]
    )


def test_semantic_isolation_terminal_approval_is_required() -> None:
    renewal = _load_json(
        PROJECT_ROOT / exception.SEMANTIC_ISOLATION_PHASE04_RENEWAL_WAIVER_PATH
    )

    with pytest.raises(readiness.ReadinessContractError, match="approval is absent"):
        exception._semantic_isolation_validate_terminal_approval_state(
            None,
            expected_upstream=_semantic_terminal_upstream(),
            expected_review_identities=_semantic_terminal_review_identities(
                _semantic_terminal_upstream()
            ),
            expected_reviewers=_semantic_terminal_reviewers(),
            expected_review_dates=_semantic_terminal_review_dates(),
            renewal=renewal,
            today=date(2026, 8, 5),
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "pending",
        "preauthorization_date",
        "pre_review_date",
        "numeric_boolean",
        "forged",
        "stale_guard",
        "stale_focused_test",
        "stale_p04_us01_story_gate",
        "stale_focused_gate_execution",
        "stale_verification",
        "stale_production_security_review",
        "stale_metrics_custody_review",
        "stale_review_artifact",
        "invalid_role_type",
        "non_independent",
        "self_review",
        "duplicate_reviewer",
        "reviewer_mismatch",
    ],
)
def test_semantic_isolation_terminal_approval_rejects_nonterminal_state(
    mutation: str,
) -> None:
    renewal = _load_json(
        PROJECT_ROOT / exception.SEMANTIC_ISOLATION_PHASE04_RENEWAL_WAIVER_PATH
    )
    upstream = _semantic_terminal_upstream()
    approval = _semantic_terminal_approval(renewal, upstream)
    if mutation == "pending":
        approval["status"] = "PENDING"
    elif mutation == "preauthorization_date":
        approval["approved_on"] = "2026-08-04"
    elif mutation == "pre_review_date":
        pass
    elif mutation == "numeric_boolean":
        approval["production_use_authorized"] = 0
    elif mutation == "forged":
        approval["upstream_identities"] = {"forged": True}
    elif mutation == "stale_review_artifact":
        approval["reviews"][0]["review_artifact_identity"][
            "raw_sha256"
        ] = "d" * 64
    elif mutation == "invalid_role_type":
        approval["reviews"][0]["review_role"] = ["production_security"]
    elif mutation.startswith("stale_"):
        field = mutation.removeprefix("stale_")
        approval["upstream_identities"][field]["raw_sha256"] = "d" * 64
    elif mutation == "non_independent":
        approval["reviews"][0]["independent"] = False
    elif mutation == "self_review":
        approval["reviews"][0]["self_review"] = True
    elif mutation == "duplicate_reviewer":
        approval["reviews"][1]["reviewer_id"] = approval["reviews"][0][
            "reviewer_id"
        ]
    elif mutation == "reviewer_mismatch":
        approval["reviews"][0]["reviewer_id"] = "different-independent-reviewer"

    with pytest.raises(readiness.ReadinessContractError):
        exception._semantic_isolation_validate_terminal_approval_state(
            approval,
            expected_upstream=upstream,
            expected_review_identities=_semantic_terminal_review_identities(
                upstream
            ),
            expected_reviewers=_semantic_terminal_reviewers(),
            expected_review_dates=(
                {
                    "production_security": "2026-08-06",
                    "metrics_custody": "2026-08-06",
                }
                if mutation == "pre_review_date"
                else _semantic_terminal_review_dates()
            ),
            renewal=renewal,
            today=date(2026, 8, 5),
        )


def test_semantic_isolation_terminal_approval_has_no_self_digest() -> None:
    renewal = _load_json(
        PROJECT_ROOT / exception.SEMANTIC_ISOLATION_PHASE04_RENEWAL_WAIVER_PATH
    )
    upstream = _semantic_terminal_upstream()
    approval = _semantic_terminal_approval(renewal, upstream)

    assert "semantic_sha256" not in approval
    assert "approval_identity" not in approval
    exception._semantic_isolation_validate_terminal_approval_state(
        approval,
        expected_upstream=upstream,
        expected_review_identities=_semantic_terminal_review_identities(
            upstream
        ),
        expected_reviewers=_semantic_terminal_reviewers(),
        expected_review_dates=_semantic_terminal_review_dates(),
        renewal=renewal,
        today=date(2026, 8, 5),
    )


def test_terminal_approval_rejects_same_actual_reviewer_with_fabricated_summaries(
) -> None:
    renewal = _load_json(
        PROJECT_ROOT / exception.SEMANTIC_ISOLATION_PHASE04_RENEWAL_WAIVER_PATH
    )
    upstream = _semantic_terminal_upstream()
    approval = _semantic_terminal_approval(renewal, upstream)

    with pytest.raises(readiness.ReadinessContractError):
        exception._semantic_isolation_validate_terminal_approval_state(
            approval,
            expected_upstream=upstream,
            expected_review_identities=_semantic_terminal_review_identities(
                upstream
            ),
            expected_reviewers={
                "production_security": "same-actual-reviewer",
                "metrics_custody": "same-actual-reviewer",
            },
            expected_review_dates=_semantic_terminal_review_dates(),
            renewal=renewal,
            today=date(2026, 8, 5),
        )


def test_semantic_isolation_preserves_exact_exception_and_gate_facts() -> None:
    renewal = _load_json(
        PROJECT_ROOT / exception.SEMANTIC_ISOLATION_PHASE04_RENEWAL_WAIVER_PATH
    )
    hardened = _load_json(PROJECT_ROOT / exception.HARDENED_PHASE04_RENEWAL_WAIVER_PATH)
    original = _waiver()

    for field in (
        "exception_scope",
        "failed_history",
        "hosted_usage",
        "not_waived",
        "operational_constraints",
        "deferred_work",
    ):
        assert renewal[field] == hardened[field] == original[field]
    assert renewal["exception_scope"] == {
        "candidate_specific": True,
        "maximum_overrun_fraction": 0.05,
        "metric": "latency_p95_seconds",
        "observed_seconds": 0.05094675,
        "overrun_fraction": 0.018935,
        "overrun_seconds": 0.00094675,
        "stage": "running_region_projection",
        "strict_ceiling_seconds": 0.05,
        "target_id": "ny-timetable",
    }
    assert renewal["failed_history"] == {
        "artifact_count": 55,
        "first_path": (
            "tracker/phase-03-layout/evidence/"
            "P03-US08-running-region-metrics-attempt-01-failed.json"
        ),
        "last_path": (
            "tracker/phase-03-layout/evidence/"
            "P03-US08-running-region-metrics-attempt-55-failed.json"
        ),
        "manifest_sha256": (
            "bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff"
        ),
    }
    assert renewal["not_waived"] == [
        "allocation",
        "api_schema_compatibility",
        "code_dependency_input_and_fixture_custody",
        "correctness_and_quality",
        "deadlines_and_resource_boundaries",
        "hosted_usage",
        "output_sizes",
        "paired_parser_latency",
        "peak_rss",
        "rollback",
        "security",
        "source_extraction_latency",
        "uber_projection_latency",
    ]
    assert renewal["operational_constraints"] == {
        "canonical_strict_final_artifact_present": False,
        "feature_flag": "PARSER_LAYOUT_RUNNING_REGIONS_ENABLED",
        "feature_flag_default": False,
        "rollback": (
            "disable the flag to skip US08 work and return the exact configured "
            "predecessor"
        ),
    }
    assert renewal["expiry"] == (
        exception.EXPECTED_SEMANTIC_ISOLATION_PHASE04_EXPIRY
    )
    assert (
        "relevant runtime dependency or lockfile custody change"
        in renewal["expiry"]["expires_before"]
    )
    assert renewal["expiry"]["review_due_on"] == "2026-09-02"


def test_semantic_isolation_expiry_is_inclusive_only_through_review_date() -> None:
    renewal = _load_json(
        PROJECT_ROOT / exception.SEMANTIC_ISOLATION_PHASE04_RENEWAL_WAIVER_PATH
    )

    exception._semantic_isolation_validate_expiry(
        renewal["expiry"],
        today=date(2026, 9, 2),
    )
    with pytest.raises(readiness.ReadinessContractError, match="expired"):
        exception._semantic_isolation_validate_expiry(
            renewal["expiry"],
            today=date(2026, 9, 3),
        )


def test_semantic_isolation_scope_is_closed_to_phase04_tables() -> None:
    renewal = _load_json(
        PROJECT_ROOT / exception.SEMANTIC_ISOLATION_PHASE04_RENEWAL_WAIVER_PATH
    )
    scope = renewal["closed_phase04_scope"]

    assert scope["phase04_only"] is True
    assert scope["phase05_authorized"] is False
    assert scope["stories_in_dependency_order"] == [
        "P04-US01",
        "P04-US02",
        "P04-US04",
        "P04-US03",
    ]
    assert scope["shared_python_paths"] == [
        "app/models.py",
        "app/services/ir.py",
        "app/services/pipeline.py",
        "app/services/presentation.py",
        "app/services/source_text_alignment.py",
        "app/services/text_reconciliation.py",
    ]
    assert scope["dedicated_python_paths"] == [
        "app/services/opaque_group_custody.py",
        "app/services/table_semantics.py",
        "app/services/tables.py",
    ]
    assert scope["exact_protected_compatibility_paths"] == [
        "app/api.py",
        "app/services/serializer.py",
        "frontend/lib/canonical-presentation.ts",
        "frontend/lib/document-api.ts",
        "frontend/lib/normalize-document-json.ts",
        "frontend/lib/page-results.ts",
        "frontend/lib/serialize-output.ts",
        "frontend/lib/types.ts",
    ]
    assert scope["administrative_candidate_paths"] == [
        str(exception.SEMANTIC_ISOLATION_GUARD_PATH),
        str(exception.SEMANTIC_ISOLATION_FOCUSED_TEST_PATH),
    ]
    assert scope["allowed_nonproduction_patterns"] == [
        "tests/fixtures/phase_04/tables/**",
        "tests/contract/test_p04_us(01|02|04|03)_*.py",
        "tests/performance/test_p04_us(01|02|04|03)_*.py",
        "tests/regression/phase_04/test_p04_us(01|02|04|03)_*.py",
        "tests/stories/phase_04/test_p04_us(01|02|04|03)_*.py",
        "frontend/tests/p04-us(01|02|04|03)-*.test.mts",
        "tracker/phase-04-tables/**",
    ]
    assert scope["new_production_paths_authorized"] is False
    assert scope["dependency_changes_authorized"] is False
    assert scope["public_capability_expansion_authorized"] is False
    assert scope["scanner_relaxation_authorized"] is False
    scoped_paths = [
        *scope["configuration_paths"],
        *scope["shared_python_paths"],
        *scope["dedicated_python_paths"],
        *scope["shared_frontend_paths"],
        *scope["dedicated_frontend_paths"],
        *scope["exact_protected_compatibility_paths"],
        *scope["administrative_candidate_paths"],
        *scope["allowed_nonproduction_patterns"],
    ]
    assert all(not re.search(r"(?:phase|p)[-_]?0?5\b", path, re.I) for path in scoped_paths)
    assert set(renewal["semantic_isolation"]["closed_table_public_roots"]) == set(
        exception._SEMANTIC_ISOLATION_TABLE_PUBLIC_ROOTS
        | exception._SEMANTIC_ISOLATION_OPAQUE_PUBLIC_ROOTS
        | exception._SEMANTIC_ISOLATION_TABLES_PUBLIC_ROOTS
    )
    assert renewal["semantic_isolation"]["activation_policy"] == {
        "mode": "terminal_exact_freeze",
        "future_syntax_authorized_by_scanner": False,
        "live_gate_date_policy": {
            "historical_fixed_dates_preserved": True,
            "live_override_supplied": False,
            "timezone": "UTC",
        },
        "reissue_after_each_story_or_code_freeze": True,
        "operative_between_freezes": False,
        "fixed_verification_path": str(
            exception.SEMANTIC_ISOLATION_PHASE04_VERIFICATION_PATH
        ),
        "fixed_terminal_approval_path": str(
            exception.SEMANTIC_ISOLATION_PHASE04_TERMINAL_APPROVAL_PATH
        ),
        "fixed_focused_gate_path": str(
            exception.SEMANTIC_ISOLATION_PHASE04_FOCUSED_GATE_PATH
        ),
        "fixed_us01_story_gate_path": str(
            exception.SEMANTIC_ISOLATION_PHASE04_US01_STORY_GATE_PATH
        ),
        "us01_preapproval_evidence_root": str(
            exception.SEMANTIC_ISOLATION_PHASE04_US01_PREAPPROVAL_EVIDENCE_ROOT
        ),
        "fixed_review_paths": {
            "production_security": str(
                exception.SEMANTIC_ISOLATION_PHASE04_PRODUCTION_SECURITY_REVIEW_PATH
            ),
            "metrics_custody": str(
                exception.SEMANTIC_ISOLATION_PHASE04_METRICS_CUSTODY_REVIEW_PATH
            ),
        },
        "terminal_status_owner_paths": list(
            exception.SEMANTIC_ISOLATION_STATUS_OWNER_PATHS
        ),
        "non_authoritative_status_summary_paths": list(
            exception.EXPECTED_SEMANTIC_ISOLATION_NON_AUTHORITATIVE_STATUS_SUMMARY_PATHS
        ),
        "terminal_configuration_paths": list(
            exception.SEMANTIC_ISOLATION_TERMINAL_CONFIGURATION_PATHS
        ),
        "terminal_identity_requirements": [
            "every current required code identity",
            (
                "every closed Phase 04 production, configuration, and "
                "frontend identity"
            ),
            "executable guard identity",
            "focused test identity",
            "P04-US01 final-code gate evidence identity",
            "P04-US01 exact gate-input identity manifest",
            "verification identity",
            "dependency custody",
            "exact current non-authoritative reconciliation summary identities",
            "protected P03 manifest",
            "Phase 05 Proposed-state boundary",
            "expiry and exact exception scope",
        ],
    }
    assert renewal["semantic_isolation"]["scanner_assurance"] == {
        "role": "non_authorizing_best_effort_telemetry",
        "authorization_effect": "none",
        "sound_sandbox_claimed": False,
        "comprehensive_capability_detection_claimed": False,
        "comprehensive_resource_or_termination_detection_claimed": False,
        "missed_or_accepted_syntax_authorizes_bytes": False,
        "nonwaived_gate_authority": (
            "exact_pinned_execution_and_independent_review_only"
        ),
        "mutated_bytes_require_new_terminal_freeze": True,
    }
    assert exception._SEMANTIC_ISOLATION_OPAQUE_PUBLIC_ROOTS == frozenset(
        {
            "capture_opaque_group_edges",
            "detach_opaque_group_edges",
            "empty_group_content_sha256",
            "has_literal_table_marker",
            "member_content_sha256",
            "record_id",
            "records_sha256",
            "restore_diagnostic_group_edges",
            "seal_diagnostic_custody",
            "stable_id",
        }
    )
    assert "build_canonical_projection" not in (
        exception._SEMANTIC_ISOLATION_OPAQUE_PUBLIC_ROOTS
    )
    assert "apply_canonical_projection" not in (
        exception._SEMANTIC_ISOLATION_OPAQUE_PUBLIC_ROOTS
    )
    opaque_path = "app/services/opaque_group_custody.py"
    assert renewal["semantic_isolation"]["existing_public_app_imports"][
        opaque_path
    ] == []
    assert all(
        imported["module"] != "app.services.presentation"
        for imported in renewal["semantic_isolation"]["allowed_app_imports"][
            opaque_path
        ]
    )
    assert renewal["semantic_isolation"]["closed_table_public_classes"] == {
        path: sorted(values)
        for path, values in exception._SEMANTIC_ISOLATION_PUBLIC_CLASSES.items()
    }
    assert renewal["semantic_isolation"]["closed_table_public_constants"] == {
        path: sorted(values)
        for path, values in exception._SEMANTIC_ISOLATION_PUBLIC_CONSTANTS.items()
    }
    assert renewal["semantic_isolation"]["existing_public_app_imports"] == {
        path: [
            {"module": module, "name": name, "asname": asname}
            for module, name, asname in sorted(values)
        ]
        for path, values in (
            exception._SEMANTIC_ISOLATION_EXISTING_PUBLIC_APP_IMPORTS.items()
        )
    }
    assert renewal["semantic_isolation"]["allowed_app_imports"] == {
        path: [
            {"module": module, "name": name, "asname": asname}
            for module, name, asname in sorted(values)
        ]
        for path, values in exception._SEMANTIC_ISOLATION_ALLOWED_APP_IMPORTS.items()
    }
    assert tuple(renewal["semantic_isolation"]["runtime_code_roots"]) == (
        exception._SEMANTIC_ISOLATION_RUNTIME_ROOTS
    )
    assert set(renewal["semantic_isolation"]["runtime_code_suffixes"]) == set(
        exception._SEMANTIC_ISOLATION_RUNTIME_SUFFIXES
    )
    assert set(
        renewal["semantic_isolation"]["phase05_boundary_identities"]
    ) == set(exception._SEMANTIC_ISOLATION_PHASE05_BOUNDARY_PATHS)
    assert renewal["semantic_isolation"]["forbidden_capabilities"] == list(
        exception._SEMANTIC_ISOLATION_FORBIDDEN_CAPABILITIES
    )
    assert set(renewal["semantic_isolation"]["exact_running_region_paths"]) == set(
        exception._SEMANTIC_ISOLATION_EXACT_RUNNING_REGION_PATHS
    )


@pytest.mark.parametrize(
    "mutation",
    [None, "ready", "in_progress", "stale", "omitted", "extra_file"],
)
def test_semantic_isolation_phase05_boundary_is_exact_and_proposed(
    tmp_path: Path,
    mutation: str | None,
) -> None:
    identities = _synthetic_phase05_boundary(tmp_path)
    story_path = "tracker/phase-05-charts-diagrams/stories/P05-US01.md"
    story = tmp_path / story_path
    if mutation == "ready":
        raw = b"# Boundary\n\nStatus: Ready  \n"
        story.write_bytes(raw)
        identities[story_path] = exception._semantic_isolation_file_identity(
            story_path,
            raw,
        )
    elif mutation == "in_progress":
        raw = b"# Boundary\n\nStatus: In Progress  \n"
        story.write_bytes(raw)
        identities[story_path] = exception._semantic_isolation_file_identity(
            story_path,
            raw,
        )
    elif mutation == "stale":
        identities[story_path]["raw_sha256"] = "0" * 64
    elif mutation == "omitted":
        identities.pop(story_path)
    elif mutation == "extra_file":
        extra = tmp_path / "tracker/phase-05-charts-diagrams/started.md"
        extra.write_text("Status: Ready\n", encoding="utf-8")

    if mutation is None:
        tracks = exception._semantic_isolation_validate_phase05_boundary(
            tmp_path,
            identities,
        )
        assert len(tracks) == len(
            exception._SEMANTIC_ISOLATION_PHASE05_BOUNDARY_PATHS
        )
    else:
        with pytest.raises(readiness.ReadinessContractError):
            exception._semantic_isolation_validate_phase05_boundary(
                tmp_path,
                identities,
            )


@pytest.mark.parametrize("mutation", [None, "omitted_path", "forbidden_drop"])
def test_semantic_isolation_protected_declarations_are_hard_compared(
    mutation: str | None,
) -> None:
    renewal = _load_json(
        PROJECT_ROOT / exception.SEMANTIC_ISOLATION_PHASE04_RENEWAL_WAIVER_PATH
    )
    isolation = deepcopy(renewal["semantic_isolation"])
    if mutation == "omitted_path":
        isolation["exact_running_region_paths"].pop(
            "app/services/running_regions.py"
        )
    elif mutation == "forbidden_drop":
        isolation["forbidden_capabilities"].pop()

    if mutation is None:
        protected = exception._semantic_isolation_validate_protected_declarations(
            isolation
        )
        assert set(protected) == set(
            exception._SEMANTIC_ISOLATION_EXACT_RUNNING_REGION_PATHS
        )
    else:
        with pytest.raises(readiness.ReadinessContractError):
            exception._semantic_isolation_validate_protected_declarations(
                isolation
            )


def test_semantic_isolation_runtime_path_inventory_is_closed() -> None:
    renewal = _load_json(
        PROJECT_ROOT / exception.SEMANTIC_ISOLATION_PHASE04_RENEWAL_WAIVER_PATH
    )
    scope = renewal["closed_phase04_scope"]
    closed_production = {
        *scope["configuration_paths"],
        *scope["shared_python_paths"],
        *scope["dedicated_python_paths"],
        *scope["shared_frontend_paths"],
        *scope["dedicated_frontend_paths"],
        *scope["exact_protected_compatibility_paths"],
    }
    expected = {
        path
        for path in metrics.REQUIRED_CODE_PATHS | closed_production
        if exception._semantic_isolation_is_runtime_code_path(path)
    }

    exception._semantic_isolation_validate_runtime_code_scope(
        PROJECT_ROOT,
        expected_paths=expected,
    )


def test_semantic_isolation_runtime_path_inventory_rejects_new_code(
    tmp_path: Path,
) -> None:
    for relative in exception._SEMANTIC_ISOLATION_RUNTIME_ROOTS:
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)
    known = tmp_path / "app/known.py"
    known.write_text("VALUE = 1\n", encoding="utf-8")
    exception._semantic_isolation_validate_runtime_code_scope(
        tmp_path,
        expected_paths={"app/known.py"},
    )

    (tmp_path / "app/unauthorized.py").write_text(
        "VALUE = 2\n",
        encoding="utf-8",
    )
    with pytest.raises(readiness.ReadinessContractError, match="production path"):
        exception._semantic_isolation_validate_runtime_code_scope(
            tmp_path,
            expected_paths={"app/known.py"},
        )


@pytest.mark.parametrize(
    "relative",
    ["frontend/db/runtime.ts", "plugin/runtime.py", "runtime.js"],
)
def test_semantic_isolation_runtime_inventory_rejects_path_escape(
    tmp_path: Path,
    relative: str,
) -> None:
    for root in exception._SEMANTIC_ISOLATION_RUNTIME_ROOTS:
        (tmp_path / root).mkdir(parents=True, exist_ok=True)
    known = tmp_path / "app/known.py"
    known.write_text("VALUE = 1\n", encoding="utf-8")
    escaped = tmp_path / relative
    escaped.parent.mkdir(parents=True, exist_ok=True)
    escaped.write_text("VALUE = 2\n", encoding="utf-8")

    with pytest.raises(readiness.ReadinessContractError, match="production path"):
        exception._semantic_isolation_validate_runtime_code_scope(
            tmp_path,
            expected_paths={"app/known.py"},
        )


def test_semantic_isolation_runtime_inventory_allows_nonproduction_tests(
    tmp_path: Path,
) -> None:
    for root in exception._SEMANTIC_ISOLATION_RUNTIME_ROOTS:
        (tmp_path / root).mkdir(parents=True, exist_ok=True)
    known = tmp_path / "app/known.py"
    known.write_text("VALUE = 1\n", encoding="utf-8")
    test_path = tmp_path / "tests/stories/phase_04/test_table.py"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text("def test_table(): pass\n", encoding="utf-8")

    exception._semantic_isolation_validate_runtime_code_scope(
        tmp_path,
        expected_paths={"app/known.py"},
    )


def test_semantic_isolation_python_projection_ignores_only_table_partition() -> None:
    baseline = b"def retained_projection():\n    return 1\n"
    table_only = baseline + b"\ndef _p04_table_private():\n    return 2\n"
    non_table = baseline.replace(b"return 1", b"return 2", 1)
    mixed_a = b"def _table_running_region_bridge():\n    return 1\n"
    mixed_b = mixed_a.replace(b"    return 1\n", b"    return 2\n", 1)

    baseline_digest = exception._semantic_isolation_python_projection(
        baseline,
        path="synthetic.py",
    )
    assert exception._semantic_isolation_python_projection(
        table_only,
        path="synthetic.py",
    ) == baseline_digest
    assert exception._semantic_isolation_python_projection(
        non_table,
        path="synthetic.py",
    ) != baseline_digest
    assert exception._semantic_isolation_python_projection(
        mixed_a,
        path="synthetic.py",
    ) != exception._semantic_isolation_python_projection(
        mixed_b,
        path="synthetic.py",
    )


def test_semantic_isolation_pipeline_projection_allows_private_table_growth() -> None:
    pipeline = (PROJECT_ROOT / "app/services/pipeline.py").read_bytes()
    changed = pipeline + b"\n\ndef _p04_table_isolation_probe():\n    return None\n"

    assert exception._semantic_isolation_python_projection(
        changed,
        path="app/services/pipeline.py",
    ) == exception._semantic_isolation_python_projection(
        pipeline,
        path="app/services/pipeline.py",
    )


def test_semantic_isolation_pipeline_candidate_projection_is_one_way() -> None:
    path = "app/services/pipeline.py"
    pipeline = (PROJECT_ROOT / path).read_bytes()
    tree = ast.parse(pipeline.decode("utf-8"))
    transformed = exception._SemanticIsolationTableStripper().visit(tree)
    assert isinstance(transformed, ast.Module)
    ast.fix_missing_locations(transformed)
    observed_candidate = exception._ast_digest(transformed)

    renewal = _load_json(
        PROJECT_ROOT / exception.SEMANTIC_ISOLATION_PHASE04_RENEWAL_WAIVER_PATH
    )
    isolation = renewal["semantic_isolation"]
    assert observed_candidate == (
        exception._SEMANTIC_ISOLATION_FINAL_US01_TABLE_PROJECTION_SHA256
    )
    assert isolation["candidate_specific_table_projection_sha256"] == {
        "app/models.py": (
            exception._SEMANTIC_ISOLATION_FINAL_US01_MODELS_PROJECTION_SHA256
        ),
        path: observed_candidate
    }
    assert exception._semantic_isolation_python_projection(
        pipeline,
        path=path,
    ) == exception._SEMANTIC_ISOLATION_PROTECTED_PIPELINE_PROJECTION_SHA256
    assert exception._SEMANTIC_ISOLATION_PROTECTED_PIPELINE_PROJECTION_SHA256 == (
        "31e3284e822a736a514ce008e4c1764c9a5dabc70cf71795ebec90fc4b8abd62"
    )


def test_semantic_isolation_models_validator_delta_is_exact_and_one_way() -> None:
    path = "app/models.py"
    models = (PROJECT_ROOT / path).read_bytes()
    tree = ast.parse(models.decode("utf-8"))
    transformed = exception._SemanticIsolationTableStripper().visit(
        ast.parse(models.decode("utf-8"))
    )
    assert isinstance(transformed, ast.Module)
    ast.fix_missing_locations(transformed)
    observed_candidate = exception._ast_digest(transformed)

    renewal = _load_json(
        PROJECT_ROOT / exception.SEMANTIC_ISOLATION_PHASE04_RENEWAL_WAIVER_PATH
    )
    isolation = renewal["semantic_isolation"]
    assert observed_candidate == (
        exception._SEMANTIC_ISOLATION_FINAL_US01_MODELS_PROJECTION_SHA256
    )
    assert isolation["models_validator_delta"] == (
        exception._SEMANTIC_ISOLATION_FINAL_US01_MODELS_DELTA
    )
    assert exception._semantic_isolation_models_validator_vector(
        models,
        tree=tree,
    ) == isolation["models_validator_delta"]["validator_vector"]
    assert exception._semantic_isolation_python_projection(
        models,
        path=path,
    ) == exception._SEMANTIC_ISOLATION_PROTECTED_MODELS_PROJECTION_SHA256
    assert exception._SEMANTIC_ISOLATION_PROTECTED_MODELS_PROJECTION_SHA256 == (
        "1976ba6f20ea6be8c8a7179a8500e442f5e62f31f8a3516ab429fa220f8275a5"
    )


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (
            b'form_group.get("canonical_mode") == "inert"',
            b'form_group.get("canonical_mode") == "active"',
        ),
        (
            b"_context_free_inert_raw_group_owner_is_closed(\n"
            b"                        item,\n"
            b"                        primary_id,\n"
            b"                    )",
            b"_context_free_inert_raw_group_owner_is_closed(\n"
            b"                        item,\n"
            b"                        item.id,\n"
            b"                    )",
        ),
        (
            b"                    item.id != public_id\n"
            b"                    or public_items_by_primary.get(primary_id) is not item\n"
            b"                    or not _context_free_inert_raw_group_owner_is_closed(\n",
            b"                    public_items_by_primary.get(primary_id) is not item\n"
            b"                    or item.id != public_id\n"
            b"                    or not _context_free_inert_raw_group_owner_is_closed(\n",
        ),
    ],
)
def test_semantic_isolation_models_validator_mutations_are_not_normalized(
    old: bytes,
    new: bytes,
) -> None:
    path = "app/models.py"
    models = (PROJECT_ROOT / path).read_bytes()
    assert models.count(old) == 1
    changed = models.replace(old, new, 1)
    assert changed != models

    assert exception._semantic_isolation_python_projection(
        changed,
        path=path,
    ) != exception._SEMANTIC_ISOLATION_PROTECTED_MODELS_PROJECTION_SHA256


def test_semantic_isolation_models_validator_requires_both_ordered_passes() -> None:
    path = "app/models.py"
    models = (PROJECT_ROOT / path).read_bytes()
    needle = (
        b"not _context_free_inert_raw_group_owner_is_closed(\n"
        b"                    item,\n"
        b"                    primary_id,\n"
        b"                )"
    )
    assert models.count(needle) == 1
    changed = models.replace(
        needle,
        b'item.type.casefold() != "text"',
        1,
    )

    assert exception._semantic_isolation_python_projection(
        changed,
        path=path,
    ) != exception._SEMANTIC_ISOLATION_PROTECTED_MODELS_PROJECTION_SHA256


def test_semantic_isolation_models_raw_pin_rejects_stripped_table_growth() -> None:
    path = "app/models.py"
    models = (PROJECT_ROOT / path).read_bytes()
    changed = models + b"\n\ndef _p04_table_models_probe():\n    return None\n"

    assert exception._semantic_isolation_python_projection(
        changed,
        path=path,
    ) != exception._SEMANTIC_ISOLATION_PROTECTED_MODELS_PROJECTION_SHA256


def test_semantic_isolation_shared_modules_match_table_scope_grammar() -> None:
    for path in (
        "app/models.py",
        "app/services/ir.py",
        "app/services/pipeline.py",
        "app/services/presentation.py",
        "app/services/source_text_alignment.py",
        "app/services/text_reconciliation.py",
    ):
        exception._semantic_isolation_validate_shared_python_table_scope(
            (PROJECT_ROOT / path).read_bytes(),
            path=path,
        )


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            b"table_decision_views_sink.clear()",
            b"table_decision_views_sink.clear(1)",
            "method capability",
        ),
        (
            b"        source_document_identity,\n        image_regions,\n",
            b"        None,\n        image_regions,\n",
            "external capability",
        ),
        (
            b"type(predecessor_failure).__name__",
            b"type(failure).__name__",
            "reflection capability",
        ),
    ],
)
def test_semantic_isolation_shared_candidate_exceptions_are_exact(
    old: bytes,
    new: bytes,
    message: str,
) -> None:
    path = "app/services/pipeline.py"
    source = (PROJECT_ROOT / path).read_bytes()
    exception._semantic_isolation_validate_shared_python_table_scope(
        source,
        path=path,
    )
    assert source.count(old) >= 1
    changed = source.replace(old, new, 1)

    with pytest.raises(readiness.ReadinessContractError, match=message):
        exception._semantic_isolation_validate_shared_python_table_scope(
            changed,
            path=path,
        )


@pytest.mark.parametrize(
    ("path", "old", "new", "message"),
    [
        (
            "app/models.py",
            b'raw_refs[0].rsplit("/", 1)',
            b'raw_refs[0].rsplit("/", 2)',
            "method capability",
        ),
        (
            "app/services/pipeline.py",
            b"_canonical_presentation_sha256(canonical)",
            b"_canonical_presentation_sha256(candidate)",
            "external capability",
        ),
        (
            "app/models.py",
            b"_build_canonical_presentation_from_validated(public_ir)",
            b"_build_canonical_presentation_from_validated(document_ir)",
            "external capability",
        ),
        (
            "app/services/pipeline.py",
            b"_build_canonical_presentation_from_validated(\n"
            b"                predecessor_ir\n"
            b"            )",
            b"_build_canonical_presentation_from_validated(\n"
            b"                candidate_ir\n"
            b"            )",
            "external capability",
        ),
    ],
)
def test_semantic_isolation_final_custody_calls_are_exactly_bounded(
    path: str,
    old: bytes,
    new: bytes,
    message: str,
) -> None:
    source = (PROJECT_ROOT / path).read_bytes()
    assert old in source
    changed = source.replace(old, new, 1)

    with pytest.raises(readiness.ReadinessContractError, match=message):
        exception._semantic_isolation_validate_shared_python_table_scope(
            changed,
            path=path,
        )


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (
            b"getattr(relationship, \"id\", None)",
            b"getattr(relationship, \"source_id\", None)",
        ),
        (
            b'hasattr(value[1], "model_dump")',
            b'hasattr(value[1], "__class__")',
        ),
    ],
)
def test_semantic_isolation_shared_reflection_allowance_is_exact(
    old: bytes,
    new: bytes,
) -> None:
    path = "app/services/pipeline.py"
    source = (PROJECT_ROOT / path).read_bytes()
    assert old in source
    changed = source.replace(old, new, 1)

    with pytest.raises(readiness.ReadinessContractError, match="dynamic|reflection"):
        exception._semantic_isolation_validate_shared_python_table_scope(
            changed,
            path=path,
        )


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            b"def _table_probe():\n    return eval('1')\n",
            "dynamic capability",
        ),
        (
            b"import requests as table_requests\n",
            "external capability",
        ),
        (
            b"from pathlib import Path\n\n"
            b"def _table_probe():\n    return Path('x').read_text()\n",
            "method capability|external capability",
        ),
        (
            b"def _table_probe():\n    p05_boundary = True\n",
            "Phase 05",
        ),
        (
            b"import time\n\ndef _table_probe():\n    return time.sleep(1)\n",
            "external capability",
        ),
        (
            b"import io\n\ndef _table_probe():\n    return io.open('x')\n",
            "external capability",
        ),
        (
            b"import io\nimport pdfplumber\n\n"
            b"def _table_probe(pdf_bytes):\n"
            b"    return pdfplumber.open(pdf_bytes)\n",
            "pdf input",
        ),
        (
            b"def _table_probe(document, name):\n"
            b"    return getattr(document, name)\n",
            "dynamic capability",
        ),
        (
            b"def _table_probe():\n"
            b"    return getattr(__builtins__, 'open')\n",
            "dynamic capability",
        ),
        (
            b"def _table_probe():\n"
            b"    left = 'running_'\n"
            b"    right = 'regions'\n"
            b"    return left + right\n",
            "reconstructed scope",
        ),
        (
            b"def _table_probe():\n"
            b"    left = 'page_'\n"
            b"    right = 'identity'\n"
            b"    return left + right\n",
            "reconstructed scope",
        ),
        (
            b"def _table_probe():\n"
            b"    left = 'phase'\n"
            b"    right = '05'\n"
            b"    return left + right\n",
            "reconstructed scope",
        ),
        (
            b"import threading\n\n"
            b"def _table_probe():\n"
            b"    return threading.Thread().start()\n",
            "method capability|external capability",
        ),
        (
            b"import pypdfium2\n\n"
            b"def _table_probe(path):\n"
            b"    return pypdfium2.PdfDocument(path)\n",
            "external capability",
        ),
        (
            b"import asyncio\n\n"
            b"async def _table_probe():\n"
            b"    return await asyncio.create_subprocess_exec('x')\n",
            "external capability",
        ),
        (
            b"import io as table_io\n"
            b"import pdfplumber as table_pdf\n\n"
            b"def _table_probe(pdf_bytes):\n"
            b"    return table_pdf.open(table_io.open('x'))\n",
            "external capability|pdf input",
        ),
        (
            b"def _table_probe(settings):\n"
            b"    settings.table_span_fidelity_enabled = True\n",
            "forced-on",
        ),
        (
            b"from pathlib import Path as table_path\n\n"
            b"def _table_probe():\n"
            b"    return table_path('x').open()\n",
            "method capability|external capability",
        ),
        (
            b"from shutil import copy as table_copy\n\n"
            b"def _table_probe():\n"
            b"    return table_copy('x', 'y')\n",
            "external capability",
        ),
        (
            b"from threading import Thread as table_thread\n\n"
            b"def _table_probe():\n"
            b"    return table_thread().start()\n",
            "method capability|external capability",
        ),
        (
            b"def _table_probe(document, name):\n"
            b"    alias = getattr\n"
            b"    return alias(document, name)\n",
            "dynamic capability",
        ),
        (
            b"def _table_probe(function):\n"
            b"    return function.__globals__['open']('x')\n",
            "reflection capability",
        ),
        (
            b"def _table_probe():\n"
            b"    while True:\n"
            b"        pass\n",
            "resource grammar",
        ),
        (
            b"def _table_probe(table_span_fidelity_enabled=False):\n"
            b"    return table_span_fidelity_enabled or True\n",
            "forced-on|flag flow",
        ),
    ],
)
def test_semantic_isolation_shared_table_scope_rejects_forbidden_capabilities(
    source: bytes,
    message: str,
) -> None:
    with pytest.raises(readiness.ReadinessContractError, match=message):
        exception._semantic_isolation_validate_shared_python_table_scope(
            source,
            path="synthetic.py",
        )


def test_semantic_isolation_dedicated_modules_match_closed_grammar() -> None:
    for path in (
        "app/services/opaque_group_custody.py",
        "app/services/table_semantics.py",
        "app/services/tables.py",
    ):
        exception._semantic_isolation_validate_dedicated_python(
            (PROJECT_ROOT / path).read_bytes(),
            path=path,
        )


def test_semantic_isolation_table_orchestrator_import_is_exact() -> None:
    path = "app/services/table_semantics.py"
    source = (PROJECT_ROOT / path).read_bytes()
    exact_import = (
        b"from app.services.pipeline import _build_docling_table_predecessor"
    )
    assert source.count(exact_import) == 1
    changed = source.replace(
        exact_import,
        b"from app.services.pipeline import _docling_table_item",
        1,
    )

    with pytest.raises(readiness.ReadinessContractError, match="dedicated import"):
        exception._semantic_isolation_validate_dedicated_python(
            changed,
            path=path,
        )


def test_semantic_isolation_opaque_custody_array_import_is_exact() -> None:
    path = "app/services/opaque_group_custody.py"
    source = (PROJECT_ROOT / path).read_bytes()
    old = b"from array import array"
    assert old in source
    changed = source.replace(old, b"from array import ArrayType, array", 1)

    with pytest.raises(readiness.ReadinessContractError, match="dedicated import"):
        exception._semantic_isolation_validate_dedicated_python(
            changed,
            path=path,
        )


@pytest.mark.parametrize(
    ("suffix", "message"),
    [
        (
            b"\n\ndef _table_probe():\n    import app.services.running_regions\n",
            "reaches P03",
        ),
        (b"\n\ndef _table_probe():\n    return eval('1')\n", "dynamic capability"),
        (
            b"\n\ndef _table_probe():\n    capability = eval\n"
            b"    return capability('1')\n",
            "dynamic capability",
        ),
        (b"\n\ndef _table_probe():\n    return open('x')\n", "dynamic capability"),
        (b"\n\ndef _table_probe():\n    import os\n", "dedicated import"),
        (
            b"\n\ndef _table_probe():\n    import time\n"
            b"    return time.sleep(1)\n",
            "external capability",
        ),
        (
            b"\n\ndef _table_probe():\n    import io\n"
            b"    return io.open('x')\n",
            "external capability",
        ),
        (b"\n\nfrom time import sleep\n", "dedicated import"),
        (b"\n\ndef _table_probe():\n    return 'Phase 05'\n", "Phase 05"),
        (b"\n\ndef _table_probe():\n    p05_boundary = True\n", "Phase 05"),
        (
            b"\n\ndef _table_probe(*, table_unknown_enabled=False):\n"
            b"    return None\n",
            "flag scope",
        ),
        (
            b"\n\ndef _table_probe():\n"
            b"    table_span_fidelity_enabled = True\n"
            b"    return table_span_fidelity_enabled\n",
            "forced-on",
        ),
        (
            b"\n\ndef _table_probe():\n"
            b"    return prepare_docling_table_inputs(\n"
            b"        {}, {}, {}, table_span_fidelity_enabled=True\n"
            b"    )\n",
            "forced-on",
        ),
        (
            b"\n\ndef _table_probe(document):\n"
            b"    return document.pages[0].page_identity\n",
            "reaches P03",
        ),
        (
            b"\n\ndef _table_probe(document):\n"
            b"    return getattr(document, 'running_' + 'regions')\n",
            "dynamic capability|reconstructed scope",
        ),
        (
            b"\n\ndef _table_probe():\n"
            b"    return 'phase' + '05'\n",
            "reconstructed scope",
        ),
        (
            b"\n\ndef _table_probe():\n"
            b"    return getattr(__builtins__, 'open')\n",
            "dynamic capability",
        ),
        (
            b"\n\nimport io as table_io\n"
            b"import pdfplumber as table_pdf\n\n"
            b"def _table_probe(pdf_bytes):\n"
            b"    return table_pdf.open(table_io.open('x'))\n",
            "external capability|pdf input",
        ),
        (
            b"\n\ndef _table_probe(settings):\n"
            b"    settings.table_span_fidelity_enabled = True\n",
            "forced-on|flag flow",
        ),
        (
            b"\n\ndef __getattr__(name):\n    return name\n",
            "module capability",
        ),
        (
            b"\n\ndef _table_probe():\n"
            b"    return ().__class__.__base__.__subclasses__()\n",
            "reflection capability",
        ),
        (
            b"\n\ndef _table_probe(function):\n"
            b"    return function.__globals__\n",
            "reflection capability",
        ),
        (
            b"\n\ndef _table_probe(value, name):\n"
            b"    return object.__getattribute__(value, name)\n",
            "reflection capability|dynamic capability",
        ),
        (
            b"\n\ndef _table_probe(value):\n"
            b"    return value.__setattr__(\n"
            b"        'table_span_fidelity_enabled', True\n"
            b"    )\n",
            "reflection capability",
        ),
        (
            b"\n\ndef _table_probe(*, table_span_fidelity_enabled=False):\n"
            b"    enabled = table_span_fidelity_enabled or True\n"
            b"    return enabled\n",
            "flag flow",
        ),
    ],
)
def test_semantic_isolation_dedicated_scanner_rejects_forbidden_scope(
    suffix: bytes,
    message: str,
) -> None:
    path = "app/services/table_semantics.py"
    source = (PROJECT_ROOT / path).read_bytes()

    with pytest.raises(readiness.ReadinessContractError, match=message):
        exception._semantic_isolation_validate_dedicated_python(
            source + suffix,
            path=path,
        )


def test_semantic_isolation_dedicated_scanner_rejects_default_on_flag() -> None:
    path = "app/services/table_semantics.py"
    source = (PROJECT_ROOT / path).read_bytes()
    needle = b"table_span_fidelity_enabled=False"
    assert needle in source
    changed = source.replace(needle, b"table_span_fidelity_enabled=True", 1)

    with pytest.raises(readiness.ReadinessContractError, match="flag default"):
        exception._semantic_isolation_validate_dedicated_python(
            changed,
            path=path,
        )


def test_semantic_isolation_dedicated_scanner_rejects_new_public_root() -> None:
    path = "app/services/table_semantics.py"
    source = (PROJECT_ROOT / path).read_bytes()
    changed = source + b"\n\ndef expand_table_authority():\n    return None\n"

    with pytest.raises(readiness.ReadinessContractError, match="public table"):
        exception._semantic_isolation_validate_dedicated_python(
            changed,
            path=path,
        )


def test_semantic_isolation_vector_reader_requires_owned_bytes() -> None:
    path = "app/services/tables.py"
    source = (PROJECT_ROOT / path).read_bytes()
    needle = b"pdfplumber.open(io.BytesIO(pdf_bytes))"
    assert needle in source
    changed = source.replace(needle, b"pdfplumber.open(pdf_bytes)", 1)

    with pytest.raises(readiness.ReadinessContractError, match="pdf input"):
        exception._semantic_isolation_validate_dedicated_python(
            changed,
            path=path,
        )


@pytest.mark.parametrize(
    ("injection", "message"),
    [
        (b"    while True:\n        pass\n", "resource grammar"),
        (
            b"    oversized = ['x'] * (1024 ** 3)\n",
            "allocation",
        ),
        (
            b"    deadline = perf_counter() + 1000000\n",
            "deadline flow",
        ),
        (
            b"    _normalize_cell(value)\n",
            "call graph",
        ),
    ],
)
def test_semantic_isolation_vector_reader_rejects_resource_and_recursion_escapes(
    injection: bytes,
    message: str,
) -> None:
    path = "app/services/tables.py"
    source = (PROJECT_ROOT / path).read_bytes()
    marker = (
        b"def _normalize_cell(value: Any) -> str:\n"
        b'    """Normalize incidental PDF spacing while retaining meaningful '
        b'line breaks."""\n\n'
    )
    assert marker in source
    changed = source.replace(marker, marker + injection, 1)

    with pytest.raises(readiness.ReadinessContractError, match=message):
        exception._semantic_isolation_validate_dedicated_python(
            changed,
            path=path,
        )


def test_semantic_isolation_vector_reader_rejects_unreachable_private_helper() -> None:
    path = "app/services/tables.py"
    source = (PROJECT_ROOT / path).read_bytes()
    changed = source + b"\n\ndef _table_unreachable():\n    return None\n"

    with pytest.raises(readiness.ReadinessContractError, match="reachability"):
        exception._semantic_isolation_validate_dedicated_python(
            changed,
            path=path,
        )


def test_semantic_isolation_vector_reader_rejects_mutual_recursion() -> None:
    path = "app/services/tables.py"
    source = (PROJECT_ROOT / path).read_bytes()
    marker = (
        b'    """Extract bordered vector tables, keyed by one-based physical '
        b'page index."""\n\n'
    )
    assert marker in source
    changed = source.replace(marker, marker + b"    _table_cycle_a()\n", 1)
    changed += (
        b"\n\ndef _table_cycle_a():\n    return _table_cycle_b()\n"
        b"\n\ndef _table_cycle_b():\n    return _table_cycle_a()\n"
    )

    with pytest.raises(readiness.ReadinessContractError, match="call graph"):
        exception._semantic_isolation_validate_dedicated_python(
            changed,
            path=path,
        )


@pytest.mark.parametrize(
    "suffix",
    [
        b"\n\nclass ExpandedTableAuthority:\n    pass\n",
        b"\n\nEXPANDED_TABLE_AUTHORITY = True\n",
        b"\n\nfrom app.models import ParseResult\n",
    ],
)
def test_semantic_isolation_dedicated_scanner_rejects_public_expansion(
    suffix: bytes,
) -> None:
    path = "app/services/table_semantics.py"
    source = (PROJECT_ROOT / path).read_bytes()

    with pytest.raises(
        readiness.ReadinessContractError,
        match="public|dedicated import",
    ):
        exception._semantic_isolation_validate_dedicated_python(
            source + suffix,
            path=path,
        )


def test_semantic_isolation_dedicated_scanner_rejects_unlisted_private_app_import(
) -> None:
    path = "app/services/table_semantics.py"
    source = (PROJECT_ROOT / path).read_bytes()
    changed = source + b"\n\nfrom app.models import ParseResult as _ParseResult\n"

    with pytest.raises(readiness.ReadinessContractError, match="dedicated import"):
        exception._semantic_isolation_validate_dedicated_python(
            changed,
            path=path,
        )


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (b'AUTHORITY = "diagnostic_only"', b'AUTHORITY = "canonical"'),
        (b"MAX_RECORDS = 65_536", b"MAX_RECORDS = 65_537"),
        (
            b"MAX_RAW_DEFINITIONS_SCANNED = 262_144",
            b"MAX_RAW_DEFINITIONS_SCANNED = 262_145",
        ),
        (
            b"MAX_CONTENT_ITEM_BYTES = 8 * 1024 * 1024",
            b"MAX_CONTENT_ITEM_BYTES = 8 * 1024 * 1024 + 1",
        ),
        (
            b"MAX_CONTENT_DOCUMENT_BYTES = 64 * 1024 * 1024",
            b"MAX_CONTENT_DOCUMENT_BYTES = 64 * 1024 * 1024 + 1",
        ),
    ],
)
def test_semantic_isolation_opaque_custody_rejects_authority_or_cap_expansion(
    old: bytes,
    new: bytes,
) -> None:
    path = "app/services/opaque_group_custody.py"
    source = (PROJECT_ROOT / path).read_bytes()
    assert old in source
    changed = source.replace(old, new, 1)

    with pytest.raises(readiness.ReadinessContractError, match="authority"):
        exception._semantic_isolation_validate_dedicated_python(
            changed,
            path=path,
        )


def test_semantic_isolation_frontend_partition_is_table_only() -> None:
    frontend = (PROJECT_ROOT / "frontend/app/clearleaf-workspace.tsx").read_bytes()
    marker = b'  if (type === "table") {'
    changed = frontend.replace(
        marker,
        marker + b"\n    const tableIsolationProbe = true;",
        1,
    )
    assert changed != frontend

    baseline_projection, _ = exception._semantic_isolation_frontend_table_block(
        frontend
    )
    changed_projection, changed_block = (
        exception._semantic_isolation_frontend_table_block(changed)
    )
    assert changed_projection == baseline_projection
    assert "tableIsolationProbe" in changed_block


@pytest.mark.parametrize(
    "injection",
    [
        b'\n    void fetch("/forbidden");',
        b'\n    void Function("return 1");',
        b'\n    void globalThis["fe" + "tch"];',
        b"\n    void ({}).constructor;",
        b'\n    void import("./forbidden");',
        b"\n    const \\u0066orbidden = true;",
        b"\n    const runningRegions = true;",
        b"\n    const phase05Boundary = true;",
        b"\n    const onClick = () => undefined;",
        b"\n    const alias = document;",
        b'\n    const phaseBoundary = "phase" + "05";',
        b'\n    const rr = "running_" + "regions";',
        b'\n    const nodeModule = "node:fs";',
        b"\n    module.exports = readTableSemantics;",
        b"\n    exports.table = readTableSemantics;",
        b'\n    const externalImage = <img src="/forbidden" />;',
        (
            b'\n    const ctor = "con" + "structor";'
            b' const scope = "global" + "This";'
            b' const request = "fe" + "tch";'
        ),
        b"\n    while (true) {}",
        b"\n    const oversized = new Array(1e9).fill(0);",
    ],
)
def test_semantic_isolation_frontend_partition_rejects_forbidden_scope(
    injection: bytes,
) -> None:
    frontend = (PROJECT_ROOT / "frontend/app/clearleaf-workspace.tsx").read_bytes()
    marker = b'  if (type === "table") {'
    changed = frontend.replace(marker, marker + injection, 1)

    with pytest.raises(readiness.ReadinessContractError, match="branch scope"):
        exception._semantic_isolation_frontend_table_block(changed)


def test_semantic_isolation_frontend_helper_matches_closed_grammar() -> None:
    helper = (PROJECT_ROOT / "frontend/lib/table-semantics.ts").read_bytes()
    exception._semantic_isolation_validate_frontend_helper(helper)


@pytest.mark.parametrize(
    ("suffix", "message"),
    [
        (b'\nconst tableFetch = () => fetch("/forbidden");\n', "helper scope"),
        (
            b'\nconst tableFetch = globalThis["fe" + "tch"];\n',
            "helper scope",
        ),
        (b"\nconst tableCtor = ({}).constructor;\n", "helper scope"),
        (b'\nconst tableImport = import("./forbidden");\n', "helper scope"),
        (b"\nconst \\u0066orbidden = true;\n", "helper scope"),
        (b"\nconst runningRegions = true;\n", "helper scope"),
        (b"\nconst phase05Boundary = true;\n", "helper scope"),
        (b'\nconst tableCtor = Function("return 1");\n', "helper scope"),
        (b"\nconst alias = document;\n", "helper scope"),
        (b'\nconst phaseBoundary = "phase" + "05";\n', "helper scope"),
        (
            b'\nconst phase = "phase"; const number = "05"; '
            b"const boundary = phase + number;\n",
            "helper scope",
        ),
        (b'\nimport fs from "node:fs";\n', "helper scope"),
        (b'\nconst child = require("node:child_process");\n', "helper scope"),
        (b"\nmodule.exports = readTableSemantics;\n", "helper scope"),
        (b"\nexports.table = readTableSemantics;\n", "helper scope"),
        (b'\nconst externalImage = <img src="/forbidden" />;\n', "helper scope"),
        (
            b'\nconst ctor = "con" + "structor";'
            b' const scope = "global" + "This";'
            b' const request = "fe" + "tch";\n',
            "helper scope",
        ),
        (b"\nwhile (true) {}\n", "helper scope"),
        (b"\nconst oversized = new Array(1e9).fill(0);\n", "helper scope"),
        (b"\nexport const expandedTableSurface = true;\n", "public capability"),
    ],
)
def test_semantic_isolation_frontend_helper_rejects_forbidden_scope(
    suffix: bytes,
    message: str,
) -> None:
    helper = (PROJECT_ROOT / "frontend/lib/table-semantics.ts").read_bytes()

    with pytest.raises(readiness.ReadinessContractError, match=message):
        exception._semantic_isolation_validate_frontend_helper(helper + suffix)


def test_semantic_isolation_exact_running_region_custody_is_immutable() -> None:
    renewal = _load_json(
        PROJECT_ROOT / exception.SEMANTIC_ISOLATION_PHASE04_RENEWAL_WAIVER_PATH
    )
    expected_paths = renewal["semantic_isolation"]["exact_running_region_paths"]

    for path, expected in expected_paths.items():
        raw = (PROJECT_ROOT / path).read_bytes()
        assert exception._semantic_isolation_identity(raw) == expected
        assert exception._semantic_isolation_identity(raw + b"\n") != expected


def test_hardened_phase04_enumerates_story_and_cumulative_frontend_tests() -> None:
    assert exception.EXPECTED_PHASE04_ADDED_PATHS == (
        "app/services/table_semantics.py",
        "frontend/lib/table-semantics.ts",
        "frontend/tests/p04-tables.test.mts",
    )
    assert exception.EXPECTED_HARDENED_PHASE04_ADDED_PATHS == (
        "app/services/table_semantics.py",
        "frontend/lib/table-semantics.ts",
        "frontend/tests/p04-us01-table-readiness.test.mts",
        "frontend/tests/p04-us01-table-span-fidelity.test.mts",
        "frontend/tests/p04-tables.test.mts",
    )
    authorized = exception._expected_hardened_phase04_authorized_change()
    assert tuple(authorized["added_phase04_paths"]) == (
        exception.EXPECTED_HARDENED_PHASE04_ADDED_PATHS
    )
    assert tuple(authorized["allowed_existing_paths"]) == (
        exception.EXPECTED_HARDENED_EXISTING_PATHS
    )
    readiness_identity = exception.EXPECTED_HARDENED_PHASE04_READINESS_TEST_IDENTITY
    readiness_raw = (PROJECT_ROOT / readiness_identity["path"]).read_bytes()
    assert len(readiness_raw) == readiness_identity["size_bytes"]
    assert hashlib.sha256(readiness_raw).hexdigest() == readiness_identity["sha256"]
    assert authorized["protected_surfaces"][readiness_identity["path"]][
        "exact_identity"
    ] == readiness_identity


def test_hardened_phase04_metrics_contract_accepts_only_two_exact_states() -> None:
    path = (
        PROJECT_ROOT
        / "tests/performance/test_p03_us08_running_region_metrics_contract.py"
    )
    candidate = path.read_bytes()
    assert exception._validate_hardened_metrics_contract_surface(candidate) == (
        exception.EXPECTED_HARDENED_METRICS_CONTRACT_CANDIDATE_IDENTITY["sha256"]
    )

    changed = candidate + b"\n"
    with pytest.raises(readiness.ReadinessContractError, match="custody bridge"):
        exception._validate_hardened_metrics_contract_surface(changed)


def test_hardened_phase04_expiry_binds_exact_production_boundary() -> None:
    expiry = exception.EXPECTED_HARDENED_PHASE04_EXPIRY

    assert expiry == {
        "expired_effect": (
            "P03-US08 returns to In Progress and dependent exit claims are blocked"
        ),
        "expires_before": [
            "production enablement",
            "running-region semantic or runtime behavior change",
            "relevant running-region custody change",
            "authorized Phase 04 scope or path expansion",
            "hardened grammar or scanner relaxation",
        ],
        "review_due_on": "2026-09-02",
    }
    changed = deepcopy(expiry)
    changed["expires_before"][0] = "production enablement of running regions"
    assert changed != expiry


def _validate_second_additive_authorization(*, today: date) -> None:
    waiver = _waiver()
    hardened = _load_json(
        PROJECT_ROOT / exception.HARDENED_PHASE04_RENEWAL_WAIVER_PATH
    )
    exception._validate_second_additive_p04_us01_authorization(
        PROJECT_ROOT,
        expected_history=waiver["failed_history"],
        hardened_renewal=hardened,
        original_waiver=waiver,
        pipeline_raw=(PROJECT_ROOT / "app/services/pipeline.py").read_bytes(),
        table_semantics_raw=(
            PROJECT_ROOT / "app/services/table_semantics.py"
        ).read_bytes(),
        today=today,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("maximum_overrun_fraction", 0.0500000001),
        ("observed_seconds", 0.05),
        ("strict_ceiling_seconds", 0.051),
    ],
)
def test_second_additive_authorization_rejects_latency_fact_drift(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: Any,
) -> None:
    authorization = deepcopy(
        exception.EXPECTED_SECOND_ADDITIVE_P04_US01_AUTHORIZATION
    )
    authorization["exception_scope"][field] = value
    monkeypatch.setattr(
        exception,
        "EXPECTED_SECOND_ADDITIVE_P04_US01_AUTHORIZATION",
        authorization,
    )

    with pytest.raises(
        readiness.ReadinessContractError,
        match="authorization differs",
    ):
        _validate_second_additive_authorization(today=date(2026, 8, 4))


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("failed_history", "artifact_count", 54),
        ("hosted_usage", "hosted_requests", 1),
        ("operational_constraints", "feature_flag_default", True),
        (
            "operational_constraints",
            "canonical_strict_final_artifact_present",
            True,
        ),
        ("prior_guard_identity", "size_bytes", 389_881),
        ("prior_focused_guard_identity", "size_bytes", 202_101),
    ],
)
def test_second_additive_authorization_rejects_nonwaived_or_custody_drift(
    monkeypatch: pytest.MonkeyPatch,
    section: str,
    field: str,
    value: Any,
) -> None:
    authorization = deepcopy(
        exception.EXPECTED_SECOND_ADDITIVE_P04_US01_AUTHORIZATION
    )
    authorization[section][field] = value
    monkeypatch.setattr(
        exception,
        "EXPECTED_SECOND_ADDITIVE_P04_US01_AUTHORIZATION",
        authorization,
    )

    with pytest.raises(
        readiness.ReadinessContractError,
        match="authorization differs",
    ):
        _validate_second_additive_authorization(today=date(2026, 8, 4))


def test_second_additive_authorization_rejects_removed_nonwaived_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = deepcopy(
        exception.EXPECTED_SECOND_ADDITIVE_P04_US01_AUTHORIZATION
    )
    authorization["not_waived"].remove("peak_rss")
    monkeypatch.setattr(
        exception,
        "EXPECTED_SECOND_ADDITIVE_P04_US01_AUTHORIZATION",
        authorization,
    )

    with pytest.raises(
        readiness.ReadinessContractError,
        match="authorization differs",
    ):
        _validate_second_additive_authorization(today=date(2026, 8, 4))


def test_second_additive_authorization_expires_after_review_date() -> None:
    with pytest.raises(
        readiness.ReadinessContractError,
        match="expired",
    ):
        _validate_second_additive_authorization(today=date(2026, 9, 3))


# These exact-construction probes describe the superseded hardened renewal's
# narrow helper grammar.  They remain as non-collected history; the active
# semantic-isolation probes below exercise the closed Phase 04 partition.
def _legacy_hardened_frontend_accepts_exact_canonical_table_delegation() -> None:
    changed = _frontend_with_canonical_table_delegation()

    assert exception._phase04_frontend_normalized_digest(changed) == (
        exception.EXPECTED_PHASE04_FRONTEND_NORMALIZED_SHA256
    )
    exception._validate_hardened_phase04_frontend(changed, helper_raw=None)
    protected = exception._expected_hardened_phase04_authorized_change()[
        "protected_surfaces"
    ]["frontend/app/clearleaf-workspace.tsx"]
    assert protected["allowed_canonical_table_delegation"] == (
        exception.EXPECTED_PHASE04_CANONICAL_TABLE_DELEGATION
    )


def _legacy_hardened_frontend_requires_form_precedence_for_table_delegation() -> None:
    source = (
        PROJECT_ROOT / "frontend/app/clearleaf-workspace.tsx"
    ).read_text(encoding="utf-8")
    fallback_context = (
        exception.EXPECTED_PHASE04_CANONICAL_FORM_BRANCH
        + exception.EXPECTED_PHASE04_CANONICAL_FALLBACK
    )
    moved = source.replace(
        fallback_context,
        exception.EXPECTED_PHASE04_CANONICAL_TABLE_DELEGATION
        + fallback_context,
        1,
    ).encode("utf-8")

    with pytest.raises(readiness.ReadinessContractError, match="precedence"):
        exception._validate_hardened_phase04_frontend(moved, helper_raw=None)


@pytest.mark.parametrize(
    ("finding_id", "old", "new"),
    [
        (
            "exactly-one-source-item",
            "matchingPrimaryItems.length !== 1",
            "matchingPrimaryItems.length === 0",
        ),
        (
            "table-type-required",
            'primaryItem.type.toLowerCase() !== "table"',
            'primaryItem.type.toLowerCase() === "table"',
        ),
        (
            "own-table-evidence-required",
            '!Object.hasOwn(primaryItem, "table_evidence")',
            '!("table_evidence" in primaryItem)',
        ),
        (
            "unmatched-item-fallback-identity",
            "if (matchingPrimaryItems.length !== 1) return canonicalFallback;",
            "if (matchingPrimaryItems.length !== 1) return null;",
        ),
        (
            "unmarked-item-fallback-identity",
            "          return canonicalFallback;\n",
            "          return null;\n",
        ),
    ],
)
def _legacy_hardened_frontend_rejects_canonical_delegation_contract_changes(
    finding_id: str,
    old: str,
    new: str,
) -> None:
    del finding_id
    delegation = exception.EXPECTED_PHASE04_CANONICAL_TABLE_DELEGATION
    assert delegation.count(old) == 1
    changed = _frontend_with_canonical_table_delegation(
        delegation.replace(old, new, 1)
    )

    with pytest.raises(readiness.ReadinessContractError, match="canonical table"):
        exception._validate_hardened_phase04_frontend(changed, helper_raw=None)


def _legacy_hardened_frontend_preserves_default_canonical_fallback_identity() -> None:
    frontend = (
        PROJECT_ROOT / "frontend/app/clearleaf-workspace.tsx"
    ).read_bytes()
    fallback_context = (
        exception.EXPECTED_PHASE04_CANONICAL_FORM_BRANCH
        + exception.EXPECTED_PHASE04_CANONICAL_FALLBACK
    ).encode("utf-8")
    changed = frontend.replace(
        fallback_context,
        (
            exception.EXPECTED_PHASE04_CANONICAL_FORM_BRANCH
            + "        return null;\n"
        ).encode("utf-8"),
        1,
    )

    with pytest.raises(readiness.ReadinessContractError, match="fallback"):
        exception._validate_hardened_phase04_frontend(changed, helper_raw=None)


def _legacy_hardened_frontend_rejects_broader_canonical_surface() -> None:
    delegation = exception.EXPECTED_PHASE04_CANONICAL_TABLE_DELEGATION
    changed = _frontend_with_canonical_table_delegation(
        "        sourcePage.items.pop();\n" + delegation
    )

    with pytest.raises(readiness.ReadinessContractError, match="canonical table"):
        exception._validate_hardened_phase04_frontend(changed, helper_raw=None)


def test_hardened_config_accepts_only_table_gated_fail_closed_checks() -> None:
    expected = (
        {"table_span_fidelity_enabled"},
        {
            "table_evidence_reconciliation_enabled",
            "table_span_fidelity_enabled",
        },
        {
            "table_candidate_gate_enabled",
            "table_evidence_reconciliation_enabled",
        },
        {
            "table_candidate_gate_enabled",
            "table_multi_page_merge_enabled",
        },
    )
    for source, names in zip(
        exception.EXPECTED_PHASE04_CONFIG_GUARD_SOURCES,
        expected,
        strict=True,
    ):
        safe = ast.parse(source).body[0]
        assert exception._validate_phase04_config_guard(safe) == names

    unsafe = ast.parse(
        "if self.table_span_fidelity_enabled:\n"
        "    self.layout_running_regions_enabled = False\n"
    ).body[0]
    with pytest.raises(readiness.ReadinessContractError, match="guard differs"):
        exception._validate_phase04_config_guard(unsafe)

    default_on = ast.parse(
        "if not self.table_span_fidelity_enabled:\n"
        "    raise ValueError('PARSER_TABLES_SPAN_FIDELITY_ENABLED changed')\n"
    ).body[0]
    with pytest.raises(readiness.ReadinessContractError, match="guard differs"):
        exception._validate_phase04_config_guard(default_on)


@pytest.mark.parametrize(
    "source",
    [
        "if self.table_span_fidelity_enabled and "
        "self.table_span_fidelity_enabled:\n"
        "    raise ValueError('kill switch')\n",
        "if self.table_evidence_reconciliation_enabled and "
        "self.table_span_fidelity_enabled:\n"
        "    raise ValueError('inverted dependency')\n",
        "if (self.table_span_fidelity_enabled or "
        "self.table_evidence_reconciliation_enabled or "
        "self.table_candidate_gate_enabled or "
        "self.table_multi_page_merge_enabled):\n"
        "    raise ValueError('combined guard')\n",
    ],
)
def test_hardened_config_rejects_kill_switch_and_inverted_guards(
    source: str,
) -> None:
    with pytest.raises(readiness.ReadinessContractError, match="guard differs"):
        exception._validate_phase04_config_guard(ast.parse(source).body[0])


def _validate_hardened_substitution(
    monkeypatch: pytest.MonkeyPatch,
    *,
    path: str,
    replacement: bytes,
) -> None:
    waiver = _waiver()
    frontend_renewal = _load_json(PROJECT_ROOT / exception.RENEWAL_WAIVER_PATH)
    phase04_renewal = _load_json(
        PROJECT_ROOT / exception.PHASE04_RENEWAL_WAIVER_PATH
    )
    primary = _artifact(waiver["primary_candidate"])
    baseline = exception._phase04_baseline_code(primary["code_sha256"]["post"])
    current = deepcopy(baseline)
    current[path] = {
        "path": path,
        "sha256": hashlib.sha256(replacement).hexdigest(),
        "size_bytes": len(replacement),
    }
    original = exception._read_bound_file

    def read_bound_file(
        root: Path,
        observed_path: str,
        *,
        maximum_bytes: int,
        label: str,
    ) -> tuple[bytes, Any]:
        raw, binding = original(
            root,
            observed_path,
            maximum_bytes=maximum_bytes,
            label=label,
        )
        if observed_path == path:
            return replacement, binding
        return raw, binding

    monkeypatch.setattr(exception, "_read_bound_file", read_bound_file)
    exception._validate_hardened_phase04_renewal(
        PROJECT_ROOT,
        current_code=current,
        phase04_baseline_code=baseline,
        expected_history=waiver["failed_history"],
        phase04_renewal=phase04_renewal,
        original_waiver=waiver,
        today=date(2026, 8, 3),
    )


def _replace_once(raw: bytes, old: bytes, new: bytes) -> bytes:
    if raw.count(old) == 1:
        return raw.replace(old, new, 1)
    assert raw.count(old) == 0, old.decode("utf-8", errors="replace")
    assert raw.count(new) == 1, new.decode("utf-8", errors="replace")
    return raw


def _all_four_story_pipeline_glue(pipeline: bytes) -> bytes:
    try:
        exception._validate_hardened_phase04_pipeline_surface(pipeline)
    except readiness.ReadinessContractError:
        pass
    else:
        return pipeline

    safe = _replace_once(
        pipeline,
        b"    native_texts: Sequence[str] | None = None,\n"
        b") -> tuple[int, dict[str, Any]]:\n"
        b"    page_index, box = _bbox_from_prov(raw_item, page_heights)\n",
        b"    native_texts: Sequence[str] | None = None,\n"
        b"    *,\n"
        b"    table_span_fidelity_enabled: bool = False,\n"
        b") -> tuple[int, dict[str, Any]]:\n"
        b"    from app.services.table_semantics import (\n"
        b"        prepare_docling_table,\n"
        b"        prepare_docling_table_input,\n"
        b"    )\n"
        b"    raw_item = prepare_docling_table_input(\n"
        b"        raw_item,\n"
        b"        page_heights,\n"
        b"        page_words_by_page,\n"
        b"        table_span_fidelity_enabled=table_span_fidelity_enabled,\n"
        b"    )\n"
        b"    page_index, box = _bbox_from_prov(raw_item, page_heights)\n",
    )
    safe = _replace_once(
        safe,
        b"    _refresh_table_serializations(item)\n"
        b"    return page_index, item\n\n\n"
        b"def _raw_table_value(",
        b"    _refresh_table_serializations(item)\n"
        b"    item = prepare_docling_table(\n"
        b"        item,\n"
        b"        raw_item,\n"
        b"        table_span_fidelity_enabled=table_span_fidelity_enabled,\n"
        b"    )\n"
        b"    return page_index, item\n\n\n"
        b"def _raw_table_value(",
    )
    safe = _replace_once(
        safe,
        b"def _vector_table_item(table: RawTable | Mapping[str, Any]) "
        b"-> dict[str, Any]:\n"
        b"    rows = [\n",
        b"def _vector_table_item(\n"
        b"    table: RawTable | Mapping[str, Any],\n"
        b"    *,\n"
        b"    table_span_fidelity_enabled: bool = False,\n"
        b") -> dict[str, Any]:\n"
        b"    from app.services.table_semantics import prepare_vector_table\n"
        b"    rows = [\n",
    )
    safe = _replace_once(
        safe,
        b"    _refresh_table_serializations(item)\n"
        b"    return item\n\n\n"
        b"def _ocr_line_primary_decision(",
        b"    _refresh_table_serializations(item)\n"
        b"    item = prepare_vector_table(\n"
        b"        item,\n"
        b"        table,\n"
        b"        table_span_fidelity_enabled=table_span_fidelity_enabled,\n"
        b"    )\n"
        b"    return item\n\n\n"
        b"def _ocr_line_primary_decision(",
    )
    safe = _replace_once(
        safe,
        b'    coordinate_unit: str = "pt",\n'
        b") -> tuple[dict[int, list[dict[str, Any]]], "
        b"dict[int, list[dict[str, Any]]]]:\n",
        b'    coordinate_unit: str = "pt",\n'
        b"    table_span_fidelity_enabled: bool = False,\n"
        b") -> tuple[dict[int, list[dict[str, Any]]], "
        b"dict[int, list[dict[str, Any]]]]:\n",
    )
    safe = _replace_once(
        safe,
        b"                native_texts,\n"
        b"            )\n"
        b"            tables[page_index].append(stamp(item))\n",
        b"                native_texts,\n"
        b"                table_span_fidelity_enabled="
        b"table_span_fidelity_enabled,\n"
        b"            )\n"
        b"            tables[page_index].append(stamp(item))\n",
    )
    safe = _replace_once(
        safe,
        b"def _merge_tables(\n"
        b"    docling_tables: Mapping[int, Sequence[dict[str, Any]]],\n"
        b"    vector_tables: Mapping[int, Sequence[RawTable]],\n"
        b") -> dict[int, list[dict[str, Any]]]:\n"
        b"    merged: dict[int, list[dict[str, Any]]] = defaultdict(list)\n",
        b"def _merge_tables(\n"
        b"    docling_tables: Mapping[int, Sequence[dict[str, Any]]],\n"
        b"    vector_tables: Mapping[int, Sequence[RawTable]],\n"
        b"    *,\n"
        b"    table_span_fidelity_enabled: bool = False,\n"
        b"    table_evidence_reconciliation_enabled: bool = False,\n"
        b") -> dict[int, list[dict[str, Any]]]:\n"
        b"    from app.services.table_semantics import reconcile_table_candidates\n"
        b"    merged: dict[int, list[dict[str, Any]]] = defaultdict(list)\n",
    )
    safe = _replace_once(
        safe,
        b"            candidate = _vector_table_item(raw_table)\n",
        b"            candidate = _vector_table_item(\n"
        b"                raw_table,\n"
        b"                table_span_fidelity_enabled="
        b"table_span_fidelity_enabled,\n"
        b"            )\n",
    )
    safe = _replace_once(
        safe,
        b"    return merged\n\n\n"
        b"def _attach_image_to_table(",
        b"    merged = reconcile_table_candidates(\n"
        b"        merged,\n"
        b"        docling_tables,\n"
        b"        vector_tables,\n"
        b"        table_span_fidelity_enabled=table_span_fidelity_enabled,\n"
        b"        table_evidence_reconciliation_enabled="
        b"table_evidence_reconciliation_enabled,\n"
        b"    )\n"
        b"    return merged\n\n\n"
        b"def _attach_image_to_table(",
    )
    safe = _replace_once(
        safe,
        b'    """Run all format-neutral analysis and reconciliation stages in one place."""\n\n',
        b'    """Run all format-neutral analysis and reconciliation stages in one place."""\n\n'
        b"    from app.services.table_semantics import (\n"
        b"        gate_table_candidates,\n"
        b"        merge_continued_tables,\n"
        b"        seal_table_pages,\n"
        b"    )\n",
    )
    safe = _replace_once(
        safe,
        b"        coordinate_unit=context.coordinate_unit,\n"
        b"    )\n"
        b"    tables = _merge_tables(docling_tables, context.vector_tables)\n",
        b"        coordinate_unit=context.coordinate_unit,\n"
        b"        table_span_fidelity_enabled="
        b"context.settings.table_span_fidelity_enabled,\n"
        b"    )\n"
        b"    tables = _merge_tables(\n"
        b"        docling_tables,\n"
        b"        context.vector_tables,\n"
        b"        table_span_fidelity_enabled="
        b"context.settings.table_span_fidelity_enabled,\n"
        b"        table_evidence_reconciliation_enabled="
        b"context.settings.table_evidence_reconciliation_enabled,\n"
        b"    )\n"
        b"    tables = gate_table_candidates(\n"
        b"        tables,\n"
        b"        body_items,\n"
        b"        context.image_regions,\n"
        b"        context.raw_docling,\n"
        b"        context.source_document_identity,\n"
        b"        table_span_fidelity_enabled="
        b"context.settings.table_span_fidelity_enabled,\n"
        b"        table_evidence_reconciliation_enabled="
        b"context.settings.table_evidence_reconciliation_enabled,\n"
        b"        table_candidate_gate_enabled="
        b"context.settings.table_candidate_gate_enabled,\n"
        b"    )\n",
    )
    safe = _replace_once(
        safe,
        b"    _enrich_ocr_confidence(context.pages, context.image_regions)\n",
        b"    _enrich_ocr_confidence(context.pages, context.image_regions)\n"
        b"    seal_table_pages(\n"
        b"        context.pages,\n"
        b"        context.source_document_identity,\n"
        b"        context.native_texts,\n"
        b"        table_span_fidelity_enabled="
        b"context.settings.table_span_fidelity_enabled,\n"
        b"        table_evidence_reconciliation_enabled="
        b"context.settings.table_evidence_reconciliation_enabled,\n"
        b"        table_candidate_gate_enabled="
        b"context.settings.table_candidate_gate_enabled,\n"
        b"        table_multi_page_merge_enabled="
        b"context.settings.table_multi_page_merge_enabled,\n"
        b"    )\n"
        b"    merge_continued_tables(\n"
        b"        context.pages,\n"
        b"        context.source_document_identity,\n"
        b"        table_span_fidelity_enabled="
        b"context.settings.table_span_fidelity_enabled,\n"
        b"        table_evidence_reconciliation_enabled="
        b"context.settings.table_evidence_reconciliation_enabled,\n"
        b"        table_candidate_gate_enabled="
        b"context.settings.table_candidate_gate_enabled,\n"
        b"        table_multi_page_merge_enabled="
        b"context.settings.table_multi_page_merge_enabled,\n"
        b"    )\n",
    )
    return safe


def test_hardened_scope_authorizes_exact_geometry_and_env_surfaces() -> None:
    authorized = exception._expected_hardened_phase04_authorized_change()

    assert ".env.example" in authorized["allowed_existing_paths"]
    assert "app/services/tables.py" in authorized["allowed_existing_paths"]
    assert authorized["sealed_exact_paths"] == {}
    assert set(authorized["protected_surfaces"]) >= {
        ".env.example",
        "app/services/pipeline.py",
        "app/services/tables.py",
    }
    pipeline = authorized["protected_surfaces"]["app/services/pipeline.py"]
    assert pipeline["broad_helper_function_names"] == sorted(
        exception.EXPECTED_HARDENED_PHASE04_PIPELINE_FUNCTIONS
    )
    assert pipeline["exact_vector_geometry_function_name"] == (
        "_parse_loaded_document"
    )


def test_hardened_env_example_accepts_only_baseline_or_exact_false_suffix() -> None:
    current = (PROJECT_ROOT / ".env.example").read_bytes()
    suffix = exception.EXPECTED_HARDENED_ENV_EXAMPLE_PHASE04_SUFFIX.encode(
        "utf-8"
    )
    baseline = current[: -len(suffix)] if current.endswith(suffix) else current
    candidate = current if current.endswith(suffix) else current + suffix

    assert exception._validate_hardened_phase04_env_example(baseline) == (
        exception.EXPECTED_HARDENED_ENV_EXAMPLE_IDENTITY["sha256"]
    )
    assert exception._validate_hardened_phase04_env_example(
        candidate
    ) == exception.EXPECTED_HARDENED_ENV_EXAMPLE_IDENTITY["sha256"]


def test_hardened_env_example_rejects_broader_or_default_on_changes() -> None:
    current = (PROJECT_ROOT / ".env.example").read_bytes()
    suffix = exception.EXPECTED_HARDENED_ENV_EXAMPLE_PHASE04_SUFFIX.encode(
        "utf-8"
    )
    baseline = current[: -len(suffix)] if current.endswith(suffix) else current
    candidates = (
        baseline
        + suffix.replace(
            b"SPAN_FIDELITY_ENABLED=false",
            b"SPAN_FIDELITY_ENABLED=true",
        ),
        baseline
        + suffix.replace(
            b"PARSER_TABLES_SPAN_FIDELITY_ENABLED=false\n"
            b"PARSER_TABLES_EVIDENCE_RECONCILIATION_ENABLED=false\n",
            b"PARSER_TABLES_EVIDENCE_RECONCILIATION_ENABLED=false\n"
            b"PARSER_TABLES_SPAN_FIDELITY_ENABLED=false\n",
        ),
        baseline + suffix + suffix,
        baseline.replace(
            b"PARSER_LAYOUT_RUNNING_REGIONS_ENABLED=false",
            b"PARSER_LAYOUT_RUNNING_REGIONS_ENABLED=true",
        )
        + suffix,
        baseline + b"PARSER_PHASE05_ENABLED=false\n" + suffix,
    )

    for candidate in candidates:
        with pytest.raises(
            readiness.ReadinessContractError,
            match="env example surface changed",
        ):
            exception._validate_hardened_phase04_env_example(candidate)


def test_hardened_tables_accepts_atomic_baseline_or_reviewed_geometry() -> None:
    current = (PROJECT_ROOT / "app/services/tables.py").read_bytes()
    current_state = exception._validate_hardened_phase04_tables_surface(current)
    geometry = _tables_with_geometry_surface(current)

    assert current_state in {"baseline", "geometry"}
    assert exception._hardened_phase04_tables_digests(geometry) == (
        exception.EXPECTED_HARDENED_TABLES_GEOMETRY_NODE_AST_SHA256
    )
    assert exception._validate_hardened_phase04_tables_surface(geometry) == (
        "geometry"
    )


def test_hardened_tables_rejects_mixed_or_mutated_geometry_vectors() -> None:
    current = (PROJECT_ROOT / "app/services/tables.py").read_bytes()
    current_state = exception._validate_hardened_phase04_tables_surface(current)
    geometry = _tables_with_geometry_surface(current)
    mutations = [
        geometry.replace(
            b"    geometry_inferred: bool | None = None\n",
            b"    geometry_inferred: bool | None = True\n",
            1,
        ),
        geometry.replace(
            b"    preserve_cell_geometry: bool = False,\n",
            b"    preserve_cell_geometry: bool = True,\n",
            1,
        ),
        geometry.replace(
            b"                geometry_row.append(_bbox_dict(coordinates))\n",
            b"                geometry_row.append(_bbox_dict(table.bbox))\n",
            1,
        ),
        geometry.replace(
            b"            candidate.table.geometry_inferred = candidate.inferred\n",
            b"            candidate.table.geometry_inferred = True\n",
            1,
        ),
        geometry.replace(
            b"                preserve_cell_geometry=preserve_cell_geometry,\n",
            b"                preserve_cell_geometry=True,\n",
            1,
        ),
    ]
    if current_state == "baseline":
        mutations.append(
            _replace_top_level_nodes(
                current,
                {"RawTable": _GEOMETRY_RAW_TABLE_SOURCE},
            )
        )
    for mutation in mutations:
        assert mutation != geometry
        with pytest.raises(
            readiness.ReadinessContractError,
            match="table extraction surface changed",
        ):
            exception._validate_hardened_phase04_tables_surface(mutation)


def test_reviewed_geometry_candidate_preserves_default_off_and_source_boxes() -> None:
    candidate = _tables_with_geometry_surface()
    namespace: dict[str, Any] = {"__name__": __name__}
    exec(compile(candidate, "<reviewed-tables-candidate>", "exec"), namespace)
    clean_table = namespace["_clean_table"]

    class ExplodingCellsRow:
        bbox = (10.0, 20.0, 70.0, 40.0)

        @property
        def cells(self) -> object:
            raise AssertionError("default-off path accessed cell geometry")

    class GeometryRow:
        bbox = (10.0, 20.0, 70.0, 40.0)
        cells = (
            (10.0, 20.0, 20.0, 40.0),
            (20.0, 20.0, 60.0, 40.0),
            (60.0, 20.0, 70.0, 40.0),
        )

    class MalformedGeometryRow:
        bbox = (10.0, 20.0, 70.0, 40.0)
        cells = (
            (10.0, 20.0, 20.0, 40.0),
            (20.0, 20.0, float("nan"), 40.0),
            (60.0, 20.0, 70.0, 40.0),
        )

    class FakeTable:
        bbox = (10.0, 20.0, 70.0, 40.0)

        def __init__(self, row: object) -> None:
            self.rows = [row]

        def extract(self, **_kwargs: Any) -> list[list[str]]:
            return [["", "United States", ""]]

    legacy = clean_table(1, FakeTable(ExplodingCellsRow()))
    assert legacy.rows == [["United States"]]
    assert legacy.cell_bboxes == ()
    assert legacy.geometry_inferred is None

    preserved = clean_table(
        1,
        FakeTable(GeometryRow()),
        preserve_cell_geometry=True,
    )
    assert preserved.rows == [["", "United States", ""]]
    assert len(preserved.cell_bboxes) == 1
    assert [box is not None for box in preserved.cell_bboxes[0]] == [
        True,
        True,
        True,
    ]
    assert preserved.cell_bboxes[0][0] == {
        "x": 10.0,
        "y": 20.0,
        "w": 10.0,
        "h": 20.0,
    }
    malformed = clean_table(
        1,
        FakeTable(MalformedGeometryRow()),
        preserve_cell_geometry=True,
    )
    assert malformed.cell_bboxes == ()
    assert "contains_malformed_cell_geometry" in malformed.parse_concerns


def _legacy_hardened_pipeline_accepts_exact_vector_geometry_threading() -> None:
    baseline = (PROJECT_ROOT / "app/services/pipeline.py").read_bytes()
    geometry = _pipeline_with_vector_geometry(baseline)

    exception._validate_hardened_phase04_pipeline_surface(baseline)
    exception._validate_hardened_phase04_pipeline_surface(geometry)
    assert exception._hardened_phase04_pipeline_digests(geometry) == (
        (
            exception
            .EXPECTED_SECOND_ADDITIVE_P04_US01_PIPELINE_MODULE_AST_SHA256
        ),
        (
            exception
            .EXPECTED_SECOND_ADDITIVE_P04_US01_PIPELINE_FUNCTION_AST_SHA256
        ),
    )


def _legacy_hardened_pipeline_rejects_nonexact_vector_geometry_threading() -> None:
    geometry = _pipeline_with_vector_geometry()
    mutations = (
        geometry.replace(
            b"            if settings.table_span_fidelity_enabled\n",
            b"            if settings.layout_running_regions_enabled\n",
            1,
        ),
        geometry.replace(
            b"                preserve_cell_geometry=True,\n",
            b"                True,\n",
            1,
        ),
        geometry.replace(
            b"            else extract_vector_tables(loaded.processing_bytes)\n",
            b"            else extract_vector_tables(\n"
            b"                loaded.processing_bytes, preserve_cell_geometry=True\n"
            b"            )\n",
            1,
        ),
        geometry.replace(
            b"        if loaded.kind is InputKind.PDF\n",
            b"        if loaded.kind is InputKind.IMAGE\n",
            1,
        ),
        geometry.replace(
            b"                loaded.processing_bytes,\n",
            b"                loaded.original_bytes,\n",
            1,
        ),
    )
    for mutation in mutations:
        assert mutation != geometry
        with pytest.raises(
            readiness.ReadinessContractError,
            match="vector extraction block differs|pipeline surface changed",
        ):
            exception._validate_hardened_phase04_pipeline_surface(mutation)


def _legacy_hardened_pipeline_accepts_only_complete_table_repair_vectors() -> None:
    bounded = (PROJECT_ROOT / "app/services/pipeline.py").read_bytes()
    baseline = _pipeline_with_baseline_table_repair(bounded)

    exception._validate_hardened_phase04_pipeline_surface(baseline)
    exception._validate_hardened_phase04_pipeline_surface(bounded)
    assert exception._hardened_phase04_pipeline_digests(bounded) == (
        (
            exception
            .EXPECTED_SECOND_ADDITIVE_P04_US01_PIPELINE_MODULE_AST_SHA256
        ),
        (
            exception
            .EXPECTED_SECOND_ADDITIVE_P04_US01_PIPELINE_FUNCTION_AST_SHA256
        ),
    )
    baseline_tree = ast.parse(baseline.decode("utf-8"))
    bounded_tree = ast.parse(bounded.decode("utf-8"))
    assert (
        exception._normalize_hardened_pipeline_table_repair(baseline_tree)
        == "baseline"
    )
    assert (
        exception._normalize_hardened_pipeline_table_repair(bounded_tree)
        == "second_additive"
    )


def test_second_additive_pipeline_vector_preserves_sealed_candidate() -> None:
    sealed = exception.EXPECTED_HARDENED_PIPELINE_TABLE_REPAIR_CANDIDATE_AST_SHA256
    additive = exception.EXPECTED_SECOND_ADDITIVE_PIPELINE_TABLE_REPAIR_AST_SHA256

    assert sealed == {
        "_table_repair_page_indexes": (
            "34f041477ed512904fd07dcb83bc40b2f9f881d4e60c0a69b4c42bb0a1df78f7"
        ),
        "_extract_table_repair_words": (
            "ae612114c5c64d9781267748a957b87615965b54843be534263f1bd84af5cbf5"
        ),
        "_parse_loaded_document.table_repair_words": (
            "b64e9e17c9c30631a5e29f11691154dc4ab133d49b79fbde811cb447c758b1e9"
        ),
    }
    assert set(additive) == set(sealed)
    assert additive["_table_repair_page_indexes"] == sealed[
        "_table_repair_page_indexes"
    ]
    assert additive["_parse_loaded_document.table_repair_words"] == sealed[
        "_parse_loaded_document.table_repair_words"
    ]
    assert additive["_extract_table_repair_words"] != sealed[
        "_extract_table_repair_words"
    ]


def _legacy_hardened_pipeline_rejects_mixed_table_repair_vectors() -> None:
    bounded = (PROJECT_ROOT / "app/services/pipeline.py").read_bytes()
    baseline = _pipeline_with_baseline_table_repair(bounded)
    mixed = _replace_top_level_nodes(
        bounded,
        {
            "_table_repair_page_indexes": (
                exception.EXPECTED_HARDENED_PIPELINE_TABLE_REPAIR_BASELINE_PAGE_INDEX_SOURCE
            )
        },
    )
    baseline_try = indent(
        exception.EXPECTED_HARDENED_PIPELINE_TABLE_REPAIR_BASELINE_TRY_SOURCE,
        "    ",
    ).encode("utf-8")
    candidate_try = indent(
        exception.EXPECTED_HARDENED_PIPELINE_TABLE_REPAIR_CANDIDATE_TRY_SOURCE,
        "    ",
    ).encode("utf-8")
    try_only_mixed = _replace_once(bounded, candidate_try, baseline_try)

    for candidate in (mixed, try_only_mixed):
        with pytest.raises(
            readiness.ReadinessContractError,
            match="table repair surface changed",
        ):
            exception._validate_hardened_phase04_pipeline_surface(candidate)
    assert baseline != mixed


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (b"time.perf_counter() + 5.0", b"time.perf_counter() + 50.0"),
        (b"current_time + 0.5", b"current_time + 5.0"),
        (b"page_word_count > 16_384", b"page_word_count > 16_385"),
        (
            b"total_word_count + page_word_count > 65_536",
            b"total_word_count + page_word_count > 65_537",
        ),
        (b"source_text_bytes > 8_388_608", b"False"),
        (b"len(text) > 16_384", b"len(text) > 16_385"),
        (b"if type(words) is not list", b"if not isinstance(words, list)"),
        (
            b"ord(character) < 32 or ord(character) == 127",
            b"False",
        ),
        (b'word.get("x0")', b'word.get("x")'),
        (b"keep_blank_chars=False", b"keep_blank_chars=True"),
        (b'extra_attrs=["fontname"]', b'extra_attrs=[]'),
        (b"len(fontname) > 256", b"len(fontname) > 257"),
        (
            b'"bold": "bold" in fontname.casefold(),',
            b'"bold": bool(fontname),',
        ),
        (
            b"if not table_span_fidelity_enabled:\n",
            b"if not settings.table_span_fidelity_enabled:\n",
        ),
        (b'tables = raw.get("tables")', b'tables = raw.get("body")'),
    ],
)
def _legacy_hardened_pipeline_rejects_table_repair_bound_or_semantic_drift(
    old: bytes,
    new: bytes,
) -> None:
    bounded = (PROJECT_ROOT / "app/services/pipeline.py").read_bytes()
    assert old in bounded
    changed = bounded.replace(old, new, 1)

    with pytest.raises(
        readiness.ReadinessContractError,
        match="table repair surface changed",
    ):
        exception._validate_hardened_phase04_pipeline_surface(changed)


def test_hardened_pipeline_rejects_duplicate_or_nested_table_repair_nodes() -> None:
    bounded = (PROJECT_ROOT / "app/services/pipeline.py").read_bytes()
    page_source = (
        exception.EXPECTED_HARDENED_PIPELINE_TABLE_REPAIR_BASELINE_PAGE_INDEX_SOURCE
    )
    duplicate = bounded + ("\n" + page_source).encode("utf-8")
    nested = bounded + ("\ndef outer_probe():\n" + indent(page_source, "    ")).encode(
        "utf-8"
    )

    for candidate in (duplicate, nested):
        with pytest.raises(
            readiness.ReadinessContractError,
            match="table repair node set differs",
        ):
            exception._validate_hardened_phase04_pipeline_surface(candidate)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (
            "settings.table_span_fidelity_enabled",
            "settings.layout_running_regions_enabled",
        ),
        ("loaded.processing_bytes", "loaded.original_bytes"),
        ("type(exc).__name__", "str(exc)"),
    ],
)
def _legacy_hardened_pipeline_rejects_table_repair_caller_custody_drift(
    old: str,
    new: str,
) -> None:
    pipeline = (PROJECT_ROOT / "app/services/pipeline.py").read_bytes()
    candidate_source = (
        exception.EXPECTED_HARDENED_PIPELINE_TABLE_REPAIR_CANDIDATE_TRY_SOURCE
    )
    assert candidate_source.count(old) == 1
    changed_source = candidate_source.replace(old, new, 1)
    candidate = indent(candidate_source, "    ").encode("utf-8")
    changed = indent(changed_source, "    ").encode("utf-8")
    mutation = _replace_once(pipeline, candidate, changed)

    with pytest.raises(
        readiness.ReadinessContractError,
        match="table repair surface changed",
    ):
        exception._validate_hardened_phase04_pipeline_surface(mutation)


def _legacy_hardened_pipeline_accepts_only_constrained_table_helper_glue() -> None:
    pipeline = (PROJECT_ROOT / "app/services/pipeline.py").read_bytes()
    safe = _all_four_story_pipeline_glue(pipeline)
    assert (
        b"from app.services.table_semantics import reconcile_table_candidates"
        in safe
    )
    assert b"merged = reconcile_table_candidates(\n" in safe
    exception._validate_hardened_phase04_pipeline_surface(safe)


def _legacy_hardened_pipeline_accepts_existing_page_word_evidence() -> None:
    pipeline = (PROJECT_ROOT / "app/services/pipeline.py").read_bytes()
    safe = _all_four_story_pipeline_glue(pipeline)
    assert b"raw_item = prepare_docling_table_input(\n" in safe
    assert b"        page_words_by_page,\n" in safe
    exception._validate_hardened_phase04_pipeline_surface(safe)


def _legacy_hardened_pipeline_accepts_all_four_story_glue_shapes() -> None:
    pipeline = (PROJECT_ROOT / "app/services/pipeline.py").read_bytes()
    safe = _all_four_story_pipeline_glue(pipeline)
    exception._validate_hardened_phase04_pipeline_surface(safe)


def _legacy_hardened_pipeline_rejects_forced_on_table_binding() -> None:
    pipeline = (PROJECT_ROOT / "app/services/pipeline.py").read_bytes()
    safe = _all_four_story_pipeline_glue(pipeline)
    changed = _replace_once(
        safe,
        b"        table_evidence_reconciliation_enabled="
        b"table_evidence_reconciliation_enabled,\n",
        b"        table_evidence_reconciliation_enabled=True,\n",
    )
    with pytest.raises(
        readiness.ReadinessContractError,
        match="helper argument differs",
    ):
        exception._validate_hardened_phase04_pipeline_surface(changed)


def _legacy_hardened_pipeline_rejects_unlisted_project_import() -> None:
    pipeline = (PROJECT_ROOT / "app/services/pipeline.py").read_bytes()
    needle = b"    merged: dict[int, list[dict[str, Any]]] = defaultdict(list)\n"
    changed = pipeline.replace(
        needle,
        (
            b"    from app.services.unlisted_phase04_helper import "
            b"mutate_table\n"
            + b"    mutate_table()\n"
            + needle
        ),
        1,
    )
    assert changed != pipeline
    with pytest.raises(readiness.ReadinessContractError, match="import differs"):
        exception._validate_hardened_phase04_pipeline_surface(changed)


def test_hardened_pipeline_rejects_arbitrary_allowed_function_mutation() -> None:
    pipeline = (PROJECT_ROOT / "app/services/pipeline.py").read_bytes()
    exception._validate_hardened_phase04_pipeline_surface(pipeline)
    changed = pipeline.replace(
        b"    page_indexes = set(docling_tables) | set(vector_tables)\n",
        b"    page_indexes = {1}\n",
        1,
    )
    assert changed != pipeline
    with pytest.raises(
        readiness.ReadinessContractError,
        match="surface changed|table repair block differs",
    ):
        exception._validate_hardened_phase04_pipeline_surface(changed)


def test_hardened_pipeline_rejects_merge_body_items_mutation() -> None:
    pipeline = (PROJECT_ROOT / "app/services/pipeline.py").read_bytes()
    exception._validate_hardened_phase04_pipeline_surface(pipeline)
    changed = pipeline.replace(
        b"        page_tables = [dict(item) for item in tables.get(page_index, [])]\n",
        b"        page_tables = []\n",
        1,
    )
    assert changed != pipeline
    with pytest.raises(
        readiness.ReadinessContractError,
        match="surface changed|table repair block differs",
    ):
        exception._validate_hardened_phase04_pipeline_surface(changed)


def test_hardened_pipeline_rejects_running_region_glue() -> None:
    pipeline = (PROJECT_ROOT / "app/services/pipeline.py").read_bytes()
    needle = b"    merged: dict[int, list[dict[str, Any]]] = defaultdict(list)\n"
    changed = pipeline.replace(
        needle,
        (
            b"    from app.services.table_semantics import "
            b"reconcile_table_candidates\n"
            + needle
            + b"    merged = reconcile_table_candidates(\n"
            + b"        merged, running_region_mode=False\n"
            + b"    )\n"
        ),
        1,
    )
    assert changed != pipeline
    with pytest.raises(readiness.ReadinessContractError):
        exception._validate_hardened_phase04_pipeline_surface(changed)


@pytest.mark.parametrize(
    "source",
    [
        "P05 = 1\n",
        "p05 = 'p05'\n",
        "P_0_5 = 1\n",
        "phase_0_5_enabled = True\n",
        "phase05Enabled = True\n",
        "tablephase05enabled = True\n",
        "TABLEPHASE05ENABLED = True\n",
        "runningRegion = True\n",
        "runningregions = True\n",
        "runningregionenabled = True\n",
        "runningregionsenabled = True\n",
        "tablerunningregionenabled = True\n",
        "TABLERUNNINGREGIONSENABLED = True\n",
        "running_Regions = True\n",
        "table_runningRegion_enabled = True\n",
        "scope = 'Running - Regions'\n",
    ],
)
def test_hardened_common_scope_rejects_phase05_and_running_region_variants(
    source: str,
) -> None:
    with pytest.raises(readiness.ReadinessContractError, match="scope differs"):
        exception._reject_phase04_scope_tokens(
            ast.parse(source),
            tokens=exception.FORBIDDEN_PHASE04_SCOPE_TOKENS,
            label="Phase 04 common probe",
        )


def test_hardened_common_scope_boundary_avoids_unrelated_words_and_phase04(
) -> None:
    safe = ast.parse(
        "phase04Enabled = True\n"
        "P04 = 'Phase 04'\n"
        "metaphase05 = 1\n"
        "notp05 = 1\n"
        "outrunningRegions = True\n"
        "runningRegional = True\n"
    )
    exception._reject_phase04_scope_tokens(
        safe,
        tokens=exception.FORBIDDEN_PHASE04_SCOPE_TOKENS,
        label="Phase 04 common probe",
    )


@pytest.mark.parametrize(
    "module_statement",
    [
        "P05 = 'blocked'\n\n",
        "runningRegion = 'blocked'\n\n",
        "PHASE_LABEL = 'Phase ' + '05'\n\n",
        "PHASE_CODE = 'P' + '05'\n\n",
        "REGION_MODE = 'running' + 'Region'\n\n",
        "REGION_LIST = 'running' + '_regions'\n\n",
        "PHASE_MULTIPLIED = 'P' * 1 + '05'\n\n",
        "PHASE_PARTS = ['P', '05']\n\n",
        "PHASE_KEYS = {'Phase ': 0, '05': 1}\n\n",
        "PHASE_VALUES = {'left': 'Phase ', 'right': '05'}\n\n",
        "PHASE_SET = {'Phase ', '05'}\n\n",
        "PHASE_SET_REVERSED = {'05', 'Phase '}\n\n",
        "PHASE_FORMATTED = f'Phase {5}'\n\n",
        "PHASE_PADDED = f'Phase {5:02d}'\n\n",
        "REGION_FORMATTED = f\"run{'ningRegion'}\"\n\n",
        "FIRST = 'Ph'\nSECOND = 'ase05'\nPHASE_ALIAS = FIRST + SECOND\n\n",
        "RUN = 'run'\nREGION = 'ningRegion'\nREGION_ALIAS = RUN + REGION\n\n",
        "PHASE_PERCENT = 'Phase %02d' % 5\n\n",
        "PHASE_FORMAT = 'Ph{}se05'.format('a')\n\n",
        "PHASE_REPLACE = 'Phxase05'.replace('x', '')\n\n",
        "PHASE_REVERSED = ''.join(reversed(['05', 'Phase ']))\n\n",
        "PHASE_SORTED = ''.join(sorted(['ase05', 'Ph']))\n\n",
        "PHASE_BYTES = b'P05'.decode()\n\n",
        "PHASE_STR = 'Phase ' + str(5)\n\n",
        "PHASE_CHR = chr(80) + chr(48) + chr(53)\n\n",
        "PHASE_IF = ('Ph' if object() else 'Ph') + 'ase05'\n\n",
        "PHASE_WALRUS = (FIRST := 'Ph') + 'ase05'\n\n",
        "PHASE_THREE_SET = {'Ph', 'ase', '05'}\n\n",
        "REGION_THREE_SET = {'run', 'ning', 'Region'}\n\n",
    ],
)
def test_hardened_table_semantics_module_rejects_boundary_scope_variables(
    module_statement: str,
) -> None:
    changed = _valid_table_semantics_source(module_body=module_statement)
    with pytest.raises(readiness.ReadinessContractError, match="scope differs"):
        exception._validate_table_semantics_module(changed)


@pytest.mark.parametrize(
    "source",
    [
        "scope = f'Phase {5}'\n",
        "scope = f'Phase {5:02d}'\n",
        "scope = f\"run{'ningRegion'}\"\n",
        "left = 'Ph'\nright = 'ase05'\nscope = left + right\n",
        "left: str = 'run'\nright = 'ningRegion'\nscope = left + right\n",
        "scope = 'Phase %02d' % 5\n",
        "scope = 'Ph{}se05'.format('a')\n",
        "scope = 'Phxase05'.replace('x', '')\n",
        "scope = ''.join(reversed(['05', 'Phase ']))\n",
        "scope = ''.join(sorted(['ase05', 'Ph']))\n",
        "scope = b'P05'.decode()\n",
        "scope = 'Phase ' + str(5)\n",
        "scope = chr(80) + chr(48) + chr(53)\n",
        "scope = ('Ph' if object() else 'Ph') + 'ase05'\n",
        "scope = (left := 'Ph') + 'ase05'\n",
        "scope = {'Ph', 'ase', '05'}\n",
        "scope = {'run', 'ning', 'Region'}\n",
        "scope = {'Ph': 'ase05'}\n",
        "scope = f'Phase {10 // 2}'\n",
        "scope = f'P{10 // 2:02d}'\n",
        "scope = f'Phase {len(\"abcde\")}'\n",
        "scope = 'Phase ' + str(10 // 2)\n",
        "scope = '50P'[::-1]\n",
        "scope = ''.join(reversed('50P'))\n",
        "scope = bytes([80, 48, 53]).decode()\n",
        "scope = bytes.fromhex('503035').decode()\n",
    ],
)
def test_hardened_common_scope_rejects_static_reconstruction(
    source: str,
) -> None:
    with pytest.raises(readiness.ReadinessContractError, match="scope differs"):
        exception._reject_phase04_scope_tokens(
            ast.parse(source),
            tokens=exception.FORBIDDEN_PHASE04_SCOPE_TOKENS,
            label="Phase 04 common probe",
        )


@pytest.mark.parametrize(
    "source",
    [
        "scope = f'Phase {4:02d}'\n",
        "left = 'Ph'\nright = 'ase04'\nscope = left + right\n",
        "scope = {'Phase ', '04'}\n",
        "scope = 'metaphase05'\n",
        "scope = 'outrunningRegions'\n",
    ],
)
def test_hardened_common_scope_allows_phase04_and_boundary_controls(
    source: str,
) -> None:
    exception._reject_phase04_scope_tokens(
        ast.parse(source),
        tokens=exception.FORBIDDEN_PHASE04_SCOPE_TOKENS,
        label="Phase 04 common probe",
    )


@pytest.mark.parametrize(
    "replay_body",
    [
        "    table['scope'] = f'Phase {10 // 2}'\n",
        "    table['scope'] = f'P{10 // 2:02d}'\n",
        "    table['scope'] = f'Phase {len(\"abcde\")}'\n",
        "    table['scope'] = f'Phase {sum([2, 3])}'\n",
        "    table['scope'] = '50P'[::-1]\n",
        "    table['scope'] = ''.join(reversed('50P'))\n",
        "    table['scope'] = bytes([80, 48, 53]).decode()\n",
        "    table['scope'] = bytes.fromhex('503035').decode()\n",
        "    table['scope'] = 'xrunningRegion'.strip('x')\n",
        "    table['scope'] = 'metaphase05'.strip('meta')\n",
        "    table['scope'] = 'xrunningRegion'.split('x')[1]\n",
    ],
)
def test_hardened_table_semantics_rejects_runtime_scope_reconstruction(
    replay_body: str,
) -> None:
    with pytest.raises(readiness.ReadinessContractError, match="scope differs"):
        exception._validate_table_semantics_module(
            _valid_table_semantics_source(replay_body=replay_body)
        )


def test_hardened_table_semantics_rejects_stdlib_scope_transforms() -> None:
    regex_source = _with_table_regex_imports(
        _valid_table_semantics_source(
            replay_body="    table['scope'] = sub('meta', '', 'metaphase05')\n"
        )
    )
    normalized_source = _valid_table_semantics_source(
        extra_import="from unicodedata import normalize\n",
        replay_body=(
            "    table['scope'] = normalize('NFKC', 'ｐｈａｓｅ０５')\n"
        ),
    )
    for source in (regex_source, normalized_source):
        with pytest.raises(readiness.ReadinessContractError, match="scope differs"):
            exception._validate_table_semantics_module(source)

    aliased_regex = _with_table_regex_imports(
        _valid_table_semantics_source(
            replay_body=(
                "    prefix = 'meta'\n"
                "    label = 'metaphase05'\n"
                "    table['scope'] = sub(prefix, '', label)\n"
            )
        )
    )
    with pytest.raises(readiness.ReadinessContractError, match="scope differs"):
        exception._validate_table_semantics_module(aliased_regex)


@pytest.mark.parametrize(
    "source",
    [
        "scope = 'ab' * 65536\n",
        "scope = f'{5:100000000d}'\n",
        "scope = f'Phase {1 << 1000000000}'\n",
        "scope = ('a' * 1000).replace('', 'b' * 1000)\n",
        "scope = '%100000000d' % 5\n",
        "scope = '%*s' % (1000000000, 'x')\n",
        "scope = '{:100000000d}'.format(5)\n",
        "scope = '{0:{1}}'.format('x', 1000000000)\n",
        "scope = f\"{table.get('value', ''):65537}\"\n",
    ],
)
def test_hardened_common_scope_preflights_static_allocation(
    source: str,
) -> None:
    with pytest.raises(readiness.ReadinessContractError):
        exception._reject_phase04_scope_tokens(
            ast.parse(source),
            tokens=exception.FORBIDDEN_PHASE04_SCOPE_TOKENS,
            label="Phase 04 common probe",
        )


def test_hardened_common_scope_preflights_split_expansion() -> None:
    source = "scope = " + repr("x " * 300) + ".split()\n"
    with pytest.raises(readiness.ReadinessContractError):
        exception._reject_phase04_scope_tokens(
            ast.parse(source),
            tokens=exception.FORBIDDEN_PHASE04_SCOPE_TOKENS,
            label="Phase 04 common probe",
        )


def _phase04_rebindings(name: str, expressions: list[str]) -> str:
    return "".join(
        f"{name} = {expression}\n" for expression in expressions
    )


_PHASE04_AGGREGATE_SCOPE_EXPANSIONS = (
    (
        _phase04_rebindings("text", [repr(f"x{index}") for index in range(17)])
        + _phase04_rebindings("count", [str(index) for index in range(1, 18)])
        + "scope = text * count\n"
    ),
    (
        _phase04_rebindings(
            "template", [repr(f"%s-{index}") for index in range(17)]
        )
        + _phase04_rebindings(
            "scalar", [repr(f"value-{index}") for index in range(17)]
        )
        + "scope = template % scalar\n"
    ),
    (
        _phase04_rebindings("number", [str(index) for index in range(17)])
        + _phase04_rebindings(
            "specification", [repr(f"0{index}d") for index in range(17)]
        )
        + "scope = f'{number:{specification}}'\n"
    ),
    (
        _phase04_rebindings(
            "receiver", [repr(f"x{index}value") for index in range(17)]
        )
        + _phase04_rebindings(
            "characters", [repr(f"z{index}") for index in range(17)]
        )
        + "scope = receiver.strip(characters)\n"
    ),
    (
        _phase04_rebindings(
            "receiver", [repr(f"a{index},b") for index in range(17)]
        )
        + _phase04_rebindings(
            "separator", [repr(f"z{index}") for index in range(17)]
        )
        + "scope = receiver.split(separator)\n"
    ),
    (
        _phase04_rebindings(
            "receiver", [repr(f"alpha-{index}") for index in range(5)]
        )
        + _phase04_rebindings("old", [repr(f"q{index}") for index in range(4)])
        + _phase04_rebindings("new", [repr(f"n{index}") for index in range(4)])
        + _phase04_rebindings("count", [str(index) for index in range(4)])
        + "scope = receiver.replace(old, new, count)\n"
    ),
    (
        _phase04_rebindings("left", [str(index) for index in range(1, 18)])
        + _phase04_rebindings("right", [str(index) for index in range(17)])
        + "scope = str(left << right)\n"
    ),
    (
        _phase04_rebindings(
            "receiver", [repr(f"abcdef-{index}") for index in range(17)]
        )
        + _phase04_rebindings("index", [str(index) for index in range(17)])
        + "scope = receiver[index]\n"
    ),
    (
        _phase04_rebindings(
            "receiver", [repr(f"abcdef-{index}") for index in range(5)]
        )
        + _phase04_rebindings("lower", [str(index) for index in range(4)])
        + _phase04_rebindings("upper", [str(index + 4) for index in range(4)])
        + _phase04_rebindings("step", [str(index + 1) for index in range(4)])
        + "scope = receiver[lower:upper:step]\n"
    ),
)


@pytest.mark.parametrize("source", _PHASE04_AGGREGATE_SCOPE_EXPANSIONS)
def test_hardened_common_scope_rejects_aggregate_static_expansion(
    source: str,
) -> None:
    with pytest.raises(readiness.ReadinessContractError):
        exception._reject_phase04_scope_tokens(
            ast.parse(source),
            tokens=exception.FORBIDDEN_PHASE04_SCOPE_TOKENS,
            label="Phase 04 common probe",
        )


_PHASE04_LEGACY_VARIANT_EXPANSIONS = (
    _phase04_rebindings(
        "choice", [repr(f"value-{index}") for index in range(257)]
    )
    + "scope = str(choice)\n",
    "scope = " + repr([f"value-{index}" for index in range(257)]) + "\n",
    "scope = " + " or ".join(repr(f"value-{index}") for index in range(257)) + "\n",
    "scope = bytes([" + ", ".join("65" for _ in range(257)) + "]).decode()\n",
    _phase04_rebindings(
        "choice", [repr(f"value-{index}") for index in range(256)]
    )
    + "scope = [choice]\n",
)


@pytest.mark.parametrize("source", _PHASE04_LEGACY_VARIANT_EXPANSIONS)
def test_hardened_common_scope_rejects_legacy_variant_expansion(
    source: str,
) -> None:
    with pytest.raises(readiness.ReadinessContractError):
        exception._reject_phase04_scope_tokens(
            ast.parse(source),
            tokens=exception.FORBIDDEN_PHASE04_SCOPE_TOKENS,
            label="Phase 04 common probe",
        )


def test_hardened_common_scope_node_limit_is_exact_and_precedes_evaluation(
) -> None:
    exact = ast.Module(
        body=[ast.Pass() for _ in range(8_191)],
        type_ignores=[],
    )
    exception._reject_phase04_scope_tokens(
        exact,
        tokens=exception.FORBIDDEN_PHASE04_SCOPE_TOKENS,
        label="Phase 04 common probe",
    )

    overflow = ast.Module(
        body=[ast.Pass() for _ in range(8_192)],
        type_ignores=[],
    )
    with pytest.raises(
        readiness.ReadinessContractError,
        match="syntax resource differs",
    ):
        exception._reject_phase04_scope_tokens(
            overflow,
            tokens=exception.FORBIDDEN_PHASE04_SCOPE_TOKENS,
            label="Phase 04 common probe",
        )


def test_hardened_pipeline_rejects_dynamic_import() -> None:
    pipeline = (PROJECT_ROOT / "app/services/pipeline.py").read_bytes()
    exception._validate_hardened_phase04_pipeline_surface(pipeline)
    needle = b"    merged: dict[int, list[dict[str, Any]]] = defaultdict(list)\n"
    changed = pipeline.replace(
        needle,
        b'    __import__("app.services.unlisted_phase04_helper")\n' + needle,
        1,
    )
    assert changed != pipeline
    with pytest.raises(
        readiness.ReadinessContractError,
        match="surface changed|table repair block differs",
    ):
        exception._validate_hardened_phase04_pipeline_surface(changed)


def test_hardened_pipeline_current_table_partition_is_exact() -> None:
    pipeline = (PROJECT_ROOT / "app/services/pipeline.py").read_bytes()
    tree = ast.parse(pipeline.decode("utf-8"))
    assert exception._normalize_hardened_pipeline_table_repair(tree) == (
        "second_additive"
    )
    assert exception._validate_hardened_phase04_pipeline_surface(pipeline) == (
        "second_additive"
    )

    old = b"table_repair_warning_type"
    assert old in pipeline
    changed = pipeline.replace(old, b"table_repair_warning_kind", 1)
    with pytest.raises(
        readiness.ReadinessContractError,
        match="table repair block differs|surface changed",
    ):
        exception._validate_hardened_phase04_pipeline_surface(changed)


def _legacy_hardened_pipeline_rejects_side_effectful_helper_argument() -> None:
    pipeline = (PROJECT_ROOT / "app/services/pipeline.py").read_bytes()
    safe = _all_four_story_pipeline_glue(pipeline)
    changed = _replace_once(
        safe,
        b"        vector_tables,\n"
        b"        table_span_fidelity_enabled=table_span_fidelity_enabled,\n",
        b"        load_evidence(),\n"
        b"        table_span_fidelity_enabled=table_span_fidelity_enabled,\n",
    )
    with pytest.raises(
        readiness.ReadinessContractError,
        match="helper argument differs",
    ):
        exception._validate_hardened_phase04_pipeline_surface(changed)


@pytest.mark.parametrize(
    "replacement",
    [
        b"        docling_tables.side_effect,\n",
        b"        docling_tables.__class__,\n",
        b"        open,\n",
        b"        context,\n",
    ],
)
def _legacy_hardened_pipeline_rejects_nonexact_helper_arguments(
    replacement: bytes,
) -> None:
    pipeline = _all_four_story_pipeline_glue(
        (PROJECT_ROOT / "app/services/pipeline.py").read_bytes()
    )
    changed = _replace_once(
        pipeline,
        b"        merged,\n"
        b"        docling_tables,\n"
        b"        vector_tables,\n",
        b"        merged,\n" + replacement + b"        vector_tables,\n",
    )
    with pytest.raises(readiness.ReadinessContractError):
        exception._validate_hardened_phase04_pipeline_surface(changed)


def _legacy_hardened_pipeline_does_not_strip_table_keyword_from_unrelated_call() -> None:
    pipeline = (PROJECT_ROOT / "app/services/pipeline.py").read_bytes()
    changed = _replace_once(
        pipeline,
        b"        page_docling = [dict(item) for item in "
        b"docling_tables.get(page_index, [])]\n",
        b"        page_docling = [\n"
        b"            dict(item, table_span_fidelity_enabled=False)\n"
        b"            for item in docling_tables.get(page_index, [])\n"
        b"        ]\n",
    )
    with pytest.raises(readiness.ReadinessContractError, match="keyword argument"):
        exception._validate_hardened_phase04_pipeline_surface(changed)


def _legacy_hardened_pipeline_rejects_arbitrary_table_named_helper() -> None:
    pipeline = (PROJECT_ROOT / "app/services/pipeline.py").read_bytes()
    needle = b"    merged: dict[int, list[dict[str, Any]]] = defaultdict(list)\n"
    changed = _replace_once(
        pipeline,
        needle,
        b"    from app.services.table_semantics import mutate_table\n"
        b"    mutate_table()\n"
        + needle,
    )
    with pytest.raises(readiness.ReadinessContractError, match="helper import"):
        exception._validate_hardened_phase04_pipeline_surface(changed)


def _legacy_hardened_source_alignment_accepts_only_exact_trailing_replay_hook() -> None:
    source = (PROJECT_ROOT / "app/services/source_text_alignment.py").read_bytes()
    anchor = b'    table["csv"] = _table_csv(rows)\n'
    hooked = source.replace(
        anchor,
        anchor + exception.EXPECTED_HARDENED_SOURCE_ALIGNMENT_HOOK.encode("utf-8"),
        1,
    )
    assert hooked != source
    exception._hardened_source_alignment_digests(hooked)

    unauthorized = source.replace(
        b'    table["rows"] = rows\n',
        b'    table["rows"] = []\n',
        1,
    )
    with pytest.raises(readiness.ReadinessContractError, match="custody differs"):
        exception._hardened_source_alignment_digests(unauthorized)


def _legacy_hardened_text_reconciliation_accepts_only_exact_marked_hook() -> None:
    source = (PROJECT_ROOT / "app/services/text_reconciliation.py").read_bytes()
    anchor = b") -> None:\n"
    function_start = source.index(b"def _ir_replace_owner_text(")
    insertion = source.index(anchor, function_start) + len(anchor)
    hooked = (
        source[:insertion]
        + exception.EXPECTED_HARDENED_TEXT_RECONCILIATION_HOOK.encode("utf-8")
        + source[insertion:]
    )
    exception._hardened_text_reconciliation_digests(hooked)

    unauthorized = source.replace(
        b"    owner.value = replace(owner.value)\n",
        b'    owner.value = "unauthorized"\n',
        1,
    )
    with pytest.raises(readiness.ReadinessContractError, match="custody differs"):
        exception._hardened_text_reconciliation_digests(unauthorized)


def test_hardened_table_semantics_scanner_allows_bounded_deadline_clock() -> None:
    exception._validate_table_semantics_module(_all_public_table_semantics_source())


def test_hardened_table_semantics_ast_ceiling_fails_closed() -> None:
    source = (PROJECT_ROOT / "app/services/table_semantics.py").read_bytes()
    tree = ast.parse(source.decode("utf-8"))
    assert sum(1 for _ in ast.walk(tree)) == 34_865
    assert 34_865 < exception.EXPECTED_TABLE_SEMANTICS_MAX_AST_NODES
    exception._validate_table_semantics_module(source)

    changed = source.replace(
        b"def _table_text_has_unsafe_control(",
        b"def _table_text_has_unsafe_controls(",
        1,
    )
    assert changed != source
    with pytest.raises(
        readiness.ReadinessContractError,
        match="second-additive P04-US01 table semantics vector differs",
    ):
        exception._validate_table_semantics_module(changed)

    above_ceiling = b"table_probe = 0\n" * 10_000
    assert sum(1 for _ in ast.walk(ast.parse(above_ceiling))) == 40_001
    with pytest.raises(
        readiness.ReadinessContractError,
        match="syntax resource differs",
    ):
        exception._validate_table_semantics_module(above_ceiling)


def _plain_table_helpers() -> dict[str, Any]:
    namespace: dict[str, Any] = {}
    source = (
        "from copy import deepcopy\n"
        "from math import isfinite\n"
        "from time import perf_counter\n\n"
        + exception.EXPECTED_TABLE_SEMANTICS_BOUNDED_ITERABLE_SOURCE
        + "\n"
        + exception.EXPECTED_TABLE_SEMANTICS_BOUNDED_TEXT_SOURCE
        + "\n"
        + exception.EXPECTED_TABLE_SEMANTICS_DEADLINE_CHECK_SOURCE
        + "\n"
        + exception.EXPECTED_TABLE_SEMANTICS_PLAIN_ASSERT_SOURCE
        + "\n"
        + exception.EXPECTED_TABLE_SEMANTICS_PLAIN_VALUE_SOURCE
    )
    exec(source, namespace)
    return namespace


def _plain_table_value_validator() -> Any:
    namespace = _plain_table_helpers()
    validate = namespace["_validate_plain_table_value"]
    return lambda value: validate(value, namespace["perf_counter"]() + 5.0)


def _plain_table_value_assertion() -> Any:
    namespace = _plain_table_helpers()
    validate = namespace["_assert_plain_table_value"]
    return lambda value: validate(value, namespace["perf_counter"]() + 5.0)


def test_hardened_table_semantics_plain_value_accepts_exact_64_mib_aggregate() -> None:
    validate = _plain_table_value_validator()
    one_mib = b"x" * 1_048_576
    # The list costs 1,088 bytes and 64 bytes objects cost 4,096 bytes,
    # leaving 1,043,392 payload bytes after 63 one-MiB entries.
    final_payload = b"y" * 1_043_392
    value = [one_mib] * 63 + [final_payload]

    assert validate(value) == value


def test_hardened_table_semantics_plain_value_rejects_64_mib_plus_one() -> None:
    validate = _plain_table_value_validator()
    one_mib = b"x" * 1_048_576
    final_payload = b"y" * 1_043_393
    value = [one_mib] * 63 + [final_payload]

    with pytest.raises(ValueError, match="aggregate byte limit exceeded"):
        validate(value)


def test_hardened_table_semantics_plain_value_counts_large_ints() -> None:
    validate = _plain_table_value_validator()
    shared = 1 << (8 * 16_320 - 1)
    exact_tail = 1 << (8 * 81_792 - 1)
    exact = [shared] * 4_095 + [exact_tail]

    assert validate(exact) == exact

    over_tail = 1 << (8 * 81_792)
    over = [shared] * 4_095 + [over_tail]
    with pytest.raises(ValueError, match="aggregate byte limit exceeded"):
        validate(over)


def test_hardened_table_semantics_plain_value_preserves_predecessor_dag_alias(
) -> None:
    rows = [["A", "B"]]
    predecessor = {"rows": rows, "value": rows}

    copied = _plain_table_value_validator()(predecessor)

    assert copied == predecessor
    assert copied is not predecessor
    assert copied["rows"] is copied["value"]
    assert copied["rows"] is not rows


def test_hardened_table_semantics_plain_assertion_does_not_copy_output() -> None:
    rows = [["A"]]
    table = {"rows": rows, "value": rows}

    asserted = _plain_table_value_assertion()(table)

    assert asserted is table
    assert asserted["rows"] is asserted["value"]


def test_hardened_table_semantics_plain_value_rejects_only_active_path_cycles(
) -> None:
    direct: dict[str, Any] = {}
    direct["self"] = direct
    indirect: list[Any] = []
    indirect.append({"back": indirect})

    for value in (direct, indirect):
        with pytest.raises(ValueError, match="cyclic table value"):
            _plain_table_value_assertion()(value)


def test_hardened_table_semantics_plain_sequence_cap_is_inclusive() -> None:
    exact = [None] * 65_536
    assert _plain_table_value_assertion()(exact) is exact

    with pytest.raises(ValueError, match="table container limit exceeded"):
        _plain_table_value_assertion()([None] * 65_537)


@pytest.mark.parametrize(
    "helper_name",
    [
        "_assert_plain_table_value",
        "_bounded_table_text",
        "_validate_plain_table_value",
    ],
)
def test_hardened_table_semantics_text_validation_suppresses_raw_context(
    helper_name: str,
) -> None:
    helpers = _plain_table_helpers()
    validate = helpers[helper_name]

    with pytest.raises(ValueError, match="table text must be valid UTF-8") as caught:
        if helper_name == "_bounded_table_text":
            validate("\ud800")
        else:
            validate("\ud800", helpers["perf_counter"]() + 5.0)

    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True
    rendered = "".join(traceback.format_exception(caught.value))
    assert "UnicodeEncodeError" not in rendered
    assert "surrogates not allowed" not in rendered


def test_hardened_table_semantics_plain_value_does_not_invoke_sentinel() -> None:
    calls: list[str] = []

    class Sentinel:
        def __int__(self) -> int:
            calls.append("int")
            return 1

        def __float__(self) -> float:
            calls.append("float")
            return 1.0

        def __format__(self, format_spec: str) -> str:
            calls.append(f"format:{format_spec}")
            return "sentinel"

    with pytest.raises(TypeError, match="exact plain data"):
        _plain_table_value_validator()(Sentinel())

    assert calls == []


def test_hardened_table_semantics_plain_mapping_rejects_hostile_key_without_callback(
) -> None:
    calls: list[str] = []

    class HostileKey:
        def __hash__(self) -> int:
            calls.append("hash")
            return 7

        def __eq__(self, other: object) -> bool:
            del other
            calls.append("eq")
            return False

    key = HostileKey()
    value = {key: "x"}
    calls.clear()

    with pytest.raises(TypeError, match="exact plain data"):
        _plain_table_value_assertion()(value)

    assert calls == []


def test_hardened_table_semantics_mapping_copier_rejects_hostile_key_without_callback(
) -> None:
    calls: list[str] = []

    class HostileKey:
        def __hash__(self) -> int:
            calls.append("hash")
            return 7

        def __eq__(self, other: object) -> bool:
            del other
            calls.append("eq")
            return False

    key = HostileKey()
    value = {key: "x"}
    calls.clear()
    namespace = _table_semantics_runtime_namespace()

    with pytest.raises(TypeError, match="exact plain data"):
        namespace["_copy_table_mapping"](
            value,
            namespace["perf_counter"]() + 5.0,
        )

    assert calls == []


def _table_semantics_runtime_namespace() -> dict[str, Any]:
    namespace: dict[str, Any] = {}
    exec(_all_public_table_semantics_source(), namespace)
    return namespace


def test_hardened_table_semantics_canonical_json_and_sha_are_exact() -> None:
    namespace = _table_semantics_runtime_namespace()
    deadline = namespace["perf_counter"]() + 5.0
    value = {"b": 1, "a": "é"}

    encoded = namespace["_canonical_table_json_bytes"](
        value,
        8_388_608,
        deadline,
    )
    digest = namespace["_canonical_table_sha256"](
        value,
        8_388_608,
        deadline,
    )

    assert encoded == '{"a":"é","b":1}'.encode("utf-8")
    assert digest == hashlib.sha256(encoded).hexdigest()
    assert namespace["_bounded_table_sha256"](
        b"document",
        67_108_864,
        deadline,
    ) == hashlib.sha256(b"document").hexdigest()


def test_hardened_table_semantics_batch_sha_is_exact_ordered_and_bounded() -> None:
    namespace = _table_semantics_runtime_namespace()
    deadline = namespace["perf_counter"]() + 5.0
    values = [
        {"domain": "cell", "row": 0, "column": 0},
        {"domain": "cell", "row": 0, "column": 1},
    ]

    observed = namespace["_batch_table_sha256"](values, 8_388_608, deadline)

    assert observed == [
        hashlib.sha256(
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        for value in values
    ]
    with pytest.raises(TypeError, match="exact list"):
        namespace["_batch_table_sha256"](tuple(values), 8_388_608, deadline)
    with pytest.raises(ValueError, match="count exceeded"):
        namespace["_batch_table_sha256"](
            [None] * 65_537,
            8_388_608,
            deadline,
        )


def test_hardened_table_semantics_batch_sha_aggregate_exact_and_plus_one() -> None:
    namespace = _table_semantics_runtime_namespace()
    deadline = namespace["perf_counter"]() + 20.0
    exact = ["x" * 1_048_576] * 7 + ["x" * 1_048_560]

    observed = namespace["_batch_table_sha256"](
        exact,
        8_388_608,
        deadline,
    )

    assert len(observed) == 8
    with pytest.raises(ValueError, match="aggregate limit exceeded"):
        namespace["_batch_table_sha256"](
            [*exact[:-1], "x" * 1_048_561],
            8_388_608,
            namespace["perf_counter"]() + 20.0,
        )


def test_hardened_table_semantics_batch_sha_count_exact_is_accepted() -> None:
    namespace = _table_semantics_runtime_namespace()
    observed = namespace["_batch_table_sha256"](
        [None] * 65_536,
        8_388_608,
        namespace["perf_counter"]() + 5.0,
    )

    assert len(observed) == 65_536
    assert observed[0] == hashlib.sha256(b"null").hexdigest()
    assert observed[-1] == observed[0]


@pytest.mark.parametrize(
    "value",
    [
        {"bytes": b"x"},
        {"tuple": ("x",)},
        {1: "non-text-key"},
        {"number": float("nan")},
    ],
)
def test_hardened_table_semantics_batch_sha_rejects_non_json_values(
    value: Any,
) -> None:
    namespace = _table_semantics_runtime_namespace()
    with pytest.raises((TypeError, ValueError)):
        namespace["_batch_table_sha256"](
            [value],
            8_388_608,
            namespace["perf_counter"]() + 5.0,
        )


def test_hardened_table_semantics_batch_sha_rejects_invalid_limit_and_deadline(
) -> None:
    namespace = _table_semantics_runtime_namespace()
    with pytest.raises(ValueError, match="limit differs"):
        namespace["_batch_table_sha256"](
            [],
            8_388_607,
            namespace["perf_counter"]() + 5.0,
        )
    with pytest.raises(TimeoutError, match="deadline exceeded"):
        namespace["_batch_table_sha256"](
            [],
            8_388_608,
            namespace["perf_counter"]() - 1.0,
        )


def test_hardened_table_semantics_scanner_rejects_batch_sha_in_loop() -> None:
    changed = _valid_table_semantics_source(
        replay_body=(
            "    seeds = []\n"
            "    for cell in _bounded_table_iterable(\n"
            "        table.get('cells', []), 65536\n"
            "    ):\n"
            "        _check_table_deadline(deadline)\n"
            "        seeds.append(cell)\n"
            "        digests = _batch_table_sha256(\n"
            "            seeds, 8388608, deadline\n"
            "        )\n"
        ),
    )

    with pytest.raises(
        readiness.ReadinessContractError,
        match="loop resource amplification",
    ):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_rejects_transitive_batch_sha_in_loop(
) -> None:
    changed = _valid_table_semantics_source(
        module_body=(
            "def _batch_digest_wrapper(values, maximum_bytes, deadline):\n"
            "    values = _validate_plain_table_value(values, deadline)\n"
            "    maximum_bytes = _validate_plain_table_value(\n"
            "        maximum_bytes, deadline\n"
            "    )\n"
            "    result = _batch_table_sha256(\n"
            "        values, maximum_bytes, deadline\n"
            "    )\n"
            "    validated_result_output = _assert_plain_table_value(\n"
            "        result, deadline\n"
            "    )\n"
            "    return result\n\n"
        ),
        replay_body=(
            "    seeds = []\n"
            "    for cell in _bounded_table_iterable(\n"
            "        table.get('cells', []), 65536\n"
            "    ):\n"
            "        _check_table_deadline(deadline)\n"
            "        seeds.append(cell)\n"
            "        digests = _batch_digest_wrapper(\n"
            "            seeds, 8388608, deadline\n"
            "        )\n"
        ),
    )

    with pytest.raises(
        readiness.ReadinessContractError,
        match="loop resource amplification",
    ):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_rejects_batch_sha_helper_drift() -> None:
    changed = _replace_once(
        _valid_table_semantics_source(),
        b"table batch SHA-256 count exceeded",
        b"table batch SHA-256 count changed",
    )

    with pytest.raises(
        readiness.ReadinessContractError,
        match="helper differs",
    ):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_rejects_batch_sha_bad_deadline() -> None:
    changed = _valid_table_semantics_source(
        replay_body=(
            "    seeds = []\n"
            "    digests = _batch_table_sha256(\n"
            "        seeds, 8388608, perf_counter() + 0.25\n"
            "    )\n"
        ),
    )

    with pytest.raises(
        readiness.ReadinessContractError,
        match="deadline forwarding",
    ):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_charges_repeated_batch_sha_calls() -> None:
    calls = "".join(
        "    digest_"
        + str(index)
        + " = _batch_table_sha256([], 8388608, deadline)\n"
        for index in range(8)
    )
    changed = _valid_table_semantics_source(replay_body=calls)

    with pytest.raises(
        readiness.ReadinessContractError,
        match="cumulative allocation",
    ):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_accepts_one_bounded_batch_outside_loop(
) -> None:
    changed = _valid_table_semantics_source(
        replay_body=(
            "    seeds = []\n"
            "    for cell in _bounded_table_iterable(\n"
            "        table.get('cells', []), 65536\n"
            "    ):\n"
            "        _check_table_deadline(deadline)\n"
            "        seeds.append({'domain': 'cell', 'cell': cell})\n"
            "    digests = _batch_table_sha256(\n"
            "        seeds, 8388608, deadline\n"
            "    )\n"
        ),
    )

    exception._validate_table_semantics_module(changed)


@pytest.mark.parametrize(
    "value",
    [
        {"bytes": b"x"},
        {"tuple": ("x",)},
        {1: "non-text-key"},
        {"number": float("nan")},
    ],
)
def test_hardened_table_semantics_canonical_json_rejects_non_json_values(
    value: Any,
) -> None:
    namespace = _table_semantics_runtime_namespace()
    with pytest.raises((TypeError, ValueError)):
        namespace["_canonical_table_json_bytes"](
            value,
            8_388_608,
            namespace["perf_counter"]() + 5.0,
        )


def test_hardened_table_semantics_canonical_json_rejects_8_mib_plus_one(
) -> None:
    namespace = _table_semantics_runtime_namespace()
    value = ["x" * 1_048_576] * 9

    with pytest.raises(ValueError, match="JSON limit exceeded"):
        namespace["_canonical_table_json_bytes"](
            value,
            8_388_608,
            namespace["perf_counter"]() + 5.0,
        )


def test_hardened_table_semantics_source_sha_is_exact_lowercase() -> None:
    namespace = _table_semantics_runtime_namespace()
    deadline = namespace["perf_counter"]() + 5.0
    digest = "a" * 64

    assert namespace["_assert_source_sha256"](digest, deadline) == digest
    for changed in ("A" * 64, "a" * 63, "g" * 64):
        with pytest.raises(ValueError, match="source SHA-256 differs"):
            namespace["_assert_source_sha256"](changed, deadline)


def test_hardened_table_semantics_raw_table_copier_accepts_exact_union() -> None:
    namespace = _table_semantics_runtime_namespace()

    class ExactRawTable:
        def __init__(self) -> None:
            self.page_index = 1
            self.bbox = {"x": 0.0, "y": 0.0, "w": 10.0, "h": 5.0}
            self.rows = [["A"]]
            self.row_bboxes = [dict(self.bbox)]
            self.parse_concerns = []
            self.cell_bboxes = ((dict(self.bbox),),)
            self.geometry_inferred = False

    namespace["RawTable"] = ExactRawTable
    deadline = namespace["perf_counter"]() + 5.0
    copied_object = namespace["_copy_raw_table_graph"](
        {1: [ExactRawTable()]},
        deadline,
    )
    predecessor = {
        "page_index": 1,
        "bbox": {"x": 0.0, "y": 0.0, "w": 10.0, "h": 5.0},
        "rows": [["A"]],
        "row_bboxes": [],
        "parse_concerns": [],
    }
    copied_mapping = namespace["_copy_raw_table_graph"](
        {1: [predecessor]},
        deadline,
    )

    assert copied_object[1][0]["cell_bboxes"][0][0]["w"] == 10.0
    assert copied_object[1][0]["geometry_inferred"] is False
    assert copied_mapping[1][0]["cell_bboxes"] == ()
    assert copied_mapping[1][0]["geometry_inferred"] is None


def test_hardened_table_semantics_raw_table_copier_rejects_unknown_fields() -> None:
    namespace = _table_semantics_runtime_namespace()
    candidate = {
        "page_index": 1,
        "bbox": {},
        "rows": [["A"]],
        "row_bboxes": [],
        "parse_concerns": [],
        "unknown": True,
    }

    with pytest.raises(ValueError, match="mapping fields differ"):
        namespace["_copy_raw_table_graph"](
            {1: [candidate]},
            namespace["perf_counter"]() + 5.0,
        )


def test_hardened_table_semantics_raw_table_candidate_cap_fails_before_copy(
) -> None:
    namespace = _table_semantics_runtime_namespace()
    calls: list[str] = []

    class HostileKey:
        def __hash__(self) -> int:
            calls.append("hash")
            return 11

        def __eq__(self, other: object) -> bool:
            del other
            calls.append("eq")
            return False

    hostile_key = HostileKey()
    predecessor = {
        "page_index": 1,
        "bbox": {},
        "rows": [["A"]],
        "row_bboxes": [],
        "parse_concerns": [],
        hostile_key: "must-not-be-copied",
    }
    calls.clear()
    graph = {
        **{page: [predecessor] * 4_096 for page in range(1, 17)},
        17: [predecessor],
    }

    with pytest.raises(ValueError, match="candidate limit exceeded"):
        namespace["_copy_raw_table_graph"](
            graph,
            namespace["perf_counter"]() + 5.0,
        )

    assert calls == []


def _valid_table_semantics_source(
    *,
    replay_body: str = "",
    module_body: str = "",
    extra_import: str = "",
) -> bytes:
    source = _all_public_table_semantics_source()
    if extra_import:
        source = _replace_once(
            source,
            b"from copy import deepcopy\n",
            b"from copy import deepcopy\n" + extra_import.encode("utf-8"),
        )
    if module_body:
        source = _replace_once(
            source,
            exception.EXPECTED_TABLE_SEMANTICS_BOUNDED_ITERABLE_SOURCE.encode(
                "utf-8"
            ),
            module_body.encode("utf-8")
            + exception.EXPECTED_TABLE_SEMANTICS_BOUNDED_ITERABLE_SOURCE.encode(
                "utf-8"
            ),
        )
    if replay_body:
        replay_body = replay_body.removeprefix(
            "    deadline = perf_counter() + 0.25\n"
        )
        replay_start = source.index(b"def replay_table_semantics(")
        insertion = source.index(
            b"    _assert_canonical_table_json(table, 8388608, deadline)\n",
            replay_start,
        )
        source = (
            source[:insertion]
            + replay_body.encode("utf-8")
            + source[insertion:]
        )
    return source


def _with_table_regex_imports(source: bytes) -> bytes:
    return _replace_once(
        source,
        b"from re import fullmatch\n",
        b"from re import fullmatch, search, sub\n",
    )


def _all_public_table_semantics_source() -> bytes:
    imports_and_helpers = (
        "from app.services.tables import RawTable\n"
        "from collections import defaultdict\n"
        "from copy import deepcopy\n"
        "from hashlib import sha256\n"
        "from json import dumps\n"
        "from math import isfinite\n"
        "from re import fullmatch\n"
        "from time import perf_counter\n\n"
        + exception.EXPECTED_TABLE_SEMANTICS_BOUNDED_ITERABLE_SOURCE
        + "\n"
        + exception.EXPECTED_TABLE_SEMANTICS_BOUNDED_TEXT_SOURCE
        + "\n"
        + exception.EXPECTED_TABLE_SEMANTICS_DEADLINE_CHECK_SOURCE
        + "\n"
        + exception.EXPECTED_TABLE_SEMANTICS_PLAIN_ASSERT_SOURCE
        + "\n"
        + exception.EXPECTED_TABLE_SEMANTICS_PLAIN_VALUE_SOURCE
        + "\n"
        + exception.EXPECTED_TABLE_SEMANTICS_MAPPING_COPY_SOURCE
        + "\n"
        + exception.EXPECTED_TABLE_SEMANTICS_RAW_TABLE_GRAPH_SOURCE
        + "\n"
        + exception.EXPECTED_TABLE_SEMANTICS_SOURCE_SHA_SOURCE
        + "\n"
        + exception.EXPECTED_TABLE_SEMANTICS_CANONICAL_JSON_SOURCE
        + "\n"
        + exception.EXPECTED_TABLE_SEMANTICS_BOUNDED_SHA_SOURCE
        + "\n"
        + exception.EXPECTED_TABLE_SEMANTICS_CANONICAL_SHA_SOURCE
        + "\n"
        + exception.EXPECTED_TABLE_SEMANTICS_BATCH_SHA_SOURCE
        + "\n"
        + exception.EXPECTED_TABLE_SEMANTICS_CANONICAL_ASSERT_SOURCE
        + "\n"
        + exception.EXPECTED_TABLE_SEMANTICS_PLAIN_LENGTH_SOURCE
        + "\n"
    )
    signatures = {
        "prepare_docling_table_input": (
            "raw_item, page_heights, page_words_by_page, *, "
            "table_span_fidelity_enabled=False"
        ),
        "prepare_docling_table": (
            "item, raw_item, *, table_span_fidelity_enabled=False"
        ),
        "prepare_vector_table": (
            "item, raw_table, *, table_span_fidelity_enabled=False"
        ),
        "reconcile_table_candidates": (
            "merged, docling_tables, vector_tables, *, "
            "table_span_fidelity_enabled=False, "
            "table_evidence_reconciliation_enabled=False"
        ),
        "gate_table_candidates": (
            "tables, body_items, image_regions, raw_docling, "
            "source_document_identity, *, table_span_fidelity_enabled=False, "
            "table_evidence_reconciliation_enabled=False, "
            "table_candidate_gate_enabled=False"
        ),
        "seal_table_pages": (
            "pages, source_sha256, native_texts, *, "
            "table_span_fidelity_enabled=False, "
            "table_evidence_reconciliation_enabled=False, "
            "table_candidate_gate_enabled=False, "
            "table_multi_page_merge_enabled=False"
        ),
        "merge_continued_tables": (
            "pages, source_sha256, *, table_span_fidelity_enabled=False, "
            "table_evidence_reconciliation_enabled=False, "
            "table_candidate_gate_enabled=False, "
            "table_multi_page_merge_enabled=False"
        ),
        "replay_table_semantics": "table, table_evidence",
        "replace_marked_table_text": (
            "owner, *, selected_text, replacement_mode, original_text"
        ),
    }
    returns = {
        "prepare_docling_table_input": "raw_item",
        "prepare_docling_table": "item",
        "prepare_vector_table": "item",
        "reconcile_table_candidates": "merged",
        "gate_table_candidates": "tables",
        "seal_table_pages": "None",
        "merge_continued_tables": "None",
        "replay_table_semantics": "table",
        "replace_marked_table_text": "None",
    }
    functions: list[str] = []
    for name, signature in signatures.items():
        body = ""
        guard = exception.EXPECTED_TABLE_SEMANTICS_DEFAULT_OFF_GUARDS.get(name)
        if guard is not None:
            body += indent(guard, "    ")
        if name == "reconcile_table_candidates":
            body += indent(
                exception.EXPECTED_TABLE_SEMANTICS_RECONCILIATION_DISABLED_BRANCH,
                "    ",
            )
        deadline_seconds = exception.EXPECTED_TABLE_SEMANTICS_PUBLIC_DEADLINE_SECONDS[
            name
        ]
        body += f"    deadline = perf_counter() + {deadline_seconds!r}\n"
        for argument, validator in (
            exception.EXPECTED_TABLE_SEMANTICS_ARGUMENT_VALIDATORS[name].items()
        ):
            policy = (
                exception.EXPECTED_TABLE_SEMANTICS_ARGUMENT_VALIDATION_POLICIES[
                    name
                ][argument]
            )
            if policy == "rebind":
                body += f"    {argument} = {validator}({argument}, deadline)\n"
            else:
                body += f"    {validator}({argument}, deadline)\n"
        output_root = exception.EXPECTED_TABLE_SEMANTICS_OUTPUT_ROOTS[name]
        if output_root is not None:
            body += (
                f"    _assert_canonical_table_json("
                f"{output_root}, "
                f"{exception.EXPECTED_TABLE_SEMANTICS_OUTPUT_JSON_LIMITS[name]}, "
                f"deadline)\n"
            )
            body += (
                f"    validated_{output_root}_output = "
                f"_assert_plain_table_value({output_root}, deadline)\n"
            )
        body += f"    return {returns[name]}\n"
        functions.append(f"def {name}({signature}):\n{body}")
    return (imports_and_helpers + "\n".join(functions)).encode("utf-8")


def test_hardened_table_semantics_scanner_accepts_exact_nine_helper_surface() -> None:
    exception._validate_table_semantics_module(
        _all_public_table_semantics_source()
    )


def test_hardened_table_semantics_reconcile_span_only_guard_retains_us01_path(
) -> None:
    namespace = _table_semantics_runtime_namespace()
    calls: list[str] = []

    def forbidden_call(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        calls.append("called")
        raise AssertionError("disabled reconciliation performed work")

    for helper_name in (
        "perf_counter",
        "_copy_table_mapping",
        "_copy_raw_table_graph",
        "_assert_canonical_table_json",
        "_assert_plain_table_value",
    ):
        namespace[helper_name] = forbidden_call
    merged = {
        "tables": [{"cells": [["A"]]}],
        "source_alternatives": [{"engine": "docling"}],
        "geometry_alternatives": [{"engine": "vector"}],
    }
    disabled = namespace["reconcile_table_candidates"](
        merged,
        object(),
        object(),
        table_span_fidelity_enabled=False,
        table_evidence_reconciliation_enabled=True,
    )
    span_only = namespace["reconcile_table_candidates"](
        merged,
        {},
        {},
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=False,
    )

    assert disabled is merged
    assert span_only is merged
    assert calls == []


@pytest.mark.parametrize(
    ("copy_statement", "mutation"),
    [
        (
            b"    merged = _copy_table_mapping(merged, deadline)\n",
            b'    merged["selected_candidate"] = True\n',
        ),
        (
            b"    docling_tables = _copy_table_mapping(docling_tables, deadline)\n",
            b'    merged["candidate_score"] = 1\n',
        ),
    ],
)
def test_hardened_table_semantics_reconcile_rejects_interstitial_story_mutation(
    copy_statement: bytes,
    mutation: bytes,
) -> None:
    safe = _all_public_table_semantics_source()
    changed = _replace_once(
        safe,
        copy_statement,
        copy_statement + mutation,
    )

    with pytest.raises(
        readiness.ReadinessContractError,
        match="reconciliation preamble",
    ):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_reconcile_rejects_old_combined_guard() -> None:
    safe = _all_public_table_semantics_source()
    changed = _replace_once(
        safe,
        b"    if not table_span_fidelity_enabled:\n"
        b"        return merged\n",
        b"    if not (\n"
        b"        table_span_fidelity_enabled\n"
        b"        and table_evidence_reconciliation_enabled\n"
        b"    ):\n"
        b"        return merged\n",
    )

    with pytest.raises(readiness.ReadinessContractError, match="default-off"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_requires_canonical_terminal_gate() -> None:
    safe = _all_public_table_semantics_source()
    changed = _replace_once(
        safe,
        b"    _assert_canonical_table_json(table, 8388608, deadline)\n",
        b"",
    )

    with pytest.raises(readiness.ReadinessContractError, match="terminal validation"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_and_runtime_allow_flattened_owned_builder(
) -> None:
    body = (
        "    cells = _validate_plain_table_value(\n"
        "        table.get('cells', []), deadline\n"
        "    )\n"
        "    cell_count = _plain_table_length(cells, deadline)\n"
        "    records = []\n"
        "    for cell in _bounded_table_iterable(cells, 65536):\n"
        "        _check_table_deadline(deadline)\n"
        "        record = {'text': cell}\n"
        "        records.append(record)\n"
        "    table['cells'] = records\n"
        "    table['cell_count'] = cell_count\n"
    )
    safe = _valid_table_semantics_source(replay_body=body)

    exception._validate_table_semantics_module(safe)
    namespace: dict[str, Any] = {}
    exec(safe, namespace)
    table = {"cells": ["A", "B"]}

    observed = namespace["replay_table_semantics"](table, {})

    assert observed is table
    assert observed == {
        "cell_count": 2,
        "cells": [{"text": "A"}, {"text": "B"}],
    }


def test_hardened_table_semantics_scanner_rejects_borrowed_input_alias() -> None:
    changed = _valid_table_semantics_source(
        replay_body=(
            "    cells = table.get('cells', [])\n"
            "    table['cell_count'] = len(cells)\n"
        ),
    )

    with pytest.raises(readiness.ReadinessContractError, match="accumulator alias"):
        exception._validate_table_semantics_module(changed)


@pytest.mark.parametrize(
    "resource_statement",
    [
        "        copied = _validate_plain_table_value(cell, deadline)\n",
        "        copied = _copy_table_mapping(cell, deadline)\n",
        "        copied = dict(cell)\n",
        "        copied = sorted(cell)\n",
    ],
)
def test_hardened_table_semantics_scanner_rejects_direct_loop_resource_amplification(
    resource_statement: str,
) -> None:
    changed = _valid_table_semantics_source(
        replay_body=(
            "    for cell in _bounded_table_iterable(\n"
            "        table.get('cells', []), 65536\n"
            "    ):\n"
            "        _check_table_deadline(deadline)\n"
            + resource_statement
        ),
    )

    with pytest.raises(
        readiness.ReadinessContractError,
        match="loop resource amplification",
    ):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_rejects_transitive_loop_resource_amplification(
) -> None:
    changed = _valid_table_semantics_source(
        module_body=(
            "def _clone_table_value(value, deadline):\n"
            "    return _validate_plain_table_value(value, deadline)\n\n"
        ),
        replay_body=(
            "    for cell in _bounded_table_iterable(\n"
            "        table.get('cells', []), 65536\n"
            "    ):\n"
            "        _check_table_deadline(deadline)\n"
            "        copied = _clone_table_value(cell, deadline)\n"
        ),
    )

    with pytest.raises(
        readiness.ReadinessContractError,
        match="loop resource amplification",
    ):
        exception._validate_table_semantics_module(changed)


@pytest.mark.parametrize(
    "resource_statement",
    [
        "    copied = deepcopy(table)\n",
        "    encoded = dumps(table)\n",
        "    digest = sha256(b'table')\n",
    ],
)
def test_hardened_table_semantics_scanner_rejects_nonfrozen_resource_calls(
    resource_statement: str,
) -> None:
    changed = _valid_table_semantics_source(replay_body=resource_statement)

    with pytest.raises(
        readiness.ReadinessContractError,
        match="frozen resource call",
    ):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_rejects_missing_public_function() -> None:
    safe = _all_public_table_semantics_source()
    changed = safe[: safe.index(b"def replace_marked_table_text(")]
    with pytest.raises(readiness.ReadinessContractError, match="function set"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_rejects_extra_public_function() -> None:
    safe = _all_public_table_semantics_source()
    changed = safe + b"\ndef inspect_table_state():\n    return None\n"
    with pytest.raises(readiness.ReadinessContractError, match="function set"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_rejects_default_on_stage() -> None:
    safe = _all_public_table_semantics_source()
    changed = _replace_once(
        safe,
        b"    if not table_span_fidelity_enabled:\n"
        b"        return raw_item\n",
        b"    if table_span_fidelity_enabled:\n"
        b"        return raw_item\n",
    )
    with pytest.raises(readiness.ReadinessContractError, match="default-off"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_rejects_public_signature_drift() -> None:
    safe = _all_public_table_semantics_source()
    changed = _replace_once(
        safe,
        b"def replay_table_semantics(table, table_evidence):\n",
        b"def replay_table_semantics(table, table_evidence, callback=None):\n",
    )
    with pytest.raises(readiness.ReadinessContractError, match="signature"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_rejects_generic_vector_validation() -> None:
    safe = _all_public_table_semantics_source()
    changed = _replace_once(
        safe,
        b"    vector_tables = _copy_raw_table_graph(vector_tables, deadline)\n",
        b"    vector_tables = _validate_plain_table_value(vector_tables, deadline)\n",
    )
    with pytest.raises(
        readiness.ReadinessContractError,
        match="boundary|reconciliation preamble",
    ):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_rejects_expression_only_copy_stage() -> None:
    safe = _all_public_table_semantics_source()
    assignment = b"    raw_item = _validate_plain_table_value(raw_item, deadline)\n"
    changed = safe.replace(
        assignment,
        b"    _validate_plain_table_value(raw_item, deadline)\n",
        1,
    )
    assert changed != safe
    with pytest.raises(readiness.ReadinessContractError, match="boundary"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_rejects_rebound_in_place_stage() -> None:
    safe = _all_public_table_semantics_source()
    changed = _replace_once(
        safe,
        b"    _assert_plain_table_value(table, deadline)\n",
        b"    table = _validate_plain_table_value(table, deadline)\n",
    )
    with pytest.raises(readiness.ReadinessContractError, match="boundary"):
        exception._validate_table_semantics_module(changed)


@pytest.mark.parametrize(
    "rebind",
    [
        "    table = {'existing': 1}\n",
        "    table = table_evidence\n",
    ],
)
def test_hardened_table_semantics_scanner_rejects_post_validation_rebind(
    rebind: str,
) -> None:
    changed = _valid_table_semantics_source(
        replay_body=rebind + "    table['terminal'] = 1\n",
    )

    with pytest.raises(readiness.ReadinessContractError, match="boundary binding"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_rejects_pattern_binding_rebind() -> None:
    changed = _valid_table_semantics_source(
        replay_body=(
            "    match {'replacement': {}}:\n"
            "        case {'replacement': table}:\n"
            "            pass\n"
            "    table['terminal'] = 1\n"
        ),
    )

    with pytest.raises(readiness.ReadinessContractError, match="control"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_rejects_exception_binding_rebind() -> None:
    changed = _valid_table_semantics_source(
        replay_body=(
            "    try:\n"
            "        int('1')\n"
            "    except ValueError as table:\n"
            "        pass\n"
            "    table['terminal'] = 1\n"
        ),
    )

    with pytest.raises(readiness.ReadinessContractError, match="boundary binding"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_rejects_image_region_use() -> None:
    safe = _all_public_table_semantics_source()
    marker = (
        b"def gate_table_candidates(tables, body_items, image_regions, "
        b"raw_docling, source_document_identity, *, "
    )
    function_start = safe.index(marker)
    insertion = safe.index(
        b"    tables = _copy_table_mapping(tables, deadline)\n",
        function_start,
    )
    changed = (
        safe[:insertion]
        + b"    ignored = image_regions\n"
        + safe[insertion:]
    )
    with pytest.raises(readiness.ReadinessContractError, match="image-region"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_preserves_span_only_seal_guard() -> None:
    safe = _all_public_table_semantics_source()
    function_start = safe.index(b"def seal_table_pages(")
    guard_start = safe.index(
        b"    if not table_span_fidelity_enabled:\n",
        function_start,
    )
    guard_end = guard_start + len(
        b"    if not table_span_fidelity_enabled:\n"
        b"        return\n"
    )
    changed = (
        safe[:guard_start]
        + b"    if not (table_span_fidelity_enabled and "
        + b"table_evidence_reconciliation_enabled):\n"
        + b"        return\n"
        + safe[guard_end:]
    )
    with pytest.raises(readiness.ReadinessContractError, match="default-off"):
        exception._validate_table_semantics_module(changed)


@pytest.mark.parametrize("seconds", ("0.25", "5.0001", "50.0"))
def test_second_additive_table_semantics_seal_deadline_is_exact(
    seconds: str,
) -> None:
    safe = _all_public_table_semantics_source()
    function_start = safe.index(b"def seal_table_pages(")
    initializer = b"    deadline = perf_counter() + 5.0\n"
    position = safe.index(initializer, function_start)
    changed = (
        safe[:position]
        + f"    deadline = perf_counter() + {seconds}\n".encode("utf-8")
        + safe[position + len(initializer) :]
    )

    with pytest.raises(
        readiness.ReadinessContractError,
        match="deadline provenance|public deadline",
    ):
        exception._validate_table_semantics_module(changed)


def test_second_additive_table_semantics_only_seal_may_use_five_seconds() -> None:
    safe = _all_public_table_semantics_source()
    function_start = safe.index(b"def replay_table_semantics(")
    initializer = b"    deadline = perf_counter() + 0.25\n"
    position = safe.index(initializer, function_start)
    changed = (
        safe[:position]
        + b"    deadline = perf_counter() + 5.0\n"
        + safe[position + len(initializer) :]
    )

    with pytest.raises(
        readiness.ReadinessContractError,
        match="deadline provenance|public deadline",
    ):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_allows_forwarded_deadline() -> None:
    changed = _valid_table_semantics_source(
        module_body=(
            "def _forwarded_deadline(values, deadline):\n"
            "    for value in _bounded_table_iterable(values, 4096):\n"
            "        _check_table_deadline(deadline)\n"
            "        return value\n"
            "    return None\n\n"
        ),
        replay_body=(
            "    observed = _forwarded_deadline(\n"
            "        table.get('rows', []), deadline\n"
            "    )\n"
        ),
    )

    exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_rejects_private_deadline_reset() -> None:
    changed = _valid_table_semantics_source(
        module_body=(
            "def _reset_deadline(value):\n"
            "    deadline = perf_counter() + 0.25\n"
            "    return _validate_plain_table_value(value, deadline)\n\n"
        ),
        replay_body="    copied = _reset_deadline(table)\n",
    )

    with pytest.raises(readiness.ReadinessContractError, match="deadline reset"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_rejects_nonforwarded_deadline() -> None:
    changed = _valid_table_semantics_source(
        module_body=(
            "def _walk(values, deadline):\n"
            "    for value in _bounded_table_iterable(values, 4096):\n"
            "        _check_table_deadline(deadline)\n"
            "        return value\n"
            "    return None\n\n"
        ),
        replay_body=(
            "    observed = _walk(\n"
            "        table.get('rows', []), perf_counter() + 0.25\n"
            "    )\n"
        ),
    )

    with pytest.raises(readiness.ReadinessContractError, match="deadline forwarding"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_rejects_second_public_deadline() -> None:
    safe = _all_public_table_semantics_source()
    function_start = safe.index(b"def replay_table_semantics(")
    initializer = b"    deadline = perf_counter() + 0.25\n"
    insertion = safe.index(initializer, function_start) + len(initializer)
    changed = safe[:insertion] + initializer + safe[insertion:]

    with pytest.raises(readiness.ReadinessContractError, match="deadline provenance"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_allows_bounded_regex_and_allocations(
) -> None:
    safe = _valid_table_semantics_source(
        replay_body=(
            "    exact_bytes = bytes(65536)\n"
            "    exact_list = [None] * 65536\n"
            "    exact_range = range(65536)\n"
            "    exact_tuple = tuple(\n"
            "        _bounded_table_iterable(table.get('rows', []), 65536)\n"
            "    )\n"
            "    width = float('12.5')\n"
            "    doubled_width = 128 * 512\n"
            "    matched = fullmatch(\n"
            "        r'[A-Z]{0,64}',\n"
            "        _bounded_table_text(table.get('label', '')),\n"
            "    )\n"
            "    found = search(\n"
            "        r'\\d{1,4}',\n"
            "        _bounded_table_text(table.get('label', '')),\n"
            "    )\n"
            "    replaced = sub(\n"
            "        r'\\s{1,64}',\n"
            "        ' ',\n"
            "        _bounded_table_text(table.get('label', '')),\n"
            "    )\n"
        )
    )

    exception._validate_table_semantics_module(_with_table_regex_imports(safe))


def test_hardened_table_semantics_scanner_allows_safe_addition() -> None:
    safe = _valid_table_semantics_source(
        replay_body=(
            "    bounded_total = len(table) + 2\n"
            "    left = [None] * 32768\n"
            "    right = [None] * 32768\n"
            "    exact_sequence = left + right\n"
            "    literal_product = 128 * 512\n"
            "    count = len(table)\n"
            "    numeric_total = count + 2\n"
            "    numeric_remainder = count % 2\n"
        )
    )

    exception._validate_table_semantics_module(safe)


def test_hardened_table_semantics_scanner_allows_static_operational_values() -> None:
    safe = _valid_table_semantics_source(
        extra_import="from decimal import Decimal\n",
        replay_body=(
            "    integer = int('12')\n"
            "    decimal_float = float('1.25')\n"
            "    exact_decimal = Decimal('2.5')\n"
            "    decoded = b'table'.decode('utf-8')\n"
            "    named = table['rows']\n"
            "    indexed = table[0]\n"
            "    encoded = _bounded_table_text(\n"
            "        table.get('label', '')\n"
            "    ).encode('utf-8')\n"
            '    formatted = f"{integer:>8}"\n'
        ),
    )

    exception._validate_table_semantics_module(safe)


@pytest.mark.parametrize(
    "body",
    [
        "    oversized = bytes(65537)\n",
        "    oversized = list(range(65537))\n",
        "    oversized = range(65537)\n",
        "    oversized = tuple(range(65537))\n",
        "    oversized = [None] * 65537\n",
        "    dynamic = bytes(table.get('size', 0))\n",
        "    dynamic = list(table.get('rows', []))\n",
        "    dynamic = tuple(table.get('rows', []))\n",
        "    dynamic = [None] * len(table)\n",
        "    dynamic = table.get('rows', []) * 2\n",
        "    dynamic_numeric = len(table) * 2\n",
        "    explosive = 2 ** len(table)\n",
        "    explosive = 1 << len(table)\n",
        "    merged_mapping = table | table_evidence\n",
    ],
)
def test_hardened_table_semantics_scanner_rejects_unbounded_allocation(
    body: str,
) -> None:
    changed = _valid_table_semantics_source(replay_body=body)

    with pytest.raises(readiness.ReadinessContractError, match="allocation bound"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_rejects_sequence_add_max_plus_one(
) -> None:
    changed = _valid_table_semantics_source(
        replay_body=(
            "    left = [None] * 32768\n"
            "    right = [None] * 32769\n"
            "    oversized = left + right\n"
        )
    )

    with pytest.raises(readiness.ReadinessContractError, match="allocation bound"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_rejects_growing_dynamic_concat(
) -> None:
    changed = _valid_table_semantics_source(
        replay_body=(
            "    growing = table.get('rows', [])\n"
            "    growing = growing + table.get('rows', [])\n"
        )
    )

    with pytest.raises(readiness.ReadinessContractError, match="allocation bound"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_rejects_percent_string_allocation(
) -> None:
    changed = _valid_table_semantics_source(
        replay_body=(
            "    formatted = '%999999999s' % "
            "table.get('label', '')\n"
        )
    )

    with pytest.raises(readiness.ReadinessContractError, match="allocation bound"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_allows_bounded_incremental_mutation(
) -> None:
    safe = _valid_table_semantics_source(
        replay_body=(
            "    deadline = perf_counter() + 0.25\n"
            "    values = []\n"
            "    mapped = {}\n"
            "    for row in _bounded_table_iterable(\n"
            "        table.get('rows', []), 4096\n"
            "    ):\n"
            "        _check_table_deadline(deadline)\n"
            "        values.append(row)\n"
            "        mapped[len(mapped)] = row\n"
        ),
    )

    exception._validate_table_semantics_module(safe)


def test_hardened_table_semantics_scanner_allows_exact_cumulative_append_bound(
) -> None:
    safe = _valid_table_semantics_source(
        replay_body=(
            "    deadline = perf_counter() + 0.25\n"
            "    values = []\n"
            "    for left in _bounded_table_iterable(range(32768), 32768):\n"
            "        _check_table_deadline(deadline)\n"
            "        values.append(left)\n"
            "    for right in _bounded_table_iterable(range(32768), 32768):\n"
            "        _check_table_deadline(deadline)\n"
            "        values.append(right)\n"
        ),
    )

    exception._validate_table_semantics_module(safe)


@pytest.mark.parametrize(
    "record_source",
    [
        (
            "        record = {\n"
            "            'id': str(index), 'row': 0, 'column': 0,\n"
            "            'kind': 'anchor', 'cell_id': str(index),\n"
            "            'covered_by_cell_id': None,\n"
            "        }\n"
        ),
        (
            "        record = {\n"
            "            'id': str(index), 'row': 0, 'column': 0,\n"
            "            'row_span': 1, 'col_span': 1, 'text': '',\n"
            "            'column_header': False, 'row_header': False,\n"
            "            'row_section': False, 'bbox': None,\n"
            "            'source': 'native', 'page_index': 1,\n"
            "            'evidence_ids': [], 'source_object_ids': [],\n"
            "            'span_decision_id': None,\n"
            "            'confidence_dimensions': {\n"
            "                'text': None, 'geometry': None,\n"
            "                'structure': None, 'header': None,\n"
            "            },\n"
            "        }\n"
        ),
    ],
)
def test_hardened_table_semantics_scanner_allows_exact_record_cardinality(
    record_source: str,
) -> None:
    safe = _valid_table_semantics_source(
        replay_body=(
            "    deadline = perf_counter() + 0.25\n"
            "    records = []\n"
            "    for index in _bounded_table_iterable(range(65536), 65536):\n"
            "        _check_table_deadline(deadline)\n"
            + record_source
            + "        records.append(record)\n"
            "    table['records'] = records\n"
        ),
    )

    exception._validate_table_semantics_module(safe)


def test_hardened_table_semantics_scanner_allows_acyclic_local_record_builder(
) -> None:
    safe = _valid_table_semantics_source(
        module_body=(
            "def _record(value):\n"
            "    return {'id': value}\n\n"
        ),
        replay_body=(
            "    deadline = perf_counter() + 0.25\n"
            "    records = []\n"
            "    for index in _bounded_table_iterable(range(65536), 65536):\n"
            "        _check_table_deadline(deadline)\n"
            "        record = _record(index)\n"
            "        records.append(record)\n"
            "    table['records'] = records\n"
        ),
    )

    exception._validate_table_semantics_module(safe)


def test_hardened_table_semantics_scanner_rejects_nonplain_append_payload(
) -> None:
    changed = _valid_table_semantics_source(
        replay_body=(
            "    deadline = perf_counter() + 0.25\n"
            "    records = []\n"
            "    opaque = perf_counter\n"
            "    for index in _bounded_table_iterable(range(1), 1):\n"
            "        _check_table_deadline(deadline)\n"
            "        records.append(opaque)\n"
            "    table['records'] = records\n"
        ),
    )

    with pytest.raises(readiness.ReadinessContractError, match="incremental mutation"):
        exception._validate_table_semantics_module(changed)


@pytest.mark.parametrize(
    "body",
    [
        (
            "    deadline = perf_counter() + 0.25\n"
            "    values = [None]\n"
            "    for value in _bounded_table_iterable(range(65536), 65536):\n"
            "        _check_table_deadline(deadline)\n"
            "        values.append(value)\n"
        ),
        "    values = []\n    values.append(None)\n",
        (
            "    deadline = perf_counter() + 0.25\n"
            "    values = []\n"
            "    for left in _bounded_table_iterable(range(32768), 32768):\n"
            "        _check_table_deadline(deadline)\n"
            "        values.append(left)\n"
            "    for right in _bounded_table_iterable(range(32769), 32769):\n"
            "        _check_table_deadline(deadline)\n"
            "        values.append(right)\n"
        ),
        (
            "    deadline = perf_counter() + 0.25\n"
            "    values = []\n"
            "    alias = values\n"
            "    for value in _bounded_table_iterable(range(1), 1):\n"
            "        _check_table_deadline(deadline)\n"
            "        values.append(value)\n"
        ),
        (
            "    deadline = perf_counter() + 0.25\n"
            "    values = []\n"
            "    values = []\n"
            "    for value in _bounded_table_iterable(range(1), 1):\n"
            "        _check_table_deadline(deadline)\n"
            "        values.append(value)\n"
        ),
        (
            "    values = []\n"
            "    values += list(range(65536))\n"
            "    values += list(range(65536))\n"
            "    table['values'] = values\n"
        ),
    ],
)
def test_hardened_table_semantics_scanner_rejects_unsafe_append_growth(
    body: str,
) -> None:
    changed = _valid_table_semantics_source(replay_body=body)

    with pytest.raises(
        readiness.ReadinessContractError,
        match="incremental mutation|accumulator alias",
    ):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_allows_exact_dynamic_dict_bound(
) -> None:
    safe = _valid_table_semantics_source(
        replay_body=(
            "    deadline = perf_counter() + 0.25\n"
            "    mapped = {}\n"
            "    for key in _bounded_table_iterable(range(65535), 65535):\n"
            "        _check_table_deadline(deadline)\n"
            "        mapped[key] = key\n"
            "    mapped['terminal'] = 1\n"
        ),
    )

    exception._validate_table_semantics_module(safe)


@pytest.mark.parametrize(
    "body",
    [
        (
            "    deadline = perf_counter() + 0.25\n"
            "    mapped = {'existing': 1}\n"
            "    for key in _bounded_table_iterable(range(65536), 65536):\n"
            "        _check_table_deadline(deadline)\n"
            "        mapped[key] = key\n"
        ),
        (
            "    deadline = perf_counter() + 0.25\n"
            "    mapped = {}\n"
            "    for key in _bounded_table_iterable(range(65536), 65536):\n"
            "        _check_table_deadline(deadline)\n"
            "        mapped[key] = key\n"
            "    mapped['terminal'] = 1\n"
        ),
        (
            "    deadline = perf_counter() + 0.25\n"
            "    mapped = {}\n"
            "    for left in _bounded_table_iterable(range(32768), 32768):\n"
            "        _check_table_deadline(deadline)\n"
            "        mapped[left] = left\n"
            "    for right in _bounded_table_iterable(range(32769), 32769):\n"
            "        _check_table_deadline(deadline)\n"
            "        mapped[right] = right\n"
        ),
        (
            "    deadline = perf_counter() + 0.25\n"
            "    mapped = {}\n"
            "    for key in _bounded_table_iterable(range(1), 1):\n"
            "        _check_table_deadline(deadline)\n"
            "        mapped['fixed'] = key\n"
        ),
    ],
)
def test_hardened_table_semantics_scanner_rejects_unsafe_dict_growth(
    body: str,
) -> None:
    changed = _valid_table_semantics_source(replay_body=body)

    with pytest.raises(
        readiness.ReadinessContractError,
        match="incremental mutation",
    ):
        exception._validate_table_semantics_module(changed)


@pytest.mark.parametrize(
    ("body", "extra_import"),
    [
        ("    values = set()\n    values.add(1)\n", ""),
        ("    mapped = {}\n    mapped.setdefault('key', 1)\n", ""),
        (
            "    stream = StringIO()\n"
            "    csv_writer = writer(stream)\n"
            "    csv_writer.writerow([1])\n",
            "from csv import writer\nfrom io import StringIO\n",
        ),
    ],
)
def test_hardened_table_semantics_scanner_rejects_unbounded_growing_methods(
    body: str,
    extra_import: str,
) -> None:
    changed = _valid_table_semantics_source(
        replay_body=body,
        extra_import=extra_import,
    )

    with pytest.raises(
        readiness.ReadinessContractError,
        match="incremental mutation|syntax resource",
    ):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_rejects_cross_helper_literal_growth(
) -> None:
    changed = _valid_table_semantics_source(
        module_body=(
            "def _inject(mapping):\n"
            "    mapping['terminal'] = 1\n"
            "    return mapping\n\n"
        ),
        replay_body=(
            "    deadline = perf_counter() + 0.25\n"
            "    mapped = {}\n"
            "    for key in _bounded_table_iterable(range(65536), 65536):\n"
            "        _check_table_deadline(deadline)\n"
            "        mapped[key] = key\n"
            "    _inject(mapped)\n"
            "    table['mapped'] = mapped\n"
        ),
    )

    with pytest.raises(readiness.ReadinessContractError, match="incremental mutation"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_counts_validated_input_literal_stores(
) -> None:
    changed = _valid_table_semantics_source(
        replay_body="    table[0] = 0\n" * 61_441,
    )

    assert len(changed) < 2 * 1024 * 1024
    with pytest.raises(
        readiness.ReadinessContractError,
        match="incremental mutation|syntax resource",
    ):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_rejects_allocating_append_payload(
) -> None:
    changed = _valid_table_semantics_source(
        module_body=(
            "def _chunk():\n"
            "    return [None] * 65536\n\n"
        ),
        replay_body=(
            "    deadline = perf_counter() + 0.25\n"
            "    values = []\n"
            "    for key in _bounded_table_iterable(range(65536), 65536):\n"
            "        _check_table_deadline(deadline)\n"
            "        values.append(_chunk())\n"
        ),
    )

    with pytest.raises(readiness.ReadinessContractError, match="method callback"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_counts_nested_append_allocation(
) -> None:
    changed = _valid_table_semantics_source(
        replay_body=(
            "    deadline = perf_counter() + 0.25\n"
            "    values = []\n"
            "    for key in _bounded_table_iterable(range(1024), 1024):\n"
            "        _check_table_deadline(deadline)\n"
            "        values.append([None] * 65536)\n"
        ),
    )

    with pytest.raises(readiness.ReadinessContractError, match="cumulative allocation"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_requires_terminal_output_validation(
) -> None:
    safe = _all_public_table_semantics_source()
    changed = _replace_once(
        safe,
        b"    validated_table_output = _assert_plain_table_value(table, deadline)\n",
        b"",
    )

    with pytest.raises(readiness.ReadinessContractError, match="terminal validation"):
        exception._validate_table_semantics_module(changed)


@pytest.mark.parametrize(
    "body",
    [
        "    table['self'] = table\n",
        (
            "    deadline = perf_counter() + 0.25\n"
            "    values = []\n"
            "    for key in _bounded_table_iterable(range(1), 1):\n"
            "        _check_table_deadline(deadline)\n"
            "        values.append(values)\n"
            "    table['values'] = values\n"
        ),
        "    table['bad'] = perf_counter\n",
        "    table['bad'] = float('nan')\n",
        "    table['bad'] = '\\ud800'\n",
        "    table['bad'] = range(1)\n",
        "    table['bad'] = {1, 2}\n",
    ],
)
def test_hardened_table_semantics_terminal_validation_fails_closed(
    body: str,
) -> None:
    source = _valid_table_semantics_source(replay_body=body)
    exception._validate_table_semantics_module(source)
    namespace: dict[str, Any] = {}
    exec(source, namespace)

    with pytest.raises((TypeError, ValueError)):
        namespace["replay_table_semantics"]({}, {})


def test_hardened_table_semantics_terminal_validation_accepts_shared_dag() -> None:
    source = _valid_table_semantics_source(
        replay_body=(
            "    shared = []\n"
            "    table['a'] = shared\n"
            "    table['b'] = shared\n"
        ),
    )
    exception._validate_table_semantics_module(source)
    namespace: dict[str, Any] = {}
    exec(source, namespace)
    table: dict[str, Any] = {}

    returned = namespace["replay_table_semantics"](table, {})

    assert returned is table
    assert returned["a"] is returned["b"]


def test_hardened_table_semantics_scanner_requires_initializer_dominance() -> None:
    changed = _valid_table_semantics_source(
        replay_body=(
            "    mapped['x'] = 1\n"
            "    mapped = {}\n"
            "    table['mapped'] = mapped\n"
        ),
    )

    with pytest.raises(readiness.ReadinessContractError, match="incremental mutation"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_counts_range_element_bytes() -> None:
    changed = _valid_table_semantics_source(
        replay_body="".join(
            f"    table['k{index}'] = list(range(65536))\n"
            for index in range(26)
        ),
    )

    with pytest.raises(readiness.ReadinessContractError, match="cumulative allocation"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_counts_interprocedural_allocation() -> None:
    changed = _valid_table_semantics_source(
        module_body=(
            "def _chunk():\n"
            "    return [None] * 65536\n\n"
        ),
        replay_body="".join(
            f"    table['k{index}'] = _chunk()\n" for index in range(129)
        ),
    )

    with pytest.raises(readiness.ReadinessContractError, match="cumulative allocation"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_caps_unrolled_numeric_work() -> None:
    changed = _valid_table_semantics_source(
        replay_body=(
            "    n0 = 1\n"
            + "".join(
                f"    n{index} = n{index - 1} + n{index - 1}\n"
                for index in range(1, 5_000)
            )
            + "    table['n'] = n4999\n"
        ),
    )

    with pytest.raises(readiness.ReadinessContractError, match="syntax resource"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_tracks_callback_call_edges() -> None:
    changed = _valid_table_semantics_source(
        module_body=(
            "def _callback(value):\n"
            "    return sorted([1], key=_callback)[0]\n\n"
        ),
        replay_body="    table['bad'] = sorted([1], key=_callback)\n",
    )

    with pytest.raises(readiness.ReadinessContractError, match="call graph"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_rejects_method_callback_multiplicity() -> None:
    changed = _valid_table_semantics_source(
        module_body=(
            "def _callback(value):\n"
            "    return [None] * 65536\n\n"
        ),
        replay_body=(
            "    values = list(range(4096))\n"
            "    values.sort(key=_callback)\n"
            "    table['bad'] = values\n"
        ),
    )

    with pytest.raises(readiness.ReadinessContractError, match="method callback"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_rejects_method_callback_factory() -> None:
    changed = _valid_table_semantics_source(
        module_body=(
            "def _callback(value):\n"
            "    return [None] * 65536\n\n"
            "def _factory():\n"
            "    return _callback\n\n"
        ),
        replay_body=(
            "    values = list(range(4096))\n"
            "    values.sort(key=_factory())\n"
            "    table['bad'] = values\n"
        ),
    )

    with pytest.raises(readiness.ReadinessContractError, match="method callback"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_forbids_swallowed_loop_timeout() -> None:
    changed = _valid_table_semantics_source(
        module_body=(
            "def _swallow(values):\n"
            "    deadline = perf_counter() + 0.25\n"
            "    try:\n"
            "        for value in _bounded_table_iterable(values, 65536):\n"
            "            _check_table_deadline(deadline)\n"
            "            return value\n"
            "    except TimeoutError:\n"
            "        return None\n"
            "    return None\n\n"
        ),
        replay_body=(
            "    table['bad'] = _swallow(table.get('rows', []))\n"
        ),
    )

    with pytest.raises(readiness.ReadinessContractError, match="deadline propagation"):
        exception._validate_table_semantics_module(changed)


@pytest.mark.parametrize(
    ("body", "extra_import"),
    [
        (
            "    values = []\n"
            "    chunk = list(range(65536))\n"
            "    values.extend(chunk)\n"
            "    values.extend(chunk)\n",
            "",
        ),
        (
            "    mapped = {}\n"
            "    mapped.update(table)\n",
            "",
        ),
        (
            "    stream = StringIO()\n"
            "    csv_writer = writer(stream)\n"
            "    csv_writer.writerows(table.get('rows', []))\n",
            "from csv import writer\nfrom io import StringIO\n",
        ),
        (
            "    stream = StringIO()\n"
            "    stream.write(_bounded_table_text(\n"
            "        table.get('label', '')\n"
            "    ))\n",
            "from io import StringIO\n",
        ),
        (
            "    values = []\n"
            "    hidden_bulk_method = values.extend\n",
            "",
        ),
    ],
)
def test_hardened_table_semantics_scanner_rejects_bulk_mutation_and_aliases(
    body: str,
    extra_import: str,
) -> None:
    changed = _valid_table_semantics_source(
        extra_import=extra_import,
        replay_body=body,
    )

    with pytest.raises(readiness.ReadinessContractError, match="bulk mutation"):
        exception._validate_table_semantics_module(changed)


@pytest.mark.parametrize(
    ("body", "extra_import", "error"),
    [
        (
            "    converted = int(table.get('value', ''))\n",
            "",
            "numeric conversion",
        ),
        (
            "    converted = float(table.get('value', ''))\n",
            "",
            "numeric conversion",
        ),
        (
            "    converted = Decimal(table.get('value', ''))\n",
            "from decimal import Decimal\n",
            "numeric conversion",
        ),
        (
            "    decoded = table.get('value', b'').decode('utf-8')\n",
            "",
            "text decoding",
        ),
        (
            "    key = table.get('key', 'rows')\n"
            "    selected = table[key]\n",
            "",
            "operational subscript",
        ),
        (
            "    selected = table[1:2]\n",
            "",
            "operational subscript",
        ),
        (
            "    formatted = f\"{table.get('value', ''):"
            "{table.get('format', '')}}\"\n",
            "",
            "format specification",
        ),
        (
            "    encoded = table.get('value', '').encode('utf-8')\n",
            "",
            "text encoding",
        ),
        (
            "    encoded = _bounded_table_text(\n"
            "        table.get('value', '')\n"
            "    ).encode(table.get('encoding', 'utf-8'))\n",
            "",
            "text encoding",
        ),
    ],
)
def test_hardened_table_semantics_scanner_rejects_dynamic_operational_values(
    body: str,
    extra_import: str,
    error: str,
) -> None:
    changed = _valid_table_semantics_source(
        extra_import=extra_import,
        replay_body=body,
    )

    with pytest.raises(readiness.ReadinessContractError, match=error):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_rejects_suppressed_context_outside_exact_helpers(
) -> None:
    changed = _valid_table_semantics_source(
        replay_body='    raise ValueError("literal") from None\n'
    )

    with pytest.raises(readiness.ReadinessContractError, match="diagnostic payload"):
        exception._validate_table_semantics_module(changed)


@pytest.mark.parametrize(
    "body",
    [
        (
            "    text = _bounded_table_text(table.get('label', ''))\n"
            "    pattern = _bounded_table_text(table.get('pattern', ''))\n"
            "    matched = search(pattern, text)\n"
        ),
        (
            "    matched = search(\n"
            "        r'[A-Z]{0,64}',\n"
            "        table.get('label', ''),\n"
            "    )\n"
        ),
        (
            "    matched = fullmatch(\n"
            "        r'(a+)+$',\n"
            "        _bounded_table_text(table.get('label', '')),\n"
            "    )\n"
        ),
        (
            "    replaced = sub(\n"
            "        r'\\s{1,64}',\n"
            "        _bounded_table_text(table.get('replacement', '')),\n"
            "        _bounded_table_text(table.get('label', '')),\n"
            "    )\n"
        ),
    ],
)
def test_hardened_table_semantics_scanner_rejects_unsafe_regex(
    body: str,
) -> None:
    changed = _with_table_regex_imports(
        _valid_table_semantics_source(replay_body=body)
    )

    with pytest.raises(readiness.ReadinessContractError, match="regex"):
        exception._validate_table_semantics_module(changed)


@pytest.mark.parametrize(
    ("finding_id", "raw"),
    [
        (
            "TS-01",
            _valid_table_semantics_source(
                module_body="TABLE_IMPORT_EVENT = perf_counter()\n\n"
            ),
        ),
        (
            "TS-02",
            _valid_table_semantics_source(
                replay_body="    table.callback()\n"
            ),
        ),
        (
            "TS-03",
            _valid_table_semantics_source(
                extra_import="from operator import attrgetter\n",
                replay_body=(
                    "    callback = attrgetter('side_effect')(table)\n"
                    "    callback()\n"
                ),
            ),
        ),
        (
            "TS-04",
            _valid_table_semantics_source(
                extra_import="from json import __loader__\n",
                replay_body="    __loader__.get_data('marker')\n",
            ),
        ),
        (
            "TS-05",
            _valid_table_semantics_source(replay_body="    breakpoint()\n"),
        ),
        (
            "TS-06",
            _valid_table_semantics_source(
                replay_body=(
                    "    for value in table:\n"
                    "        table_evidence = value\n"
                )
            ),
        ),
        (
            "GUARD-REFLECTION-CHAIN",
            _valid_table_semantics_source(
                extra_import="from operator import attrgetter\n",
                replay_body=(
                    "    globals_name = '__glo' + 'bals__'\n"
                    "    callback = attrgetter(globals_name)(table)\n"
                    "    callback()\n"
                ),
            ),
        ),
        (
            "GUARD-RAISE-RAW-PAYLOAD",
            _valid_table_semantics_source(
                replay_body="    raise ValueError(str(table))\n"
            ),
        ),
        (
            "GUARD-ASSERT-RAW-PAYLOAD",
            _valid_table_semantics_source(
                replay_body="    assert True, str(table)\n"
            ),
        ),
        (
            "GUARD-RAISE-CAUSE",
            _valid_table_semantics_source(
                replay_body=(
                    '    raise ValueError("literal") from '
                    "ValueError(str(table))\n"
                )
            ),
        ),
        (
            "GUARD-RECURSIVE-CALL-GRAPH",
            _valid_table_semantics_source(
                module_body="def _cycle():\n    return _cycle()\n\n"
            ),
        ),
        (
            "GUARD-DEADLINE-OVERWRITE",
            _valid_table_semantics_source(
                module_body=(
                    "def _deadline_overwrite(values):\n"
                    "    deadline = perf_counter() + 0.25\n"
                    "    deadline = perf_counter() + 1.0\n"
                    "    for value in _bounded_table_iterable(values, 4096):\n"
                    "        _check_table_deadline(deadline)\n"
                    "        return value\n"
                    "    return None\n\n"
                )
            ),
        ),
    ],
)
def test_hardened_table_semantics_scanner_rejects_red_team_findings(
    finding_id: str,
    raw: bytes,
) -> None:
    del finding_id
    with pytest.raises(readiness.ReadinessContractError):
        exception._validate_table_semantics_module(raw)


def test_hardened_table_semantics_scanner_rejects_opaque_owner_compare() -> None:
    safe = _all_public_table_semantics_source()
    function_start = safe.index(b"def replace_marked_table_text(")
    insertion = safe.index(b"    return None\n", function_start)
    changed = (
        safe[:insertion]
        + b"    observed = owner == selected_text\n"
        + safe[insertion:]
    )
    with pytest.raises(readiness.ReadinessContractError, match="opaque value"):
        exception._validate_table_semantics_module(changed)


def test_hardened_table_semantics_scanner_rejects_opaque_alias_dispatch() -> None:
    safe = _all_public_table_semantics_source()
    function_start = safe.index(b"def prepare_vector_table(")
    validation = b"    item = _validate_plain_table_value(item, deadline)\n"
    insertion = safe.index(validation, function_start) + len(validation)
    changed = (
        safe[:insertion]
        + b"    alias = raw_table\n"
        + b"    observed = alias.callback\n"
        + safe[insertion:]
    )
    with pytest.raises(readiness.ReadinessContractError, match="opaque value"):
        exception._validate_table_semantics_module(changed)


@pytest.mark.parametrize(
    "raw",
    [
        b"from app.services.running_regions import project_running_regions\n",
        b"from app.services.source_text_alignment import _refresh_table\n",
        b"from app.services.unlisted_phase04_helper import mutate_table\n",
        b'def replay_table_semantics(table):\n    return __import__("os")\n',
        b"import subprocess\ndef replay_table_semantics(table):\n"
        b"    return subprocess.run([])\n",
        b"import time\ndef replay_table_semantics(table):\n"
        b"    time.sleep(1)\n    return table\n",
        b"from time import sleep as wait\n"
        b"def replay_table_semantics(table):\n    wait(1)\n    return table\n",
        b"from io import open as table_stream\n"
        b"def replay_table_semantics(table):\n"
        b"    return table_stream('/tmp/out', 'w')\n",
        b"def replay_table_semantics(table):\n"
        b"    return object.__subclasses__()\n",
        b"def replay_table_semantics(table):\n"
        b"    return table['callback']()\n",
        b"print('table import side effect')\n"
        b"def replay_table_semantics(table):\n    return table\n",
    ],
)
def test_hardened_table_semantics_scanner_rejects_out_of_scope_code(
    raw: bytes,
) -> None:
    with pytest.raises(readiness.ReadinessContractError):
        exception._validate_table_semantics_module(raw)


@pytest.mark.parametrize(
    "injection",
    [
        "    const runningRegion = item.running_regions;\n",
        "    eval(item.value);\n",
        "    fetch('/leak');\n",
        '    globalThis["fe" + "tch"]("/leak");\n',
        "    (0, eval)(item.value);\n",
        '    return ({}).constructor.constructor("return 1")();\n',
        '    window["open"]("https://example.invalid");\n',
        "    return <div dangerouslySetInnerHTML={{ __html: item.html }} />;\n",
    ],
)
def test_hardened_frontend_table_branch_rejects_unsafe_scope(
    injection: str,
) -> None:
    frontend = (PROJECT_ROOT / "frontend/app/clearleaf-workspace.tsx").read_bytes()
    marker = b'  if (type === "table") {\n'
    changed = frontend.replace(marker, marker + injection.encode("utf-8"), 1)
    with pytest.raises(readiness.ReadinessContractError, match="scope differs"):
        exception._validate_hardened_phase04_frontend(changed, helper_raw=None)


@pytest.mark.parametrize(
    "capability_read",
    [
        "process.env;\n",
        "Deno.env;\n",
        "Bun.env;\n",
        "fs.promises;\n",
        "sessionStorage.length;\n",
        "localStorage.length;\n",
        "indexedDB;\n",
        "caches;\n",
        "cookieStore;\n",
        "performance.now;\n",
        "crypto.subtle;\n",
        "chrome.runtime;\n",
        "browser.runtime;\n",
    ],
)
def test_hardened_frontend_rejects_property_only_global_capability_reads(
    capability_read: str,
) -> None:
    with pytest.raises(readiness.ReadinessContractError, match="scope differs"):
        exception._validate_phase04_frontend_text(
            capability_read,
            label="hardened Phase 04 frontend table branch",
        )


def test_hardened_frontend_capability_roots_keep_unrelated_words_safe() -> None:
    safe = (
        "const processional = String(item);\n"
        "const cryptogram = String(processional);\n"
        "const performanceReview = String(cryptogram);\n"
        "const browserWidth = Number(value);\n"
        "return String(browserWidth) + performanceReview;\n"
    )
    exception._validate_phase04_frontend_text(
        safe,
        label="hardened Phase 04 frontend table branch",
    )


@pytest.mark.parametrize(
    ("finding_id", "injection"),
    [
        ("FE-01", '    self["fe" + "tch"](item.value);\n'),
        (
            "FE-02",
            '    Reflect.get(self, "fe" + "tch")(item.value);\n',
        ),
        ("FE-03", "    setTimeout(item.value, 0);\n"),
        (
            "FE-04",
            "    const image = new Image(); image.src = item.value;\n",
        ),
        (
            "FE-05",
            '    const name = "con" + "structor"; self[name](item.value);\n',
        ),
        ("FE-06", "    import/*comment*/(item.value);\n"),
        ("FE-07", "    <img src={item.value} />;\n"),
        ("FE-08", "    localStorage.setItem('table', item.value);\n"),
        (
            "FE-09",
            "    new BroadcastChannel('table').postMessage(item.value);\n",
        ),
        ("FE-10", r"    global\u0054his;" + "\n"),
        ("FE-11", '    self["doc" + "ument"];\n'),
        ("FE-12", '    self["inner" + "HTML"] = item.value;\n'),
        ("FE-OPTIONAL-MEMBER", "    item?.value;\n"),
        ("FE-CALL-RESULT-MEMBER", "    getRows().values();\n"),
        ("FE-PAREN-CALL-RESULT-MEMBER", "    (getRows()).values();\n"),
        ("FE-CALL-RESULT-INDEX", "    getRows()[0];\n"),
        (
            "FE-FUNCTION-ALIAS",
            "    const map = Function; const find = map(item.value); "
            "return find();\n",
        ),
        ("FE-TS-NONNULL-COMPUTED", "    item![item.value];\n"),
        (
            "FE-REBIND-LOCAL-CALLABLE",
            "    function renderRows(value) { return value; } "
            "renderRows = String; return renderRows(item);\n",
        ),
        (
            "FE-MUTABLE-ARROW-CALLABLE",
            "    let find = (value) => value; return find(item);\n",
        ),
        (
            "FE-CODE-POINT-ESCAPE",
            r"    globalThi\u{0073}.fetc\u{0068}(item.value);" + "\n",
        ),
        (
            "FE-TS-NONNULL-CALL",
            "    const callback = item.callback; callback!(item);\n",
        ),
        (
            "FE-TS-GENERIC-CALL",
            "    type table = unknown; const callback = item.callback; "
            "callback<table>(item);\n",
        ),
        (
            "FE-TAGGED-TEMPLATE-CALL",
            "    const callback = item.callback; callback`payload`;\n",
        ),
    ],
)
def test_hardened_frontend_rejects_all_red_team_findings(
    finding_id: str,
    injection: str,
) -> None:
    del finding_id
    frontend = (PROJECT_ROOT / "frontend/app/clearleaf-workspace.tsx").read_bytes()
    marker = b'  if (type === "table") {\n'
    changed = frontend.replace(marker, marker + injection.encode("utf-8"), 1)
    with pytest.raises(readiness.ReadinessContractError):
        exception._validate_hardened_phase04_frontend(changed, helper_raw=None)


def test_hardened_frontend_helper_accepts_only_exact_public_function() -> None:
    safe = (
        "export function readTableSemantics(item: unknown) {\n"
        "  if (!item) { return null; }\n"
        "  return null;\n"
        "}\n"
    )
    exception._validate_phase04_frontend_text(
        safe,
        label="hardened Phase 04 frontend helper",
    )
    exception._validate_phase04_frontend_helper_surface(safe)

    safe_with_local_callable = (
        "export function readTableSemantics(item: unknown) {\n"
        "  const render = (value: unknown) => String(value);\n"
        "  if (!item) { return null; }\n"
        "  return render(item);\n"
        "}\n"
    )
    exception._validate_phase04_frontend_text(
        safe_with_local_callable,
        label="hardened Phase 04 frontend helper",
    )
    exception._validate_phase04_frontend_helper_surface(safe_with_local_callable)

    changed = safe + "export function sendTable(item: unknown) { return item; }\n"
    with pytest.raises(readiness.ReadinessContractError, match="public surface"):
        exception._validate_phase04_frontend_helper_surface(changed)


@pytest.mark.parametrize(
    ("finding_id", "source"),
    [
        (
            "FE-EXPORT-ASYNC",
            "export async function readTableSemantics(item: unknown) { "
            "return null; }\n",
        ),
        (
            "FE-EXPORT-DEFAULT",
            "export default function readTableSemantics(item: unknown) { "
            "return null; }\n",
        ),
        (
            "FE-EXPORT-LIST",
            "function readTableSemantics(item: unknown) { return null; }\n"
            "export { readTableSemantics };\n",
        ),
        (
            "FE-EXPORT-ADDITIONAL",
            "export function readTableSemantics(item: unknown) { "
            "return null; }\nexport default readTableSemantics;\n",
        ),
        (
            "FE-COMMONJS-MODULE",
            "export function readTableSemantics(item: unknown) { "
            "return null; }\nmodule.exports = readTableSemantics;\n",
        ),
        (
            "FE-COMMONJS-EXPORTS",
            "export function readTableSemantics(item: unknown) { "
            "return null; }\nexports.helper = readTableSemantics;\n",
        ),
    ],
)
def test_hardened_frontend_helper_rejects_nonexact_export_forms(
    finding_id: str,
    source: str,
) -> None:
    del finding_id
    with pytest.raises(readiness.ReadinessContractError, match="public surface"):
        exception._validate_phase04_frontend_helper_surface(source)


@pytest.mark.parametrize(
    "source",
    [
        "export function readTableSemantics(item: unknown) { "
        "return <img src={item} />; }\n",
        "export function readTableSemantics(item: unknown) { "
        "return <table onClick={() => item}><tbody /></table>; }\n",
        "export function readTableSemantics(item: unknown) { "
        "return <table {...item}><tbody /></table>; }\n",
        "export function readTableSemantics(item: unknown) { "
        "return <table {  ...item}><tbody /></table>; }\n",
    ],
)
def test_hardened_frontend_helper_rejects_resource_event_and_spread_jsx(
    source: str,
) -> None:
    with pytest.raises(readiness.ReadinessContractError):
        exception._validate_phase04_frontend_text(
            source,
            label="hardened Phase 04 frontend helper",
        )


def test_hardened_frontend_accepts_frozen_calls_and_acyclic_owned_values() -> None:
    main_branch = (
        "if (Boolean(item)) {\n"
        "  const count = Number(value);\n"
        "  const label = String(count);\n"
        "  const semantics = readTableSemantics(item);\n"
        "  const gated = gateTableCandidates(semantics);\n"
        "  return renderValidatedTextRunOverlay("
        "textRunSemantics, [0], item.id) ?? label;\n"
        "}\n"
    )
    exception._validate_phase04_frontend_text(
        main_branch,
        label="hardened Phase 04 frontend table branch",
    )

    helper = (
        "export function readTableSemantics(item: unknown) {\n"
        "  const normalize = (value: unknown) => String(value);\n"
        "  const render = (value: unknown) => normalize(value);\n"
        "  const rows: unknown[] = [];\n"
        "  const normalizedRows = rows.map((value) => render(value));\n"
        "  if (!Boolean(item) || !Array.isArray(normalizedRows)) return null;\n"
        "  return normalizedRows.join(',');\n"
        "}\n"
    )
    exception._validate_phase04_frontend_text(
        helper,
        label="hardened Phase 04 frontend helper",
    )
    exception._validate_phase04_frontend_helper_surface(helper)


@pytest.mark.parametrize(
    ("binding_form", "source"),
    [
        ("const", "const Boolean = (value: unknown) => value;\n"),
        ("let", "let Number = String;\n"),
        ("var", "var String = Boolean;\n"),
        (
            "parameter",
            "const inspect = (gateTableCandidates: unknown) => "
            "String(gateTableCandidates);\n",
        ),
        ("assignment", "readTableSemantics = String;\n"),
        ("logical-assignment", "Boolean ||= String;\n"),
        ("destructuring-assignment", "({ candidate: Number } = item);\n"),
        ("update", "renderValidatedTextRunOverlay++;\n"),
    ],
)
def test_hardened_frontend_rejects_protected_callable_rebinding(
    binding_form: str,
    source: str,
) -> None:
    del binding_form
    with pytest.raises(
        exception.readiness.ReadinessContractError,
        match="protected callable binding differs",
    ):
        exception._validate_phase04_frontend_text(
            source,
            label="hardened Phase 04 frontend table branch",
        )


@pytest.mark.parametrize(
    ("root_form", "source"),
    [
        (
            "const-shadow",
            "const Object = { values: (value: unknown) => [value] }; "
            "return Object.values(item);\n",
        ),
        (
            "let-shadow",
            "let JSON = { stringify: String }; return JSON.stringify(item);\n",
        ),
        (
            "var-shadow",
            "var Array = { isArray: Boolean }; return Array.isArray(item);\n",
        ),
        (
            "parameter-shadow",
            "const inspect = (JSON: unknown) => JSON.stringify(item); "
            "return inspect(item);\n",
        ),
        ("global-assignment", "Object = item; return Object.values(item);\n"),
        ("logical-assignment", "JSON ??= item; return JSON.stringify(item);\n"),
        ("prefix-update", "++Array; return Array.isArray(item);\n"),
        (
            "destructuring-declaration",
            "const { Object } = item; return Object.values(item);\n",
        ),
        (
            "destructuring-assignment",
            "({ JSON } = item); return JSON.stringify(item);\n",
        ),
        (
            "ts-root-alias",
            "const TablesObject = Object as typeof Object; "
            "return TablesObject.values(item);\n",
        ),
        (
            "direct-ts-cast",
            "return (Object as { values: (value: unknown) => unknown[] })"
            ".values(item);\n",
        ),
        (
            "plain-root-alias",
            "const TablesObject = Object; return TablesObject.values(item);\n",
        ),
        (
            "ts-method-alias",
            "const values = Object.values as (value: unknown) => unknown[]; "
            "return values(item);\n",
        ),
        (
            "object-literal-borrow",
            "const borrowed = { values: Object.values }; "
            "return borrowed.values(item);\n",
        ),
        (
            "typed-inline-parameter-shadow",
            "const rows: unknown[] = []; "
            "return rows.map((Object: unknown): unknown => "
            "Object.values(item));\n",
        ),
        (
            "method-overwrite",
            "Object.values = item.callback; return Object.values(item);\n",
        ),
        (
            "global-root-property",
            "globalThis.Object = item; return Object.values(item);\n",
        ),
    ],
)
def test_hardened_frontend_rejects_shadowed_or_borrowed_static_roots(
    root_form: str,
    source: str,
) -> None:
    del root_form
    with pytest.raises(readiness.ReadinessContractError):
        exception._validate_phase04_frontend_text(
            source,
            label="hardened Phase 04 frontend table branch",
        )


def test_hardened_frontend_accepts_unshadowed_reviewed_static_roots() -> None:
    safe = (
        "const rows = Object.values(item);\n"
        "const keys = Object.keys(item);\n"
        "const entries = Object.entries(item);\n"
        "const encoded = JSON.stringify(rows);\n"
        "if (Array.isArray(rows) && Number.isFinite(keys.length)) {\n"
        "  return encoded;\n"
        "}\n"
        "return String(entries);\n"
    )
    exception._validate_phase04_frontend_text(
        safe,
        label="hardened Phase 04 frontend table branch",
    )


@pytest.mark.parametrize(
    ("hook_form", "source"),
    [
        (
            "self-to-string",
            "const value = { toString: () => String(value) }; "
            "return String(value);\n",
        ),
        (
            "opaque-value-of",
            "const value = { valueOf: item.callback }; return Number(value);\n",
        ),
        (
            "opaque-to-json",
            "const value = { toJSON: item.callback }; "
            "return JSON.stringify(value);\n",
        ),
        (
            "method-hook",
            "const value = { toString() { return String(item); } }; "
            "return String(value);\n",
        ),
        (
            "async-method-hook",
            "const value = { async toString() { return String(item); } }; "
            "return String(value);\n",
        ),
        (
            "generator-method-hook",
            "const value = { *valueOf() { return String(item); } }; "
            "return String(value);\n",
        ),
        (
            "quoted-hook",
            "const value = { 'toJSON': item.callback }; "
            "return JSON.stringify(value);\n",
        ),
        (
            "computed-quoted-hook",
            "const value = { ['toJSON']: item.callback }; "
            "return JSON.stringify(value);\n",
        ),
        (
            "opaque-computed-hook",
            "const hook = String(item); "
            "const value = { [hook]: item.callback }; return String(value);\n",
        ),
        (
            "getter-hook",
            "const value = { get payload() { return item.callback; } }; "
            "return Object.values(value);\n",
        ),
        (
            "comment-interposed-getter-hook",
            "const value = { get /* boundary */ payload() "
            "{ return item.callback; } }; return Object.values(value);\n",
        ),
        (
            "setter-hook",
            "const value = { set payload(next: unknown) { String(next); } }; "
            "return String(value);\n",
        ),
        (
            "symbol-to-primitive",
            "const value = { [Symbol.toPrimitive]: item.callback }; "
            "return String(value);\n",
        ),
        (
            "symbol-iterator",
            "const value = { [Symbol.iterator]: item.callback }; "
            "return Object.values(value);\n",
        ),
    ],
)
def test_hardened_frontend_rejects_implicit_object_coercion_hooks(
    hook_form: str,
    source: str,
) -> None:
    del hook_form
    with pytest.raises(
        readiness.ReadinessContractError,
        match="implicit coercion hook differs",
    ):
        exception._validate_phase04_frontend_text(
            source,
            label="hardened Phase 04 frontend table branch",
        )


def test_hardened_frontend_accepts_plain_object_without_coercion_hooks() -> None:
    safe = (
        "const value = { label: String(item) };\n"
        "return JSON.stringify(value);\n"
    )
    exception._validate_phase04_frontend_text(
        safe,
        label="hardened Phase 04 frontend table branch",
    )


@pytest.mark.parametrize(
    ("graph_form", "source"),
    [
        (
            "direct",
            "const visit = (value: unknown) => visit(value);\n"
            "return visit(item);\n",
        ),
        (
            "mutual",
            "const left = (value: unknown) => right(value);\n"
            "const right = (value: unknown) => left(value);\n"
            "return left(item);\n",
        ),
        (
            "typed-method-self",
            "const visit = (value: unknown): unknown => {\n"
            "  const rows: unknown[] = [];\n"
            "  return rows.map(visit);\n"
            "};\n"
            "return visit(item);\n",
        ),
        (
            "typed-method-mutual",
            "const left = (value: unknown): unknown => {\n"
            "  const rows: unknown[] = [];\n"
            "  return rows.map(right);\n"
            "};\n"
            "const right = (value: unknown): unknown => {\n"
            "  const values: unknown[] = [];\n"
            "  return values.filter(left);\n"
            "};\n"
            "return left(item);\n",
        ),
        (
            "named-default-self",
            "function visit(value: unknown = visit()) { return value; }\n"
            "return visit(item);\n",
        ),
        (
            "named-default-mutual",
            "function left(value: unknown = right()) { return value; }\n"
            "function right(value: unknown = left()) { return value; }\n"
            "return left(item);\n",
        ),
    ],
)
def test_hardened_frontend_rejects_recursive_local_call_graph(
    graph_form: str,
    source: str,
) -> None:
    del graph_form
    with pytest.raises(
        exception.readiness.ReadinessContractError,
        match="callable graph differs",
    ):
        exception._validate_phase04_frontend_text(
            source,
            label="hardened Phase 04 frontend table branch",
        )


def test_hardened_frontend_method_receivers_require_owned_provenance() -> None:
    safe = (
        "const rows: unknown[] = [];\n"
        "const values = rows.map((value) => String(value));\n"
        "return values.join(',');\n"
    )
    exception._validate_phase04_frontend_text(
        safe,
        label="hardened Phase 04 frontend table branch",
    )

    for unsafe in (
        "const rows: unknown[] = []; rows.sort();\n",
        "return mystery.map((value) => String(value));\n",
        "return item.map(String);\n",
        "const rows = item; return rows.map(String);\n",
        "const rows = item.rows; return rows.map(String);\n",
        "const render = (rows: unknown[]) => rows.map(String); "
        "return render([]);\n",
        "const values = Object.values(item); const row = values.at(0); "
        "return row.map(String);\n",
        "const rows: unknown[] = []; rows = item; return rows.map(String);\n",
        "const rows: unknown[] = []; [rows] = [item]; "
        "return rows.map(String);\n",
    ):
        with pytest.raises(
            exception.readiness.ReadinessContractError,
            match="method target differs",
        ):
            exception._validate_phase04_frontend_text(
                unsafe,
                label="hardened Phase 04 frontend table branch",
            )


@pytest.mark.parametrize(
    "source",
    [
        (
            "const visit = (value: unknown): unknown => value; "
            "const alias = visit; const rows: unknown[] = []; "
            "return rows.map(alias);\n"
        ),
        (
            "const visit = (value: unknown): unknown => value; "
            "const rows: unknown[] = []; return rows.map((visit));\n"
        ),
    ],
)
def test_hardened_frontend_rejects_local_callback_alias_variants(
    source: str,
) -> None:
    with pytest.raises(readiness.ReadinessContractError):
        exception._validate_phase04_frontend_text(
            source,
            label="hardened Phase 04 frontend table branch",
        )


@pytest.mark.parametrize(
    "phase05_form",
    [
        "const phase05 = String(item); return phase05;\n",
        "const PHASE_05 = String(item); return PHASE_05;\n",
        "const P05 = String(item); return P05;\n",
        "return String('Phase 05');\n",
        "const phase__0_5 = String(item); return phase__0_5;\n",
        "return String('p 0 5');\n",
        "return String('Phase ' + '05');\n",
        "const table_phase05_enabled = Boolean(item); "
        "return table_phase05_enabled;\n",
        "const tablephase05enabled = Boolean(item); "
        "return tablephase05enabled;\n",
        "const TABLEPHASE05ENABLED = Boolean(item); "
        "return TABLEPHASE05ENABLED;\n",
    ],
)
def test_hardened_frontend_rejects_phase05_boundary_tokens(
    phase05_form: str,
) -> None:
    with pytest.raises(
        readiness.ReadinessContractError,
        match="scope differs",
    ):
        exception._validate_phase04_frontend_text(
            phase05_form,
            label="hardened Phase 04 frontend table branch",
        )


@pytest.mark.parametrize(
    "running_region_form",
    [
        "const runningRegion = Boolean(item); return runningRegion;\n",
        "const runningregions = Boolean(item); return runningregions;\n",
        "const running_Regions = Boolean(item); return running_Regions;\n",
        "const table_runningRegion_enabled = Boolean(item); "
        "return table_runningRegion_enabled;\n",
        "const runningregionenabled = Boolean(item); "
        "return runningregionenabled;\n",
        "const runningregionsenabled = Boolean(item); "
        "return runningregionsenabled;\n",
        "const tablerunningregionenabled = Boolean(item); "
        "return tablerunningregionenabled;\n",
        "const TABLERUNNINGREGIONSENABLED = Boolean(item); "
        "return TABLERUNNINGREGIONSENABLED;\n",
        "return String('Running - Regions');\n",
        "return String('running' + 'Region');\n",
    ],
)
def test_hardened_frontend_rejects_running_region_boundary_tokens(
    running_region_form: str,
) -> None:
    with pytest.raises(
        readiness.ReadinessContractError,
        match="scope differs",
    ):
        exception._validate_phase04_frontend_text(
            running_region_form,
            label="hardened Phase 04 frontend table branch",
        )


@pytest.mark.parametrize(
    "body",
    [
        'return String("Ph" + "ase05");\n',
        'const parts = ["Ph", "ase05"]; return parts.join("");\n',
        'const left = "Ph"; const right = "ase05"; return left + right;\n',
        "return String(`Ph` + `ase05`);\n",
        'return String("run" + "ningRegion");\n',
        'return String("run" + "ning" + "Regions");\n',
        'return String("tablePh" + "ase05Enabled");\n',
        'return String("tab" + "lephase05enabled");\n',
        'return String("tableRun" + "ningRegionEnabled");\n',
        'return String("Ph" + "ase" + 5);\n',
        'return String("P" + 0 + 5);\n',
        'return String("Ph" + "ase" + 0x5);\n',
        'return String("Ph" + "ase" + 5.0);\n',
        'return String("Ph" + "ase" + 5n);\n',
        'return String("Ph" /* split */ + "ase05");\n',
        'return String("Phase " + 10 / 2);\n',
        'return String("xrunningRegion").slice(1);\n',
        'return String("50P"[2] + "50P"[1] + "50P"[0]);\n',
        'const value = "50P"; return String(value[2] + value[1] + value[0]);\n',
        'const value = String("50P"); '
        'return String(value.at(2) + value.at(1) + value.at(0));\n',
        'const value = String("05Phase"); '
        'return String(value.slice(2) + value.slice(0, 2));\n',
        'const value = ["50P"]; '
        'return String(value[0][2] + value[0][1] + value[0][0]);\n',
        'const left = "0P"; const right = "5"; '
        'return String(left[1] + left[0] + right[0]);\n',
        'return String("OP"[1] + "x0"[1] + "x5"[1]);\n',
        'const a = String("OP"); const b = String("x0"); '
        'const c = String("x5"); '
        'return String(a.at(1) + b.at(1) + c.at(1));\n',
        'const a = String("xP"); const b = String("x0"); '
        'const c = String("x5"); '
        'return String(a.slice(1) + b.slice(1) + c.slice(1));\n',
        'const a = String("xrunning"); const b = String("xRegion"); '
        'return String(a.slice(1) + b.slice(1));\n',
        'const n = Number("10") / Number("2"); '
        'return String("phase" + n);\n',
        'const pattern = /[//]/; return String("Ph" + "ase05");\n',
        'if (Boolean(item)) /[//]/.test("x"); '
        'return String("Ph" + "ase05");\n',
        'if (Boolean(item)) { }\n/[a//]/.test("x"); '
        'return String("Ph" + "ase05");\n',
        'if (Boolean(item)) { } /[a//]/.test("x"); '
        'return String("Ph" + "ase05");\n',
        'return Boolean(item)</a[//]/.test("x"); '
        'return String("Ph" + "ase05");\n',
        r'return String("Ph\ase05");' "\n",
        'return String("Ph\\\nase05");\n',
        r'return String("\120\150\141\163\145\060\065");' "\n",
    ],
)
def test_hardened_frontend_rejects_reconstructed_scope_on_both_surfaces(
    body: str,
) -> None:
    with pytest.raises(readiness.ReadinessContractError, match="scope differs"):
        exception._validate_phase04_frontend_text(
            body,
            label="hardened Phase 04 frontend table branch",
        )
    helper = (
        "export function readTableSemantics(item: unknown) {\n"
        f"  {body}"
        "}\n"
    )
    with pytest.raises(readiness.ReadinessContractError, match="scope differs"):
        exception._validate_phase04_frontend_helper_surface(helper)


@pytest.mark.parametrize(
    "source",
    [
        "total / count",
        "(left + right) / count",
        "rows[0] / 2",
        "read() / 2",
        "total /* bounded */ / /* bounded */ count",
        "total /= count",
    ],
)
def test_hardened_frontend_lexer_preserves_proven_division(source: str) -> None:
    assert exception._phase04_frontend_literal_values(source) == ()


@pytest.mark.parametrize(
    "source",
    [
        "/value/u",
        "const pattern = /value/u",
        "return /value/u",
        "throw /value/u",
        "if (item) /value/u",
        "while (item) /value/u",
        "for (;;) /value/u",
        "with (item) /value/u",
        "switch (item) /value/u",
        "catch (error) /value/u",
        "if (item) { } /value/u",
        "else /value/u",
        "value / /pattern/u",
        "value /= /pattern/u",
    ],
)
def test_hardened_frontend_lexer_rejects_regex_context(source: str) -> None:
    with pytest.raises(readiness.ReadinessContractError, match="scope differs"):
        exception._phase04_frontend_literal_values(source)


def test_hardened_frontend_lexer_never_uses_prefix_slices() -> None:
    class NoPrefixSlice(str):
        def __getitem__(self, key: object) -> str:
            if (
                isinstance(key, slice)
                and key.start is None
                and isinstance(key.stop, int)
            ):
                raise AssertionError("quadratic prefix slice")
            return super().__getitem__(key)  # type: ignore[index]

    with pytest.raises(readiness.ReadinessContractError, match="scope differs"):
        exception._phase04_frontend_literal_values(
            NoPrefixSlice("value/" * 4_097)
        )


def test_hardened_frontend_lexer_requires_proven_matching_jsx_closures() -> None:
    assert exception._phase04_frontend_literal_values(
        "return <table><tbody /></table>;",
        allow_jsx=True,
    ) == ()

    for source, allow_jsx in (
        ("return <table><tbody></table></tbody>;", True),
        ("return </table>;", False),
        ("return Boolean(item)</a[//]/.test('x');", True),
    ):
        with pytest.raises(readiness.ReadinessContractError, match="scope differs"):
            exception._phase04_frontend_literal_values(
                source,
                allow_jsx=allow_jsx,
            )


def test_hardened_frontend_lexer_bounds_cumulative_jsx_lookahead() -> None:
    overlapping = "return " + "<table =" * 400 + "/>;"
    nested = (
        "return "
        + "<table key={" * 300
        + "null"
        + "}>" * 300
        + "</table>" * 300
        + ";"
    )
    for source in (overlapping, nested):
        with pytest.raises(readiness.ReadinessContractError, match="scope differs"):
            exception._phase04_frontend_literal_values(
                source,
                allow_jsx=True,
            )


def test_hardened_frontend_reconstructed_scope_positive_controls() -> None:
    body = (
        'const values: unknown[] = ["metaphase05", '
        '"outrunningregionenabled", "Phase 04", "runbook", "region"];\n'
        'return values.join(",");\n'
    )
    exception._validate_phase04_frontend_text(
        body,
        label="hardened Phase 04 frontend table branch",
    )
    exception._validate_phase04_frontend_helper_surface(
        "export function readTableSemantics(item: unknown) {\n"
        f"  {body}"
        "}\n"
    )


def test_hardened_frontend_literal_reconstruction_limit_fails_closed() -> None:
    excessive = "return [" + ",".join('"x"' for _ in range(4_097)) + "];\n"
    with pytest.raises(readiness.ReadinessContractError, match="scope differs"):
        exception._validate_phase04_frontend_text(
            excessive,
            label="hardened Phase 04 frontend table branch",
        )

    oversized_literal = 'return "' + ("x" * 262_145) + '";\n'
    with pytest.raises(readiness.ReadinessContractError, match="scope differs"):
        exception._validate_phase04_frontend_text(
            oversized_literal,
            label="hardened Phase 04 frontend table branch",
        )

    oversized_source = "x" * (2 * 1024 * 1024 + 1)
    with pytest.raises(readiness.ReadinessContractError, match="scope differs"):
        exception._validate_phase04_frontend_text(
            oversized_source,
            label="hardened Phase 04 frontend table branch",
        )


def test_hardened_frontend_phase05_guard_does_not_match_phase04() -> None:
    safe = (
        "const phase04Label = String('Phase 04');\n"
        "const P04 = String(phase04Label);\n"
        "const metaphase05 = Boolean(P04);\n"
        "const outrunningRegions = Boolean(P04);\n"
        "const outrunningregionenabled = Boolean(metaphase05);\n"
        "const runningRegional = String(outrunningRegions);\n"
        "if (outrunningregionenabled) { return runningRegional; }\n"
        "return runningRegional;\n"
    )
    exception._validate_phase04_frontend_text(
        safe,
        label="hardened Phase 04 frontend table branch",
    )


def test_hardened_frontend_helper_surface_rejects_phase05_boundary() -> None:
    helper = (
        "export function readTableSemantics(item: unknown) {\n"
        "  return String('P05');\n"
        "}\n"
    )
    with pytest.raises(
        readiness.ReadinessContractError,
        match="helper scope differs",
    ):
        exception._validate_phase04_frontend_helper_surface(helper)


def test_hardened_frontend_accepts_owned_callbacks_and_normal_react_map() -> None:
    safe = (
        "const render = (value: unknown) => String(value);\n"
        "const rows: unknown[] = [];\n"
        "const rendered = rows.map(render);\n"
        "const selected = rendered.filter((value) => Boolean(value));\n"
        "const frozen = selected.map(String);\n"
        "const encoded = JSON.stringify(frozen);\n"
        "return <tbody>{frozen.map((row) => "
        "<tr key={String(row)}><td>{row}</td></tr>)}</tbody>;\n"
    )
    exception._validate_phase04_frontend_text(
        safe,
        label="hardened Phase 04 frontend table branch",
    )


@pytest.mark.parametrize(
    ("callback_form", "source"),
    [
        (
            "member-callback",
            "const rows: unknown[] = []; return rows.map(item.callback);\n",
        ),
        (
            "borrowed-binding",
            "const rows: unknown[] = []; const callback = item.callback; "
            "return rows.filter(callback);\n",
        ),
        (
            "json-replacer",
            "const rows: unknown[] = []; "
            "return JSON.stringify(rows, item.callback);\n",
        ),
    ],
)
def test_hardened_frontend_rejects_unowned_callback_dispatch(
    callback_form: str,
    source: str,
) -> None:
    del callback_form
    with pytest.raises(exception.readiness.ReadinessContractError):
        exception._validate_phase04_frontend_text(
            source,
            label="hardened Phase 04 frontend table branch",
        )


@pytest.mark.parametrize(
    ("dispatch_form", "body"),
    [
        (
            "indexed-array",
            "const callbacks = [item.callback]; return callbacks[0](item);",
        ),
        (
            "indexed-object-values",
            "const callbacks = Object.values(item); return callbacks[0](item);",
        ),
        (
            "indexed-tuple-literal",
            "return [item.callback][0](item);",
        ),
        (
            "indexed-parenthesized",
            "const callbacks = [item.callback]; return (callbacks[0])(item);",
        ),
        (
            "indexed-method",
            "const callbacks = [item.callback]; return callbacks[0].map(String);",
        ),
        (
            "nested-property-method",
            "const callbacks = { first: item.callback }; "
            "return callbacks.first.map(String);",
        ),
        (
            "indexed-alias",
            "const callbacks = [item.callback]; const callback = callbacks[0]; "
            "return callback(item);",
        ),
        (
            "indexed-destructure",
            "const callbacks = [item.callback]; const [callback] = callbacks; "
            "return callback(item);",
        ),
        (
            "array-destructuring-overwrite",
            "const callback = (value: unknown) => value; "
            "[callback] = [item.callback]; return callback(item);",
        ),
        (
            "tuple-destructuring-overwrite",
            "const callback = (value: unknown) => value; "
            "const callbacks = [item.callback]; [callback] = callbacks; "
            "return callback(item);",
        ),
        (
            "object-destructuring-overwrite",
            "const callback = (value: unknown) => value; "
            "({ callback } = item); return callback(item);",
        ),
        (
            "local-callable-shadow",
            "const callback = (value: unknown) => value; "
            "const callbacks = [item.callback]; "
            "return callbacks.map((callback) => callback(item));",
        ),
    ],
)
def test_hardened_frontend_rejects_indexed_and_aliased_callback_dispatch(
    dispatch_form: str,
    body: str,
) -> None:
    del dispatch_form
    source = (
        "export function readTableSemantics(item: unknown) {\n"
        f"  {body}\n"
        "}\n"
    )
    with pytest.raises(readiness.ReadinessContractError):
        exception._validate_phase04_frontend_text(
            source,
            label="hardened Phase 04 frontend helper",
        )


@pytest.mark.parametrize(
    ("mutation_form", "source"),
    [
        ("self", "self.name = String(item);\n"),
        ("top", "top.name = String(item);\n"),
        ("parent", "parent.name = String(item);\n"),
        ("frames", "frames[0].name = String(item);\n"),
        ("opener", "opener.name = String(item);\n"),
        ("property", "item.value = String(value);\n"),
        ("index-update", "const rows = []; rows[0]++;\n"),
        (
            "destructured-property",
            "({ value: item.value } = { value });\n",
        ),
    ],
)
def test_hardened_frontend_rejects_browser_roots_and_property_mutation(
    mutation_form: str,
    source: str,
) -> None:
    del mutation_form
    with pytest.raises(exception.readiness.ReadinessContractError):
        exception._validate_phase04_frontend_text(
            source,
            label="hardened Phase 04 frontend table branch",
        )


def test_hardened_frontend_helper_allows_only_types_beside_public_function() -> None:
    safe = (
        "type CellText = string | null;\n"
        "interface TableView { rows: CellText[]; }\n"
        "export function readTableSemantics(item: unknown) {\n"
        "  if (!item) return null;\n"
        "  return null;\n"
        "}\n"
    )
    exception._validate_phase04_frontend_text(
        safe,
        label="hardened Phase 04 frontend helper",
    )
    exception._validate_phase04_frontend_helper_surface(safe)

    for runtime_tail in (
        "throw String('blocked');\n",
        "String('executed');\n",
        "const executed = String('executed');\n",
        "type Hidden = string\nthrow String('blocked');\n",
    ):
        changed = safe + runtime_tail
        with pytest.raises(
            exception.readiness.ReadinessContractError,
            match="module scope differs",
        ):
            exception._validate_phase04_frontend_helper_surface(changed)


@pytest.mark.parametrize(
    ("implicit_form", "source"),
    [
        ("decorator", "@sealed\nclass TableView {}\n"),
        ("array-spread", "const values = [...item];\n"),
        ("object-spread", "const value = { ...item };\n"),
        ("using", "using tableResource = item;\n"),
    ],
)
def test_hardened_frontend_rejects_implicit_invocation_syntax(
    implicit_form: str,
    source: str,
) -> None:
    del implicit_form
    with pytest.raises(exception.readiness.ReadinessContractError):
        exception._validate_phase04_frontend_text(
            source,
            label="hardened Phase 04 frontend table branch",
        )


@pytest.mark.parametrize(
    ("syntax_form", "source"),
    [
        ("computed", "return item /* boundary */ [ value ];\n"),
        ("optional", "return item /* boundary */ ? /* boundary */ . value;\n"),
        (
            "call-result-member",
            "const readRows = () => [];\n"
            "return readRows /* boundary */ () /* boundary */ . values();\n",
        ),
        (
            "jsx-spread",
            "return <table { /* boundary */ ...item}><tbody /></table>;\n",
        ),
    ],
)
def test_hardened_frontend_rejects_comment_interposed_forms(
    syntax_form: str,
    source: str,
) -> None:
    del syntax_form
    with pytest.raises(exception.readiness.ReadinessContractError):
        exception._validate_phase04_frontend_text(
            source,
            label="hardened Phase 04 frontend table branch",
        )


@pytest.mark.parametrize(
    ("surface", "source"),
    [
        ("main-module", "module /* boundary */ . exports = item;\n"),
        ("main-exports", "exports /* boundary */ . table = item;\n"),
        (
            "helper-module",
            "export function readTableSemantics(item: unknown) { "
            "module.exports = item; return null; }\n",
        ),
        (
            "helper-exports",
            "export function readTableSemantics(item: unknown) { "
            "exports.table = item; return null; }\n",
        ),
    ],
)
def test_hardened_frontend_rejects_commonjs_in_both_surfaces(
    surface: str,
    source: str,
) -> None:
    label = (
        "hardened Phase 04 frontend helper"
        if surface.startswith("helper-")
        else "hardened Phase 04 frontend table branch"
    )
    with pytest.raises(exception.readiness.ReadinessContractError):
        exception._validate_phase04_frontend_text(source, label=label)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"approval":{},"approval":{}}',
        b'{"maximum_overrun_fraction":NaN}',
        b'{"observed_seconds":Infinity}',
    ],
)
def test_waiver_loader_rejects_duplicate_and_nonfinite_json(raw: bytes) -> None:
    with pytest.raises(
        (metrics.MetricsExecutionError, readiness.ReadinessContractError),
        match="strict JSON",
    ):
        exception._strict_json(raw, "latency waiver")


def test_waiver_rejects_noncanonical_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    waiver = _waiver()
    compact = json.dumps(
        waiver,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    original = exception._read_bound_file

    def read_bound_file(
        root: Path,
        path: str,
        *,
        maximum_bytes: int,
        label: str,
    ) -> tuple[bytes, Any]:
        raw, binding = original(
            root,
            path,
            maximum_bytes=maximum_bytes,
            label=label,
        )
        if path == str(exception.WAIVER_PATH):
            return compact, binding
        return raw, binding

    monkeypatch.setattr(exception, "_read_bound_file", read_bound_file)
    with pytest.raises(readiness.ReadinessContractError, match="bytes differ"):
        exception.validate_performance_exception(
            PROJECT_ROOT,
            today=date(2026, 8, 3),
        )


def test_waiver_rejects_changed_or_missing_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiver = _waiver()
    waiver["approval"]["statements"][1] = "accept any performance failure"
    _serve_sealed_waiver(monkeypatch, waiver)

    with pytest.raises(readiness.ReadinessContractError, match="approval differs"):
        exception.validate_performance_exception(
            PROJECT_ROOT,
            today=date(2026, 8, 3),
        )


def test_waiver_rejects_expiry() -> None:
    with pytest.raises(readiness.ReadinessContractError, match="expired"):
        exception.validate_performance_exception(
            PROJECT_ROOT,
            today=date(2026, 9, 3),
        )


def test_waiver_cannot_extend_the_authorized_review_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiver = _waiver()
    waiver["expiry"]["review_due_on"] = "2099-09-02"
    _serve_sealed_waiver(monkeypatch, waiver)

    with pytest.raises(readiness.ReadinessContractError, match="expired"):
        exception.validate_performance_exception(
            PROJECT_ROOT,
            today=date(2026, 9, 3),
        )


def test_not_waived_must_remain_a_json_array(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiver = _waiver()
    waiver["not_waived"] = {
        field: True for field in exception.EXPECTED_NOT_WAIVED
    }
    _serve_sealed_waiver(monkeypatch, waiver)

    with pytest.raises(readiness.ReadinessContractError, match="exclusions differ"):
        exception.validate_performance_exception(
            PROJECT_ROOT,
            today=date(2026, 8, 3),
        )


def test_waiver_rejects_default_on_or_broader_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiver = _waiver()
    waiver["operational_constraints"]["feature_flag_default"] = True
    _serve_sealed_waiver(monkeypatch, waiver)

    with pytest.raises(readiness.ReadinessContractError, match="rollback differs"):
        exception.validate_performance_exception(
            PROJECT_ROOT,
            today=date(2026, 8, 3),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("candidate_specific", 1),
        ("observed_seconds", "0.05094675"),
        ("maximum_overrun_fraction", True),
    ],
)
def test_exception_scope_rejects_json_type_confusion(
    field: str,
    value: Any,
) -> None:
    waiver = _waiver()
    primary = _artifact(waiver["primary_candidate"])
    scope = deepcopy(waiver["exception_scope"])
    scope[field] = value

    with pytest.raises(readiness.ReadinessContractError):
        exception._validate_primary_candidate(primary, scope)


def test_primary_candidate_cannot_expand_to_more_than_five_percent() -> None:
    waiver = _waiver()
    primary = deepcopy(_artifact(waiver["primary_candidate"]))
    target = primary["running_region_projection"]["targets"]["ny-timetable"]
    target["summary"]["latency_p95_seconds"] = 0.052500000001
    scope = deepcopy(waiver["exception_scope"])
    scope.update(
        {
            "observed_seconds": 0.052500000001,
            "overrun_seconds": 0.002500000001,
            "overrun_fraction": 0.05000000002,
        }
    )

    with pytest.raises(readiness.ReadinessContractError, match="not close"):
        exception._validate_primary_candidate(primary, scope)


def test_complete_companion_cannot_waive_memory() -> None:
    waiver = _waiver()
    companion = deepcopy(_artifact(waiver["complete_companion"]))
    target = companion["paired_parser"]["targets"]["uber-earnings"]
    target["peak_rss_delta_bytes"] = metrics.PEAK_RSS_DELTA_CEILING_BYTES + 1

    with pytest.raises(readiness.ReadinessContractError, match="paired gate"):
        exception._validate_complete_companion(companion)


def test_complete_companion_passes_the_full_historical_artifact_schema() -> None:
    waiver = _waiver()
    companion = deepcopy(_artifact(waiver["complete_companion"]))
    existing_paths = metrics.discover_existing_metrics_artifact_paths(PROJECT_ROOT)
    (
        _,
        _,
        current_input_custody,
        current_m0_identity,
        current_predecessor_outputs,
        current_code,
        current_dependency_custody,
        observed_history,
    ) = metrics._collect_repository_custody(
        PROJECT_ROOT,
        code_paths=tuple(sorted(metrics.REQUIRED_CODE_PATHS)),
        expected_existing_paths=existing_paths,
    )

    exception._validate_historical_artifact(
        companion,
        current_code=current_code,
        current_dependency_custody=current_dependency_custody,
        current_input_custody=current_input_custody,
        current_m0_identity=current_m0_identity,
        current_predecessor_outputs=current_predecessor_outputs,
        observed_history=observed_history,
    )

    companion["quality"]["page_identity_exact_count"] = 29
    companion["semantic_sha256"] = metrics._artifact_semantic_sha256(companion)
    with pytest.raises(readiness.ReadinessContractError):
        exception._validate_historical_artifact(
            companion,
            current_code=current_code,
            current_dependency_custody=current_dependency_custody,
            current_input_custody=current_input_custody,
            current_m0_identity=current_m0_identity,
            current_predecessor_outputs=current_predecessor_outputs,
            observed_history=observed_history,
        )


@pytest.mark.parametrize(
    ("section", "mutation", "message"),
    [
        ("expiry", {"extra": "open schema"}, "expiry keys differ"),
        (
            "deferred_work",
            {"required_outcome": "ignore the exception forever"},
            "deferred work differs",
        ),
        ("hosted_usage", {"hosted_requests": False}, "hosted use differs"),
    ],
)
def test_waiver_rejects_open_or_type_confused_nested_contracts(
    monkeypatch: pytest.MonkeyPatch,
    section: str,
    mutation: dict[str, Any],
    message: str,
) -> None:
    waiver = _waiver()
    waiver[section].update(mutation)
    _serve_sealed_waiver(monkeypatch, waiver)

    with pytest.raises(readiness.ReadinessContractError, match=message):
        exception.validate_performance_exception(
            PROJECT_ROOT,
            today=date(2026, 8, 3),
        )


def test_waiver_rejects_changed_failed_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiver = _waiver()
    waiver["failed_history"]["artifact_count"] = 50
    _serve_sealed_waiver(monkeypatch, waiver)

    with pytest.raises(readiness.ReadinessContractError, match="history differs"):
        exception.validate_performance_exception(
            PROJECT_ROOT,
            today=date(2026, 8, 3),
        )


def test_waiver_rejects_candidate_identity_substitution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiver = _waiver()
    waiver["primary_candidate"]["generated_at"] = "2026-08-03T13:02:12+05:30"
    _serve_sealed_waiver(monkeypatch, waiver)

    with pytest.raises(readiness.ReadinessContractError, match="identity differs"):
        exception.validate_performance_exception(
            PROJECT_ROOT,
            today=date(2026, 8, 3),
        )


def test_bound_reader_rejects_symlinked_waivers(tmp_path: Path) -> None:
    for index, relative_path in enumerate(
        (
            exception.WAIVER_PATH,
            exception.RENEWAL_WAIVER_PATH,
            exception.PHASE04_RENEWAL_WAIVER_PATH,
            exception.HARDENED_PHASE04_RENEWAL_WAIVER_PATH,
        )
    ):
        repository_root = tmp_path / f"repository-{index}"
        evidence = repository_root / relative_path.parent
        evidence.mkdir(parents=True)
        outside = tmp_path / f"outside-{index}.json"
        outside.write_text("{}\n", encoding="utf-8")
        (repository_root / relative_path).symlink_to(outside)

        with pytest.raises(
            (metrics.MetricsExecutionError, readiness.ReadinessContractError),
            match="custody differs",
        ):
            exception._read_bound_file(
                repository_root,
                str(relative_path),
                maximum_bytes=exception.WAIVER_MAXIMUM_BYTES,
                label="latency waiver",
            )


def test_waiver_detects_repository_reobservation_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = metrics._collect_repository_custody
    observations = 0

    def collect_repository_custody(*args: Any, **kwargs: Any) -> Any:
        nonlocal observations
        result = original(*args, **kwargs)
        observations += 1
        if observations == 2:
            changed = list(result)
            current_code = deepcopy(changed[5])
            first_path = min(current_code)
            current_code[first_path]["size_bytes"] += 1
            changed[5] = current_code
            return tuple(changed)
        return result

    monkeypatch.setattr(metrics, "_collect_repository_custody", collect_repository_custody)
    monkeypatch.setattr(
        exception,
        "_validate_semantic_isolation_terminal_approval",
        lambda *args, **kwargs: [],
    )
    with pytest.raises(readiness.ReadinessContractError, match="changed"):
        exception.validate_performance_exception(
            PROJECT_ROOT,
            today=date(2026, 8, 3),
        )


def test_waivers_detect_second_read_binding_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = exception._read_bound_file

    for target in (
        exception.WAIVER_PATH,
        exception.RENEWAL_WAIVER_PATH,
        exception.PHASE04_RENEWAL_WAIVER_PATH,
        exception.HARDENED_PHASE04_RENEWAL_WAIVER_PATH,
    ):
        waiver_reads = 0

        def read_bound_file(
            root: Path,
            path: str,
            *,
            maximum_bytes: int,
            label: str,
        ) -> tuple[bytes, Any]:
            nonlocal waiver_reads
            raw, binding = original(
                root,
                path,
                maximum_bytes=maximum_bytes,
                label=label,
            )
            if path != str(target):
                return raw, binding
            waiver_reads += 1
            if waiver_reads == 2:
                file_binding, directory_bindings = binding
                changed_file_binding = (*file_binding[:-1], file_binding[-1] + 1)
                return raw, (changed_file_binding, directory_bindings)
            return raw, binding

        with monkeypatch.context() as patcher:
            patcher.setattr(exception, "_read_bound_file", read_bound_file)
            patcher.setattr(
                exception,
                "_validate_semantic_isolation_terminal_approval",
                lambda *args, **kwargs: [],
            )
            with pytest.raises(readiness.ReadinessContractError, match="changed"):
                exception.validate_performance_exception(
                    PROJECT_ROOT,
                    today=date(2026, 8, 3),
                )


def test_existing_waiver_paths_refuse_exclusive_create() -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)

    for relative_path in (
        exception.WAIVER_PATH,
        exception.RENEWAL_WAIVER_PATH,
        exception.PHASE04_RENEWAL_WAIVER_PATH,
        exception.HARDENED_PHASE04_RENEWAL_WAIVER_PATH,
    ):
        path = PROJECT_ROOT / relative_path
        before = path.read_bytes()
        with pytest.raises(FileExistsError):
            descriptor = os.open(path, flags, 0o600)
            os.close(descriptor)
        assert path.read_bytes() == before
