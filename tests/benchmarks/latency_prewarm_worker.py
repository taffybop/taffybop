"""Local-only synthetic lifecycle worker for LAT-US02 evidence contracts.

The worker intentionally does not import :mod:`app`.  It exercises the
predecessor-lazy versus startup-prewarmed lifecycle and emits a bounded closed
envelope so the runner and adversarial contract tests can be proven before the
production adapter is available.  It never opens a network connection.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import resource
import sys
import time
from pathlib import Path

import psutil

from tests.benchmarks.latency_prewarm_contracts import (
    AttemptStatus,
    LifecycleResourceEvidence,
    OutputIdentity,
    RequestObservation,
    ResourcePhase,
    ResourceSample,
    RunMode,
    SourceIdentity,
    WorkerMeasurementEnvelope,
    canonical_model_bytes,
    configuration_identity,
)
from tests.benchmarks.latency_runner import (
    derive_candidate_code_sha256,
    derive_dependency_lock_sha256,
    derive_model_artifacts_sha256,
)

MAXIMUM_SOURCE_BYTES = 32 * 1024 * 1024
MAXIMUM_REQUEST_COUNT = 32
SYNTHETIC_CONVERTER_ID = "lat-us02-synthetic-immutable-converter-v1"
SYNTHETIC_CONVERTER_SHA256 = hashlib.sha256(
    SYNTHETIC_CONVERTER_ID.encode("ascii")
).hexdigest()


def _hwm_bytes() -> int:
    raw = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return max(1, raw if sys.platform == "darwin" else raw * 1_024)


def _resource_sample(phase: ResourcePhase) -> ResourceSample:
    process = psutil.Process()
    try:
        children = process.children(recursive=True)
    except (OSError, psutil.Error):
        # Some sandboxed macOS workers deny the global PID enumeration used by
        # psutil.children(). This synthetic worker never spawns descendants;
        # the runner independently proves that the owned worker PID is reaped.
        children = []
    usage = resource.getrusage(resource.RUSAGE_SELF)
    try:
        descriptor_count = process.num_fds()
    except (AttributeError, psutil.Error):
        descriptor_count = 0
    try:
        thread_count = process.num_threads()
    except (OSError, psutil.Error):
        thread_count = 1
    for child in children:
        try:
            thread_count += child.num_threads()
        except psutil.Error:
            continue
    return ResourceSample(
        phase=phase,
        observed_monotonic_ns=time.monotonic_ns(),
        rss_bytes=_hwm_bytes(),
        user_cpu_ns=max(0, int(usage.ru_utime * 1_000_000_000)),
        system_cpu_ns=max(0, int(usage.ru_stime * 1_000_000_000)),
        process_count=1 + len(children),
        thread_count=max(1, thread_count),
        file_descriptor_count=max(0, descriptor_count),
    )


def _read_source(path: Path, expected_size: int, expected_sha256: str) -> bytes:
    stat = path.lstat()
    if path.is_symlink() or not path.is_file():
        raise ValueError("source must be a non-symlink regular file")
    if stat.st_size <= 0 or stat.st_size > MAXIMUM_SOURCE_BYTES:
        raise ValueError("source size is outside the worker bound")
    data = path.read_bytes()
    if len(data) != expected_size or hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("source identity differs")
    return data


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.resolve().open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class _ImmutableSyntheticConverter:
    __slots__ = ("_identity",)

    def __init__(self, *, initialization_delay_ms: int) -> None:
        if initialization_delay_ms:
            time.sleep(initialization_delay_ms / 1_000)
        self._identity = SYNTHETIC_CONVERTER_SHA256

    @property
    def state_fingerprint(self) -> str:
        return self._identity

    def parse(self, *, case_id: str, source: bytes) -> bytes:
        source_sha256 = hashlib.sha256(source).hexdigest()
        payload = {
            "case_id": case_id,
            "converter_sha256": self._identity,
            "source_sha256": source_sha256,
        }
        return json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")


def execute_control(
    *,
    workspace: Path,
    source_path: Path,
    source_identity: SourceIdentity,
    mode: RunMode,
    request_count: int,
    startup_timeout_ns: int,
    initialization_delay_ms: int,
    expected_application_sha256: str,
    expected_dependency_sha256: str,
    expected_parser_runtime_sha256: str,
    expected_runtime_artifacts_sha256: str,
    expected_configuration_sha256: str,
    expected_converter_sha256: str,
) -> WorkerMeasurementEnvelope:
    """Execute one deterministic, content-free local lifecycle control."""

    if request_count < 2 or request_count > MAXIMUM_REQUEST_COUNT:
        raise ValueError("request count must retain at least two bounded requests")
    source = _read_source(
        source_path, source_identity.size_bytes, source_identity.sha256
    )
    cold_sample = _resource_sample(ResourcePhase.COLD_INITIALIZATION)
    startup_started = time.monotonic_ns()
    dependency_valid = derive_dependency_lock_sha256(workspace) == (
        expected_dependency_sha256
    )
    artifact_valid = derive_model_artifacts_sha256(workspace) == (
        expected_runtime_artifacts_sha256
    )
    application_valid = derive_candidate_code_sha256(workspace) == (
        expected_application_sha256
    )
    parser_runtime_valid = _file_sha256(Path(sys.executable)) == (
        expected_parser_runtime_sha256
    )
    config = configuration_identity(
        prewarm_enabled=mode is RunMode.ENABLED,
        startup_timeout_ns=startup_timeout_ns,
    )
    configuration_valid = config.sha256 == expected_configuration_sha256
    converter_valid = expected_converter_sha256 == SYNTHETIC_CONVERTER_SHA256
    identities_valid = all(
        (
            dependency_valid,
            artifact_valid,
            application_valid,
            parser_runtime_valid,
            configuration_valid,
            converter_valid,
        )
    )
    if not identities_valid:
        identity_checks = {
            "application": application_valid,
            "dependency": dependency_valid,
            "parser_runtime": parser_runtime_valid,
            "runtime_artifact": artifact_valid,
            "configuration": configuration_valid,
            "converter": converter_valid,
        }
        failed_identities = ",".join(
            name for name, valid in identity_checks.items() if not valid
        )
        raise ValueError(
            f"exact startup identity validation failed: {failed_identities}"
        )

    converter: _ImmutableSyntheticConverter | None = None
    prewarmed_idle: ResourceSample | None = None
    if mode is RunMode.ENABLED:
        converter = _ImmutableSyntheticConverter(
            initialization_delay_ms=initialization_delay_ms
        )
        prewarmed_idle = _resource_sample(ResourcePhase.PREWARMED_IDLE)
    startup_duration_ns = time.monotonic_ns() - startup_started
    if startup_duration_ns > startup_timeout_ns:
        raise TimeoutError("bounded startup timeout exceeded")

    observations: list[RequestObservation] = []
    fingerprint_after_first: str | None = None
    request_peak: ResourceSample | None = None
    for request_index in range(1, request_count + 1):
        request_started = time.monotonic_ns()
        if converter is None:
            converter = _ImmutableSyntheticConverter(
                initialization_delay_ms=initialization_delay_ms
            )
        response = converter.parse(case_id=source_identity.case_id, source=source)
        latency_ns = time.monotonic_ns() - request_started
        raw_sha256 = hashlib.sha256(response).hexdigest()
        observations.append(
            RequestObservation(
                request_index=request_index,
                latency_ns=max(1, latency_ns),
                status=AttemptStatus.SUCCESS,
                output=OutputIdentity(
                    sha256=raw_sha256,
                    normalized_sha256=raw_sha256,
                    semantic_sha256=raw_sha256,
                    size_bytes=len(response),
                    media_type="application/json",
                    validation="synthetic_contract_control",
                    normalization_policy=(
                        "json_exclude_processing_duration_ms_v1"
                    ),
                ),
                failure=None,
            )
        )
        if request_index == 1:
            fingerprint_after_first = converter.state_fingerprint
            request_peak = _resource_sample(ResourcePhase.REQUEST_PEAK)
    assert converter is not None and request_peak is not None
    repeated_sample = _resource_sample(ResourcePhase.REPEATED_REQUEST)
    state_retained = converter.state_fingerprint != fingerprint_after_first
    converter = None
    gc.collect()
    shutdown_sample = _resource_sample(ResourcePhase.SHUTDOWN)

    return WorkerMeasurementEnvelope(
        schema_id="phase-latency-prewarm-worker-envelope-v1",
        case_id=source_identity.case_id,
        mode=mode,
        source=source_identity,
        startup_duration_ns=startup_duration_ns,
        application_identity_validated=application_valid,
        dependency_identity_validated=dependency_valid,
        parser_runtime_identity_validated=parser_runtime_valid,
        runtime_artifact_identity_validated=artifact_valid,
        configuration_identity_validated=configuration_valid,
        converter_identity_validated=converter_valid,
        ready_after_identity_validation=True,
        prewarm_completed=mode is RunMode.ENABLED,
        requests=tuple(observations),
        resources=LifecycleResourceEvidence(
            cold_initialization=cold_sample,
            prewarmed_idle=prewarmed_idle,
            request_peak=request_peak,
            repeated_request=repeated_sample,
            shutdown=shutdown_sample,
        ),
        state_retention_detected=state_retained,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--source-label", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--source-size", required=True, type=int)
    parser.add_argument("--page-count", required=True, type=int)
    parser.add_argument("--mode", required=True, choices=tuple(RunMode))
    parser.add_argument("--request-count", required=True, type=int)
    parser.add_argument("--startup-timeout-ns", required=True, type=int)
    parser.add_argument("--initialization-delay-ms", type=int, default=8)
    parser.add_argument("--application-sha256", required=True)
    parser.add_argument("--dependency-sha256", required=True)
    parser.add_argument("--parser-runtime-sha256", required=True)
    parser.add_argument("--runtime-artifacts-sha256", required=True)
    parser.add_argument("--configuration-sha256", required=True)
    parser.add_argument("--converter-sha256", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    source = SourceIdentity(
        case_id=args.case_id,
        path=args.source_label,
        filename=Path(args.source_label).name,
        sha256=args.source_sha256,
        size_bytes=args.source_size,
        page_count=args.page_count,
    )
    envelope = execute_control(
        workspace=Path(args.workspace).resolve(),
        source_path=Path(args.source).resolve(),
        source_identity=source,
        mode=RunMode(args.mode),
        request_count=args.request_count,
        startup_timeout_ns=args.startup_timeout_ns,
        initialization_delay_ms=args.initialization_delay_ms,
        expected_application_sha256=args.application_sha256,
        expected_dependency_sha256=args.dependency_sha256,
        expected_parser_runtime_sha256=args.parser_runtime_sha256,
        expected_runtime_artifacts_sha256=args.runtime_artifacts_sha256,
        expected_configuration_sha256=args.configuration_sha256,
        expected_converter_sha256=args.converter_sha256,
    )
    sys.stdout.buffer.write(canonical_model_bytes(envelope))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
