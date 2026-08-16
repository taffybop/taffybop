from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from app.config import MEBIBYTE, Settings
from app.services.visual_model_contracts import (
    VisualModelIdentity,
    VisualModelResponse,
    canonical_visual_model_json,
)
from app.services.visual_model_local import (
    DeterministicLocalVisualModelLoader,
    DeterministicLocalVisualModelRuntime,
    LocalVisualModelAdapter,
    LocalVisualModelNetworkAccessError,
)
from tests.stories.phase_06.test_p06_us01_model_contract import (
    _observation,
    _request,
)


_ARTIFACT_BYTES = b"deterministic-local-visual-model-artifact-v1"


def _write_artifact(tmp_path: Path) -> tuple[str, str]:
    artifact_path = tmp_path / "fixture-model.bin"
    artifact_path.write_bytes(_ARTIFACT_BYTES)
    return (
        str(artifact_path.resolve()),
        hashlib.sha256(_ARTIFACT_BYTES).hexdigest(),
    )


def _settings(
    artifact_path: str,
    artifact_sha256: str,
    **overrides: Any,
) -> Settings:
    values: dict[str, Any] = {
        "visual_structure_schema_enabled": True,
        "visual_models_contract_enabled": True,
        "visual_models_local_enabled": True,
        "visual_models_local_usage_approved": True,
        "visual_models_local_usage_approval_id": "approval-fixture-2026-08",
        "visual_models_local_artifact_path": artifact_path,
        "visual_models_local_artifact_sha256": artifact_sha256,
        "visual_models_local_artifact_source": "fixture://pre-provisioned",
        "visual_models_local_license_id": "fixture-test-only",
        "visual_models_local_model_name": "fixture-model",
        "visual_models_local_model_version": "fixture-v1",
    }
    values.update(overrides)
    return Settings(**values)


def _local_response(artifact_sha256: str) -> dict[str, Any]:
    identity = VisualModelIdentity(
        adapter_kind="local",
        adapter_name="local-visual-model-adapter",
        adapter_version="1.0.0",
        model_name="fixture-model",
        model_version="fixture-v1",
        prompt_version="grounded-v1",
        response_schema_version="1.0",
        artifact_sha256=artifact_sha256,
        artifact_source="fixture://pre-provisioned",
        license_id="fixture-test-only",
    )
    observation = _observation(identity=identity)
    return VisualModelResponse(
        schema_version="1.0",
        request_id="request-1",
        identity=identity,
        observations=[observation],
    ).model_dump(mode="json", exclude_none=True)


def test_local_defaults_off_dependency_and_rollback_ignore_stale_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = DeterministicLocalVisualModelRuntime({"not": "invoked"})
    loader = DeterministicLocalVisualModelLoader(runtime)
    result = LocalVisualModelAdapter(Settings(), loader).invoke(_request())

    assert Settings().visual_models_local_enabled is False
    assert result.status == "unavailable"
    assert result.fallback_preserved is True
    assert result.failure is not None
    assert result.failure.code == "local_visual_model_disabled"
    assert loader.call_count == 0
    assert runtime.call_count == 0
    with pytest.raises(ValueError, match="PARSER_VISUAL_MODELS_LOCAL_ENABLED"):
        Settings(visual_models_local_enabled=True)

    monkeypatch.setenv("PARSER_VISUAL_MODELS_LOCAL_ENABLED", "false")
    monkeypatch.setenv("PARSER_VISUAL_MODELS_LOCAL_USAGE_APPROVED", "not-bool")
    monkeypatch.setenv("PARSER_VISUAL_MODELS_LOCAL_TIMEOUT_SECONDS", "NaN")
    monkeypatch.setenv("PARSER_VISUAL_MODELS_LOCAL_ARTIFACT_SHA256", "bad")
    rolled_back = Settings.from_env()
    assert rolled_back.visual_models_local_enabled is False
    assert rolled_back.visual_models_local_usage_approved is False
    assert rolled_back.visual_models_local_timeout_seconds == 2.0


def test_no_usage_approval_returns_unchanged_fallback_without_loading() -> None:
    fallback = {
        "items": [{"id": "chart-1", "parse_concerns": ["unresolved"]}],
        "markdown": "![chart](source.png)",
    }
    before = deepcopy(fallback)
    runtime = DeterministicLocalVisualModelRuntime({"not": "invoked"})
    loader = DeterministicLocalVisualModelLoader(runtime)
    settings = Settings(
        visual_structure_schema_enabled=True,
        visual_models_contract_enabled=True,
        visual_models_local_enabled=True,
    )

    result = LocalVisualModelAdapter(settings, loader).invoke(_request())

    assert result.status == "unavailable"
    assert result.failure is not None
    assert result.failure.code == "local_visual_model_artifact_unapproved"
    assert loader.call_count == runtime.call_count == 0
    assert fallback == before
    assert json.dumps(fallback, sort_keys=True) == json.dumps(before, sort_keys=True)


def test_success_is_lazy_grounded_offline_and_deterministic(tmp_path: Path) -> None:
    artifact_path, digest = _write_artifact(tmp_path)
    response = _local_response(digest)
    runtime = DeterministicLocalVisualModelRuntime(response)
    loader = DeterministicLocalVisualModelLoader(runtime)
    adapter = LocalVisualModelAdapter(_settings(artifact_path, digest), loader)
    request = _request()

    assert adapter.is_available() is True
    assert loader.call_count == runtime.call_count == 0
    first = adapter.invoke(request)
    second = adapter.invoke(request)

    assert first.status == second.status == "accepted"
    assert first.contract_envelope is not None
    assert second.contract_envelope is not None
    assert first.contract_envelope.response is not None
    assert second.contract_envelope.response is not None
    assert canonical_visual_model_json(first.contract_envelope.response) == (
        canonical_visual_model_json(second.contract_envelope.response)
    )
    assert loader.call_count == 1
    assert runtime.call_count == 2
    assert runtime.requests == [request, request]
    assert runtime.limits[0].network_allowed is False
    assert runtime.limits[0].work_units == 8
    identity = first.contract_envelope.response.identity
    assert identity.artifact_sha256 == digest
    assert identity.artifact_source == "fixture://pre-provisioned"
    assert identity.license_id == "fixture-test-only"
    assert loader.artifacts[0].usage_approval is True
    assert loader.artifacts[0].usage_approval_id == "approval-fixture-2026-08"


@pytest.mark.parametrize(
    ("case", "expected_status", "expected_code"),
    [
        (
            "missing",
            "unavailable",
            "local_visual_model_artifact_missing",
        ),
        (
            "corrupt",
            "rejected",
            "local_visual_model_artifact_invalid",
        ),
    ],
)
def test_missing_or_corrupt_artifact_never_loads_and_preserves_fallback(
    tmp_path: Path,
    case: str,
    expected_status: str,
    expected_code: str,
) -> None:
    artifact_path, digest = _write_artifact(tmp_path)
    if case == "missing":
        configured_path = str((tmp_path / "missing.bin").resolve())
        configured_digest = digest
    else:
        configured_path = artifact_path
        configured_digest = "0" * 64
    fallback = {"source": "phase-05", "observations": []}
    before = deepcopy(fallback)
    runtime = DeterministicLocalVisualModelRuntime(_local_response(digest))
    loader = DeterministicLocalVisualModelLoader(runtime)

    result = LocalVisualModelAdapter(
        _settings(configured_path, configured_digest),
        loader,
    ).invoke(_request())

    assert result.status == expected_status
    assert result.contract_envelope is None
    assert result.failure is not None
    assert result.failure.code == expected_code
    assert loader.call_count == runtime.call_count == 0
    assert fallback == before


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (TimeoutError("fixture deadline"), "local_visual_model_timeout"),
        (MemoryError("fixture memory limit"), "local_visual_model_resource_limit"),
        (
            LocalVisualModelNetworkAccessError("fixture socket denied"),
            "local_visual_model_network_denied",
        ),
        (RuntimeError("fixture runtime failed"), "local_visual_model_inference_failed"),
    ],
)
def test_runtime_failures_are_typed_and_never_expose_partial_output(
    tmp_path: Path,
    failure: Exception,
    expected_code: str,
) -> None:
    artifact_path, digest = _write_artifact(tmp_path)
    runtime = DeterministicLocalVisualModelRuntime(
        _local_response(digest),
        failure=failure,
    )
    loader = DeterministicLocalVisualModelLoader(runtime)

    result = LocalVisualModelAdapter(
        _settings(artifact_path, digest),
        loader,
    ).invoke(_request())

    assert result.status == "rejected"
    assert result.contract_envelope is None
    assert result.failure is not None
    assert result.failure.code == expected_code
    assert result.failure.concern.stage == "adapter"


def test_loader_failure_is_typed_and_does_not_cache_a_runtime(tmp_path: Path) -> None:
    artifact_path, digest = _write_artifact(tmp_path)
    runtime = DeterministicLocalVisualModelRuntime(_local_response(digest))
    loader = DeterministicLocalVisualModelLoader(
        runtime,
        failure=RuntimeError("fixture loader failure"),
    )
    adapter = LocalVisualModelAdapter(_settings(artifact_path, digest), loader)

    first = adapter.invoke(_request())
    second = adapter.invoke(_request())

    assert first.failure is not None and second.failure is not None
    assert first.failure.code == second.failure.code == (
        "local_visual_model_loader_failed"
    )
    assert loader.call_count == 2
    assert runtime.call_count == 0


def test_crop_and_work_limits_reject_before_loading(tmp_path: Path) -> None:
    artifact_path, digest = _write_artifact(tmp_path)
    runtime = DeterministicLocalVisualModelRuntime(_local_response(digest))
    loader = DeterministicLocalVisualModelLoader(runtime)
    adapter = LocalVisualModelAdapter(
        _settings(
            artifact_path,
            digest,
            visual_models_max_crop_width=99,
            visual_models_local_max_work_units=7,
        ),
        loader,
    )

    crop_result = adapter.invoke(_request(), work_units=7)
    work_result = adapter.invoke(_request(), work_units=8)

    assert crop_result.failure is not None
    assert crop_result.failure.code == "local_visual_model_input_limit"
    assert work_result.failure is not None
    assert work_result.failure.code == "local_visual_model_resource_limit"
    assert loader.call_count == runtime.call_count == 0


def test_output_limit_malformed_and_provenance_failures_are_isolated(
    tmp_path: Path,
) -> None:
    artifact_path, digest = _write_artifact(tmp_path)
    oversized = _local_response(digest)
    oversized["observations"][0]["text"] = "x" * 2_000
    cases = [
        (
            oversized,
            {"visual_models_max_response_bytes": 1_024},
            "local_visual_model_output_limit",
        ),
        (
            {"schema_version": "1.0", "request_id": "request-1"},
            {},
            "local_visual_model_response_malformed",
        ),
        (
            _local_response("f" * 64),
            {},
            "local_visual_model_provenance_mismatch",
        ),
    ]

    for raw_response, overrides, expected_code in cases:
        runtime = DeterministicLocalVisualModelRuntime(raw_response)
        loader = DeterministicLocalVisualModelLoader(runtime)
        result = LocalVisualModelAdapter(
            _settings(artifact_path, digest, **overrides),
            loader,
        ).invoke(_request())
        assert result.status == "rejected"
        assert result.contract_envelope is None
        assert result.failure is not None
        assert result.failure.code == expected_code


@pytest.mark.parametrize(
    ("override", "value"),
    [
        ("visual_models_local_timeout_seconds", 0.0009),
        ("visual_models_local_max_work_units", 100_001),
        ("visual_models_local_max_concurrency", 9),
        ("visual_models_local_max_memory_bytes", MEBIBYTE - 1),
        ("visual_models_local_max_artifact_bytes", 16 * 1024 * MEBIBYTE + 1),
    ],
)
def test_resource_configuration_rejects_values_outside_boundaries(
    override: str,
    value: int | float,
) -> None:
    values: dict[str, Any] = {
        "visual_structure_schema_enabled": True,
        "visual_models_contract_enabled": True,
        "visual_models_local_enabled": True,
        override: value,
    }

    with pytest.raises(ValueError, match="PARSER_VISUAL_MODELS_LOCAL"):
        Settings(**values)


def test_approved_configuration_requires_complete_resolved_manifest(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="USAGE_APPROVAL_ID"):
        Settings(
            visual_structure_schema_enabled=True,
            visual_models_contract_enabled=True,
            visual_models_local_enabled=True,
            visual_models_local_usage_approved=True,
        )

    relative = "fixture-model.bin"
    with pytest.raises(ValueError, match="absolute, resolved"):
        _settings(relative, "a" * 64)

    artifact_path, digest = _write_artifact(tmp_path)
    settings = _settings(
        artifact_path,
        digest,
        visual_models_local_timeout_seconds=0.001,
        visual_models_local_max_work_units=1,
        visual_models_local_max_concurrency=8,
        visual_models_local_max_memory_bytes=MEBIBYTE,
        visual_models_local_max_artifact_bytes=MEBIBYTE,
    )
    assert settings.visual_models_local_timeout_seconds == 0.001
    assert settings.visual_models_local_max_work_units == 1
    assert settings.visual_models_local_max_concurrency == 8


def test_environment_reads_approved_manifest_only_inside_local_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifact_path, digest = _write_artifact(tmp_path)
    values = {
        "PARSER_VISUAL_STRUCTURE_SCHEMA_ENABLED": "true",
        "PARSER_VISUAL_MODELS_CONTRACT_ENABLED": "true",
        "PARSER_VISUAL_MODELS_LOCAL_ENABLED": "true",
        "PARSER_VISUAL_MODELS_LOCAL_USAGE_APPROVED": "true",
        "PARSER_VISUAL_MODELS_LOCAL_USAGE_APPROVAL_ID": "approval-env",
        "PARSER_VISUAL_MODELS_LOCAL_ARTIFACT_PATH": artifact_path,
        "PARSER_VISUAL_MODELS_LOCAL_ARTIFACT_SHA256": digest,
        "PARSER_VISUAL_MODELS_LOCAL_ARTIFACT_SOURCE": "fixture://env",
        "PARSER_VISUAL_MODELS_LOCAL_LICENSE_ID": "fixture-env-only",
        "PARSER_VISUAL_MODELS_LOCAL_MODEL_NAME": "env-model",
        "PARSER_VISUAL_MODELS_LOCAL_MODEL_VERSION": "env-v1",
        "PARSER_VISUAL_MODELS_LOCAL_TIMEOUT_SECONDS": "30",
        "PARSER_VISUAL_MODELS_LOCAL_MAX_WORK_UNITS": "100000",
        "PARSER_VISUAL_MODELS_LOCAL_MAX_CONCURRENCY": "8",
        "PARSER_VISUAL_MODELS_LOCAL_MAX_MEMORY_BYTES": str(128 * 1024**3),
        "PARSER_VISUAL_MODELS_LOCAL_MAX_ARTIFACT_BYTES": str(16 * 1024**3),
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    settings = Settings.from_env()

    assert settings.visual_models_local_enabled is True
    assert settings.visual_models_local_usage_approved is True
    assert settings.visual_models_local_usage_approval_id == "approval-env"
    assert settings.visual_models_local_artifact_path == artifact_path
    assert settings.visual_models_local_artifact_sha256 == digest
    assert settings.visual_models_local_timeout_seconds == 30.0
    assert settings.visual_models_local_max_concurrency == 8
