"""Focused mutation tests for the phase-latency P03 continuity guard."""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from tests.fixtures.phase_03.running_regions import contract as readiness
from tests.fixtures.phase_latency import p03_continuity as continuity


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _offline_dependency_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    monkeypatch.setenv("TOKENIZERS_PARALLELISM", "false")


def _renewal() -> dict[str, Any]:
    return json.loads(
        (PROJECT_ROOT / continuity.RENEWAL_RECORD_PATH).read_text(encoding="utf-8")
    )


def _custody() -> dict[str, Any]:
    return json.loads(
        (PROJECT_ROOT / continuity.CUSTODY_RECORD_PATH).read_text(encoding="utf-8")
    )


def test_live_phase_latency_continuity_guard_passes_without_strict_pass_claim() -> None:
    result = continuity.validate_latency_continuity_renewal(PROJECT_ROOT)

    assert result["attempt_48"] == continuity.EXPECTED_ATTEMPT_FACTS
    assert result["failed_history"] == continuity.EXPECTED_FAILED_HISTORY
    assert result["unchanged_ceilings"] == continuity.EXPECTED_CEILINGS
    assert result["production_latency_flags"] == []
    assert result["production_latency_modules"] == []
    assert result["rollback_action"] == "stop_disposable_benchmark_worker"
    assert result["strict_current_artifact_pass"] is False
    assert result["production_approval"] is False


@pytest.mark.parametrize(
    ("path", "replacement", "message"),
    [
        (
            ("immutable_attempt_48", "observed_seconds"),
            "0.052500000",
            "attempt-48 facts differ",
        ),
        (
            ("immutable_attempt_48", "maximum_candidate_specific_bound"),
            "0.06",
            "attempt-48 facts differ",
        ),
        (
            ("unchanged_ceilings", "running_region_projection_p95_seconds"),
            "0.052500000",
            "ceilings differ",
        ),
        (
            ("default_off_rollback", "running_region_default"),
            True,
            "rollback differs",
        ),
        (
            ("claims", "strict_current_artifact_pass"),
            True,
            "claims differ",
        ),
    ],
)
def test_renewal_rejects_scope_widening(
    path: tuple[str, str],
    replacement: Any,
    message: str,
) -> None:
    record = _renewal()
    record[path[0]][path[1]] = replacement

    with pytest.raises(readiness.ReadinessContractError, match=message):
        continuity._validate_renewal_record(record)


def test_renewal_rejects_removed_non_waived_gate() -> None:
    record = _renewal()
    record["non_waived_gates"].remove("rss")

    with pytest.raises(
        readiness.ReadinessContractError,
        match="non-waived gates differ",
    ):
        continuity._validate_renewal_record(record)


def test_renewal_rejects_production_or_phase_boundary_authority() -> None:
    record = _renewal()
    record["scope"]["production_enablement"] = True
    record["scope"]["phase_05_authority"] = True

    with pytest.raises(readiness.ReadinessContractError, match="scope differs"):
        continuity._validate_renewal_record(record)


def test_live_guard_expires_after_review_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        continuity,
        "_current_utc_date",
        lambda: date(2026, 9, 3),
    )
    with pytest.raises(readiness.ReadinessContractError, match="expired"):
        continuity.validate_latency_continuity_renewal(PROJECT_ROOT)


def test_custody_record_rejects_manifest_or_validator_waiver() -> None:
    record = _custody()
    record["historical_validator_policy"]["historical_validators_weakened"] = True

    with pytest.raises(readiness.ReadinessContractError, match="record differs"):
        continuity._validate_custody_record(PROJECT_ROOT, record)


def test_custody_record_rejects_production_latency_hook_claim() -> None:
    record = _custody()
    record["default_off_observation"]["production_latency_runtime_hooks"] = True

    with pytest.raises(readiness.ReadinessContractError, match="record differs"):
        continuity._validate_custody_record(PROJECT_ROOT, record)


def test_dependency_reconciliation_is_only_exact_pytest_marker_delta() -> None:
    continuity._validate_dependency_delta(PROJECT_ROOT, _custody())


@pytest.mark.parametrize("target", ("pyproject.toml", "uv.lock"))
def test_dependency_reconciliation_rejects_any_further_manifest_bytes(
    tmp_path: Path,
    target: str,
) -> None:
    (tmp_path / "pyproject.toml").write_bytes(
        (PROJECT_ROOT / "pyproject.toml").read_bytes()
    )
    (tmp_path / "uv.lock").write_bytes((PROJECT_ROOT / "uv.lock").read_bytes())
    path = tmp_path / target
    path.write_bytes(path.read_bytes() + b"# unauthorized successor delta\n")

    with pytest.raises(
        readiness.ReadinessContractError,
        match="identity differs",
    ):
        continuity._validate_dependency_delta(tmp_path, _custody())


def _copy_app(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    shutil.copytree(PROJECT_ROOT / "app", root / "app")
    return root


def test_running_region_projection_allows_unrelated_source(
    tmp_path: Path,
) -> None:
    root = _copy_app(tmp_path)
    path = root / "app/services/unrelated_successor.py"
    path.write_bytes(b"def unrelated_successor_probe() -> bool:\n    return False\n")

    assert continuity.running_region_integration_projection(root) == (
        continuity.EXPECTED_RUNNING_REGION_INTEGRATION_PROJECTION
    )
    assert continuity._validate_production_latency_isolation(root) is None


def test_app_walk_rejects_symlinked_directory_before_source_selection(
    tmp_path: Path,
) -> None:
    root = _copy_app(tmp_path)
    outside = tmp_path / "outside-app-code"
    outside.mkdir()
    (outside / "neutral.py").write_bytes(b"VALUE = 1\n")
    (root / "app/services/linked_pkg").symlink_to(
        outside,
        target_is_directory=True,
    )

    with pytest.raises(readiness.ReadinessContractError, match="binding differs"):
        continuity.running_region_integration_projection(root)
    with pytest.raises(readiness.ReadinessContractError, match="binding differs"):
        continuity._validate_production_latency_isolation(root)


def test_production_latency_isolation_rejects_latency_package_path(
    tmp_path: Path,
) -> None:
    root = _copy_app(tmp_path)
    package = root / "app/latency"
    package.mkdir()
    (package / "__init__.py").write_bytes(b"VALUE = 1\n")

    with pytest.raises(
        readiness.ReadinessContractError,
        match="production latency module differs",
    ):
        continuity._validate_production_latency_isolation(root)


def test_production_latency_isolation_rejects_latency_bytecode_artifact(
    tmp_path: Path,
) -> None:
    root = _copy_app(tmp_path)
    bytecode = root / "app/services/__pycache__/latency_telemetry.pyc"
    bytecode.parent.mkdir(exist_ok=True)
    bytecode.write_bytes(b"stale-generated-bytecode-control")

    with pytest.raises(
        readiness.ReadinessContractError,
        match="production latency module differs",
    ):
        continuity._validate_production_latency_isolation(root)


def test_app_walk_rejects_entry_overflow_before_sorting_unbounded_input(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    app = root / "app"
    app.mkdir(parents=True)
    for index in range(continuity._MAXIMUM_APP_ENTRIES + 1):
        (app / f"entry-{index:04d}.txt").write_bytes(b"")

    with pytest.raises(
        readiness.ReadinessContractError,
        match="app entry count differs",
    ):
        continuity._validated_app_python_paths(app)


@pytest.mark.parametrize(
    "mutation",
    (
        b'\nprotected_change = "running_regions"\n',
        b'\nprotected_change = "running_" + "regions"\n',
        b"from app.services import running_regions\n",
        b"from app.services.running_regions import project_running_regions\n",
    ),
)
def test_running_region_projection_rejects_direct_or_reconstructed_scope(
    tmp_path: Path,
    mutation: bytes,
) -> None:
    root = _copy_app(tmp_path)
    path = root / "app/services/unrelated_successor.py"
    path.write_bytes(mutation)

    assert continuity.running_region_integration_projection(root) != (
        continuity.EXPECTED_RUNNING_REGION_INTEGRATION_PROJECTION
    )


def test_live_guard_fails_closed_on_running_region_projection_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        continuity,
        "running_region_integration_projection",
        lambda root: {"entry_count": 89, "sha256": "0" * 64},
    )

    with pytest.raises(
        readiness.ReadinessContractError,
        match="semantic/runtime projection differs",
    ):
        continuity.validate_latency_continuity_renewal(PROJECT_ROOT)


def test_running_region_projection_rejects_reachability_wrapper(
    tmp_path: Path,
) -> None:
    root = _copy_app(tmp_path)
    path = root / "app/services/pipeline.py"
    tree = ast.parse(path.read_bytes(), filename="app/services/pipeline.py")
    wrapped = False
    for parent in ast.walk(tree):
        for field, value in ast.iter_fields(parent):
            if not isinstance(value, list):
                continue
            for index, child in enumerate(value):
                if (
                    not wrapped
                    and isinstance(child, ast.If)
                    and "layout_running_regions_enabled" in ast.dump(child.test)
                ):
                    value[index] = ast.If(
                        test=ast.Constant(value=False),
                        body=[child],
                        orelse=[],
                    )
                    wrapped = True
                    break
            if wrapped:
                break
        if wrapped:
            break
    assert wrapped is True
    ast.fix_missing_locations(tree)
    path.write_text(ast.unparse(tree) + "\n", encoding="utf-8")

    assert continuity.running_region_integration_projection(root) != (
        continuity.EXPECTED_RUNNING_REGION_INTEGRATION_PROJECTION
    )


def test_lat_us01_rejects_production_latency_module(tmp_path: Path) -> None:
    root = _copy_app(tmp_path)
    path = root / "app/services/latency_telemetry.py"
    path.write_bytes(b"ENABLED = False\n")

    with pytest.raises(
        readiness.ReadinessContractError,
        match="production latency module differs",
    ):
        continuity._validate_production_latency_isolation(root)


@pytest.mark.parametrize(
    "binding",
    (
        b'PROBE_ENV = "PARSER_LATENCY_STAGE_ENABLED"\n',
        b'PROBE_ENV = "PARSER_" + "LATENCY_STAGE_ENABLED"\n',
        b"latency_stage_telemetry_enabled = False\n",
        b"from tests.benchmarks import latency_worker\n",
    ),
)
def test_lat_us01_rejects_direct_or_reconstructed_production_latency_env(
    tmp_path: Path,
    binding: bytes,
) -> None:
    root = _copy_app(tmp_path)
    path = root / "app/services/unrelated_successor.py"
    path.write_bytes(binding)

    with pytest.raises(
        readiness.ReadinessContractError,
        match="production latency binding differs",
    ):
        continuity._validate_production_latency_isolation(root)


def test_lat_us01_production_isolation_fails_closed_on_malformed_source(
    tmp_path: Path,
) -> None:
    root = _copy_app(tmp_path)
    path = root / "app/services/unrelated_successor.py"
    path.write_bytes(b"def incomplete(\n")

    with pytest.raises(
        readiness.ReadinessContractError,
        match="production source syntax differs",
    ):
        continuity._validate_production_latency_isolation(root)


@pytest.mark.parametrize(
    "expected",
    continuity.EXPECTED_PREDECESSOR_SOURCE_IDENTITIES,
    ids=lambda expected: expected["path"],
)
def test_predecessor_source_custody_rejects_any_byte_change(
    tmp_path: Path,
    expected: dict[str, Any],
) -> None:
    root = _copy_app(tmp_path)
    path = root / expected["path"]
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(
        readiness.ReadinessContractError,
        match="predecessor source identity differs",
    ):
        continuity._validate_predecessor_source_identities(root, _custody())


def test_guard_constants_pin_exact_source_identities() -> None:
    for expected in (
        continuity.EXPECTED_RENEWAL_DECISION_IDENTITY,
        continuity.EXPECTED_RENEWAL_RECORD_IDENTITY,
        continuity.EXPECTED_CUSTODY_RECORD_IDENTITY,
        continuity.EXPECTED_ATTEMPT_48_IDENTITY,
        continuity.PROTECTED_RUNNING_REGION_MODULE_IDENTITY,
        continuity.HISTORICAL_VALIDATOR_IDENTITY,
        *continuity.EXPECTED_PREDECESSOR_SOURCE_IDENTITIES,
    ):
        raw = (PROJECT_ROOT / expected["path"]).read_bytes()
        assert len(raw) == expected["size_bytes"]
        assert hashlib.sha256(raw).hexdigest() == expected["sha256"]


def test_custody_schema_is_closed() -> None:
    record = deepcopy(_custody())
    record["open_authority"] = True

    with pytest.raises(readiness.ReadinessContractError, match="keys differ"):
        continuity._validate_custody_record(PROJECT_ROOT, record)
