"""Executable, fail-closed local latency profiler and campaign evaluator.

This module never calls LlamaCloud. It profiles the local ASGI application
through fixed, external test instrumentation, samples the exact worker process
tree, and emits one candidate attempt. Provider UI evidence is entered
separately and remains subject to the closed campaign contract.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import ctypes
import hashlib
import importlib.metadata
import io
import json
import os
import platform
import re
import resource
import select
import shutil
import signal
import socket
import stat as stat_module
import struct
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from itertools import pairwise
from pathlib import Path
from typing import Any, Generic, TypeVar

import psutil

from tests.benchmarks.latency_campaign import build_interleaved_plan, evaluate_campaign
from tests.benchmarks.latency_contracts import (
    MAXIMUM_PROCESS_SNAPSHOTS,
    MAXIMUM_PROCESSES_PER_SNAPSHOT,
    PROCESS_TREE_SCHEMA_ID,
    STAGE_TRACE_SCHEMA_ID,
    AttemptSlot,
    AttemptStatus,
    CampaignScope,
    ConfigurationIdentity,
    EnvironmentIdentityEvidence,
    FailureRecord,
    FailureType,
    InstalledDistributionIdentity,
    LatencyAttempt,
    LatencyCampaign,
    NetworkIsolationEvidence,
    PartialProcessTreeEvidence,
    ProcessIdentity,
    ProcessMetric,
    ProcessRole,
    ProcessTreeMetrics,
    ProcessTreeSnapshot,
    ProviderEvidenceRegistry,
    ProviderEvidenceSidecar,
    RuntimeBinaryIdentity,
    SourceBinding,
    SourceIdentity,
    StageCardinalityPolicy,
    StageName,
    StageSpan,
    StageStatus,
    StageTrace,
    SystemName,
    WorkerExecutionEvidence,
    WorkerFatalEnvelope,
    WorkerLifecycle,
    WorkerWatchdogEvidence,
    canonical_model_bytes,
    configuration_identity_sha256,
    read_latency_campaign,
)
from tests.benchmarks.latency_isolation import (
    CHILD_NETWORK_GUARD_SHA256,
    CHILD_NETWORK_GUARD_SIZE_BYTES,
    OS_NETWORK_SANDBOX_PROFILE_SHA256,
    OS_NETWORK_SANDBOX_PROFILE_SIZE_BYTES,
    attest_darwin_pipe_peers,
    child_network_guard_identity,
    controlled_worker_environment,
    darwin_pipe_file_descriptors,
    materialize_private_child_network_guard,
    normalized_worker_environment_sha256,
    os_network_sandbox_identity,
    private_child_network_guard_identity,
    sandboxed_worker_command,
    sanitized_worker_environment,
    trusted_python_runtime_executable_paths,
    validate_owned_unix_probe,
    worker_environment_sha256,
)

T = TypeVar("T")
DEFAULT_SAMPLE_INTERVAL_NS = 50_000_000
DEFAULT_HARD_MAXIMUM_GAP_NS = 250_000_000
EXTERNAL_SAMPLER_PROCESS_LANE_COUNT = 6
DARWIN_SAMPLER_QOS_CLASS_USER_INTERACTIVE = 0x21
MAXIMUM_PROFILE_DURATION_NS = 300_000_000_000
MAXIMUM_SOURCE_BYTES = 32 * 1024 * 1024
MAXIMUM_RESPONSE_BYTES = 64 * 1024 * 1024
MAXIMUM_EVIDENCE_BYTES = 4 * 1024 * 1024
MAXIMUM_SAMPLER_EVIDENCE_BYTES = 32 * 1024 * 1024
MAXIMUM_FATAL_ENVELOPE_BYTES = 512
WORKER_FATAL_EXIT_CODE = 88
WORKER_FATAL_ENVELOPE_WRITE_FAILED_EXIT_CODE = 89
MAXIMUM_CAMPAIGN_BYTES = 64 * 1024 * 1024
MAXIMUM_PROFILE_SET_BYTES = 512 * 1024 * 1024
MAXIMUM_PROFILE_EVALUATION_BYTES = 1024 * 1024
MAXIMUM_UI_ARTIFACT_BYTES = 32 * 1024 * 1024
WORKER_STARTUP_PREWARM_TIMEOUT_SECONDS = 300.0
WORKER_CLEANUP_GRACE_SECONDS = 2.0
WORKER_RESOURCE_CLOSURE_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class ProfileResult(Generic[T]):
    result: T | None
    operation_error: BaseException | None
    process_tree: ProcessTreeMetrics


def _strict_monotonic_ns(value: int, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TypeError(f"{label} must be a non-negative integer nanosecond value")
    return value


def bounded_read_bytes(
    path: Path,
    *,
    maximum_bytes: int,
    allow_empty: bool = False,
) -> bytes:
    """Read one regular file without permitting an unbounded allocation."""

    if isinstance(maximum_bytes, bool) or maximum_bytes <= 0:
        raise ValueError("maximum_bytes must be a positive integer")
    file_stat = path.lstat()
    if path.is_symlink() or not stat_module.S_ISREG(file_stat.st_mode):
        raise ValueError("retained input must be a non-symlink regular file")
    if file_stat.st_size <= 0 and not allow_empty:
        raise ValueError("retained input must be a non-empty regular file")
    if file_stat.st_size > maximum_bytes:
        raise ValueError("retained input exceeds its byte bound")
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
    )
    opened_stat = os.fstat(descriptor)
    if (
        opened_stat.st_dev != file_stat.st_dev
        or opened_stat.st_ino != file_stat.st_ino
        or not stat_module.S_ISREG(opened_stat.st_mode)
    ):
        os.close(descriptor)
        raise ValueError("retained input identity changed before open")
    with os.fdopen(descriptor, "rb") as stream:
        data = stream.read(maximum_bytes + 1)
        if len(data) > maximum_bytes or stream.read(1):
            raise ValueError("retained input exceeded its byte bound while reading")
        final_stat = os.fstat(stream.fileno())
    final_path_stat = path.lstat()
    if (
        len(data) != file_stat.st_size
        or final_stat.st_dev != opened_stat.st_dev
        or final_stat.st_ino != opened_stat.st_ino
        or final_stat.st_size != opened_stat.st_size
        or final_stat.st_mtime_ns != opened_stat.st_mtime_ns
        or path.is_symlink()
        or final_path_stat.st_dev != opened_stat.st_dev
        or final_path_stat.st_ino != opened_stat.st_ino
        or final_path_stat.st_size != opened_stat.st_size
        or final_path_stat.st_mtime_ns != opened_stat.st_mtime_ns
    ):
        raise ValueError("retained input changed while reading")
    return data


def _read_worker_fatal_envelope(path: Path) -> WorkerFatalEnvelope:
    """Read one canonical fatal frame from the private worker protocol root."""

    parent_stat = path.parent.lstat()
    file_stat = path.lstat()
    if (
        path.parent.is_symlink()
        or not stat_module.S_ISDIR(parent_stat.st_mode)
        or stat_module.S_IMODE(parent_stat.st_mode) != 0o700
        or parent_stat.st_uid != os.getuid()
        or path.name != "fatal.json"
        or path.is_symlink()
        or not stat_module.S_ISREG(file_stat.st_mode)
        or stat_module.S_IMODE(file_stat.st_mode) != 0o600
        or file_stat.st_uid != os.getuid()
        or file_stat.st_nlink != 1
        or not 0 < file_stat.st_size <= MAXIMUM_FATAL_ENVELOPE_BYTES
    ):
        raise RuntimeError("worker fatal envelope custody differs")
    data = bounded_read_bytes(path, maximum_bytes=MAXIMUM_FATAL_ENVELOPE_BYTES)
    envelope = WorkerFatalEnvelope.model_validate_json(data)
    if canonical_model_bytes(envelope) != data:
        raise RuntimeError("worker fatal envelope is not canonical")
    return envelope


def _resolve_workspace_path(workspace: Path, path: Path) -> Path:
    root = workspace.resolve()
    candidate = path if path.is_absolute() else root / path
    try:
        lexical_relative = candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("identity path escaped workspace") from error
    if any(part in {"", ".", ".."} for part in lexical_relative.parts):
        raise ValueError("identity path is not canonical")
    current = root
    for part in lexical_relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("identity path contains a symlink")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError("identity path escaped workspace") from error
    return resolved


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _bounded_streaming_file_identity(
    path: Path,
    *,
    maximum_bytes: int = 2 * 1024 * 1024 * 1024,
) -> tuple[int, str]:
    file_stat = path.lstat()
    if (
        path.is_symlink()
        or not stat_module.S_ISREG(file_stat.st_mode)
        or file_stat.st_size < 0
        or file_stat.st_size > maximum_bytes
    ):
        raise ValueError("identity file is not regular or exceeds its bound")
    digest = hashlib.sha256()
    observed = 0
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    opened_stat = os.fstat(descriptor)
    if (
        opened_stat.st_dev != file_stat.st_dev
        or opened_stat.st_ino != file_stat.st_ino
        or not stat_module.S_ISREG(opened_stat.st_mode)
    ):
        os.close(descriptor)
        raise ValueError("identity file changed before open")
    with os.fdopen(descriptor, "rb") as stream:
        while chunk := stream.read(1024 * 1024):
            observed += len(chunk)
            if observed > maximum_bytes:
                raise ValueError("identity file exceeded its bound while reading")
            digest.update(chunk)
        final_stat = os.fstat(stream.fileno())
    if (
        observed != file_stat.st_size
        or final_stat.st_dev != opened_stat.st_dev
        or final_stat.st_ino != opened_stat.st_ino
        or final_stat.st_size != opened_stat.st_size
        or final_stat.st_mtime_ns != opened_stat.st_mtime_ns
    ):
        raise ValueError("identity file changed while reading")
    return observed, digest.hexdigest()


def _tree_identity(
    workspace: Path,
    relative_root: str,
    *,
    suffixes: tuple[str, ...] | None = None,
    maximum_aggregate_bytes: int = 2 * 1024 * 1024 * 1024,
) -> str:
    if maximum_aggregate_bytes <= 0:
        raise ValueError("identity tree aggregate bound must be positive")
    root = _resolve_workspace_path(workspace, Path(relative_root))
    if not root.is_dir():
        raise ValueError("identity tree root must be a directory")
    records: list[dict[str, Any]] = []
    aggregate_bytes = 0
    if root.exists():
        pending = [root]
        entries: list[Path] = []
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    if len(entries) >= 8_192:
                        raise ValueError("identity tree exceeds its entry-count bound")
                    path = Path(entry.path)
                    if entry.is_symlink():
                        raise ValueError("identity tree cannot contain symlinks")
                    entries.append(path)
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(path)
                    elif not entry.is_file(follow_symlinks=False):
                        raise ValueError("identity tree contains a non-regular entry")
        paths = tuple(sorted(path for path in entries if path.is_file()))
        if len(paths) > 4_096:
            raise ValueError("identity tree exceeds its file-count bound")
        for path in paths:
            if suffixes is not None and path.suffix not in suffixes:
                continue
            resolved = _resolve_workspace_path(workspace, path)
            try:
                resolved.relative_to(root)
            except ValueError as error:
                raise ValueError("identity tree member escaped its root") from error
            candidate_size = resolved.lstat().st_size
            if candidate_size > maximum_aggregate_bytes - aggregate_bytes:
                raise ValueError("identity tree exceeds its aggregate byte bound")
            size_bytes, sha256 = _bounded_streaming_file_identity(
                resolved,
                maximum_bytes=maximum_aggregate_bytes - aggregate_bytes,
            )
            aggregate_bytes += size_bytes
            records.append(
                {
                    "path": path.relative_to(workspace).as_posix(),
                    "sha256": sha256,
                    "size_bytes": size_bytes,
                }
            )
    return _canonical_hash(records)


def derive_candidate_code_sha256(workspace: Path | None = None) -> str:
    return _tree_identity((workspace or Path.cwd()).resolve(), "app", suffixes=(".py",))


def derive_dependency_lock_sha256(workspace: Path | None = None) -> str:
    root = (workspace or Path.cwd()).resolve()
    records = []
    for relative, maximum in (
        ("pyproject.toml", 2 * 1024 * 1024),
        ("uv.lock", 16 * 1024 * 1024),
    ):
        path = _resolve_workspace_path(root, Path(relative))
        data = bounded_read_bytes(path, maximum_bytes=maximum)
        records.append(
            {
                "path": relative,
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    return _canonical_hash(records)


def derive_model_artifacts_sha256(workspace: Path | None = None) -> str:
    return _tree_identity((workspace or Path.cwd()).resolve(), ".models")


ENVIRONMENT_DISTRIBUTIONS = (
    "docling",
    "docling-core",
    "fastapi",
    "httpx",
    "numpy",
    "pdfplumber",
    "pillow",
    "psutil",
    "pydantic",
    "pypdf",
    "pypdfium2",
    "pytesseract",
    "starlette",
    "torch",
    "torchvision",
)


def _installed_distribution_identity(name: str) -> InstalledDistributionIdentity:
    try:
        distribution = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return InstalledDistributionIdentity(
            name=name,
            version=None,
            verified_file_count=0,
            verified_aggregate_bytes=0,
            installed_files_sha256=_canonical_hash([]),
            identity_basis="distribution-absent-from-locked-runtime-v1",
        )
    root = Path(sys.prefix).resolve()
    records: list[dict[str, Any]] = []
    aggregate_bytes = 0
    files = tuple(item for item in (distribution.files or ()) if item.hash is not None)
    if not files or len(files) > 20_000:
        raise RuntimeError(
            "installed distribution file inventory is empty or unbounded"
        )
    for item in sorted(files, key=str):
        path = Path(distribution.locate_file(item))
        if path.is_symlink():
            raise RuntimeError("installed distribution contains a symlinked file")
        resolved = path.resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError as error:
            raise RuntimeError(
                "installed distribution file escaped runtime prefix"
            ) from error
        remaining = 2 * 1024 * 1024 * 1024 - aggregate_bytes
        if remaining <= 0:
            raise RuntimeError("installed distribution exceeds aggregate byte bound")
        size_bytes, sha256 = _bounded_streaming_file_identity(
            resolved,
            maximum_bytes=remaining,
        )
        if item.hash is None or item.hash.mode != "sha256":
            raise RuntimeError("installed distribution RECORD digest is unsupported")
        try:
            declared_sha256 = base64.urlsafe_b64decode(
                item.hash.value + "=" * (-len(item.hash.value) % 4)
            ).hex()
        except (ValueError, TypeError) as error:
            raise RuntimeError(
                "installed distribution RECORD digest is malformed"
            ) from error
        if declared_sha256 != sha256:
            raise RuntimeError(
                "installed distribution file differs from its RECORD digest"
            )
        aggregate_bytes += size_bytes
        records.append(
            {
                "path": str(item),
                "size_bytes": size_bytes,
                "sha256": sha256,
                "declared_record_sha256": declared_sha256,
            }
        )
    return InstalledDistributionIdentity(
        name=name,
        version=distribution.version,
        verified_file_count=len(records),
        verified_aggregate_bytes=aggregate_bytes,
        installed_files_sha256=_canonical_hash(records),
        identity_basis="all-record-hashed-installed-files-with-declared-digests-v1",
    )


def _binary_identity(
    *, role: str, path: Path, version: str | None
) -> RuntimeBinaryIdentity:
    resolved = path.resolve(strict=True)
    size_bytes, sha256 = _bounded_streaming_file_identity(
        resolved,
        maximum_bytes=512 * 1024 * 1024,
    )
    return RuntimeBinaryIdentity(
        role=role,
        resolved_path_sha256=hashlib.sha256(str(resolved).encode("utf-8")).hexdigest(),
        size_bytes=size_bytes,
        content_sha256=sha256,
        version=version,
    )


def _tesseract_identities() -> tuple[RuntimeBinaryIdentity, RuntimeBinaryIdentity]:
    command = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
    if not command:
        raise RuntimeError("Tesseract executable is unavailable")
    executable = Path(command).resolve(strict=True)
    completed = subprocess.run(
        (str(executable), "--version"),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10.0,
        check=True,
        env=_sanitized_worker_environment(),
    )
    version = (completed.stdout or completed.stderr).splitlines()[0].strip()
    if not version or len(version) > 256:
        raise RuntimeError("Tesseract version evidence is invalid")
    candidates = []
    configured = os.environ.get("TESSERACT_DATA_PATH") or os.environ.get(
        "TESSDATA_PREFIX"
    )
    if configured:
        candidates.append(Path(configured) / "eng.traineddata")
    candidates.extend(
        (
            executable.parent.parent / "share" / "tessdata" / "eng.traineddata",
            Path("/opt/homebrew/share/tessdata/eng.traineddata"),
            Path("/usr/local/share/tessdata/eng.traineddata"),
            Path("/usr/share/tesseract-ocr/5/tessdata/eng.traineddata"),
        )
    )
    traineddata = next((item for item in candidates if item.is_file()), None)
    if traineddata is None:
        raise RuntimeError("English Tesseract traineddata is unavailable")
    return (
        _binary_identity(role="tesseract", path=executable, version=version),
        _binary_identity(role="eng-traineddata", path=traineddata, version=None),
    )


@lru_cache(maxsize=1)
def derive_environment_manifest() -> EnvironmentIdentityEvidence:
    distributions = tuple(
        sorted(
            (
                _installed_distribution_identity(name)
                for name in ENVIRONMENT_DISTRIBUTIONS
            ),
            key=lambda item: item.name,
        )
    )
    tesseract, traineddata = _tesseract_identities()
    cpu_model = platform.processor().strip() or platform.machine()
    if platform.system() == "Darwin":
        try:
            observed = subprocess.run(
                ("/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=5.0,
                check=True,
                env=_sanitized_worker_environment(),
            ).stdout.strip()
            if observed:
                cpu_model = observed
        except (OSError, subprocess.SubprocessError):
            pass
    payload: dict[str, Any] = {
        "schema_id": "phase-latency-environment-identity-v1",
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "python_cache_tag": sys.implementation.cache_tag,
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "cpu_model_sha256": hashlib.sha256(cpu_model.encode("utf-8")).hexdigest(),
        "logical_cpu_count": int(psutil.cpu_count(logical=True) or 0),
        "physical_cpu_count": int(psutil.cpu_count(logical=False) or 0),
        "total_memory_bytes": int(psutil.virtual_memory().total),
        "power_thermal_state": "unavailable_uncontrolled",
        "sanitized_worker_environment_sha256": worker_environment_sha256(
            _sanitized_worker_environment()
        ),
        "distributions": distributions,
        "binaries": (
            _binary_identity(
                role="python", path=Path(sys.executable), version=sys.version.split()[0]
            ),
            tesseract,
            traineddata,
        ),
        "p00_reference_docling_core_version": "2.87.1",
        "observed_docling_core_version": importlib.metadata.version("docling-core"),
        "p00_comparable": False,
        "noncomparability_reason": "docling-core-2.88.0-vs-p00-2.87.1",
    }
    payload["manifest_sha256"] = _canonical_hash(
        {
            key: (
                [item.model_dump(mode="json") for item in value]
                if isinstance(value, tuple)
                else value
            )
            for key, value in payload.items()
        }
    )
    return EnvironmentIdentityEvidence.model_validate(payload)


def derive_environment_sha256() -> str:
    return derive_environment_manifest().manifest_sha256


def _sanitized_worker_environment(
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    return controlled_worker_environment(
        Path.cwd(),
        os.environ if source is None else source,
    )


def derive_settings_sha256(settings: Any) -> str:
    return _canonical_hash(asdict(settings))


def derive_semantic_request_sha256(output_format: str) -> str:
    return _canonical_hash(
        {
            "endpoint": "/v1/parse",
            "method": "POST",
            "output_format": output_format,
            "semantic_contract": "complete-source-grounded-parse-result-v1",
        }
    )


def required_external_stage_inventory(
    *,
    source_suffix: str,
    output_format: str,
) -> tuple[StageName, ...]:
    from app.config import get_settings
    from tests.benchmarks.latency_instrumentation import (
        resolved_stage_cardinality_policies,
    )

    policies = resolved_stage_cardinality_policies(
        settings=get_settings(),
        source_suffix=source_suffix,
        output_format=output_format,
    )
    return tuple(
        sorted(
            (item.stage for item in policies if item.minimum_calls > 0),
            key=lambda item: item.value,
        )
    )


def derive_candidate_configuration(
    *,
    settings: Any,
    source_suffix: str,
    output_format: str,
    workspace: Path | None = None,
    worker_lifecycle: WorkerLifecycle = WorkerLifecycle.FRESH_PROCESS_REQUEST_COLD,
    content_result_cache_proof_sha256_value: str | None = None,
    synthetic_minimal: bool = False,
    bounded_concurrency: int = 1,
) -> ConfigurationIdentity:
    root = (workspace or Path.cwd()).resolve()
    if worker_lifecycle not in {
        WorkerLifecycle.FRESH_PROCESS_REQUEST_COLD,
        WorkerLifecycle.FRESH_PROCESS_REQUEST_PREWARMED,
    }:
        raise ValueError("external candidate configuration lifecycle differs")
    if (
        isinstance(bounded_concurrency, bool)
        or not isinstance(bounded_concurrency, int)
        or not 1 <= bounded_concurrency <= 4
    ):
        raise ValueError("candidate concurrency must be an integer in [1, 4]")
    from tests.benchmarks.latency_instrumentation import (
        content_result_cache_proof_sha256,
        resolved_stage_cardinality_policies,
    )

    if synthetic_minimal:
        policies = (
            StageCardinalityPolicy(
                policy_id="api-response-construction",
                stage=StageName.RESPONSE_MATERIALIZATION,
                minimum_calls=1,
                maximum_calls=1,
                condition_id="synthetic-harness-control",
                exclusive_group="response-format-route",
                allow_degraded_on_success=False,
                target_ids=("api-markdown-response",),
            ),
        )
    else:
        policies = resolved_stage_cardinality_policies(
            settings=settings,
            source_suffix=source_suffix,
            output_format=output_format,
        )
    lifecycle = worker_lifecycle
    is_cold = lifecycle is WorkerLifecycle.FRESH_PROCESS_REQUEST_COLD
    cache_proof = (
        content_result_cache_proof_sha256_value
        or content_result_cache_proof_sha256(root)
    )
    fields: dict[str, Any] = {
        "system": SystemName.CANDIDATE,
        "semantic_request_sha256": derive_semantic_request_sha256(output_format),
        "output_format": output_format,
        "cache_disabled": True,
        "service": "document-parse-api",
        "api_version": "v1",
        "tier": None,
        "cost_optimizer": None,
        "credits_per_page": None,
        "total_latency_metric": "asgi_complete_response_bytes",
        "cache_scope": "content_and_result_cache",
        "worker_lifecycle": lifecycle,
        "prewarm_completed_before_request": not is_cold,
        "bounded_concurrency": bounded_concurrency,
        "settings_sha256": derive_settings_sha256(settings),
        "runtime_sha256": derive_environment_sha256(),
        "model_artifacts_sha256": derive_model_artifacts_sha256(root),
        "internal_reuse_state": (
            "prewarmed_before_request"
            if not is_cold
            else "process_engine_cache_empty_at_request_start"
        ),
        "required_stage_inventory": tuple(
            sorted(
                (item.stage for item in policies if item.minimum_calls > 0),
                key=lambda item: item.value,
            )
        ),
        "stage_cardinality_policies": policies,
        "application_startup_completed_before_request": True,
        "pipeline_import_state_at_request_start": (
            "not_loaded" if is_cold else "loaded_by_controlled_prewarm"
        ),
        "engine_cache_state_at_request_start": (
            "module_not_loaded_process_cache_empty"
            if is_cold
            else "prewarmed_process_cache"
        ),
        "filesystem_cache_state": "uncontrolled_shared_host_cache",
        "content_result_cache_proof_sha256": cache_proof,
    }
    fields["system_configuration_sha256"] = configuration_identity_sha256(fields)
    return ConfigurationIdentity.model_validate(fields)


def derive_source_identity(
    path: Path,
    *,
    case_id: str,
    workspace: Path | None = None,
) -> SourceIdentity:
    root = (workspace or Path.cwd()).resolve()
    resolved = _resolve_workspace_path(root, path)
    relative = resolved.relative_to(root).as_posix()
    data = bounded_read_bytes(resolved, maximum_bytes=MAXIMUM_SOURCE_BYTES)
    suffix = resolved.suffix.casefold()
    if suffix == ".pdf":
        import pypdfium2 as pdfium

        with pdfium.PdfDocument(data) as document:
            page_count = len(document)
    elif suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            page_count = int(getattr(image, "n_frames", 1))
    else:
        raise ValueError("latency source extension is unsupported")
    if not 1 <= page_count <= 100:
        raise ValueError("source page count is outside the benchmark bound")
    return SourceIdentity(
        case_id=case_id,
        path=relative,
        filename=resolved.name,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        page_count=page_count,
    )


def _verify_workspace_file(
    workspace: Path,
    *,
    path: str,
    size_bytes: int,
    sha256: str,
    maximum_bytes: int,
) -> None:
    resolved = _resolve_workspace_path(workspace, Path(path))
    data = bounded_read_bytes(resolved, maximum_bytes=maximum_bytes)
    if len(data) != size_bytes or hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError("retained artifact identity mismatch")


def _verify_v2_network_artifact_custody(
    isolation: NetworkIsolationEvidence,
    *,
    workspace: Path,
    expected_worker_environment_sha256: str,
) -> None:
    """Recompute every stable v2 network-isolation artifact identity."""

    if isolation.policy != (
        "sanitized-offline-env-python-deny-and-os-process-tree-deny-v2"
    ):
        return
    sandbox = isolation.os_process_tree_sandbox
    sandbox_size_bytes, sandbox_sha256 = os_network_sandbox_identity()
    child_guard_size_bytes, child_guard_sha256 = child_network_guard_identity(workspace)
    if (
        isolation.worker_environment_sha256 != expected_worker_environment_sha256
        or sandbox is None
        or sandbox.executable_size_bytes != sandbox_size_bytes
        or sandbox.executable_sha256 != sandbox_sha256
        or sandbox.profile_size_bytes != OS_NETWORK_SANDBOX_PROFILE_SIZE_BYTES
        or sandbox.profile_sha256 != OS_NETWORK_SANDBOX_PROFILE_SHA256
        or sandbox.child_guard_size_bytes != child_guard_size_bytes
        or sandbox.child_guard_sha256 != child_guard_sha256
    ):
        raise ValueError("retained v2 network-isolation artifact custody differs")


def verify_campaign_custody(
    campaign: LatencyCampaign,
    *,
    workspace: Path | None = None,
    approved_provider_registry_sha256: str | None = None,
) -> None:
    """Verify every referenced source/UI artifact against its retained bytes."""

    root = (workspace or Path.cwd()).resolve()
    if campaign.candidate_code_sha256 != derive_candidate_code_sha256(root):
        raise ValueError("candidate source-tree identity mismatch")
    if campaign.dependency_lock_sha256 != derive_dependency_lock_sha256(root):
        raise ValueError("dependency-lock identity mismatch")
    if campaign.model_artifacts_sha256 != derive_model_artifacts_sha256(root):
        raise ValueError("model-artifact identity mismatch")
    if campaign.environment_sha256 != derive_environment_sha256():
        raise ValueError("benchmark environment identity mismatch")
    if (
        campaign.scope is not CampaignScope.SYNTHETIC_CONTROL
        and campaign.environment_manifest != derive_environment_manifest()
    ):
        raise ValueError("benchmark environment manifest differs")
    if campaign.scope is CampaignScope.PHASE_EXIT_ALL_15:
        if campaign.corpus_registry is None or campaign.phase03_oracle_artifact is None:
            raise ValueError("phase-exit corpus custody is incomplete")
        for artifact in (
            campaign.corpus_registry,
            campaign.phase03_oracle_artifact,
        ):
            _verify_workspace_file(
                root,
                path=artifact.path,
                size_bytes=artifact.size_bytes,
                sha256=artifact.sha256,
                maximum_bytes=4 * 1024 * 1024,
            )
        registry_artifact = campaign.provider_evidence_registry
        if (
            registry_artifact is None
            or approved_provider_registry_sha256 != registry_artifact.sha256
        ):
            raise ValueError("approved provider evidence registry identity is required")
        registry_bytes = bounded_read_bytes(
            _resolve_workspace_path(root, Path(registry_artifact.path)),
            maximum_bytes=4 * 1024 * 1024,
        )
        if (
            len(registry_bytes) != registry_artifact.size_bytes
            or hashlib.sha256(registry_bytes).hexdigest() != registry_artifact.sha256
        ):
            raise ValueError("provider evidence registry artifact differs")
        provider_registry = ProviderEvidenceRegistry.model_validate_json(registry_bytes)
        if canonical_model_bytes(provider_registry) != registry_bytes:
            raise ValueError("provider evidence registry is not canonical")
    else:
        provider_registry = None
    identities: dict[str, tuple[int, str, int]] = {}
    verified_sources: dict[str, SourceIdentity] = {}
    expected_v2_worker_environment_sha = worker_environment_sha256(
        _sanitized_worker_environment()
    )
    expected_v1_worker_environment_sha = worker_environment_sha256(
        sanitized_worker_environment()
    )
    for attempt in campaign.attempts:
        source_identity = (
            attempt.source.size_bytes,
            attempt.source.sha256,
            MAXIMUM_SOURCE_BYTES,
        )
        previous = identities.setdefault(attempt.source.path, source_identity)
        if previous != source_identity:
            raise ValueError("one retained path claimed conflicting source identities")
        actual_source = verified_sources.get(attempt.source.path)
        if actual_source is None:
            try:
                actual_source = derive_source_identity(
                    root / attempt.source.path,
                    case_id=attempt.case_id,
                    workspace=root,
                )
            except BaseException as error:
                raise ValueError(
                    "source identity mismatch or invalid page count"
                ) from error
            verified_sources[attempt.source.path] = actual_source
        if actual_source != attempt.source:
            raise ValueError("source identity/page count must derive from exact bytes")
        if attempt.system is SystemName.CANDIDATE:
            for isolation in (
                attempt.authoritative_network_isolation,
                attempt.diagnostic_network_isolation,
            ):
                if isolation is not None:
                    expected_worker_environment_sha256 = (
                        expected_v2_worker_environment_sha
                        if isolation.policy
                        == "sanitized-offline-env-python-deny-and-os-process-tree-deny-v2"
                        else expected_v1_worker_environment_sha
                    )
                    if isolation.worker_environment_sha256 != (
                        expected_worker_environment_sha256
                    ):
                        raise ValueError(
                            "worker sanitized environment identity differs"
                        )
                    _verify_v2_network_artifact_custody(
                        isolation,
                        workspace=root,
                        expected_worker_environment_sha256=(
                            expected_worker_environment_sha256
                        ),
                    )
            if campaign.scope is not CampaignScope.SYNTHETIC_CONTROL:
                from app.config import get_settings

                expected_configuration = derive_candidate_configuration(
                    settings=get_settings(),
                    source_suffix=Path(attempt.source.path).suffix,
                    output_format=attempt.configuration.output_format.value,
                    workspace=root,
                    worker_lifecycle=attempt.configuration.worker_lifecycle,
                    bounded_concurrency=attempt.configuration.bounded_concurrency,
                )
                if attempt.configuration != expected_configuration:
                    raise ValueError("candidate live configuration identity differs")
            if (
                attempt.instrumentation_manifest is not None
                and campaign.scope is not CampaignScope.SYNTHETIC_CONTROL
            ):
                from tests.benchmarks.latency_instrumentation import (
                    verify_instrumentation_manifest,
                )

                verify_instrumentation_manifest(
                    attempt.instrumentation_manifest,
                    workspace=root,
                )
                for artifact in attempt.instrumentation_manifest.harness_files:
                    artifact_identity = (
                        artifact.size_bytes,
                        artifact.sha256,
                        8 * 1024 * 1024,
                    )
                    previous = identities.setdefault(artifact.path, artifact_identity)
                    if previous != artifact_identity:
                        raise ValueError(
                            "one harness path claimed conflicting identities"
                        )
                for target in attempt.instrumentation_manifest.targets:
                    artifact = target.source
                    artifact_identity = (
                        artifact.size_bytes,
                        artifact.sha256,
                        8 * 1024 * 1024,
                    )
                    previous = identities.setdefault(artifact.path, artifact_identity)
                    if previous != artifact_identity:
                        raise ValueError(
                            "one observer source claimed conflicting identities"
                        )
        if attempt.provider_total_latency is not None:
            artifact = attempt.provider_total_latency.retained_ui_evidence
            artifact_identity = (
                artifact.size_bytes,
                artifact.sha256,
                MAXIMUM_UI_ARTIFACT_BYTES,
            )
            previous = identities.setdefault(artifact.path, artifact_identity)
            if previous != artifact_identity:
                raise ValueError("one retained path claimed conflicting UI identities")
            if campaign.scope is CampaignScope.PHASE_EXIT_ALL_15:
                if provider_registry is None or attempt.output is None:
                    raise ValueError("provider reviewed evidence is incomplete")
                sidecar_artifact = attempt.provider_total_latency.reviewed_sidecar
                if (
                    sidecar_artifact is None
                    or sidecar_artifact not in provider_registry.sidecars
                ):
                    raise ValueError("provider sidecar is not independently approved")
                sidecar_bytes = bounded_read_bytes(
                    _resolve_workspace_path(root, Path(sidecar_artifact.path)),
                    maximum_bytes=4 * 1024 * 1024,
                )
                if (
                    len(sidecar_bytes) != sidecar_artifact.size_bytes
                    or hashlib.sha256(sidecar_bytes).hexdigest()
                    != sidecar_artifact.sha256
                ):
                    raise ValueError("provider reviewed sidecar artifact differs")
                sidecar = ProviderEvidenceSidecar.model_validate_json(sidecar_bytes)
                if canonical_model_bytes(sidecar) != sidecar_bytes:
                    raise ValueError("provider reviewed sidecar is not canonical")
                provider = attempt.provider_total_latency
                if (
                    sidecar.source != attempt.source
                    or sidecar.job_id != provider.job_id
                    or sidecar.status != provider.status
                    or sidecar.display_value != provider.display_value
                    or sidecar.observed_at_utc != provider.observed_at_utc
                    or sidecar.screenshot != provider.retained_ui_evidence
                    or sidecar.provider_output != attempt.output
                ):
                    raise ValueError("provider sidecar semantics differ from attempt")
                for retained_artifact, maximum in (
                    (sidecar_artifact, 4 * 1024 * 1024),
                    (sidecar.screenshot, MAXIMUM_UI_ARTIFACT_BYTES),
                    (sidecar.structured_capture, 4 * 1024 * 1024),
                ):
                    if retained_artifact is None:
                        continue
                    retained_identity = (
                        retained_artifact.size_bytes,
                        retained_artifact.sha256,
                        maximum,
                    )
                    previous = identities.setdefault(
                        retained_artifact.path, retained_identity
                    )
                    if previous != retained_identity:
                        raise ValueError("provider evidence path identity conflicts")
        if (
            attempt.system is SystemName.LLAMAPARSE
            and attempt.output is not None
            and attempt.output.retained_artifact is not None
        ):
            output = attempt.output.retained_artifact
            output_identity = (
                output.size_bytes,
                output.sha256,
                MAXIMUM_RESPONSE_BYTES,
            )
            previous = identities.setdefault(output.path, output_identity)
            if previous != output_identity:
                raise ValueError("one retained path claimed conflicting outputs")
    for path, (size_bytes, sha256, maximum_bytes) in sorted(identities.items()):
        _verify_workspace_file(
            root,
            path=path,
            size_bytes=size_bytes,
            sha256=sha256,
            maximum_bytes=maximum_bytes,
        )


def _stage_failure_code(value: str | None, *, fallback: str) -> str:
    candidate = (value or fallback).casefold()
    if "timeout" in candidate:
        return "request_timeout"
    if "cancel" in candidate or candidate in {"keyboardinterrupt", "systemexit"}:
        return "request_cancelled"
    return "request_exception"


_RESOURCE_TRACKER_CODE = re.compile(
    r"from multiprocessing\.resource_tracker import main;main\(([0-9]+)\)\Z"
)


def _owned_resource_tracker_fd(
    process: psutil.Process,
    *,
    root_pid: int,
) -> int | None:
    try:
        command = tuple(process.cmdline())
        match = _RESOURCE_TRACKER_CODE.fullmatch(command[-1] if command else "")
        if (
            process.ppid() != root_pid
            or os.getpgid(process.pid) != root_pid
            or os.getsid(process.pid) != root_pid
            or Path(process.exe()).resolve()
            not in trusted_python_runtime_executable_paths()
            or Path(psutil.Process(root_pid).exe()).resolve()
            not in trusted_python_runtime_executable_paths()
            or len(command) < 3
            or command[-2] != "-c"
            or match is None
        ):
            return None
        return int(match.group(1))
    except (ProcessLookupError, psutil.Error, OSError):
        return None


def _attest_owned_resource_tracker(
    identity: ProcessIdentity,
    *,
    root_pid: int,
) -> tuple[psutil.Process, int, int]:
    """Bind one live direct tracker to its PID generation, session, and FD."""

    if identity.role is not ProcessRole.RESOURCE_TRACKER:
        raise RuntimeError("response descendant is not a resource tracker")
    process = psutil.Process(identity.pid)
    if int(process.create_time() * 1_000_000_000) != identity.create_time_ns:
        raise RuntimeError("resource tracker PID generation changed")
    tracker_read_fd = _owned_resource_tracker_fd(process, root_pid=root_pid)
    if tracker_read_fd is None:
        raise RuntimeError("resource tracker ownership signature differs")
    worker_write_fds: list[int] = []
    for candidate in darwin_pipe_file_descriptors(root_pid):
        try:
            attest_darwin_pipe_peers(
                root_pid,
                candidate,
                identity.pid,
                tracker_read_fd,
            )
        except RuntimeError:
            continue
        worker_write_fds.append(candidate)
    if len(worker_write_fds) != 1:
        raise RuntimeError("resource tracker peer pipe ownership differs")
    return process, tracker_read_fd, worker_write_fds[0]


def _wait_for_process_stopped_state(
    process: psutil.Process,
    *,
    stopped: bool,
    timeout_seconds: float = 1.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status = process.status()
        if (status == psutil.STATUS_STOPPED) is stopped:
            return
        time.sleep(0.005)
    state = "stopped" if stopped else "resumed"
    raise RuntimeError(f"resource tracker {state} state was not observed")


def _process_role(process: psutil.Process, *, root_pid: int) -> ProcessRole:
    if _owned_resource_tracker_fd(process, root_pid=root_pid) is not None:
        return ProcessRole.RESOURCE_TRACKER
    try:
        name = process.name().casefold()
    except (psutil.Error, OSError):
        name = ""
    if "tesseract" in name:
        return ProcessRole.TESSERACT
    if "docling" in name:
        return ProcessRole.DOCLING_CHILD
    return ProcessRole.OTHER_PARSER_CHILD


def _worker_hwm_bytes(rss_bytes: int, *, pid: int) -> int:
    if pid != os.getpid():
        # External observations retain RSS as a lower bound until the worker's
        # terminal self-report supplies exact ru_maxrss.
        return rss_bytes
    raw = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    measured = raw if platform.system() == "Darwin" else raw * 1_024
    return max(measured, rss_bytes)


def _fd_count(process: psutil.Process) -> int:
    if hasattr(process, "num_fds"):
        return int(process.num_fds())
    if hasattr(process, "num_handles"):
        return int(process.num_handles())
    raise RuntimeError("platform exposes neither process FDs nor handles")


@lru_cache(maxsize=1)
def _darwin_child_pid_reader() -> Any:
    libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    reader = libproc.proc_listchildpids
    reader.argtypes = (ctypes.c_int, ctypes.c_void_p, ctypes.c_int)
    reader.restype = ctypes.c_int
    return reader


def _direct_child_processes(process: psutil.Process) -> list[psutil.Process]:
    """List direct children without a system-wide process-table scan on Darwin."""

    if platform.system() != "Darwin":
        return list(process.children(recursive=False))
    capacity = MAXIMUM_PROCESSES_PER_SNAPSHOT + 1
    child_pids = (ctypes.c_int * capacity)()
    observed = int(
        _darwin_child_pid_reader()(
            int(process.pid),
            ctypes.byref(child_pids),
            ctypes.sizeof(child_pids),
        )
    )
    if observed < 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))
    if observed >= capacity:
        raise RuntimeError("process-tree descendant bound exceeded")
    retained: list[psutil.Process] = []
    for pid in child_pids[:observed]:
        if pid <= 0:
            raise RuntimeError("Darwin child PID evidence differs")
        try:
            retained.append(psutil.Process(int(pid)))
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
    return retained


def _process_metric(
    process: psutil.Process,
    *,
    role: ProcessRole,
    worker: bool,
) -> ProcessMetric:
    with process.oneshot():
        identity = ProcessIdentity(
            pid=int(process.pid),
            create_time_ns=max(1, int(process.create_time() * 1_000_000_000)),
            role=role,
        )
        memory = process.memory_info()
        cpu = process.cpu_times()
        rss_bytes = int(memory.rss)
        return ProcessMetric(
            identity=identity,
            rss_bytes=rss_bytes,
            user_cpu_ns=max(0, int(cpu.user * 1_000_000_000)),
            system_cpu_ns=max(0, int(cpu.system * 1_000_000_000)),
            thread_count=int(process.num_threads()),
            fd_count=_fd_count(process),
            self_hwm_bytes=(
                _worker_hwm_bytes(rss_bytes, pid=int(process.pid))
                if worker
                else None
            ),
        )


def read_process_tree_snapshot(
    root_pid: int,
    *,
    observed_monotonic_ns: int | None = None,
    allow_synthetic_root_only: bool = False,
) -> ProcessTreeSnapshot:
    """Read one recursively scoped process-tree snapshot with PID reuse guards."""

    root = psutil.Process(root_pid)
    root_metric = _process_metric(
        root,
        role=ProcessRole.CANDIDATE_WORKER,
        worker=True,
    )
    descendants: list[ProcessMetric] = []
    try:
        pending = [root]
        children: list[psutil.Process] = []
        seen = {(int(root.pid), int(root.create_time() * 1_000_000_000))}
        while pending:
            parent = pending.pop(0)
            try:
                direct = _direct_child_processes(parent)
            except (
                ProcessLookupError,
                psutil.NoSuchProcess,
                psutil.ZombieProcess,
            ):
                if int(parent.pid) == root_pid:
                    raise
                continue
            for child in direct:
                try:
                    identity = (
                        int(child.pid),
                        int(child.create_time() * 1_000_000_000),
                    )
                except (
                    ProcessLookupError,
                    psutil.NoSuchProcess,
                    psutil.ZombieProcess,
                ):
                    continue
                if identity in seen:
                    continue
                seen.add(identity)
                children.append(child)
                if len(children) >= MAXIMUM_PROCESSES_PER_SNAPSHOT:
                    raise RuntimeError("process-tree descendant bound exceeded")
                pending.append(child)
    except (PermissionError, psutil.AccessDenied):
        if not allow_synthetic_root_only:
            raise RuntimeError("recursive descendant observation is unavailable")
        children = []
    for child in children:
        try:
            descendants.append(
                _process_metric(
                    child,
                    role=_process_role(child, root_pid=root_pid),
                    worker=False,
                )
            )
        except (psutil.NoSuchProcess, psutil.ZombieProcess, OSError):
            continue
    descendants.sort(key=lambda item: (item.identity.pid, item.identity.create_time_ns))
    members = (root_metric, *descendants)
    observed_ns = (
        time.perf_counter_ns()
        if observed_monotonic_ns is None
        else _strict_monotonic_ns(
            observed_monotonic_ns,
            label="observed_monotonic_ns",
        )
    )
    return ProcessTreeSnapshot(
        observed_monotonic_ns=observed_ns,
        members=members,
        total_rss_bytes=sum(item.rss_bytes for item in members),
        total_user_cpu_ns=sum(item.user_cpu_ns for item in members),
        total_system_cpu_ns=sum(item.system_cpu_ns for item in members),
        total_thread_count=sum(item.thread_count for item in members),
        total_fd_count=sum(item.fd_count for item in members),
    )


def assemble_process_tree_metrics(
    snapshots: Sequence[ProcessTreeSnapshot],
    *,
    request_started_monotonic_ns: int,
    request_ended_monotonic_ns: int,
    sampling_interval_target_ns: int,
    hard_maximum_gap_ns: int,
    cleanup_disposition: str = "same_process_restored",
    worker_reaped: bool = False,
    worker_hwm_measurement_basis: str = "same_process_ru_maxrss",
    descendant_observation_basis: str = "recursive_psutil",
    exact_worker_self_cpu_ns: int | None = None,
    exact_reaped_children_cpu_ns: int = 0,
    reaped_children_hwm_bytes: int = 0,
    resource_boundary_basis: str = "same-process-rusage-self-v1",
    resource_boundary_complete: bool = True,
    response_boundary_snapshot_index: int | None = None,
    resource_tracker_freeze_disposition: str | None = None,
    resource_tracker_command_fd: int | None = None,
    resource_tracker_worker_write_fd: int | None = None,
    resource_tracker_stopped_state_verified: bool | None = None,
    resource_tracker_resumed_state_verified: bool | None = None,
    worker_reported_hwm_bytes_at_response_boundary: int | None = None,
    lifecycle_exact_worker_self_cpu_ns: int | None = None,
    lifecycle_reaped_children_cpu_ns: int | None = None,
) -> ProcessTreeMetrics:
    """Create a fully recomputed process-tree record from retained samples."""

    retained = tuple(snapshots)
    if len(retained) < 2:
        raise ValueError("at least baseline and terminal process samples are required")
    gaps = tuple(
        current.observed_monotonic_ns - previous.observed_monotonic_ns
        for previous, current in pairwise(retained)
    )
    v2 = response_boundary_snapshot_index is not None
    if v2 and (
        response_boundary_snapshot_index < 1
        or response_boundary_snapshot_index >= len(retained) - 1
    ):
        raise ValueError("v2 response boundary index is invalid")
    request_retained = (
        retained[: response_boundary_snapshot_index + 1]
        if response_boundary_snapshot_index is not None
        else retained
    )
    cpu_baselines: dict[tuple[int, int], int] = {}
    cpu_maxima: dict[tuple[int, int], int] = {}
    for snapshot in request_retained:
        for member in snapshot.members:
            identity = (member.identity.pid, member.identity.create_time_ns)
            cumulative = member.user_cpu_ns + member.system_cpu_ns
            if identity not in cpu_baselines:
                cpu_baselines[identity] = (
                    cumulative
                    if snapshot.observed_monotonic_ns <= request_started_monotonic_ns
                    else 0
                )
            cpu_maxima[identity] = max(
                cpu_maxima.get(identity, cumulative),
                cumulative,
            )
    observed_cpu_ns = sum(
        max(0, maximum - cpu_baselines[identity])
        for identity, maximum in cpu_maxima.items()
    )
    peak_worker_hwm_bytes = max(
        int(item.members[0].self_hwm_bytes or 0) for item in request_retained
    )
    response_snapshot = (
        retained[response_boundary_snapshot_index]
        if response_boundary_snapshot_index is not None
        else None
    )
    closure_snapshot = retained[-1] if response_snapshot is not None else None
    baseline_descendant_cpu = (
        sum(
            member.user_cpu_ns + member.system_cpu_ns
            for member in retained[0].members[1:]
        )
        if response_snapshot is not None
        else None
    )
    response_descendant_cpu = (
        sum(
            member.user_cpu_ns + member.system_cpu_ns
            for member in response_snapshot.members[1:]
        )
        if response_snapshot is not None
        else None
    )
    frozen_descendant_cpu = (
        int(response_descendant_cpu or 0) - int(baseline_descendant_cpu or 0)
        if response_snapshot is not None
        else 0
    )
    if frozen_descendant_cpu < 0:
        raise ValueError("response descendant CPU regressed from baseline")
    post_response_lifecycle_cpu_ns = None
    if response_snapshot is not None:
        if (
            lifecycle_exact_worker_self_cpu_ns is None
            or lifecycle_reaped_children_cpu_ns is None
            or exact_worker_self_cpu_ns is None
        ):
            raise ValueError("v2 lifecycle CPU inputs are incomplete")
        post_response_lifecycle_cpu_ns = (
            lifecycle_exact_worker_self_cpu_ns
            - exact_worker_self_cpu_ns
            + lifecycle_reaped_children_cpu_ns
            - exact_reaped_children_cpu_ns
            - int(response_descendant_cpu or 0)
        )
        if post_response_lifecycle_cpu_ns < 0:
            raise ValueError("v2 post-response lifecycle CPU is negative")
    lifecycle_peak_worker_hwm = (
        max(int(item.members[0].self_hwm_bytes or 0) for item in retained)
        if response_snapshot is not None
        else None
    )
    return ProcessTreeMetrics(
        schema_id=PROCESS_TREE_SCHEMA_ID,
        scope="candidate_worker_and_descendants",
        request_started_monotonic_ns=request_started_monotonic_ns,
        request_ended_monotonic_ns=request_ended_monotonic_ns,
        sampling_interval_target_ns=sampling_interval_target_ns,
        hard_maximum_gap_ns=hard_maximum_gap_ns,
        maximum_observed_gap_ns=max(gaps),
        snapshots=retained,
        peak_total_rss_bytes=max(item.total_rss_bytes for item in request_retained),
        peak_worker_hwm_bytes=peak_worker_hwm_bytes,
        maximum_observed_process_cpu_ns=observed_cpu_ns,
        exact_worker_self_cpu_ns=(
            observed_cpu_ns
            if exact_worker_self_cpu_ns is None
            else exact_worker_self_cpu_ns
        ),
        exact_reaped_children_cpu_ns=exact_reaped_children_cpu_ns,
        conservative_frozen_response_boundary_descendant_cpu_ns=(frozen_descendant_cpu),
        post_response_lifecycle_cpu_ns=post_response_lifecycle_cpu_ns,
        baseline_descendant_cumulative_cpu_ns=baseline_descendant_cpu,
        response_boundary_descendant_cumulative_cpu_ns=(response_descendant_cpu),
        lifecycle_exact_worker_self_cpu_ns=lifecycle_exact_worker_self_cpu_ns,
        lifecycle_reaped_children_cpu_ns=lifecycle_reaped_children_cpu_ns,
        reaped_children_hwm_bytes=reaped_children_hwm_bytes,
        conservative_process_lifetime_hwm_bytes=(
            None
            if response_snapshot is not None
            else peak_worker_hwm_bytes + reaped_children_hwm_bytes
        ),
        lifecycle_root_hwm_plus_max_reaped_child_hwm_component_bytes=(
            int(lifecycle_peak_worker_hwm or 0) + reaped_children_hwm_bytes
            if lifecycle_peak_worker_hwm is not None
            else None
        ),
        resource_boundary_basis=resource_boundary_basis,
        resource_boundary_complete=resource_boundary_complete,
        response_boundary_snapshot=response_snapshot,
        response_boundary_snapshot_index=response_boundary_snapshot_index,
        resource_closure_snapshot=closure_snapshot,
        response_boundary_descendant_count=(
            len(response_snapshot.members) - 1
            if response_snapshot is not None
            else None
        ),
        response_boundary_descendant_roles=(
            tuple(member.identity.role for member in response_snapshot.members[1:])
            if response_snapshot is not None
            else None
        ),
        resource_closure_complete=(
            len(closure_snapshot.members) == 1 if closure_snapshot is not None else None
        ),
        resource_tracker_freeze_disposition=(resource_tracker_freeze_disposition),
        resource_tracker_command_fd=resource_tracker_command_fd,
        resource_tracker_worker_write_fd=resource_tracker_worker_write_fd,
        resource_tracker_stopped_state_verified=(
            resource_tracker_stopped_state_verified
        ),
        resource_tracker_resumed_state_verified=(
            resource_tracker_resumed_state_verified
        ),
        response_through_resource_closure_peak_total_rss_bytes=(
            max(
                item.total_rss_bytes
                for item in retained[response_boundary_snapshot_index:]
            )
            if response_snapshot is not None
            else None
        ),
        worker_reported_hwm_bytes_at_response_boundary=(
            worker_reported_hwm_bytes_at_response_boundary
        ),
        worker_lifetime_hwm_bytes_at_resource_closure=(
            int(closure_snapshot.members[0].self_hwm_bytes or 0)
            if closure_snapshot is not None
            else None
        ),
        rss_measurement_basis="sampled_process_tree_lower_bound_at_bounded_cadence",
        cpu_measurement_basis="sum_of_per_process_request_cumulative_deltas",
        worker_hwm_measurement_basis=worker_hwm_measurement_basis,
        descendant_observation_basis=descendant_observation_basis,
        cleanup_disposition=cleanup_disposition,
        worker_reaped=worker_reaped,
        observed_descendants_reaped=True,
    )


class ProcessTreeSampler:
    """Periodic current-worker sampler with baseline and terminal cleanup gates."""

    def __init__(
        self,
        *,
        root_pid: int | None = None,
        target_interval_ns: int = DEFAULT_SAMPLE_INTERVAL_NS,
        hard_maximum_gap_ns: int = DEFAULT_HARD_MAXIMUM_GAP_NS,
        snapshot_reader: Callable[[int], ProcessTreeSnapshot] | None = None,
    ) -> None:
        self.root_pid = os.getpid() if root_pid is None else root_pid
        if self.root_pid != os.getpid():
            raise ValueError("sampler root must be the current candidate worker")
        if target_interval_ns <= 0 or hard_maximum_gap_ns < target_interval_ns:
            raise ValueError("sampler cadence must be positive and bounded")
        maximum_expected_samples = (
            MAXIMUM_PROFILE_DURATION_NS + target_interval_ns - 1
        ) // target_interval_ns + 2
        if maximum_expected_samples > MAXIMUM_PROCESS_SNAPSHOTS:
            raise ValueError("sampler cadence can exceed the retained snapshot bound")
        self.target_interval_ns = target_interval_ns
        self.hard_maximum_gap_ns = hard_maximum_gap_ns
        self._snapshot_reader = snapshot_reader or (
            lambda observed_ns: read_process_tree_snapshot(
                self.root_pid,
                observed_monotonic_ns=observed_ns,
            )
        )
        self._stop = threading.Event()
        self._samples: list[ProcessTreeSnapshot] = []
        self._error: BaseException | None = None

    def _sample(self) -> None:
        if len(self._samples) >= MAXIMUM_PROCESS_SNAPSHOTS:
            raise RuntimeError("process-tree snapshot retention bound exceeded")
        self._samples.append(self._snapshot_reader(time.perf_counter_ns()))

    def _run(self) -> None:
        interval_seconds = self.target_interval_ns / 1_000_000_000
        while not self._stop.wait(interval_seconds):
            try:
                self._sample()
            except BaseException as error:  # noqa: BLE001 - retain cancellations
                self._error = error
                self._stop.set()

    def profile(self, operation: Callable[[], T]) -> ProfileResult[T]:
        if self._samples:
            raise RuntimeError("a process-tree sampler instance is single-use")
        self._sample()
        worker = threading.Thread(
            target=self._run,
            name="phase-latency-process-tree-sampler",
            daemon=False,
        )
        worker.start()
        request_started_ns = time.perf_counter_ns()
        result: T | None = None
        operation_error: BaseException | None = None
        try:
            result = operation()
        except BaseException as error:  # noqa: BLE001 - cancellation is evidence
            operation_error = error
        finally:
            request_ended_ns = time.perf_counter_ns()
            self._stop.set()
            worker.join()
        evidence_errors: list[BaseException] = []
        if self._error is not None:
            evidence_errors.append(
                RuntimeError("process-tree periodic sampling failed")
            )
            evidence_errors[-1].__cause__ = self._error
        try:
            self._sample()
            metrics = assemble_process_tree_metrics(
                self._samples,
                request_started_monotonic_ns=request_started_ns,
                request_ended_monotonic_ns=request_ended_ns,
                sampling_interval_target_ns=self.target_interval_ns,
                hard_maximum_gap_ns=self.hard_maximum_gap_ns,
            )
        except BaseException as error:  # noqa: BLE001 - preserve cleanup failures
            evidence_errors.append(error)
        if evidence_errors:
            combined = (
                [operation_error] if operation_error is not None else []
            ) + evidence_errors
            raise BaseExceptionGroup("local profile and evidence failures", combined)
        return ProfileResult(
            result=result,
            operation_error=operation_error,
            process_tree=metrics,
        )


def _write_sampler_frame(fd: int, value: Mapping[str, Any]) -> None:
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if not payload or len(payload) > MAXIMUM_SAMPLER_EVIDENCE_BYTES:
        raise RuntimeError("external sampler frame exceeds its bound")
    framed = struct.pack("!Q", len(payload)) + payload
    offset = 0
    while offset < len(framed):
        written = os.write(fd, framed[offset:])
        if written <= 0:
            raise RuntimeError("external sampler frame write failed")
        offset += written


def _request_external_sampler_qos() -> None:
    """Give only the lightweight observer thread a bounded-cadence QoS."""

    if platform.system() != "Darwin":
        return
    libc = ctypes.CDLL(None)
    setter = libc.pthread_set_qos_class_self_np
    setter.argtypes = (ctypes.c_uint, ctypes.c_int)
    setter.restype = ctypes.c_int
    result = int(setter(DARWIN_SAMPLER_QOS_CLASS_USER_INTERACTIVE, 0))
    if result != 0:
        raise OSError(result, os.strerror(result))


def _external_sampler_process_main(
    *,
    root_pid: int,
    target_interval_ns: int,
    lane_index: int,
    allow_synthetic_root_only: bool,
    command_fd: int,
    evidence_fd: int,
    snapshot_reader: Callable[..., ProcessTreeSnapshot] | None = None,
    request_qos: bool = True,
) -> None:
    """Run periodic psutil reads outside the controller's scheduling domain."""

    retained: list[ProcessTreeSnapshot] = []
    try:
        if request_qos:
            _request_external_sampler_qos()
        _write_sampler_frame(
            evidence_fd,
            {
                "schema_id": "phase-latency-external-sampler-process-v1",
                "status": "ready",
            },
        )
        lane_interval_ns = (
            target_interval_ns * EXTERNAL_SAMPLER_PROCESS_LANE_COUNT
        )
        next_sample_ns = (
            time.perf_counter_ns() + target_interval_ns * (lane_index + 1)
        )
        while True:
            remaining_seconds = max(
                0.0,
                (next_sample_ns - time.perf_counter_ns()) / 1_000_000_000,
            )
            readable, _, _ = select.select(
                (command_fd,),
                (),
                (),
                remaining_seconds,
            )
            if readable:
                command = os.read(command_fd, 1)
                if command != b"S":
                    raise RuntimeError("external sampler command differs")
                break
            if len(retained) >= (
                MAXIMUM_PROCESS_SNAPSHOTS
                // EXTERNAL_SAMPLER_PROCESS_LANE_COUNT
                - 1
            ):
                raise RuntimeError("external process snapshot bound exceeded")
            retained.append(
                (snapshot_reader or read_process_tree_snapshot)(
                    root_pid,
                    allow_synthetic_root_only=allow_synthetic_root_only,
                )
            )
            next_sample_ns += lane_interval_ns
            if next_sample_ns < time.perf_counter_ns():
                next_sample_ns = time.perf_counter_ns()
        _write_sampler_frame(
            evidence_fd,
            {
                "schema_id": "phase-latency-external-sampler-process-v1",
                "status": "success",
                "snapshots": tuple(
                    item.model_dump(mode="json") for item in retained
                ),
            },
        )
    except BaseException as error:  # noqa: BLE001 - child evidence fails closed
        try:
            _write_sampler_frame(
                evidence_fd,
                {
                    "error_type": _exception_type(error),
                    "schema_id": "phase-latency-external-sampler-process-v1",
                    "status": "error",
                    "snapshots": tuple(
                        item.model_dump(mode="json") for item in retained
                    ),
                },
            )
        except BaseException:
            os._exit(WORKER_FATAL_ENVELOPE_WRITE_FAILED_EXIT_CODE)
        os._exit(WORKER_FATAL_EXIT_CODE)
    os._exit(0)


class ExternalProcessTreeSampler:
    """Bounded sampler owned by the controller, never by the parser worker."""

    def __init__(
        self,
        root_pid: int,
        *,
        target_interval_ns: int = DEFAULT_SAMPLE_INTERVAL_NS,
        hard_maximum_gap_ns: int = DEFAULT_HARD_MAXIMUM_GAP_NS,
        allow_synthetic_root_only: bool = False,
        snapshot_reader: Callable[..., ProcessTreeSnapshot] | None = None,
    ) -> None:
        if root_pid == os.getpid() or root_pid <= 0:
            raise ValueError("external sampler requires an owned child worker")
        child_lane_samples = (
            MAXIMUM_PROFILE_DURATION_NS + target_interval_ns - 1
        ) // target_interval_ns
        controller_lane_interval_ns = (
            target_interval_ns * EXTERNAL_SAMPLER_PROCESS_LANE_COUNT
        )
        controller_lane_samples = (
            MAXIMUM_PROFILE_DURATION_NS + controller_lane_interval_ns - 1
        ) // controller_lane_interval_ns
        maximum_expected_samples = (
            child_lane_samples + controller_lane_samples + 5
        )
        if (
            target_interval_ns <= 0
            or hard_maximum_gap_ns < target_interval_ns
            or maximum_expected_samples > MAXIMUM_PROCESS_SNAPSHOTS
        ):
            raise ValueError("external sampler cadence is invalid or unbounded")
        self.root_pid = root_pid
        self.target_interval_ns = target_interval_ns
        self.hard_maximum_gap_ns = hard_maximum_gap_ns
        self.allow_synthetic_root_only = allow_synthetic_root_only
        self._snapshot_reader = snapshot_reader
        self._samples: list[ProcessTreeSnapshot] = []
        self._error: BaseException | None = None
        self._lock = threading.Lock()
        self._capture_lock = threading.Lock()
        self._sampler_pids: list[int] = []
        self._sampler_create_time_ns: list[int] = []
        self._command_fds: list[int | None] = []
        self._evidence_fds: list[int | None] = []
        self._sampler_wait_statuses: list[int | None] = []
        self._sampler_stopped = False
        self._controller_stop = threading.Event()
        self._controller_thread: threading.Thread | None = None
        self._boundary_captured = False
        self._resource_closure_captured = False
        self.response_boundary_snapshot: ProcessTreeSnapshot | None = None
        self.response_boundary_snapshot_index: int | None = None
        self.resource_closure_snapshot: ProcessTreeSnapshot | None = None
        self.resource_tracker_freeze_disposition: str | None = None
        self.resource_tracker_command_fd: int | None = None
        self.resource_tracker_worker_write_fd: int | None = None
        self.resource_tracker_stopped_state_verified: bool | None = None
        self.resource_tracker_resumed_state_verified: bool | None = None

    def _sample_locked(self) -> tuple[int, ProcessTreeSnapshot]:
        snapshot = (self._snapshot_reader or read_process_tree_snapshot)(
            self.root_pid,
            allow_synthetic_root_only=self.allow_synthetic_root_only,
        )
        with self._lock:
            if len(self._samples) >= MAXIMUM_PROCESS_SNAPSHOTS:
                raise RuntimeError("external process snapshot bound exceeded")
            if self._samples and snapshot.observed_monotonic_ns <= (
                self._samples[-1].observed_monotonic_ns
            ):
                raise RuntimeError("external sampling clock did not advance")
            self._samples.append(snapshot)
            return len(self._samples) - 1, snapshot

    def _sample(self) -> None:
        with self._capture_lock:
            self._sample_locked()

    def _sample_initial_baseline(self) -> None:
        """Retry only transient pre-request OS reads; never retry a request."""

        retained_error: BaseException | None = None
        for retry_index in range(3):
            try:
                self._sample_locked()
                return
            except (
                ProcessLookupError,
                psutil.NoSuchProcess,
                psutil.ZombieProcess,
            ):
                raise
            except (OSError, psutil.Error) as error:
                retained_error = error
                if retry_index < 2:
                    time.sleep(0.01)
        raise RuntimeError(
            "external sampler baseline OS read remained unavailable"
        ) from retained_error

    def _run_controller_lane(self) -> None:
        try:
            _request_external_sampler_qos()
        except BaseException as error:  # noqa: BLE001 - evidence fails closed
            with self._lock:
                if self._error is None:
                    self._error = error
            self._controller_stop.set()
            return
        lane_interval_ns = (
            self.target_interval_ns * EXTERNAL_SAMPLER_PROCESS_LANE_COUNT
        )
        next_sample_ns = time.perf_counter_ns() + self.target_interval_ns // 2
        while True:
            remaining_seconds = max(
                0.0,
                (next_sample_ns - time.perf_counter_ns()) / 1_000_000_000,
            )
            if self._controller_stop.wait(remaining_seconds):
                return
            try:
                self._sample()
            except BaseException as error:  # noqa: BLE001 - evidence fails closed
                with self._lock:
                    if self._error is None:
                        self._error = error
                self._controller_stop.set()
                return
            next_sample_ns += lane_interval_ns
            if next_sample_ns < time.perf_counter_ns():
                next_sample_ns = time.perf_counter_ns()

    def _stop_controller_lane(self) -> None:
        self._controller_stop.set()
        if self._controller_thread is None:
            return
        self._controller_thread.join(timeout=2.0)
        if self._controller_thread.is_alive():
            raise RuntimeError("controller sampler thread did not terminate")

    def _read_exact_sampler_bytes(
        self,
        size: int,
        *,
        deadline: float,
        lane_index: int,
    ) -> bytes:
        evidence_fd = self._evidence_fds[lane_index]
        if evidence_fd is None:
            raise RuntimeError("external sampler evidence FD is absent")
        retained = bytearray()
        while len(retained) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("external sampler evidence timed out")
            readable, _, _ = select.select(
                (evidence_fd,),
                (),
                (),
                remaining,
            )
            if not readable:
                raise TimeoutError("external sampler evidence timed out")
            chunk = os.read(evidence_fd, size - len(retained))
            if not chunk:
                raise RuntimeError("external sampler evidence truncated")
            retained.extend(chunk)
        return bytes(retained)

    def _read_sampler_frame(
        self,
        *,
        timeout_seconds: float,
        lane_index: int,
    ) -> Mapping[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        header = self._read_exact_sampler_bytes(
            8,
            deadline=deadline,
            lane_index=lane_index,
        )
        size = struct.unpack("!Q", header)[0]
        if not 0 < size <= MAXIMUM_SAMPLER_EVIDENCE_BYTES:
            raise RuntimeError("external sampler frame size differs")
        payload = self._read_exact_sampler_bytes(
            size,
            deadline=deadline,
            lane_index=lane_index,
        )
        value = json.loads(payload.decode("utf-8", errors="strict"))
        if (
            not isinstance(value, dict)
            or json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            != payload
        ):
            raise RuntimeError("external sampler frame is non-canonical")
        return value

    def _merge_periodic_samples(
        self,
        periodic: Sequence[ProcessTreeSnapshot],
    ) -> None:
        response_time = (
            self.response_boundary_snapshot.observed_monotonic_ns
            if self.response_boundary_snapshot is not None
            else None
        )
        with self._lock:
            combined = sorted(
                (*self._samples, *periodic),
                key=lambda item: item.observed_monotonic_ns,
            )
            if len(combined) > MAXIMUM_PROCESS_SNAPSHOTS:
                raise RuntimeError("external process snapshot bound exceeded")
            if any(
                right.observed_monotonic_ns <= left.observed_monotonic_ns
                for left, right in pairwise(combined)
            ):
                raise RuntimeError("external sampling clock did not advance")
            self._samples = combined
            if response_time is not None:
                matching = tuple(
                    index
                    for index, snapshot in enumerate(combined)
                    if snapshot.observed_monotonic_ns == response_time
                )
                if len(matching) != 1:
                    raise RuntimeError("response boundary sample identity differs")
                self.response_boundary_snapshot_index = matching[0]

    def _wait_sampler_process(
        self,
        *,
        timeout_seconds: float,
        lane_index: int,
    ) -> int:
        if lane_index >= len(self._sampler_pids):
            raise RuntimeError("external sampler process is absent")
        retained_status = self._sampler_wait_statuses[lane_index]
        if retained_status is not None:
            return retained_status
        sampler_pid = self._sampler_pids[lane_index]
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            waited_pid, status = os.waitpid(sampler_pid, os.WNOHANG)
            if waited_pid == sampler_pid:
                self._sampler_wait_statuses[lane_index] = status
                return status
            time.sleep(0.005)
        raise TimeoutError("external sampler process did not terminate")

    def _terminate_sampler_process(self, lane_index: int) -> None:
        if (
            lane_index >= len(self._sampler_pids)
            or self._sampler_wait_statuses[lane_index] is not None
        ):
            return
        sampler_pid = self._sampler_pids[lane_index]
        try:
            os.kill(sampler_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            _, status = os.waitpid(sampler_pid, 0)
        except ChildProcessError:
            return
        self._sampler_wait_statuses[lane_index] = status

    def _stop_periodic_process(self) -> None:
        if self._sampler_stopped:
            return
        if (
            len(self._command_fds) != EXTERNAL_SAMPLER_PROCESS_LANE_COUNT
            or any(fd is None for fd in self._command_fds)
        ):
            raise RuntimeError("external sampler command FD is absent")
        frames: list[Mapping[str, Any]] = []
        statuses: list[int] = []
        controller_error: BaseException | None = None
        try:
            self._stop_controller_lane()
        except BaseException as error:  # noqa: BLE001 - still reap child lanes
            controller_error = error
        try:
            for lane_index, sampler_pid in enumerate(self._sampler_pids):
                waited_pid, status = os.waitpid(sampler_pid, os.WNOHANG)
                if waited_pid == sampler_pid:
                    self._sampler_wait_statuses[lane_index] = status
                else:
                    command_fd = self._command_fds[lane_index]
                    assert command_fd is not None
                    try:
                        written = os.write(command_fd, b"S")
                    except BrokenPipeError:
                        written = 1
                    if written != 1:
                        raise RuntimeError("external sampler stop command failed")
                command_fd = self._command_fds[lane_index]
                assert command_fd is not None
                os.close(command_fd)
                self._command_fds[lane_index] = None
            for lane_index in range(EXTERNAL_SAMPLER_PROCESS_LANE_COUNT):
                frames.append(
                    self._read_sampler_frame(
                        timeout_seconds=10.0,
                        lane_index=lane_index,
                    )
                )
                statuses.append(
                    self._wait_sampler_process(
                        timeout_seconds=5.0,
                        lane_index=lane_index,
                    )
                )
        except BaseException:
            for lane_index in range(len(self._sampler_pids)):
                self._terminate_sampler_process(lane_index)
            for lane_index, command_fd in enumerate(self._command_fds):
                if command_fd is not None:
                    os.close(command_fd)
                    self._command_fds[lane_index] = None
            raise
        finally:
            for lane_index, evidence_fd in enumerate(self._evidence_fds):
                if evidence_fd is not None:
                    os.close(evidence_fd)
                    self._evidence_fds[lane_index] = None
            self._sampler_stopped = True
        periodic: list[ProcessTreeSnapshot] = []
        for frame, status in zip(frames, statuses, strict=True):
            if frame.get("schema_id") != (
                "phase-latency-external-sampler-process-v1"
            ):
                raise RuntimeError("external sampler schema differs")
            raw_snapshots = frame.get("snapshots")
            if not isinstance(raw_snapshots, list):
                raise RuntimeError("external sampler snapshot inventory differs")
            periodic.extend(
                ProcessTreeSnapshot.model_validate(item)
                for item in raw_snapshots
            )
            exit_code = os.waitstatus_to_exitcode(status)
            if frame.get("status") == "error":
                error_type = frame.get("error_type")
                if not isinstance(error_type, str) or not error_type:
                    raise RuntimeError("external sampler error family differs")
                if self._error is None:
                    self._error = RuntimeError(
                        f"external sampler process failed: {error_type}"
                    )
            elif frame.get("status") != "success" or exit_code != 0:
                raise RuntimeError("external sampler process disposition differs")
        self._merge_periodic_samples(periodic)
        if controller_error is not None:
            raise RuntimeError(
                "controller periodic process sampling failed"
            ) from controller_error
        if self._error is not None:
            raise RuntimeError(
                "external periodic process sampling failed"
            ) from self._error

    def start(self) -> None:
        if self._sampler_pids:
            raise RuntimeError("external sampler is single-use")
        try:
            self._sample_initial_baseline()
            for lane_index in range(EXTERNAL_SAMPLER_PROCESS_LANE_COUNT):
                command_read_fd, command_write_fd = os.pipe()
                evidence_read_fd, evidence_write_fd = os.pipe()
                sampler_pid = os.fork()
                if sampler_pid == 0:
                    os.close(command_write_fd)
                    os.close(evidence_read_fd)
                    null_fd = os.open(os.devnull, os.O_RDWR)
                    try:
                        for standard_fd in (0, 1, 2):
                            os.dup2(null_fd, standard_fd)
                    finally:
                        if null_fd > 2:
                            os.close(null_fd)
                    if self._snapshot_reader is not None:
                        _external_sampler_process_main(
                            root_pid=self.root_pid,
                            target_interval_ns=self.target_interval_ns,
                            lane_index=lane_index,
                            allow_synthetic_root_only=(
                                self.allow_synthetic_root_only
                            ),
                            command_fd=command_read_fd,
                            evidence_fd=evidence_write_fd,
                            snapshot_reader=self._snapshot_reader,
                            request_qos=False,
                        )
                    try:
                        os.set_inheritable(command_read_fd, True)
                        os.set_inheritable(evidence_write_fd, True)
                        command = (
                            sys.executable,
                            "-m",
                            "tests.benchmarks.latency_runner",
                            "_external-sampler-process",
                            "--root-pid",
                            str(self.root_pid),
                            "--target-interval-ns",
                            str(self.target_interval_ns),
                            "--lane-index",
                            str(lane_index),
                            "--allow-synthetic-root-only",
                            str(int(self.allow_synthetic_root_only)),
                            "--command-fd",
                            str(command_read_fd),
                            "--evidence-fd",
                            str(evidence_write_fd),
                        )
                        os.execve(sys.executable, command, dict(os.environ))
                    except BaseException as error:  # noqa: BLE001
                        try:
                            _write_sampler_frame(
                                evidence_write_fd,
                                {
                                    "error_type": _exception_type(error),
                                    "schema_id": (
                                        "phase-latency-external-sampler-process-v1"
                                    ),
                                    "status": "error",
                                    "snapshots": (),
                                },
                            )
                        except BaseException:
                            os._exit(
                                WORKER_FATAL_ENVELOPE_WRITE_FAILED_EXIT_CODE
                            )
                        os._exit(WORKER_FATAL_EXIT_CODE)
                    os._exit(WORKER_FATAL_ENVELOPE_WRITE_FAILED_EXIT_CODE)
                os.close(command_read_fd)
                os.close(evidence_write_fd)
                self._sampler_pids.append(sampler_pid)
                self._command_fds.append(command_write_fd)
                self._evidence_fds.append(evidence_read_fd)
                self._sampler_wait_statuses.append(None)
                self._sampler_create_time_ns.append(
                    max(
                        1,
                        int(
                            psutil.Process(sampler_pid).create_time()
                            * 1_000_000_000
                        ),
                    )
                )
                frame = self._read_sampler_frame(
                    timeout_seconds=10.0,
                    lane_index=lane_index,
                )
                if frame.get("status") == "error":
                    error_type = frame.get("error_type")
                    if (
                        frame.get("schema_id")
                        != "phase-latency-external-sampler-process-v1"
                        or not isinstance(error_type, str)
                        or not error_type
                        or frame.get("snapshots") != []
                        or set(frame)
                        != {"error_type", "schema_id", "snapshots", "status"}
                    ):
                        raise RuntimeError(
                            "external sampler ready error frame differs"
                        )
                    raise RuntimeError(
                        f"external sampler ready failed: {error_type}"
                    )
                if (
                    frame.get("schema_id")
                    != "phase-latency-external-sampler-process-v1"
                    or frame.get("status") != "ready"
                    or set(frame) != {"schema_id", "status"}
                ):
                    raise RuntimeError("external sampler ready frame differs")
            self._controller_thread = threading.Thread(
                target=self._run_controller_lane,
                name="phase-latency-controller-sampler",
                daemon=False,
            )
            self._controller_thread.start()
        except BaseException:
            self._controller_stop.set()
            if self._controller_thread is not None:
                self._controller_thread.join(timeout=2.0)
            for lane_index in range(len(self._sampler_pids)):
                self._terminate_sampler_process(lane_index)
            for lane_index, command_fd in enumerate(self._command_fds):
                if command_fd is not None:
                    os.close(command_fd)
                    self._command_fds[lane_index] = None
            for lane_index, evidence_fd in enumerate(self._evidence_fds):
                if evidence_fd is not None:
                    os.close(evidence_fd)
                    self._evidence_fds[lane_index] = None
            self._sampler_stopped = True
            raise

    def capture_response_boundary(self) -> None:
        """Freeze the process timeline before worker-side response validation."""

        if not self._sampler_pids or self._boundary_captured:
            raise RuntimeError("external response boundary is single-capture")
        if self._error is not None:
            raise RuntimeError(
                "external periodic process sampling failed"
            ) from self._error
        with self._capture_lock:
            if self._error is not None:
                raise RuntimeError(
                    "external periodic process sampling failed"
                ) from self._error
            try:
                preview = (self._snapshot_reader or read_process_tree_snapshot)(
                    self.root_pid,
                    allow_synthetic_root_only=self.allow_synthetic_root_only,
                )
            except BaseException as error:
                with self._lock:
                    if self._error is None:
                        self._error = error
                raise RuntimeError(
                    "external periodic process sampling failed"
                ) from error
            with self._lock:
                baseline = self._samples[0]
            baseline_descendants = tuple(
                member.identity for member in baseline.members[1:]
            )
            response_descendants = tuple(
                member.identity for member in preview.members[1:]
            )
            if baseline_descendants and (
                len(baseline_descendants) != 1
                or baseline_descendants[0].role is not ProcessRole.RESOURCE_TRACKER
            ):
                raise RuntimeError("baseline retained an unsupported descendant")
            if response_descendants:
                if len(response_descendants) != 1:
                    raise RuntimeError("response retained multiple descendants")
                tracker_identity = response_descendants[0]
                if baseline_descendants and baseline_descendants != (tracker_identity,):
                    raise RuntimeError("prewarm resource tracker identity changed")
                tracker, tracker_read_fd, worker_write_fd = (
                    _attest_owned_resource_tracker(
                        tracker_identity,
                        root_pid=self.root_pid,
                    )
                )
                if tracker.status() in {
                    psutil.STATUS_STOPPED,
                    psutil.STATUS_ZOMBIE,
                    psutil.STATUS_DEAD,
                }:
                    raise RuntimeError("resource tracker was not live before freeze")
                stop_sent = False
                resumed = False
                try:
                    os.kill(tracker_identity.pid, signal.SIGSTOP)
                    stop_sent = True
                    _wait_for_process_stopped_state(tracker, stopped=True)
                    (
                        frozen_tracker,
                        frozen_tracker_read_fd,
                        frozen_worker_write_fd,
                    ) = _attest_owned_resource_tracker(
                        tracker_identity,
                        root_pid=self.root_pid,
                    )
                    if (
                        frozen_tracker_read_fd != tracker_read_fd
                        or frozen_worker_write_fd != worker_write_fd
                        or frozen_tracker.status() != psutil.STATUS_STOPPED
                    ):
                        raise RuntimeError(
                            "frozen resource tracker pipe identity differs"
                        )
                    index, frozen = self._sample_locked()
                    frozen_descendants = tuple(
                        member.identity for member in frozen.members[1:]
                    )
                    if frozen_descendants != (tracker_identity,):
                        raise RuntimeError("frozen tracker boundary identity differs")
                    self.response_boundary_snapshot = frozen
                    self.response_boundary_snapshot_index = index
                    self.resource_tracker_freeze_disposition = (
                        "controller-sigstop-snapshot-sigcont-v1"
                    )
                    self.resource_tracker_command_fd = tracker_read_fd
                    self.resource_tracker_worker_write_fd = worker_write_fd
                    self.resource_tracker_stopped_state_verified = True
                finally:
                    if stop_sent:
                        try:
                            os.kill(tracker_identity.pid, signal.SIGCONT)
                        except ProcessLookupError:
                            pass
                        else:
                            _wait_for_process_stopped_state(
                                tracker,
                                stopped=False,
                            )
                            (
                                resumed_tracker,
                                resumed_tracker_read_fd,
                                resumed_worker_write_fd,
                            ) = _attest_owned_resource_tracker(
                                tracker_identity,
                                root_pid=self.root_pid,
                            )
                            if (
                                resumed_tracker_read_fd != tracker_read_fd
                                or resumed_worker_write_fd != worker_write_fd
                                or resumed_tracker.status()
                                in {
                                    psutil.STATUS_STOPPED,
                                    psutil.STATUS_ZOMBIE,
                                    psutil.STATUS_DEAD,
                                }
                            ):
                                raise RuntimeError(
                                    "resource tracker resume identity differs"
                                )
                            resumed = True
                    self.resource_tracker_resumed_state_verified = resumed
                if not resumed:
                    raise RuntimeError("resource tracker was not resumed")
            else:
                if baseline_descendants:
                    raise RuntimeError("prewarm resource tracker disappeared")
                index, boundary = self._sample_locked()
                if len(boundary.members) != 1:
                    raise RuntimeError("root-only response boundary changed")
                self.response_boundary_snapshot = boundary
                self.response_boundary_snapshot_index = index
                self.resource_tracker_freeze_disposition = "not_required_root_only"
        self._boundary_captured = True

    def capture_resource_closure(self) -> None:
        if (
            not self._sampler_pids
            or not self._boundary_captured
            or self._resource_closure_captured
        ):
            raise RuntimeError("external resource closure is out of sequence")
        if self._error is not None:
            raise RuntimeError(
                "external periodic process sampling failed"
            ) from self._error
        self._stop_periodic_process()
        if self._error is not None:
            raise RuntimeError(
                "external periodic process sampling failed"
            ) from self._error
        with self._capture_lock:
            _, closure = self._sample_locked()
            if len(closure.members) != 1:
                raise RuntimeError("resource closure retained a descendant")
            self.resource_closure_snapshot = closure
        self._resource_closure_captured = True

    def finish(
        self,
        *,
        terminal_worker_hwm_bytes: int,
        request_started_monotonic_ns: int,
        request_ended_monotonic_ns: int,
        resource_closure_worker_hwm_bytes: int | None = None,
    ) -> tuple[ProcessTreeSnapshot, ...]:
        if not self._sampler_pids or not self._boundary_captured:
            raise RuntimeError("external response boundary was not captured")
        if resource_closure_worker_hwm_bytes is not None and not (
            self._resource_closure_captured
        ):
            raise RuntimeError("external resource closure was not captured")
        if resource_closure_worker_hwm_bytes is not None and (
            not self._sampler_stopped or not self._resource_closure_captured
        ):
            raise RuntimeError("external resource closure sampler is incomplete")
        if resource_closure_worker_hwm_bytes is None and not self._sampler_stopped:
            self._stop_periodic_process()
        with self._lock:
            captured = list(self._samples)
        if resource_closure_worker_hwm_bytes is None:
            return _request_boundary_snapshots(
                captured,
                request_started_monotonic_ns=request_started_monotonic_ns,
                request_ended_monotonic_ns=request_ended_monotonic_ns,
                terminal_worker_hwm_bytes=terminal_worker_hwm_bytes,
            )
        if self.response_boundary_snapshot_index is None:
            raise RuntimeError("response boundary index is absent")
        retained, shifted_response_index = _lifecycle_boundary_snapshots(
            captured,
            request_started_monotonic_ns=request_started_monotonic_ns,
            request_ended_monotonic_ns=request_ended_monotonic_ns,
            response_boundary_index=self.response_boundary_snapshot_index,
            response_worker_hwm_bytes=terminal_worker_hwm_bytes,
            closure_worker_hwm_bytes=resource_closure_worker_hwm_bytes,
        )
        self.response_boundary_snapshot_index = shifted_response_index
        self.response_boundary_snapshot = retained[shifted_response_index]
        self.resource_closure_snapshot = retained[-1]
        return retained

    def partial(self) -> tuple[ProcessTreeSnapshot, ...]:
        """Freeze and retain bounded samples when no response boundary exists."""

        if not self._sampler_pids:
            raise RuntimeError("external sampler was not started")
        if not self._sampler_stopped:
            try:
                self._stop_periodic_process()
            except BaseException as error:  # noqa: BLE001 - retain partial evidence
                if self._error is None:
                    self._error = error
        with self._lock:
            return tuple(self._samples)


def _request_boundary_snapshots(
    captured: Sequence[ProcessTreeSnapshot],
    *,
    request_started_monotonic_ns: int,
    request_ended_monotonic_ns: int,
    terminal_worker_hwm_bytes: int,
) -> tuple[ProcessTreeSnapshot, ...]:
    """Trim real samples at the first observed post-response boundary."""

    retained_input = tuple(captured)
    if request_ended_monotonic_ns <= request_started_monotonic_ns:
        raise ValueError("request boundary must be positive")
    baseline_indices = [
        index
        for index, snapshot in enumerate(retained_input)
        if snapshot.observed_monotonic_ns <= request_started_monotonic_ns
    ]
    terminal_indices = [
        index
        for index, snapshot in enumerate(retained_input)
        if snapshot.observed_monotonic_ns >= request_ended_monotonic_ns
    ]
    if not baseline_indices or not terminal_indices:
        raise RuntimeError("external sampling missed the request boundary")
    baseline_index = baseline_indices[-1]
    terminal_index = next(
        (index for index in terminal_indices if index > baseline_index),
        None,
    )
    if terminal_index is None:
        raise RuntimeError("external sampling did not retain both boundaries")
    retained = list(retained_input[baseline_index : terminal_index + 1])
    terminal = retained[-1].model_dump(mode="json")
    terminal["members"][0]["self_hwm_bytes"] = max(
        terminal_worker_hwm_bytes,
        terminal["members"][0]["rss_bytes"],
    )
    retained[-1] = ProcessTreeSnapshot.model_validate(terminal)
    return tuple(retained)


def _lifecycle_boundary_snapshots(
    captured: Sequence[ProcessTreeSnapshot],
    *,
    request_started_monotonic_ns: int,
    request_ended_monotonic_ns: int,
    response_boundary_index: int,
    response_worker_hwm_bytes: int,
    closure_worker_hwm_bytes: int,
) -> tuple[tuple[ProcessTreeSnapshot, ...], int]:
    """Retain the request baseline through the final pre-exit root sample."""

    retained_input = tuple(captured)
    if (
        request_ended_monotonic_ns <= request_started_monotonic_ns
        or response_boundary_index <= 0
        or response_boundary_index >= len(retained_input)
        or retained_input[response_boundary_index].observed_monotonic_ns
        < request_ended_monotonic_ns
    ):
        raise RuntimeError("v2 response boundary timeline differs")
    baseline_indices = [
        index
        for index, snapshot in enumerate(retained_input[:response_boundary_index])
        if snapshot.observed_monotonic_ns <= request_started_monotonic_ns
    ]
    if not baseline_indices:
        raise RuntimeError("v2 sampling missed the request baseline")
    baseline_index = baseline_indices[-1]
    retained = list(retained_input[baseline_index:])
    shifted_response_index = response_boundary_index - baseline_index
    if shifted_response_index <= 0 or shifted_response_index >= len(retained):
        raise RuntimeError("v2 shifted response boundary differs")

    response = retained[shifted_response_index].model_dump(mode="json")
    response["members"][0]["self_hwm_bytes"] = max(
        response_worker_hwm_bytes,
        response["members"][0]["rss_bytes"],
    )
    retained[shifted_response_index] = ProcessTreeSnapshot.model_validate(response)
    closure = retained[-1].model_dump(mode="json")
    if len(closure["members"]) != 1:
        raise RuntimeError("v2 final pre-exit boundary retained a descendant")
    closure["members"][0]["self_hwm_bytes"] = max(
        closure_worker_hwm_bytes,
        closure["members"][0]["rss_bytes"],
    )
    retained[-1] = ProcessTreeSnapshot.model_validate(closure)
    return tuple(retained), shifted_response_index


def _worker_startup_deadline(*, clock: Callable[[], float] = time.monotonic) -> float:
    return clock() + WORKER_STARTUP_PREWARM_TIMEOUT_SECONDS


def _worker_request_deadline(
    timeout_seconds: float, *, clock: Callable[[], float] = time.monotonic
) -> float:
    if not 0 < timeout_seconds <= 300.0:
        raise ValueError("request deadline must be in (0, 300] seconds")
    return clock() + timeout_seconds


def _attempt_status_from_exception(error: BaseException) -> AttemptStatus:
    name = type(error).__name__.casefold()
    if "cancel" in name or name in {"keyboardinterrupt", "systemexit"}:
        return AttemptStatus.CANCELLED
    if "timeout" in name:
        return AttemptStatus.TIMEOUT
    return AttemptStatus.ERROR


def _exception_type(error: BaseException) -> str:
    retained = "".join(
        character
        for character in type(error).__name__[:128]
        if character.isalnum() or character in {"_", "."}
    )
    return retained or "Exception"


def _root_only_failure_trace(
    process_tree: ProcessTreeMetrics,
    *,
    status: AttemptStatus,
    error: BaseException,
) -> StageTrace:
    stage_status = StageStatus(status.value)
    return StageTrace(
        schema_id=STAGE_TRACE_SCHEMA_ID,
        status=stage_status,
        authoritative_total_ns=(
            process_tree.request_ended_monotonic_ns
            - process_tree.request_started_monotonic_ns
        ),
        attributed_top_level_union_ns=0,
        unattributed_remainder_ns=(
            process_tree.request_ended_monotonic_ns
            - process_tree.request_started_monotonic_ns
        ),
        spans=(
            StageSpan(
                span_id="request",
                name=StageName.REQUEST_TOTAL,
                parent_span_id=None,
                started_monotonic_ns=process_tree.request_started_monotonic_ns,
                ended_monotonic_ns=process_tree.request_ended_monotonic_ns,
                status=stage_status,
                failure_code=_stage_failure_code(
                    type(error).__name__,
                    fallback="request_failure",
                ),
            ),
        ),
    )


def _touch_exclusive(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    opened = os.fstat(descriptor)
    os.close(descriptor)
    retained = path.lstat()
    if (
        path.is_symlink()
        or not stat_module.S_ISREG(retained.st_mode)
        or stat_module.S_IMODE(retained.st_mode) != 0o600
        or retained.st_uid != os.getuid()
        or retained.st_nlink != 1
        or retained.st_size != 0
        or (retained.st_dev, retained.st_ino) != (opened.st_dev, opened.st_ino)
    ):
        raise RuntimeError("worker protocol marker custody differs")


def _private_empty_marker_exists(path: Path) -> bool:
    try:
        retained = path.lstat()
    except FileNotFoundError:
        return False
    if (
        path.is_symlink()
        or not stat_module.S_ISREG(retained.st_mode)
        or stat_module.S_IMODE(retained.st_mode) != 0o600
        or retained.st_uid != os.getuid()
        or retained.st_nlink != 1
        or retained.st_size != 0
    ):
        raise RuntimeError("worker protocol marker custody differs")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    opened = os.fstat(descriptor)
    os.close(descriptor)
    final_path = path.lstat()
    if (
        (opened.st_dev, opened.st_ino) != (retained.st_dev, retained.st_ino)
        or opened.st_size != 0
        or (final_path.st_dev, final_path.st_ino) != (opened.st_dev, opened.st_ino)
        or final_path.st_size != 0
    ):
        raise RuntimeError("worker protocol marker identity changed")
    return True


def _refresh_heartbeat(path: Path) -> None:
    file_stat = path.lstat()
    if path.is_symlink() or not stat_module.S_ISREG(file_stat.st_mode):
        raise RuntimeError("watchdog heartbeat identity differs")
    os.utime(path, None, follow_symlinks=False)


def _same_process(identity: ProcessIdentity) -> bool:
    try:
        process = psutil.Process(identity.pid)
        return int(process.create_time() * 1_000_000_000) == identity.create_time_ns
    except (psutil.NoSuchProcess, psutil.ZombieProcess, OSError):
        return False


def _terminate_and_reap_owned_worker(
    process: subprocess.Popen[bytes],
    *,
    process_group_id: int,
    observed: Sequence[ProcessIdentity],
) -> None:
    """Terminate only the fresh session created by this controller and reap it."""

    # The session/process-group is the ownership boundary. Signal it even when
    # the leader has already exited: an unsampled forked child may remain in
    # that exact group after a crash.
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=WORKER_CLEANUP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process_group_id, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=WORKER_CLEANUP_GRACE_SECONDS)
        except subprocess.TimeoutExpired as final_error:
            raise RuntimeError(
                "owned benchmark worker could not be reaped"
            ) from final_error

    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        group_survived = False
    else:
        group_survived = True
    if group_survived:
        try:
            os.killpg(process_group_id, signal.SIGKILL)
        except ProcessLookupError:
            group_survived = False
        deadline = time.monotonic() + WORKER_CLEANUP_GRACE_SECONDS
        while group_survived and time.monotonic() < deadline:
            try:
                os.killpg(process_group_id, 0)
            except ProcessLookupError:
                group_survived = False
                break
            time.sleep(0.01)
        if group_survived:
            raise RuntimeError("owned benchmark process group survived cleanup")

    # A child can exit between samples, so this is an observed-identity proof,
    # not a claim that bounded sampling saw every transient process.
    survivors = tuple(identity for identity in observed if _same_process(identity))
    if survivors:
        for identity in survivors:
            try:
                os.kill(identity.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        retained_processes = []
        for identity in survivors:
            if not _same_process(identity):
                continue
            try:
                retained_processes.append(psutil.Process(identity.pid))
            except (psutil.NoSuchProcess, psutil.ZombieProcess, OSError):
                continue
        psutil.wait_procs(retained_processes, timeout=WORKER_CLEANUP_GRACE_SECONDS)
    if any(_same_process(identity) for identity in observed):
        raise RuntimeError("observed benchmark descendants survived cleanup")


def _controller_failure_attempt(
    *,
    slot: AttemptSlot,
    source: SourceIdentity,
    configuration: ConfigurationIdentity,
    candidate_code_sha256: str,
    dependency_lock_sha256: str,
    environment_sha256: str,
    model_artifacts_sha256: str,
    attempt_id: str,
    started_at: datetime,
    completed_at: datetime,
    started_ns: int,
    ended_ns: int,
    status: AttemptStatus,
    failure_type: FailureType,
    failure_code: str,
    partial_snapshots: Sequence[ProcessTreeSnapshot] = (),
    worker_fatal_envelope: WorkerFatalEnvelope | None = None,
) -> LatencyAttempt:
    ended_ns = max(
        ended_ns,
        (
            partial_snapshots[-1].observed_monotonic_ns
            if partial_snapshots
            else started_ns + 1
        ),
        started_ns + 1,
    )
    stage_status = StageStatus(status.value)
    trace = StageTrace(
        schema_id=STAGE_TRACE_SCHEMA_ID,
        status=stage_status,
        authoritative_total_ns=ended_ns - started_ns,
        collector_started_monotonic_ns=None,
        collector_finished_monotonic_ns=None,
        pre_collector_duration_ns=None,
        post_collector_duration_ns=None,
        attributed_top_level_union_ns=0,
        unattributed_remainder_ns=ended_ns - started_ns,
        spans=(
            StageSpan(
                span_id="request",
                name=StageName.REQUEST_TOTAL,
                parent_span_id=None,
                started_monotonic_ns=started_ns,
                ended_monotonic_ns=ended_ns,
                status=stage_status,
                failure_code=failure_code,
            ),
        ),
    )
    partial_process_tree = (
        PartialProcessTreeEvidence(
            schema_id="phase-latency-partial-process-tree-v1",
            request_started_monotonic_ns=started_ns,
            observation_ended_monotonic_ns=max(
                ended_ns,
                partial_snapshots[-1].observed_monotonic_ns,
            ),
            snapshots=tuple(partial_snapshots),
            peak_sampled_total_rss_bytes=max(
                item.total_rss_bytes for item in partial_snapshots
            ),
            measurement_disposition=(
                "incomplete-worker-terminated-before-response-boundary-v1"
            ),
            failure_code=failure_code,
            cleanup_disposition="external_worker_group_reaped",
        )
        if partial_snapshots
        else None
    )
    return LatencyAttempt(
        attempt_id=attempt_id,
        slot_id=slot.slot_id,
        order_index=slot.order_index,
        case_id=slot.case_id,
        pair_index=slot.pair_index,
        system=slot.system,
        source=source,
        source_binding=SourceBinding.WORKSPACE_BYTES,
        configuration=configuration,
        candidate_code_sha256=candidate_code_sha256,
        dependency_lock_sha256=dependency_lock_sha256,
        environment_sha256=environment_sha256,
        model_artifacts_sha256=model_artifacts_sha256,
        status=status,
        started_at_utc=started_at,
        completed_at_utc=completed_at,
        total_latency_ns=trace.authoritative_total_ns,
        cache_hit=False,
        evidence_complete=False,
        output=None,
        failure=FailureRecord(
            code=failure_code,
            stage=StageName.REQUEST_TOTAL,
            exception_type=failure_type,
        ),
        worker_fatal_envelope=worker_fatal_envelope,
        stage_trace=trace,
        process_tree=None,
        partial_process_tree=partial_process_tree,
        provider_total_latency=None,
    )


@dataclass(frozen=True, slots=True)
class _ExternalWorkerRun:
    role: str
    evidence: WorkerExecutionEvidence | None
    snapshots: tuple[ProcessTreeSnapshot, ...]
    status: AttemptStatus
    failure_type: FailureType
    failure_code: str
    started_at: datetime
    completed_at: datetime
    started_ns: int
    ended_ns: int
    watchdog_evidence: WorkerWatchdogEvidence | None
    worker_fatal_envelope: WorkerFatalEnvelope | None = None
    response_boundary_snapshot_index: int | None = None
    resource_tracker_freeze_disposition: str | None = None
    resource_tracker_command_fd: int | None = None
    resource_tracker_worker_write_fd: int | None = None
    resource_tracker_stopped_state_verified: bool | None = None
    resource_tracker_resumed_state_verified: bool | None = None


@dataclass(frozen=True, slots=True)
class _ConcurrentWorkerRegistration:
    attempt_id: str
    case_id: str
    slot_id: str
    pid: int
    create_time_ns: int


@dataclass(frozen=True, slots=True)
class _ConcurrentAggregateObservation:
    sweep_started_monotonic_ns: int
    sweep_ended_monotonic_ns: int
    snapshots: tuple[tuple[str, ProcessTreeSnapshot], ...]


class _ConcurrentRoundObserver:
    """Observe one role-homogeneous worker forest at one shared cadence."""

    _MAXIMUM_SNAPSHOTS = 8_192

    def __init__(
        self,
        *,
        role: str,
        round_index: int,
        barrier_id: str,
        target_interval_ns: int = DEFAULT_SAMPLE_INTERVAL_NS,
    ) -> None:
        if role not in {
            "authoritative_uninstrumented",
            "diagnostic_instrumented",
        }:
            raise ValueError("concurrent observer role differs")
        if round_index not in {1, 2}:
            raise ValueError("concurrent observer round differs")
        if target_interval_ns <= 0:
            raise ValueError("concurrent observer cadence must be positive")
        maximum_expected_samples = (
            MAXIMUM_PROFILE_DURATION_NS + target_interval_ns - 1
        ) // target_interval_ns + 2
        if maximum_expected_samples > self._MAXIMUM_SNAPSHOTS:
            raise ValueError("concurrent observer cadence exceeds its retention bound")
        self.role = role
        self.round_index = round_index
        self.barrier_id = barrier_id
        self.target_interval_ns = target_interval_ns
        self.controller_started_monotonic_ns = time.perf_counter_ns()
        self._registrations: dict[str, _ConcurrentWorkerRegistration] = {}
        self._response_boundaries: set[str] = set()
        self._observations: list[_ConcurrentAggregateObservation] = []
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None
        self._controller_ended_monotonic_ns: int | None = None

    def register(
        self,
        *,
        attempt_id: str,
        slot: AttemptSlot,
        pid: int,
    ) -> None:
        if self._thread is not None:
            raise RuntimeError("concurrent worker registered after observer start")
        if attempt_id in self._registrations:
            raise RuntimeError("concurrent worker registered more than once")
        process = psutil.Process(pid)
        create_time_ns = max(1, int(process.create_time() * 1_000_000_000))
        self._registrations[attempt_id] = _ConcurrentWorkerRegistration(
            attempt_id=attempt_id,
            case_id=slot.case_id,
            slot_id=slot.slot_id,
            pid=pid,
            create_time_ns=create_time_ns,
        )

    def _sample_once(self) -> None:
        with self._condition:
            registrations = tuple(
                sorted(
                    self._registrations.values(),
                    key=lambda item: (item.case_id, item.attempt_id),
                )
            )
        sweep_started_ns = time.perf_counter_ns()
        retained: list[tuple[str, ProcessTreeSnapshot]] = []
        for registration in registrations:
            try:
                snapshot = read_process_tree_snapshot(registration.pid)
            except (psutil.NoSuchProcess, psutil.ZombieProcess, ProcessLookupError):
                continue
            root_identity = snapshot.members[0].identity
            if (
                root_identity.pid != registration.pid
                or root_identity.create_time_ns != registration.create_time_ns
            ):
                raise RuntimeError("concurrent worker identity changed while sampling")
            retained.append((registration.attempt_id, snapshot))
        if not retained:
            return
        sweep_ended_ns = max(
            time.perf_counter_ns(),
            retained[-1][1].observed_monotonic_ns,
            sweep_started_ns + 1,
        )
        if sweep_ended_ns - sweep_started_ns > DEFAULT_HARD_MAXIMUM_GAP_NS:
            raise RuntimeError("concurrent aggregate sweep exceeded its hard bound")
        with self._condition:
            if len(self._observations) >= self._MAXIMUM_SNAPSHOTS:
                raise RuntimeError("concurrent aggregate snapshot bound exceeded")
            if self._observations and sweep_ended_ns <= (
                self._observations[-1].sweep_ended_monotonic_ns
            ):
                raise RuntimeError("concurrent aggregate sampling clock regressed")
            self._observations.append(
                _ConcurrentAggregateObservation(
                    sweep_started_monotonic_ns=sweep_started_ns,
                    sweep_ended_monotonic_ns=sweep_ended_ns,
                    snapshots=tuple(retained),
                )
            )

    def _run(self) -> None:
        interval = self.target_interval_ns / 1_000_000_000
        try:
            self._sample_once()
            while not self._stop.wait(interval):
                self._sample_once()
        except BaseException as error:  # noqa: BLE001 - evidence must fail closed
            self._error = error
            self._stop.set()

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("concurrent aggregate observer is single-use")
        if len(self._registrations) != 2:
            raise RuntimeError("concurrent aggregate observer requires two workers")
        self._thread = threading.Thread(
            target=self._run,
            name=f"phase-latency-concurrent-{self.role}",
            daemon=False,
        )
        self._thread.start()

    def response_boundary(self, attempt_id: str) -> None:
        if attempt_id not in self._registrations:
            raise RuntimeError("unknown concurrent worker reached response boundary")
        with self._condition:
            if attempt_id in self._response_boundaries:
                raise RuntimeError("concurrent response boundary repeated")
            self._response_boundaries.add(attempt_id)
            if len(self._response_boundaries) == len(self._registrations):
                self._stop.set()

    def abort(self) -> None:
        self._stop.set()

    def discard(self) -> None:
        """Stop and join an observer whose coordinated round failed."""

        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            if self._thread.is_alive():
                raise RuntimeError("aborted concurrent aggregate observer did not stop")

    def finish(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            if self._thread.is_alive():
                raise RuntimeError("concurrent aggregate observer did not stop")
        self._controller_ended_monotonic_ns = max(
            time.perf_counter_ns(),
            self.controller_started_monotonic_ns + 1,
        )
        if self._error is not None:
            raise RuntimeError(
                "concurrent aggregate observation failed"
            ) from self._error
        if len(self._registrations) != 2 or len(self._response_boundaries) != 2:
            raise RuntimeError("concurrent aggregate evidence is incomplete")

    def build_evidence(
        self,
        attempts: Sequence[LatencyAttempt],
    ) -> Any:
        """Bind raw forest observations to the accepted attempt intervals."""

        from tests.benchmarks.latency_profile_set import (
            ActiveSlotEvent,
            ConcurrentAggregateSnapshot,
            ConcurrentRoundEvidence,
            ConcurrentWorkerGroupMetric,
            ConcurrentWorkerInterval,
        )

        if self._controller_ended_monotonic_ns is None:
            raise RuntimeError("concurrent observer was not finalized")
        retained_attempts = tuple(attempts)
        if len(retained_attempts) != 2:
            raise ValueError("concurrent evidence requires two accepted attempts")
        diagnostic = self.role == "diagnostic_instrumented"
        trees: dict[str, ProcessTreeMetrics] = {}
        intervals: list[Any] = []
        for attempt in retained_attempts:
            tree = (
                attempt.diagnostic_process_tree if diagnostic else attempt.process_tree
            )
            registration = self._registrations.get(attempt.attempt_id)
            if tree is None or registration is None:
                raise RuntimeError(
                    "concurrent attempt omitted complete process evidence"
                )
            root = tree.snapshots[0].members[0].identity
            if (
                root.pid != registration.pid
                or root.create_time_ns != registration.create_time_ns
            ):
                raise RuntimeError("concurrent process-tree registration differs")
            trees[attempt.attempt_id] = tree
            intervals.append(
                ConcurrentWorkerInterval(
                    case_id=attempt.case_id,
                    attempt_id=attempt.attempt_id,
                    slot_id=attempt.slot_id,
                    worker_group_id=registration.pid,
                    worker_create_time_ns=registration.create_time_ns,
                    request_started_monotonic_ns=tree.request_started_monotonic_ns,
                    request_ended_monotonic_ns=tree.request_ended_monotonic_ns,
                )
            )

        event_rows = sorted(
            (
                timestamp,
                event,
                interval.slot_id,
            )
            for interval in intervals
            for timestamp, event in (
                (interval.request_started_monotonic_ns, "start"),
                (interval.request_ended_monotonic_ns, "end"),
            )
        )
        if any(current[0] <= previous[0] for previous, current in pairwise(event_rows)):
            raise RuntimeError("concurrent request event timestamps are not unique")
        active: set[str] = set()
        ledger: list[Any] = []
        for timestamp, event, slot_id in event_rows:
            if event == "start":
                active.add(slot_id)
            else:
                active.remove(slot_id)
            ledger.append(
                ActiveSlotEvent(
                    observed_monotonic_ns=timestamp,
                    event=event,
                    slot_id=slot_id,
                    active_slot_ids=tuple(sorted(active)),
                )
            )

        interval_by_attempt = {item.attempt_id: item for item in intervals}
        aggregate_snapshots: list[Any] = []
        for observation in self._observations:
            groups: list[Any] = []
            observed_by_attempt = dict(observation.snapshots)
            for attempt in retained_attempts:
                interval = interval_by_attempt[attempt.attempt_id]
                snapshot = observed_by_attempt.get(attempt.attempt_id)
                if snapshot is None or not (
                    interval.request_started_monotonic_ns
                    <= observation.sweep_started_monotonic_ns
                    <= snapshot.observed_monotonic_ns
                    <= observation.sweep_ended_monotonic_ns
                    <= interval.request_ended_monotonic_ns
                ):
                    continue
                groups.append(
                    ConcurrentWorkerGroupMetric(
                        case_id=attempt.case_id,
                        attempt_id=attempt.attempt_id,
                        slot_id=attempt.slot_id,
                        worker_group_id=interval.worker_group_id,
                        worker_create_time_ns=interval.worker_create_time_ns,
                        sampled_monotonic_ns=snapshot.observed_monotonic_ns,
                        rss_bytes=snapshot.total_rss_bytes,
                        cumulative_cpu_ns=(
                            snapshot.total_user_cpu_ns + snapshot.total_system_cpu_ns
                        ),
                    )
                )
            if groups:
                aggregate_snapshots.append(
                    ConcurrentAggregateSnapshot(
                        aggregation_basis=(
                            "bounded-skew-sequential-process-tree-sweep-v1"
                        ),
                        sweep_started_monotonic_ns=(
                            observation.sweep_started_monotonic_ns
                        ),
                        sweep_ended_monotonic_ns=(observation.sweep_ended_monotonic_ns),
                        observed_monotonic_ns=observation.sweep_ended_monotonic_ns,
                        groups=tuple(groups),
                        aggregate_rss_bytes=sum(item.rss_bytes for item in groups),
                        aggregate_cpu_ns=sum(item.cumulative_cpu_ns for item in groups),
                    )
                )
        synchronized = tuple(
            item for item in aggregate_snapshots if len(item.groups) == 2
        )
        if not synchronized:
            raise RuntimeError("concurrent observer retained no overlapping sample")
        overlap_start = max(item.request_started_monotonic_ns for item in intervals)
        overlap_end = min(item.request_ended_monotonic_ns for item in intervals)
        synchronized_times = tuple(item.observed_monotonic_ns for item in synchronized)
        cadence_gaps = (
            synchronized_times[0] - overlap_start,
            *(current - previous for previous, current in pairwise(synchronized_times)),
            overlap_end - synchronized_times[-1],
        )
        if any(gap < 0 for gap in cadence_gaps):
            raise RuntimeError("concurrent sample escaped the overlap interval")
        exact_cpu = sum(
            tree.exact_worker_self_cpu_ns
            + tree.exact_reaped_children_cpu_ns
            + tree.conservative_frozen_response_boundary_descendant_cpu_ns
            for tree in trees.values()
        )
        conservative_cpu = sum(
            max(
                tree.maximum_observed_process_cpu_ns,
                tree.exact_worker_self_cpu_ns
                + tree.exact_reaped_children_cpu_ns
                + tree.conservative_frozen_response_boundary_descendant_cpu_ns,
            )
            for tree in trees.values()
        )
        if any(
            not tree.worker_reaped or not tree.observed_descendants_reaped
            for tree in trees.values()
        ):
            raise RuntimeError("concurrent worker groups were not fully reaped")
        return ConcurrentRoundEvidence(
            role=self.role,
            round_index=self.round_index,
            barrier_id=self.barrier_id,
            controller_started_monotonic_ns=self.controller_started_monotonic_ns,
            controller_ended_monotonic_ns=self._controller_ended_monotonic_ns,
            worker_intervals=tuple(intervals),
            active_slot_ledger=tuple(ledger),
            maximum_occupancy=2,
            overlap_ns=overlap_end - overlap_start,
            worker_group_count=2,
            bounded_skew_snapshots=tuple(aggregate_snapshots),
            sampling_interval_target_ns=DEFAULT_SAMPLE_INTERVAL_NS,
            hard_maximum_gap_ns=DEFAULT_HARD_MAXIMUM_GAP_NS,
            maximum_observed_gap_ns=max(cadence_gaps),
            peak_bounded_skew_aggregate_rss_bytes=max(
                item.aggregate_rss_bytes for item in synchronized
            ),
            exact_aggregate_cpu_ns=exact_cpu,
            conservative_aggregate_cpu_ns=conservative_cpu,
            all_groups_reaped=True,
        )


class _ConcurrentReleaseGate:
    """Small reusable-free barrier that permits watchdog heartbeats while waiting."""

    def __init__(
        self,
        parties: int,
        *,
        observer: _ConcurrentRoundObserver | None = None,
    ) -> None:
        self._parties = parties
        self._arrived = 0
        self._aborted = False
        self._condition = threading.Condition()
        self._observer = observer

    def register(
        self,
        *,
        attempt_id: str,
        slot: AttemptSlot,
        pid: int,
    ) -> None:
        if self._observer is not None:
            self._observer.register(
                attempt_id=attempt_id,
                slot=slot,
                pid=pid,
            )

    def response_boundary(self, attempt_id: str) -> None:
        if self._observer is not None:
            self._observer.response_boundary(attempt_id)

    def abort(self) -> None:
        if self._observer is not None:
            self._observer.abort()
        with self._condition:
            self._aborted = True
            self._condition.notify_all()

    def await_release(self, refresh: Callable[[], None]) -> None:
        deadline = time.monotonic() + WORKER_STARTUP_PREWARM_TIMEOUT_SECONDS
        with self._condition:
            if self._aborted:
                raise RuntimeError("concurrent release gate was aborted")
            self._arrived += 1
            if self._arrived > self._parties:
                raise RuntimeError("concurrent release gate exceeded its bound")
            if self._arrived == self._parties:
                if self._observer is not None:
                    self._observer.start()
                self._condition.notify_all()
                return
            while self._arrived < self._parties:
                if self._aborted:
                    raise RuntimeError("concurrent release gate was aborted")
                refresh()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("concurrent release gate timed out")
                self._condition.wait(timeout=min(0.2, remaining))


def _run_one_external_worker(
    *,
    role: str,
    source: SourceIdentity,
    source_path: Path,
    output_format: str,
    request_profile: str,
    timeout_seconds: float,
    root: Path,
    synthetic_fixture_mode: str | None,
    bounded_concurrency: int,
    expected_execution_identity: tuple[str, str, str, str],
    release_barrier: _ConcurrentReleaseGate | None = None,
    coordination_attempt_id: str | None = None,
    coordination_slot: AttemptSlot | None = None,
) -> _ExternalWorkerRun:
    if (coordination_attempt_id is None) != (coordination_slot is None):
        raise ValueError("concurrent worker coordination identity is incomplete")
    if release_barrier is not None and coordination_attempt_id is None:
        raise ValueError("concurrent worker requires a coordination identity")
    started_at = datetime.now(UTC)
    fallback_started_ns = time.perf_counter_ns()
    with tempfile.TemporaryDirectory(prefix="plt-", dir="/tmp") as directory:
        protocol = Path(directory).resolve(strict=True)
        protocol_stat = protocol.lstat()
        if (
            protocol.is_symlink()
            or not stat_module.S_ISDIR(protocol_stat.st_mode)
            or stat_module.S_IMODE(protocol_stat.st_mode) != 0o700
            or protocol_stat.st_uid != os.getuid()
        ):
            raise RuntimeError("worker protocol root custody differs")
        child_guard_root = materialize_private_child_network_guard(root, protocol)
        ready = protocol / "ready"
        go = protocol / "go"
        result_path = protocol / "result.json"
        fatal_envelope_path = protocol / "fatal.json"
        done = protocol / "done"
        ack = protocol / "ack"
        response_boundary = protocol / "response-boundary"
        response_boundary_ack = protocol / "response-boundary-ack"
        resource_closure = protocol / "resource-closure"
        resource_closure_ack = protocol / "resource-closure-ack"
        heartbeat = protocol / "controller-heartbeat"
        watchdog_ready = protocol / "watchdog-ready"
        unix_proxy_probe = protocol / "network-proxy-probe.sock"
        unix_proxy_listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        unix_proxy_listener.bind(str(unix_proxy_probe))
        os.chmod(unix_proxy_probe, 0o600)
        unix_proxy_listener.listen(1)
        unix_proxy_listener.setblocking(False)
        unix_probe_stat = unix_proxy_probe.lstat()
        try:
            validate_owned_unix_probe(
                unix_proxy_probe,
                expected_dev=unix_probe_stat.st_dev,
                expected_ino=unix_probe_stat.st_ino,
            )
        except RuntimeError:
            unix_proxy_listener.close()
            raise
        unix_proxy_listener_fd = unix_proxy_listener.fileno()
        _touch_exclusive(heartbeat)
        sandbox_size_bytes, sandbox_sha256 = os_network_sandbox_identity()
        worker_environment = controlled_worker_environment(
            root,
            os.environ,
            child_guard_root=child_guard_root,
        )
        worker_environment["PYTHONPYCACHEPREFIX"] = str(protocol / "pycache")
        worker_environment["PHASE_LATENCY_NETWORK_DENIAL_MARKER"] = str(
            protocol / "network-denied"
        )
        expected_worker_environment_sha256 = worker_environment_sha256(
            worker_environment
        )
        normalized_environment_sha256 = normalized_worker_environment_sha256(
            worker_environment,
            workspace=root,
            protocol_root=protocol,
        )
        worker_command = (
            sys.executable,
            "-m",
            "tests.benchmarks.latency_worker",
            "--workspace",
            str(root),
            "--source",
            str(source_path.resolve()),
            "--source-sha256",
            source.sha256,
            "--source-size",
            str(source.size_bytes),
            "--source-page-count",
            str(source.page_count),
            "--candidate-code-sha256",
            expected_execution_identity[0],
            "--dependency-lock-sha256",
            expected_execution_identity[1],
            "--environment-sha256",
            expected_execution_identity[2],
            "--model-artifacts-sha256",
            expected_execution_identity[3],
            "--case-id",
            source.case_id,
            "--output-format",
            output_format,
            "--measurement-role",
            role,
            "--request-profile",
            request_profile,
            "--bounded-concurrency",
            str(bounded_concurrency),
            "--ready",
            str(ready),
            "--go",
            str(go),
            "--result",
            str(result_path),
            "--fatal-envelope",
            str(fatal_envelope_path),
            "--done",
            str(done),
            "--ack",
            str(ack),
            "--response-boundary",
            str(response_boundary),
            "--response-boundary-ack",
            str(response_boundary_ack),
            "--resource-closure",
            str(resource_closure),
            "--resource-closure-ack",
            str(resource_closure_ack),
            "--os-sandbox-size",
            str(sandbox_size_bytes),
            "--os-sandbox-sha256",
            sandbox_sha256,
            "--os-sandbox-profile-size",
            str(OS_NETWORK_SANDBOX_PROFILE_SIZE_BYTES),
            "--os-sandbox-profile-sha256",
            OS_NETWORK_SANDBOX_PROFILE_SHA256,
            "--os-sandbox-unix-probe",
            str(unix_proxy_probe),
            "--child-guard-root",
            str(child_guard_root),
            "--worker-environment-sha256",
            expected_worker_environment_sha256,
            "--normalized-worker-environment-sha256",
            normalized_environment_sha256,
            "--pycache-prefix",
            str(protocol / "pycache"),
        )
        if request_profile == "request_prewarmed_after_app_startup":
            control_name = (
                "clean-energy.pdf"
                if source.filename == "insurance-acord.pdf"
                else "insurance-acord.pdf"
            )
            prewarm_path = root / "benchmark-expertmodeldata" / control_name
            prewarm = derive_source_identity(
                prewarm_path,
                case_id=f"prewarm-{control_name.removesuffix('.pdf')}",
                workspace=root,
            )
            worker_command = (
                *worker_command,
                "--prewarm-source",
                str(prewarm_path),
                "--prewarm-source-sha256",
                prewarm.sha256,
                "--prewarm-source-size",
                str(prewarm.size_bytes),
                "--prewarm-source-page-count",
                str(prewarm.page_count),
                "--prewarm-case-id",
                prewarm.case_id,
            )
        if synthetic_fixture_mode is not None:
            worker_command = (
                *worker_command,
                "--fixture-mode",
                synthetic_fixture_mode,
            )
        command = sandboxed_worker_command(worker_command)
        process = subprocess.Popen(
            command,
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=worker_environment,
        )
        try:
            from tests.benchmarks.latency_watchdog import (
                MAXIMUM_EVIDENCE_BYTES as MAXIMUM_WATCHDOG_EVIDENCE_BYTES,
            )
            from tests.benchmarks.latency_watchdog import (
                build_watchdog_command,
                sanitized_watchdog_environment,
            )

            controller_process = psutil.Process(os.getpid())
            worker_process = psutil.Process(process.pid)
            watchdog_command = build_watchdog_command(
                python_executable=sys.executable,
                controller_pid=os.getpid(),
                controller_create_time_ns=int(
                    controller_process.create_time() * 1_000_000_000
                ),
                worker_pid=process.pid,
                worker_create_time_ns=int(worker_process.create_time() * 1_000_000_000),
                worker_pgid=process.pid,
                heartbeat_root=protocol.resolve(),
                heartbeat_path=heartbeat.resolve(),
                ready_path=watchdog_ready.resolve(),
            )
            watchdog = subprocess.Popen(
                watchdog_command,
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=sanitized_watchdog_environment(),
            )
        except BaseException:
            _terminate_and_reap_owned_worker(
                process,
                process_group_id=process.pid,
                observed=(),
            )
            raise
        last_heartbeat_refresh = time.monotonic()

        def refresh_heartbeat_if_due() -> None:
            nonlocal last_heartbeat_refresh
            now = time.monotonic()
            if now - last_heartbeat_refresh >= 0.25:
                _refresh_heartbeat(heartbeat)
                last_heartbeat_refresh = now

        sampler: ExternalProcessTreeSampler | None = None
        snapshots: tuple[ProcessTreeSnapshot, ...] = ()
        evidence: WorkerExecutionEvidence | None = None
        failure_status = AttemptStatus.ERROR
        failure_type = FailureType.WORKER_PROTOCOL_ERROR
        failure_code = "worker_protocol_error"
        request_started_ns = fallback_started_ns
        request_ended_ns = fallback_started_ns + 1
        observed: tuple[ProcessIdentity, ...] = ()
        watchdog_evidence: WorkerWatchdogEvidence | None = None
        worker_fatal_envelope: WorkerFatalEnvelope | None = None
        worker_exit_classified = False
        barrier_released = False
        response_boundary_notified = False
        resource_closure_captured = False
        resource_closure_deadline: float | None = None
        startup_deadline = _worker_startup_deadline()

        def classify_worker_exit(default_failure_code: str) -> None:
            nonlocal failure_type, failure_code
            nonlocal worker_fatal_envelope, worker_exit_classified

            if worker_exit_classified:
                return
            returncode = process.poll()
            if returncode is None:
                raise RuntimeError("live worker cannot be exit-classified")
            worker_exit_classified = True
            try:
                fatal_envelope_path.lstat()
            except FileNotFoundError:
                fatal_path_present = False
            else:
                fatal_path_present = True
            if returncode == WORKER_FATAL_EXIT_CODE:
                try:
                    worker_fatal_envelope = _read_worker_fatal_envelope(
                        fatal_envelope_path
                    )
                except BaseException:  # noqa: BLE001 - malformed fatal evidence closes
                    worker_fatal_envelope = None
                    failure_type = FailureType.WORKER_PROTOCOL_ERROR
                    failure_code = "worker_fatal_envelope_invalid"
                else:
                    failure_type = FailureType.WORKER_CRASH
                    failure_code = default_failure_code
                return
            if returncode == WORKER_FATAL_ENVELOPE_WRITE_FAILED_EXIT_CODE:
                worker_fatal_envelope = None
                failure_type = FailureType.WORKER_PROTOCOL_ERROR
                failure_code = "worker_fatal_envelope_write_failed"
                return
            if fatal_path_present:
                worker_fatal_envelope = None
                failure_type = FailureType.WORKER_PROTOCOL_ERROR
                failure_code = "worker_fatal_envelope_invalid"
                return
            failure_type = (
                FailureType.WORKER_SIGNAL
                if returncode < 0
                else FailureType.WORKER_CRASH
            )
            failure_code = default_failure_code

        try:
            while not watchdog_ready.exists():
                refresh_heartbeat_if_due()
                if watchdog.poll() is not None:
                    raise RuntimeError("worker watchdog exited before binding")
                if time.monotonic() >= startup_deadline:
                    raise TimeoutError("worker watchdog binding timed out")
                time.sleep(0.01)
            ready_stat = watchdog_ready.lstat()
            if (
                watchdog_ready.is_symlink()
                or not stat_module.S_ISREG(ready_stat.st_mode)
                or stat_module.S_IMODE(ready_stat.st_mode) != 0o600
                or ready_stat.st_uid != os.getuid()
                or bounded_read_bytes(
                    watchdog_ready,
                    maximum_bytes=16,
                )
                != b"READY\n"
            ):
                raise RuntimeError("worker watchdog ready evidence differs")
            while not _private_empty_marker_exists(ready):
                refresh_heartbeat_if_due()
                if process.poll() is not None:
                    classify_worker_exit("worker_exited_before_ready")
                    break
                if time.monotonic() >= startup_deadline:
                    failure_status = AttemptStatus.TIMEOUT
                    failure_type = FailureType.WORKER_TIMEOUT
                    failure_code = "worker_startup_or_prewarm_timeout"
                    break
                time.sleep(0.01)
            if _private_empty_marker_exists(ready):
                validate_owned_unix_probe(
                    unix_proxy_probe,
                    expected_dev=unix_probe_stat.st_dev,
                    expected_ino=unix_probe_stat.st_ino,
                )
                try:
                    accepted, _ = unix_proxy_listener.accept()
                except BlockingIOError:
                    pass
                else:
                    accepted.close()
                    raise RuntimeError("OS sandbox allowed a Unix proxy connection")
                unix_proxy_listener.close()
                try:
                    os.fstat(unix_proxy_listener_fd)
                except OSError:
                    pass
                else:
                    raise RuntimeError("OS sandbox probe listener FD remained open")
                validate_owned_unix_probe(
                    unix_proxy_probe,
                    expected_dev=unix_probe_stat.st_dev,
                    expected_ino=unix_probe_stat.st_ino,
                )
                unix_proxy_probe.unlink()
                if unix_proxy_probe.exists():
                    raise RuntimeError("OS sandbox Unix proxy survived unlink")
                sampler = ExternalProcessTreeSampler(
                    process.pid,
                    allow_synthetic_root_only=(synthetic_fixture_mode is not None),
                )
                sampler.start()
                if release_barrier is not None:
                    assert coordination_attempt_id is not None
                    assert coordination_slot is not None
                    release_barrier.register(
                        attempt_id=coordination_attempt_id,
                        slot=coordination_slot,
                        pid=process.pid,
                    )
                    release_barrier.await_release(refresh_heartbeat_if_due)
                    barrier_released = True
                request_started_ns = time.perf_counter_ns()
                _touch_exclusive(go)
                request_deadline = _worker_request_deadline(timeout_seconds)
                boundary_captured = False
                while not _private_empty_marker_exists(done):
                    refresh_heartbeat_if_due()
                    if (
                        _private_empty_marker_exists(response_boundary)
                        and not boundary_captured
                    ):
                        sampler.capture_response_boundary()
                        if release_barrier is not None:
                            assert coordination_attempt_id is not None
                            release_barrier.response_boundary(coordination_attempt_id)
                            response_boundary_notified = True
                        _touch_exclusive(response_boundary_ack)
                        boundary_captured = True
                        resource_closure_deadline = (
                            time.monotonic() + WORKER_RESOURCE_CLOSURE_TIMEOUT_SECONDS
                        )
                    if (
                        _private_empty_marker_exists(resource_closure)
                        and not resource_closure_captured
                    ):
                        if not boundary_captured:
                            raise RuntimeError(
                                "resource closure preceded the response boundary"
                            )
                        sampler.capture_resource_closure()
                        _touch_exclusive(resource_closure_ack)
                        resource_closure_captured = True
                    if process.poll() is not None:
                        classify_worker_exit("worker_exited_during_request")
                        break
                    if not boundary_captured and time.monotonic() >= request_deadline:
                        failure_status = AttemptStatus.TIMEOUT
                        failure_type = FailureType.WORKER_TIMEOUT
                        failure_code = "worker_hard_timeout"
                        break
                    if (
                        boundary_captured
                        and not resource_closure_captured
                        and resource_closure_deadline is not None
                        and time.monotonic() >= resource_closure_deadline
                    ):
                        failure_status = AttemptStatus.TIMEOUT
                        failure_type = FailureType.WORKER_TIMEOUT
                        failure_code = "worker_resource_closure_timeout"
                        break
                    time.sleep(0.01)
                request_ended_ns = max(time.perf_counter_ns(), request_started_ns + 1)
                if _private_empty_marker_exists(done):
                    if not boundary_captured:
                        raise RuntimeError(
                            "worker completed without response-boundary handshake"
                        )
                    if not resource_closure_captured:
                        raise RuntimeError(
                            "worker completed without resource-closure handshake"
                        )
                    evidence = WorkerExecutionEvidence.model_validate_json(
                        bounded_read_bytes(
                            result_path,
                            maximum_bytes=MAXIMUM_EVIDENCE_BYTES,
                        )
                    )
                    if evidence.measurement_role != role:
                        raise ValueError("worker measurement role differs")
                    if evidence.exact_supplied_environment_sha256 != (
                        expected_worker_environment_sha256
                    ) or evidence.network_isolation.worker_environment_sha256 != (
                        normalized_environment_sha256
                    ):
                        raise ValueError("worker environment evidence differs")
                    request_started_ns = evidence.request_started_monotonic_ns
                    request_ended_ns = evidence.request_ended_monotonic_ns
                    snapshots = sampler.finish(
                        terminal_worker_hwm_bytes=(
                            evidence.worker_hwm_bytes_at_response_boundary
                        ),
                        request_started_monotonic_ns=request_started_ns,
                        request_ended_monotonic_ns=request_ended_ns,
                        resource_closure_worker_hwm_bytes=(
                            evidence.worker_hwm_bytes_at_resource_closure
                        ),
                    )
                    pre_ack_snapshot = read_process_tree_snapshot(process.pid)
                    if (
                        len(pre_ack_snapshot.members) != 1
                        or pre_ack_snapshot.members[0].identity
                        != snapshots[0].members[0].identity
                    ):
                        raise RuntimeError("pre-ack worker tree retained a descendant")
                    _touch_exclusive(ack)
                    exit_deadline = time.monotonic() + WORKER_CLEANUP_GRACE_SECONDS
                    while process.poll() is None and time.monotonic() < exit_deadline:
                        refresh_heartbeat_if_due()
                        time.sleep(0.01)
                    if process.poll() is None:
                        failure_type = FailureType.WORKER_PROTOCOL_ERROR
                        failure_code = "worker_ack_exit_timeout"
                        evidence = None
                    elif process.returncode != 0:
                        classify_worker_exit("worker_nonzero_after_final_ack")
                        evidence = None
                    else:
                        try:
                            fatal_envelope_path.lstat()
                        except FileNotFoundError:
                            pass
                        else:
                            raise RuntimeError(
                                "zero-exit worker retained a fatal envelope"
                            )
                        try:
                            os.killpg(process.pid, 0)
                        except ProcessLookupError:
                            pass
                        else:
                            raise RuntimeError(
                                "worker process group survived zero exit"
                            )
                        denial_marker_present = _private_empty_marker_exists(
                            protocol / "network-denied"
                        )
                        if denial_marker_present != bool(
                            evidence.network_isolation.denied_network_attempt_count
                        ):
                            raise RuntimeError(
                                "controller network-denial marker proof differs"
                            )
                        if os_network_sandbox_identity() != (
                            sandbox_size_bytes,
                            sandbox_sha256,
                        ) or private_child_network_guard_identity(child_guard_root) != (
                            CHILD_NETWORK_GUARD_SIZE_BYTES,
                            CHILD_NETWORK_GUARD_SHA256,
                        ):
                            raise RuntimeError(
                                "worker isolation identity changed during execution"
                            )
                        evidence_payload = evidence.model_dump(mode="json")
                        evidence_payload["network_isolation"][
                            "python_guard_restore_disposition"
                        ] = "controller-verified-worker-zero-exit"
                        evidence_payload["resource_tracker_disposition"][
                            "controller_no_relaunch_through_zero_exit_verified"
                        ] = True
                        evidence = WorkerExecutionEvidence.model_validate(
                            evidence_payload
                        )
                observed = tuple(
                    member.identity
                    for snapshot in snapshots
                    for member in snapshot.members
                )
        except KeyboardInterrupt:
            failure_status = AttemptStatus.CANCELLED
            failure_type = FailureType.WORKER_CANCELLED
            failure_code = "worker_cancelled"
        except BaseException:  # noqa: BLE001 - closed evidence error
            failure_status = AttemptStatus.ERROR
            failure_type = FailureType.EVIDENCE_ERROR
            failure_code = "worker_evidence_error"
            evidence = None
            observed = tuple(
                member.identity for snapshot in snapshots for member in snapshot.members
            )
        finally:
            unix_proxy_listener.close()
            if unix_proxy_probe.exists():
                unix_proxy_probe.unlink()
            if release_barrier is not None and (
                not barrier_released or not response_boundary_notified
            ):
                release_barrier.abort()
            if sampler is not None and not snapshots:
                try:
                    snapshots = sampler.partial()
                except BaseException:  # noqa: BLE001 - cleanup remains fail-closed
                    snapshots = ()
            observed_by_process = {
                (item.pid, item.create_time_ns): item for item in observed
            }
            for snapshot in snapshots:
                for member in snapshot.members:
                    identity = member.identity
                    observed_by_process[(identity.pid, identity.create_time_ns)] = (
                        identity
                    )
            observed = tuple(
                observed_by_process[key] for key in sorted(observed_by_process)
            )
            if evidence is None:
                request_ended_ns = max(
                    time.perf_counter_ns(),
                    (
                        snapshots[-1].observed_monotonic_ns
                        if snapshots
                        else request_started_ns + 1
                    ),
                    request_started_ns + 1,
                )
            _terminate_and_reap_owned_worker(
                process,
                process_group_id=process.pid,
                observed=observed,
            )
            _refresh_heartbeat(heartbeat)
            try:
                watchdog_output, _ = watchdog.communicate(timeout=3.0)
            except subprocess.TimeoutExpired:
                watchdog.kill()
                watchdog_output, _ = watchdog.communicate(timeout=1.0)
            if (
                watchdog.returncode == 0
                and len(watchdog_output) <= MAXIMUM_WATCHDOG_EVIDENCE_BYTES
            ):
                try:
                    watchdog_evidence = WorkerWatchdogEvidence.model_validate_json(
                        watchdog_output
                    )
                except BaseException:  # noqa: BLE001 - watchdog evidence fails closed
                    watchdog_evidence = None
            if watchdog_evidence is None and evidence is not None:
                evidence = None
                failure_status = AttemptStatus.ERROR
                failure_type = FailureType.WORKER_PROTOCOL_ERROR
                failure_code = "worker_protocol_error"
        return _ExternalWorkerRun(
            role=role,
            evidence=evidence,
            snapshots=snapshots,
            status=failure_status if evidence is None else evidence.status,
            failure_type=failure_type,
            failure_code=failure_code,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            started_ns=request_started_ns,
            ended_ns=request_ended_ns,
            watchdog_evidence=watchdog_evidence,
            worker_fatal_envelope=worker_fatal_envelope,
            response_boundary_snapshot_index=(
                sampler.response_boundary_snapshot_index
                if sampler is not None and evidence is not None
                else None
            ),
            resource_tracker_freeze_disposition=(
                sampler.resource_tracker_freeze_disposition
                if sampler is not None and evidence is not None
                else None
            ),
            resource_tracker_command_fd=(
                sampler.resource_tracker_command_fd
                if sampler is not None and evidence is not None
                else None
            ),
            resource_tracker_worker_write_fd=(
                sampler.resource_tracker_worker_write_fd
                if sampler is not None and evidence is not None
                else None
            ),
            resource_tracker_stopped_state_verified=(
                sampler.resource_tracker_stopped_state_verified
                if sampler is not None and evidence is not None
                else None
            ),
            resource_tracker_resumed_state_verified=(
                sampler.resource_tracker_resumed_state_verified
                if sampler is not None and evidence is not None
                else None
            ),
        )


def run_external_candidate_attempt(
    *,
    slot: AttemptSlot,
    source_path: Path,
    attempt_id: str,
    output_format: str = "json",
    timeout_seconds: float = 300.0,
    workspace: Path | None = None,
    synthetic_fixture_mode: str | None = None,
    request_profile: str = "request_cold_after_app_startup",
    bounded_concurrency: int = 1,
    _precomputed_runs: Mapping[str, _ExternalWorkerRun] | None = None,
    _precomputed_started_at: datetime | None = None,
    _role_observer: Callable[[AttemptSlot, str, _ExternalWorkerRun], None]
    | None = None,
) -> LatencyAttempt:
    """Run an uninstrumented comparator and a separate diagnostic twin."""

    if slot.system is not SystemName.CANDIDATE:
        raise ValueError("external local profiler can execute candidate slots only")
    if not 0 < timeout_seconds <= 300.0:
        raise ValueError("external worker deadline must be in (0, 300] seconds")
    if synthetic_fixture_mode is not None and (
        synthetic_fixture_mode
        not in {
            "mock-testclient",
            "mock-error",
            "mock-hang",
            "mock-crash",
            "mock-fatal",
        }
        or not slot.case_id.startswith("synthetic-")
        or not attempt_id.startswith("synthetic-")
        or output_format != "markdown"
    ):
        raise ValueError("synthetic external worker is restricted to harness controls")
    if request_profile not in {
        "request_cold_after_app_startup",
        "request_prewarmed_after_app_startup",
    }:
        raise ValueError("candidate request profile differs")
    if (
        isinstance(bounded_concurrency, bool)
        or not isinstance(bounded_concurrency, int)
        or not 1 <= bounded_concurrency <= 4
    ):
        raise ValueError("candidate concurrency must be an integer in [1, 4]")
    root = (workspace or Path.cwd()).resolve()
    source = derive_source_identity(
        source_path,
        case_id=slot.case_id,
        workspace=root,
    )
    from app.config import get_settings

    lifecycle = (
        WorkerLifecycle.FRESH_PROCESS_REQUEST_COLD
        if request_profile == "request_cold_after_app_startup"
        else WorkerLifecycle.FRESH_PROCESS_REQUEST_PREWARMED
    )
    controller_configuration = derive_candidate_configuration(
        settings=get_settings(),
        source_suffix=source_path.suffix,
        output_format=output_format,
        workspace=root,
        worker_lifecycle=lifecycle,
        synthetic_minimal=(synthetic_fixture_mode is not None),
        bounded_concurrency=bounded_concurrency,
    )
    controller_execution_identity = (
        derive_candidate_code_sha256(root),
        derive_dependency_lock_sha256(root),
        derive_environment_sha256(),
        derive_model_artifacts_sha256(root),
    )
    if (
        controller_configuration.runtime_sha256 != controller_execution_identity[2]
        or controller_configuration.model_artifacts_sha256
        != controller_execution_identity[3]
    ):
        raise RuntimeError("controller configuration execution identity differs")
    controller_started_at = _precomputed_started_at or datetime.now(UTC)
    if _precomputed_runs is None:
        order = (
            ("authoritative_uninstrumented", "diagnostic_instrumented")
            if slot.pair_index % 2
            else ("diagnostic_instrumented", "authoritative_uninstrumented")
        )
        runs = {}
        for role in order:
            run = _run_one_external_worker(
                role=role,
                source=source,
                source_path=source_path,
                output_format=output_format,
                request_profile=request_profile,
                timeout_seconds=timeout_seconds,
                root=root,
                synthetic_fixture_mode=synthetic_fixture_mode,
                bounded_concurrency=bounded_concurrency,
                expected_execution_identity=controller_execution_identity,
            )
            runs[role] = run
            if _role_observer is not None:
                _role_observer(slot, attempt_id, run)
    else:
        if set(_precomputed_runs) != {
            "authoritative_uninstrumented",
            "diagnostic_instrumented",
        } or any(run.role != role for role, run in _precomputed_runs.items()):
            raise ValueError("precomputed worker role inventory differs")
        order = ("authoritative_uninstrumented", "diagnostic_instrumented")
        runs = dict(_precomputed_runs)
    authoritative = runs["authoritative_uninstrumented"]
    diagnostic = runs["diagnostic_instrumented"]
    completed_at = datetime.now(UTC)
    post_execution_identity = (
        derive_candidate_code_sha256(root),
        derive_dependency_lock_sha256(root),
        derive_environment_sha256(),
        derive_model_artifacts_sha256(root),
    )
    if post_execution_identity != controller_execution_identity:
        return _controller_failure_attempt(
            slot=slot,
            source=source,
            configuration=controller_configuration,
            candidate_code_sha256=controller_execution_identity[0],
            dependency_lock_sha256=controller_execution_identity[1],
            environment_sha256=controller_execution_identity[2],
            model_artifacts_sha256=controller_execution_identity[3],
            attempt_id=attempt_id,
            started_at=controller_started_at,
            completed_at=completed_at,
            started_ns=authoritative.started_ns,
            ended_ns=authoritative.ended_ns,
            status=AttemptStatus.ERROR,
            failure_type=FailureType.EVIDENCE_ERROR,
            failure_code="controller_execution_identity_drift",
        )
    missing = authoritative if authoritative.evidence is None else diagnostic
    if missing.evidence is None:
        return _controller_failure_attempt(
            slot=slot,
            source=source,
            configuration=controller_configuration,
            candidate_code_sha256=controller_execution_identity[0],
            dependency_lock_sha256=controller_execution_identity[1],
            environment_sha256=controller_execution_identity[2],
            model_artifacts_sha256=controller_execution_identity[3],
            attempt_id=attempt_id,
            started_at=controller_started_at,
            completed_at=completed_at,
            started_ns=missing.started_ns,
            ended_ns=missing.ended_ns,
            status=missing.status,
            failure_type=missing.failure_type,
            failure_code=missing.failure_code,
            partial_snapshots=missing.snapshots,
            worker_fatal_envelope=missing.worker_fatal_envelope,
        )

    authoritative_evidence = authoritative.evidence
    diagnostic_evidence = diagnostic.evidence
    expected_identities = (
        source,
        *controller_execution_identity,
        derive_environment_manifest(),
        controller_configuration,
    )
    for evidence in (authoritative_evidence, diagnostic_evidence):
        observed_identities = (
            evidence.source,
            evidence.candidate_code_sha256,
            evidence.dependency_lock_sha256,
            evidence.environment_sha256,
            evidence.model_artifacts_sha256,
            evidence.environment_manifest,
            evidence.configuration,
        )
        if observed_identities != expected_identities:
            return _controller_failure_attempt(
                slot=slot,
                source=source,
                configuration=controller_configuration,
                candidate_code_sha256=controller_execution_identity[0],
                dependency_lock_sha256=controller_execution_identity[1],
                environment_sha256=controller_execution_identity[2],
                model_artifacts_sha256=controller_execution_identity[3],
                attempt_id=attempt_id,
                started_at=controller_started_at,
                completed_at=completed_at,
                started_ns=authoritative_evidence.request_started_monotonic_ns,
                ended_ns=authoritative_evidence.request_ended_monotonic_ns,
                status=AttemptStatus.ERROR,
                failure_type=FailureType.EVIDENCE_ERROR,
                failure_code="worker_identity_mismatch",
            )
    try:
        process_tree = assemble_process_tree_metrics(
            authoritative.snapshots,
            request_started_monotonic_ns=(
                authoritative_evidence.request_started_monotonic_ns
            ),
            request_ended_monotonic_ns=(
                authoritative_evidence.request_ended_monotonic_ns
            ),
            sampling_interval_target_ns=DEFAULT_SAMPLE_INTERVAL_NS,
            hard_maximum_gap_ns=DEFAULT_HARD_MAXIMUM_GAP_NS,
            cleanup_disposition="external_worker_reaped",
            worker_reaped=True,
            worker_hwm_measurement_basis="worker_reported_ru_maxrss",
            descendant_observation_basis=(
                "synthetic_worker_declared_no_children"
                if synthetic_fixture_mode is not None
                else "recursive_psutil"
            ),
            exact_worker_self_cpu_ns=(
                int(
                    authoritative_evidence.resource_boundary.response_boundary_worker_self_user_cpu_delta_ns
                    or 0
                )
                + int(
                    authoritative_evidence.resource_boundary.response_boundary_worker_self_system_cpu_delta_ns
                    or 0
                )
            ),
            exact_reaped_children_cpu_ns=(
                int(
                    authoritative_evidence.resource_boundary.response_boundary_reaped_children_user_cpu_delta_ns
                    or 0
                )
                + int(
                    authoritative_evidence.resource_boundary.response_boundary_reaped_children_system_cpu_delta_ns
                    or 0
                )
            ),
            reaped_children_hwm_bytes=(
                authoritative_evidence.resource_boundary.reaped_children_process_lifetime_hwm_bytes
            ),
            resource_boundary_basis=authoritative_evidence.resource_boundary.basis,
            resource_boundary_complete=(len(authoritative.snapshots[-1].members) == 1),
            response_boundary_snapshot_index=(
                authoritative.response_boundary_snapshot_index
            ),
            resource_tracker_freeze_disposition=(
                authoritative.resource_tracker_freeze_disposition
            ),
            resource_tracker_command_fd=authoritative.resource_tracker_command_fd,
            resource_tracker_worker_write_fd=(
                authoritative.resource_tracker_worker_write_fd
            ),
            resource_tracker_stopped_state_verified=(
                authoritative.resource_tracker_stopped_state_verified
            ),
            resource_tracker_resumed_state_verified=(
                authoritative.resource_tracker_resumed_state_verified
            ),
            worker_reported_hwm_bytes_at_response_boundary=(
                authoritative_evidence.worker_hwm_bytes_at_response_boundary
            ),
            lifecycle_exact_worker_self_cpu_ns=(
                authoritative_evidence.resource_boundary.worker_self_user_cpu_delta_ns
                + authoritative_evidence.resource_boundary.worker_self_system_cpu_delta_ns
            ),
            lifecycle_reaped_children_cpu_ns=(
                authoritative_evidence.resource_boundary.reaped_children_user_cpu_delta_ns
                + authoritative_evidence.resource_boundary.reaped_children_system_cpu_delta_ns
            ),
        )
        diagnostic_process_tree = assemble_process_tree_metrics(
            diagnostic.snapshots,
            request_started_monotonic_ns=(
                diagnostic_evidence.request_started_monotonic_ns
            ),
            request_ended_monotonic_ns=(diagnostic_evidence.request_ended_monotonic_ns),
            sampling_interval_target_ns=DEFAULT_SAMPLE_INTERVAL_NS,
            hard_maximum_gap_ns=DEFAULT_HARD_MAXIMUM_GAP_NS,
            cleanup_disposition="external_worker_reaped",
            worker_reaped=True,
            worker_hwm_measurement_basis="worker_reported_ru_maxrss",
            descendant_observation_basis=(
                "synthetic_worker_declared_no_children"
                if synthetic_fixture_mode is not None
                else "recursive_psutil"
            ),
            exact_worker_self_cpu_ns=(
                int(
                    diagnostic_evidence.resource_boundary.response_boundary_worker_self_user_cpu_delta_ns
                    or 0
                )
                + int(
                    diagnostic_evidence.resource_boundary.response_boundary_worker_self_system_cpu_delta_ns
                    or 0
                )
            ),
            exact_reaped_children_cpu_ns=(
                int(
                    diagnostic_evidence.resource_boundary.response_boundary_reaped_children_user_cpu_delta_ns
                    or 0
                )
                + int(
                    diagnostic_evidence.resource_boundary.response_boundary_reaped_children_system_cpu_delta_ns
                    or 0
                )
            ),
            reaped_children_hwm_bytes=(
                diagnostic_evidence.resource_boundary.reaped_children_process_lifetime_hwm_bytes
            ),
            resource_boundary_basis=diagnostic_evidence.resource_boundary.basis,
            resource_boundary_complete=(len(diagnostic.snapshots[-1].members) == 1),
            response_boundary_snapshot_index=(
                diagnostic.response_boundary_snapshot_index
            ),
            resource_tracker_freeze_disposition=(
                diagnostic.resource_tracker_freeze_disposition
            ),
            resource_tracker_command_fd=diagnostic.resource_tracker_command_fd,
            resource_tracker_worker_write_fd=(
                diagnostic.resource_tracker_worker_write_fd
            ),
            resource_tracker_stopped_state_verified=(
                diagnostic.resource_tracker_stopped_state_verified
            ),
            resource_tracker_resumed_state_verified=(
                diagnostic.resource_tracker_resumed_state_verified
            ),
            worker_reported_hwm_bytes_at_response_boundary=(
                diagnostic_evidence.worker_hwm_bytes_at_response_boundary
            ),
            lifecycle_exact_worker_self_cpu_ns=(
                diagnostic_evidence.resource_boundary.worker_self_user_cpu_delta_ns
                + diagnostic_evidence.resource_boundary.worker_self_system_cpu_delta_ns
            ),
            lifecycle_reaped_children_cpu_ns=(
                diagnostic_evidence.resource_boundary.reaped_children_user_cpu_delta_ns
                + diagnostic_evidence.resource_boundary.reaped_children_system_cpu_delta_ns
            ),
        )
        authoritative_total_ns = (
            authoritative_evidence.request_ended_monotonic_ns
            - authoritative_evidence.request_started_monotonic_ns
        )
        diagnostic_total_ns = (
            diagnostic_evidence.request_ended_monotonic_ns
            - diagnostic_evidence.request_started_monotonic_ns
        )
        twin_order = (
            "authoritative_then_diagnostic"
            if order[0] == "authoritative_uninstrumented"
            else "diagnostic_then_authoritative"
        )
        if authoritative_evidence.status is not diagnostic_evidence.status:
            raise ValueError("worker twin outcome status differs")
        if authoritative_evidence.http_status != diagnostic_evidence.http_status:
            raise ValueError("worker twin HTTP status differs")
        if authoritative_evidence.status is not AttemptStatus.SUCCESS:
            if (
                authoritative_evidence.failure is None
                or diagnostic_evidence.failure is None
                or authoritative_evidence.failure.exception_type
                is not diagnostic_evidence.failure.exception_type
                or authoritative_evidence.failure.code
                != diagnostic_evidence.failure.code
            ):
                raise ValueError("worker twin failure classification differs")
            return LatencyAttempt(
                attempt_id=attempt_id,
                slot_id=slot.slot_id,
                order_index=slot.order_index,
                case_id=slot.case_id,
                pair_index=slot.pair_index,
                system=slot.system,
                source=source,
                source_binding=SourceBinding.WORKSPACE_BYTES,
                configuration=controller_configuration,
                candidate_code_sha256=controller_execution_identity[0],
                dependency_lock_sha256=controller_execution_identity[1],
                environment_sha256=controller_execution_identity[2],
                model_artifacts_sha256=controller_execution_identity[3],
                status=authoritative_evidence.status,
                started_at_utc=authoritative_evidence.started_at_utc,
                completed_at_utc=authoritative_evidence.completed_at_utc,
                total_latency_ns=authoritative_total_ns,
                cache_hit=False,
                evidence_complete=(
                    authoritative_evidence.evidence_complete
                    and diagnostic_evidence.evidence_complete
                ),
                output=None,
                failure=authoritative_evidence.failure,
                diagnostic_failure=diagnostic_evidence.failure,
                failure_stage_parity_policy=(
                    "authoritative-root-versus-diagnostic-first-failed-stage-v1"
                ),
                error_response=authoritative_evidence.error_response,
                stage_trace=diagnostic_evidence.stage_trace,
                process_tree=process_tree,
                diagnostic_process_tree=diagnostic_process_tree,
                diagnostic_total_latency_ns=diagnostic_total_ns,
                diagnostic_output=None,
                diagnostic_error_response=diagnostic_evidence.error_response,
                twin_order=twin_order,
                observer_delta_ns=diagnostic_total_ns - authoritative_total_ns,
                observer_adjustment_applied=False,
                instrumentation_manifest=(diagnostic_evidence.instrumentation_manifest),
                authoritative_cache_state=authoritative_evidence.cache_state,
                diagnostic_cache_state=diagnostic_evidence.cache_state,
                authoritative_network_isolation=(
                    authoritative_evidence.network_isolation
                ),
                diagnostic_network_isolation=diagnostic_evidence.network_isolation,
                authoritative_post_response_validation_duration_ns=(
                    authoritative_evidence.post_response_validation_duration_ns
                ),
                diagnostic_post_response_validation_duration_ns=(
                    diagnostic_evidence.post_response_validation_duration_ns
                ),
                authoritative_response_boundary_protocol=(
                    authoritative_evidence.response_boundary_protocol
                ),
                diagnostic_response_boundary_protocol=(
                    diagnostic_evidence.response_boundary_protocol
                ),
                authoritative_watchdog=authoritative.watchdog_evidence,
                diagnostic_watchdog=diagnostic.watchdog_evidence,
                authoritative_resource_tracker_disposition=(
                    authoritative_evidence.resource_tracker_disposition
                ),
                diagnostic_resource_tracker_disposition=(
                    diagnostic_evidence.resource_tracker_disposition
                ),
                provider_total_latency=None,
            )
        return LatencyAttempt(
            attempt_id=attempt_id,
            slot_id=slot.slot_id,
            order_index=slot.order_index,
            case_id=slot.case_id,
            pair_index=slot.pair_index,
            system=slot.system,
            source=source,
            source_binding=SourceBinding.WORKSPACE_BYTES,
            configuration=controller_configuration,
            candidate_code_sha256=controller_execution_identity[0],
            dependency_lock_sha256=controller_execution_identity[1],
            environment_sha256=controller_execution_identity[2],
            model_artifacts_sha256=controller_execution_identity[3],
            status=AttemptStatus.SUCCESS,
            started_at_utc=authoritative_evidence.started_at_utc,
            completed_at_utc=authoritative_evidence.completed_at_utc,
            total_latency_ns=authoritative_total_ns,
            cache_hit=False,
            evidence_complete=True,
            output=authoritative_evidence.output,
            failure=None,
            error_response=None,
            stage_trace=diagnostic_evidence.stage_trace,
            process_tree=process_tree,
            diagnostic_process_tree=diagnostic_process_tree,
            diagnostic_total_latency_ns=diagnostic_total_ns,
            diagnostic_output=diagnostic_evidence.output,
            diagnostic_error_response=None,
            twin_order=twin_order,
            observer_delta_ns=diagnostic_total_ns - authoritative_total_ns,
            observer_adjustment_applied=False,
            instrumentation_manifest=diagnostic_evidence.instrumentation_manifest,
            authoritative_cache_state=authoritative_evidence.cache_state,
            diagnostic_cache_state=diagnostic_evidence.cache_state,
            authoritative_network_isolation=(authoritative_evidence.network_isolation),
            diagnostic_network_isolation=diagnostic_evidence.network_isolation,
            authoritative_post_response_validation_duration_ns=(
                authoritative_evidence.post_response_validation_duration_ns
            ),
            diagnostic_post_response_validation_duration_ns=(
                diagnostic_evidence.post_response_validation_duration_ns
            ),
            authoritative_response_boundary_protocol=(
                authoritative_evidence.response_boundary_protocol
            ),
            diagnostic_response_boundary_protocol=(
                diagnostic_evidence.response_boundary_protocol
            ),
            authoritative_watchdog=authoritative.watchdog_evidence,
            diagnostic_watchdog=diagnostic.watchdog_evidence,
            authoritative_resource_tracker_disposition=(
                authoritative_evidence.resource_tracker_disposition
            ),
            diagnostic_resource_tracker_disposition=(
                diagnostic_evidence.resource_tracker_disposition
            ),
            provider_total_latency=None,
        )
    except BaseException:  # noqa: BLE001 - retain rejected twin in denominator
        return _controller_failure_attempt(
            slot=slot,
            source=source,
            configuration=controller_configuration,
            candidate_code_sha256=controller_execution_identity[0],
            dependency_lock_sha256=controller_execution_identity[1],
            environment_sha256=controller_execution_identity[2],
            model_artifacts_sha256=controller_execution_identity[3],
            attempt_id=attempt_id,
            started_at=controller_started_at,
            completed_at=completed_at,
            started_ns=authoritative_evidence.request_started_monotonic_ns,
            ended_ns=authoritative_evidence.request_ended_monotonic_ns,
            status=AttemptStatus.ERROR,
            failure_type=FailureType.EVIDENCE_ERROR,
            failure_code="worker_evidence_rejected",
        )


@dataclass(frozen=True, slots=True)
class ExternalCandidateJob:
    slot: AttemptSlot
    source_path: Path
    attempt_id: str


def run_bounded_concurrent_candidate_attempts(
    *,
    jobs: Sequence[ExternalCandidateJob],
    bounded_concurrency: int,
    output_format: str = "json",
    timeout_seconds: float = 300.0,
    workspace: Path | None = None,
    synthetic_fixture_mode: str | None = None,
    request_profile: str = "request_cold_after_app_startup",
    _round_observers: list[_ConcurrentRoundObserver] | None = None,
    _round_observer_errors: list[BaseException] | None = None,
    _role_observer: Callable[[AttemptSlot, str, _ExternalWorkerRun], None]
    | None = None,
) -> tuple[LatencyAttempt, ...]:
    """Run role-homogeneous synchronized worker rounds under one process bound."""

    retained = tuple(jobs)
    if (
        isinstance(bounded_concurrency, bool)
        or not isinstance(bounded_concurrency, int)
        or not 2 <= bounded_concurrency <= 4
    ):
        raise ValueError("concurrent profile bound must be an integer in [2, 4]")
    if not bounded_concurrency <= len(retained) <= 16:
        raise ValueError("concurrent profile job count is outside its bound")
    if len({job.attempt_id for job in retained}) != len(retained):
        raise ValueError("concurrent profile attempt IDs must be unique")
    if len({job.slot.slot_id for job in retained}) != len(retained):
        raise ValueError("concurrent profile slots must be unique")

    root = (workspace or Path.cwd()).resolve()
    execution_identity = (
        derive_candidate_code_sha256(root),
        derive_dependency_lock_sha256(root),
        derive_environment_sha256(),
        derive_model_artifacts_sha256(root),
    )
    sources = {
        job.attempt_id: derive_source_identity(
            job.source_path,
            case_id=job.slot.case_id,
            workspace=root,
        )
        for job in retained
    }
    controller_started = {job.attempt_id: datetime.now(UTC) for job in retained}

    def run_role(role: str) -> dict[str, _ExternalWorkerRun]:
        completed: dict[str, _ExternalWorkerRun] = {}
        for offset in range(0, len(retained), bounded_concurrency):
            batch = retained[offset : offset + bounded_concurrency]
            observer: _ConcurrentRoundObserver | None = None
            if _round_observers is not None:
                if len(retained) != 2 or len(batch) != 2 or offset != 0:
                    raise ValueError(
                        "retained concurrent-round evidence requires exactly two jobs"
                    )
                diagnostic = role == "diagnostic_instrumented"
                observer = _ConcurrentRoundObserver(
                    role=role,
                    round_index=2 if diagnostic else 1,
                    barrier_id=(
                        "lat-us01-bound2-diagnostic-barrier"
                        if diagnostic
                        else "lat-us01-bound2-authoritative-barrier"
                    ),
                )
            gate = _ConcurrentReleaseGate(len(batch), observer=observer)

            def execute(
                job: ExternalCandidateJob,
                round_gate: _ConcurrentReleaseGate = gate,
            ) -> _ExternalWorkerRun:
                try:
                    run = _run_one_external_worker(
                        role=role,
                        source=sources[job.attempt_id],
                        source_path=job.source_path,
                        output_format=output_format,
                        request_profile=request_profile,
                        timeout_seconds=timeout_seconds,
                        root=root,
                        synthetic_fixture_mode=synthetic_fixture_mode,
                        bounded_concurrency=bounded_concurrency,
                        expected_execution_identity=execution_identity,
                        release_barrier=round_gate,
                        coordination_attempt_id=job.attempt_id,
                        coordination_slot=job.slot,
                    )
                    if _role_observer is not None:
                        _role_observer(job.slot, job.attempt_id, run)
                    return run
                except BaseException:
                    round_gate.abort()
                    raise

            try:
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=len(batch),
                    thread_name_prefix=f"phase-latency-{role}-round",
                ) as executor:
                    futures = tuple(executor.submit(execute, job) for job in batch)
                    runs = tuple(future.result() for future in futures)
                if observer is not None:
                    try:
                        observer.finish()
                    except BaseException as error:
                        observer.discard()
                        if _round_observer_errors is None:
                            raise
                        _round_observer_errors.append(error)
                    else:
                        _round_observers.append(observer)
            except BaseException:
                gate.abort()
                if observer is not None:
                    observer.discard()
                raise
            completed.update(
                (job.attempt_id, run) for job, run in zip(batch, runs, strict=True)
            )
        return completed

    authoritative_runs = run_role("authoritative_uninstrumented")
    diagnostic_runs = run_role("diagnostic_instrumented")
    results = tuple(
        run_external_candidate_attempt(
            slot=job.slot,
            source_path=job.source_path,
            attempt_id=job.attempt_id,
            output_format=output_format,
            timeout_seconds=timeout_seconds,
            workspace=root,
            synthetic_fixture_mode=synthetic_fixture_mode,
            request_profile=request_profile,
            bounded_concurrency=bounded_concurrency,
            _precomputed_runs={
                "authoritative_uninstrumented": authoritative_runs[job.attempt_id],
                "diagnostic_instrumented": diagnostic_runs[job.attempt_id],
            },
            _precomputed_started_at=controller_started[job.attempt_id],
        )
        for job in retained
    )
    if any(
        attempt.configuration.bounded_concurrency != bounded_concurrency
        for attempt in results
    ):
        raise RuntimeError("concurrent profile configuration binding differs")
    return results


def run_synchronized_concurrent_candidate_profile(
    *,
    jobs: Sequence[ExternalCandidateJob],
    timeout_seconds: float = 300.0,
    workspace: Path | None = None,
    _role_observer: Callable[[AttemptSlot, str, _ExternalWorkerRun], None]
    | None = None,
    _attempt_observer: Callable[[LatencyAttempt], None] | None = None,
) -> Any:
    """Run and retain the exact two-case LAT-US01 concurrent profile."""

    from tests.benchmarks.latency_profile_set import (
        CONCURRENT_CASE_ORDER,
        ConcurrentBatchEvidence,
    )

    retained = tuple(jobs)
    if len(retained) != 2 or tuple(job.slot.case_id for job in retained) != (
        CONCURRENT_CASE_ORDER
    ):
        raise ValueError("concurrent profile requires the frozen NY/Uber case order")
    controller = psutil.Process(os.getpid())
    thread_count_before = int(controller.num_threads())
    fd_count_before = _fd_count(controller)
    observers: list[_ConcurrentRoundObserver] = []
    observer_errors: list[BaseException] = []
    attempts = run_bounded_concurrent_candidate_attempts(
        jobs=retained,
        bounded_concurrency=2,
        output_format="json",
        timeout_seconds=timeout_seconds,
        workspace=workspace,
        request_profile="request_cold_after_app_startup",
        _round_observers=observers,
        _round_observer_errors=observer_errors,
        _role_observer=_role_observer,
    )
    if _attempt_observer is not None:
        for attempt in attempts:
            _attempt_observer(attempt)
    thread_count_after = int(controller.num_threads())
    fd_count_after = _fd_count(controller)
    if observer_errors:
        raise BaseExceptionGroup(
            "concurrent aggregate evidence failed after attempt retention",
            observer_errors,
        )
    if len(observers) != 2:
        raise RuntimeError("concurrent profile omitted a role-homogeneous round")
    return ConcurrentBatchEvidence(
        schema_id="phase-latency-concurrent-batch-v1",
        batch_id="lat-us01-ny-uber-bound2-cold-json",
        bounded_concurrency=2,
        ordered_attempts=attempts,
        authoritative_round=observers[0].build_evidence(attempts),
        diagnostic_round=observers[1].build_evidence(attempts),
        controller_thread_count_before=thread_count_before,
        controller_thread_count_after=thread_count_after,
        controller_fd_count_before=fd_count_before,
        controller_fd_count_after=fd_count_after,
        hosted_calls=0,
        hosted_credits=0,
        prompt_tokens=0,
        completion_tokens=0,
        billed_cost_microusd=0,
        egress_bytes=0,
    )


def _workspace_artifact_identity(
    workspace: Path,
    relative: str,
    *,
    maximum_bytes: int,
) -> Any:
    from tests.benchmarks.latency_contracts import ArtifactIdentity

    data = bounded_read_bytes(
        _resolve_workspace_path(workspace, Path(relative)),
        maximum_bytes=maximum_bytes,
    )
    return ArtifactIdentity(
        path=relative,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def derive_candidate_profile_execution_identity(
    workspace: Path | None = None,
) -> Any:
    """Derive the complete profile identity from current on-disk bytes."""

    from tests.benchmarks.latency_profile_set import (
        HARNESS_PATHS,
        CandidateExecutionIdentity,
    )
    from tests.fixtures.phase_03.running_regions.oracle import SOURCE_IDENTITIES

    root = (workspace or Path.cwd()).resolve()
    artifacts = {
        path: _workspace_artifact_identity(
            root,
            path,
            maximum_bytes=(16 * 1024 * 1024 if path == "uv.lock" else 8 * 1024 * 1024),
        )
        for path in (
            "pyproject.toml",
            "uv.lock",
            "tracker/phase-00-baseline/evidence/P00-US04-corpus-registry.json",
            "tests/fixtures/phase_03/running_regions/oracle.py",
            "tracker/benchmarks/llamaparse-15/runs/baseline-20260728-current/run-metadata.json",
            "tracker/phase-00-baseline/evidence/p00-us10-corpus-20260729-03/run-record.json",
            "tracker/phase-00-baseline/evidence/p00-us10-corpus-20260729-03/semantic-report.json",
            "tracker/phase-00-baseline/evidence/lat-us01-current-runtime-baseline-20260809-r01/run-record.json",
            "tracker/phase-00-baseline/evidence/lat-us01-current-runtime-baseline-20260809-r01/semantic-report.json",
            "tracker/phase-00-baseline/evidence/lat-us01-current-runtime-baseline-20260809-r01/semantic-report.md",
        )
    }
    harness_files = tuple(
        _workspace_artifact_identity(root, path, maximum_bytes=8 * 1024 * 1024)
        for path in HARNESS_PATHS
    )
    source_registry_sha256 = _canonical_hash(SOURCE_IDENTITIES)
    return CandidateExecutionIdentity(
        candidate_code_sha256=derive_candidate_code_sha256(root),
        pyproject=artifacts["pyproject.toml"],
        dependency_lock=artifacts["uv.lock"],
        dependency_manifest_sha256=derive_dependency_lock_sha256(root),
        environment_manifest=derive_environment_manifest(),
        environment_comparable=False,
        model_artifacts_sha256=derive_model_artifacts_sha256(root),
        corpus_registry=artifacts[
            "tracker/phase-00-baseline/evidence/P00-US04-corpus-registry.json"
        ],
        phase03_oracle=artifacts["tests/fixtures/phase_03/running_regions/oracle.py"],
        m0_resource_record=artifacts[
            "tracker/benchmarks/llamaparse-15/runs/baseline-20260728-current/run-metadata.json"
        ],
        p00_run_record=artifacts[
            "tracker/phase-00-baseline/evidence/p00-us10-corpus-20260729-03/run-record.json"
        ],
        p00_semantic_report=artifacts[
            "tracker/phase-00-baseline/evidence/p00-us10-corpus-20260729-03/semantic-report.json"
        ],
        current_runtime_run_record=artifacts[
            "tracker/phase-00-baseline/evidence/lat-us01-current-runtime-baseline-20260809-r01/run-record.json"
        ],
        current_runtime_semantic_report=artifacts[
            "tracker/phase-00-baseline/evidence/lat-us01-current-runtime-baseline-20260809-r01/semantic-report.json"
        ],
        current_runtime_semantic_report_markdown=artifacts[
            "tracker/phase-00-baseline/evidence/lat-us01-current-runtime-baseline-20260809-r01/semantic-report.md"
        ],
        harness_files=harness_files,
        source_registry_sha256=source_registry_sha256,
    )


def verify_candidate_profile_set_custody(
    profile_set: Any,
    *,
    workspace: Path | None = None,
    ledger_path: Path | None = None,
) -> None:
    """Independently recompute every profile identity from retained bytes."""

    from tests.benchmarks.latency_instrumentation import (
        verify_instrumentation_manifest,
    )
    from tests.benchmarks.latency_profile_set import (
        CASE_ORDER,
        CandidateProfileSet,
    )
    from tests.fixtures.phase_03.running_regions.oracle import SOURCE_IDENTITIES

    if not isinstance(profile_set, CandidateProfileSet):
        raise TypeError("profile custody requires a validated CandidateProfileSet")
    root = (workspace or Path.cwd()).resolve()
    expected_identity = derive_candidate_profile_execution_identity(root)
    if profile_set.identity != expected_identity:
        raise ValueError("candidate profile execution identity differs from disk")
    if ledger_path is None:
        raise ValueError("candidate profile custody requires its retained ledger")
    resolved_ledger = _resolve_workspace_path(root, ledger_path)
    ledger_stat = resolved_ledger.lstat()
    if (
        resolved_ledger.is_symlink()
        or not stat_module.S_ISREG(ledger_stat.st_mode)
        or stat_module.S_IMODE(ledger_stat.st_mode) != 0o600
        or ledger_stat.st_uid != os.getuid()
        or ledger_stat.st_nlink != 1
    ):
        raise ValueError("candidate profile ledger custody differs")
    retained_ledger_bytes = bounded_read_bytes(
        resolved_ledger,
        maximum_bytes=MAXIMUM_PROFILE_SET_BYTES,
    )
    retained_ledger = type(profile_set.attempt_ledger).model_validate_json(
        retained_ledger_bytes
    )
    if (
        canonical_model_bytes(retained_ledger) != retained_ledger_bytes
        or retained_ledger != profile_set.attempt_ledger
    ):
        raise ValueError("candidate profile retained ledger differs")
    if tuple(SOURCE_IDENTITIES) != CASE_ORDER or (
        _canonical_hash(SOURCE_IDENTITIES)
        != profile_set.identity.source_registry_sha256
    ):
        raise ValueError("candidate profile source registry differs")

    expected_worker_environment_sha256 = (
        expected_identity.environment_manifest.sanitized_worker_environment_sha256
    )

    def verify_profile_source(source: SourceIdentity) -> None:
        registered = SOURCE_IDENTITIES.get(source.case_id)
        if registered is None:
            raise ValueError("candidate profile source is outside the registry")
        actual = derive_source_identity(
            root / registered["path"],
            case_id=source.case_id,
            workspace=root,
        )
        if actual != source:
            raise ValueError("candidate profile historical source bytes differ")

    def verify_profile_network(isolation: NetworkIsolationEvidence | None) -> None:
        if isolation is not None:
            if isolation.policy != (
                "sanitized-offline-env-python-deny-and-os-process-tree-deny-v2"
            ):
                raise ValueError("candidate profile retained non-v2 network isolation")
            _verify_v2_network_artifact_custody(
                isolation,
                workspace=root,
                expected_worker_environment_sha256=(expected_worker_environment_sha256),
            )

    for observation in retained_ledger.role_observations:
        worker = observation.worker_evidence
        if worker is None:
            continue
        verify_profile_source(worker.source)
        verify_profile_network(worker.network_isolation)
        if worker.instrumentation_manifest is not None:
            verify_instrumentation_manifest(
                worker.instrumentation_manifest,
                workspace=root,
            )
    for observation in retained_ledger.attempt_observations:
        attempt = observation.attempt
        verify_profile_source(attempt.source)
        verify_profile_network(attempt.authoritative_network_isolation)
        verify_profile_network(attempt.diagnostic_network_isolation)
        if attempt.instrumentation_manifest is not None:
            verify_instrumentation_manifest(
                attempt.instrumentation_manifest,
                workspace=root,
            )

    for case in profile_set.cases:
        source = derive_source_identity(
            root / case.source.path,
            case_id=case.case_id,
            workspace=root,
        )
        registered = SOURCE_IDENTITIES[case.case_id]
        if source != case.source or source.model_dump(mode="json") != {
            "case_id": case.case_id,
            "path": registered["path"],
            "filename": Path(registered["path"]).name,
            "sha256": registered["sha256"],
            "size_bytes": registered["size_bytes"],
            "page_count": registered["page_count"],
        }:
            raise ValueError("candidate profile source bytes differ from registry")
    attempts = (
        tuple(
            attempt
            for case in profile_set.cases
            for attempt in (case.cold_json, case.prewarmed_json, case.cold_markdown)
        )
        + profile_set.concurrent_batch.ordered_attempts
    )
    for attempt in attempts:
        registered = SOURCE_IDENTITIES[attempt.case_id]
        actual_source = derive_source_identity(
            root / registered["path"],
            case_id=attempt.case_id,
            workspace=root,
        )
        if attempt.source != actual_source:
            raise ValueError("candidate attempt source bytes differ from registry")
        if attempt.instrumentation_manifest is None:
            if (
                attempt.status is AttemptStatus.SUCCESS
                or attempt.evidence_complete is not False
            ):
                raise ValueError("candidate profile omitted diagnostic harness custody")
            continue
        verify_instrumentation_manifest(
            attempt.instrumentation_manifest,
            workspace=root,
        )


class _IncompleteCandidateProfileRun(RuntimeError):
    """Content-free signal that the retained ledger cannot emit a profile."""


def run_all_15_candidate_profile(
    *,
    ledger_output: Path,
    timeout_seconds: float = 300.0,
    workspace: Path | None = None,
) -> Any:
    """Execute 47 fixed slots with an atomic checkpoint before every next step."""

    from tests.benchmarks.latency_profile_set import (
        CANDIDATE_PROFILE_SLOT_PLAN,
        CURRENT_RUNTIME_OUTPUT_IDENTITIES,
        M0_CASE_HWM_BYTES,
        P00_OUTPUT_IDENTITIES,
        CandidateProfileCase,
        CandidateProfileSet,
        P00QualityEvidence,
        append_attempt_observation,
        append_controller_failure,
        append_role_observation,
        attempt_output_matches_current_runtime,
        finalize_ledger,
        initial_candidate_profile_attempt_ledger,
        next_candidate_profile_execution_id,
    )

    if not 0 < timeout_seconds <= 300.0:
        raise ValueError("all-15 profile timeout must be in (0, 300] seconds")
    root = (workspace or Path.cwd()).resolve()
    identity = derive_candidate_profile_execution_identity(root)
    ledger_path = _new_workspace_output_path(str(ledger_output), workspace=root)
    store = _CandidateProfileLedgerStore(
        path=ledger_path,
        initial_ledger=initial_candidate_profile_attempt_ledger(identity),
        workspace=root,
    )
    checkpoint_lock = threading.Lock()
    current_slot: AttemptSlot | None = None
    current_execution_id: str | None = None

    def checkpoint(transform: Callable[[Any], Any]) -> Any:
        with checkpoint_lock:
            return store.checkpoint(transform(store.ledger))

    def retain_role(
        slot: AttemptSlot,
        execution_id: str,
        run: _ExternalWorkerRun,
    ) -> None:
        evidence = run.evidence
        status = evidence.status if evidence is not None else run.status
        failure = (
            evidence.failure
            if evidence is not None
            else FailureRecord(
                code=run.failure_code,
                stage=StageName.REQUEST_TOTAL,
                exception_type=run.failure_type,
            )
        )
        checkpoint(
            lambda ledger: append_role_observation(
                ledger,
                execution_id=execution_id,
                slot_id=slot.slot_id,
                role=run.role,
                status=status,
                failure=failure,
                started_at_utc=(
                    evidence.started_at_utc if evidence is not None else run.started_at
                ),
                completed_at_utc=(
                    evidence.completed_at_utc
                    if evidence is not None
                    else run.completed_at
                ),
                started_monotonic_ns=(
                    evidence.request_started_monotonic_ns
                    if evidence is not None
                    else run.started_ns
                ),
                ended_monotonic_ns=(
                    evidence.request_ended_monotonic_ns
                    if evidence is not None
                    else run.ended_ns
                ),
                worker_evidence=evidence,
                snapshots=run.snapshots,
                watchdog=run.watchdog_evidence,
                worker_fatal_envelope=run.worker_fatal_envelope,
            )
        )

    def retain_attempt(attempt: LatencyAttempt) -> None:
        checkpoint(lambda ledger: append_attempt_observation(ledger, attempt))

    def close_ledger(ledger: Any) -> Any:
        return finalize_ledger(
            ledger,
            finalized_at_utc=datetime.now(UTC),
            finalized_monotonic_ns=time.perf_counter_ns(),
        )

    def execute_slot(slot_spec: Any) -> LatencyAttempt:
        nonlocal current_slot, current_execution_id
        current_slot = AttemptSlot(
            slot_id=slot_spec.slot_id,
            order_index=slot_spec.order_index,
            case_id=slot_spec.case_id,
            pair_index=1,
            system=SystemName.CANDIDATE,
        )
        current_execution_id = next_candidate_profile_execution_id(
            store.ledger,
            current_slot.slot_id,
        )
        request_profile = (
            "request_prewarmed_after_app_startup"
            if slot_spec.profile == "prewarmed-json"
            else "request_cold_after_app_startup"
        )
        attempt = run_external_candidate_attempt(
            slot=current_slot,
            source_path=(
                root / "benchmark-expertmodeldata" / f"{current_slot.case_id}.pdf"
            ),
            attempt_id=current_execution_id,
            output_format=slot_spec.output_format.value,
            timeout_seconds=timeout_seconds,
            workspace=root,
            request_profile=request_profile,
            _role_observer=retain_role,
        )
        retain_attempt(attempt)
        return attempt

    isolated_attempts: dict[str, LatencyAttempt] = {}
    concurrent_batch: Any = None
    try:
        for slot_spec in CANDIDATE_PROFILE_SLOT_PLAN[:45]:
            isolated_attempts[slot_spec.slot_id] = execute_slot(slot_spec)

        concurrent_specs = CANDIDATE_PROFILE_SLOT_PLAN[45:]
        concurrent_jobs = []
        for slot_spec in concurrent_specs:
            current_slot = AttemptSlot(
                slot_id=slot_spec.slot_id,
                order_index=slot_spec.order_index,
                case_id=slot_spec.case_id,
                pair_index=1,
                system=SystemName.CANDIDATE,
            )
            current_execution_id = next_candidate_profile_execution_id(
                store.ledger,
                current_slot.slot_id,
            )
            concurrent_jobs.append(
                ExternalCandidateJob(
                    slot=current_slot,
                    source_path=(
                        root
                        / "benchmark-expertmodeldata"
                        / f"{current_slot.case_id}.pdf"
                    ),
                    attempt_id=current_execution_id,
                )
            )
        current_slot = None
        current_execution_id = None
        concurrent_batch = run_synchronized_concurrent_candidate_profile(
            jobs=tuple(concurrent_jobs),
            timeout_seconds=timeout_seconds,
            workspace=root,
            _role_observer=retain_role,
            _attempt_observer=retain_attempt,
        )
    except BaseException as error:
        keyboard_interrupt = isinstance(error, KeyboardInterrupt)
        status = (
            AttemptStatus.CANCELLED
            if keyboard_interrupt
            else AttemptStatus.TIMEOUT
            if isinstance(error, TimeoutError)
            else AttemptStatus.ERROR
        )
        failure_code = (
            "worker_cancelled"
            if keyboard_interrupt
            else "worker_hard_timeout"
            if isinstance(error, TimeoutError)
            else "worker_evidence_error"
        )
        failure_type = (
            FailureType.WORKER_CANCELLED
            if keyboard_interrupt
            else FailureType.WORKER_TIMEOUT
            if isinstance(error, TimeoutError)
            else FailureType.EVIDENCE_ERROR
        )
        retained_ledger = store.ledger
        closed_execution_ids = {
            item.execution_id for item in retained_ledger.attempt_observations
        } | {
            item.execution_id
            for item in retained_ledger.controller_failures
            if item.execution_id is not None
        }
        open_executions: list[tuple[str, str]] = []
        for observation in retained_ledger.role_observations:
            key = (observation.slot_id, observation.execution_id)
            if (
                observation.execution_id not in closed_execution_ids
                and key not in open_executions
            ):
                open_executions.append(key)
        active_execution = (
            (current_slot.slot_id, current_execution_id)
            if current_slot is not None
            and current_execution_id is not None
            and current_execution_id not in closed_execution_ids
            else None
        )
        failure_targets: tuple[tuple[str | None, str | None], ...]
        if open_executions:
            failure_targets = tuple(open_executions)
        elif active_execution is not None:
            failure_targets = (active_execution,)
        else:
            failure_targets = ((None, None),)
        for failed_slot_id, failed_execution_id in failure_targets:
            checkpoint(
                lambda ledger, slot_id=failed_slot_id, execution_id=failed_execution_id: (
                    append_controller_failure(
                        ledger,
                        event_kind=(
                            "controller_keyboard_interrupt"
                            if keyboard_interrupt
                            else "controller_exception"
                        ),
                        slot_id=slot_id,
                        execution_id=execution_id,
                        status=status,
                        failure_code=failure_code,
                        failure_type=failure_type,
                        observed_at_utc=datetime.now(UTC),
                        observed_monotonic_ns=time.perf_counter_ns(),
                    )
                )
            )
        checkpoint(close_ledger)
        raise

    final_ledger = checkpoint(close_ledger)
    if final_ledger.disposition != "complete" or final_ledger.missing_slot_ids:
        raise _IncompleteCandidateProfileRun()
    if concurrent_batch is None:
        raise _IncompleteCandidateProfileRun()

    retained_cases = []
    for case_index, case_id in enumerate(
        slot.case_id for slot in CANDIDATE_PROFILE_SLOT_PLAN[::3][:15]
    ):
        labels = ("cold-json", "prewarmed-json", "cold-markdown")
        cold_json, prewarmed_json, cold_markdown = tuple(
            isolated_attempts[f"{case_id}-{label}"] for label in labels
        )
        json_sha256, markdown_sha256, markdown_size = P00_OUTPUT_IDENTITIES[case_id]
        current_json_sha256, current_markdown_sha256, current_markdown_size = (
            CURRENT_RUNTIME_OUTPUT_IDENTITIES[case_id]
        )
        retained_cases.append(
            CandidateProfileCase(
                case_id=case_id,
                source=cold_json.source,
                source_custody="public-redistributable",
                m0_case_hwm_bytes=M0_CASE_HWM_BYTES[case_id],
                p00_semantic_json_sha256=json_sha256,
                p00_markdown_sha256=markdown_sha256,
                p00_markdown_size_bytes=markdown_size,
                current_runtime_semantic_json_sha256=current_json_sha256,
                current_runtime_markdown_sha256=current_markdown_sha256,
                current_runtime_markdown_size_bytes=current_markdown_size,
                cold_json=cold_json,
                prewarmed_json=prewarmed_json,
                cold_markdown=cold_markdown,
            )
        )
    selected_attempts = tuple(
        attempt
        for case in retained_cases
        for attempt in (case.cold_json, case.prewarmed_json, case.cold_markdown)
    ) + concurrent_batch.ordered_attempts
    slot_by_id = {item.slot_id: item for item in CANDIDATE_PROFILE_SLOT_PLAN}
    zero_unexplained_drift = (
        not final_ledger.has_blocking_observation
        and all(
            attempt_output_matches_current_runtime(
                attempt, slot_by_id[attempt.slot_id]
            )
            for attempt in selected_attempts
        )
    )
    retained = CandidateProfileSet(
        schema_id="phase-latency-candidate-profile-set-v1",
        schema_version="1.0",
        profile_set_id="lat-us01-all-15-profile-v1",
        identity=identity,
        attempt_ledger=final_ledger,
        quality=P00QualityEvidence(
            case_count=15,
            page_count=30,
            reviewed_claim_count=210,
            literal_eligible_count=109,
            semantic_eligible_count=162,
            excluded_unsupported_count=48,
            control_count=25,
            dimension_count=12,
            quality_signature_sha256=(
                "a18dfdeec1eda8840e269da046285aa518a9a6094e4943e174f0893dc216a1ed"
            ),
            stable_output_signature_sha256=(
                "a7b02cdee0e58c881122a692d2bfecdacb13eefbb35225be705ae3ff6c7113a0"
            ),
            current_runtime_stable_output_signature_sha256=(
                "d10fb6107c9a0b97788ec23d2519a31b53dc3c23df5b06a1566b9e96a072e71e"
            ),
            baseline_policy=(
                "p00-historical-plus-reviewed-current-runtime-exact-v1"
            ),
            zero_unexplained_drift=zero_unexplained_drift,
        ),
        cases=tuple(retained_cases),
        concurrent_batch=concurrent_batch,
        production_instrumentation_enabled=False,
        production_feature_flag=None,
        rollback_disposition="stop-disposable-benchmark-workers",
        cache_policy="content-result-cache-disabled-filesystem-cache-uncontrolled",
        failure_retention_policy="retain-every-attempt-no-aggregate-masking-v1",
        environment_comparable=False,
        hosted_calls=0,
        hosted_credits=0,
        prompt_tokens=0,
        completion_tokens=0,
        billed_cost_microusd=0,
        egress_bytes=0,
    )
    verify_candidate_profile_set_custody(
        retained,
        workspace=root,
        ledger_path=ledger_path,
    )
    retained_ledger = store._read_and_validate(type(final_ledger))
    if retained_ledger != retained.attempt_ledger:
        raise RuntimeError("profile does not bind the retained attempt ledger")
    return retained


def run_local_candidate_attempt(
    *,
    slot: AttemptSlot,
    source: SourceIdentity,
    configuration: ConfigurationIdentity,
    attempt_id: str,
    sampler: ProcessTreeSampler | None = None,
) -> LatencyAttempt:
    """Compatibility entry point; real attempts always use a fresh worker.

    A caller-supplied sampler exists only for deterministic failure-retention
    unit controls.  It cannot produce a successful benchmark observation.
    """

    if slot.system is not SystemName.CANDIDATE:
        raise ValueError("local profiler can execute candidate slots only")
    if configuration.system is not SystemName.CANDIDATE:
        raise ValueError("local profiler requires candidate configuration")
    workspace = Path.cwd().resolve()
    source_path = (workspace / source.path).resolve()
    actual_source = derive_source_identity(
        source_path,
        case_id=slot.case_id,
        workspace=workspace,
    )
    if actual_source != source:
        raise ValueError("source identity/page count must derive from exact bytes")
    if sampler is None:
        attempt = run_external_candidate_attempt(
            slot=slot,
            source_path=source_path,
            attempt_id=attempt_id,
            output_format=configuration.output_format.value,
            workspace=workspace,
        )
        if attempt.configuration != configuration:
            execution_identity = (
                attempt.candidate_code_sha256,
                attempt.dependency_lock_sha256,
                attempt.environment_sha256,
                attempt.model_artifacts_sha256,
            )
            if any(value is None for value in execution_identity):
                raise RuntimeError("candidate attempt omitted execution identity")
            return _controller_failure_attempt(
                slot=slot,
                source=source,
                configuration=attempt.configuration,
                candidate_code_sha256=execution_identity[0],
                dependency_lock_sha256=execution_identity[1],
                environment_sha256=execution_identity[2],
                model_artifacts_sha256=execution_identity[3],
                attempt_id=attempt_id,
                started_at=attempt.started_at_utc,
                completed_at=attempt.completed_at_utc,
                started_ns=attempt.stage_trace.spans[0].started_monotonic_ns,
                ended_ns=attempt.stage_trace.spans[0].ended_monotonic_ns,
                status=AttemptStatus.ERROR,
                failure_type=FailureType.EVIDENCE_ERROR,
                failure_code="caller_configuration_mismatch",
            )
        return attempt

    started_at = datetime.now(UTC)
    profiled = sampler.profile(
        lambda: (_ for _ in ()).throw(
            RuntimeError("same-process success profiling is disabled")
        )
    )
    completed_at = datetime.now(UTC)
    if profiled.operation_error is None:
        raise RuntimeError("injected sampler cannot create a successful attempt")
    status = _attempt_status_from_exception(profiled.operation_error)
    trace = _root_only_failure_trace(
        profiled.process_tree,
        status=status,
        error=profiled.operation_error,
    )
    execution_identity = (
        configuration.runtime_sha256,
        configuration.runtime_sha256,
        configuration.runtime_sha256,
        configuration.model_artifacts_sha256,
    )
    minimum_completed_at = started_at + timedelta(
        microseconds=(trace.authoritative_total_ns + 999) // 1_000
    )
    completed_at = max(completed_at, minimum_completed_at)
    return LatencyAttempt(
        attempt_id=attempt_id,
        slot_id=slot.slot_id,
        order_index=slot.order_index,
        case_id=slot.case_id,
        pair_index=slot.pair_index,
        system=slot.system,
        source=source,
        source_binding=SourceBinding.WORKSPACE_BYTES,
        configuration=configuration,
        candidate_code_sha256=execution_identity[0],
        dependency_lock_sha256=execution_identity[1],
        environment_sha256=execution_identity[2],
        model_artifacts_sha256=execution_identity[3],
        status=status,
        started_at_utc=started_at,
        completed_at_utc=completed_at,
        total_latency_ns=trace.authoritative_total_ns,
        cache_hit=False,
        evidence_complete=False,
        output=None,
        failure=FailureRecord(
            code=(
                "request_timeout"
                if status is AttemptStatus.TIMEOUT
                else "request_exception"
            ),
            stage=StageName.REQUEST_TOTAL,
            exception_type=FailureType.REQUEST_EXCEPTION,
        ),
        stage_trace=trace,
        process_tree=profiled.process_tree,
        provider_total_latency=None,
    )


def _new_workspace_output_path(output: str, *, workspace: Path) -> Path:
    if not output or any(not 32 <= ord(character) <= 126 for character in output):
        raise ValueError("output path must contain printable ASCII only")
    root = workspace.resolve()
    candidate = Path(output)
    candidate = candidate if candidate.is_absolute() else root / candidate
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("output path escaped workspace") from error
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("output path is not canonical")
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError("output parent contains a symlink")
    parent = candidate.parent.resolve(strict=True)
    try:
        parent.relative_to(root)
    except ValueError as error:
        raise ValueError("output parent escaped workspace") from error
    if candidate.exists() or candidate.is_symlink():
        raise FileExistsError("output path already exists")
    return candidate


def _emit_json(
    value: bytes,
    output: str | None,
    *,
    maximum_bytes: int = MAXIMUM_PROFILE_SET_BYTES,
    workspace: Path | None = None,
) -> None:
    if not value or len(value) > maximum_bytes:
        raise ValueError("JSON evidence is empty or exceeds its byte bound")
    if output is None:
        print(value.decode("utf-8"))
        return
    root = (workspace or Path.cwd()).resolve()
    path = _new_workspace_output_path(output, workspace=root)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{time.perf_counter_ns()}.tmp"
    )
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    linked = False
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path, follow_symlinks=False)
        linked = True
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    if not linked:
        raise RuntimeError("atomic evidence link was not created")
    retained = bounded_read_bytes(path, maximum_bytes=maximum_bytes)
    retained_stat = path.lstat()
    if (
        retained != value
        or stat_module.S_IMODE(retained_stat.st_mode) != 0o600
        or retained_stat.st_uid != os.getuid()
        or retained_stat.st_nlink != 1
    ):
        raise RuntimeError("retained JSON evidence differs after atomic write")


class _CandidateProfileLedgerStore:
    """Fsynced, atomic, same-path checkpoint persistence for one profile run."""

    def __init__(
        self,
        *,
        path: Path,
        initial_ledger: Any,
        workspace: Path,
    ) -> None:
        self.path = path
        self._ledger = initial_ledger
        self._lock = threading.Lock()
        initial_bytes = canonical_model_bytes(initial_ledger)
        _emit_json(
            initial_bytes,
            str(path),
            maximum_bytes=MAXIMUM_PROFILE_SET_BYTES,
            workspace=workspace,
        )
        retained = self._read_and_validate(type(initial_ledger))
        if retained != initial_ledger:
            raise RuntimeError("initial profile ledger checkpoint differs")
        retained_stat = path.lstat()
        self._identity = (retained_stat.st_dev, retained_stat.st_ino)

    @property
    def ledger(self) -> Any:
        with self._lock:
            return self._ledger

    def _read_and_validate(self, model_type: Any) -> Any:
        retained_stat = self.path.lstat()
        if (
            self.path.is_symlink()
            or not stat_module.S_ISREG(retained_stat.st_mode)
            or stat_module.S_IMODE(retained_stat.st_mode) != 0o600
            or retained_stat.st_uid != os.getuid()
            or retained_stat.st_nlink != 1
        ):
            raise RuntimeError("profile ledger file custody differs")
        retained_bytes = bounded_read_bytes(
            self.path,
            maximum_bytes=MAXIMUM_PROFILE_SET_BYTES,
        )
        retained = model_type.model_validate_json(retained_bytes)
        if canonical_model_bytes(retained) != retained_bytes:
            raise RuntimeError("profile ledger checkpoint is not canonical")
        return retained

    def checkpoint(self, ledger: Any) -> Any:
        with self._lock:
            current = self._read_and_validate(type(self._ledger))
            current_stat = self.path.lstat()
            if (
                current != self._ledger
                or (current_stat.st_dev, current_stat.st_ino) != self._identity
                or ledger.previous_checkpoint_sha256 != self._ledger.checkpoint_sha256
            ):
                raise RuntimeError("profile ledger checkpoint chain or inode differs")
            value = canonical_model_bytes(ledger)
            if not value or len(value) > MAXIMUM_PROFILE_SET_BYTES:
                raise ValueError("profile ledger checkpoint exceeds its byte bound")
            temporary = self.path.with_name(
                f".{self.path.name}.{os.getpid()}.{time.perf_counter_ns()}.tmp"
            )
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(value)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                directory_descriptor = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_descriptor)
                finally:
                    os.close(directory_descriptor)
            finally:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
            retained = self._read_and_validate(type(ledger))
            if retained != ledger:
                raise RuntimeError("profile ledger differs after atomic checkpoint")
            retained_stat = self.path.lstat()
            self._identity = (retained_stat.st_dev, retained_stat.st_ino)
            self._ledger = retained
            return retained


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    sampler_process = commands.add_parser(
        "_external-sampler-process",
        help=argparse.SUPPRESS,
    )
    sampler_process.add_argument("--root-pid", type=int, required=True)
    sampler_process.add_argument(
        "--target-interval-ns", type=int, required=True
    )
    sampler_process.add_argument("--lane-index", type=int, required=True)
    sampler_process.add_argument(
        "--allow-synthetic-root-only", choices=("0", "1"), required=True
    )
    sampler_process.add_argument("--command-fd", type=int, required=True)
    sampler_process.add_argument("--evidence-fd", type=int, required=True)
    plan = commands.add_parser("plan", help="emit the deterministic round-major plan")
    plan.add_argument("--case", action="append", required=True, dest="cases")
    plan.add_argument("--samples", type=int, default=5)
    plan.add_argument("--output")
    evaluate = commands.add_parser("evaluate", help="validate and evaluate a campaign")
    evaluate.add_argument("campaign")
    evaluate.add_argument("--approved-provider-registry-sha256")
    evaluate.add_argument("--output")
    profile = commands.add_parser(
        "profile-local",
        help="execute one candidate slot in a fresh deadline-controlled worker",
    )
    profile.add_argument("--source", required=True)
    profile.add_argument("--case-id", required=True)
    profile.add_argument("--pair-index", type=int, required=True)
    profile.add_argument("--order-index", type=int, required=True)
    profile.add_argument("--attempt-id", required=True)
    profile.add_argument("--timeout-seconds", type=float, default=300.0)
    profile.add_argument(
        "--output-format", choices=("json", "markdown"), default="json"
    )
    profile.add_argument("--output", required=True)
    all_15 = commands.add_parser(
        "profile-all-15",
        help="execute and retain the exact 47-attempt candidate profile",
    )
    all_15.add_argument("--timeout-seconds", type=float, default=300.0)
    all_15.add_argument("--ledger-output", required=True)
    all_15.add_argument("--output", required=True)
    all_15.add_argument("--evaluation-output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "_external-sampler-process":
        if (
            args.root_pid <= 0
            or args.target_interval_ns <= 0
            or not 0 <= args.lane_index < EXTERNAL_SAMPLER_PROCESS_LANE_COUNT
            or args.command_fd <= 2
            or args.evidence_fd <= 2
            or args.command_fd == args.evidence_fd
        ):
            raise ValueError("external sampler process input differs")
        _external_sampler_process_main(
            root_pid=args.root_pid,
            target_interval_ns=args.target_interval_ns,
            lane_index=args.lane_index,
            allow_synthetic_root_only=(
                args.allow_synthetic_root_only == "1"
            ),
            command_fd=args.command_fd,
            evidence_fd=args.evidence_fd,
        )
        return WORKER_FATAL_ENVELOPE_WRITE_FAILED_EXIT_CODE
    if args.command == "plan":
        plan = build_interleaved_plan(args.cases, sample_count=args.samples)
        payload = json.dumps(
            [slot.model_dump(mode="json") for slot in plan],
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        _emit_json(payload, args.output)
        return 0
    if args.command == "evaluate":
        campaign = read_latency_campaign(
            bounded_read_bytes(
                Path(args.campaign),
                maximum_bytes=MAXIMUM_CAMPAIGN_BYTES,
            )
        )
        verify_campaign_custody(
            campaign,
            approved_provider_registry_sha256=(args.approved_provider_registry_sha256),
        )
        _emit_json(canonical_model_bytes(evaluate_campaign(campaign)), args.output)
        return 0
    if args.command == "profile-local":
        source_path = Path(args.source).resolve()
        try:
            source_path.relative_to(Path.cwd().resolve())
        except ValueError as error:
            raise ValueError(
                "profile source must remain inside the workspace"
            ) from error
        slot = AttemptSlot(
            slot_id=f"{args.case_id}-p{args.pair_index:02d}-candidate",
            order_index=args.order_index,
            case_id=args.case_id,
            pair_index=args.pair_index,
            system=SystemName.CANDIDATE,
        )
        attempt = run_external_candidate_attempt(
            slot=slot,
            source_path=source_path,
            attempt_id=args.attempt_id,
            output_format=args.output_format,
            timeout_seconds=args.timeout_seconds,
        )
        _emit_json(canonical_model_bytes(attempt), args.output)
        return int(
            attempt.status is not AttemptStatus.SUCCESS
            or attempt.evidence_complete is not True
        )
    if args.command == "profile-all-15":
        from tests.benchmarks.latency_profile_set import (
            CandidateProfileEvaluation,
            CandidateProfileSet,
            evaluate_candidate_profile_set,
        )

        root = Path.cwd().resolve()
        ledger_path = _new_workspace_output_path(
            args.ledger_output,
            workspace=root,
        )
        output_path = _new_workspace_output_path(args.output, workspace=root)
        evaluation_path = _new_workspace_output_path(
            args.evaluation_output,
            workspace=root,
        )
        if len({ledger_path, output_path, evaluation_path}) != 3:
            raise ValueError("ledger, profile, and evaluation outputs must be distinct")
        try:
            profile_set = run_all_15_candidate_profile(
                ledger_output=ledger_path,
                timeout_seconds=args.timeout_seconds,
                workspace=root,
            )
        except KeyboardInterrupt:
            print(
                '{"failure_code":"controller_keyboard_interrupt","passed":false}',
                file=sys.stderr,
            )
            return 130
        except BaseException:  # noqa: BLE001 - content-free CLI failure
            print(
                '{"failure_code":"candidate_profile_incomplete","passed":false}',
                file=sys.stderr,
            )
            return 2
        verify_candidate_profile_set_custody(
            profile_set,
            workspace=root,
            ledger_path=ledger_path,
        )
        profile_bytes = canonical_model_bytes(profile_set)
        if len(profile_bytes) > MAXIMUM_PROFILE_SET_BYTES:
            raise ValueError("candidate profile exceeds its retained byte bound")
        evaluation = evaluate_candidate_profile_set(profile_set)
        evaluation_bytes = canonical_model_bytes(evaluation)
        _emit_json(
            profile_bytes,
            str(output_path),
            maximum_bytes=MAXIMUM_PROFILE_SET_BYTES,
        )
        retained_profile_bytes = bounded_read_bytes(
            output_path,
            maximum_bytes=MAXIMUM_PROFILE_SET_BYTES,
        )
        retained_profile = CandidateProfileSet.model_validate_json(
            retained_profile_bytes
        )
        if canonical_model_bytes(retained_profile) != retained_profile_bytes:
            raise RuntimeError("retained candidate profile is not canonical")
        verify_candidate_profile_set_custody(
            retained_profile,
            workspace=root,
            ledger_path=ledger_path,
        )
        if (
            hashlib.sha256(retained_profile_bytes).hexdigest()
            != hashlib.sha256(profile_bytes).hexdigest()
        ):
            raise RuntimeError("retained candidate profile hash differs")
        _emit_json(
            evaluation_bytes,
            str(evaluation_path),
            maximum_bytes=MAXIMUM_PROFILE_EVALUATION_BYTES,
        )
        retained_evaluation_bytes = bounded_read_bytes(
            evaluation_path,
            maximum_bytes=MAXIMUM_PROFILE_EVALUATION_BYTES,
        )
        retained_evaluation = CandidateProfileEvaluation.model_validate_json(
            retained_evaluation_bytes
        )
        if (
            canonical_model_bytes(retained_evaluation) != retained_evaluation_bytes
            or retained_evaluation != evaluate_candidate_profile_set(retained_profile)
        ):
            raise RuntimeError("retained profile evaluation differs")
        print(
            json.dumps(
                {
                    "evaluation_path": evaluation_path.relative_to(root).as_posix(),
                    "evaluation_sha256": hashlib.sha256(
                        retained_evaluation_bytes
                    ).hexdigest(),
                    "passed": retained_evaluation.passed,
                    "profile_path": output_path.relative_to(root).as_posix(),
                    "profile_sha256": hashlib.sha256(
                        retained_profile_bytes
                    ).hexdigest(),
                },
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 0 if retained_evaluation.passed else 1
    raise AssertionError("unreachable command")


if __name__ == "__main__":
    raise SystemExit(main())
