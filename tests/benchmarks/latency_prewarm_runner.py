"""Minimal local-only runner for LAT-US02 prewarm evidence controls.

The runner launches only :mod:`latency_prewarm_worker`; it has no provider or
production-application adapter and therefore cannot spend hosted credits.  A
future production adapter can produce the same closed worker envelope without
changing these custody/evaluation contracts.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import psutil

from tests.benchmarks.latency_prewarm_contracts import (
    ArtifactIdentity,
    AttemptStatus,
    CaseAttemptIndex,
    CleanupEvidence,
    DirectionalLlamaReference,
    ExecutionIdentity,
    LocalPrewarmAttempt,
    LocalPrewarmEvaluation,
    LocalPrewarmEvidenceBundle,
    RunMode,
    RuntimeArtifactSetIdentity,
    SourceIdentity,
    WorkerMeasurementEnvelope,
    configuration_identity,
    evaluate_local_prewarm_bundle,
    runtime_artifact_set,
)
from tests.benchmarks.latency_runner import (
    derive_candidate_code_sha256,
    derive_dependency_lock_sha256,
    derive_model_artifacts_sha256,
)
from tests.benchmarks.latency_prewarm_worker import SYNTHETIC_CONVERTER_SHA256

MAXIMUM_WORKER_STDOUT_BYTES = 2 * 1024 * 1024
MAXIMUM_WORKER_STDERR_BYTES = 64 * 1024
DEFAULT_STARTUP_TIMEOUT_NS = 5_000_000_000


@dataclass(frozen=True, slots=True)
class LocalCase:
    case_id: str
    source_path: Path
    source_label: str
    page_count: int
    directional_llama_latency_ms: int | None = None


@dataclass(frozen=True, slots=True)
class LocalCampaignResult:
    bundle: LocalPrewarmEvidenceBundle
    evaluation: LocalPrewarmEvaluation


def _sha256_file(path: Path) -> tuple[int, str]:
    resolved = path.resolve()
    stat = resolved.stat()
    if not resolved.is_file() or stat.st_size <= 0:
        raise ValueError("identity target must be a non-empty regular file")
    digest = hashlib.sha256()
    observed = 0
    with resolved.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            observed += len(chunk)
            digest.update(chunk)
    if observed != stat.st_size:
        raise ValueError("identity target changed while reading")
    return observed, digest.hexdigest()


def _tree_size(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("runtime artifact tree cannot contain symlinks")
        if path.is_file():
            total += path.stat().st_size
    return max(1, total)


def current_execution_identity(workspace: Path) -> ExecutionIdentity:
    """Bind current app, lock, Python, local models, and additive harness bytes."""

    root = workspace.resolve()
    runtime_path = Path(sys.executable).resolve()
    _, parser_runtime_sha256 = _sha256_file(runtime_path)
    models = root / ".models"
    model_artifact = ArtifactIdentity(
        path=".models",
        sha256=derive_model_artifacts_sha256(root),
        size_bytes=_tree_size(models),
    )
    runtime_artifacts: RuntimeArtifactSetIdentity = runtime_artifact_set(
        (model_artifact,)
    )
    harness_paths = (
        root / "tests/benchmarks/latency_prewarm_contracts.py",
        root / "tests/benchmarks/latency_prewarm_runner.py",
        root / "tests/benchmarks/latency_prewarm_worker.py",
    )
    harness_records = []
    for path in harness_paths:
        size, sha256 = _sha256_file(path)
        harness_records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256,
                "size_bytes": size,
            }
        )
    harness_sha256 = hashlib.sha256(
        json.dumps(
            harness_records,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return ExecutionIdentity(
        application_code_sha256=derive_candidate_code_sha256(root),
        dependency_manifest_sha256=derive_dependency_lock_sha256(root),
        parser_runtime_sha256=parser_runtime_sha256,
        runtime_artifacts=runtime_artifacts,
        harness_sha256=harness_sha256,
    )


def _controller_counts() -> tuple[int, int]:
    process = psutil.Process()
    try:
        descriptor_count = process.num_fds()
    except (AttributeError, psutil.Error):
        descriptor_count = 0
    return process.num_threads(), descriptor_count


def _worker_environment(workspace: Path) -> dict[str, str]:
    allowed = {
        key: value
        for key, value in os.environ.items()
        if key
        in {
            "DYLD_LIBRARY_PATH",
            "LANG",
            "LC_ALL",
            "LD_LIBRARY_PATH",
            "PATH",
            "SYSTEMROOT",
            "TMPDIR",
        }
    }
    allowed.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(workspace.resolve()),
            "TOKENIZERS_PARALLELISM": "false",
        }
    )
    return allowed


def run_local_attempt(
    *,
    workspace: Path,
    case: LocalCase,
    mode: RunMode,
    repetition_index: int,
    execution: ExecutionIdentity,
    request_count: int = 2,
    startup_timeout_ns: int = DEFAULT_STARTUP_TIMEOUT_NS,
    initialization_delay_ms: int = 8,
) -> LocalPrewarmAttempt:
    """Run one bounded synthetic control attempt without retries or selection."""

    source_path = case.source_path.resolve()
    source_size, source_sha256 = _sha256_file(source_path)
    source = SourceIdentity(
        case_id=case.case_id,
        path=case.source_label,
        filename=Path(case.source_label).name,
        sha256=source_sha256,
        size_bytes=source_size,
        page_count=case.page_count,
    )
    configuration = configuration_identity(
        prewarm_enabled=mode is RunMode.ENABLED,
        startup_timeout_ns=startup_timeout_ns,
    )
    attempt_id = (
        f"lat-us02-{case.case_id}-{mode.value}-r{repetition_index:02d}"
    )
    command = (
        sys.executable,
        "-m",
        "tests.benchmarks.latency_prewarm_worker",
        "--workspace",
        str(workspace.resolve()),
        "--source",
        str(source_path),
        "--source-label",
        case.source_label,
        "--case-id",
        case.case_id,
        "--source-sha256",
        source.sha256,
        "--source-size",
        str(source.size_bytes),
        "--page-count",
        str(source.page_count),
        "--mode",
        mode.value,
        "--request-count",
        str(request_count),
        "--startup-timeout-ns",
        str(startup_timeout_ns),
        "--initialization-delay-ms",
        str(initialization_delay_ms),
        "--application-sha256",
        execution.application_code_sha256,
        "--dependency-sha256",
        execution.dependency_manifest_sha256,
        "--parser-runtime-sha256",
        execution.parser_runtime_sha256,
        "--runtime-artifacts-sha256",
        execution.runtime_artifacts.artifacts[0].sha256,
        "--configuration-sha256",
        configuration.sha256,
        "--converter-sha256",
        SYNTHETIC_CONVERTER_SHA256,
    )
    controller_threads_before, controller_fds_before = _controller_counts()
    started_at = datetime.now(UTC)
    process = subprocess.Popen(
        command,
        cwd=workspace,
        env=_worker_environment(workspace),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    worker_pid = process.pid
    worker_create_time = psutil.Process(worker_pid).create_time()
    stdout, stderr = process.communicate(
        timeout=max(10.0, startup_timeout_ns / 1_000_000_000 + 5.0)
    )
    completed_at = datetime.now(UTC)
    cleanup_started = time.monotonic_ns()
    if len(stdout) > MAXIMUM_WORKER_STDOUT_BYTES:
        raise RuntimeError("prewarm worker stdout exceeded its evidence bound")
    if len(stderr) > MAXIMUM_WORKER_STDERR_BYTES:
        raise RuntimeError("prewarm worker stderr exceeded its evidence bound")
    if process.returncode != 0:
        stderr_text = stderr.decode("utf-8", errors="replace")
        raise RuntimeError(
            "prewarm worker failed closed with exit code "
            f"{process.returncode}: {stderr_text}"
        )
    envelope = WorkerMeasurementEnvelope.model_validate_json(stdout)
    controller_threads_after, controller_fds_after = _controller_counts()
    same_worker_alive = False
    try:
        remaining = psutil.Process(worker_pid)
        same_worker_alive = remaining.create_time() == worker_create_time
    except psutil.NoSuchProcess:
        same_worker_alive = False
    cleanup_duration_ns = time.monotonic_ns() - cleanup_started
    shutdown = envelope.resources.shutdown
    cold = envelope.resources.cold_initialization
    cleanup = CleanupEvidence(
        shutdown_duration_ns=cleanup_duration_ns,
        cleanup_completed=(not same_worker_alive and shutdown.process_count == 1),
        worker_exited=process.returncode is not None,
        worker_reaped=not same_worker_alive,
        exit_code=process.returncode,
        owned_process_count_after_shutdown=max(0, shutdown.process_count - 1),
        all_owned_processes_reaped=shutdown.process_count == 1,
        threads_returned_to_baseline=(
            shutdown.thread_count <= cold.thread_count
            and controller_threads_after <= controller_threads_before
        ),
        file_descriptors_returned_to_baseline=(
            shutdown.file_descriptor_count <= cold.file_descriptor_count
            and controller_fds_after <= controller_fds_before
        ),
        state_retention_detected=envelope.state_retention_detected,
        oom_observed=False,
        unbounded_rss_growth_observed=False,
    )
    status = AttemptStatus.SUCCESS
    return LocalPrewarmAttempt(
        schema_id="phase-latency-prewarm-attempt-v1",
        attempt_id=attempt_id,
        case_id=case.case_id,
        repetition_index=repetition_index,
        mode=mode,
        started_at_utc=started_at,
        completed_at_utc=completed_at,
        source=source,
        execution=execution,
        configuration=configuration,
        worker=envelope,
        cleanup=cleanup,
        status=status,
        failure=None,
    )


def run_synthetic_local_campaign(
    *,
    workspace: Path,
    cases: tuple[LocalCase, ...],
    repetitions: int = 2,
    request_count: int = 2,
) -> LocalCampaignResult:
    """Run all declared local pairs once each; never retry or select results."""

    if not cases:
        raise ValueError("at least one local case is required")
    if repetitions < 2:
        raise ValueError("local comparisons require repeated observations")
    execution = current_execution_identity(workspace)
    attempts: list[LocalPrewarmAttempt] = []
    indexes: list[CaseAttemptIndex] = []
    references: list[DirectionalLlamaReference] = []
    for case in sorted(cases, key=lambda item: item.case_id):
        predecessor_ids: list[str] = []
        enabled_ids: list[str] = []
        for repetition_index in range(1, repetitions + 1):
            for mode, destination in (
                (RunMode.PREDECESSOR, predecessor_ids),
                (RunMode.ENABLED, enabled_ids),
            ):
                attempt = run_local_attempt(
                    workspace=workspace,
                    case=case,
                    mode=mode,
                    repetition_index=repetition_index,
                    execution=execution,
                    request_count=request_count,
                )
                attempts.append(attempt)
                destination.append(attempt.attempt_id)
        indexes.append(
            CaseAttemptIndex(
                case_id=case.case_id,
                predecessor_attempt_ids=tuple(predecessor_ids),
                enabled_attempt_ids=tuple(enabled_ids),
            )
        )
        if case.directional_llama_latency_ms is not None:
            source_size, source_sha256 = _sha256_file(case.source_path)
            del source_size
            references.append(
                DirectionalLlamaReference(
                    case_id=case.case_id,
                    source_sha256=source_sha256,
                    provider_total_latency_ms=case.directional_llama_latency_ms,
                    source="retained_one_sample_llamaparse_v1",
                )
            )
    bundle = LocalPrewarmEvidenceBundle(
        schema_id="phase-latency-prewarm-evidence-v1",
        evidence_scope="synthetic_contract_control",
        generated_at_utc=datetime.now(UTC),
        attempts=tuple(attempts),
        case_indexes=tuple(indexes),
        directional_llama_references=tuple(references),
    )
    return LocalCampaignResult(
        bundle=bundle,
        evaluation=evaluate_local_prewarm_bundle(bundle),
    )


__all__ = [
    "DEFAULT_STARTUP_TIMEOUT_NS",
    "LocalCampaignResult",
    "LocalCase",
    "current_execution_identity",
    "run_local_attempt",
    "run_synthetic_local_campaign",
]
