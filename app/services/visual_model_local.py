"""Lazy, offline-only local adapter for the Phase 06 visual-model contract.

This module deliberately knows nothing about document merging.  A successful
call returns additive contract evidence and every other outcome returns only a
typed failure, so the caller's Phase 05 result remains untouched.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import threading
import time
from copy import deepcopy
from typing import Any, Literal, Protocol

from pydantic import Field, model_validator

from app.config import Settings
from app.services.visual_model_contracts import (
    VisualModelConcern,
    VisualModelContract,
    VisualModelContractEnvelope,
    VisualModelRequest,
    VisualModelResponse,
    finite_visual_model_payload,
    validate_visual_model_response,
)


_SHA256_PATTERN = r"^[0-9a-f]{64}$"

LocalFailureCode = Literal[
    "local_visual_model_disabled",
    "local_visual_model_artifact_unapproved",
    "local_visual_model_artifact_missing",
    "local_visual_model_artifact_invalid",
    "local_visual_model_input_limit",
    "local_visual_model_output_limit",
    "local_visual_model_timeout",
    "local_visual_model_resource_limit",
    "local_visual_model_network_denied",
    "local_visual_model_loader_failed",
    "local_visual_model_inference_failed",
    "local_visual_model_response_malformed",
    "local_visual_model_provenance_mismatch",
]
LocalFailureKind = Literal[
    "disabled",
    "unavailable",
    "artifact",
    "input_limit",
    "output_limit",
    "timeout",
    "resource_limit",
    "network_denied",
    "malformed_response",
    "provenance",
    "adapter",
]


class LocalVisualModelArtifact(VisualModelContract):
    """Approved, immutable identity of one locally supplied model artifact."""

    artifact_path: str = Field(min_length=1, max_length=4_096)
    artifact_sha256: str = Field(pattern=_SHA256_PATTERN)
    artifact_source: str = Field(min_length=1, max_length=512)
    license_id: str = Field(min_length=1, max_length=256)
    usage_approval: Literal[True]
    usage_approval_id: str = Field(min_length=1, max_length=256)
    model_name: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=128)
    adapter_name: str = Field(min_length=1, max_length=128)
    adapter_version: str = Field(min_length=1, max_length=64)
    prompt_version: str = Field(min_length=1, max_length=64)
    hardware: Literal["cpu", "gpu", "accelerator"]


class LocalVisualModelLimits(VisualModelContract):
    """Complete bounded execution grant passed to an injected runtime."""

    crop_width: int = Field(ge=1, le=8_192)
    crop_height: int = Field(ge=1, le=8_192)
    crop_pixels: int = Field(ge=1, le=16_000_000)
    request_bytes: int = Field(ge=1_024, le=25 * 1024 * 1024)
    response_bytes: int = Field(ge=1_024, le=1024 * 1024)
    observations: int = Field(ge=1, le=256)
    timeout_seconds: float = Field(gt=0.0, le=30.0, allow_inf_nan=False)
    work_units: int = Field(ge=1, le=100_000)
    max_work_units: int = Field(ge=1, le=100_000)
    max_memory_bytes: int = Field(ge=1024 * 1024, le=128 * 1024**3)
    max_artifact_bytes: int = Field(ge=1024 * 1024, le=16 * 1024**3)
    max_concurrency: int = Field(ge=1, le=8)
    hardware: Literal["cpu", "gpu", "accelerator"]
    network_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_work_grant(self) -> "LocalVisualModelLimits":
        if self.work_units > self.max_work_units:
            raise ValueError("local visual-model work request exceeds its grant")
        return self


class LocalVisualModelFailure(VisualModelContract):
    """Stable failure returned instead of exception text or partial output."""

    code: LocalFailureCode
    kind: LocalFailureKind
    retryable: bool
    concern: VisualModelConcern

    @model_validator(mode="after")
    def validate_concern(self) -> "LocalVisualModelFailure":
        if self.concern.code != self.code or self.concern.stage != "adapter":
            raise ValueError("local adapter failure and concern differ")
        return self


class LocalVisualModelResult(VisualModelContract):
    """One accepted response or one closed failure; never a partial merge."""

    status: Literal["accepted", "unavailable", "rejected"]
    contract_envelope: VisualModelContractEnvelope | None = None
    failure: LocalVisualModelFailure | None = None
    fallback_preserved: Literal[True] = True

    @model_validator(mode="after")
    def validate_state(self) -> "LocalVisualModelResult":
        accepted = self.status == "accepted"
        if accepted != (self.contract_envelope is not None):
            raise ValueError("local adapter result state differs")
        if accepted == (self.failure is not None):
            raise ValueError("local adapter result failure state differs")
        if self.contract_envelope is not None and (
            self.contract_envelope.status != "accepted"
            or self.contract_envelope.response is None
        ):
            raise ValueError("local adapter cannot expose a rejected response")
        return self


class LocalVisualModelNetworkAccessError(RuntimeError):
    """A runtime/loader raises this when its offline guard blocks egress."""


class LocalVisualModelResourceLimitError(RuntimeError):
    """A runtime/loader raises this when a granted resource budget is hit."""


class LocalVisualModelRuntime(Protocol):
    """Injected offline runtime; implementations must honor every limit."""

    def infer(
        self,
        request: VisualModelRequest,
        *,
        limits: LocalVisualModelLimits,
    ) -> Any: ...


class LocalVisualModelLoader(Protocol):
    """Injected loader; the adapter never downloads or discovers artifacts."""

    def __call__(
        self,
        artifact: LocalVisualModelArtifact,
        *,
        limits: LocalVisualModelLimits,
    ) -> LocalVisualModelRuntime: ...


class _ArtifactFailure(ValueError):
    def __init__(self, code: LocalFailureCode) -> None:
        super().__init__(code)
        self.code = code


def _failure(
    code: LocalFailureCode,
    kind: LocalFailureKind,
    *,
    unavailable: bool = False,
    retryable: bool = False,
) -> LocalVisualModelResult:
    concern = VisualModelConcern(
        code=code,
        stage="adapter",
        severity="warning" if unavailable else "error",
    )
    return LocalVisualModelResult(
        status="unavailable" if unavailable else "rejected",
        failure=LocalVisualModelFailure(
            code=code,
            kind=kind,
            retryable=retryable,
            concern=concern,
        ),
    )


def _json_size(value: Any) -> int:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        default=lambda member: member.model_dump(mode="json"),
    ).encode("utf-8")
    return len(encoded)


class LocalVisualModelAdapter:
    """Lazy adapter over an explicitly injected, offline local runtime."""

    kind: Literal["local"] = "local"

    def __init__(
        self,
        settings: Settings,
        loader: LocalVisualModelLoader,
    ) -> None:
        self._settings = settings
        self._loader = loader
        self._runtime: LocalVisualModelRuntime | None = None
        self._runtime_lock = threading.Lock()
        configured_concurrency = settings.visual_models_local_max_concurrency
        concurrency = (
            configured_concurrency
            if isinstance(configured_concurrency, int)
            and not isinstance(configured_concurrency, bool)
            and configured_concurrency >= 1
            else 1
        )
        self._capacity = threading.BoundedSemaphore(concurrency)

    def is_available(self) -> bool:
        """Report configured eligibility without touching the artifact."""

        return bool(
            self._settings.visual_models_local_enabled
            and self._settings.visual_models_local_usage_approved
            and self._settings.visual_models_local_artifact_path
            and self._settings.visual_models_local_artifact_sha256
            and self._settings.visual_models_local_artifact_source
            and self._settings.visual_models_local_license_id
            and self._settings.visual_models_local_usage_approval_id
            and self._settings.visual_models_local_model_name
            and self._settings.visual_models_local_model_version
        )

    def invoke(
        self,
        request: VisualModelRequest,
        *,
        work_units: int | None = None,
    ) -> LocalVisualModelResult:
        """Run one bounded request and expose only independently valid output."""

        if not self._settings.visual_models_local_enabled:
            return _failure(
                "local_visual_model_disabled",
                "disabled",
                unavailable=True,
            )
        if not self._settings.visual_models_local_usage_approved:
            return _failure(
                "local_visual_model_artifact_unapproved",
                "unavailable",
                unavailable=True,
            )

        try:
            artifact = self._artifact()
        except (TypeError, ValueError):
            return _failure(
                "local_visual_model_artifact_invalid",
                "artifact",
            )

        pixels = request.crop.width * request.crop.height
        requested_work = (
            max(1, (pixels + 1_023) // 1_024)
            if work_units is None
            else work_units
        )
        if (
            isinstance(requested_work, bool)
            or not isinstance(requested_work, int)
            or requested_work < 1
            or requested_work > self._settings.visual_models_local_max_work_units
        ):
            return _failure(
                "local_visual_model_resource_limit",
                "resource_limit",
            )
        try:
            request_size = _json_size(request)
        except (MemoryError, OverflowError, TypeError, ValueError):
            return _failure(
                "local_visual_model_input_limit",
                "input_limit",
            )
        if (
            request.crop.width > self._settings.visual_models_max_crop_width
            or request.crop.height > self._settings.visual_models_max_crop_height
            or pixels > self._settings.visual_models_max_crop_pixels
            or request_size > self._settings.visual_models_max_request_bytes
        ):
            return _failure(
                "local_visual_model_input_limit",
                "input_limit",
            )

        limits = self._limits(requested_work)
        if not self._capacity.acquire(blocking=False):
            return _failure(
                "local_visual_model_resource_limit",
                "resource_limit",
                retryable=True,
            )
        try:
            started = time.monotonic()
            try:
                runtime = self._runtime_for(artifact, limits)
                raw_response = runtime.infer(request, limits=limits)
            except _ArtifactFailure as exc:
                unavailable = exc.code == "local_visual_model_artifact_missing"
                return _failure(
                    exc.code,
                    "unavailable" if unavailable else "artifact",
                    unavailable=unavailable,
                )
            except LocalVisualModelNetworkAccessError:
                return _failure(
                    "local_visual_model_network_denied",
                    "network_denied",
                )
            except (LocalVisualModelResourceLimitError, MemoryError):
                return _failure(
                    "local_visual_model_resource_limit",
                    "resource_limit",
                    retryable=True,
                )
            except TimeoutError:
                return _failure(
                    "local_visual_model_timeout",
                    "timeout",
                    retryable=True,
                )
            except Exception:
                code: LocalFailureCode = (
                    "local_visual_model_loader_failed"
                    if self._runtime is None
                    else "local_visual_model_inference_failed"
                )
                return _failure(code, "adapter", retryable=True)
            if time.monotonic() - started > limits.timeout_seconds:
                return _failure(
                    "local_visual_model_timeout",
                    "timeout",
                    retryable=True,
                )
        finally:
            self._capacity.release()

        candidate_response = (
            raw_response.model_dump(mode="json", exclude_none=True)
            if isinstance(raw_response, VisualModelResponse)
            else raw_response
        )
        try:
            finite_visual_model_payload(candidate_response)
            if _json_size(candidate_response) > limits.response_bytes:
                return _failure(
                    "local_visual_model_output_limit",
                    "output_limit",
                )
        except (MemoryError, OverflowError, TypeError, ValueError):
            return _failure(
                "local_visual_model_response_malformed",
                "malformed_response",
            )

        envelope = validate_visual_model_response(request, candidate_response)
        if envelope.status != "accepted" or envelope.response is None:
            return _failure(
                "local_visual_model_response_malformed",
                "malformed_response",
            )
        if len(envelope.response.observations) > limits.observations:
            return _failure(
                "local_visual_model_output_limit",
                "output_limit",
            )
        if not self._provenance_matches(envelope.response, artifact):
            return _failure(
                "local_visual_model_provenance_mismatch",
                "provenance",
            )
        return LocalVisualModelResult(
            status="accepted",
            contract_envelope=envelope,
        )

    def _artifact(self) -> LocalVisualModelArtifact:
        return LocalVisualModelArtifact(
            artifact_path=self._settings.visual_models_local_artifact_path,
            artifact_sha256=self._settings.visual_models_local_artifact_sha256,
            artifact_source=self._settings.visual_models_local_artifact_source,
            license_id=self._settings.visual_models_local_license_id,
            usage_approval=self._settings.visual_models_local_usage_approved,
            usage_approval_id=(
                self._settings.visual_models_local_usage_approval_id
            ),
            model_name=self._settings.visual_models_local_model_name,
            model_version=self._settings.visual_models_local_model_version,
            adapter_name=self._settings.visual_models_local_adapter_name,
            adapter_version=self._settings.visual_models_local_adapter_version,
            prompt_version=self._settings.visual_models_local_prompt_version,
            hardware=self._settings.visual_models_local_hardware,
        )

    def _limits(self, work_units: int) -> LocalVisualModelLimits:
        return LocalVisualModelLimits(
            crop_width=self._settings.visual_models_max_crop_width,
            crop_height=self._settings.visual_models_max_crop_height,
            crop_pixels=self._settings.visual_models_max_crop_pixels,
            request_bytes=self._settings.visual_models_max_request_bytes,
            response_bytes=self._settings.visual_models_max_response_bytes,
            observations=self._settings.visual_models_max_observations,
            timeout_seconds=self._settings.visual_models_local_timeout_seconds,
            work_units=work_units,
            max_work_units=self._settings.visual_models_local_max_work_units,
            max_memory_bytes=self._settings.visual_models_local_max_memory_bytes,
            max_artifact_bytes=self._settings.visual_models_local_max_artifact_bytes,
            max_concurrency=self._settings.visual_models_local_max_concurrency,
            hardware=self._settings.visual_models_local_hardware,
        )

    def _runtime_for(
        self,
        artifact: LocalVisualModelArtifact,
        limits: LocalVisualModelLimits,
    ) -> LocalVisualModelRuntime:
        if self._runtime is not None:
            return self._runtime
        with self._runtime_lock:
            if self._runtime is not None:
                return self._runtime
            self._validate_artifact(artifact, limits.max_artifact_bytes)
            runtime = self._loader(artifact, limits=limits)
            if runtime is None or not callable(getattr(runtime, "infer", None)):
                raise TypeError("local visual-model loader returned no runtime")
            self._runtime = runtime
            return runtime

    @staticmethod
    def _validate_artifact(
        artifact: LocalVisualModelArtifact,
        max_artifact_bytes: int,
    ) -> None:
        path = artifact.artifact_path
        try:
            if not os.path.isabs(path) or os.path.realpath(path) != path:
                raise _ArtifactFailure("local_visual_model_artifact_invalid")
            metadata = os.stat(path, follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode):
                raise _ArtifactFailure("local_visual_model_artifact_invalid")
            if metadata.st_size < 1:
                raise _ArtifactFailure("local_visual_model_artifact_invalid")
            if metadata.st_size > max_artifact_bytes:
                raise _ArtifactFailure("local_visual_model_artifact_invalid")
            digest = hashlib.sha256()
            total = 0
            with open(path, "rb") as artifact_file:
                while chunk := artifact_file.read(1024 * 1024):
                    total += len(chunk)
                    if total > max_artifact_bytes:
                        raise _ArtifactFailure(
                            "local_visual_model_artifact_invalid"
                        )
                    digest.update(chunk)
            if total != metadata.st_size or digest.hexdigest() != artifact.artifact_sha256:
                raise _ArtifactFailure("local_visual_model_artifact_invalid")
        except FileNotFoundError as exc:
            raise _ArtifactFailure("local_visual_model_artifact_missing") from exc
        except _ArtifactFailure:
            raise
        except OSError as exc:
            raise _ArtifactFailure("local_visual_model_artifact_invalid") from exc

    @staticmethod
    def _provenance_matches(
        response: VisualModelResponse,
        artifact: LocalVisualModelArtifact,
    ) -> bool:
        identity = response.identity
        return bool(
            identity.adapter_kind == "local"
            and identity.adapter_name == artifact.adapter_name
            and identity.adapter_version == artifact.adapter_version
            and identity.model_name == artifact.model_name
            and identity.model_version == artifact.model_version
            and identity.prompt_version == artifact.prompt_version
            and identity.artifact_sha256 == artifact.artifact_sha256
            and identity.artifact_source == artifact.artifact_source
            and identity.license_id == artifact.license_id
        )


class DeterministicLocalVisualModelRuntime:
    """Pure test double that returns a fresh copy of one configured payload."""

    def __init__(self, raw_response: Any, *, failure: Exception | None = None) -> None:
        self._raw_response = deepcopy(raw_response)
        self._failure = failure
        self.call_count = 0
        self.requests: list[VisualModelRequest] = []
        self.limits: list[LocalVisualModelLimits] = []

    def infer(
        self,
        request: VisualModelRequest,
        *,
        limits: LocalVisualModelLimits,
    ) -> Any:
        if limits.network_allowed is not False:
            raise LocalVisualModelNetworkAccessError("network grant differs")
        self.call_count += 1
        self.requests.append(request)
        self.limits.append(limits)
        if self._failure is not None:
            raise self._failure
        return deepcopy(self._raw_response)


class DeterministicLocalVisualModelLoader:
    """Lazy test loader with observable calls and no discovery or I/O."""

    def __init__(
        self,
        runtime: LocalVisualModelRuntime,
        *,
        failure: Exception | None = None,
    ) -> None:
        self.runtime = runtime
        self.failure = failure
        self.call_count = 0
        self.artifacts: list[LocalVisualModelArtifact] = []
        self.limits: list[LocalVisualModelLimits] = []

    def __call__(
        self,
        artifact: LocalVisualModelArtifact,
        *,
        limits: LocalVisualModelLimits,
    ) -> LocalVisualModelRuntime:
        if limits.network_allowed is not False:
            raise LocalVisualModelNetworkAccessError("network grant differs")
        self.call_count += 1
        self.artifacts.append(artifact)
        self.limits.append(limits)
        if self.failure is not None:
            raise self.failure
        return self.runtime


__all__ = [
    "DeterministicLocalVisualModelLoader",
    "DeterministicLocalVisualModelRuntime",
    "LocalFailureCode",
    "LocalFailureKind",
    "LocalVisualModelAdapter",
    "LocalVisualModelArtifact",
    "LocalVisualModelFailure",
    "LocalVisualModelLimits",
    "LocalVisualModelLoader",
    "LocalVisualModelNetworkAccessError",
    "LocalVisualModelResourceLimitError",
    "LocalVisualModelResult",
    "LocalVisualModelRuntime",
]
