"""Retained local-only campaign CLI for the LAT-US02 production adapter."""

from __future__ import annotations

import argparse
import contextlib
import errno
import hashlib
import json
import os
import re
import select
import selectors
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from functools import wraps
from math import ceil
from pathlib import Path
from statistics import median
from typing import Annotated, Any, Callable, Literal, Mapping
from unittest.mock import patch

import psutil
from pydantic import Field, StrictBool, ValidationError, model_validator
from pydantic_core import to_jsonable_python

from tests.benchmarks.corpus_registry import (
    EXPECTED_CASE_IDS,
    PortableCorpusRegistry,
    load_corpus_registry,
    verify_current_artifacts,
)
from tests.benchmarks.latency_isolation import (
    OS_NETWORK_SANDBOX_EXECUTABLE,
    OS_NETWORK_SANDBOX_PROFILE,
    controlled_worker_environment,
    materialize_private_child_network_guard,
    sandboxed_worker_command,
    sanitized_worker_environment,
    worker_environment_sha256,
)
from tests.benchmarks.latency_prewarm_contracts import (
    ArtifactIdentity,
    AsgiResponseWitness,
    AttemptStatus,
    BrokerChildBirth,
    BrokerChildCpuReceipt,
    BrokerChildWait4Tombstone,
    BrokerLifecycleReceiptEvidence,
    BrokerQuiescenceReceipt,
    BrokerRequestBindingEvidence,
    BrokerScratchInventory,
    CaseAttemptIndex,
    CleanupEvidence,
    ConfigurationIdentity,
    ControllerPreExecGatedChildSample,
    ControllerResourceSampleLogRow,
    ContractModel,
    CrossInputIsolationEvidence,
    CrossInputRequestObservation,
    CurrentRuntimeOutputExpectation,
    DependencyRuntimeIdentity,
    DirectionalLlamaReference,
    ExecutionIdentity,
    ExactProcessIdentity,
    ExactBrokerRequestCpuEvidence,
    ExternalCpuStableEdgeRecord,
    FrameworkThreadBaseline,
    FailureCode,
    FailureRecord,
    ImmutableRuntimeInputCustodyEvidence,
    KernelSandboxNativeProbeInvocation,
    KernelSandboxNativeProbeResult,
    LocalPrewarmAttempt,
    LocalPrewarmEvaluation,
    LocalPrewarmEvidenceBundle,
    LifecycleResourceEvidence,
    NativeProcessResourceSample,
    NativeFileDescriptorInventory,
    NativeSelfCpuCounter,
    NativeThreadInventory,
    PEAK_SAMPLE_EDGE_TOLERANCE_NS,
    PEAK_SAMPLE_MAXIMUM_GAP_NS,
    PEAK_SAMPLE_TARGET_INTERVAL_NS,
    PRODUCTION_CASE_IDS,
    PRODUCTION_MINIMUM_REQUESTS,
    REQUEST_CONTROL_TRANSCRIPT_MAXIMUM_BYTES,
    RequestObservation,
    RequestControlReadinessEvidence,
    RequestResourceBoundary,
    RawRUsage,
    ResourcePhase,
    ResourceSample,
    RunMode,
    RuntimeArtifactSetIdentity,
    SampledProcessIdentity,
    SourceIdentity,
    TerminalRecordDescriptor,
    TerminalRecordManifest,
    TerminalRecordSubmanifest,
    TerminalRequestControlTranscriptEvidence,
    TrustedLauncherIdentity,
    UninstrumentedRollbackEvidence,
    UninstrumentedRollbackObservation,
    WorkerMeasurementEnvelope,
    canonical_model_bytes,
    cross_input_configuration_identity,
    derive_lifecycle_cleanup_tests_sha256,
    derive_prewarm_harness_sha256,
    evaluate_retained_local_prewarm_bundle,
    evaluate_local_prewarm_attempt_blocking_failures,
    external_cpu_stable_edge_record,
    production_configuration_identity,
    rollback_output_configuration_identity,
    request_control_readiness_evidence,
    require_terminal_request_control_transcript,
    runtime_artifact_set,
    sanitized_configuration_projection,
    broker_scratch_inventory,
    broker_lifecycle_receipt_evidence,
    terminal_record_descriptor,
    terminal_record_manifest,
    terminal_record_submanifest,
    terminal_child_watch_log_evidence,
    terminal_request_control_transcript_evidence,
)
from tests.benchmarks.latency_prewarm_cpu import (
    DarwinProcessMetricSample,
    DarwinProcessSelfCpuSample,
    darwin_process_group_pids,
    read_darwin_process_identity,
    sample_darwin_process_group_metrics,
    sample_darwin_process_self_cpu,
)
from tests.benchmarks.latency_prewarm_production_worker import (
    CrossInputRawWorkerEnvelope,
    CrossInputWorkerEnvelope,
    DirectRollbackRawWorkerEnvelope,
    PrebindFatalRecord,
    ProductionRawRequestObservation,
    ProductionRawWorkerEnvelope,
    _unbounded_rss_growth,
    derive_production_network_isolation_sha256,
)
from tests.benchmarks.latency_prewarm_watchdog import (
    MAXIMUM_ATTEMPT_RUNTIME_NS,
    MAXIMUM_EVIDENCE_BYTES as MAXIMUM_PREWARM_WATCHDOG_EVIDENCE_BYTES,
    AppendOnlyLogSnapshot,
    PhaseDeadlineAck,
    PhaseDeadlineRecord,
    PrewarmWatchdogConfig,
    _WatchdogLauncherChannel,
    append_phase_deadline,
    build_prewarm_watchdog_command,
    read_phase_acks,
    read_phase_deadlines,
)
from tests.benchmarks.latency_watchdog import sanitized_watchdog_environment
from tests.benchmarks.latency_runner import (
    derive_candidate_code_sha256,
    derive_dependency_lock_sha256,
    read_process_tree_snapshot,
)
from app.services.immutable_tree_custody import (
    DarwinImmutableTreeCustody,
    ImmutableTreeCustodyViolation,
)
from app.services.parser_sandbox_materialization import (
    SandboxProbeMaterialization,
    materialize_sandbox_probe_roots,
    select_bounded_probe_source,
)
from app.services.parser_sandbox_attempt import SandboxAttemptProbeAuthority

DEFAULT_REGISTRY_PATH = (
    "tracker/phase-00-baseline/evidence/P00-US04-corpus-registry.json"
)
DEFAULT_LLAMA_REFERENCE_PATH = (
    "tracker/benchmarks/llamaparse-15/latency-reference-v1.json"
)
MAXIMUM_WORKER_STDOUT_BYTES = 4_194_304
MAXIMUM_WORKER_STDERR_BYTES = 4_194_304
MAXIMUM_WORKER_COMBINED_BYTES = 4_194_304
MAXIMUM_BROKER_LAUNCH_TEMPLATE_BYTES = 524_288
MAXIMUM_PRIVATE_PROTOCOL_EVIDENCE_BYTES = 16_777_216
MAXIMUM_IMMUTABLE_INPUT_CUSTODY_BYTES = 16_777_216
MINIMUM_REPETITIONS = 2
MINIMUM_REQUESTS = PRODUCTION_MINIMUM_REQUESTS
WATCHDOG_READY_TIMEOUT_NS = 5_000_000_000
WATCHDOG_HEARTBEAT_INTERVAL_SECONDS = 0.250
POST_DEADLINE_REAP_SECONDS = 5.0
MAXIMUM_BROKER_READY_BYTES = 16_384
MAXIMUM_SUPERVISOR_READY_BYTES = 16_384
MAXIMUM_NATIVE_FORK_PROBE_BYTES = 1_048_576
MAXIMUM_NATIVE_SPAWN_GUARD_BYTES = 1_048_576
MAXIMUM_NATIVE_SANDBOX_PROBE_BYTES = 1_048_576
MAXIMUM_NATIVE_RUNTIME_GATE_BYTES = 1_048_576
OS_FORK_DENIED_SANDBOX_PROFILE = (
    "(version 1)(allow default)(deny network-outbound)"
    "(deny network-inbound)(deny process-fork)"
)
OS_FORK_DENIED_SANDBOX_PROFILE_SHA256 = hashlib.sha256(
    OS_FORK_DENIED_SANDBOX_PROFILE.encode("ascii")
).hexdigest()
APPROVED_COMBINED_ARTIFACT_SHA256 = (
    "7da24e7a135b1f0c66048fb552c5dce4d41bc328daf9e86670f435203dad09d4"
)
APPROVED_CLASSIFIER_SNAPSHOT_REVISION = (
    "f859dfbff5c9916cd996942d4b0db7fa25808220"
)


@dataclass(frozen=True, slots=True)
class BrokeredLaunchInputs:
    tesseract_executable: Path
    tesseract_data_path: Path
    immutable_artifact_root: Path
    allowed_languages: tuple[str, ...]
    request_root: Path
    worker_scratch_root: Path
    staged_executable_root: Path
    child_wrapper_path: Path

    def __post_init__(self) -> None:
        paths = (
            self.tesseract_executable,
            self.tesseract_data_path,
            self.immutable_artifact_root,
            self.request_root,
            self.worker_scratch_root,
            self.staged_executable_root,
            self.child_wrapper_path,
        )
        if any(not path.is_absolute() for path in paths):
            raise ValueError("brokered launch paths must be absolute")
        if (
            not self.allowed_languages
            or self.allowed_languages != tuple(sorted(set(self.allowed_languages)))
        ):
            raise ValueError("brokered launch languages must be canonical")


class ControllerProcessIdentity(ContractModel):
    pid: Annotated[int, Field(strict=True, gt=0)]
    create_time_ns: Annotated[int, Field(strict=True, gt=0)]
    process_group_id: Annotated[int, Field(strict=True, gt=0)]
    session_id: Annotated[int, Field(strict=True, gt=0)]


class LauncherOwnedRootIdentity(ContractModel):
    """Full immutable identity returned by the sole-parent launcher."""

    pid: Annotated[int, Field(strict=True, gt=0)]
    start_abstime: Annotated[int, Field(strict=True, gt=0)]
    create_time_ns: Annotated[int, Field(strict=True, gt=0)]
    ppid: Annotated[int, Field(strict=True, gt=0)]
    pgid: Annotated[int, Field(strict=True, gt=0)]
    sid: Annotated[int, Field(strict=True, gt=0)]
    uid: Annotated[int, Field(strict=True, gt=0)]
    euid: Annotated[int, Field(strict=True, gt=0)]

    @model_validator(mode="after")
    def validate_fresh_root(self) -> "LauncherOwnedRootIdentity":
        if self.pid != self.pgid or self.pid != self.sid:
            raise ValueError("launcher-owned root must lead its fresh group/session")
        return self


def _native_fd_membership_sha256(
    inventory: NativeFileDescriptorInventory,
) -> str:
    """Hash stable descriptor membership, excluding mutable I/O position/state."""

    descriptors: list[dict[str, Any]] = []
    for item in inventory.descriptors:
        value = item.model_dump(mode="json")
        value.pop("record_sha256")
        value.pop("descriptor_offset")
        if value["vnode"] is not None:
            value["vnode"].pop("size")
        if value["socket"] is not None:
            value["socket"].pop("socket_state")
        if value["pipe"] is not None:
            value["pipe"].pop("pipe_status")
        if value["kqueue"] is not None:
            value["kqueue"].pop("kqueue_state")
        descriptors.append(value)
    return _canonical_sha256(
        {
            "schema_id": "darwin-stable-fd-membership-projection-v1",
            "process": inventory.process.model_dump(mode="json"),
            "descriptors": descriptors,
        }
    )


class ControllerResourceSample(ContractModel):
    observed_monotonic_ns: Annotated[int, Field(strict=True, gt=0)]
    identity: ControllerProcessIdentity
    thread_count: Annotated[int, Field(strict=True, gt=0)]
    file_descriptor_count: Annotated[int, Field(strict=True, ge=0)]
    thread_inventory: NativeThreadInventory
    file_descriptor_inventory: NativeFileDescriptorInventory
    file_descriptor_membership_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_exact_inventory(self) -> "ControllerResourceSample":
        expected = (
            self.identity.pid,
            self.identity.process_group_id,
            self.identity.session_id,
        )
        if (
            self.thread_count != self.thread_inventory.thread_count
            or self.file_descriptor_count
            != len(self.file_descriptor_inventory.descriptors)
            or (
                self.thread_inventory.process.pid,
                self.thread_inventory.process.pgid,
                self.thread_inventory.process.sid,
            )
            != expected
            or (
                self.file_descriptor_inventory.process.pid,
                self.file_descriptor_inventory.process.pgid,
                self.file_descriptor_inventory.process.sid,
            )
            != expected
            or self.thread_inventory.process
            != self.file_descriptor_inventory.process
            or self.file_descriptor_membership_sha256
            != _native_fd_membership_sha256(self.file_descriptor_inventory)
            or max(
                self.thread_inventory.second_scan_completed_monotonic_ns,
                self.file_descriptor_inventory.second_scan_completed_monotonic_ns,
            )
            > self.observed_monotonic_ns
        ):
            raise ValueError("controller exact resource inventory differs")
        return self


class ControllerResourceBoundary(ContractModel):
    before: ControllerResourceSample
    after: ControllerResourceSample
    threads_returned_to_baseline: StrictBool
    file_descriptors_returned_to_baseline: StrictBool

    @model_validator(mode="after")
    def validate_boundary(self) -> "ControllerResourceBoundary":
        if self.before.identity != self.after.identity:
            raise ValueError("controller identity changed across attempt")
        if (
            self.before.thread_inventory.process
            != self.after.thread_inventory.process
        ):
            raise ValueError("controller native identity changed across attempt")
        if self.after.observed_monotonic_ns < self.before.observed_monotonic_ns:
            raise ValueError("controller resource boundary regressed")
        if self.threads_returned_to_baseline != (
            self.after.thread_inventory.thread_ids
            == self.before.thread_inventory.thread_ids
        ):
            raise ValueError("controller thread restoration claim differs")
        if self.file_descriptors_returned_to_baseline != (
            self.after.file_descriptor_membership_sha256
            == self.before.file_descriptor_membership_sha256
        ):
            raise ValueError("controller FD restoration claim differs")
        return self


class ProductionWatchdogTerminalEvidence(ContractModel):
    schema_id: Literal["phase-latency-prewarm-watchdog-terminal-v1"]
    attempt_id: str
    controller_pid: Annotated[int, Field(strict=True, gt=0)]
    controller_start_abstime: Annotated[int, Field(strict=True, gt=0)]
    controller_create_time_ns: Annotated[int, Field(strict=True, gt=0)]
    controller_pgid: Annotated[int, Field(strict=True, gt=0)]
    controller_sid: Annotated[int, Field(strict=True, gt=0)]
    worker_pid: Annotated[int, Field(strict=True, gt=0)]
    worker_create_time_ns: Annotated[int, Field(strict=True, gt=0)]
    worker_pgid: Annotated[int, Field(strict=True, gt=0)]
    worker_sid: Annotated[int, Field(strict=True, gt=0)]
    broker_pid: Annotated[int, Field(strict=True, gt=0)] | None = None
    broker_start_abstime: Annotated[
        int, Field(strict=True, gt=0)
    ] | None = None
    broker_create_time_ns: Annotated[
        int, Field(strict=True, gt=0)
    ] | None = None
    broker_pgid: Annotated[int, Field(strict=True, gt=0)] | None = None
    broker_sid: Annotated[int, Field(strict=True, gt=0)] | None = None
    absolute_deadline_monotonic_ns: Annotated[int, Field(strict=True, gt=0)]
    observed_monotonic_ns: Annotated[int, Field(strict=True, gt=0)]
    outcome: Literal[
        "worker_exited",
        "controller_dead_worker_terminated",
        "controller_reused_worker_terminated",
        "heartbeat_stale_worker_terminated",
        "heartbeat_invalid_worker_terminated",
        "absolute_deadline_worker_terminated",
        "signal_worker_terminated",
        "internal_error_worker_terminated",
        "phase_control_invalid_worker_terminated",
        "phase_deadline_worker_terminated",
        "worker_group_residue_terminated",
        "invalid_control_input",
        "private_session_required",
        "controller_unavailable_at_bind",
        "controller_reused_at_bind",
        "worker_unavailable_at_bind",
        "worker_identity_rejected",
        "heartbeat_invalid_at_bind",
        "worker_reused_without_signal",
        "worker_group_drift_without_signal",
        "worker_termination_unconfirmed",
        "worker_termination_unsafe",
        "broker_unavailable_at_bind",
        "broker_identity_rejected",
        "broker_exited_worker_terminated",
        "broker_reused_worker_terminated",
        "broker_group_drift_worker_terminated",
        "broker_group_residue_terminated",
        "child_deadline_worker_terminated",
    ]
    exit_code: Annotated[int, Field(strict=True, ge=0, le=37)]
    termination_policy: Literal["sigterm-250ms-then-sigkill-v1"]
    watchdog_excluded_from_worker_request_tree: Literal[True]
    worker_kill_attempted: StrictBool
    sigterm_attempted: StrictBool
    sigkill_attempted: StrictBool
    worker_group_disappearance_confirmed: StrictBool
    broker_kill_attempted: StrictBool = False
    broker_sigterm_attempted: StrictBool = False
    broker_sigkill_attempted: StrictBool = False
    broker_group_disappearance_confirmed: StrictBool | None = None
    child_watch_registration_count: Annotated[
        int, Field(strict=True, ge=0)
    ] | None = None
    child_watch_reaped_count: Annotated[int, Field(strict=True, ge=0)] | None = None
    child_watch_open_registration_count: Annotated[
        int, Field(strict=True, ge=0)
    ] | None = None
    child_watch_all_disappearance_confirmed: StrictBool | None = None
    child_watch_identity_drift_observed: StrictBool | None = None
    child_watch_sigterm_attempted: StrictBool | None = None
    child_watch_sigkill_attempted: StrictBool | None = None
    child_watch_audit_closed: StrictBool | None = None
    child_watch_channel_eof: StrictBool | None = None
    child_watch_log_size_bytes: Annotated[int, Field(strict=True, ge=0)] | None = None
    child_watch_log_head_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    child_watch_log_row_count: Annotated[
        int, Field(strict=True, ge=0)
    ] | None = None
    child_watch_record_blob_root_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    child_watch_record_blob_count: Annotated[
        int, Field(strict=True, ge=0)
    ] | None = None
    child_watch_record_blob_size_bytes: Annotated[
        int, Field(strict=True, ge=0)
    ] | None = None
    child_watch_record_blob_head_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    child_watch_event_blob_count: Annotated[
        int, Field(strict=True, ge=0)
    ] | None = None
    child_watch_event_blob_size_bytes: Annotated[
        int, Field(strict=True, ge=0)
    ] | None = None
    child_watch_event_blob_root_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    child_watch_event_head_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    child_deadline_violation_observed: StrictBool = False
    phase_sequence: Annotated[int, Field(strict=True, gt=0)] | None
    phase: Literal["startup", "request", "shutdown"] | None
    phase_deadline_monotonic_ns: Annotated[
        int, Field(strict=True, gt=0)
    ] | None
    phase_record_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    phase_ack_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    phase_deadline_acknowledged: StrictBool
    phase_deadline_violation_observed: StrictBool
    rejected_phase_sequence: Annotated[int, Field(strict=True, gt=0)] | None
    rejected_phase_record_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_terminal(self) -> "ProductionWatchdogTerminalEvidence":
        fields = self.model_dump(mode="json", exclude={"record_sha256"})
        if self.record_sha256 != _canonical_sha256(fields):
            raise ValueError("watchdog terminal identity differs")
        broker_identity = (
            self.broker_pid,
            self.broker_start_abstime,
            self.broker_create_time_ns,
            self.broker_pgid,
            self.broker_sid,
        )
        if any(value is not None for value in broker_identity) != all(
            value is not None for value in broker_identity
        ):
            raise ValueError("watchdog terminal broker identity is incomplete")
        if self.broker_pid is None:
            child_watch_values = (
                self.child_watch_registration_count,
                self.child_watch_reaped_count,
                self.child_watch_open_registration_count,
                self.child_watch_all_disappearance_confirmed,
                self.child_watch_identity_drift_observed,
                self.child_watch_sigterm_attempted,
                self.child_watch_sigkill_attempted,
                self.child_watch_audit_closed,
                self.child_watch_channel_eof,
                self.child_watch_log_size_bytes,
                self.child_watch_log_head_sha256,
                self.child_watch_log_row_count,
                self.child_watch_record_blob_root_sha256,
                self.child_watch_record_blob_count,
                self.child_watch_record_blob_size_bytes,
                self.child_watch_record_blob_head_sha256,
                self.child_watch_event_blob_count,
                self.child_watch_event_blob_size_bytes,
                self.child_watch_event_blob_root_sha256,
                self.child_watch_event_head_sha256,
            )
            if (
                self.broker_group_disappearance_confirmed is not None
                or self.broker_kill_attempted
                or self.broker_sigterm_attempted
                or self.broker_sigkill_attempted
                or any(value is not None for value in child_watch_values)
            ):
                raise ValueError("brokerless terminal retained broker claims")
        elif (
            self.broker_pid != self.broker_pgid
            or self.broker_pid != self.broker_sid
            or self.broker_pgid == self.worker_pgid
            or self.broker_group_disappearance_confirmed is None
        ):
            raise ValueError("watchdog terminal broker custody differs")
        else:
            child_watch_values = (
                self.child_watch_registration_count,
                self.child_watch_reaped_count,
                self.child_watch_open_registration_count,
                self.child_watch_all_disappearance_confirmed,
                self.child_watch_identity_drift_observed,
                self.child_watch_sigterm_attempted,
                self.child_watch_sigkill_attempted,
                self.child_watch_audit_closed,
                self.child_watch_channel_eof,
                self.child_watch_log_size_bytes,
                self.child_watch_log_head_sha256,
                self.child_watch_log_row_count,
                self.child_watch_record_blob_root_sha256,
                self.child_watch_record_blob_count,
                self.child_watch_record_blob_size_bytes,
                self.child_watch_record_blob_head_sha256,
                self.child_watch_event_blob_count,
                self.child_watch_event_blob_size_bytes,
                self.child_watch_event_blob_root_sha256,
                self.child_watch_event_head_sha256,
            )
            if not all(value is not None for value in child_watch_values):
                raise ValueError("watchdog child custody evidence is incomplete")
            assert self.child_watch_registration_count is not None
            assert self.child_watch_reaped_count is not None
            assert self.child_watch_open_registration_count is not None
            assert self.child_watch_log_size_bytes is not None
            assert self.child_watch_log_row_count is not None
            assert self.child_watch_record_blob_count is not None
            assert self.child_watch_record_blob_size_bytes is not None
            assert self.child_watch_event_blob_count is not None
            assert self.child_watch_event_blob_size_bytes is not None
            if (
                self.child_watch_reaped_count
                + self.child_watch_open_registration_count
                != self.child_watch_registration_count
                or self.child_watch_log_size_bytes
                != self.child_watch_log_row_count * 81
                or self.child_watch_log_row_count
                != self.child_watch_record_blob_count
                or (
                    self.child_watch_log_row_count == 0
                    and self.child_watch_record_blob_size_bytes != 0
                )
                or (
                    self.child_watch_log_row_count > 0
                    and self.child_watch_record_blob_size_bytes <= 0
                )
                or self.child_watch_event_blob_count
                != 3 * self.child_watch_registration_count
                or (
                    self.child_watch_registration_count == 0
                    and (
                        self.child_watch_event_blob_size_bytes != 0
                        or self.child_watch_event_head_sha256 != "0" * 64
                    )
                )
                or (
                    self.child_watch_registration_count > 0
                    and (
                        self.child_watch_event_blob_size_bytes <= 0
                        or self.child_watch_event_head_sha256 == "0" * 64
                    )
                )
            ):
                raise ValueError("watchdog child registration closure differs")
        if self.outcome == "worker_exited":
            if (
                self.exit_code != 0
                or self.worker_kill_attempted
                or self.sigterm_attempted
                or self.sigkill_attempted
                or not self.worker_group_disappearance_confirmed
                or not self.phase_deadline_acknowledged
                or self.phase_sequence is None
                or self.phase != "shutdown"
                or self.phase_deadline_monotonic_ns is None
                or self.phase_record_sha256 is None
                or self.phase_ack_sha256 is None
                or self.observed_monotonic_ns
                >= self.phase_deadline_monotonic_ns
                or self.observed_monotonic_ns
                >= self.absolute_deadline_monotonic_ns
                or self.phase_deadline_violation_observed
                or self.rejected_phase_sequence is not None
                or self.rejected_phase_record_sha256 is not None
                or self.child_deadline_violation_observed
                or (
                    self.broker_pid is not None
                    and (
                        not self.broker_group_disappearance_confirmed
                        or self.broker_kill_attempted
                        or self.broker_sigterm_attempted
                        or self.broker_sigkill_attempted
                        or self.child_watch_registration_count
                        != self.child_watch_reaped_count
                        or self.child_watch_open_registration_count != 0
                        or not self.child_watch_all_disappearance_confirmed
                        or self.child_watch_identity_drift_observed
                        or self.child_watch_sigterm_attempted
                        or self.child_watch_sigkill_attempted
                        or not self.child_watch_audit_closed
                        or not self.child_watch_channel_eof
                    )
                )
            ):
                raise ValueError("normal watchdog terminal evidence differs")
        elif self.exit_code == 0:
            raise ValueError("blocking watchdog outcome cannot exit zero")
        if self.phase_deadline_violation_observed != (
            self.outcome == "phase_deadline_worker_terminated"
        ):
            raise ValueError("watchdog phase-deadline violation claim differs")
        if self.child_deadline_violation_observed != (
            self.outcome == "child_deadline_worker_terminated"
        ):
            raise ValueError("watchdog child-deadline violation claim differs")
        if (self.rejected_phase_sequence is None) != (
            self.rejected_phase_record_sha256 is None
        ):
            raise ValueError("rejected watchdog phase identity is incomplete")
        if self.rejected_phase_sequence is not None and (
            not self.phase_deadline_violation_observed
            or self.phase_sequence is None
            or self.rejected_phase_sequence <= self.phase_sequence
        ):
            raise ValueError("rejected watchdog phase identity differs")
        return self


class ProductionLaunchIntent(ContractModel):
    schema_id: Literal["phase-latency-prewarm-launch-intent-v1"]
    attempt_id: str
    retained_at_utc: datetime
    controller: ControllerProcessIdentity
    absolute_deadline_monotonic_ns: Annotated[int, Field(strict=True, gt=0)]
    worker_command_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    worker_environment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    broker_command_template_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    broker_environment_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    capability_scope_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    capability_nonce_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    managed_group_policy: Literal[
        "direct-worker-default-off-v1",
        "fork-denied-worker-plus-tesseract-broker-v1",
    ] = "direct-worker-default-off-v1"
    release_policy: Literal[
        "o-excl-intent-then-watchdog-ready-then-one-byte-release-v1"
    ] = "o-excl-intent-then-watchdog-ready-then-one-byte-release-v1"
    watchdog_policy: Literal[
        "separate-session-exact-identity-absolute-deadline-term-kill-v1"
    ] = "separate-session-exact-identity-absolute-deadline-term-kill-v1"
    intent_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_intent(self) -> "ProductionLaunchIntent":
        if self.retained_at_utc.tzinfo is None or (
            self.retained_at_utc.utcoffset() != timedelta(0)
        ):
            raise ValueError("launch intent timestamp must be UTC")
        broker_fields = (
            self.broker_command_template_sha256,
            self.broker_environment_sha256,
            self.capability_scope_sha256,
            self.capability_nonce_sha256,
        )
        if (self.managed_group_policy.endswith("broker-v1")) != all(
            value is not None for value in broker_fields
        ):
            raise ValueError("launch intent broker capability differs")
        if any(value is not None for value in broker_fields) != all(
            value is not None for value in broker_fields
        ):
            raise ValueError("launch intent broker binding is incomplete")
        fields = self.model_dump(mode="json", exclude={"intent_sha256"})
        if self.intent_sha256 != _canonical_sha256(fields):
            raise ValueError("launch intent identity differs")
        return self


class ProductionLaunchRecord(ContractModel):
    schema_id: Literal["phase-latency-prewarm-launch-record-v1"]
    attempt_id: str
    intent_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retained_before_release_monotonic_ns: Annotated[
        int, Field(strict=True, gt=0)
    ]
    worker: ControllerProcessIdentity
    broker: ControllerProcessIdentity | None = None
    watchdog: ControllerProcessIdentity
    watchdog_ready_mode: Literal[384] = 0o600
    watchdog_terminal_filename: str
    broker_ready_filename: str | None = None
    broker_ready_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    supervisor_ready_filename: str | None = None
    supervisor_ready_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    broker_config_filename: str | None = None
    broker_config_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    released_worker_command_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    released_worker_environment_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    broker_command_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    broker_environment_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    startup_phase_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    startup_phase_ack_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    startup_phase_deadline_acknowledged: Literal[True] = True
    release_token_sha256: Literal[
        "4bf5122f344554c53bde2ebb8cd2b7e3d1600ad631c385a5d7cce23c7785459a"
    ] = "4bf5122f344554c53bde2ebb8cd2b7e3d1600ad631c385a5d7cce23c7785459a"
    release_authorized: Literal[True] = True
    watchdog_excluded_from_worker_request_tree: Literal[True] = True
    launch_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_launch(self) -> "ProductionLaunchRecord":
        if self.worker.pid != self.worker.process_group_id or (
            self.worker.pid != self.worker.session_id
        ):
            raise ValueError("worker launch identity lacks a fresh session")
        if self.watchdog.pid != self.watchdog.process_group_id or (
            self.watchdog.pid != self.watchdog.session_id
        ):
            raise ValueError("watchdog launch identity lacks a fresh session")
        if self.worker.process_group_id == self.watchdog.process_group_id:
            raise ValueError("worker and watchdog groups must be distinct")
        broker_fields = (
            self.broker_ready_filename,
            self.broker_ready_sha256,
            self.supervisor_ready_filename,
            self.supervisor_ready_sha256,
            self.broker_config_filename,
            self.broker_config_sha256,
            self.broker_command_sha256,
            self.broker_environment_sha256,
        )
        if self.broker is None:
            if any(value is not None for value in broker_fields):
                raise ValueError("brokerless launch retained broker evidence")
        elif (
            self.broker.pid != self.broker.process_group_id
            or self.broker.pid != self.broker.session_id
            or self.broker.process_group_id
            in {
                self.worker.process_group_id,
                self.watchdog.process_group_id,
            }
            or not all(value is not None for value in broker_fields)
        ):
            raise ValueError("broker launch identity/custody differs")
        fields = self.model_dump(mode="json", exclude={"launch_sha256"})
        if self.launch_sha256 != _canonical_sha256(fields):
            raise ValueError("launch record identity differs")
        return self


class ProductionLaunchFailureRecord(ContractModel):
    schema_id: Literal["phase-latency-prewarm-launch-failure-v1"]
    attempt_id: str
    intent_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retained_monotonic_ns: Annotated[int, Field(strict=True, gt=0)]
    controller: ControllerProcessIdentity
    worker_started: StrictBool
    broker_started: StrictBool = False
    watchdog_started: StrictBool
    launch_record_retained: StrictBool
    error_type_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_failure(self) -> "ProductionLaunchFailureRecord":
        fields = self.model_dump(mode="json", exclude={"record_sha256"})
        if self.record_sha256 != _canonical_sha256(fields):
            raise ValueError("launch failure record identity differs")
        return self


class ProductionCampaignPlan(ContractModel):
    schema_id: Literal["phase-latency-prewarm-production-plan-v1"]
    generated_at_utc: datetime
    corpus_registry: ArtifactIdentity
    llama_reference: ArtifactIdentity
    sources: Annotated[tuple[SourceIdentity, ...], Field(min_length=15, max_length=15)]
    repetitions: Annotated[int, Field(strict=True, ge=2, le=16)]
    requests_per_attempt: Annotated[int, Field(strict=True, ge=4, le=32)]
    execution: ExecutionIdentity
    artifact_materialization: "RuntimeArtifactMaterialization"
    pairing_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    attempt_order: Literal[
        "case_then_repetition_then_predecessor_then_enabled"
    ] = "case_then_repetition_then_predecessor_then_enabled"
    production_asgi_lifespan_required: Literal[True] = True
    immutable_pre_release_launch_ledger_required: Literal[True] = True
    kernel_hard_controller_watchdog_required: Literal[True] = True
    watchdog_excluded_from_worker_request_metrics: Literal[True] = True
    controller_signal_group_cleanup_required: Literal[True] = True
    external_phase_deadline_ack_required: Literal[True] = True
    cross_input_sequence: Literal[
        "insurance-acord->clean-energy->insurance-acord"
    ] = "insurance-acord->clean-energy->insurance-acord"
    hosted_campaign_invoked: Literal[False] = False
    hosted_calls: Literal[0] = 0
    egress_bytes: Literal[0] = 0
    r34_configuration_comparable: Literal[False] = False
    r34_exact_output_identity_claimed: Literal[False] = False
    r34_artifact_scope_disposition: Literal[
        "pending_approved_combined_tree_full_15_output_gate"
    ] = "pending_approved_combined_tree_full_15_output_gate"

    @model_validator(mode="after")
    def validate_plan(self) -> "ProductionCampaignPlan":
        if tuple(item.case_id for item in self.sources) != PRODUCTION_CASE_IDS:
            raise ValueError("production plan must retain all 15 cases in order")
        return self


class LauncherTerminalEvidence(ContractModel):
    """Closed replayable custody for watchdog-owned root launch and wait4."""

    schema_id: Literal["phase-latency-launcher-terminal-evidence-v1"] = (
        "phase-latency-launcher-terminal-evidence-v1"
    )
    attempt_id: Annotated[str, Field(min_length=1, max_length=128)]
    raw_log_canonical_jsonl: Annotated[
        str, Field(min_length=1, max_length=1_048_576)
    ]
    log_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    log_size_bytes: Annotated[int, Field(strict=True, gt=0, le=1_048_576)]
    log_row_count: Annotated[int, Field(strict=True, gt=0, le=4_096)]
    log_device: Annotated[int, Field(strict=True, ge=0)]
    log_inode: Annotated[int, Field(strict=True, gt=0)]
    log_mode: Literal[384] = 0o600
    log_uid: Annotated[int, Field(strict=True, ge=0)]
    log_nlink: Literal[1] = 1
    controller: ControllerProcessIdentity
    controller_start_abstime: Annotated[int, Field(strict=True, gt=0)]
    launcher: TrustedLauncherIdentity
    worker_root: LauncherOwnedRootIdentity
    broker_root: LauncherOwnedRootIdentity | None = None
    watchdog_result_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    terminal_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    root_returncodes: dict[str, int]
    root_wait4_record_sha256s: dict[str, str]
    root_wait4_log_row_sha256s: dict[str, str]
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_launcher_terminal(self) -> "LauncherTerminalEvidence":
        try:
            raw = self.raw_log_canonical_jsonl.encode("utf-8", errors="strict")
        except UnicodeEncodeError as error:
            raise ValueError("launcher terminal log is not UTF-8") from error
        expected_roots = (
            {"worker": self.worker_root}
            if self.broker_root is None
            else {"broker": self.broker_root, "worker": self.worker_root}
        )
        observed = _validate_watchdog_launcher_terminal_log(
            raw_log=raw,
            attempt_id=self.attempt_id,
            expected_roots=expected_roots,
            expected_watchdog_result_record_sha256=(
                self.watchdog_result_record_sha256
            ),
        )
        roles = set(expected_roots)
        if (
            self.log_sha256 != hashlib.sha256(raw).hexdigest()
            or self.log_size_bytes != len(raw)
            or self.log_row_count != observed["row_count"]
            or self.terminal_record_sha256
            != observed["terminal_record_sha256"]
            or self.root_returncodes != observed["root_returncodes"]
            or self.root_wait4_record_sha256s
            != observed["root_wait4_record_sha256s"]
            or self.root_wait4_log_row_sha256s
            != observed["root_wait4_log_row_sha256s"]
            or self.controller != observed["controller"]
            or self.controller_start_abstime
            != observed["controller_start_abstime"]
            or self.launcher != observed["launcher"]
            or set(self.root_returncodes) != roles
            or set(self.root_wait4_record_sha256s) != roles
            or set(self.root_wait4_log_row_sha256s) != roles
            or any(
                type(value) is not str
                or re.fullmatch(r"[0-9a-f]{64}", value) is None
                for values in (
                    self.root_wait4_record_sha256s,
                    self.root_wait4_log_row_sha256s,
                )
                for value in values.values()
            )
            or self.record_sha256
            != _canonical_sha256(
                self.model_dump(mode="json", exclude={"record_sha256"})
            )
        ):
            raise ValueError("launcher terminal evidence differs")
        return self


def _launcher_terminal_evidence(**fields: object) -> LauncherTerminalEvidence:
    if "record_sha256" in fields:
        raise ValueError("launcher terminal evidence identity is derived")
    provisional = LauncherTerminalEvidence.model_construct(
        **fields, record_sha256="0" * 64
    )
    return LauncherTerminalEvidence(
        **fields,
        record_sha256=_canonical_sha256(
            provisional.model_dump(mode="json", exclude={"record_sha256"})
        ),
    )


def _launcher_terminal_matches_fork_denial(
    launcher: LauncherTerminalEvidence,
    fork_denial: Any,
) -> bool:
    worker = fork_denial.worker
    broker = fork_denial.broker
    return bool(
        launcher.controller.pid == fork_denial.controller_pid
        and launcher.controller_start_abstime
        == fork_denial.controller_start_abstime
        and launcher.launcher == fork_denial.launcher
        and (
            launcher.worker_root.pid,
            launcher.worker_root.start_abstime,
            launcher.worker_root.ppid,
            launcher.worker_root.pgid,
            launcher.worker_root.sid,
        )
        == (
            worker.pid,
            worker.start_abstime,
            worker.parent_pid,
            worker.process_group_id,
            worker.session_id,
        )
        and launcher.worker_root.uid == fork_denial.real_uid
        and launcher.worker_root.euid == fork_denial.effective_uid
        and launcher.broker_root is not None
        and (
            launcher.broker_root.pid,
            launcher.broker_root.start_abstime,
            launcher.broker_root.ppid,
            launcher.broker_root.pgid,
            launcher.broker_root.sid,
        )
        == (
            broker.pid,
            broker.start_abstime,
            broker.parent_pid,
            broker.process_group_id,
            broker.session_id,
        )
        and launcher.broker_root.uid == fork_denial.broker_real_uid
        and launcher.broker_root.euid == fork_denial.broker_effective_uid
    )


def _launcher_terminal_matches_watchdog(
    launcher: LauncherTerminalEvidence,
    terminal: ProductionWatchdogTerminalEvidence,
) -> bool:
    return (
        launcher.controller.pid,
        launcher.controller_start_abstime,
        launcher.controller.create_time_ns,
        launcher.controller.process_group_id,
        launcher.controller.session_id,
    ) == (
        terminal.controller_pid,
        terminal.controller_start_abstime,
        terminal.controller_create_time_ns,
        terminal.controller_pgid,
        terminal.controller_sid,
    )


class ProductionAttemptReceipt(ContractModel):
    schema_id: Literal["phase-latency-prewarm-attempt-receipt-v1"]
    attempt_id: str
    source: SourceIdentity
    execution: ExecutionIdentity
    configuration: ConfigurationIdentity
    started_at_utc: datetime
    completed_at_utc: datetime
    controller_elapsed_ns: Annotated[int, Field(strict=True, ge=0)]
    worker_process_group_count: Literal[1] = 1
    broker_process_group_count: Literal[0, 1] = 0
    worker_return_code: int
    broker_return_code: int | None = None
    stdout_size_bytes: Annotated[int, Field(strict=True, ge=0)]
    stdout_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stderr_size_bytes: Annotated[int, Field(strict=True, ge=0)]
    stderr_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    worker_stream_capture_disposition: Literal[
        "complete",
        "bounded_observed_prefix_overflow",
        "incomplete_observed_prefix_forced_close",
    ]
    worker_combined_output_limit_bytes: Literal[4_194_304] = 4_194_304
    broker_stdout_size_bytes: Annotated[int, Field(strict=True, ge=0)] = 0
    broker_stdout_sha256: str = Field(
        default=hashlib.sha256(b"").hexdigest(), pattern=r"^[0-9a-f]{64}$"
    )
    broker_stderr_size_bytes: Annotated[int, Field(strict=True, ge=0)] = 0
    broker_stderr_sha256: str = Field(
        default=hashlib.sha256(b"").hexdigest(), pattern=r"^[0-9a-f]{64}$"
    )
    broker_stream_capture_disposition: Literal[
        "not_applicable",
        "complete",
        "bounded_observed_prefix_overflow",
        "incomplete_observed_prefix_forced_close",
    ] = "not_applicable"
    broker_reaped: StrictBool = False
    broker_process_group_gone: StrictBool = False
    forced_group_cleanup_required: StrictBool
    all_group_members_gone: StrictBool
    controller_resources: ControllerResourceBoundary
    launch_intent_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    launch_record_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    launch_failure_record_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    phase_deadline_log_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    phase_ack_log_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    phase_sequence_count: Annotated[int, Field(strict=True, ge=0)]
    watchdog_terminal_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    watchdog_terminal_observed_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    watchdog_terminal_validation_failed: StrictBool = False
    watchdog_terminal: ProductionWatchdogTerminalEvidence | None = None
    launcher_terminal_evidence: LauncherTerminalEvidence | None = None
    terminal_request_control_transcript: (
        TerminalRequestControlTranscriptEvidence | None
    ) = None
    immutable_input_custody: ImmutableRuntimeInputCustodyEvidence | None = None
    immutable_input_custody_validation_failed: StrictBool = False
    watchdog_reaped: StrictBool
    watchdog_process_group_gone: StrictBool
    watchdog_excluded_from_worker_request_tree: Literal[True] = True
    prebind_fatal_record_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    prebind_fatal_record_validation_failed: StrictBool = False
    status: AttemptStatus
    failure: FailureRecord | None
    attempt: LocalPrewarmAttempt | None
    hosted_calls: Literal[0] = 0
    egress_bytes: Literal[0] = 0

    @model_validator(mode="after")
    def validate_receipt(self) -> "ProductionAttemptReceipt":
        broker_required = self.configuration.execution_topology == (
            "fork-denied-worker-external-tesseract-broker-v1"
        )
        if (self.watchdog_terminal is None) != (
            self.watchdog_terminal_sha256 is None
        ):
            raise ValueError("watchdog terminal identity is incomplete")
        if self.watchdog_terminal is not None and self.watchdog_terminal_sha256 != (
            hashlib.sha256(canonical_model_bytes(self.watchdog_terminal)).hexdigest()
        ):
            raise ValueError("watchdog terminal hash differs")
        if self.attempt is not None and not (
            self.attempt_id == self.attempt.attempt_id
            and self.source == self.attempt.source
            and self.execution == self.attempt.execution
            and self.configuration == self.attempt.configuration
            and self.started_at_utc == self.attempt.started_at_utc
            and self.completed_at_utc == self.attempt.completed_at_utc
            and self.status is self.attempt.status
            and self.failure == self.attempt.failure
        ):
            raise ValueError("receipt fields differ from its embedded attempt")
        if self.status is AttemptStatus.SUCCESS:
            if (
                (
                    broker_required
                    and (
                        self.broker_process_group_count != 1
                        or self.broker_return_code != 0
                        or not self.broker_reaped
                        or not self.broker_process_group_gone
                        or self.broker_stream_capture_disposition != "complete"
                    )
                )
                or (
                    not broker_required
                    and (
                        self.broker_process_group_count != 0
                        or self.broker_return_code is not None
                        or self.broker_stream_capture_disposition
                        != "not_applicable"
                    )
                )
                or self.attempt is None
                or self.failure is not None
                or self.worker_return_code != 0
                or self.forced_group_cleanup_required
                or not self.all_group_members_gone
                or not self.controller_resources.threads_returned_to_baseline
                or not self.controller_resources.file_descriptors_returned_to_baseline
                or self.launch_record_sha256 is None
                or self.launch_failure_record_sha256 is not None
                or self.phase_deadline_log_sha256 is None
                or self.phase_ack_log_sha256 is None
                or self.phase_sequence_count
                != int(self.configuration.request_count or 0) + 2
                or self.watchdog_terminal_sha256 is None
                or self.watchdog_terminal is None
                or self.watchdog_terminal_observed_sha256
                != self.watchdog_terminal_sha256
                or self.watchdog_terminal_validation_failed
                or self.watchdog_terminal.outcome != "worker_exited"
                or self.launcher_terminal_evidence is None
                or self.terminal_request_control_transcript is None
                or self.terminal_request_control_transcript
                != self.attempt.worker.terminal_request_control_transcript
                or self.launcher_terminal_evidence.attempt_id != self.attempt_id
                or self.launcher_terminal_evidence.watchdog_result_record_sha256
                != hashlib.sha256(
                    canonical_model_bytes(self.watchdog_terminal)[:-1]
                ).hexdigest()
                or not _launcher_terminal_matches_watchdog(
                    self.launcher_terminal_evidence,
                    self.watchdog_terminal,
                )
                or self.attempt.worker.fork_denial_evidence is None
                or not _launcher_terminal_matches_fork_denial(
                    self.launcher_terminal_evidence,
                    self.attempt.worker.fork_denial_evidence,
                )
                or self.watchdog_terminal.phase_sequence
                != self.phase_sequence_count
                or not self.watchdog_reaped
                or not self.watchdog_process_group_gone
                or self.prebind_fatal_record_sha256 is not None
                or self.prebind_fatal_record_validation_failed
                or self.worker_stream_capture_disposition != "complete"
                or (
                    broker_required
                    and (
                        self.immutable_input_custody is None
                        or self.immutable_input_custody.attempt_id
                        != self.attempt_id
                        or self.immutable_input_custody_validation_failed
                    )
                )
                or (
                    not broker_required
                    and self.immutable_input_custody is not None
                )
            ):
                raise ValueError("successful production receipt is incomplete")
        elif self.failure is None:
            raise ValueError("failed production receipt must retain a failure")
        elif self.attempt is not None and self.attempt.status is AttemptStatus.SUCCESS:
            raise ValueError("failed receipt cannot embed a successful attempt")
        return self


class DirectRollbackAttemptReceipt(ContractModel):
    """Closed controller receipt for one brokerless rollback observation."""

    schema_id: Literal["phase-latency-direct-rollback-attempt-receipt-v1"] = (
        "phase-latency-direct-rollback-attempt-receipt-v1"
    )
    attempt_id: str
    source: SourceIdentity
    execution: ExecutionIdentity
    configuration: ConfigurationIdentity
    started_at_utc: datetime
    completed_at_utc: datetime
    controller_elapsed_ns: Annotated[int, Field(strict=True, ge=0)]
    worker_return_code: Literal[0] = 0
    stdout_size_bytes: Annotated[int, Field(strict=True, gt=0)]
    stdout_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stderr_size_bytes: Literal[0] = 0
    stderr_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    launch_intent_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    launch_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    phase_deadline_log_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    phase_ack_log_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    phase_sequence_count: Literal[3] = 3
    watchdog_terminal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    watchdog_terminal_observed_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    watchdog_terminal: ProductionWatchdogTerminalEvidence
    launcher_terminal_evidence: LauncherTerminalEvidence | None = None
    terminal_request_control_transcript: Literal[None] = None
    immutable_input_custody: Literal[None] = None
    immutable_input_custody_validation_failed: Literal[False] = False
    watchdog_reaped: Literal[True] = True
    watchdog_process_group_gone: Literal[True] = True
    worker_reaped: Literal[True] = True
    worker_process_group_gone: Literal[True] = True
    forced_group_cleanup_required: Literal[False] = False
    controller_resources: ControllerResourceBoundary
    raw_worker: DirectRollbackRawWorkerEnvelope
    status: Literal[AttemptStatus.SUCCESS] = AttemptStatus.SUCCESS
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_direct_receipt(self) -> "DirectRollbackAttemptReceipt":
        if (
            self.attempt_id != self.raw_worker.attempt_id
            or self.source != self.raw_worker.source
            or self.configuration.sha256 != self.raw_worker.configuration_sha256
            or self.configuration.measurement_kind != "rollback_output_gate"
            or self.configuration.execution_topology != "direct-default-off-v1"
            or self.stdout_size_bytes
            != len(canonical_model_bytes(self.raw_worker))
            or self.stdout_sha256
            != hashlib.sha256(canonical_model_bytes(self.raw_worker)).hexdigest()
            or self.stderr_sha256 != hashlib.sha256(b"").hexdigest()
            or self.watchdog_terminal_sha256
            != hashlib.sha256(canonical_model_bytes(self.watchdog_terminal)).hexdigest()
            or self.watchdog_terminal_observed_sha256
            != self.watchdog_terminal_sha256
            or self.watchdog_terminal.outcome != "worker_exited"
            or self.launcher_terminal_evidence is None
            or self.launcher_terminal_evidence.attempt_id != self.attempt_id
            or self.launcher_terminal_evidence.watchdog_result_record_sha256
            != hashlib.sha256(
                canonical_model_bytes(self.watchdog_terminal)[:-1]
            ).hexdigest()
            or not _launcher_terminal_matches_watchdog(
                self.launcher_terminal_evidence,
                self.watchdog_terminal,
            )
            or self.launcher_terminal_evidence.broker_root is not None
            or (
                self.launcher_terminal_evidence.worker_root.pid,
                self.launcher_terminal_evidence.worker_root.create_time_ns,
                self.launcher_terminal_evidence.worker_root.pgid,
                self.launcher_terminal_evidence.worker_root.sid,
            )
            != (
                self.watchdog_terminal.worker_pid,
                self.watchdog_terminal.worker_create_time_ns,
                self.watchdog_terminal.worker_pgid,
                self.watchdog_terminal.worker_sid,
            )
            or self.watchdog_terminal.phase_sequence != 3
            or not self.controller_resources.threads_returned_to_baseline
            or not self.controller_resources.file_descriptors_returned_to_baseline
            or self.record_sha256
            != _canonical_sha256(
                self.model_dump(mode="json", exclude={"record_sha256"})
            )
        ):
            raise ValueError("direct rollback receipt custody differs")
        return self


def _direct_rollback_attempt_receipt(
    **fields: object,
) -> DirectRollbackAttemptReceipt:
    provisional = DirectRollbackAttemptReceipt.model_construct(
        **fields, record_sha256="0" * 64
    )
    return DirectRollbackAttemptReceipt(
        **fields,
        record_sha256=_canonical_sha256(
            provisional.model_dump(mode="json", exclude={"record_sha256"})
        ),
    )


class DirectRollbackFailureReceipt(ContractModel):
    """Fail-closed receipt for a direct rollback attempt that did not complete."""

    schema_id: Literal["phase-latency-direct-rollback-failure-receipt-v1"] = (
        "phase-latency-direct-rollback-failure-receipt-v1"
    )
    attempt_id: str
    source: SourceIdentity
    execution: ExecutionIdentity
    configuration: ConfigurationIdentity
    started_at_utc: datetime
    completed_at_utc: datetime
    controller_elapsed_ns: Annotated[int, Field(strict=True, ge=0)]
    worker_return_code: int | None
    stdout_size_bytes: Annotated[int, Field(strict=True, ge=0)]
    stdout_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stderr_size_bytes: Annotated[int, Field(strict=True, ge=0)]
    stderr_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    launch_intent_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    launch_record_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    phase_deadline_log_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    phase_ack_log_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    watchdog_terminal_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    watchdog_terminal: ProductionWatchdogTerminalEvidence | None = None
    launcher_terminal_evidence: LauncherTerminalEvidence | None = None
    cleanup_attempted: Literal[True] = True
    worker_process_group_gone: StrictBool
    watchdog_reaped: StrictBool
    watchdog_process_group_gone: StrictBool
    controller_resources: ControllerResourceBoundary | None = None
    controller_resources_validation_failed: StrictBool
    status: Literal[AttemptStatus.ERROR] = AttemptStatus.ERROR
    failure: FailureRecord
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_failure_receipt(self) -> "DirectRollbackFailureReceipt":
        if (
            self.configuration.measurement_kind != "rollback_output_gate"
            or self.configuration.execution_topology != "direct-default-off-v1"
            or (self.watchdog_terminal is None)
            != (self.watchdog_terminal_sha256 is None)
            or (
                self.watchdog_terminal is not None
                and self.watchdog_terminal_sha256
                != hashlib.sha256(
                    canonical_model_bytes(self.watchdog_terminal)
                ).hexdigest()
            )
            or (self.controller_resources is None)
            == (not self.controller_resources_validation_failed)
            or self.record_sha256
            != _canonical_sha256(
                self.model_dump(mode="json", exclude={"record_sha256"})
            )
        ):
            raise ValueError("direct rollback failure receipt custody differs")
        return self


def _direct_rollback_failure_receipt(
    **fields: object,
) -> DirectRollbackFailureReceipt:
    provisional = DirectRollbackFailureReceipt.model_construct(
        **fields, record_sha256="0" * 64
    )
    return DirectRollbackFailureReceipt(
        **fields,
        record_sha256=_canonical_sha256(
            provisional.model_dump(mode="json", exclude={"record_sha256"})
        ),
    )


class CrossInputControlReceipt(ContractModel):
    schema_id: Literal["phase-latency-prewarm-cross-input-receipt-v1"]
    control_id: Literal["lat-us02-cross-input-isolation"] = (
        "lat-us02-cross-input-isolation"
    )
    started_at_utc: datetime
    completed_at_utc: datetime
    controller_elapsed_ns: Annotated[int, Field(strict=True, ge=0)]
    worker_return_code: int
    broker_process_group_count: Literal[0, 1] = 0
    broker_return_code: int | None = None
    stdout_size_bytes: Annotated[int, Field(strict=True, ge=0)]
    stdout_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stderr_size_bytes: Annotated[int, Field(strict=True, ge=0)]
    stderr_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    worker_stream_capture_disposition: Literal[
        "complete",
        "bounded_observed_prefix_overflow",
        "incomplete_observed_prefix_forced_close",
    ]
    worker_combined_output_limit_bytes: Literal[4_194_304] = 4_194_304
    broker_stdout_size_bytes: Annotated[int, Field(strict=True, ge=0)]
    broker_stdout_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    broker_stderr_size_bytes: Annotated[int, Field(strict=True, ge=0)]
    broker_stderr_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    broker_stream_capture_disposition: Literal[
        "not_applicable",
        "complete",
        "bounded_observed_prefix_overflow",
        "incomplete_observed_prefix_forced_close",
    ]
    broker_reaped: StrictBool
    broker_process_group_gone: StrictBool
    forced_group_cleanup_required: StrictBool
    all_group_members_gone: StrictBool
    controller_resources: ControllerResourceBoundary
    launch_intent_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    launch_record_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    launch_failure_record_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    phase_deadline_log_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    phase_ack_log_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    phase_sequence_count: Annotated[int, Field(strict=True, ge=0)]
    watchdog_terminal_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    watchdog_terminal_observed_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    watchdog_terminal_validation_failed: StrictBool = False
    watchdog_terminal: ProductionWatchdogTerminalEvidence | None = None
    launcher_terminal_evidence: LauncherTerminalEvidence | None = None
    terminal_request_control_transcript: (
        TerminalRequestControlTranscriptEvidence | None
    ) = None
    immutable_input_custody: ImmutableRuntimeInputCustodyEvidence | None = None
    immutable_input_custody_validation_failed: StrictBool = False
    watchdog_reaped: StrictBool
    watchdog_process_group_gone: StrictBool
    watchdog_excluded_from_worker_request_tree: Literal[True] = True
    prebind_fatal_record_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    prebind_fatal_record_validation_failed: StrictBool = False
    status: AttemptStatus
    failure: FailureRecord | None
    evidence: CrossInputIsolationEvidence | None

    @model_validator(mode="after")
    def validate_control_receipt(self) -> "CrossInputControlReceipt":
        if (self.watchdog_terminal is None) != (
            self.watchdog_terminal_sha256 is None
        ):
            raise ValueError("cross-input watchdog terminal identity is incomplete")
        if self.watchdog_terminal is not None and self.watchdog_terminal_sha256 != (
            hashlib.sha256(canonical_model_bytes(self.watchdog_terminal)).hexdigest()
        ):
            raise ValueError("cross-input watchdog terminal hash differs")
        if self.status is AttemptStatus.SUCCESS:
            if (
                self.evidence is None
                or self.broker_process_group_count != 1
                or self.failure is not None
                or self.worker_return_code != 0
                or self.broker_return_code != 0
                or not self.broker_reaped
                or not self.broker_process_group_gone
                or self.broker_stream_capture_disposition != "complete"
                or self.forced_group_cleanup_required
                or not self.all_group_members_gone
                or not self.controller_resources.threads_returned_to_baseline
                or not self.controller_resources.file_descriptors_returned_to_baseline
                or self.launch_record_sha256 is None
                or self.launch_failure_record_sha256 is not None
                or self.phase_deadline_log_sha256 is None
                or self.phase_ack_log_sha256 is None
                or self.phase_sequence_count != 5
                or self.watchdog_terminal_sha256 is None
                or self.watchdog_terminal is None
                or self.watchdog_terminal_observed_sha256
                != self.watchdog_terminal_sha256
                or self.watchdog_terminal_validation_failed
                or self.watchdog_terminal.outcome != "worker_exited"
                or self.launcher_terminal_evidence is None
                or self.terminal_request_control_transcript is None
                or self.terminal_request_control_transcript
                != self.evidence.terminal_request_control_transcript
                or self.launcher_terminal_evidence.attempt_id != self.control_id
                or self.launcher_terminal_evidence.watchdog_result_record_sha256
                != hashlib.sha256(
                    canonical_model_bytes(self.watchdog_terminal)[:-1]
                ).hexdigest()
                or not _launcher_terminal_matches_watchdog(
                    self.launcher_terminal_evidence,
                    self.watchdog_terminal,
                )
                or not _launcher_terminal_matches_fork_denial(
                    self.launcher_terminal_evidence,
                    self.evidence.fork_denial_evidence,
                )
                or self.watchdog_terminal.phase_sequence
                != self.phase_sequence_count
                or not self.watchdog_reaped
                or not self.watchdog_process_group_gone
                or self.prebind_fatal_record_sha256 is not None
                or self.prebind_fatal_record_validation_failed
                or self.worker_stream_capture_disposition != "complete"
                or self.immutable_input_custody is None
                or self.immutable_input_custody.attempt_id != self.control_id
                or self.immutable_input_custody_validation_failed
            ):
                raise ValueError("successful cross-input receipt is incomplete")
        elif self.failure is None or self.evidence is not None:
            raise ValueError("failed cross-input receipt is inconsistent")
        return self


class RuntimeArtifactSourceIdentity(ContractModel):
    source_id: str
    source_role: Literal[
        "base_docling_model_tree", "optional_classifier_snapshot"
    ]
    portable_label: str
    snapshot_revision: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")] | None
    resolved_path: str
    resolved_path_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_count: Annotated[int, Field(strict=True, gt=0)]
    aggregate_bytes: Annotated[int, Field(strict=True, gt=0)]

    @model_validator(mode="after")
    def validate_source_identity(self) -> "RuntimeArtifactSourceIdentity":
        path = Path(self.resolved_path)
        if (
            not path.is_absolute()
            or "\x00" in self.resolved_path
            or "\n" in self.resolved_path
            or len(self.resolved_path) > 4_096
            or ".." in path.parts
        ):
            raise ValueError("materialization source path must be bounded and absolute")
        if self.resolved_path_identity_sha256 != _canonical_sha256(
            {"resolved_path": self.resolved_path}
        ):
            raise ValueError("materialization source path identity differs")
        if self.source_role == "base_docling_model_tree":
            if self.snapshot_revision is not None:
                raise ValueError("base model source cannot declare a snapshot revision")
        elif self.snapshot_revision is None:
            raise ValueError("classifier source must declare its snapshot revision")
        return self


class RuntimeArtifactMaterialization(ContractModel):
    schema_id: Literal["phase-latency-prewarm-artifact-materialization-v1"]
    target: ArtifactIdentity
    target_resolved_runtime_path: str
    target_resolved_path_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_content_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_metadata_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_file_count: Annotated[int, Field(strict=True, gt=0)]
    target_aggregate_bytes: Annotated[int, Field(strict=True, gt=0)]
    target_directory_mode: Literal[448]
    target_owned_by_current_uid: Literal[True]
    target_before_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_after_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_before_content_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_after_content_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_before_metadata_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_after_metadata_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_before_file_count: Annotated[int, Field(strict=True, gt=0)]
    target_after_file_count: Annotated[int, Field(strict=True, gt=0)]
    target_before_aggregate_bytes: Annotated[int, Field(strict=True, gt=0)]
    target_after_aggregate_bytes: Annotated[int, Field(strict=True, gt=0)]
    sources: Annotated[
        tuple[RuntimeArtifactSourceIdentity, ...], Field(min_length=2, max_length=2)
    ]
    source_union_equals_target: Literal[True]
    symlinks_in_target: Literal[False]
    before_after_identity_unchanged: Literal[True]
    no_write_observed: Literal[True]
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_manifest(self) -> "RuntimeArtifactMaterialization":
        path = Path(self.target_resolved_runtime_path)
        if (
            not path.is_absolute()
            or "\x00" in self.target_resolved_runtime_path
            or "\n" in self.target_resolved_runtime_path
            or len(self.target_resolved_runtime_path) > 4_096
            or ".." in path.parts
        ):
            raise ValueError("materialization target path must be bounded and absolute")
        if self.target_resolved_path_identity_sha256 != _canonical_sha256(
            {"resolved_path": self.target_resolved_runtime_path}
        ):
            raise ValueError("materialization target path identity differs")
        if not (
            self.target_before_artifact_sha256
            == self.target_after_artifact_sha256
            == self.target.sha256
            == self.target_before_content_manifest_sha256
            == self.target_after_content_manifest_sha256
            == self.target_content_manifest_sha256
            and self.target_before_metadata_sha256
            == self.target_after_metadata_sha256
            == self.target_metadata_sha256
            and self.target_before_file_count
            == self.target_after_file_count
            == self.target_file_count
            and self.target_before_aggregate_bytes
            == self.target_after_aggregate_bytes
            == self.target_aggregate_bytes
            == self.target.size_bytes
        ):
            raise ValueError("materialization target changed between observations")
        fields = self.model_dump(mode="json", exclude={"manifest_sha256"})
        if self.manifest_sha256 != _canonical_sha256(fields):
            raise ValueError("artifact materialization manifest identity differs")
        return self


class PostAttemptArtifactObservation(ContractModel):
    schema_id: Literal["phase-latency-prewarm-post-attempt-artifact-v1"]
    attempt_id: str
    observed_at_utc: datetime
    preflight_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_resolved_runtime_path: str
    target_resolved_path_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_artifact_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    observed_content_manifest_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    observed_metadata_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    observed_file_count: Annotated[int, Field(strict=True, gt=0)] | None = None
    observed_aggregate_bytes: Annotated[int, Field(strict=True, gt=0)] | None = None
    observed_directory_mode: Annotated[int, Field(strict=True, ge=0)] | None = None
    observed_owned_by_current_uid: StrictBool | None = None
    observed_symlinks_in_target: StrictBool | None = None
    status: Literal["matched", "mismatch", "observation_error"]
    matches_preflight: StrictBool
    failure_detail_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_observation(self) -> "PostAttemptArtifactObservation":
        if (
            self.observed_at_utc.tzinfo is None
            or self.observed_at_utc.utcoffset() != timedelta(0)
        ):
            raise ValueError("artifact observation timestamp must be UTC")
        observed = (
            self.observed_artifact_sha256,
            self.observed_content_manifest_sha256,
            self.observed_metadata_sha256,
            self.observed_file_count,
            self.observed_aggregate_bytes,
            self.observed_directory_mode,
            self.observed_owned_by_current_uid,
            self.observed_symlinks_in_target,
        )
        if self.status == "matched":
            if (
                not self.matches_preflight
                or any(value is None for value in observed)
                or self.failure_detail_sha256 is not None
            ):
                raise ValueError("matched artifact observation is incomplete")
        elif self.matches_preflight:
            raise ValueError("non-matching artifact observation cannot claim equality")
        elif self.status == "observation_error" and self.failure_detail_sha256 is None:
            raise ValueError("artifact observation error lacks failure identity")
        fields = self.model_dump(mode="json", exclude={"observation_sha256"})
        if self.observation_sha256 != _canonical_sha256(fields):
            raise ValueError("post-attempt artifact observation identity differs")
        return self


class CampaignClosureEntry(ContractModel):
    relative_path: Annotated[str, Field(min_length=1, max_length=4_096)]
    device: Annotated[int, Field(strict=True, ge=0)]
    inode: Annotated[int, Field(strict=True, gt=0)]
    mode: Literal[384] = 0o600
    uid: Annotated[int, Field(strict=True, ge=0)]
    nlink: Literal[1] = 1
    size_bytes: Annotated[int, Field(strict=True, ge=0)]
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_path(self) -> "CampaignClosureEntry":
        path = Path(self.relative_path)
        if (
            path.is_absolute()
            or self.relative_path != path.as_posix()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
            or self.relative_path == "campaign-closure.json"
        ):
            raise ValueError("campaign closure entry path differs")
        return self


class CampaignClosureOutputRootIdentity(ContractModel):
    resolved_path: Annotated[str, Field(min_length=1, max_length=4_096)]
    device: Annotated[int, Field(strict=True, ge=0)]
    inode: Annotated[int, Field(strict=True, gt=0)]
    mode: Literal[448] = 0o700
    uid: Annotated[int, Field(strict=True, ge=0)]
    nlink: Annotated[int, Field(strict=True, gt=0)]
    descriptor_opened_o_directory: Literal[True] = True
    descriptor_opened_o_nofollow: Literal[True] = True

    @model_validator(mode="after")
    def validate_root(self) -> "CampaignClosureOutputRootIdentity":
        path = Path(self.resolved_path)
        if not path.is_absolute() or path != path.resolve():
            raise ValueError("campaign closure output root differs")
        return self


class CampaignOutputVnodeIdentity(ContractModel):
    relative_path: Annotated[str, Field(min_length=1, max_length=4_096)]
    device: Annotated[int, Field(strict=True, ge=0)]
    inode: Annotated[int, Field(strict=True, gt=0)]
    mode: Annotated[int, Field(strict=True, ge=0)]
    uid: Annotated[int, Field(strict=True, ge=0)]
    nlink: Annotated[int, Field(strict=True, gt=0)]

    @model_validator(mode="after")
    def validate_vnode_path(self) -> "CampaignOutputVnodeIdentity":
        if self.relative_path == ".":
            return self
        path = Path(self.relative_path)
        if (
            path.is_absolute()
            or self.relative_path != path.as_posix()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError("campaign output vnode path differs")
        return self


class CampaignLauncherRootTerminalDisposition(ContractModel):
    role: Literal["broker", "worker"]
    root: LauncherOwnedRootIdentity
    returncode: int
    wait4_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    wait4_log_row_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    group_esrch_after_wait4: Literal[True] = True
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_terminal_root(self) -> "CampaignLauncherRootTerminalDisposition":
        if self.record_sha256 != _canonical_sha256(
            self.model_dump(mode="json", exclude={"record_sha256"})
        ):
            raise ValueError("campaign launcher root disposition differs")
        return self


class CampaignTerminalArtifactBinding(ContractModel):
    relative_path: Annotated[str, Field(min_length=1, max_length=4_096)]
    record_kind: Literal[
        "launch-intent",
        "launch-record",
        "launch-failure",
        "phase-deadlines",
        "phase-acks",
        "watchdog-terminal",
        "launcher-ledger",
        "broker-launch-template",
        "broker-ready",
        "supervisor-ready",
        "child-watch-ledger",
        "request-control-ledger",
        "broker-request-receipt",
        "external-cpu-samples",
        "controller-resource-samples",
        "kernel-sandbox-evidence",
        "native-closure-post-observation",
        "immutable-input-custody",
        "attempt-receipt",
        "cross-input-receipt",
        "artifact-observation",
        "worker-prebind-fatal",
    ]
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: Annotated[int, Field(strict=True, gt=0)]
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_artifact(self) -> "CampaignTerminalArtifactBinding":
        path = Path(self.relative_path)
        if (
            path.is_absolute()
            or self.relative_path != path.as_posix()
            or len(path.parts) != 2
            or path.parts[0] != "terminal"
            or self.record_sha256
            != _canonical_sha256(
                self.model_dump(mode="json", exclude={"record_sha256"})
            )
        ):
            raise ValueError("campaign terminal artifact binding differs")
        return self


class CampaignReceiptTerminalDisposition(ContractModel):
    """One launch intent closed by a typed, launcher-bound attempt receipt."""

    schema_id: Literal["phase-latency-campaign-receipt-disposition-v1"] = (
        "phase-latency-campaign-receipt-disposition-v1"
    )
    disposition: Literal["receipt"] = "receipt"
    attempt_id: Annotated[str, Field(min_length=1, max_length=128)]
    intent: ProductionLaunchIntent
    intent_relative_path: Annotated[str, Field(min_length=1, max_length=4_096)]
    intent_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_relative_path: Annotated[str, Field(min_length=1, max_length=4_096)]
    receipt_schema_id: Literal[
        "phase-latency-prewarm-attempt-receipt-v1",
        "phase-latency-direct-rollback-attempt-receipt-v1",
        "phase-latency-direct-rollback-failure-receipt-v1",
        "phase-latency-prewarm-cross-input-receipt-v1",
    ]
    receipt_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    launcher_ledger_relative_path: Annotated[
        str, Field(min_length=1, max_length=4_096)
    ]
    launcher_ledger_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    launcher_terminal_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    watchdog_terminal_relative_path: Annotated[
        str, Field(min_length=1, max_length=4_096)
    ]
    watchdog_terminal_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    controller: ControllerProcessIdentity
    roots: Annotated[
        tuple[CampaignLauncherRootTerminalDisposition, ...],
        Field(min_length=1, max_length=2),
    ]
    attempt_artifacts: Annotated[
        tuple[CampaignTerminalArtifactBinding, ...],
        Field(min_length=4, max_length=4_096),
    ]
    watchdog_reaped: Literal[True] = True
    watchdog_group_esrch: Literal[True] = True
    all_producer_groups_esrch: Literal[True] = True
    launch_record_relative_path: str | None = None
    launch_record_content_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    launch_record_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    launch_failure_relative_path: str | None = None
    launch_failure_content_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    launch_failure_record_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_receipt_disposition(self) -> "CampaignReceiptTerminalDisposition":
        expected_roles = (
            ("broker", "worker")
            if self.intent.managed_group_policy.endswith("broker-v1")
            else ("worker",)
        )
        root_roles = tuple(item.role for item in self.roots)
        launch_record_fields = (
            self.launch_record_relative_path,
            self.launch_record_content_sha256,
            self.launch_record_sha256,
        )
        launch_failure_fields = (
            self.launch_failure_relative_path,
            self.launch_failure_content_sha256,
            self.launch_failure_record_sha256,
        )
        expected_prefix = f"terminal/{self.attempt_id}"
        allowed_receipts = {
            f"{expected_prefix}.json",
            f"{expected_prefix}-receipt.json",
        }
        artifact_paths = tuple(item.relative_path for item in self.attempt_artifacts)
        artifact_by_kind: dict[str, list[CampaignTerminalArtifactBinding]] = {}
        for artifact in self.attempt_artifacts:
            artifact_by_kind.setdefault(artifact.record_kind, []).append(artifact)
        if (
            self.attempt_id != self.intent.attempt_id
            or self.intent_relative_path
            != f"{expected_prefix}-launch-intent.json"
            or self.receipt_relative_path not in allowed_receipts
            or self.launcher_ledger_relative_path
            != f"{expected_prefix}-watchdog-launcher.jsonl"
            or self.watchdog_terminal_relative_path
            != f"{expected_prefix}-watchdog-terminal.json"
            or self.controller != self.intent.controller
            or root_roles != expected_roles
            or len(set(root_roles)) != len(root_roles)
            or artifact_paths != tuple(sorted(artifact_paths))
            or len(artifact_paths) != len(set(artifact_paths))
            or any(
                path != self.receipt_relative_path
                and not path.startswith(f"{expected_prefix}-")
                for path in artifact_paths
            )
            or artifact_paths
            != tuple(sorted(set(artifact_paths)))
            or self.intent_relative_path not in artifact_paths
            or self.receipt_relative_path not in artifact_paths
            or self.launcher_ledger_relative_path not in artifact_paths
            or self.watchdog_terminal_relative_path not in artifact_paths
            or len(artifact_by_kind.get("launch-intent", ())) != 1
            or len(
                artifact_by_kind.get(
                    "cross-input-receipt"
                    if self.receipt_schema_id
                    == "phase-latency-prewarm-cross-input-receipt-v1"
                    else "attempt-receipt",
                    (),
                )
            )
            != 1
            or len(artifact_by_kind.get("launcher-ledger", ())) != 1
            or len(artifact_by_kind.get("watchdog-terminal", ())) != 1
            or len(artifact_by_kind.get("launch-record", ()))
            != (1 if self.launch_record_relative_path is not None else 0)
            or len(artifact_by_kind.get("launch-failure", ()))
            != (1 if self.launch_failure_relative_path is not None else 0)
            or self.intent_content_sha256
            != hashlib.sha256(canonical_model_bytes(self.intent)).hexdigest()
            or any(value is not None for value in launch_record_fields)
            != all(value is not None for value in launch_record_fields)
            or any(value is not None for value in launch_failure_fields)
            != all(value is not None for value in launch_failure_fields)
            or (
                self.launch_record_relative_path is not None
                and self.launch_record_relative_path
                != f"{expected_prefix}-launch-record.json"
            )
            or (
                self.launch_failure_relative_path is not None
                and self.launch_failure_relative_path
                != f"{expected_prefix}-launch-failure.json"
            )
            or self.record_sha256
            != _canonical_sha256(
                self.model_dump(mode="json", exclude={"record_sha256"})
            )
        ):
            raise ValueError("campaign receipt terminal disposition differs")
        return self


class CampaignFailureQuiescenceEvidence(ContractModel):
    """Controller-only final barrier authorizing a failed campaign closure."""

    schema_id: Literal["phase-latency-campaign-failure-quiescence-v1"] = (
        "phase-latency-campaign-failure-quiescence-v1"
    )
    controller: ControllerProcessIdentity
    barrier_entry_thread_inventory: NativeThreadInventory
    final_file_descriptor_inventory: NativeFileDescriptorInventory
    precommit_thread_inventory: NativeThreadInventory
    termination_signal_numbers: Annotated[
        tuple[int, ...], Field(min_length=2, max_length=2)
    ]
    barrier_signal_mask_before_inventory: tuple[int, ...]
    barrier_signal_mask_before_commit: tuple[int, ...]
    termination_signals_blocked_for_entire_barrier: Literal[True] = True
    controller_sole_thread_for_entire_barrier: Literal[True] = True
    output_prefix_vnodes: Annotated[
        tuple[CampaignOutputVnodeIdentity, ...],
        Field(min_length=2, max_length=4_098),
    ]
    output_prefix_vnodes_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    first_output_prefix_vnodes_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    second_output_prefix_vnodes_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    darwin_vnode_write_access_mask: Literal[2] = 2
    writable_output_prefix_descriptor_fds: tuple[int, ...] = ()
    no_output_prefix_vnode_fd_with_write_access: Literal[True] = True
    first_output_scan_started_monotonic_ns: Annotated[
        int, Field(strict=True, gt=0)
    ]
    first_output_scan_completed_monotonic_ns: Annotated[
        int, Field(strict=True, gt=0)
    ]
    second_output_scan_started_monotonic_ns: Annotated[
        int, Field(strict=True, gt=0)
    ]
    second_output_scan_completed_monotonic_ns: Annotated[
        int, Field(strict=True, gt=0)
    ]
    first_output_scan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    second_output_scan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    exact_double_output_scan: Literal[True] = True
    launch_dispositions: Annotated[
        tuple[CampaignReceiptTerminalDisposition, ...],
        Field(max_length=256),
    ] = ()
    launch_intent_count: Annotated[int, Field(strict=True, ge=0, le=256)]
    commit_authorized_at_monotonic_ns: Annotated[int, Field(strict=True, gt=0)]
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_failure_quiescence(self) -> "CampaignFailureQuiescenceEvidence":
        expected_signals = tuple(sorted((int(signal.SIGHUP), int(signal.SIGTERM))))
        entry_threads = self.barrier_entry_thread_inventory
        precommit_threads = self.precommit_thread_inventory
        fd_inventory = self.final_file_descriptor_inventory
        chronology = (
            entry_threads.second_scan_completed_monotonic_ns,
            fd_inventory.first_scan_started_monotonic_ns,
            fd_inventory.second_scan_completed_monotonic_ns,
            self.first_output_scan_started_monotonic_ns,
            self.first_output_scan_completed_monotonic_ns,
            self.second_output_scan_started_monotonic_ns,
            self.second_output_scan_completed_monotonic_ns,
            precommit_threads.first_scan_started_monotonic_ns,
            precommit_threads.second_scan_completed_monotonic_ns,
            self.commit_authorized_at_monotonic_ns,
        )
        vnode_projection = [
            item.model_dump(mode="json") for item in self.output_prefix_vnodes
        ]
        vnode_keys = {
            (item.device, item.inode) for item in self.output_prefix_vnodes
        }
        recomputed_writable_output_fds = tuple(
            item.fd
            for item in fd_inventory.descriptors
            if item.vnode is not None
            and (item.vnode.device, item.vnode.inode) in vnode_keys
            and bool(item.open_flags & self.darwin_vnode_write_access_mask)
        )
        if (
            self.termination_signal_numbers != expected_signals
            or self.barrier_signal_mask_before_inventory
            != tuple(sorted(set(self.barrier_signal_mask_before_inventory)))
            or self.barrier_signal_mask_before_commit
            != tuple(sorted(set(self.barrier_signal_mask_before_commit)))
            or not set(expected_signals).issubset(
                self.barrier_signal_mask_before_inventory
            )
            or self.barrier_signal_mask_before_inventory
            != self.barrier_signal_mask_before_commit
            or entry_threads.thread_count != 1
            or precommit_threads.thread_count != 1
            or entry_threads.thread_ids != precommit_threads.thread_ids
            or entry_threads.process != precommit_threads.process
            or entry_threads.process != fd_inventory.process
            or (
                self.controller.pid,
                self.controller.process_group_id,
                self.controller.session_id,
            )
            != (
                entry_threads.process.pid,
                entry_threads.process.pgid,
                entry_threads.process.sid,
            )
            or chronology != tuple(sorted(chronology))
            or self.first_output_scan_sha256
            != self.second_output_scan_sha256
            or tuple(item.relative_path for item in self.output_prefix_vnodes)
            != tuple(
                sorted(item.relative_path for item in self.output_prefix_vnodes)
            )
            or len(
                {
                    (item.device, item.inode)
                    for item in self.output_prefix_vnodes
                }
            )
            != len(self.output_prefix_vnodes)
            or self.output_prefix_vnodes_sha256
            != _canonical_sha256(vnode_projection)
            or self.first_output_prefix_vnodes_sha256
            != self.output_prefix_vnodes_sha256
            or self.second_output_prefix_vnodes_sha256
            != self.output_prefix_vnodes_sha256
            or self.writable_output_prefix_descriptor_fds
            != recomputed_writable_output_fds
            or recomputed_writable_output_fds
            or self.launch_intent_count != len(self.launch_dispositions)
            or tuple(item.attempt_id for item in self.launch_dispositions)
            != tuple(sorted(item.attempt_id for item in self.launch_dispositions))
            or len({item.attempt_id for item in self.launch_dispositions})
            != len(self.launch_dispositions)
            or self.record_sha256
            != _canonical_sha256(
                self.model_dump(mode="json", exclude={"record_sha256"})
            )
        ):
            raise ValueError("campaign failure quiescence evidence differs")
        return self


class CampaignClosureManifest(ContractModel):
    schema_id: Literal["phase-latency-campaign-closure-manifest-v1"] = (
        "phase-latency-campaign-closure-manifest-v1"
    )
    campaign_id: Literal["LAT-US02"] = "LAT-US02"
    status: Literal["success", "failure"]
    output_root: CampaignClosureOutputRootIdentity
    entries: Annotated[
        tuple[CampaignClosureEntry, ...], Field(min_length=1, max_length=4_096)
    ]
    entry_count: Annotated[int, Field(strict=True, gt=0, le=4_096)]
    aggregate_bytes: Annotated[int, Field(strict=True, ge=0)]
    sole_self_exclusion: Literal["campaign-closure.json"] = (
        "campaign-closure.json"
    )
    producer_groups_esrch: Literal[True] = True
    writer_fds_closed: Literal[True] = True
    fsync_completed: Literal[True] = True
    terminal_manifest_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    bundle_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    evaluation_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    failure: FailureRecord | None = None
    failure_quiescence: CampaignFailureQuiescenceEvidence | None = None
    completed_at_monotonic_ns: Annotated[int, Field(strict=True, gt=0)]
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_closure(self) -> "CampaignClosureManifest":
        paths = tuple(item.relative_path for item in self.entries)
        inode_keys = tuple((item.device, item.inode) for item in self.entries)
        if (
            paths != tuple(sorted(paths))
            or len(paths) != len(set(paths))
            or len(inode_keys) != len(set(inode_keys))
            or self.entry_count != len(self.entries)
            or self.aggregate_bytes
            != sum(item.size_bytes for item in self.entries)
            or (
                self.status == "success"
                and (
                    self.terminal_manifest_sha256 is None
                    or self.bundle_sha256 is None
                    or self.evaluation_sha256 is None
                    or self.failure is not None
                    or self.failure_quiescence is not None
                )
            )
            or (
                self.status == "failure"
                and (
                    self.bundle_sha256 is not None
                    or self.evaluation_sha256 is not None
                    or self.failure is None
                    or self.failure_quiescence is None
                )
            )
            or (
                self.status == "failure"
                and self.failure_quiescence is not None
                and not self._failure_paths_are_bound()
            )
            or self.record_sha256
            != _canonical_sha256(
                self.model_dump(mode="json", exclude={"record_sha256"})
            )
        ):
            raise ValueError("campaign closure manifest differs")
        return self

    def _failure_paths_are_bound(self) -> bool:
        assert self.failure_quiescence is not None
        by_path = {item.relative_path: item for item in self.entries}
        if not {
            path for path in by_path if len(Path(path).parts) == 1
        }.issubset(_CAMPAIGN_FAILURE_ALLOWED_ROOT_ARTIFACT_PATHS):
            return False
        intent_paths = {
            path
            for path in by_path
            if path.startswith("terminal/")
            and path.endswith("-launch-intent.json")
        }
        dispositions = self.failure_quiescence.launch_dispositions
        if intent_paths != {item.intent_relative_path for item in dispositions}:
            return False
        vnodes_by_path = {
            item.relative_path: item
            for item in self.failure_quiescence.output_prefix_vnodes
        }
        if set(vnodes_by_path) != {".", "terminal", *by_path}:
            return False
        root_vnode = vnodes_by_path["."]
        if (
            root_vnode.device,
            root_vnode.inode,
            root_vnode.mode,
            root_vnode.uid,
            root_vnode.nlink,
        ) != (
            self.output_root.device,
            self.output_root.inode,
            self.output_root.mode,
            self.output_root.uid,
            self.output_root.nlink,
        ):
            return False
        terminal_vnode = vnodes_by_path["terminal"]
        if terminal_vnode.mode != 0o700 or terminal_vnode.uid != self.output_root.uid:
            return False
        for relative_path, entry in by_path.items():
            vnode = vnodes_by_path[relative_path]
            if (
                vnode.device,
                vnode.inode,
                vnode.mode,
                vnode.uid,
                vnode.nlink,
            ) != (
                entry.device,
                entry.inode,
                entry.mode,
                entry.uid,
                entry.nlink,
            ):
                return False
        bound_terminal_paths: set[str] = set()
        for disposition in dispositions:
            path_hashes = (
                (
                    disposition.intent_relative_path,
                    disposition.intent_content_sha256,
                ),
                (
                    disposition.receipt_relative_path,
                    disposition.receipt_content_sha256,
                ),
                (
                    disposition.launcher_ledger_relative_path,
                    disposition.launcher_ledger_content_sha256,
                ),
                (
                    disposition.watchdog_terminal_relative_path,
                    disposition.watchdog_terminal_content_sha256,
                ),
            )
            optional_path_hashes = (
                (
                    disposition.launch_record_relative_path,
                    disposition.launch_record_content_sha256,
                ),
                (
                    disposition.launch_failure_relative_path,
                    disposition.launch_failure_content_sha256,
                ),
            )
            if any(
                path not in by_path or by_path[path].content_sha256 != digest
                for path, digest in path_hashes
            ) or any(
                path is not None
                and (
                    digest is None
                    or path not in by_path
                    or by_path[path].content_sha256 != digest
                )
                for path, digest in optional_path_hashes
            ):
                return False
            for artifact in disposition.attempt_artifacts:
                entry = by_path.get(artifact.relative_path)
                if (
                    entry is None
                    or artifact.relative_path in bound_terminal_paths
                    or entry.content_sha256 != artifact.content_sha256
                    or entry.size_bytes != artifact.size_bytes
                ):
                    return False
                bound_terminal_paths.add(artifact.relative_path)
        flat_terminal_paths = {
            path
            for path in by_path
            if len(Path(path).parts) == 2 and Path(path).parts[0] == "terminal"
        }
        if not (flat_terminal_paths - bound_terminal_paths).issubset(
            _CAMPAIGN_GLOBAL_TERMINAL_ARTIFACT_PATHS
        ):
            return False
        return self.failure_quiescence.first_output_scan_sha256 == _canonical_sha256(
            [item.model_dump(mode="json") for item in self.entries]
        )


class CampaignFailureMarker(ContractModel):
    """Diagnostic prefix snapshot that makes no final-closure claim."""

    schema_id: Literal["phase-latency-campaign-failure-marker-v1"] = (
        "phase-latency-campaign-failure-marker-v1"
    )
    campaign_id: Literal["LAT-US02"] = "LAT-US02"
    status: Literal["incomplete_custody"] = "incomplete_custody"
    entries: Annotated[
        tuple[CampaignClosureEntry, ...], Field(min_length=1, max_length=4_096)
    ]
    entry_count: Annotated[int, Field(strict=True, gt=0, le=4_096)]
    aggregate_bytes: Annotated[int, Field(strict=True, ge=0)]
    failure: FailureRecord
    producer_groups_esrch: Literal[False] = False
    writer_fds_closed: Literal[False] = False
    final_closure_claimed: Literal[False] = False
    observed_at_monotonic_ns: Annotated[int, Field(strict=True, gt=0)]
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_marker(self) -> "CampaignFailureMarker":
        paths = tuple(item.relative_path for item in self.entries)
        if (
            paths != tuple(sorted(paths))
            or len(paths) != len(set(paths))
            or self.entry_count != len(self.entries)
            or self.aggregate_bytes
            != sum(item.size_bytes for item in self.entries)
            or self.record_sha256
            != _canonical_sha256(
                self.model_dump(mode="json", exclude={"record_sha256"})
            )
        ):
            raise ValueError("campaign failure marker differs")
        return self


ProductionCampaignPlan.model_rebuild()


@dataclass(frozen=True, slots=True)
class PreparedProductionRuntime:
    common_environment: dict[str, str]
    artifact_identity: ArtifactIdentity
    dependency_runtime_sha256: str
    execution: ExecutionIdentity
    pairing_sha256: str
    artifact_materialization: RuntimeArtifactMaterialization


@dataclass(frozen=True, slots=True)
class ProductionCampaignResult:
    plan: ProductionCampaignPlan
    bundle: LocalPrewarmEvidenceBundle
    evaluation: LocalPrewarmEvaluation
    receipt_paths: tuple[Path, ...]
    artifact_observation_paths: tuple[Path, ...]
    final_artifact_manifest_path: Path
    campaign_closure_manifest_path: Path


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            to_jsonable_python(value),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _canonical_payload_bytes(value: object) -> bytes:
    return json.dumps(
        to_jsonable_python(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _broker_launch_template_bytes(value: Mapping[str, Any]) -> bytes:
    payload = _canonical_payload_bytes(dict(value))
    if not payload or len(payload) > MAXIMUM_BROKER_LAUNCH_TEMPLATE_BYTES:
        raise ValueError("broker launch template exceeded its bound")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def _seatbelt_path_literal(path: Path) -> str:
    value = str(path.resolve(strict=True))
    if "\x00" in value or "\n" in value or "\r" in value:
        raise ValueError("Seatbelt path contains control bytes")
    return json.dumps(value, ensure_ascii=True)


def _production_seatbelt_profile(
    *,
    artifact_root: Path,
    tessdata_root: Path,
    request_root: Path,
    input_probe_root: Path,
    network_trap_root: Path,
    artifact_probe_clone_root: Path,
    tessdata_probe_clone_root: Path,
    staged_executable_probe_clone_root: Path,
    worker_scratch_root: Path | None,
    immutable_executable: Path,
    deny_process_fork: bool,
    deny_all_file_writes: bool = False,
) -> str:
    clauses = [
        "(version 1)",
        "(allow default)",
        "(deny network-outbound)",
        "(deny network-inbound)",
    ]
    if deny_process_fork:
        clauses.append("(deny process-fork)")
    clauses.extend(
        (
            "(deny file-write* "
            f"(subpath {_seatbelt_path_literal(artifact_root)}) "
            f"(subpath {_seatbelt_path_literal(tessdata_root)}) "
            f"(literal {_seatbelt_path_literal(immutable_executable)}))",
        )
    )
    clauses.append(
        "(deny file-write* "
        f"(subpath {_seatbelt_path_literal(input_probe_root)}) "
        f"(subpath {_seatbelt_path_literal(network_trap_root)}) "
        f"(subpath {_seatbelt_path_literal(artifact_probe_clone_root)}) "
        f"(subpath {_seatbelt_path_literal(tessdata_probe_clone_root)}) "
        "(subpath "
        f"{_seatbelt_path_literal(staged_executable_probe_clone_root)}))"
    )
    if deny_all_file_writes:
        clauses.extend(
            (
                "(deny file-write* "
                f"(subpath {_seatbelt_path_literal(request_root)}))",
                "(deny file-write*)",
            )
        )
    else:
        if worker_scratch_root is None:
            raise ValueError("worker scratch root is required")
        clauses.append(
            "(deny file-write* (require-not "
            f"(subpath {_seatbelt_path_literal(worker_scratch_root)})))"
        )
    profile = "".join(clauses)
    if not profile.isascii() or len(profile.encode("ascii")) > 16 * 1024:
        raise ValueError("production Seatbelt profile exceeds its bound")
    return profile


def _stage_private_executable(*, source: Path, target: Path) -> dict[str, object]:
    source_resolved = source.resolve(strict=True)
    source_stat = source_resolved.lstat()
    if (
        not stat.S_ISREG(source_stat.st_mode)
        or source_resolved.is_symlink()
        or source_stat.st_mode & (stat.S_ISUID | stat.S_ISGID)
    ):
        raise RuntimeError("source executable custody differs")
    source_fd = os.open(
        source_resolved,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    target_fd = os.open(
        target,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o500,
    )
    source_digest = hashlib.sha256()
    try:
        while chunk := os.read(source_fd, 1024 * 1024):
            source_digest.update(chunk)
            written = 0
            while written < len(chunk):
                count = os.write(target_fd, chunk[written:])
                if count <= 0:
                    raise OSError("staged executable write made no progress")
                written += count
        os.fsync(target_fd)
        target_stat = os.fstat(target_fd)
        source_after = os.fstat(source_fd)
    finally:
        os.close(target_fd)
        os.close(source_fd)
    if (
        source_after.st_dev != source_stat.st_dev
        or source_after.st_ino != source_stat.st_ino
        or source_after.st_size != source_stat.st_size
        or not stat.S_ISREG(target_stat.st_mode)
        or stat.S_IMODE(target_stat.st_mode) != 0o500
        or target_stat.st_uid != os.geteuid()
        or target_stat.st_nlink != 1
        or target_stat.st_size != source_stat.st_size
    ):
        raise RuntimeError("staged executable identity differs")
    digest = source_digest.hexdigest()
    if _sha256_file(target) != digest:
        raise RuntimeError("staged executable bytes differ from source")
    return {
        "resolved_path": str(target.resolve(strict=True)),
        "sha256": digest,
        "device": target_stat.st_dev,
        "inode": target_stat.st_ino,
        "mode": target_stat.st_mode,
        "uid": target_stat.st_uid,
        "nlink": target_stat.st_nlink,
        "size": target_stat.st_size,
    }


def _build_and_stage_native_fork_probe(
    *, workspace: Path, target_root: Path
) -> tuple[Path, dict[str, object], str]:
    """Build the pinned vfork-safe C probe, then retain it with O_EXCL custody."""

    source = (
        workspace / "app/services/parser_fork_denial_probe.c"
    ).resolve(strict=True)
    source_sha256 = _sha256_file(source)
    compiler = Path("/usr/bin/clang").resolve(strict=True)
    target = target_root / "parser-fork-denial-probe.dylib"
    if target.exists():
        raise FileExistsError("native fork probe target already exists")
    with tempfile.TemporaryDirectory(
        prefix="native-fork-probe-build-", dir=target_root
    ) as raw_build_root:
        build_root = Path(raw_build_root).resolve(strict=True)
        built = build_root / "probe.dylib"
        build_environment = sanitized_watchdog_environment()
        for name in ("TMPDIR", "TMP", "TEMP"):
            build_environment[name] = str(build_root)
        completed = subprocess.run(
            (
                str(compiler),
                "-dynamiclib",
                "-Os",
                "-fvisibility=hidden",
                "-o",
                str(built),
                str(source),
            ),
            cwd=workspace,
            env=build_environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30.0,
        )
        if (
            completed.returncode != 0
            or completed.stdout
            or len(completed.stderr) > 65_536
            or not built.is_file()
            or built.stat().st_size <= 0
            or built.stat().st_size > MAXIMUM_NATIVE_FORK_PROBE_BYTES
        ):
            raise RuntimeError("native fork probe build failed")
        identity = _stage_private_executable(source=built, target=target)
    if (
        identity["resolved_path"] != str(target.resolve(strict=True))
        or identity["sha256"] != _sha256_file(target)
        or stat.S_IMODE(target.stat().st_mode) != 0o500
    ):
        raise RuntimeError("native fork probe staged identity differs")
    return target, identity, source_sha256


def _build_and_stage_native_spawn_guard(
    *, workspace: Path, target_root: Path
) -> tuple[Path, dict[str, object], Path, str]:
    """Build and privately stage the broker's pinned ``__fork`` boundary."""

    source = (
        workspace / "app/services/tesseract_broker_spawn.c"
    ).resolve(strict=True)
    source_sha256 = _sha256_file(source)
    compiler = Path("/usr/bin/clang").resolve(strict=True)
    target = target_root / "tesseract-broker-spawn-guard.dylib"
    if target.exists():
        raise FileExistsError("native spawn guard target already exists")
    with tempfile.TemporaryDirectory(
        prefix="native-spawn-guard-build-", dir=target_root
    ) as raw_build_root:
        build_root = Path(raw_build_root).resolve(strict=True)
        built = build_root / "spawn-guard.dylib"
        build_environment = sanitized_watchdog_environment()
        for name in ("TMPDIR", "TMP", "TEMP"):
            build_environment[name] = str(build_root)
        completed = subprocess.run(
            (
                str(compiler),
                "-dynamiclib",
                "-Os",
                "-fvisibility=hidden",
                "-o",
                str(built),
                str(source),
            ),
            cwd=workspace,
            env=build_environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30.0,
        )
        if (
            completed.returncode != 0
            or completed.stdout
            or len(completed.stderr) > 65_536
            or not built.is_file()
            or built.stat().st_size <= 0
            or built.stat().st_size > MAXIMUM_NATIVE_SPAWN_GUARD_BYTES
        ):
            raise RuntimeError("native spawn guard build failed")
        identity = _stage_private_executable(source=built, target=target)
    if (
        identity["resolved_path"] != str(target.resolve(strict=True))
        or identity["sha256"] != _sha256_file(target)
        or stat.S_IMODE(target.stat().st_mode) != 0o500
        or _sha256_file(source) != source_sha256
    ):
        raise RuntimeError("native spawn guard staged identity differs")
    return target, identity, source, source_sha256


def _build_and_stage_native_runtime_gate(
    *, workspace: Path, target_root: Path
) -> tuple[Path, dict[str, object], Path, dict[str, object]]:
    """Build and privately stage the trusted pre-main runtime gate.

    Both the exact C source and resulting Mach-O are O_EXCL materialized under
    the controller's private executable root.  ``derive_native_closure`` then
    binds these exact identities into the staged Tesseract closure.
    """

    workspace_source = (
        workspace / "app/services/tesseract_runtime_gate.c"
    ).resolve(strict=True)
    source = target_root / "tesseract-runtime-gate.c"
    target = target_root / "tesseract-runtime-gate.dylib"
    if source.exists() or target.exists():
        raise FileExistsError("native runtime gate target already exists")
    source_identity = _stage_private_executable(
        source=workspace_source,
        target=source,
    )
    compiler = Path("/usr/bin/clang").resolve(strict=True)
    with tempfile.TemporaryDirectory(
        prefix="native-runtime-gate-build-", dir=target_root
    ) as raw_build_root:
        build_root = Path(raw_build_root).resolve(strict=True)
        built = build_root / "runtime-gate.dylib"
        build_environment = sanitized_watchdog_environment()
        for name in ("TMPDIR", "TMP", "TEMP"):
            build_environment[name] = str(build_root)
        completed = subprocess.run(
            (
                str(compiler),
                "-dynamiclib",
                "-Os",
                "-fvisibility=hidden",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-o",
                str(built),
                str(source),
            ),
            cwd=workspace,
            env=build_environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30.0,
        )
        if (
            completed.returncode != 0
            or completed.stdout
            or len(completed.stderr) > 65_536
            or not built.is_file()
            or built.stat().st_size <= 0
            or built.stat().st_size > MAXIMUM_NATIVE_RUNTIME_GATE_BYTES
        ):
            raise RuntimeError("native runtime gate build failed")
        library_identity = _stage_private_executable(
            source=built,
            target=target,
        )
    if (
        source_identity["resolved_path"] != str(source.resolve(strict=True))
        or source_identity["sha256"] != _sha256_file(source)
        or library_identity["resolved_path"] != str(target.resolve(strict=True))
        or library_identity["sha256"] != _sha256_file(target)
        or stat.S_IMODE(source.stat().st_mode) != 0o500
        or stat.S_IMODE(target.stat().st_mode) != 0o500
        or source.stat().st_uid != os.geteuid()
        or target.stat().st_uid != os.geteuid()
        or source.stat().st_nlink != 1
        or target.stat().st_nlink != 1
    ):
        raise RuntimeError("native runtime gate staged identity differs")
    return source, source_identity, target, library_identity


def _root_owned_executable_identity(path: Path) -> dict[str, object]:
    """Observe one resolved root-owned, non-writable executable vnode."""

    resolved = path.resolve(strict=True)
    observed = resolved.lstat()
    if (
        resolved.is_symlink()
        or not stat.S_ISREG(observed.st_mode)
        or observed.st_uid != 0
        or observed.st_nlink != 1
        or observed.st_size <= 0
        or observed.st_mode
        & (stat.S_IWGRP | stat.S_IWOTH | stat.S_ISUID | stat.S_ISGID)
    ):
        raise RuntimeError("guard Python executable custody differs")
    return {
        "resolved_path": str(resolved),
        "sha256": _sha256_file(resolved),
        "device": observed.st_dev,
        "inode": observed.st_ino,
        "mode": observed.st_mode,
        "uid": observed.st_uid,
        "nlink": observed.st_nlink,
        "size": observed.st_size,
    }


def _build_and_stage_native_sandbox_probe(
    *, workspace: Path, target_root: Path
) -> tuple[Path, dict[str, object], Path, str]:
    """Build and privately stage the exact descriptor-relative Seatbelt probe."""

    workspace_source = (
        workspace / "app/services/parser_sandbox_probe.c"
    ).resolve(strict=True)
    source_sha256 = _sha256_file(workspace_source)
    compiler = Path("/usr/bin/clang").resolve(strict=True)
    source = target_root / "parser_sandbox_probe.c"
    target = target_root / "parser-sandbox-probe.dylib"
    if source.exists() or target.exists():
        raise FileExistsError("native sandbox probe target already exists")
    source_identity = _stage_private_executable(
        source=workspace_source,
        target=source,
    )
    with tempfile.TemporaryDirectory(
        prefix="native-sandbox-probe-build-", dir=target_root
    ) as raw_build_root:
        build_root = Path(raw_build_root).resolve(strict=True)
        built = build_root / "sandbox-probe.dylib"
        build_environment = sanitized_watchdog_environment()
        for name in ("TMPDIR", "TMP", "TEMP"):
            build_environment[name] = str(build_root)
        completed = subprocess.run(
            (
                str(compiler),
                "-dynamiclib",
                "-Os",
                "-fvisibility=hidden",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-o",
                str(built),
                str(source),
            ),
            cwd=workspace,
            env=build_environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30.0,
        )
        if (
            completed.returncode != 0
            or completed.stdout
            or len(completed.stderr) > 65_536
            or not built.is_file()
            or built.stat().st_size <= 0
            or built.stat().st_size > MAXIMUM_NATIVE_SANDBOX_PROBE_BYTES
        ):
            raise RuntimeError("native sandbox probe build failed")
        identity = _stage_private_executable(source=built, target=target)
    if (
        identity["resolved_path"] != str(target.resolve(strict=True))
        or identity["sha256"] != _sha256_file(target)
        or stat.S_IMODE(target.stat().st_mode) != 0o500
        or _sha256_file(source) != source_sha256
        or source_identity["sha256"] != source_sha256
        or stat.S_IMODE(source.stat().st_mode) != 0o500
        or source.stat().st_uid != os.geteuid()
        or source.stat().st_nlink != 1
    ):
        raise RuntimeError("native sandbox probe staged identity differs")
    return target, identity, source, source_sha256


def _sandboxed_exact_profile_command(
    command: tuple[str, ...], profile: str
) -> tuple[str, ...]:
    if not command or not profile:
        raise ValueError("sandbox command/profile is empty")
    return (OS_NETWORK_SANDBOX_EXECUTABLE, "-p", profile, *command)


def _filesystem_identity(path: Path) -> dict[str, object]:
    resolved = path.resolve(strict=True)
    opened = resolved.lstat()
    if (
        resolved.is_symlink()
        or not stat.S_ISDIR(opened.st_mode)
        or stat.S_IMODE(opened.st_mode) != 0o700
        or opened.st_uid != os.geteuid()
    ):
        raise RuntimeError("broker filesystem directory custody differs")
    return {
        "resolved_path": str(resolved),
        "device": opened.st_dev,
        "inode": opened.st_ino,
        "mode": opened.st_mode,
        "uid": opened.st_uid,
    }


def _content_records_sha256(records: object) -> str:
    """Match ``parser_worker.artifact_identity`` content canonicalization."""

    return hashlib.sha256(
        json.dumps(
            records,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _file_identity(workspace: Path, path: Path) -> ArtifactIdentity:
    resolved = path.resolve(strict=True)
    relative = resolved.relative_to(workspace.resolve()).as_posix()
    data = resolved.read_bytes()
    if not data:
        raise ValueError("retained input artifact cannot be empty")
    return ArtifactIdentity(
        path=relative,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
    )


def _resolved_path_identity(path: Path) -> str:
    return _canonical_sha256({"resolved_path": str(path.resolve(strict=True))})


def _tree_content_records(
    root: Path,
    *,
    prefix: str = "",
    allow_empty: bool = False,
) -> tuple[tuple[dict[str, object], ...], int]:
    resolved_root = root.resolve(strict=True)
    records = []
    aggregate = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_dir():
            continue
        resolved = path.resolve(strict=True)
        if not resolved.is_file():
            raise ValueError("materialization source contains a non-file leaf")
        data = resolved.read_bytes()
        aggregate += len(data)
        if aggregate > 16 * 1024 * 1024 * 1024 or len(records) >= 4_096:
            raise ValueError("materialization source exceeds its evidence bound")
        relative = path.relative_to(root).as_posix()
        records.append(
            {
                "path": f"{prefix}/{relative}" if prefix else relative,
                "sha256": hashlib.sha256(data).hexdigest(),
                "size_bytes": len(data),
            }
        )
    if (not records and not allow_empty) or resolved_root != root.resolve(strict=True):
        raise ValueError("materialization source is empty or unstable")
    return tuple(records), aggregate


def _observe_post_attempt_artifact(
    *,
    attempt_id: str,
    prepared: PreparedProductionRuntime,
    artifacts_path: Path,
) -> PostAttemptArtifactObservation:
    """Best-effort closed observation that can also retain mismatch/error state."""

    expected = prepared.artifact_materialization
    resolved_runtime_path = expected.target_resolved_runtime_path
    resolved_path_identity = expected.target_resolved_path_identity_sha256
    observed_artifact_sha256: str | None = None
    observed_content_manifest_sha256: str | None = None
    observed_metadata_sha256: str | None = None
    observed_file_count: int | None = None
    observed_aggregate_bytes: int | None = None
    observed_directory_mode: int | None = None
    observed_owned_by_current_uid: bool | None = None
    observed_symlinks_in_target: bool | None = None
    failure_detail_sha256: str | None = None
    try:
        from app.services.parser_worker import artifact_identity

        supplied_is_symlink = artifacts_path.is_symlink()
        resolved = artifacts_path.resolve(strict=True)
        resolved_runtime_path = str(resolved)
        resolved_path_identity = _resolved_path_identity(resolved)
        observed = artifact_identity(resolved)
        records, aggregate = _tree_content_records(resolved)
        observed_artifact_sha256 = observed.sha256
        observed_content_manifest_sha256 = _content_records_sha256(records)
        observed_metadata_sha256 = observed.metadata_sha256
        observed_file_count = observed.file_count
        observed_aggregate_bytes = observed.aggregate_bytes
        target_stat = resolved.lstat()
        observed_directory_mode = stat.S_IMODE(target_stat.st_mode)
        observed_owned_by_current_uid = target_stat.st_uid == os.getuid()
        observed_symlinks_in_target = supplied_is_symlink or any(
            path.is_symlink() for path in resolved.rglob("*")
        )
        matches = bool(
            aggregate == observed.aggregate_bytes
            and len(records) == observed.file_count
            and observed.sha256 == observed_content_manifest_sha256
            and resolved_runtime_path == expected.target_resolved_runtime_path
            and resolved_path_identity
            == expected.target_resolved_path_identity_sha256
            and observed.sha256 == expected.target.sha256
            and observed_content_manifest_sha256
            == expected.target_content_manifest_sha256
            and observed.metadata_sha256 == expected.target_metadata_sha256
            and observed.file_count == expected.target_file_count
            and observed.aggregate_bytes == expected.target_aggregate_bytes
            and observed_directory_mode == expected.target_directory_mode
            and observed_owned_by_current_uid
            == expected.target_owned_by_current_uid
            and observed_symlinks_in_target == expected.symlinks_in_target
        )
        status = "matched" if matches else "mismatch"
    except BaseException as error:
        matches = False
        status = "observation_error"
        failure_detail_sha256 = _canonical_sha256(
            {
                "error_type": f"{type(error).__module__}.{type(error).__qualname__}"
            }
        )
    fields = {
        "schema_id": "phase-latency-prewarm-post-attempt-artifact-v1",
        "attempt_id": attempt_id,
        "observed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "preflight_manifest_sha256": expected.manifest_sha256,
        "target_resolved_runtime_path": resolved_runtime_path,
        "target_resolved_path_identity_sha256": resolved_path_identity,
        "observed_artifact_sha256": observed_artifact_sha256,
        "observed_content_manifest_sha256": observed_content_manifest_sha256,
        "observed_metadata_sha256": observed_metadata_sha256,
        "observed_file_count": observed_file_count,
        "observed_aggregate_bytes": observed_aggregate_bytes,
        "observed_directory_mode": observed_directory_mode,
        "observed_owned_by_current_uid": observed_owned_by_current_uid,
        "observed_symlinks_in_target": observed_symlinks_in_target,
        "status": status,
        "matches_preflight": matches,
        "failure_detail_sha256": failure_detail_sha256,
    }
    return PostAttemptArtifactObservation(
        **fields, observation_sha256=_canonical_sha256(fields)
    )


def _materialization_manifest(
    *,
    target_path: Path,
    target: ArtifactIdentity,
    workspace_model_source: Path,
    classifier_source: Path,
    target_metadata_sha256: str,
    target_file_count: int,
    target_aggregate_bytes: int,
    target_before_artifact_sha256: str | None = None,
    target_after_artifact_sha256: str | None = None,
    target_before_metadata_sha256: str | None = None,
    target_after_metadata_sha256: str | None = None,
    target_before_file_count: int | None = None,
    target_after_file_count: int | None = None,
    target_before_aggregate_bytes: int | None = None,
    target_after_aggregate_bytes: int | None = None,
    target_before_records: tuple[dict[str, object], ...] | None = None,
    target_after_records: tuple[dict[str, object], ...] | None = None,
) -> RuntimeArtifactMaterialization:
    before_records, before_tree_bytes = (
        _tree_content_records(target_path)
        if target_before_records is None
        else (target_before_records, sum(int(row["size_bytes"]) for row in target_before_records))
    )
    after_records, after_tree_bytes = (
        _tree_content_records(target_path)
        if target_after_records is None
        else (target_after_records, sum(int(row["size_bytes"]) for row in target_after_records))
    )
    content_unchanged = (
        before_records == after_records
        and before_tree_bytes == after_tree_bytes
    )
    if not content_unchanged:
        raise ValueError("approved artifact target content changed during preparation")
    base_records, base_bytes = _tree_content_records(workspace_model_source)
    classifier_name = "docling-project--DocumentFigureClassifier-v2.5"
    classifier_records, classifier_bytes = _tree_content_records(
        classifier_source, prefix=classifier_name
    )
    source_union = tuple(
        sorted((*base_records, *classifier_records), key=lambda item: str(item["path"]))
    )
    source_union_equals_target = not (
        source_union != before_records
        or source_union != after_records
        or before_tree_bytes != base_bytes + classifier_bytes
        or after_tree_bytes != base_bytes + classifier_bytes
    )
    if not source_union_equals_target:
        raise ValueError("approved artifact target differs from its two sources")
    symlinks_in_target = any(path.is_symlink() for path in target_path.rglob("*"))
    if symlinks_in_target:
        raise ValueError("approved artifact target cannot contain symlinks")
    target_stat = target_path.lstat()
    if (
        stat.S_IMODE(target_stat.st_mode) != 0o700
        or target_stat.st_uid != os.getuid()
    ):
        raise ValueError("approved artifact target must be owned mode 0700")
    sources = (
        RuntimeArtifactSourceIdentity(
            source_id="workspace-model-tree",
            source_role="base_docling_model_tree",
            portable_label=".models/docling",
            snapshot_revision=None,
            resolved_path=str(workspace_model_source.resolve(strict=True)),
            resolved_path_identity_sha256=_resolved_path_identity(
                workspace_model_source
            ),
            content_manifest_sha256=_content_records_sha256(base_records),
            file_count=len(base_records),
            aggregate_bytes=base_bytes,
        ),
        RuntimeArtifactSourceIdentity(
            source_id=f"hf-classifier-snapshot-{classifier_source.name}",
            source_role="optional_classifier_snapshot",
            portable_label=(
                "huggingface-cache/docling-project/"
                "DocumentFigureClassifier-v2.5/snapshots/"
                f"{classifier_source.name}"
            ),
            snapshot_revision=classifier_source.name,
            resolved_path=str(classifier_source.resolve(strict=True)),
            resolved_path_identity_sha256=_resolved_path_identity(classifier_source),
            content_manifest_sha256=_content_records_sha256(classifier_records),
            file_count=len(classifier_records),
            aggregate_bytes=classifier_bytes,
        ),
    )
    before_artifact_sha256 = (
        target.sha256
        if target_before_artifact_sha256 is None
        else target_before_artifact_sha256
    )
    after_artifact_sha256 = (
        target.sha256
        if target_after_artifact_sha256 is None
        else target_after_artifact_sha256
    )
    before_metadata_sha256 = (
        target_metadata_sha256
        if target_before_metadata_sha256 is None
        else target_before_metadata_sha256
    )
    after_metadata_sha256 = (
        target_metadata_sha256
        if target_after_metadata_sha256 is None
        else target_after_metadata_sha256
    )
    before_file_count = (
        target_file_count
        if target_before_file_count is None
        else target_before_file_count
    )
    after_file_count = (
        target_file_count
        if target_after_file_count is None
        else target_after_file_count
    )
    before_aggregate_bytes = (
        target_aggregate_bytes
        if target_before_aggregate_bytes is None
        else target_before_aggregate_bytes
    )
    after_aggregate_bytes = (
        target_aggregate_bytes
        if target_after_aggregate_bytes is None
        else target_after_aggregate_bytes
    )
    before_after_identity_unchanged = bool(
        content_unchanged
        and before_artifact_sha256 == after_artifact_sha256 == target.sha256
        and before_metadata_sha256
        == after_metadata_sha256
        == target_metadata_sha256
        and before_file_count == after_file_count == target_file_count
        and before_aggregate_bytes
        == after_aggregate_bytes
        == target_aggregate_bytes
        == target.size_bytes
    )
    if not before_after_identity_unchanged:
        raise ValueError("approved artifact identity changed between observations")
    no_write_observed = before_after_identity_unchanged
    fields = {
        "schema_id": "phase-latency-prewarm-artifact-materialization-v1",
        "target": target.model_dump(mode="json"),
        "target_resolved_runtime_path": str(target_path.resolve(strict=True)),
        "target_resolved_path_identity_sha256": _resolved_path_identity(target_path),
        "target_content_manifest_sha256": _content_records_sha256(after_records),
        "target_metadata_sha256": target_metadata_sha256,
        "target_file_count": target_file_count,
        "target_aggregate_bytes": target_aggregate_bytes,
        "target_directory_mode": 0o700,
        "target_owned_by_current_uid": True,
        "target_before_artifact_sha256": before_artifact_sha256,
        "target_after_artifact_sha256": after_artifact_sha256,
        "target_before_content_manifest_sha256": _content_records_sha256(
            before_records
        ),
        "target_after_content_manifest_sha256": _content_records_sha256(after_records),
        "target_before_metadata_sha256": before_metadata_sha256,
        "target_after_metadata_sha256": after_metadata_sha256,
        "target_before_file_count": before_file_count,
        "target_after_file_count": after_file_count,
        "target_before_aggregate_bytes": before_aggregate_bytes,
        "target_after_aggregate_bytes": after_aggregate_bytes,
        "sources": [item.model_dump(mode="json") for item in sources],
        "source_union_equals_target": source_union_equals_target,
        "symlinks_in_target": symlinks_in_target,
        "before_after_identity_unchanged": before_after_identity_unchanged,
        "no_write_observed": no_write_observed,
    }
    return RuntimeArtifactMaterialization(
        **fields, manifest_sha256=_canonical_sha256(fields)
    )


def _settings_from_environment(environment: dict[str, str]):
    from app.config import Settings

    with patch.dict(os.environ, environment, clear=True):
        return Settings.from_env()


def _settings_sha256(settings: object) -> str:
    from dataclasses import asdict

    return hashlib.sha256(
        json.dumps(
            asdict(settings),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def prepare_production_runtime(
    *,
    workspace: Path,
    artifacts_path: Path,
    artifacts_label: str,
    workspace_model_source: Path,
    classifier_source: Path,
    tesseract_executable: Path,
    tesseract_data_path: Path,
    source_environment: dict[str, str] | None = None,
) -> PreparedProductionRuntime:
    """Derive artifact/dependency identities dynamically from final Settings."""

    root = workspace.resolve()
    artifacts = artifacts_path.resolve(strict=True)
    executable = tesseract_executable.resolve(strict=True)
    tessdata = tesseract_data_path.resolve(strict=True)
    if artifacts.is_symlink() or executable.is_symlink() or tessdata.is_symlink():
        raise ValueError("production dependency endpoints must already be resolved")

    from app.services.parser_worker import artifact_identity, dependency_identity

    observed_artifact = artifact_identity(artifacts)
    if observed_artifact.sha256 != APPROVED_COMBINED_ARTIFACT_SHA256:
        raise ValueError("production artifact is not the reviewed combined tree")
    if classifier_source.resolve(strict=True).name != (
        APPROVED_CLASSIFIER_SNAPSHOT_REVISION
    ):
        raise ValueError("production classifier snapshot revision differs")
    target_before_records, target_before_tree_bytes = _tree_content_records(artifacts)
    if (
        len(target_before_records) != observed_artifact.file_count
        or target_before_tree_bytes != observed_artifact.aggregate_bytes
    ):
        raise RuntimeError("approved artifact observations disagree before preparation")
    common = sanitized_worker_environment(source_environment or os.environ)
    common.update(
        {
            "DOCLING_ARTIFACTS_PATH": str(artifacts),
            "TESSERACT_CMD": str(executable),
            "TESSERACT_DATA_PATH": str(tessdata),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "PARSER_LATENCY_PREWARM_TIMEOUT_SECONDS": "300",
            "PARSER_LATENCY_PREWARM_SHUTDOWN_GRACE_SECONDS": "2",
            "PARSER_LATENCY_PREWARM_ARTIFACTS_SHA256": observed_artifact.sha256,
            "PARSER_LATENCY_PREWARM_DEPENDENCY_SHA256": "0" * 64,
            "PARSER_LATENCY_PREWARM_ENABLED": "true",
        }
    )
    provisional = _settings_from_environment(common)
    provisional_dependency = dependency_identity(provisional)
    common["PARSER_LATENCY_PREWARM_DEPENDENCY_SHA256"] = (
        provisional_dependency.sha256
    )
    final_settings = _settings_from_environment(common)
    final_dependency = dependency_identity(final_settings)
    if final_dependency.sha256 != provisional_dependency.sha256:
        raise RuntimeError("dependency identity changed under final exact Settings")

    artifact_record = ArtifactIdentity(
        path=artifacts_label,
        sha256=observed_artifact.sha256,
        size_bytes=observed_artifact.aggregate_bytes,
    )
    runtime_artifacts: RuntimeArtifactSetIdentity = runtime_artifact_set(
        (artifact_record,)
    )
    runtime_path = Path(sys.executable).resolve(strict=True)
    network_sha256 = derive_production_network_isolation_sha256(root)
    execution = ExecutionIdentity(
        application_code_sha256=derive_candidate_code_sha256(root),
        dependency_manifest_sha256=derive_dependency_lock_sha256(root),
        dependency_runtime_sha256=final_dependency.sha256,
        dependency_runtime=DependencyRuntimeIdentity(
            sha256=final_dependency.sha256,
            distribution_count=final_dependency.distribution_count,
            verified_file_count=final_dependency.verified_file_count,
            verified_aggregate_bytes=final_dependency.verified_aggregate_bytes,
            tesseract_version=final_dependency.tesseract_version,
            language_count=final_dependency.language_count,
        ),
        parser_runtime_sha256=hashlib.sha256(runtime_path.read_bytes()).hexdigest(),
        runtime_artifacts=runtime_artifacts,
        harness_sha256=derive_prewarm_harness_sha256(root),
        lifecycle_cleanup_tests_sha256=derive_lifecycle_cleanup_tests_sha256(root),
        network_isolation_sha256=network_sha256,
    )
    pairing_environment = {
        key: value
        for key, value in common.items()
        if key != "PARSER_LATENCY_PREWARM_ENABLED"
    }
    pairing_sha256 = _canonical_sha256(
        {
            "environment": pairing_environment,
            "endpoint": "/v1/parse",
            "output_format": "json",
            "artifacts_label": artifacts_label,
            "artifacts_path_identity_sha256": _resolved_path_identity(artifacts),
            "tesseract_executable": str(executable),
            "tesseract_data_path": str(tessdata),
        }
    )
    common.pop("PARSER_LATENCY_PREWARM_ENABLED")
    artifact_after = artifact_identity(artifacts)
    target_after_records, target_after_tree_bytes = _tree_content_records(artifacts)
    if artifact_after != observed_artifact:
        raise RuntimeError("approved artifact identity changed during preparation")
    if (
        len(target_after_records) != artifact_after.file_count
        or target_after_tree_bytes != artifact_after.aggregate_bytes
    ):
        raise RuntimeError("approved artifact observations disagree after preparation")
    materialization = _materialization_manifest(
        target_path=artifacts,
        target=artifact_record,
        workspace_model_source=workspace_model_source,
        classifier_source=classifier_source,
        target_metadata_sha256=observed_artifact.metadata_sha256,
        target_file_count=observed_artifact.file_count,
        target_aggregate_bytes=observed_artifact.aggregate_bytes,
        target_before_artifact_sha256=observed_artifact.sha256,
        target_after_artifact_sha256=artifact_after.sha256,
        target_before_metadata_sha256=observed_artifact.metadata_sha256,
        target_after_metadata_sha256=artifact_after.metadata_sha256,
        target_before_file_count=observed_artifact.file_count,
        target_after_file_count=artifact_after.file_count,
        target_before_aggregate_bytes=observed_artifact.aggregate_bytes,
        target_after_aggregate_bytes=artifact_after.aggregate_bytes,
        target_before_records=target_before_records,
        target_after_records=target_after_records,
    )
    return PreparedProductionRuntime(
        common_environment=dict(sorted(common.items())),
        artifact_identity=artifact_record,
        dependency_runtime_sha256=final_dependency.sha256,
        execution=execution,
        pairing_sha256=pairing_sha256,
        artifact_materialization=materialization,
    )


def _finalize_production_artifact_materialization(
    *,
    prepared: PreparedProductionRuntime,
    artifacts_path: Path,
    workspace_model_source: Path,
    classifier_source: Path,
) -> RuntimeArtifactMaterialization:
    """Re-observe the target after every attempt and bind it to preflight."""

    from app.services.parser_worker import artifact_identity

    artifacts = artifacts_path.resolve(strict=True)
    before = artifact_identity(artifacts)
    before_records, before_tree_bytes = _tree_content_records(artifacts)
    after = artifact_identity(artifacts)
    after_records, after_tree_bytes = _tree_content_records(artifacts)
    if (
        len(before_records) != before.file_count
        or before_tree_bytes != before.aggregate_bytes
        or len(after_records) != after.file_count
        or after_tree_bytes != after.aggregate_bytes
    ):
        raise RuntimeError("final artifact observations disagree")
    target = ArtifactIdentity(
        path=prepared.artifact_identity.path,
        sha256=before.sha256,
        size_bytes=before.aggregate_bytes,
    )
    final = _materialization_manifest(
        target_path=artifacts,
        target=target,
        workspace_model_source=workspace_model_source,
        classifier_source=classifier_source,
        target_metadata_sha256=before.metadata_sha256,
        target_file_count=before.file_count,
        target_aggregate_bytes=before.aggregate_bytes,
        target_before_artifact_sha256=before.sha256,
        target_after_artifact_sha256=after.sha256,
        target_before_metadata_sha256=before.metadata_sha256,
        target_after_metadata_sha256=after.metadata_sha256,
        target_before_file_count=before.file_count,
        target_after_file_count=after.file_count,
        target_before_aggregate_bytes=before.aggregate_bytes,
        target_after_aggregate_bytes=after.aggregate_bytes,
        target_before_records=before_records,
        target_after_records=after_records,
    )
    if final != prepared.artifact_materialization:
        raise RuntimeError("final artifact identity differs from preflight custody")
    return final


def _source_identities(registry: PortableCorpusRegistry) -> tuple[SourceIdentity, ...]:
    from tests.benchmarks.latency_profile_set import SOURCE_CUSTODY

    retained = []
    for case in registry.cases:
        source = case.artifacts[0]
        retained.append(
            SourceIdentity(
                case_id=case.case_id,
                path=source.path,
                filename=Path(source.path).name,
                sha256=source.sha256,
                size_bytes=source.size_bytes,
                page_count=case.page_count,
            )
        )
    result = tuple(retained)
    if tuple(item.case_id for item in result) != EXPECTED_CASE_IDS:
        raise ValueError("registry source order differs from LlamaParse-15")
    if tuple(SOURCE_CUSTODY) != PRODUCTION_CASE_IDS or any(
        (item.sha256, item.size_bytes, item.page_count)
        != SOURCE_CUSTODY[item.case_id]
        for item in result
    ):
        raise ValueError("registry sources differ from frozen source custody")
    return result


def _directional_llama_references(
    path: Path,
    sources: tuple[SourceIdentity, ...],
) -> tuple[DirectionalLlamaReference, ...]:
    payload = json.loads(path.read_bytes())
    if (
        type(payload) is not dict
        or payload.get("schema") != "llamaparse-latency-reference-v1"
        or type(payload.get("observations")) is not list
    ):
        raise ValueError("directional Llama reference shape differs")
    latency_by_case = {}
    for row in payload["observations"]:
        if type(row) is not dict or type(row.get("normalized_seconds")) not in {
            int,
            float,
        }:
            raise ValueError("directional Llama row differs")
        latency_by_case[row.get("case_id")] = round(
            row["normalized_seconds"] * 1_000
        )
    if tuple(sorted(latency_by_case)) != tuple(sorted(PRODUCTION_CASE_IDS)):
        raise ValueError("directional Llama reference lacks complete case coverage")
    return tuple(
        DirectionalLlamaReference(
            case_id=source.case_id,
            source_sha256=source.sha256,
            provider_total_latency_ms=latency_by_case[source.case_id],
            source="retained_one_sample_llamaparse_v1",
        )
        for source in sources
    )


def _current_runtime_expectations(
    sources: tuple[SourceIdentity, ...],
) -> tuple[CurrentRuntimeOutputExpectation, ...]:
    from tests.benchmarks.latency_profile_set import (
        CURRENT_RUNTIME_OUTPUT_IDENTITIES,
    )

    if tuple(CURRENT_RUNTIME_OUTPUT_IDENTITIES) != PRODUCTION_CASE_IDS:
        raise ValueError("current-runtime output identity order differs")
    return tuple(
        CurrentRuntimeOutputExpectation(
            case_id=source.case_id,
            source_sha256=source.sha256,
            semantic_sha256=CURRENT_RUNTIME_OUTPUT_IDENTITIES[source.case_id][0],
        )
        for source in sources
    )


def _ensure_private_directory(path: Path) -> Path:
    if not path.exists():
        path.mkdir(mode=0o700, parents=False)
    observed = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISDIR(observed.st_mode)
        or stat.S_IMODE(observed.st_mode) != 0o700
        or observed.st_uid != os.getuid()
    ):
        raise ValueError("retained output directory must be owned mode 0700")
    return path.resolve(strict=True)


def _append_terminal_record_descriptor(
    entries: list[TerminalRecordDescriptor],
    *,
    output_root: Path,
    path: Path,
    segment: Literal[
        "rollback", "rollback_gate", "cross_input", "paired", "campaign_final"
    ],
    record_kind: str,
    topology: Literal[
        "direct-default-off-v1",
        "fork-denied-worker-external-tesseract-broker-v1",
        "campaign-controller-v1",
    ],
    attempt_id: str | None = None,
    case_id: str | None = None,
    case_ordinal: int | None = None,
    attempt_status: AttemptStatus | None = None,
) -> TerminalRecordDescriptor:
    """O_NOFOLLOW-reread one fsynced record into the campaign hash chain."""

    resolved_root = output_root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    try:
        relative_path = resolved.relative_to(resolved_root).as_posix()
    except ValueError as error:
        raise RuntimeError("terminal record escaped output custody") from error
    if any(item.relative_path == relative_path for item in entries):
        raise RuntimeError("terminal record was indexed twice")
    raw, _opened = _read_private_payload_with_identity(
        resolved, maximum_bytes=67_108_864
    )
    retained_ns = max(
        time.monotonic_ns(),
        entries[-1].retained_monotonic_ns + 1 if entries else 1,
    )
    descriptor = terminal_record_descriptor(
        sequence=len(entries) + 1,
        previous_entry_sha256=(
            entries[-1].entry_sha256 if entries else "0" * 64
        ),
        retained_monotonic_ns=retained_ns,
        segment=segment,
        record_kind=record_kind,
        relative_path=relative_path,
        topology=topology,
        attempt_id=attempt_id,
        case_id=case_id,
        case_ordinal=case_ordinal,
        attempt_status=attempt_status,
        content_sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
        file_mode=0o600,
        reopened_no_follow_after_fsync=True,
    )
    entries.append(descriptor)
    return descriptor


def _execution_record_kind(
    *, path: Path, attempt_id: str, receipt_filename: str
) -> str:
    name = path.name
    if name == receipt_filename:
        return (
            "cross-input-receipt"
            if "cross-input" in attempt_id
            else "attempt-receipt"
        )
    request_receipt_prefix = f"{attempt_id}-request-"
    request_receipt_suffix = "-broker-receipt.json"
    if (
        name.startswith(request_receipt_prefix)
        and name.endswith(request_receipt_suffix)
    ):
        sequence_text = name[
            len(request_receipt_prefix) : -len(request_receipt_suffix)
        ]
        if len(sequence_text) != 4 or not sequence_text.isdecimal():
            raise RuntimeError(
                f"unclassified terminal execution record: {name}"
            )
        return "broker-request-receipt"
    suffixes = (
        ("-launch-intent.json", "launch-intent"),
        ("-launch-record.json", "launch-record"),
        ("-launch-failure.json", "launch-failure"),
        ("-phase-deadlines.jsonl", "phase-deadlines"),
        ("-phase-acks.jsonl", "phase-acks"),
        ("-watchdog-terminal.json", "watchdog-terminal"),
        ("-watchdog-launcher.jsonl", "launcher-ledger"),
        ("-artifact-observation.json", "artifact-observation"),
        ("-child-watch.jsonl", "child-watch-ledger"),
        ("-request-control.jsonl", "request-control-ledger"),
        ("-external-cpu-samples.jsonl", "external-cpu-samples"),
        ("-controller-resource-samples.jsonl", "controller-resource-samples"),
        ("-kernel-sandbox-evidence.json", "kernel-sandbox-evidence"),
        ("-native-closure-post.json", "native-closure-post-observation"),
        ("-broker-launch-template.json", "broker-launch-template"),
        ("-broker-ready.json", "broker-ready"),
        ("-supervisor-ready.json", "supervisor-ready"),
        ("-worker-prebind-fatal.json", "worker-prebind-fatal"),
    )
    for suffix, kind in suffixes:
        if name == f"{attempt_id}{suffix}":
            return kind
    raise RuntimeError(f"unclassified terminal execution record: {name}")


def _append_unindexed_attempt_records(
    entries: list[TerminalRecordDescriptor],
    *,
    output_root: Path,
    terminal_directory: Path,
    attempt_id: str,
    receipt_filename: str,
    segment: Literal["cross_input", "paired"],
    case_id: str | None,
    case_ordinal: int | None,
    attempt_status: AttemptStatus,
) -> None:
    indexed = {item.relative_path for item in entries}
    candidates = []
    for path in terminal_directory.iterdir():
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.resolve(strict=True).relative_to(
            output_root.resolve(strict=True)
        ).as_posix()
        if relative in indexed:
            continue
        if path.name == receipt_filename or path.name.startswith(f"{attempt_id}-"):
            candidates.append(path)
    kind_order = {
        kind: index
        for index, kind in enumerate(
            (
                "launch-intent",
                "launch-record",
                "phase-deadlines",
                "phase-acks",
                "watchdog-terminal",
                "launcher-ledger",
                "broker-launch-template",
                "broker-ready",
                "supervisor-ready",
                "child-watch-ledger",
                "request-control-ledger",
                "broker-request-receipt",
                "external-cpu-samples",
                "controller-resource-samples",
                "kernel-sandbox-evidence",
                "native-closure-post-observation",
                "attempt-receipt",
                "cross-input-receipt",
                "artifact-observation",
                "launch-failure",
                "worker-prebind-fatal",
            )
        )
    }
    classified = [
        (
            _execution_record_kind(
                path=path,
                attempt_id=attempt_id,
                receipt_filename=receipt_filename,
            ),
            path,
        )
        for path in candidates
    ]
    for kind, path in sorted(
        classified, key=lambda item: (kind_order[item[0]], item[1].name)
    ):
        _append_terminal_record_descriptor(
            entries,
            output_root=output_root,
            path=path,
            segment=segment,
            record_kind=kind,
            topology="fork-denied-worker-external-tesseract-broker-v1",
            attempt_id=attempt_id,
            case_id=case_id,
            case_ordinal=case_ordinal,
            attempt_status=(
                attempt_status
                if kind in {"attempt-receipt", "cross-input-receipt"}
                else None
            ),
        )


def write_private_canonical(path: Path, model: ContractModel) -> None:
    """Create one canonical JSON evidence file, mode 0600, without overwrite."""

    payload = canonical_model_bytes(model)
    # A controller termination delivered after O_EXCL creation but before the
    # final fsync would otherwise leave a partial immutable receipt.  Treat the
    # complete fsync/stat sequence as the evidence commit point and deliver a
    # pending TERM/HUP immediately after that point.
    with _blocked_controller_termination_signals():
        descriptor = os.open(
            path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            written = 0
            while written < len(payload):
                count = os.write(descriptor, payload[written:])
                if count <= 0:
                    raise RuntimeError("private evidence write did not advance")
                written += count
            os.fsync(descriptor)
            observed = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        if (
            not stat.S_ISREG(observed.st_mode)
            or stat.S_IMODE(observed.st_mode) != 0o600
            or observed.st_uid != os.getuid()
            or observed.st_nlink != 1
            or observed.st_size != len(payload)
        ):
            raise RuntimeError("private evidence file custody differs")


def _write_private_payload(
    path: Path, payload: bytes, *, maximum_bytes: int = 65_536
) -> str:
    """O_EXCL-retain bounded non-JSON protocol evidence with exact custody."""

    if not 1 <= maximum_bytes <= MAXIMUM_PRIVATE_PROTOCOL_EVIDENCE_BYTES:
        raise ValueError("private protocol evidence bound differs")
    if len(payload) > maximum_bytes:
        raise ValueError("private protocol evidence size differs")
    with _blocked_controller_termination_signals():
        descriptor = os.open(
            path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            written = 0
            while written < len(payload):
                count = os.write(descriptor, payload[written:])
                if count <= 0:
                    raise OSError("private protocol evidence write did not advance")
                written += count
            os.fsync(descriptor)
            observed = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        if (
            not stat.S_ISREG(observed.st_mode)
            or stat.S_IMODE(observed.st_mode) != 0o600
            or observed.st_uid != os.getuid()
            or observed.st_nlink != 1
            or observed.st_size != len(payload)
        ):
            raise RuntimeError("private protocol evidence custody differs")
    return hashlib.sha256(payload).hexdigest()


def _read_private_payload(path: Path, *, maximum_bytes: int) -> bytes:
    """Reopen one retained record without symlink traversal and bind its inode."""

    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        observed = os.fstat(descriptor)
        if (
            not stat.S_ISREG(observed.st_mode)
            or stat.S_IMODE(observed.st_mode) != 0o600
            or observed.st_uid != os.getuid()
            or observed.st_nlink != 1
            or observed.st_size < 0
            or observed.st_size > maximum_bytes
        ):
            raise RuntimeError("private retained payload custody differs")
        chunks: list[bytes] = []
        remaining = observed.st_size
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                raise RuntimeError("private retained payload ended early")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        if (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_uid,
            after.st_nlink,
            after.st_size,
            after.st_mtime_ns,
        ) != (
            observed.st_dev,
            observed.st_ino,
            observed.st_mode,
            observed.st_uid,
            observed.st_nlink,
            observed.st_size,
            observed.st_mtime_ns,
        ):
            raise RuntimeError("private retained payload changed while reading")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _read_private_payload_with_identity(
    path: Path, *, maximum_bytes: int
) -> tuple[bytes, os.stat_result]:
    """O_NOFOLLOW reread returning the exact stable fstat identity."""

    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        observed = os.fstat(descriptor)
        if (
            not stat.S_ISREG(observed.st_mode)
            or stat.S_IMODE(observed.st_mode) != 0o600
            or observed.st_uid != os.geteuid()
            or observed.st_nlink != 1
            or observed.st_size <= 0
            or observed.st_size > maximum_bytes
        ):
            raise RuntimeError("private retained payload identity differs")
        chunks: list[bytes] = []
        retained_size = 0
        while retained_size < observed.st_size:
            chunk = os.read(
                descriptor,
                min(1_048_576, observed.st_size - retained_size),
            )
            if not chunk:
                raise RuntimeError("private retained payload ended early")
            chunks.append(chunk)
            retained_size += len(chunk)
        after = os.fstat(descriptor)
        if any(
            getattr(after, field) != getattr(observed, field)
            for field in (
                "st_dev",
                "st_ino",
                "st_mode",
                "st_uid",
                "st_nlink",
                "st_size",
                "st_mtime_ns",
            )
        ):
            raise RuntimeError("private retained payload changed while reading")
        return b"".join(chunks), observed
    finally:
        os.close(descriptor)


def _scan_campaign_output_fd(
    *,
    root_fd: int,
    expected_relative_paths: set[str] | None,
    allow_self_exclusion: bool,
) -> tuple[CampaignClosureEntry, ...]:
    retained: list[CampaignClosureEntry] = []
    observed_directories: set[str] = set()

    def scan(directory_fd: int, prefix: tuple[str, ...]) -> None:
        names = os.listdir(directory_fd)
        if names != sorted(names):
            names = sorted(names)
        if len(names) != len(set(names)):
            raise RuntimeError("campaign output directory returned duplicate names")
        for name in names:
            if (
                not name
                or name in {".", ".."}
                or "/" in name
                or "\x00" in name
            ):
                raise RuntimeError("campaign output member name differs")
            relative_parts = (*prefix, name)
            relative_path = Path(*relative_parts).as_posix()
            observed = os.stat(
                name, dir_fd=directory_fd, follow_symlinks=False
            )
            if stat.S_ISLNK(observed.st_mode):
                raise RuntimeError("campaign output contains a symlink")
            if stat.S_ISDIR(observed.st_mode):
                is_terminal_root = not prefix and name == "terminal"
                is_child_watch_blob_root = (
                    len(prefix) == 1
                    and prefix[0] == "terminal"
                    and re.fullmatch(
                        r"[A-Za-z0-9._-]+-child-watch\.jsonl\.(?:records|events)",
                        name,
                    )
                    is not None
                )
                if not (is_terminal_root or is_child_watch_blob_root):
                    raise RuntimeError("campaign output directory structure differs")
                if (
                    stat.S_IMODE(observed.st_mode) != 0o700
                    or observed.st_uid != os.geteuid()
                ):
                    raise RuntimeError("campaign retained directory custody differs")
                observed_directories.add(relative_path)
                child_fd = os.open(
                    name,
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=directory_fd,
                )
                try:
                    child_stat = os.fstat(child_fd)
                    if (
                        child_stat.st_dev != observed.st_dev
                        or child_stat.st_ino != observed.st_ino
                        or child_stat.st_mode != observed.st_mode
                    ):
                        raise RuntimeError("campaign terminal directory drifted")
                    scan(child_fd, relative_parts)
                finally:
                    os.close(child_fd)
                continue
            if not stat.S_ISREG(observed.st_mode):
                raise RuntimeError("campaign output contains an unexpected type")
            if len(prefix) == 2:
                blob_pattern = (
                    r"r[0-9]{8}-[0-9a-f]{16}\.json"
                    if prefix[-1].endswith(".records")
                    else r"e[0-9]{8}-[0-9a-f]{16}\.json"
                )
                if re.fullmatch(blob_pattern, name) is None:
                    raise RuntimeError("campaign child-watch blob name differs")
            if relative_path == "campaign-closure.json":
                if allow_self_exclusion:
                    continue
                raise FileExistsError("campaign closure existed before final commit")
            descriptor = os.open(
                name,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_fd,
            )
            try:
                opened = os.fstat(descriptor)
                if (
                    opened.st_dev != observed.st_dev
                    or opened.st_ino != observed.st_ino
                    or opened.st_mode != observed.st_mode
                    or stat.S_IMODE(opened.st_mode) != 0o600
                    or opened.st_uid != os.geteuid()
                    or opened.st_nlink != 1
                    or opened.st_size < 0
                ):
                    raise RuntimeError("campaign output file custody differs")
                digest = hashlib.sha256()
                remaining = opened.st_size
                while remaining:
                    chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                    if not chunk:
                        raise RuntimeError("campaign output file read was short")
                    digest.update(chunk)
                    remaining -= len(chunk)
                after = os.fstat(descriptor)
                if any(
                    getattr(after, field) != getattr(opened, field)
                    for field in (
                        "st_dev",
                        "st_ino",
                        "st_mode",
                        "st_uid",
                        "st_nlink",
                        "st_size",
                        "st_mtime_ns",
                    )
                ):
                    raise RuntimeError("campaign output file changed during scan")
            finally:
                os.close(descriptor)
            retained.append(
                CampaignClosureEntry(
                    relative_path=relative_path,
                    device=opened.st_dev,
                    inode=opened.st_ino,
                    mode=stat.S_IMODE(opened.st_mode),
                    uid=opened.st_uid,
                    nlink=opened.st_nlink,
                    size_bytes=opened.st_size,
                    content_sha256=digest.hexdigest(),
                )
            )

    scan(root_fd, ())
    observed_paths = {item.relative_path for item in retained}
    nested_roots = observed_directories - {"terminal"}
    main_ledgers = {
        path
        for path in observed_paths
        if len(Path(path).parts) == 2
        and path.startswith("terminal/")
        and path.endswith("-child-watch.jsonl")
    }
    expected_nested_roots = {
        f"{path}.records" for path in main_ledgers
    } | {f"{path}.events" for path in main_ledgers}
    nested_blob_paths = {
        path
        for path in observed_paths
        if len(Path(path).parts) == 3
        and Path(path).parts[:2]
        in {
            tuple(Path(root).parts) for root in expected_nested_roots
        }
    }
    if (
        "terminal" not in observed_directories
        or nested_roots != expected_nested_roots
        or any(
            len(Path(path).parts) == 3 and path not in nested_blob_paths
            for path in observed_paths
        )
        or (
            expected_relative_paths is not None
            and (
                not expected_relative_paths.issubset(observed_paths)
                or observed_paths - expected_relative_paths
                != nested_blob_paths
            )
        )
    ):
        raise RuntimeError("campaign closure output membership differs")
    inode_keys = {(item.device, item.inode) for item in retained}
    if len(inode_keys) != len(retained):
        raise RuntimeError("campaign output reused a file inode")
    return tuple(sorted(retained, key=lambda item: item.relative_path))


class _CampaignFailureClosureUnavailable(RuntimeError):
    """The retained prefix is diagnostic, but cannot support a final claim."""


def _campaign_entries_sha256(
    entries: tuple[CampaignClosureEntry, ...],
) -> str:
    return _canonical_sha256(
        [item.model_dump(mode="json") for item in entries]
    )


def _read_campaign_output_member(
    *,
    root_fd: int,
    relative_path: str,
    maximum_bytes: int,
) -> tuple[bytes, os.stat_result]:
    """Descriptor-relative, no-follow stable reread of one closure member."""

    path = Path(relative_path)
    if (
        path.is_absolute()
        or relative_path != path.as_posix()
        or not path.parts
        or len(path.parts) > 2
        or any(part in {"", ".", ".."} for part in path.parts)
        or (len(path.parts) == 2 and path.parts[0] != "terminal")
        or isinstance(maximum_bytes, bool)
        or maximum_bytes <= 0
    ):
        raise RuntimeError("campaign member path/bound differs")
    directory_fd = os.dup(root_fd)
    try:
        if len(path.parts) == 2:
            child_fd = os.open(
                path.parts[0],
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = child_fd
        descriptor = os.open(
            path.parts[-1],
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_fd,
        )
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or stat.S_IMODE(opened.st_mode) != 0o600
                or opened.st_uid != os.geteuid()
                or opened.st_nlink != 1
                or opened.st_size <= 0
                or opened.st_size > maximum_bytes
            ):
                raise RuntimeError("campaign member file custody differs")
            retained = bytearray()
            while len(retained) < opened.st_size:
                chunk = os.read(
                    descriptor,
                    min(1_048_576, opened.st_size - len(retained)),
                )
                if not chunk:
                    raise RuntimeError("campaign member reread was short")
                retained.extend(chunk)
            after = os.fstat(descriptor)
            if any(
                getattr(after, field) != getattr(opened, field)
                for field in (
                    "st_dev",
                    "st_ino",
                    "st_mode",
                    "st_uid",
                    "st_nlink",
                    "st_size",
                    "st_mtime_ns",
                )
            ):
                raise RuntimeError("campaign member changed during reread")
            return bytes(retained), opened
        finally:
            os.close(descriptor)
    finally:
        os.close(directory_fd)


def _campaign_output_prefix_vnodes(
    *,
    root_fd: int,
    root_stat: os.stat_result,
    entries: tuple[CampaignClosureEntry, ...],
) -> tuple[CampaignOutputVnodeIdentity, ...]:
    terminal_observed = os.stat(
        "terminal", dir_fd=root_fd, follow_symlinks=False
    )
    terminal_fd = os.open(
        "terminal",
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=root_fd,
    )
    try:
        terminal_opened = os.fstat(terminal_fd)
    finally:
        os.close(terminal_fd)
    if (
        not stat.S_ISDIR(terminal_opened.st_mode)
        or stat.S_IMODE(terminal_opened.st_mode) != 0o700
        or terminal_opened.st_uid != os.geteuid()
        or any(
            getattr(terminal_opened, field)
            != getattr(terminal_observed, field)
            for field in ("st_dev", "st_ino", "st_mode", "st_uid", "st_nlink")
        )
    ):
        raise RuntimeError("campaign terminal vnode custody differs")
    vnodes = (
        CampaignOutputVnodeIdentity(
            relative_path=".",
            device=root_stat.st_dev,
            inode=root_stat.st_ino,
            mode=stat.S_IMODE(root_stat.st_mode),
            uid=root_stat.st_uid,
            nlink=root_stat.st_nlink,
        ),
        CampaignOutputVnodeIdentity(
            relative_path="terminal",
            device=terminal_opened.st_dev,
            inode=terminal_opened.st_ino,
            mode=stat.S_IMODE(terminal_opened.st_mode),
            uid=terminal_opened.st_uid,
            nlink=terminal_opened.st_nlink,
        ),
        *(
            CampaignOutputVnodeIdentity(
                relative_path=item.relative_path,
                device=item.device,
                inode=item.inode,
                mode=item.mode,
                uid=item.uid,
                nlink=item.nlink,
            )
            for item in entries
        ),
    )
    ordered = tuple(sorted(vnodes, key=lambda item: item.relative_path))
    if len({(item.device, item.inode) for item in ordered}) != len(ordered):
        raise RuntimeError("campaign output vnode identity was reused")
    return ordered


def _campaign_model_from_member(
    *,
    root_fd: int,
    relative_path: str,
    model: type[ContractModel],
    maximum_bytes: int = 67_108_864,
) -> tuple[ContractModel, bytes]:
    raw, _opened = _read_campaign_output_member(
        root_fd=root_fd,
        relative_path=relative_path,
        maximum_bytes=maximum_bytes,
    )
    value = model.model_validate_json(raw)
    if canonical_model_bytes(value) != raw:
        raise RuntimeError("campaign member model is not canonical")
    return value, raw


def _campaign_receipt_model(
    *, root_fd: int, relative_path: str
) -> tuple[
    ProductionAttemptReceipt
    | DirectRollbackAttemptReceipt
    | DirectRollbackFailureReceipt
    | CrossInputControlReceipt,
    bytes,
]:
    raw, _opened = _read_campaign_output_member(
        root_fd=root_fd,
        relative_path=relative_path,
        maximum_bytes=67_108_864,
    )
    try:
        header = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("campaign receipt is not JSON") from error
    if type(header) is not dict or type(header.get("schema_id")) is not str:
        raise RuntimeError("campaign receipt schema is absent")
    receipt_model: type[ContractModel] | None = {
        "phase-latency-prewarm-attempt-receipt-v1": ProductionAttemptReceipt,
        "phase-latency-direct-rollback-attempt-receipt-v1": (
            DirectRollbackAttemptReceipt
        ),
        "phase-latency-direct-rollback-failure-receipt-v1": (
            DirectRollbackFailureReceipt
        ),
        "phase-latency-prewarm-cross-input-receipt-v1": CrossInputControlReceipt,
    }.get(header["schema_id"])
    if receipt_model is None:
        raise RuntimeError("campaign receipt schema differs")
    receipt = receipt_model.model_validate_json(raw)
    if canonical_model_bytes(receipt) != raw:
        raise RuntimeError("campaign receipt is not canonical")
    if not isinstance(
        receipt,
        (
            ProductionAttemptReceipt,
            DirectRollbackAttemptReceipt,
            DirectRollbackFailureReceipt,
            CrossInputControlReceipt,
        ),
    ):
        raise RuntimeError("campaign receipt model differs")
    return receipt, raw


_CAMPAIGN_GLOBAL_TERMINAL_ARTIFACT_PATHS = frozenset(
    {
        "terminal/lat-us02-rollback-evidence.json",
        "terminal/lat-us02-rollback-submanifest.json",
        "terminal/campaign-final-artifact-observation.json",
    }
)
_CAMPAIGN_FAILURE_ALLOWED_ROOT_ARTIFACT_PATHS = frozenset(
    {
        "lat-us02-production-plan.json",
        "lat-us02-production-final-artifact-manifest.json",
        "lat-us02-terminal-record-manifest.json",
        "lat-us02-production-evidence.json",
        "lat-us02-production-evaluation.json",
    }
)


def _campaign_attempt_artifact_bindings(
    *,
    entries_by_path: Mapping[str, CampaignClosureEntry],
    attempt_id: str,
    receipt_relative_path: str,
) -> tuple[CampaignTerminalArtifactBinding, ...]:
    bindings: list[CampaignTerminalArtifactBinding] = []
    receipt_filename = Path(receipt_relative_path).name
    for relative_path, entry in sorted(entries_by_path.items()):
        path = Path(relative_path)
        if len(path.parts) != 2 or path.parts[0] != "terminal":
            continue
        if path.name == f"{attempt_id}-immutable-input-custody.json":
            record_kind = "immutable-input-custody"
        else:
            try:
                record_kind = _execution_record_kind(
                    path=path,
                    attempt_id=attempt_id,
                    receipt_filename=receipt_filename,
                )
            except RuntimeError:
                continue
        fields: dict[str, object] = {
            "relative_path": relative_path,
            "record_kind": record_kind,
            "content_sha256": entry.content_sha256,
            "size_bytes": entry.size_bytes,
        }
        bindings.append(
            CampaignTerminalArtifactBinding(
                **fields, record_sha256=_canonical_sha256(fields)
            )
        )
    return tuple(bindings)


def _require_campaign_global_terminal_artifacts(
    *,
    root_fd: int,
    entries_by_path: Mapping[str, CampaignClosureEntry],
) -> set[str]:
    present = {
        path
        for path in _CAMPAIGN_GLOBAL_TERMINAL_ARTIFACT_PATHS
        if path in entries_by_path
    }
    rollback_evidence_path = "terminal/lat-us02-rollback-evidence.json"
    rollback_submanifest_path = "terminal/lat-us02-rollback-submanifest.json"
    if (rollback_evidence_path in present) != (
        rollback_submanifest_path in present
    ):
        raise RuntimeError("campaign rollback gate terminal pair is incomplete")
    if rollback_evidence_path in present:
        evidence, _evidence_raw = _campaign_model_from_member(
            root_fd=root_fd,
            relative_path=rollback_evidence_path,
            model=UninstrumentedRollbackEvidence,
        )
        submanifest, _submanifest_raw = _campaign_model_from_member(
            root_fd=root_fd,
            relative_path=rollback_submanifest_path,
            model=TerminalRecordSubmanifest,
        )
        assert isinstance(evidence, UninstrumentedRollbackEvidence)
        assert isinstance(submanifest, TerminalRecordSubmanifest)
        if (
            evidence.terminal_records != submanifest
            or evidence.terminal_record_manifest_sha256
            != submanifest.manifest_sha256
        ):
            raise RuntimeError("campaign rollback gate terminal join differs")
    final_artifact_path = "terminal/campaign-final-artifact-observation.json"
    if final_artifact_path in present:
        observation, _observation_raw = _campaign_model_from_member(
            root_fd=root_fd,
            relative_path=final_artifact_path,
            model=PostAttemptArtifactObservation,
        )
        assert isinstance(observation, PostAttemptArtifactObservation)
        if observation.attempt_id != "campaign-final":
            raise RuntimeError("campaign final artifact observation differs")
    return present


def _campaign_receipt_terminal_disposition(
    *,
    root_fd: int,
    entries_by_path: Mapping[str, CampaignClosureEntry],
    intent: ProductionLaunchIntent,
    intent_relative_path: str,
    intent_raw: bytes,
) -> CampaignReceiptTerminalDisposition:
    attempt_id = intent.attempt_id
    receipt_candidates = tuple(
        path
        for path in (
            f"terminal/{attempt_id}.json",
            f"terminal/{attempt_id}-receipt.json",
        )
        if path in entries_by_path
    )
    if len(receipt_candidates) != 1:
        # The launcher currently does not retain the ECHILD/no-group proof which
        # would make its root-less launch-failure row authoritative.  Never turn
        # that vacuous legacy Boolean into a final pre-spawn disposition.
        raise RuntimeError("launch intent lacks one typed terminal receipt")
    receipt_relative_path = receipt_candidates[0]
    receipt, receipt_raw = _campaign_receipt_model(
        root_fd=root_fd, relative_path=receipt_relative_path
    )
    receipt_attempt_id = (
        receipt.control_id
        if isinstance(receipt, CrossInputControlReceipt)
        else receipt.attempt_id
    )
    if (
        receipt_attempt_id != attempt_id
        or receipt.launch_intent_sha256 != intent.intent_sha256
        or receipt.launcher_terminal_evidence is None
        or receipt.watchdog_terminal is None
        or receipt.watchdog_terminal_sha256 is None
        or not receipt.watchdog_reaped
        or not receipt.watchdog_process_group_gone
    ):
        raise RuntimeError("campaign receipt launch/watchdog custody differs")
    launcher = receipt.launcher_terminal_evidence
    watchdog_terminal = receipt.watchdog_terminal
    expected_roles = (
        ("broker", "worker")
        if intent.managed_group_policy.endswith("broker-v1")
        else ("worker",)
    )
    if (
        launcher.attempt_id != attempt_id
        or launcher.controller != intent.controller
        or not _launcher_terminal_matches_watchdog(launcher, watchdog_terminal)
        or tuple(sorted(launcher.root_returncodes)) != expected_roles
        or tuple(sorted(launcher.root_wait4_record_sha256s)) != expected_roles
        or tuple(sorted(launcher.root_wait4_log_row_sha256s)) != expected_roles
    ):
        raise RuntimeError("campaign receipt launcher binding differs")
    if isinstance(receipt, (ProductionAttemptReceipt, CrossInputControlReceipt)):
        if (
            not receipt.all_group_members_gone
            or (
                intent.managed_group_policy.endswith("broker-v1")
                and (
                    not receipt.broker_reaped
                    or not receipt.broker_process_group_gone
                )
            )
        ):
            raise RuntimeError("campaign receipt producer groups are not gone")
    elif isinstance(receipt, DirectRollbackFailureReceipt):
        if not receipt.worker_process_group_gone:
            raise RuntimeError("direct rollback worker group is not gone")
    elif not receipt.worker_process_group_gone:
        raise RuntimeError("direct rollback worker group is not gone")

    launcher_relative_path = f"terminal/{attempt_id}-watchdog-launcher.jsonl"
    watchdog_relative_path = f"terminal/{attempt_id}-watchdog-terminal.json"
    launcher_entry = entries_by_path.get(launcher_relative_path)
    watchdog_entry = entries_by_path.get(watchdog_relative_path)
    if (
        launcher_entry is None
        or watchdog_entry is None
        or launcher_entry.content_sha256 != launcher.log_sha256
        or launcher_entry.size_bytes != launcher.log_size_bytes
        or watchdog_entry.content_sha256 != receipt.watchdog_terminal_sha256
    ):
        raise RuntimeError("campaign receipt terminal file custody differs")
    launcher_raw, _launcher_stat = _read_campaign_output_member(
        root_fd=root_fd,
        relative_path=launcher_relative_path,
        maximum_bytes=1_048_576,
    )
    watchdog_raw, _watchdog_stat = _read_campaign_output_member(
        root_fd=root_fd,
        relative_path=watchdog_relative_path,
        maximum_bytes=1_048_576,
    )
    if (
        launcher_raw.decode("utf-8", errors="strict")
        != launcher.raw_log_canonical_jsonl
        or watchdog_raw != canonical_model_bytes(watchdog_terminal)
    ):
        raise RuntimeError("campaign receipt terminal bytes differ")

    roots: list[CampaignLauncherRootTerminalDisposition] = []
    for role in expected_roles:
        root = launcher.broker_root if role == "broker" else launcher.worker_root
        if root is None:
            raise RuntimeError("campaign receipt launcher root is absent")
        root_fields = {
            "role": role,
            "root": root,
            "returncode": launcher.root_returncodes[role],
            "wait4_record_sha256": launcher.root_wait4_record_sha256s[role],
            "wait4_log_row_sha256": launcher.root_wait4_log_row_sha256s[role],
            "group_esrch_after_wait4": True,
        }
        roots.append(
            CampaignLauncherRootTerminalDisposition(
                **root_fields, record_sha256=_canonical_sha256(root_fields)
            )
        )

    launch_record_relative_path = f"terminal/{attempt_id}-launch-record.json"
    launch_record: ProductionLaunchRecord | None = None
    launch_record_raw: bytes | None = None
    if launch_record_relative_path in entries_by_path:
        parsed, launch_record_raw = _campaign_model_from_member(
            root_fd=root_fd,
            relative_path=launch_record_relative_path,
            model=ProductionLaunchRecord,
        )
        assert isinstance(parsed, ProductionLaunchRecord)
        launch_record = parsed
        if (
            launch_record.attempt_id != attempt_id
            or launch_record.intent_sha256 != intent.intent_sha256
            or launch_record.launch_sha256 != receipt.launch_record_sha256
        ):
            raise RuntimeError("campaign launch record binding differs")
    elif receipt.launch_record_sha256 is not None:
        raise RuntimeError("campaign receipt launch record is absent")

    launch_failure_relative_path = f"terminal/{attempt_id}-launch-failure.json"
    launch_failure: ProductionLaunchFailureRecord | None = None
    launch_failure_raw: bytes | None = None
    if launch_failure_relative_path in entries_by_path:
        parsed, launch_failure_raw = _campaign_model_from_member(
            root_fd=root_fd,
            relative_path=launch_failure_relative_path,
            model=ProductionLaunchFailureRecord,
        )
        assert isinstance(parsed, ProductionLaunchFailureRecord)
        launch_failure = parsed
        if (
            launch_failure.attempt_id != attempt_id
            or launch_failure.intent_sha256 != intent.intent_sha256
            or launch_failure.controller != intent.controller
        ):
            raise RuntimeError("campaign launch failure binding differs")
        retained_failure_sha = getattr(
            receipt, "launch_failure_record_sha256", None
        )
        if (
            hasattr(receipt, "launch_failure_record_sha256")
            and retained_failure_sha != launch_failure.record_sha256
        ):
            raise RuntimeError("campaign receipt launch failure hash differs")
    elif getattr(receipt, "launch_failure_record_sha256", None) is not None:
        raise RuntimeError("campaign receipt launch failure record is absent")

    attempt_artifacts = _campaign_attempt_artifact_bindings(
        entries_by_path=entries_by_path,
        attempt_id=attempt_id,
        receipt_relative_path=receipt_relative_path,
    )
    artifacts_by_kind: dict[str, tuple[CampaignTerminalArtifactBinding, ...]] = {
        kind: tuple(item for item in attempt_artifacts if item.record_kind == kind)
        for kind in {item.record_kind for item in attempt_artifacts}
    }

    def require_bound_content(kind: str, expected_sha256: str | None) -> None:
        retained = artifacts_by_kind.get(kind, ())
        if expected_sha256 is None:
            if retained:
                raise RuntimeError(
                    f"campaign receipt retained unbound {kind} artifact"
                )
            return
        if len(retained) != 1 or retained[0].content_sha256 != expected_sha256:
            raise RuntimeError(f"campaign receipt {kind} artifact differs")

    require_bound_content("phase-deadlines", receipt.phase_deadline_log_sha256)
    require_bound_content("phase-acks", receipt.phase_ack_log_sha256)
    request_control = getattr(receipt, "terminal_request_control_transcript", None)
    require_bound_content(
        "request-control-ledger",
        request_control.sha256 if request_control is not None else None,
    )
    immutable_custody = getattr(receipt, "immutable_input_custody", None)
    require_bound_content(
        "immutable-input-custody",
        (
            hashlib.sha256(canonical_model_bytes(immutable_custody)).hexdigest()
            if immutable_custody is not None
            else None
        ),
    )

    fields: dict[str, object] = {
        "schema_id": "phase-latency-campaign-receipt-disposition-v1",
        "disposition": "receipt",
        "attempt_id": attempt_id,
        "intent": intent,
        "intent_relative_path": intent_relative_path,
        "intent_content_sha256": hashlib.sha256(intent_raw).hexdigest(),
        "receipt_relative_path": receipt_relative_path,
        "receipt_schema_id": receipt.schema_id,
        "receipt_content_sha256": hashlib.sha256(receipt_raw).hexdigest(),
        "launcher_ledger_relative_path": launcher_relative_path,
        "launcher_ledger_content_sha256": hashlib.sha256(launcher_raw).hexdigest(),
        "launcher_terminal_record_sha256": launcher.terminal_record_sha256,
        "watchdog_terminal_relative_path": watchdog_relative_path,
        "watchdog_terminal_content_sha256": hashlib.sha256(watchdog_raw).hexdigest(),
        "controller": intent.controller,
        "roots": tuple(roots),
        "attempt_artifacts": attempt_artifacts,
        "watchdog_reaped": True,
        "watchdog_group_esrch": True,
        "all_producer_groups_esrch": True,
        "launch_record_relative_path": (
            launch_record_relative_path if launch_record is not None else None
        ),
        "launch_record_content_sha256": (
            hashlib.sha256(launch_record_raw).hexdigest()
            if launch_record_raw is not None
            else None
        ),
        "launch_record_sha256": (
            launch_record.launch_sha256 if launch_record is not None else None
        ),
        "launch_failure_relative_path": (
            launch_failure_relative_path if launch_failure is not None else None
        ),
        "launch_failure_content_sha256": (
            hashlib.sha256(launch_failure_raw).hexdigest()
            if launch_failure_raw is not None
            else None
        ),
        "launch_failure_record_sha256": (
            launch_failure.record_sha256 if launch_failure is not None else None
        ),
    }
    return CampaignReceiptTerminalDisposition(
        **fields, record_sha256=_canonical_sha256(fields)
    )


def _campaign_launch_terminal_dispositions(
    *,
    root_fd: int,
    entries: tuple[CampaignClosureEntry, ...],
) -> tuple[CampaignReceiptTerminalDisposition, ...]:
    entries_by_path = {item.relative_path: item for item in entries}
    root_artifact_paths = {
        path for path in entries_by_path if len(Path(path).parts) == 1
    }
    if not root_artifact_paths.issubset(
        _CAMPAIGN_FAILURE_ALLOWED_ROOT_ARTIFACT_PATHS
    ):
        raise RuntimeError("campaign failure root artifact membership differs")
    intent_paths = tuple(
        sorted(
            path
            for path in entries_by_path
            if path.startswith("terminal/")
            and path.endswith("-launch-intent.json")
        )
    )
    dispositions: list[CampaignReceiptTerminalDisposition] = []
    attempt_ids: set[str] = set()
    for intent_relative_path in intent_paths:
        parsed, intent_raw = _campaign_model_from_member(
            root_fd=root_fd,
            relative_path=intent_relative_path,
            model=ProductionLaunchIntent,
        )
        assert isinstance(parsed, ProductionLaunchIntent)
        intent = parsed
        if (
            intent.attempt_id in attempt_ids
            or intent_relative_path
            != f"terminal/{intent.attempt_id}-launch-intent.json"
            or entries_by_path[intent_relative_path].content_sha256
            != hashlib.sha256(intent_raw).hexdigest()
        ):
            raise RuntimeError("campaign launch intent identity differs")
        attempt_ids.add(intent.attempt_id)
        dispositions.append(
            _campaign_receipt_terminal_disposition(
                root_fd=root_fd,
                entries_by_path=entries_by_path,
                intent=intent,
                intent_relative_path=intent_relative_path,
                intent_raw=intent_raw,
            )
        )
    retained = tuple(sorted(dispositions, key=lambda item: item.attempt_id))
    global_terminal_paths = _require_campaign_global_terminal_artifacts(
        root_fd=root_fd, entries_by_path=entries_by_path
    )
    owned_paths = tuple(
        artifact.relative_path
        for disposition in retained
        for artifact in disposition.attempt_artifacts
    )
    if len(owned_paths) != len(set(owned_paths)):
        raise RuntimeError("campaign terminal artifact ownership overlaps")
    flat_terminal_paths = {
        path
        for path in entries_by_path
        if len(Path(path).parts) == 2 and Path(path).parts[0] == "terminal"
    }
    if flat_terminal_paths != set(owned_paths) | global_terminal_paths:
        raise RuntimeError("campaign terminal artifact lacks one typed disposition")
    return retained


def _write_campaign_closure_manifest(
    *,
    output_root: Path,
    expected_relative_paths: set[str],
    producer_groups_esrch: bool,
    terminal_manifest_sha256: str,
    bundle_sha256: str,
    evaluation_sha256: str,
) -> Path:
    if not producer_groups_esrch:
        raise RuntimeError("campaign producers were not kernel-quiescent")
    resolved_root = output_root.resolve(strict=True)
    root_fd = os.open(
        resolved_root,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    closure_path = resolved_root / "campaign-closure.json"
    try:
        root_stat = os.fstat(root_fd)
        if (
            not stat.S_ISDIR(root_stat.st_mode)
            or stat.S_IMODE(root_stat.st_mode) != 0o700
            or root_stat.st_uid != os.geteuid()
        ):
            raise RuntimeError("campaign output root custody differs")
        entries = _scan_campaign_output_fd(
            root_fd=root_fd,
            expected_relative_paths=expected_relative_paths,
            allow_self_exclusion=False,
        )
        fields: dict[str, object] = {
            "schema_id": "phase-latency-campaign-closure-manifest-v1",
            "campaign_id": "LAT-US02",
            "status": "success",
            "output_root": CampaignClosureOutputRootIdentity(
                resolved_path=str(resolved_root),
                device=root_stat.st_dev,
                inode=root_stat.st_ino,
                mode=stat.S_IMODE(root_stat.st_mode),
                uid=root_stat.st_uid,
                nlink=root_stat.st_nlink,
                descriptor_opened_o_directory=True,
                descriptor_opened_o_nofollow=True,
            ),
            "entries": entries,
            "entry_count": len(entries),
            "aggregate_bytes": sum(item.size_bytes for item in entries),
            "sole_self_exclusion": "campaign-closure.json",
            "producer_groups_esrch": True,
            "writer_fds_closed": True,
            "fsync_completed": True,
            "terminal_manifest_sha256": terminal_manifest_sha256,
            "bundle_sha256": bundle_sha256,
            "evaluation_sha256": evaluation_sha256,
            "completed_at_monotonic_ns": max(1, time.monotonic_ns()),
        }
        provisional = CampaignClosureManifest.model_construct(
            **fields, record_sha256="0" * 64
        )
        closure = CampaignClosureManifest(
            **fields,
            record_sha256=_canonical_sha256(
                provisional.model_dump(mode="json", exclude={"record_sha256"})
            ),
        )
        payload = canonical_model_bytes(closure)
        with _blocked_controller_termination_signals():
            descriptor = os.open(
                "campaign-closure.json",
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=root_fd,
            )
            try:
                offset = 0
                while offset < len(payload):
                    written = os.write(descriptor, payload[offset:])
                    if written <= 0:
                        raise RuntimeError("campaign closure write made no progress")
                    offset += written
                os.fsync(descriptor)
                closure_stat = os.fstat(descriptor)
            finally:
                os.close(descriptor)
            os.fsync(root_fd)
        if (
            not stat.S_ISREG(closure_stat.st_mode)
            or stat.S_IMODE(closure_stat.st_mode) != 0o600
            or closure_stat.st_uid != os.geteuid()
            or closure_stat.st_nlink != 1
            or closure_stat.st_size != len(payload)
        ):
            raise RuntimeError("campaign closure file custody differs")
        reread_fd = os.open(
            "campaign-closure.json",
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=root_fd,
        )
        try:
            reread = b""
            while len(reread) < len(payload):
                chunk = os.read(reread_fd, len(payload) - len(reread))
                if not chunk:
                    raise RuntimeError("campaign closure reread was short")
                reread += chunk
            reread_stat = os.fstat(reread_fd)
        finally:
            os.close(reread_fd)
        if reread != payload or any(
            getattr(reread_stat, field) != getattr(closure_stat, field)
            for field in ("st_dev", "st_ino", "st_mode", "st_uid", "st_nlink", "st_size")
        ):
            raise RuntimeError("campaign closure changed after fsync")
        if _scan_campaign_output_fd(
            root_fd=root_fd,
            expected_relative_paths=expected_relative_paths,
            allow_self_exclusion=True,
        ) != entries:
            raise RuntimeError("campaign output changed during closure commit")
    finally:
        os.close(root_fd)
    return closure_path


def _write_quiescent_campaign_failure_closure(
    *, output_root: Path, failure: FailureRecord
) -> Path:
    """Commit a final failed prefix only after kernel-backed quiescence proof.

    Any missing pre-commit proof raises ``_CampaignFailureClosureUnavailable``;
    the caller may then retain the deliberately nonfinal diagnostic marker.  A
    failure after O_EXCL creation is never downgraded to that marker.
    """

    resolved_root = output_root.resolve(strict=True)
    root_fd = os.open(
        resolved_root,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    closure_path = resolved_root / "campaign-closure.json"
    try:
        root_stat = os.fstat(root_fd)
        if (
            not stat.S_ISDIR(root_stat.st_mode)
            or stat.S_IMODE(root_stat.st_mode) != 0o700
            or root_stat.st_uid != os.geteuid()
        ):
            raise _CampaignFailureClosureUnavailable(
                "campaign failure root custody differs"
            )
        try:
            initial_entries = _scan_campaign_output_fd(
                root_fd=root_fd,
                expected_relative_paths=None,
                allow_self_exclusion=False,
            )
            if not any(
                item.relative_path == "lat-us02-production-plan.json"
                for item in initial_entries
            ):
                raise RuntimeError("campaign failure prefix lacks its plan")
            dispositions = _campaign_launch_terminal_dispositions(
                root_fd=root_fd, entries=initial_entries
            )
            terminal_manifest_sha256: str | None = None
            terminal_manifest_relative = "lat-us02-terminal-record-manifest.json"
            if any(
                item.relative_path == terminal_manifest_relative
                for item in initial_entries
            ):
                parsed, _raw = _campaign_model_from_member(
                    root_fd=root_fd,
                    relative_path=terminal_manifest_relative,
                    model=TerminalRecordManifest,
                )
                assert isinstance(parsed, TerminalRecordManifest)
                terminal_manifest_sha256 = parsed.manifest_sha256
        except BaseException as error:
            raise _CampaignFailureClosureUnavailable(
                "campaign failure terminal dispositions are incomplete"
            ) from error

        with _blocked_controller_termination_signals():
            try:
                from app.services.tesseract_broker_native import (
                    native_detailed_file_descriptor_inventory,
                    native_detailed_thread_inventory,
                )

                expected_signals = tuple(
                    sorted((int(signal.SIGHUP), int(signal.SIGTERM)))
                )
                mask_before = tuple(
                    sorted(
                        int(item)
                        for item in signal.pthread_sigmask(
                            signal.SIG_BLOCK, set()
                        )
                    )
                )
                if not set(expected_signals).issubset(mask_before):
                    raise RuntimeError(
                        "campaign failure termination signals are not blocked"
                    )
                entry_threads = NativeThreadInventory.model_validate(
                    asdict(native_detailed_thread_inventory(os.getpid()))
                )
                if entry_threads.thread_count != 1:
                    raise RuntimeError(
                        "campaign failure controller is not single-threaded"
                    )
                fd_inventory = NativeFileDescriptorInventory.model_validate(
                    asdict(
                        native_detailed_file_descriptor_inventory(os.getpid())
                    )
                )
                first_started = max(1, time.monotonic_ns())
                first_entries = _scan_campaign_output_fd(
                    root_fd=root_fd,
                    expected_relative_paths={
                        item.relative_path for item in initial_entries
                    },
                    allow_self_exclusion=False,
                )
                first_vnodes = _campaign_output_prefix_vnodes(
                    root_fd=root_fd,
                    root_stat=root_stat,
                    entries=first_entries,
                )
                first_completed = max(first_started, time.monotonic_ns())
                second_started = max(first_completed, time.monotonic_ns())
                second_entries = _scan_campaign_output_fd(
                    root_fd=root_fd,
                    expected_relative_paths={
                        item.relative_path for item in initial_entries
                    },
                    allow_self_exclusion=False,
                )
                second_vnodes = _campaign_output_prefix_vnodes(
                    root_fd=root_fd,
                    root_stat=root_stat,
                    entries=second_entries,
                )
                second_completed = max(second_started, time.monotonic_ns())
                if (
                    first_entries != initial_entries
                    or second_entries != first_entries
                    or second_vnodes != first_vnodes
                ):
                    raise RuntimeError(
                        "campaign failure output changed during its final scans"
                    )
                vnode_keys = {
                    (item.device, item.inode) for item in second_vnodes
                }
                writable_output_fds = tuple(
                    item.fd
                    for item in fd_inventory.descriptors
                    if item.vnode is not None
                    and (item.vnode.device, item.vnode.inode) in vnode_keys
                    and bool(item.open_flags & 0x2)
                )
                if writable_output_fds:
                    raise RuntimeError(
                        "campaign failure output retains a writable vnode FD"
                    )
                precommit_threads = NativeThreadInventory.model_validate(
                    asdict(native_detailed_thread_inventory(os.getpid()))
                )
                mask_before_commit = tuple(
                    sorted(
                        int(item)
                        for item in signal.pthread_sigmask(
                            signal.SIG_BLOCK, set()
                        )
                    )
                )
                if (
                    precommit_threads.thread_count != 1
                    or precommit_threads.thread_ids != entry_threads.thread_ids
                    or precommit_threads.process != entry_threads.process
                    or mask_before_commit != mask_before
                ):
                    raise RuntimeError(
                        "campaign failure controller barrier drifted"
                    )
                entries_sha256 = _campaign_entries_sha256(second_entries)
                vnode_sha256 = _canonical_sha256(
                    [item.model_dump(mode="json") for item in second_vnodes]
                )
                commit_authorized_at = max(1, time.monotonic_ns())
                quiescence_fields: dict[str, object] = {
                    "schema_id": "phase-latency-campaign-failure-quiescence-v1",
                    "controller": _process_identity(os.getpid()),
                    "barrier_entry_thread_inventory": entry_threads,
                    "final_file_descriptor_inventory": fd_inventory,
                    "precommit_thread_inventory": precommit_threads,
                    "termination_signal_numbers": expected_signals,
                    "barrier_signal_mask_before_inventory": mask_before,
                    "barrier_signal_mask_before_commit": mask_before_commit,
                    "termination_signals_blocked_for_entire_barrier": True,
                    "controller_sole_thread_for_entire_barrier": True,
                    "output_prefix_vnodes": second_vnodes,
                    "output_prefix_vnodes_sha256": vnode_sha256,
                    "first_output_prefix_vnodes_sha256": vnode_sha256,
                    "second_output_prefix_vnodes_sha256": vnode_sha256,
                    "darwin_vnode_write_access_mask": 2,
                    "writable_output_prefix_descriptor_fds": (),
                    "no_output_prefix_vnode_fd_with_write_access": True,
                    "first_output_scan_started_monotonic_ns": first_started,
                    "first_output_scan_completed_monotonic_ns": first_completed,
                    "second_output_scan_started_monotonic_ns": second_started,
                    "second_output_scan_completed_monotonic_ns": second_completed,
                    "first_output_scan_sha256": entries_sha256,
                    "second_output_scan_sha256": entries_sha256,
                    "exact_double_output_scan": True,
                    "launch_dispositions": dispositions,
                    "launch_intent_count": len(dispositions),
                    "commit_authorized_at_monotonic_ns": commit_authorized_at,
                }
                quiescence = CampaignFailureQuiescenceEvidence(
                    **quiescence_fields,
                    record_sha256=_canonical_sha256(quiescence_fields),
                )
                closure_fields: dict[str, object] = {
                    "schema_id": "phase-latency-campaign-closure-manifest-v1",
                    "campaign_id": "LAT-US02",
                    "status": "failure",
                    "output_root": CampaignClosureOutputRootIdentity(
                        resolved_path=str(resolved_root),
                        device=root_stat.st_dev,
                        inode=root_stat.st_ino,
                        mode=stat.S_IMODE(root_stat.st_mode),
                        uid=root_stat.st_uid,
                        nlink=root_stat.st_nlink,
                        descriptor_opened_o_directory=True,
                        descriptor_opened_o_nofollow=True,
                    ),
                    "entries": second_entries,
                    "entry_count": len(second_entries),
                    "aggregate_bytes": sum(
                        item.size_bytes for item in second_entries
                    ),
                    "sole_self_exclusion": "campaign-closure.json",
                    "producer_groups_esrch": True,
                    "writer_fds_closed": True,
                    "fsync_completed": True,
                    "terminal_manifest_sha256": terminal_manifest_sha256,
                    "bundle_sha256": None,
                    "evaluation_sha256": None,
                    "failure": failure,
                    "failure_quiescence": quiescence,
                    "completed_at_monotonic_ns": commit_authorized_at,
                }
                provisional = CampaignClosureManifest.model_construct(
                    **closure_fields, record_sha256="0" * 64
                )
                closure = CampaignClosureManifest(
                    **closure_fields,
                    record_sha256=_canonical_sha256(
                        provisional.model_dump(
                            mode="json", exclude={"record_sha256"}
                        )
                    ),
                )
                payload = canonical_model_bytes(closure)
            except BaseException as error:
                raise _CampaignFailureClosureUnavailable(
                    "campaign failure controller quiescence proof is incomplete"
                ) from error

            descriptor = os.open(
                "campaign-closure.json",
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=root_fd,
            )
            try:
                offset = 0
                while offset < len(payload):
                    written = os.write(descriptor, payload[offset:])
                    if written <= 0:
                        raise RuntimeError(
                            "campaign failure closure write made no progress"
                        )
                    offset += written
                os.fsync(descriptor)
                closure_stat = os.fstat(descriptor)
            finally:
                os.close(descriptor)
            os.fsync(root_fd)
        if (
            not stat.S_ISREG(closure_stat.st_mode)
            or stat.S_IMODE(closure_stat.st_mode) != 0o600
            or closure_stat.st_uid != os.geteuid()
            or closure_stat.st_nlink != 1
            or closure_stat.st_size != len(payload)
        ):
            raise RuntimeError("campaign failure closure file custody differs")
        reread, reread_stat = _read_campaign_output_member(
            root_fd=root_fd,
            relative_path="campaign-closure.json",
            maximum_bytes=max(len(payload), 1),
        )
        if reread != payload or any(
            getattr(reread_stat, field) != getattr(closure_stat, field)
            for field in (
                "st_dev",
                "st_ino",
                "st_mode",
                "st_uid",
                "st_nlink",
                "st_size",
            )
        ):
            raise RuntimeError("campaign failure closure changed after fsync")
        if _scan_campaign_output_fd(
            root_fd=root_fd,
            expected_relative_paths={
                item.relative_path for item in second_entries
            },
            allow_self_exclusion=True,
        ) != second_entries:
            raise RuntimeError(
                "campaign output changed after failure closure commit"
            )
    finally:
        os.close(root_fd)
    return closure_path


def _write_campaign_failure_marker(
    *, output_root: Path, failure: FailureRecord
) -> Path:
    """Retain a diagnostic prefix without asserting producer quiescence."""

    resolved_root = output_root.resolve(strict=True)
    root_fd = os.open(
        resolved_root,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    marker_path = resolved_root / "campaign-failure-marker.json"
    try:
        root_stat = os.fstat(root_fd)
        if (
            not stat.S_ISDIR(root_stat.st_mode)
            or stat.S_IMODE(root_stat.st_mode) != 0o700
            or root_stat.st_uid != os.geteuid()
        ):
            raise RuntimeError("campaign failure-marker root custody differs")
        entries = _scan_campaign_output_fd(
            root_fd=root_fd,
            expected_relative_paths=None,
            allow_self_exclusion=False,
        )
        fields: dict[str, object] = {
            "schema_id": "phase-latency-campaign-failure-marker-v1",
            "campaign_id": "LAT-US02",
            "status": "incomplete_custody",
            "entries": entries,
            "entry_count": len(entries),
            "aggregate_bytes": sum(item.size_bytes for item in entries),
            "failure": failure,
            "producer_groups_esrch": False,
            "writer_fds_closed": False,
            "final_closure_claimed": False,
            "observed_at_monotonic_ns": max(1, time.monotonic_ns()),
        }
        provisional = CampaignFailureMarker.model_construct(
            **fields, record_sha256="0" * 64
        )
        marker = CampaignFailureMarker(
            **fields,
            record_sha256=_canonical_sha256(
                provisional.model_dump(mode="json", exclude={"record_sha256"})
            ),
        )
        payload = canonical_model_bytes(marker)
        with _blocked_controller_termination_signals():
            descriptor = os.open(
                "campaign-failure-marker.json",
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=root_fd,
            )
            try:
                offset = 0
                while offset < len(payload):
                    written = os.write(descriptor, payload[offset:])
                    if written <= 0:
                        raise RuntimeError(
                            "campaign failure-marker write made no progress"
                        )
                    offset += written
                os.fsync(descriptor)
                observed = os.fstat(descriptor)
            finally:
                os.close(descriptor)
            os.fsync(root_fd)
        if (
            not stat.S_ISREG(observed.st_mode)
            or stat.S_IMODE(observed.st_mode) != 0o600
            or observed.st_uid != os.geteuid()
            or observed.st_nlink != 1
            or observed.st_size != len(payload)
        ):
            raise RuntimeError("campaign failure-marker file custody differs")
    finally:
        os.close(root_fd)
    return marker_path


def _read_bounded_ready_pipe(
    descriptor: int,
    *,
    maximum_bytes: int,
    deadline_monotonic_ns: int,
    pump: Callable[[], None],
    producers: tuple[subprocess.Popen[bytes], ...],
) -> tuple[bytes, dict[str, object]]:
    """Read one producer-closed canonical READY frame under a fixed bound."""

    os.set_blocking(descriptor, False)
    retained = bytearray()
    selector = selectors.DefaultSelector()
    selector.register(descriptor, selectors.EVENT_READ)
    eof = False
    try:
        while not eof:
            pump()
            if any(process.poll() is not None for process in producers):
                # A producer may close after a successful one-shot write; drain
                # the pipe before classifying its process exit.
                pass
            remaining_ns = deadline_monotonic_ns - time.monotonic_ns()
            if remaining_ns <= 0:
                raise TimeoutError("managed READY pipe timed out")
            for key, _mask in selector.select(
                min(0.01, remaining_ns / 1_000_000_000)
            ):
                try:
                    chunk = os.read(key.fd, min(4096, maximum_bytes + 2))
                except BlockingIOError:
                    continue
                if not chunk:
                    eof = True
                    break
                retained.extend(chunk)
                if len(retained) > maximum_bytes:
                    raise ValueError("managed READY frame exceeded its bound")
        raw = bytes(retained)
        if not raw or not raw.endswith(b"\n") or raw.count(b"\n") != 1:
            raise ValueError("managed READY frame count differs")
        try:
            value = json.loads(raw[:-1])
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("managed READY frame is not JSON") from error
        if type(value) is not dict or _canonical_payload_bytes(value) != raw[:-1]:
            raise ValueError("managed READY frame is not canonical")
        return raw, value
    finally:
        selector.close()


def _validate_ready_record_hash(
    value: dict[str, object], *, schema_id: str
) -> None:
    if value.get("schema_id") != schema_id or set(value).isdisjoint(
        {"ready_sha256"}
    ):
        raise ValueError("managed READY schema differs")
    retained = value.get("ready_sha256")
    fields = dict(value)
    fields.pop("ready_sha256", None)
    if not isinstance(retained, str) or retained != _canonical_sha256(fields):
        raise ValueError("managed READY record hash differs")


def _validate_root_sandbox_probe_report(
    value: object,
    *,
    plan: Mapping[str, object],
    expected_pid: int,
    expected_start_abstime: int,
    expected_ppid: int,
    expected_pgid: int,
    expected_sid: int,
) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError("managed sandbox report fields differ")
    expected_report_fields = {
        "schema_id",
        "attempt_id",
        "attempt_nonce_sha256",
        "scope_sha256",
        "role",
        "profile_sha256",
        "native_closure_sha256",
        "plan_sha256",
        "probe_executor_authority",
        "probe_executor_source_sha256",
        "probe_executor_source_observation_before",
        "probe_executor_source_observation_after",
        "probe_library_sha256",
        "probe_library_identity",
        "sandbox_applied_at_monotonic_ns",
        "process",
        "file_descriptor_inventory_before_probes",
        "file_descriptor_inventory_after_probes",
        "held_directories",
        "held_directories_sha256",
        "rows",
        "record_sha256",
    }
    if set(value) != expected_report_fields:
        raise ValueError("managed sandbox report fields differ")
    report = dict(value)
    retained_sha256 = report.pop("record_sha256", None)
    process = report.get("process")
    rows = report.get("rows")
    operations = plan.get("operations")
    if (
        retained_sha256 != _canonical_sha256(report)
        or report.get("schema_id")
        != "phase-latency-kernel-sandbox-role-native-report-v1"
        or report.get("attempt_id") != plan.get("attempt_id")
        or report.get("attempt_nonce_sha256")
        != plan.get("attempt_nonce_sha256")
        or report.get("scope_sha256") != plan.get("scope_sha256")
        or report.get("role") != plan.get("role")
        or report.get("profile_sha256") != plan.get("profile_sha256")
        or report.get("native_closure_sha256")
        != plan.get("native_closure_sha256")
        or report.get("plan_sha256") != plan.get("plan_sha256")
        or report.get("probe_executor_authority")
        != plan.get("probe_executor_authority")
        or report.get("probe_executor_source_sha256")
        != plan.get("probe_executor_source_sha256")
        or report.get("probe_library_sha256")
        != plan.get("probe_library_sha256")
        or type(process) is not dict
        or process.get("pid") != expected_pid
        or process.get("start_abstime") != expected_start_abstime
        or process.get("ppid") != expected_ppid
        or process.get("pgid") != expected_pgid
        or process.get("sid") != expected_sid
        or type(rows) is not list
        or type(operations) is not list
        or any(type(row) is not dict for row in rows)
        or any(type(operation) is not dict for operation in operations)
        or len(rows) != len(operations)
        or type(report.get("sandbox_applied_at_monotonic_ns")) is not int
        or report.get("sandbox_applied_at_monotonic_ns", 0) <= 0
        or report.get("held_directories") != plan.get("held_directories")
        or report.get("held_directories_sha256")
        != _canonical_sha256(
            {"held_directories": plan.get("held_directories")}
        )
        or tuple(row.get("operation") for row in rows)
        != tuple(operation.get("operation") for operation in operations)
        or tuple(row.get("probe_sequence") for row in rows)
        != tuple(range(1, len(rows) + 1))
    ):
        raise ValueError("managed sandbox report authority differs")

    before_source = report["probe_executor_source_observation_before"]
    after_source = report["probe_executor_source_observation_after"]
    if type(before_source) is not dict or type(after_source) is not dict:
        raise ValueError("managed sandbox executor observation differs")
    source_ignored = {"descriptor", "observed_at_monotonic_ns"}
    if (
        before_source.get("content_sha256")
        != plan.get("probe_executor_source_sha256")
        or {
            key: item
            for key, item in before_source.items()
            if key not in source_ignored
        }
        != {
            key: item
            for key, item in after_source.items()
            if key not in source_ignored
        }
    ):
        raise ValueError("managed sandbox executor custody differs")

    before_inventory = NativeFileDescriptorInventory.model_validate(
        report["file_descriptor_inventory_before_probes"]
    )
    after_inventory = NativeFileDescriptorInventory.model_validate(
        report["file_descriptor_inventory_after_probes"]
    )
    if (
        before_inventory.process != after_inventory.process
        or before_inventory.process.pid != expected_pid
        or before_inventory.process.start_abstime != expected_start_abstime
        or before_inventory.descriptors != after_inventory.descriptors
        or before_inventory.inventory_sha256 != after_inventory.inventory_sha256
    ):
        raise ValueError("managed sandbox report FD inventory differs")

    previous_completed = report["sandbox_applied_at_monotonic_ns"]
    for row, operation in zip(rows, operations, strict=True):
        if type(row) is not dict or type(operation) is not dict or set(row) != {
            "operation",
            "probe_sequence",
            "started_monotonic_ns",
            "completed_monotonic_ns",
            "native_invocation",
            "native_result",
        }:
            raise ValueError("managed sandbox report row differs")
        invocation = KernelSandboxNativeProbeInvocation.model_validate(
            row["native_invocation"]
        )
        result = KernelSandboxNativeProbeResult.model_validate(
            row["native_result"]
        )
        path_operation = operation.get("kind") == "path"
        payload_hex = operation.get("payload_hex")
        if type(payload_hex) is not str:
            raise ValueError("managed sandbox operation payload differs")
        try:
            payload = bytes.fromhex(payload_hex)
        except ValueError as error:
            raise ValueError("managed sandbox operation payload differs") from error
        primary = operation.get("primary_relative_path")
        secondary = operation.get("secondary_relative_path")
        expected_static_invocation = {
            "helper_function": (
                "lat_us02_sandbox_probe_path"
                if path_operation
                else "lat_us02_sandbox_probe_network"
            ),
            "operation_code": operation.get("operation_code"),
            "held_directory_fd": operation.get("held_directory_fd"),
            "primary_relative_path_hex": (
                primary.encode("utf-8").hex()
                if path_operation and isinstance(primary, str)
                else None
            ),
            "secondary_relative_path_hex": (
                secondary.encode("utf-8").hex()
                if path_operation and isinstance(secondary, str)
                else None
            ),
            "open_flags": operation.get("open_flags") if path_operation else None,
            "create_mode": operation.get("create_mode") if path_operation else None,
            "domain": operation.get("domain") if not path_operation else None,
            "socket_type": (
                operation.get("socket_type") if not path_operation else None
            ),
            "protocol": operation.get("protocol") if not path_operation else None,
            "sockaddr_hex": (
                operation.get("sockaddr_hex") if not path_operation else None
            ),
            "payload_hex": payload_hex,
            "payload_size_bytes": len(payload),
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
        }
        if any(
            getattr(invocation, key) != expected
            for key, expected in expected_static_invocation.items()
        ):
            raise ValueError("managed sandbox invocation crossed its plan")
        started = row["started_monotonic_ns"]
        completed = row["completed_monotonic_ns"]
        if (
            type(started) is not int
            or type(completed) is not int
            or not previous_completed <= started
            or not (
                started
                <= invocation.signals_blocked_at_monotonic_ns
                < invocation.syscall_returned_at_monotonic_ns
                < invocation.signals_restored_at_monotonic_ns
                <= completed
            )
            or result.operation_code != operation.get("operation_code")
        ):
            raise ValueError("managed sandbox invocation chronology differs")
        previous_completed = completed

        operation_code = operation.get("operation_code")
        if path_operation and operation_code == 5:
            valid_disposition = (
                result.terminal_stage_code == 5
                and result.raw_errno == 0
                and result.syscall_return == result.bytes_received
                and result.bytes_received > 0
                and result.bytes_sent == 0
            )
        elif path_operation and operation_code == 6:
            valid_disposition = (
                result.terminal_stage_code == 7
                and result.raw_errno == 0
                and result.syscall_return == 0
                and result.bytes_sent == len(payload)
                and result.bytes_received == len(payload)
            )
        else:
            expected_stage = (
                {1: 2, 2: 6, 3: 7, 4: 8}.get(operation_code)
                if path_operation
                else {1: 10, 2: 11, 3: 12}.get(operation_code)
            )
            valid_disposition = (
                result.terminal_stage_code == expected_stage
                and result.syscall_return == -1
                and result.raw_errno in {errno.EPERM, errno.EACCES}
                and result.bytes_sent == 0
                and result.bytes_received == 0
            )
        if not valid_disposition:
            raise ValueError("managed sandbox syscall disposition differs")
    return {**report, "record_sha256": retained_sha256}


def _group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _frozen_process_group_state(identity: ControllerProcessIdentity) -> str:
    """Return empty/exact/unsafe for one frozen fresh-session process group."""

    controller_pid = os.getpid()
    protected = {0, 1, controller_pid, os.getpgrp(), os.getsid(0)}
    if (
        identity.pid != identity.process_group_id
        or identity.pid != identity.session_id
        or identity.process_group_id <= 1
        or identity.process_group_id in protected
    ):
        return "unsafe"
    try:
        leader = psutil.Process(identity.pid)
        with leader.oneshot():
            leader_create_time_ns = int(leader.create_time() * 1_000_000_000)
            leader_status = leader.status()
        if leader_create_time_ns != identity.create_time_ns:
            return "unsafe"
        if leader_status in {psutil.STATUS_DEAD, psutil.STATUS_ZOMBIE}:
            return "exact"
        try:
            leader_pgid = os.getpgid(identity.pid)
            leader_sid = os.getsid(identity.pid)
        except ProcessLookupError:
            return "exact" if _group_exists(identity.process_group_id) else "empty"
        if leader_pgid != identity.process_group_id or (
            leader_sid != identity.session_id
        ):
            return "unsafe"
        # A live exact fresh-session leader is itself authoritative nonempty
        # membership; global Darwin process enumeration may be unavailable.
        return "exact"
    except psutil.NoSuchProcess:
        pass
    except (OSError, psutil.Error):
        return "unsafe"

    # Kernel ESRCH is the only successful disappearance proof. Conversely, a
    # still-existing fresh-session group cannot be reused in another session
    # while any member remains, even when Darwin denies global KERN_PROC reads.
    if not _group_exists(identity.process_group_id):
        return "empty"

    members: list[tuple[int, int, int, int]] = []
    try:
        for process in psutil.process_iter(attrs=("pid",)):
            pid = int(process.info["pid"])
            try:
                process_group_id = os.getpgid(pid)
                if process_group_id != identity.process_group_id:
                    continue
                session_id = os.getsid(pid)
                create_time_ns = int(process.create_time() * 1_000_000_000)
            except psutil.NoSuchProcess:
                return "unknown"
            except (OSError, psutil.Error):
                return "unknown"
            members.append((pid, create_time_ns, process_group_id, session_id))
    except (OSError, psutil.Error):
        return "unknown"
    if not members:
        return "unknown"
    if any(
        pid in protected
        or process_group_id != identity.process_group_id
        or session_id != identity.session_id
        for pid, _created, process_group_id, session_id in members
    ):
        return "unsafe"
    return "exact"


def _signal_frozen_process_group(
    identity: ControllerProcessIdentity,
    signum: int,
) -> bool:
    state = _frozen_process_group_state(identity)
    if state == "empty":
        return False
    if state != "exact":
        raise RuntimeError("refusing drifted frozen process-group target")
    try:
        os.killpg(identity.process_group_id, signum)
    except ProcessLookupError:
        if _frozen_process_group_state(identity) != "empty":
            raise RuntimeError("frozen process-group disappearance is unconfirmed")
        return False
    return True


def _process_identity(pid: int) -> ControllerProcessIdentity:
    process = psutil.Process(pid)
    with process.oneshot():
        create_time_ns = int(process.create_time() * 1_000_000_000)
        process_group_id = os.getpgid(pid)
        session_id = os.getsid(pid)
        if process.status() in {psutil.STATUS_DEAD, psutil.STATUS_ZOMBIE}:
            raise RuntimeError("process identity is terminal")
    return ControllerProcessIdentity(
        pid=pid,
        create_time_ns=create_time_ns,
        process_group_id=process_group_id,
        session_id=session_id,
    )


def _controller_resource_sample() -> ControllerResourceSample:
    from app.services.tesseract_broker_native import (
        native_detailed_file_descriptor_inventory,
        native_detailed_thread_inventory,
    )

    process = psutil.Process(os.getpid())
    identity = _process_identity(os.getpid())
    thread_inventory = NativeThreadInventory.model_validate(
        asdict(native_detailed_thread_inventory(os.getpid()))
    )
    file_descriptor_inventory = NativeFileDescriptorInventory.model_validate(
        asdict(native_detailed_file_descriptor_inventory(os.getpid()))
    )
    with process.oneshot():
        thread_count = process.num_threads()
        file_descriptor_count = process.num_fds()
    return ControllerResourceSample(
        observed_monotonic_ns=max(1, time.monotonic_ns()),
        identity=identity,
        thread_count=thread_count,
        file_descriptor_count=file_descriptor_count,
        thread_inventory=thread_inventory,
        file_descriptor_inventory=file_descriptor_inventory,
        file_descriptor_membership_sha256=(
            _native_fd_membership_sha256(file_descriptor_inventory)
        ),
    )


def _controller_resource_boundary(
    before: ControllerResourceSample,
) -> ControllerResourceBoundary:
    after = _controller_resource_sample()
    return ControllerResourceBoundary(
        before=before,
        after=after,
        threads_returned_to_baseline=(
            after.thread_inventory.thread_ids
            == before.thread_inventory.thread_ids
        ),
        file_descriptors_returned_to_baseline=(
            after.file_descriptor_membership_sha256
            == before.file_descriptor_membership_sha256
        ),
    )


def _touch_private_heartbeat(path: Path) -> None:
    observed = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(observed.st_mode)
        or stat.S_IMODE(observed.st_mode) != 0o600
        or observed.st_uid != os.getuid()
        or observed.st_nlink != 1
        or observed.st_size != 0
    ):
        raise RuntimeError("watchdog heartbeat custody differs")
    os.utime(path, None, follow_symlinks=False)


def _create_private_empty(path: Path) -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    observed = os.fstat(descriptor)
    if (
        not stat.S_ISREG(observed.st_mode)
        or stat.S_IMODE(observed.st_mode) != 0o600
        or observed.st_uid != os.getuid()
        or observed.st_nlink != 1
        or observed.st_size != 0
    ):
        os.close(descriptor)
        raise RuntimeError("private empty file custody differs")
    return descriptor


class _ControllerTerminationSignal(BaseException):
    def __init__(self, signum: int) -> None:
        super().__init__(signum)
        self.signum = signum


@dataclass(slots=True)
class _ControllerSignalLatch:
    signum: int | None = None


class _GuardedLaunchError(Exception):
    def __init__(self, launch: "_GuardedWorkerLaunch", error: BaseException) -> None:
        super().__init__(type(error).__qualname__)
        self.launch = launch
        self.error = error


@contextmanager
def _scoped_signal_cleanup():
    previous: dict[int, object] = {}
    latch = _ControllerSignalLatch()

    def terminate(signum: int, _frame: object) -> None:
        if latch.signum is not None:
            return
        latch.signum = signum
        raise _ControllerTerminationSignal(signum)

    for signum in (signal.SIGTERM, signal.SIGHUP):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, terminate)
    try:
        yield latch
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def _with_scoped_signal_cleanup(function: Callable[..., object]):
    @wraps(function)
    def wrapped(*args: object, **kwargs: object):
        with _scoped_signal_cleanup():
            return function(*args, **kwargs)

    return wrapped


@contextmanager
def _blocked_controller_termination_signals():
    blocked = {signal.SIGTERM, signal.SIGHUP}
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


class _BoundedPipeCapture:
    """Persistent fair nonblocking capture with one combined retained bound."""

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        *,
        limit_bytes: int = MAXIMUM_WORKER_COMBINED_BYTES,
    ) -> None:
        if process.stdout is None or process.stderr is None:
            raise RuntimeError("bounded worker capture requires both pipes")
        if isinstance(limit_bytes, bool) or not 0 < limit_bytes <= (
            MAXIMUM_WORKER_COMBINED_BYTES
        ):
            raise ValueError("bounded capture limit differs")
        self.process = process
        self.limit_bytes = limit_bytes
        self.selector = selectors.DefaultSelector()
        self.streams = {"stdout": process.stdout, "stderr": process.stderr}
        self.counts = {"stdout": 0, "stderr": 0}
        self.digests = {name: hashlib.sha256() for name in self.streams}
        self.buffers = {name: bytearray() for name in self.streams}
        self.eof = {"stdout": False, "stderr": False}
        self.overflow = False
        self.forced_close = False
        self.closed = False
        for name, stream in self.streams.items():
            os.set_blocking(stream.fileno(), False)
            self.selector.register(stream, selectors.EVENT_READ, data=name)

    @property
    def complete(self) -> bool:
        return all(self.eof.values())

    @property
    def retained_size_bytes(self) -> int:
        return sum(len(value) for value in self.buffers.values())

    def pump(self, timeout_seconds: float) -> bool:
        """Read at most one 64 KiB chunk per ready stream; return first overflow."""

        if self.closed or self.complete:
            return False
        first_overflow = False
        for key, _mask in self.selector.select(timeout=max(0.0, timeout_seconds)):
            name = str(key.data)
            try:
                chunk = os.read(key.fd, 65_536)
            except BlockingIOError:
                continue
            if not chunk:
                self.selector.unregister(key.fileobj)
                self.eof[name] = True
                continue
            retained_remaining = max(
                0,
                self.limit_bytes
                - self.counts["stdout"]
                - self.counts["stderr"],
            )
            retained = chunk[:retained_remaining]
            self.counts[name] += len(retained)
            self.digests[name].update(retained)
            self.buffers[name].extend(retained)
            over_limit = len(retained) != len(chunk)
            if over_limit and not self.overflow:
                self.overflow = True
                first_overflow = True
        return first_overflow

    def close(self, *, forced: bool) -> None:
        if self.closed:
            return
        self.forced_close = forced and not self.complete
        self.closed = True
        self.selector.close()
        for stream in self.streams.values():
            stream.close()

    def bytes(self, name: Literal["stdout", "stderr"]) -> bytes:
        return bytes(self.buffers[name])

    def sha256(self, name: Literal["stdout", "stderr"]) -> str:
        return self.digests[name].hexdigest()

    @property
    def disposition(self) -> str:
        if self.forced_close or not self.complete:
            return "incomplete_observed_prefix_forced_close"
        if self.overflow:
            return "bounded_observed_prefix_overflow"
        return "complete"


REQUEST_CPU_SAMPLE_LOG_MAXIMUM_BYTES = 1_048_576
REQUEST_RESOURCE_SAMPLE_LOG_MAXIMUM_BYTES = 16_777_216
MAXIMUM_CONTROLLER_RESOURCE_SAMPLES = 8_192


class _DurableHashChainedLog:
    """One controller-owned O_EXCL JSONL chain fsynced before every ACK."""

    def __init__(self, path: Path, *, schema_id: str, maximum_bytes: int) -> None:
        parent = _ensure_private_directory(path.parent)
        if path.parent.resolve(strict=True) != parent or path.exists():
            raise FileExistsError("durable controller log path already exists")
        if not 1 <= maximum_bytes <= REQUEST_CONTROL_TRANSCRIPT_MAXIMUM_BYTES:
            raise ValueError("durable controller log bound differs")
        self.path = path
        self.schema_id = schema_id
        self.maximum_bytes = maximum_bytes
        self.sequence = 0
        self.head_sha256 = "0" * 64
        self.size_bytes = 0
        self.rows: list[dict[str, Any]] = []
        self.closed = False
        self._descriptor = os.open(
            path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        observed = os.fstat(self._descriptor)
        if (
            not stat.S_ISREG(observed.st_mode)
            or stat.S_IMODE(observed.st_mode) != 0o600
            or observed.st_uid != os.geteuid()
            or observed.st_nlink != 1
            or observed.st_size != 0
        ):
            os.close(self._descriptor)
            self.closed = True
            raise RuntimeError("durable controller log custody differs")
        parent_fd = os.open(
            parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)

    def append(self, *, kind: str, record: Mapping[str, Any]) -> str:
        if self.closed:
            raise RuntimeError("durable controller log is closed")
        if not kind or len(kind.encode("ascii", "strict")) > 64:
            raise ValueError("durable controller log kind differs")
        fields = {
            "schema_id": self.schema_id,
            "row_sequence": self.sequence + 1,
            "previous_row_sha256": self.head_sha256,
            "kind": kind,
            "record": dict(record),
            "retained_monotonic_ns": max(1, time.monotonic_ns()),
        }
        row_sha256 = _canonical_sha256(fields)
        row = {**fields, "row_sha256": row_sha256}
        payload = _canonical_payload_bytes(row) + b"\n"
        if self.size_bytes + len(payload) > self.maximum_bytes:
            raise RuntimeError("durable controller log exceeded its byte bound")
        with _blocked_controller_termination_signals():
            written = 0
            while written < len(payload):
                count = os.write(self._descriptor, payload[written:])
                if count <= 0:
                    raise OSError("durable controller log write made no progress")
                written += count
            os.fsync(self._descriptor)
            observed = os.fstat(self._descriptor)
        self.sequence += 1
        self.head_sha256 = row_sha256
        self.size_bytes += len(payload)
        self.rows.append(row)
        if observed.st_size != self.size_bytes:
            raise RuntimeError("durable controller log size differs")
        return row_sha256

    def close(self) -> None:
        if self.closed:
            return
        os.fsync(self._descriptor)
        os.close(self._descriptor)
        self.closed = True

    def validate_retained(self) -> bytes:
        if not self.closed:
            raise RuntimeError("durable controller log remained open")
        raw = _read_private_payload(self.path, maximum_bytes=self.maximum_bytes)
        if not raw or not raw.endswith(b"\n") or len(raw) != self.size_bytes:
            raise RuntimeError("durable controller log framing differs")
        previous = "0" * 64
        sequence = 0
        for line in raw.splitlines():
            try:
                value = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise RuntimeError("durable controller log JSON differs") from error
            if (
                type(value) is not dict
                or set(value)
                != {
                    "schema_id",
                    "row_sequence",
                    "previous_row_sha256",
                    "kind",
                    "record",
                    "retained_monotonic_ns",
                    "row_sha256",
                }
                or _canonical_payload_bytes(value) != line
                or value["schema_id"] != self.schema_id
                or value["row_sequence"] != sequence + 1
                or value["previous_row_sha256"] != previous
            ):
                raise RuntimeError("durable controller log row differs")
            digest = value.pop("row_sha256")
            if digest != _canonical_sha256(value):
                raise RuntimeError("durable controller log row digest differs")
            value["row_sha256"] = digest
            sequence += 1
            previous = digest
        if sequence != self.sequence or previous != self.head_sha256:
            raise RuntimeError("durable controller log terminal chain differs")
        return raw


@dataclass(frozen=True, slots=True)
class _ExternalRequestCpuBoundary:
    request_id: str
    request_epoch: int
    request_sequence: int
    arm: dict[str, Any]
    begin_blocked: dict[str, Any]
    begin_release: dict[str, Any]
    end_blocked: dict[str, Any]
    broker_request_receipt: dict[str, Any]
    receipt_release: dict[str, Any]
    raw_result: dict[str, Any]
    result_ack: dict[str, Any]
    broker_before: DarwinProcessSelfCpuSample
    worker_before: DarwinProcessSelfCpuSample
    broker_after: DarwinProcessSelfCpuSample
    worker_after: DarwinProcessSelfCpuSample
    begin_scratch: BrokerScratchInventory
    end_scratch: BrokerScratchInventory
    begin_sample_record: ExternalCpuStableEdgeRecord
    end_sample_record: ExternalCpuStableEdgeRecord
    begin_sample_record_sha256: str
    end_sample_record_sha256: str
    begin_sample_row_sha256: str
    end_sample_row_sha256: str
    frame_record_sha256s: tuple[str, ...]
    transcript_row_sha256s: tuple[str, ...]
    resource_window: _ControllerRequestResourceWindow | None = None


@dataclass(frozen=True, slots=True)
class _ControllerRequestResourceWindow:
    samples: tuple[dict[str, Any], ...]
    rows: tuple[ControllerResourceSampleLogRow, ...]
    row_sha256s: tuple[str, ...]
    pre_exec_gated_child_samples: tuple[dict[str, Any], ...]
    sampled_process_identities: tuple[SampledProcessIdentity, ...]
    peak: ResourceSample
    peak_process_count: int
    peak_rss_bytes: int
    peak_thread_count: int
    peak_file_descriptor_count: int
    first_sample_monotonic_ns: int
    last_sample_monotonic_ns: int
    maximum_gap_ns: int
    target_interval_ns: int
    edge_tolerance_ns: int


def _require_complete_phase_authority(
    *,
    records: tuple[PhaseDeadlineRecord, ...],
    acks: tuple[PhaseDeadlineAck, ...],
    expected_request_count: int,
    request_boundaries: tuple[_ExternalRequestCpuBoundary, ...] | None,
) -> None:
    """Require one durable startup/request*/shutdown writer and exact ACKs."""

    if expected_request_count <= 0:
        raise RuntimeError("phase authority request count differs")
    expected_phases = (
        "startup",
        *("request" for _ in range(expected_request_count)),
        "shutdown",
    )
    if (
        len(records) != expected_request_count + 2
        or len(acks) != len(records)
        or tuple(record.phase for record in records) != expected_phases
        or tuple(record.sequence for record in records)
        != tuple(range(1, len(records) + 1))
        or tuple(ack.sequence for ack in acks)
        != tuple(range(1, len(acks) + 1))
        or any(
            ack.phase_record_sha256 != record.record_sha256
            or ack.observed_monotonic_ns < record.issued_monotonic_ns
            or ack.observed_monotonic_ns >= record.deadline_monotonic_ns
            for record, ack in zip(records, acks, strict=True)
        )
    ):
        raise RuntimeError("complete phase deadline/ACK authority differs")
    if request_boundaries is None:
        return
    if len(request_boundaries) != expected_request_count:
        raise RuntimeError("phase authority request boundary count differs")
    for request_sequence, (record, boundary) in enumerate(
        zip(records[1:-1], request_boundaries, strict=True), start=1
    ):
        arm = boundary.arm
        receipt = getattr(boundary, "broker_request_receipt", None)
        if receipt is None:
            end_blocked = getattr(boundary, "end_blocked", None)
            if isinstance(end_blocked, Mapping):
                receipt = end_blocked.get("broker_request_receipt")
        if (
            boundary.request_sequence != request_sequence
            or arm.get("request_sequence") != request_sequence
            or not isinstance(receipt, Mapping)
            or arm.get("request_deadline_monotonic_ns")
            != record.deadline_monotonic_ns
            or receipt.get("phase_deadline_monotonic_ns")
            != record.deadline_monotonic_ns
        ):
            raise RuntimeError("request phase deadline/ARM/receipt join differs")
@dataclass(frozen=True, slots=True)
class _LiveChildWatchSnapshot:
    raw_size_bytes: int
    raw_sha256: str
    broker_row_count: int
    broker_head_sha256: str
    event_count: int
    event_head_sha256: str
    pending_spawn_intents: dict[tuple[Any, ...], dict[str, Any]]
    provisional_children: dict[tuple[int, int], dict[str, Any]]
    known_children: dict[tuple[int, int], dict[str, Any]]
    open_registrations: dict[tuple[int, int], dict[str, Any]]
    terminal_wait4_identities: frozenset[tuple[int, int]]
    pre_exec_gated_samples: dict[tuple[int, int], dict[str, Any]]
    record_blob_count: int
    record_blob_size_bytes: int
    record_blob_head_sha256: str
    record_blob_root: dict[str, Any]
    event_blob_size_bytes: int
    event_blob_root: dict[str, Any]


def _read_child_watch_blob_root(
    root: Path,
    *,
    name_pattern: re.Pattern[str],
    maximum_bytes: int,
) -> tuple[dict[str, bytes], dict[str, os.stat_result], os.stat_result]:
    """Descriptor-relatively inventory one immutable watchdog blob root."""

    if not root.is_absolute() or root.is_symlink():
        raise RuntimeError("child-watch blob root path differs")
    descriptor = os.open(
        root,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        root_stat = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(root_stat.st_mode)
            or stat.S_IMODE(root_stat.st_mode) != 0o700
            or root_stat.st_uid != os.geteuid()
            or root_stat.st_nlink < 2
        ):
            raise RuntimeError("child-watch blob root custody differs")
        names = tuple(sorted(os.listdir(descriptor)))
        if any(name_pattern.fullmatch(name) is None for name in names):
            raise RuntimeError("child-watch blob filename differs")
        blobs: dict[str, bytes] = {}
        identities: dict[str, os.stat_result] = {}
        aggregate = 0
        for name in names:
            child = os.open(
                name,
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=descriptor,
            )
            try:
                before = os.fstat(child)
                if (
                    not stat.S_ISREG(before.st_mode)
                    or stat.S_IMODE(before.st_mode) != 0o600
                    or before.st_uid != os.geteuid()
                    or before.st_nlink != 1
                    or before.st_size < 0
                    or aggregate + before.st_size > maximum_bytes
                ):
                    raise RuntimeError("child-watch blob custody differs")
                chunks: list[bytes] = []
                remaining = before.st_size
                while remaining:
                    chunk = os.read(child, min(remaining, 1 * 1024 * 1024))
                    if not chunk:
                        raise RuntimeError("child-watch blob was truncated")
                    chunks.append(chunk)
                    remaining -= len(chunk)
                if os.read(child, 1):
                    raise RuntimeError("child-watch blob grew while read")
                after = os.fstat(child)
                if (
                    (after.st_dev, after.st_ino, after.st_mode, after.st_uid,
                     after.st_nlink, after.st_size)
                    != (before.st_dev, before.st_ino, before.st_mode,
                        before.st_uid, before.st_nlink, before.st_size)
                ):
                    raise RuntimeError("child-watch blob identity raced")
                payload = b"".join(chunks)
                if len(payload) != before.st_size:
                    raise RuntimeError("child-watch blob size differs")
                blobs[name] = payload
                identities[name] = before
                aggregate += len(payload)
            finally:
                os.close(child)
        after_root = os.fstat(descriptor)
        if (
            (after_root.st_dev, after_root.st_ino, after_root.st_mode,
             after_root.st_uid, after_root.st_nlink)
            != (root_stat.st_dev, root_stat.st_ino, root_stat.st_mode,
                root_stat.st_uid, root_stat.st_nlink)
            or tuple(sorted(os.listdir(descriptor))) != names
        ):
            raise RuntimeError("child-watch blob root inventory raced")
        return blobs, identities, root_stat
    finally:
        os.close(descriptor)


def _read_child_watch_bundle(path: Path) -> dict[str, Any]:
    """Read and replay one stable compact-ledger/blob-root snapshot."""

    from app.services.tesseract_broker_protocol import (
        MAX_BROKER_AUDIT_BLOB_BYTES,
        MAX_BROKER_AUDIT_LEDGER_BYTES,
        canonical_sha256,
        replay_broker_audit_blob_bundle,
    )

    last_error: BaseException | None = None
    for _attempt in range(4):
        try:
            compact = _read_private_payload(
                path, maximum_bytes=MAX_BROKER_AUDIT_LEDGER_BYTES
            )
            record_root_path = path.parent / f"{path.name}.records"
            event_root_path = path.parent / f"{path.name}.events"
            record_blobs, record_stats, record_root_stat = (
                _read_child_watch_blob_root(
                    record_root_path,
                    name_pattern=re.compile(r"r[0-9]{8}-[0-9a-f]{16}\.json"),
                    maximum_bytes=MAX_BROKER_AUDIT_BLOB_BYTES,
                )
            )
            event_blobs, event_stats, event_root_stat = (
                _read_child_watch_blob_root(
                    event_root_path,
                    name_pattern=re.compile(r"e[0-9]{8}-[0-9a-f]{16}\.json"),
                    maximum_bytes=MAX_BROKER_AUDIT_BLOB_BYTES,
                )
            )
            replay = replay_broker_audit_blob_bundle(
                compact_ledger=compact,
                record_blobs=record_blobs,
                event_blobs=event_blobs,
            )
            previous_blob_sha256 = "0" * 64
            for row in replay["rows"]:
                name = (
                    f"r{row['row_sequence']:08d}-"
                    f"{row['record_sha256'][:16]}.json"
                )
                observed = record_stats[name]
                blob_mapping = {
                    "schema_id": (
                        "parser-tesseract-broker-audit-record-blob-v1"
                    ),
                    "row_sequence": row["row_sequence"],
                    "kind": row["kind"],
                    "record_bytes": row["record_bytes"],
                    "record_sha256": row["record_sha256"],
                    "resolved_path": str(record_root_path / name),
                    "device": int(observed.st_dev),
                    "inode": int(observed.st_ino),
                    "mode": int(observed.st_mode),
                    "uid": int(observed.st_uid),
                    "nlink": int(observed.st_nlink),
                    "previous_blob_record_sha256": previous_blob_sha256,
                }
                previous_blob_sha256 = canonical_sha256(blob_mapping)
            record_root = {
                "schema_id": (
                    "parser-tesseract-broker-audit-record-blob-root-v1"
                ),
                "resolved_path": str(record_root_path),
                "device": int(record_root_stat.st_dev),
                "inode": int(record_root_stat.st_ino),
                "mode": int(record_root_stat.st_mode),
                "uid": int(record_root_stat.st_uid),
                "nlink": int(record_root_stat.st_nlink),
                "entry_count": replay["record_blob_count"],
                "aggregate_bytes": replay["record_blob_size_bytes"],
                "head_sha256": previous_blob_sha256,
            }
            record_root["record_sha256"] = canonical_sha256(record_root)
            event_root = {
                "schema_id": "parser-tesseract-watch-event-blob-root-v1",
                "resolved_path": str(event_root_path),
                "device": int(event_root_stat.st_dev),
                "inode": int(event_root_stat.st_ino),
                "mode": int(event_root_stat.st_mode),
                "uid": int(event_root_stat.st_uid),
                "nlink": int(event_root_stat.st_nlink),
                "entry_count": replay["event_count"],
                "aggregate_bytes": replay["event_blob_size_bytes"],
                "head_sha256": replay["event_head_sha256"],
            }
            event_root["record_sha256"] = canonical_sha256(event_root)
            return {
                **replay,
                "compact_ledger": compact,
                "record_blobs": record_blobs,
                "event_blobs": event_blobs,
                "record_blob_identities": {
                    name: {
                        "device": int(observed.st_dev),
                        "inode": int(observed.st_ino),
                        "mode": int(observed.st_mode),
                        "uid": int(observed.st_uid),
                        "nlink": int(observed.st_nlink),
                    }
                    for name, observed in record_stats.items()
                },
                "event_blob_identities": {
                    name: {
                        "device": int(observed.st_dev),
                        "inode": int(observed.st_ino),
                        "mode": int(observed.st_mode),
                        "uid": int(observed.st_uid),
                        "nlink": int(observed.st_nlink),
                    }
                    for name, observed in event_stats.items()
                },
                "record_blob_head_sha256": previous_blob_sha256,
                "record_blob_root": record_root,
                "event_blob_root": event_root,
            }
        except (OSError, RuntimeError, ValueError) as error:
            last_error = error
            time.sleep(0)
    raise RuntimeError("child-watch audit bundle lacked a stable snapshot") from last_error


def _read_live_child_watch_snapshot(path: Path) -> _LiveChildWatchSnapshot:
    """Read one stable, hash-checked prefix of the watchdog-owned child log."""

    bundle = _read_child_watch_bundle(path)

    broker_sequence = 0
    broker_head = "0" * 64
    event_sequence = 0
    event_head = "0" * 64
    known: dict[tuple[int, int], dict[str, Any]] = {}
    open_registrations: dict[tuple[int, int], dict[str, Any]] = {}
    terminal_wait4: set[tuple[int, int]] = set()
    pre_exec_samples: dict[tuple[int, int], dict[str, Any]] = {}
    registration_by_sha: dict[str, tuple[int, int]] = {}
    pending_spawn_intents: dict[tuple[Any, ...], dict[str, Any]] = {}
    provisional_children: dict[tuple[int, int], dict[str, Any]] = {}

    def spawn_token(record: Mapping[str, Any]) -> tuple[Any, ...]:
        return tuple(
            record.get(name)
            for name in (
                "request_id",
                "request_epoch",
                "request_sequence",
                "spawn_sequence",
                "spawn_nonce_sha256",
            )
        )

    for parsed in bundle["merged_entries"]:
        value = dict(parsed)
        schema_id = value.get("schema_id")
        if schema_id == "parser-tesseract-broker-ledger-row-v2":
            if set(value) != {
                "schema_id",
                "row_sequence",
                "previous_row_sha256",
                "kind",
                "kind_code",
                "record",
                "record_bytes",
                "record_sha256",
                "compact_commitment_hex",
                "row_sha256",
            }:
                raise RuntimeError("live child-watch broker fields differ")
            row_sha256 = value["row_sha256"]
            if (
                value["row_sequence"] != broker_sequence + 1
                or value["previous_row_sha256"] != broker_head
                or type(value["record"]) is not dict
            ):
                raise RuntimeError("live child-watch broker chain differs")
            broker_sequence += 1
            broker_head = str(row_sha256)
            record = dict(value["record"])
            if value["kind"] == "spawn_intent":
                token = spawn_token(record)
                candidate = dict(record)
                spawn_sha256 = candidate.pop("spawn_intent_sha256", None)
                if (
                    any(item in (None, "", 0) for item in token)
                    or spawn_sha256 != _canonical_sha256(candidate)
                    or token in pending_spawn_intents
                ):
                    raise RuntimeError("live spawn intent differs")
                pending_spawn_intents[token] = {
                    "record": record,
                    "row_sha256": row_sha256,
                }
            elif value["kind"] == "child_provisional":
                token = spawn_token(record)
                pending = pending_spawn_intents.get(token)
                key = (int(record.get("pid", 0)), int(record.get("start_abstime", 0)))
                candidate = dict(record)
                provisional_sha256 = candidate.pop(
                    "provisional_record_sha256", None
                )
                if (
                    pending is None
                    or min(key) <= 0
                    or key in known
                    or provisional_sha256 != _canonical_sha256(candidate)
                    or record.get("spawn_intent_sha256")
                    != pending["record"].get("spawn_intent_sha256")
                    or record.get("spawn_intent_ledger_row_sha256")
                    != pending["row_sha256"]
                ):
                    raise RuntimeError("live provisional child identity differs")
                pending_spawn_intents.pop(token)
                provisional_children[key] = record
                known[key] = record
            elif value["kind"] == "child_intent":
                key = (int(record.get("pid", 0)), int(record.get("start_abstime", 0)))
                provisional = provisional_children.get(key)
                registration_sha256 = record.get(
                    "watchdog_registration_sha256"
                )
                if (
                    provisional is None
                    or registration_by_sha.get(str(registration_sha256)) != key
                    or record.get("provisional_record_sha256")
                    != provisional.get("provisional_record_sha256")
                    or record.get("spawn_intent_sha256")
                    != provisional.get("spawn_intent_sha256")
                ):
                    raise RuntimeError("live child intent identity differs")
                known[key] = {**provisional, **record}
            elif value["kind"] == "child_wait4":
                key = (int(record.get("pid", 0)), int(record.get("start_abstime", 0)))
                if min(key) <= 0 or key not in known:
                    raise RuntimeError("live child wait4 identity differs")
                terminal_wait4.add(key)
                open_registrations.pop(key, None)
        elif schema_id == "phase-latency-prewarm-child-watch-event-v1":
            if set(value) != {
                "schema_id",
                "event_sequence",
                "previous_event_sha256",
                "kind",
                "frame_sha256",
                "payload",
                "observed_monotonic_ns",
                "record_sha256",
            }:
                raise RuntimeError("live child-watch event fields differ")
            record_sha256 = value["record_sha256"]
            if (
                value["event_sequence"] != event_sequence + 1
                or value["previous_event_sha256"] != event_head
                or type(value["payload"]) is not dict
            ):
                raise RuntimeError("live child-watch event chain differs")
            event_sequence += 1
            event_head = str(record_sha256)
            payload = dict(value["payload"])
            kind = value["kind"]
            if kind == "child_watch_register":
                registration_sha256 = payload.get("registration_sha256")
                candidate = dict(payload)
                candidate.pop("registration_sha256", None)
                key = (
                    int(payload.get("pid", 0)),
                    int(payload.get("start_abstime", 0)),
                )
                if (
                    min(key) <= 0
                    or type(registration_sha256) is not str
                    or registration_sha256 != _canonical_sha256(candidate)
                    or key not in known
                    or key in open_registrations
                    or registration_sha256 in registration_by_sha
                ):
                    raise RuntimeError("live child registration differs")
                known[key] = payload
                open_registrations[key] = payload
                registration_by_sha[registration_sha256] = key
            elif kind == "child_watch_birth":
                registration_sha256 = payload.get("registration_sha256")
                if registration_sha256 not in registration_by_sha:
                    raise RuntimeError("live child birth lacks registration")
                key = registration_by_sha[str(registration_sha256)]
                sample = payload.get("pre_exec_gated_child_sample")
                if type(sample) is not dict:
                    raise RuntimeError("live child birth lacks gated sample")
                sample_value = dict(sample)
                sample_sha256 = sample_value.pop("record_sha256", None)
                if (
                    sample_value.get("schema_id")
                    != "phase-latency-pre-exec-gated-child-sample-v1"
                    or sample_sha256 != _canonical_sha256(sample_value)
                    or (
                        sample_value.get("pid"),
                        sample_value.get("start_abstime"),
                    )
                    != key
                    or sample_value.get("sampled_before_exec_release_e") is not True
                    or key in pre_exec_samples
                ):
                    raise RuntimeError("live pre-exec child sample differs")
                pre_exec_samples[key] = dict(sample)
            elif kind == "child_watch_reaped":
                registration_sha256 = payload.get("registration_sha256")
                key = registration_by_sha.get(str(registration_sha256))
                if key is None or key not in terminal_wait4:
                    raise RuntimeError("live child reaped event lacks wait4")
                open_registrations.pop(key, None)
            else:
                raise RuntimeError("live child-watch event kind differs")
        else:
            raise RuntimeError("live child-watch schema differs")
    return _LiveChildWatchSnapshot(
        raw_size_bytes=bundle["compact_ledger_size_bytes"],
        raw_sha256=bundle["compact_ledger_sha256"],
        broker_row_count=broker_sequence,
        broker_head_sha256=broker_head,
        event_count=event_sequence,
        event_head_sha256=event_head,
        pending_spawn_intents=pending_spawn_intents,
        provisional_children=provisional_children,
        known_children=known,
        open_registrations=open_registrations,
        terminal_wait4_identities=frozenset(terminal_wait4),
        pre_exec_gated_samples=pre_exec_samples,
        record_blob_count=bundle["record_blob_count"],
        record_blob_size_bytes=bundle["record_blob_size_bytes"],
        record_blob_head_sha256=bundle["record_blob_head_sha256"],
        record_blob_root=bundle["record_blob_root"],
        event_blob_size_bytes=bundle["event_blob_size_bytes"],
        event_blob_root=bundle["event_blob_root"],
    )


def _retained_child_audit_joins(
    path: Path,
) -> dict[str, dict[str, Any]]:
    """Rebuild every one-use broker/watchdog child join from terminal bytes."""

    bundle = _read_child_watch_bundle(path)
    joins: dict[str, dict[str, Any]] = {}
    spawn_to_registration: dict[tuple[Any, ...], str] = {}

    def spawn_token(record: Mapping[str, Any]) -> tuple[Any, ...]:
        return tuple(
            record.get(name)
            for name in (
                "request_id",
                "request_epoch",
                "request_sequence",
                "spawn_sequence",
                "spawn_nonce_sha256",
            )
        )

    def spawn_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
        return tuple(
            record.get(name)
            for name in (
                "request_id",
                "request_epoch",
                "request_sequence",
                "spawn_sequence",
                "spawn_nonce_sha256",
                "pid",
                "start_abstime",
            )
        )

    def put_once(join: dict[str, Any], name: str, value: Any) -> None:
        if name in join:
            raise RuntimeError(f"child audit {name} was reused")
        join[name] = value

    pending_spawn_intents: dict[tuple[Any, ...], dict[str, Any]] = {}
    pending_provisionals: dict[tuple[Any, ...], dict[str, Any]] = {}
    for value in bundle["merged_entries"]:
        if value["schema_id"] == "parser-tesseract-broker-ledger-row-v2":
            kind = value["kind"]
            record = dict(value["record"])
            if kind == "spawn_intent":
                token = spawn_token(record)
                put_once(
                    pending_spawn_intents,
                    token,
                    {
                        "spawn_intent": record,
                        "spawn_intent_ledger_row_sha256": value[
                            "row_sha256"
                        ],
                    },
                )
                continue
            if kind == "child_provisional":
                token = spawn_token(record)
                spawn = pending_spawn_intents.pop(token, None)
                key = spawn_key(record)
                if (
                    spawn is None
                    or key in pending_provisionals
                    or record.get("spawn_intent_sha256")
                    != spawn["spawn_intent"].get("spawn_intent_sha256")
                    or record.get("spawn_intent_ledger_row_sha256")
                    != spawn["spawn_intent_ledger_row_sha256"]
                ):
                    raise RuntimeError("child provisional audit join differs")
                pending_provisionals[key] = {
                    **spawn,
                    "provisional": record,
                    "provisional_child_ledger_row_sha256": value[
                        "row_sha256"
                    ],
                }
                continue
            registration_sha256 = record.get("registration_sha256")
            if registration_sha256 is None:
                registration_sha256 = record.get(
                    "watchdog_registration_sha256"
                )
            if registration_sha256 is None:
                registration_sha256 = spawn_to_registration.get(
                    spawn_key(record)
                )
            if registration_sha256 is None:
                continue
            join = joins.get(str(registration_sha256))
            if join is None:
                raise RuntimeError("child audit row preceded registration")
            if kind == "watchdog_register_ack":
                put_once(join, "registration_ack", record)
                put_once(
                    join, "registration_ack_row_sha256", value["row_sha256"]
                )
            elif kind == "child_intent":
                put_once(join, "child_ready_intent", record)
                put_once(
                    join,
                    "child_ready_intent_ledger_row_sha256",
                    value["row_sha256"],
                )
            elif kind == "child_birth":
                put_once(join, "birth_commitment", record)
                put_once(join, "birth_ledger_row_sha256", value["row_sha256"])
            elif kind == "watchdog_birth_ack":
                put_once(join, "birth_ack", record)
                put_once(join, "birth_ack_row_sha256", value["row_sha256"])
            elif kind == "child_exec_release":
                put_once(join, "exec_release", record)
                put_once(
                    join, "exec_release_ledger_row_sha256", value["row_sha256"]
                )
            elif kind == "child_wait4":
                put_once(join, "wait4", record)
                put_once(join, "wait4_ledger_row_sha256", value["row_sha256"])
            elif kind == "watchdog_reaped_ack":
                put_once(join, "reaped_ack", record)
                put_once(join, "reaped_ack_row_sha256", value["row_sha256"])
        elif value["schema_id"] == (
            "phase-latency-prewarm-child-watch-event-v1"
        ):
            kind = value["kind"]
            payload = dict(value["payload"])
            registration_sha256 = payload.get("registration_sha256")
            if kind == "child_watch_register":
                if type(registration_sha256) is not str:
                    raise RuntimeError("child registration SHA differs")
                key = spawn_key(payload)
                if (
                    registration_sha256 in joins
                    or key in spawn_to_registration
                    or key not in pending_provisionals
                ):
                    raise RuntimeError("child registration join differs")
                joins[registration_sha256] = {
                    **pending_provisionals.pop(key),
                    "registration": payload,
                    "registration_event_record_sha256": value[
                        "record_sha256"
                    ],
                }
                spawn_to_registration[key] = registration_sha256
                continue
            join = joins.get(str(registration_sha256))
            if join is None:
                raise RuntimeError("child event preceded registration")
            if kind == "child_watch_birth":
                put_once(join, "birth_event", payload)
                put_once(
                    join,
                    "birth_event_record_sha256",
                    value["record_sha256"],
                )
            elif kind == "child_watch_reaped":
                put_once(join, "reaped_event", payload)
                put_once(
                    join,
                    "reaped_event_record_sha256",
                    value["record_sha256"],
                )
    if pending_spawn_intents or pending_provisionals:
        raise RuntimeError("child audit retained unregistered spawn custody")
    required = {
        "spawn_intent",
        "spawn_intent_ledger_row_sha256",
        "provisional",
        "provisional_child_ledger_row_sha256",
        "registration",
        "registration_event_record_sha256",
        "registration_ack",
        "registration_ack_row_sha256",
        "child_ready_intent",
        "child_ready_intent_ledger_row_sha256",
        "birth_commitment",
        "birth_ledger_row_sha256",
        "birth_event",
        "birth_event_record_sha256",
        "birth_ack",
        "birth_ack_row_sha256",
        "exec_release",
        "exec_release_ledger_row_sha256",
        "wait4",
        "wait4_ledger_row_sha256",
        "reaped_event",
        "reaped_event_record_sha256",
        "reaped_ack",
        "reaped_ack_row_sha256",
    }
    if any(set(join) != required for join in joins.values()):
        raise RuntimeError("terminal child audit join is incomplete")
    for registration_sha256, join in joins.items():
        spawn_intent = join["spawn_intent"]
        provisional = join["provisional"]
        registration = join["registration"]
        registration_ack = join["registration_ack"]
        child_ready_intent = join["child_ready_intent"]
        birth = join["birth_commitment"]
        if (
            registration.get("registration_sha256") != registration_sha256
            or spawn_token(spawn_intent) != spawn_token(provisional)
            or spawn_key(provisional) != spawn_key(registration)
            or spawn_key(registration) != spawn_key(child_ready_intent)
            or spawn_key(child_ready_intent) != spawn_key(birth)
            or provisional.get("spawn_intent_sha256")
            != spawn_intent.get("spawn_intent_sha256")
            or provisional.get("spawn_intent_ledger_row_sha256")
            != join["spawn_intent_ledger_row_sha256"]
            or registration.get("provisional_child_ledger_row_sha256")
            != join["provisional_child_ledger_row_sha256"]
            or registration_ack.get("provisional_child_ledger_row_sha256")
            != join["provisional_child_ledger_row_sha256"]
            or child_ready_intent.get("provisional_record_sha256")
            != provisional.get("provisional_record_sha256")
            or child_ready_intent.get("watchdog_registration_sha256")
            != registration_sha256
            or child_ready_intent.get("watchdog_registration_ack_sha256")
            != registration_ack.get("watchdog_record_sha256")
            or birth.get("child_ready_intent_ledger_row_sha256")
            != join["child_ready_intent_ledger_row_sha256"]
            or birth.get("child_ready_sha256")
            != child_ready_intent.get("child_ready_sha256")
        ):
            raise RuntimeError("terminal child audit lineage differs")
    return joins


@dataclass(frozen=True, slots=True)
class _ExactProcessMetricObservation:
    cpu: DarwinProcessSelfCpuSample
    sample_started_monotonic_ns: int
    sample_completed_monotonic_ns: int
    rss_bytes: int
    thread_count: int
    native_thread_ids: tuple[int, ...]
    file_descriptor_count: int


def _sample_exact_process_metric(
    expected: Mapping[str, Any],
) -> _ExactProcessMetricObservation:
    from app.services.tesseract_broker_native import native_thread_inventory

    pid = int(expected["pid"])
    expected_identity = (
        pid,
        int(expected["start_abstime"]),
        int(expected["ppid"]),
        int(expected["pgid"]),
        int(expected["sid"]),
    )
    sample_started_monotonic_ns = max(1, time.monotonic_ns())
    identity_before = read_darwin_process_identity(pid)
    if (
        identity_before.pid,
        identity_before.start_abstime,
        identity_before.parent_pid,
        identity_before.process_group_id,
        identity_before.session_id,
    ) != expected_identity:
        raise RuntimeError("controller resource identity drifted before sampling")
    native_thread_ids_before = tuple(native_thread_inventory(pid))
    process = psutil.Process(pid)
    with process.oneshot():
        memory = process.memory_info()
        rss_bytes = int(memory.rss)
        thread_count = int(process.num_threads())
        if not hasattr(process, "num_fds"):
            raise RuntimeError("Darwin process FD count is unavailable")
        file_descriptor_count = int(process.num_fds())
    cpu = sample_darwin_process_self_cpu(
        pid=pid,
        expected_start_abstime=int(expected["start_abstime"]),
        expected_parent_pid=int(expected["ppid"]),
        expected_process_group_id=int(expected["pgid"]),
        expected_session_id=int(expected["sid"]),
    )
    if any(
        value < 0
        for value in (rss_bytes, thread_count, file_descriptor_count)
    ) or thread_count <= 0:
        raise RuntimeError("controller resource metric differs")
    native_thread_ids_after = tuple(native_thread_inventory(pid))
    identity_after = read_darwin_process_identity(pid)
    sample_completed_monotonic_ns = max(1, time.monotonic_ns())
    if (
        native_thread_ids_before != native_thread_ids_after
        or native_thread_ids_after
        != tuple(sorted(set(native_thread_ids_after)))
        or len(native_thread_ids_after) != thread_count
        or (
            identity_after.pid,
            identity_after.start_abstime,
            identity_after.parent_pid,
            identity_after.process_group_id,
            identity_after.session_id,
        )
        != expected_identity
        or not (
            sample_started_monotonic_ns
            <= cpu.observed_monotonic_ns
            <= sample_completed_monotonic_ns
        )
    ):
        raise RuntimeError("controller identity/thread inventory drifted")
    return _ExactProcessMetricObservation(
        cpu=cpu,
        sample_started_monotonic_ns=sample_started_monotonic_ns,
        sample_completed_monotonic_ns=sample_completed_monotonic_ns,
        rss_bytes=rss_bytes,
        thread_count=thread_count,
        native_thread_ids=native_thread_ids_after,
        file_descriptor_count=file_descriptor_count,
    )


class _ControllerOwnedRequestResourceSampler:
    """Concurrent controller sampler for both roots and registered children."""

    def __init__(
        self,
        *,
        attempt_id: str,
        request_id: str,
        request_epoch: int,
        request_sequence: int,
        worker_identity: Mapping[str, Any],
        broker_identity: Mapping[str, Any],
        framework_thread_baseline: FrameworkThreadBaseline,
        child_watch_log_path: Path,
        durable_log: _DurableHashChainedLog,
        fatal_callback: Callable[[], None],
    ) -> None:
        self.attempt_id = attempt_id
        self.request_id = request_id
        self.request_epoch = request_epoch
        self.request_sequence = request_sequence
        self.worker_identity = dict(worker_identity)
        self.broker_identity = dict(broker_identity)
        self.framework_thread_baseline = framework_thread_baseline
        self.required_worker_proc_thread_ids = (
            framework_thread_baseline.full_worker_proc_thread_ids
        )
        self.child_watch_log_path = child_watch_log_path
        self.durable_log = durable_log
        self.fatal_callback = fatal_callback
        self._stop = threading.Event()
        self._boundary_active = threading.Event()
        self._sample_lock = threading.Lock()
        self._samples: list[dict[str, Any]] = []
        self._memberships: list[str] = []
        self._row_sha256s: list[str] = []
        self._first_log_row_index = len(durable_log.rows)
        self._pre_exec_samples: dict[tuple[int, int], dict[str, Any]] = {}
        self._provisional_child_tokens: dict[
            tuple[int, int], tuple[Any, ...]
        ] = {}
        self._error: BaseException | None = None
        self._thread = threading.Thread(
            target=self._run,
            name=f"lat-us02-controller-resource-{request_sequence}",
            daemon=False,
        )

    @staticmethod
    def _identity_mapping(
        metric: _ExactProcessMetricObservation,
    ) -> dict[str, int]:
        return {
            "pid": metric.cpu.pid,
            "start_abstime": metric.cpu.start_abstime,
            "ppid": metric.cpu.parent_pid,
            "pgid": metric.cpu.process_group_id,
            "sid": metric.cpu.session_id,
        }

    def _sample_child(
        self,
        expected: Mapping[str, Any],
        *,
        snapshot: _LiveChildWatchSnapshot,
    ) -> _ExactProcessMetricObservation | None:
        normalized = {
            "pid": int(expected["pid"]),
            "start_abstime": int(expected["start_abstime"]),
            "ppid": int(expected.get("ppid", self.broker_identity["pid"])),
            "pgid": int(expected.get("pgid", self.broker_identity["pgid"])),
            "sid": int(expected.get("sid", self.broker_identity["sid"])),
        }
        key = (normalized["pid"], normalized["start_abstime"])
        try:
            return _sample_exact_process_metric(normalized)
        except (ProcessLookupError, psutil.NoSuchProcess, psutil.ZombieProcess):
            refreshed = _read_live_child_watch_snapshot(
                self.child_watch_log_path
            )
            if key in refreshed.terminal_wait4_identities:
                return None
            raise RuntimeError(
                "registered child disappeared without durable wait4"
            )

    def _sample_once(self, *, boundary_membership: str) -> None:
        if boundary_membership not in {
            "coverage_only",
            "boundary_begin",
            "boundary_interior",
            "boundary_end",
        }:
            raise ValueError("controller resource boundary membership differs")
        with self._sample_lock:
            self._sample_once_locked(boundary_membership=boundary_membership)

    def _sample_once_locked(self, *, boundary_membership: str) -> None:
        child_snapshot = _read_live_child_watch_snapshot(
            self.child_watch_log_path
        )
        current_pre_exec_samples = {
            key: sample
            for key, sample in child_snapshot.pre_exec_gated_samples.items()
            if (
                child_snapshot.known_children.get(key, {}).get("request_id"),
                child_snapshot.known_children.get(key, {}).get(
                    "request_epoch"
                ),
                child_snapshot.known_children.get(key, {}).get(
                    "request_sequence"
                ),
            )
            == (
                self.request_id,
                self.request_epoch,
                self.request_sequence,
            )
        }
        for key, sample in current_pre_exec_samples.items():
            previous = self._pre_exec_samples.get(key)
            if previous is not None and previous != sample:
                raise RuntimeError("pre-exec gated child sample changed")
            self._pre_exec_samples[key] = sample
        worker_group = darwin_process_group_pids(
            int(self.worker_identity["pgid"])
        )
        if worker_group != (int(self.worker_identity["pid"]),):
            raise RuntimeError("fork-denied worker group ceased to be root-only")
        worker_metric = _sample_exact_process_metric(self.worker_identity)
        if worker_metric.native_thread_ids != self.required_worker_proc_thread_ids:
            raise RuntimeError(
                "complete worker PROC thread baseline drifted during sampling"
            )
        broker_group = darwin_process_group_pids(
            int(self.broker_identity["pgid"])
        )
        if int(self.broker_identity["pid"]) not in broker_group:
            raise RuntimeError("broker root disappeared during request sampling")
        broker_metric = _sample_exact_process_metric(self.broker_identity)

        child_metrics: dict[
            tuple[int, int], _ExactProcessMetricObservation
        ] = {}
        observed_children: dict[tuple[int, int], DarwinProcessSelfCpuSample] = {}
        for child_pid in broker_group:
            if child_pid != int(self.broker_identity["pid"]):
                identity = read_darwin_process_identity(child_pid)
                key = (identity.pid, identity.start_abstime)
                if key in observed_children:
                    raise RuntimeError("broker child identity was duplicated")
                observed_children[key] = identity
        unknown_keys = tuple(
            key
            for key in observed_children
            if key not in child_snapshot.known_children
        )
        if unknown_keys:
            refreshed = _read_live_child_watch_snapshot(
                self.child_watch_log_path
            )
            child_snapshot = refreshed
            unknown_keys = tuple(
                key
                for key in observed_children
                if key not in child_snapshot.known_children
            )
        current_pending_intents = {
            token: item
            for token, item in child_snapshot.pending_spawn_intents.items()
            if token[:3]
            == (
                self.request_id,
                self.request_epoch,
                self.request_sequence,
            )
        }
        if len(unknown_keys) > 1:
            raise RuntimeError("multiple children preceded provisional custody")
        if unknown_keys:
            key = unknown_keys[0]
            identity = observed_children[key]
            existing_token = self._provisional_child_tokens.get(key)
            if existing_token is None:
                unresolved_provisionals = {
                    tracked_key
                    for tracked_key in self._provisional_child_tokens
                    if tracked_key not in child_snapshot.provisional_children
                }
                if (
                    len(current_pending_intents) != 1
                    or unresolved_provisionals
                    or identity.parent_pid != int(self.broker_identity["pid"])
                    or identity.process_group_id != int(self.broker_identity["pgid"])
                    or identity.session_id != int(self.broker_identity["sid"])
                ):
                    raise RuntimeError(
                        "broker child lacked one durable pre-fork spawn intent"
                    )
                existing_token = next(iter(current_pending_intents))
                self._provisional_child_tokens[key] = existing_token
            elif existing_token not in current_pending_intents:
                raise RuntimeError("provisional child intent disappeared before join")
        for key, token in tuple(self._provisional_child_tokens.items()):
            provisional = child_snapshot.provisional_children.get(key)
            if provisional is not None:
                observed_token = tuple(
                    provisional.get(name)
                    for name in (
                        "request_id",
                        "request_epoch",
                        "request_sequence",
                        "spawn_sequence",
                        "spawn_nonce_sha256",
                    )
                )
                if observed_token != token:
                    raise RuntimeError("provisional child joined the wrong spawn intent")
            elif key not in observed_children:
                raise RuntimeError("unjoined provisional child disappeared")
        for key, identity in observed_children.items():
            expected = child_snapshot.known_children.get(key)
            if expected is None:
                token = self._provisional_child_tokens.get(key)
                if token is None:
                    raise RuntimeError("broker child existed before durable intent")
                expected = {
                    "pid": identity.pid,
                    "start_abstime": identity.start_abstime,
                    "ppid": identity.parent_pid,
                    "pgid": identity.process_group_id,
                    "sid": identity.session_id,
                }
            metric = self._sample_child(expected, snapshot=child_snapshot)
            if metric is not None:
                child_metrics[key] = metric
        for key, expected in child_snapshot.open_registrations.items():
            if key in child_metrics:
                continue
            metric = self._sample_child(expected, snapshot=child_snapshot)
            if metric is not None:
                child_metrics[key] = metric

        ordered = (worker_metric, broker_metric)
        process_rows: list[dict[str, Any]] = []
        for index, metric in enumerate(ordered):
            role = (
                "parser_worker"
                if index == 0
                else "tesseract_broker"
                if index == 1
                else "tesseract_child"
            )
            process_rows.append(
                {
                    "role": role,
                    **self._identity_mapping(metric),
                    "sample_started_monotonic_ns": (
                        metric.sample_started_monotonic_ns
                    ),
                    "observed_monotonic_ns": metric.cpu.observed_monotonic_ns,
                    "sample_completed_monotonic_ns": (
                        metric.sample_completed_monotonic_ns
                    ),
                    "user_cpu_ns": metric.cpu.user_cpu_ns,
                    "system_cpu_ns": metric.cpu.system_cpu_ns,
                    "rss_bytes": metric.rss_bytes,
                    "thread_count": metric.thread_count,
                    "native_thread_ids": list(metric.native_thread_ids),
                    "file_descriptor_count": metric.file_descriptor_count,
                }
            )
        for key in sorted(child_metrics):
            metric = child_metrics[key]
            process_rows.append(
                {
                    "role": "tesseract_child",
                    **self._identity_mapping(metric),
                    "sample_started_monotonic_ns": (
                        metric.sample_started_monotonic_ns
                    ),
                    "observed_monotonic_ns": metric.cpu.observed_monotonic_ns,
                    "sample_completed_monotonic_ns": (
                        metric.sample_completed_monotonic_ns
                    ),
                    "user_cpu_ns": metric.cpu.user_cpu_ns,
                    "system_cpu_ns": metric.cpu.system_cpu_ns,
                    "rss_bytes": metric.rss_bytes,
                    "thread_count": metric.thread_count,
                    "native_thread_ids": list(metric.native_thread_ids),
                    "file_descriptor_count": metric.file_descriptor_count,
                }
            )
        process_rows[2:] = sorted(
            process_rows[2:], key=lambda item: (item["pid"], item["start_abstime"])
        )
        sweep_started_ns = min(
            int(item["sample_started_monotonic_ns"]) for item in process_rows
        )
        sweep_completed_ns = max(
            int(item["sample_completed_monotonic_ns"]) for item in process_rows
        )
        sweep_span_ns = sweep_completed_ns - sweep_started_ns
        if sweep_span_ns > PEAK_SAMPLE_EDGE_TOLERANCE_NS:
            raise RuntimeError(
                "controller resource process sweep exceeded tolerance"
            )
        record = {
            "schema_id": "phase-latency-controller-resource-sample-v1",
            "attempt_id": self.attempt_id,
            "request_id": self.request_id,
            "request_epoch": self.request_epoch,
            "request_sequence": self.request_sequence,
            "observed_monotonic_ns": sweep_completed_ns,
            "sweep_started_monotonic_ns": sweep_started_ns,
            "sweep_completed_monotonic_ns": sweep_completed_ns,
            "sweep_span_ns": sweep_span_ns,
            "maximum_sweep_span_ns": PEAK_SAMPLE_EDGE_TOLERANCE_NS,
            "sample_order": "worker-root-broker-root-registered-children-v1",
            "boundary_membership": boundary_membership,
            "processes": process_rows,
            "aggregate": {
                "process_count": len(process_rows),
                "rss_bytes": sum(int(item["rss_bytes"]) for item in process_rows),
                "thread_count": sum(
                    int(item["thread_count"]) for item in process_rows
                ),
                "file_descriptor_count": sum(
                    int(item["file_descriptor_count"]) for item in process_rows
                ),
            },
            "child_watch_prefix": {
                "size_bytes": child_snapshot.raw_size_bytes,
                "sha256": child_snapshot.raw_sha256,
                "broker_row_count": child_snapshot.broker_row_count,
                "broker_head_sha256": child_snapshot.broker_head_sha256,
                "record_blob_count": child_snapshot.record_blob_count,
                "record_blob_size_bytes": (
                    child_snapshot.record_blob_size_bytes
                ),
                "record_blob_head_sha256": (
                    child_snapshot.record_blob_head_sha256
                ),
                "record_blob_root_sha256": (
                    child_snapshot.record_blob_root["record_sha256"]
                ),
                "event_count": child_snapshot.event_count,
                "event_blob_size_bytes": child_snapshot.event_blob_size_bytes,
                "event_blob_root_sha256": (
                    child_snapshot.event_blob_root["record_sha256"]
                ),
                "event_head_sha256": child_snapshot.event_head_sha256,
                "open_registration_count": len(
                    child_snapshot.open_registrations
                ),
                "terminal_wait4_count": len(
                    child_snapshot.terminal_wait4_identities
                ),
                "current_request_pre_exec_gated_sample_record_sha256s": sorted(
                    sample["record_sha256"]
                    for sample in current_pre_exec_samples.values()
                ),
            },
        }
        row_sha256 = self.durable_log.append(
            kind="controller-resource-sample", record=record
        )
        self._samples.append(record)
        self._memberships.append(boundary_membership)
        self._row_sha256s.append(row_sha256)
        if len(self._samples) > MAXIMUM_CONTROLLER_RESOURCE_SAMPLES:
            raise RuntimeError("controller resource sample bound exceeded")

    def _run(self) -> None:
        try:
            while not self._stop.wait(
                PEAK_SAMPLE_TARGET_INTERVAL_NS / 1_000_000_000
            ):
                with self._sample_lock:
                    self._sample_once_locked(
                        boundary_membership=(
                            "boundary_interior"
                            if self._boundary_active.is_set()
                            else "coverage_only"
                        )
                    )
        except BaseException as error:
            self._error = error
            self._stop.set()
            try:
                self.fatal_callback()
            except BaseException:
                pass

    def start(self) -> None:
        self._sample_once(boundary_membership="coverage_only")
        self._thread.start()

    def sample_boundary_edge(self, edge: Literal["begin", "end"]) -> None:
        with self._sample_lock:
            if edge == "begin":
                self._boundary_active.set()
                self._sample_once_locked(
                    boundary_membership="boundary_begin"
                )
                return
            self._sample_once_locked(boundary_membership="boundary_end")
            self._boundary_active.clear()

    def finish(self) -> _ControllerRequestResourceWindow:
        self._stop.set()
        self._thread.join(timeout=2.0)
        if self._thread.is_alive():
            raise RuntimeError("controller resource sampler did not stop")
        if self._error is not None:
            raise RuntimeError("controller resource sampling failed") from self._error
        self._sample_once(boundary_membership="coverage_only")
        terminal_snapshot = _read_live_child_watch_snapshot(
            self.child_watch_log_path
        )
        for key, token in self._provisional_child_tokens.items():
            provisional = terminal_snapshot.provisional_children.get(key)
            if provisional is None or tuple(
                provisional.get(name)
                for name in (
                    "request_id",
                    "request_epoch",
                    "request_sequence",
                    "spawn_sequence",
                    "spawn_nonce_sha256",
                )
            ) != token:
                raise RuntimeError("provisional child custody remained unjoined")
        if len(self._samples) < 2:
            raise RuntimeError("controller resource coverage is insufficient")
        intervals = tuple(
            (
                int(item["sweep_started_monotonic_ns"]),
                int(item["sweep_completed_monotonic_ns"]),
            )
            for item in self._samples
        )
        if any(
            later_start < earlier_completed
            for (_, earlier_completed), (later_start, _) in zip(
                intervals, intervals[1:], strict=False
            )
        ):
            raise RuntimeError("controller resource samples are not monotonic")
        maximum_gap_ns = max(
            later_start - earlier_completed
            for (_, earlier_completed), (later_start, _) in zip(
                intervals, intervals[1:], strict=False
            )
        )
        if maximum_gap_ns > PEAK_SAMPLE_MAXIMUM_GAP_NS:
            raise RuntimeError("controller resource sampling cadence was missed")
        boundary_samples = tuple(
            item
            for item, membership in zip(
                self._samples, self._memberships, strict=True
            )
            if membership != "coverage_only"
        )
        if len(boundary_samples) < 2:
            raise RuntimeError("controller boundary resource coverage is insufficient")
        boundary_intervals = tuple(
            (
                int(item["sweep_started_monotonic_ns"]),
                int(item["sweep_completed_monotonic_ns"]),
            )
            for item in boundary_samples
        )
        boundary_maximum_gap_ns = max(
            later_start - earlier_completed
            for (_, earlier_completed), (later_start, _) in zip(
                boundary_intervals, boundary_intervals[1:], strict=False
            )
        )
        if boundary_maximum_gap_ns > PEAK_SAMPLE_MAXIMUM_GAP_NS:
            raise RuntimeError("controller boundary sampling cadence was missed")
        peak_record = max(
            boundary_samples,
            key=lambda item: int(item["aggregate"]["rss_bytes"]),
        )
        identities: dict[tuple[int, int], SampledProcessIdentity] = {}
        for sample in self._samples:
            for item in sample["processes"]:
                identity = SampledProcessIdentity(
                    role=item["role"],
                    pid=item["pid"],
                    start_abstime=item["start_abstime"],
                    parent_pid=item["ppid"],
                    process_group_id=item["pgid"],
                    session_id=item["sid"],
                )
                key = (identity.pid, identity.start_abstime)
                previous = identities.get(key)
                if previous is not None and previous != identity:
                    raise RuntimeError("sampled process lineage drifted")
                identities[key] = identity
        for key, sample in self._pre_exec_samples.items():
            identity = SampledProcessIdentity(
                role="tesseract_child",
                pid=sample["pid"],
                start_abstime=sample["start_abstime"],
                parent_pid=sample["ppid"],
                process_group_id=sample["pgid"],
                session_id=sample["sid"],
            )
            previous = identities.get(key)
            if previous is not None and previous != identity:
                raise RuntimeError("gated child sample lineage drifted")
            identities[key] = identity
        peak_aggregate = peak_record["aggregate"]
        raw_rows = self.durable_log.rows[self._first_log_row_index :]
        if len(raw_rows) != len(self._samples):
            raise RuntimeError("controller resource row retention differs")
        rows = tuple(
            ControllerResourceSampleLogRow.model_validate(row)
            for row in raw_rows
        )
        return _ControllerRequestResourceWindow(
            samples=tuple(self._samples),
            rows=rows,
            row_sha256s=tuple(self._row_sha256s),
            pre_exec_gated_child_samples=tuple(
                self._pre_exec_samples[key]
                for key in sorted(self._pre_exec_samples)
            ),
            sampled_process_identities=tuple(
                identities[key] for key in sorted(identities)
            ),
            peak=ResourceSample(
                phase=ResourcePhase.REQUEST_PEAK,
                observed_monotonic_ns=int(
                    peak_record["observed_monotonic_ns"]
                ),
                rss_bytes=int(peak_aggregate["rss_bytes"]),
                user_cpu_ns=sum(
                    int(item["user_cpu_ns"])
                    for item in peak_record["processes"]
                ),
                system_cpu_ns=sum(
                    int(item["system_cpu_ns"])
                    for item in peak_record["processes"]
                ),
                process_count=int(peak_aggregate["process_count"]),
                thread_count=int(peak_aggregate["thread_count"]),
                file_descriptor_count=int(
                    peak_aggregate["file_descriptor_count"]
                ),
            ),
            peak_process_count=max(
                int(item["aggregate"]["process_count"])
                for item in boundary_samples
            ),
            peak_rss_bytes=max(
                int(item["aggregate"]["rss_bytes"])
                for item in boundary_samples
            ),
            peak_thread_count=max(
                int(item["aggregate"]["thread_count"])
                for item in boundary_samples
            ),
            peak_file_descriptor_count=max(
                int(item["aggregate"]["file_descriptor_count"])
                for item in boundary_samples
            ),
            first_sample_monotonic_ns=boundary_intervals[0][0],
            last_sample_monotonic_ns=boundary_intervals[-1][1],
            maximum_gap_ns=boundary_maximum_gap_ns,
            target_interval_ns=PEAK_SAMPLE_TARGET_INTERVAL_NS,
            edge_tolerance_ns=PEAK_SAMPLE_EDGE_TOLERANCE_NS,
        )


def _contract_process_identity(
    *, role: Literal["parser_worker", "tesseract_broker"], identity: Any
) -> ExactProcessIdentity:
    return ExactProcessIdentity(
        role=role,
        pid=identity.pid,
        start_abstime=identity.start_abstime,
        parent_pid=identity.ppid,
        process_group_id=identity.pgid,
        session_id=identity.sid,
    )


def _contract_quiescence_receipt(
    *, receipt: Any, value: Any, edge: Literal["begin", "end"]
) -> BrokerQuiescenceReceipt:
    if (
        value.phase != edge
        or value.active_job_count != 0
        or value.recursive_descendants
        or not value.wait4_echild
    ):
        raise RuntimeError("broker quiescence projection differs")
    worker = _contract_process_identity(
        role="parser_worker", identity=value.worker_identity
    )
    broker = _contract_process_identity(
        role="tesseract_broker", identity=value.broker_identity
    )
    return BrokerQuiescenceReceipt(
        request_id=value.request_id,
        attempt_nonce_sha256=receipt.attempt_nonce_sha256,
        scope_sha256=receipt.scope_sha256,
        request_epoch=value.request_epoch,
        request_sequence=value.request_sequence,
        edge=edge,
        observed_monotonic_ns=value.observed_at_monotonic_ns,
        worker=worker,
        broker=broker,
        ledger_head_sha256=value.ledger_head_sha256,
        completed_spawn_count=value.completed_spawn_count,
        open_spawn_count=value.active_job_count,
        wait4_nohang_disposition="echild",
        ipc_pending_bytes=value.protocol_pending_bytes,
        worker_group_member_pids=tuple(
            item.pid for item in value.worker_group_members
        ),
        broker_group_member_pids=tuple(
            item.pid for item in value.broker_group_members
        ),
        broker_thread_count=value.broker_thread_count,
        broker_thread_inventory_sha256=(
            value.broker_thread_inventory_sha256
        ),
        broker_thread_observed_at_monotonic_ns=(
            value.broker_thread_observed_at_monotonic_ns
        ),
        request_root_inventory=BrokerScratchInventory.model_validate(
            asdict(value.request_root_inventory)
        ),
        process_group_scan_complete=value.process_group_scan_complete,
        admission_lock_held=value.admission_lock_held,
        broker_armed_and_blocked=value.broker_armed_and_blocked,
        worker_fork_denial_active=value.worker_fork_denial_active,
    )


def _contract_child_receipts(
    *,
    receipt: Any,
    child_audit_joins: Mapping[str, Mapping[str, Any]],
    resource_window: _ControllerRequestResourceWindow | None,
) -> tuple[BrokerChildCpuReceipt, ...]:
    retained: list[BrokerChildCpuReceipt] = []
    receipt_birth_keys = {
        (item.pid, item.start_abstime) for item in receipt.births
    }
    if resource_window is not None:
        gated_sample_keys = {
            (item["pid"], item["start_abstime"])
            for item in resource_window.pre_exec_gated_child_samples
        }
        if gated_sample_keys != receipt_birth_keys:
            raise RuntimeError("gated child sample/birth identity set differs")
    tombstone_by_key = {
        (item.spawn_sequence, item.spawn_nonce_sha256, item.pid): item
        for item in receipt.tombstones
    }
    for app_birth in receipt.births:
        birth = BrokerChildBirth.model_validate(asdict(app_birth))
        key = (
            birth.spawn_sequence,
            birth.spawn_nonce_sha256,
            birth.pid,
        )
        app_tombstone = tombstone_by_key.get(key)
        if app_tombstone is None:
            raise RuntimeError("broker birth lacks exact wait4 tombstone")
        tombstone = BrokerChildWait4Tombstone.model_validate(
            asdict(app_tombstone)
        )
        join = child_audit_joins.get(birth.watchdog_registration_sha256)
        if join is None:
            raise RuntimeError("broker birth lacks watchdog audit join")
        registration = join["registration"]
        registration_identity = (
            registration["request_id"],
            registration["request_epoch"],
            registration["request_sequence"],
            registration["spawn_sequence"],
            registration["spawn_nonce_sha256"],
            registration["pid"],
            registration["start_abstime"],
        )
        birth_identity = (
            birth.request_id,
            birth.request_epoch,
            birth.request_sequence,
            birth.spawn_sequence,
            birth.spawn_nonce_sha256,
            birth.pid,
            birth.start_abstime,
        )
        registration_ack = join["registration_ack"]
        spawn_intent = join["spawn_intent"]
        provisional = join["provisional"]
        child_ready_intent = join["child_ready_intent"]
        birth_commitment = join["birth_commitment"]
        birth_event = join["birth_event"]
        birth_ack = join["birth_ack"]
        exec_release = join["exec_release"]
        wait4 = join["wait4"]
        reaped_event = join["reaped_event"]
        reaped_ack = join["reaped_ack"]
        descriptor_projection = [
            item.model_dump(mode="json")
            for item in birth.open_file_descriptors
        ]
        inventory_projection = {
            "child_ready_sha256": birth.child_ready_sha256,
            "open_file_descriptors": descriptor_projection,
            "open_fd_inventory_sha256": birth.open_fd_inventory_sha256,
            "native_thread_count": birth.native_thread_count,
            "native_thread_ids": list(birth.native_thread_ids),
            "native_thread_inventory_sha256": (
                birth.native_thread_inventory_sha256
            ),
        }
        fork_adjacent_projection = {
            "broker_thread_count_immediately_before_fork": (
                birth.broker_thread_count_immediately_before_fork
            ),
            "broker_thread_inventory_immediately_before_fork_sha256": (
                birth.broker_thread_inventory_immediately_before_fork_sha256
            ),
            "broker_thread_immediately_before_fork_observed_at_monotonic_ns": (
                birth.broker_thread_immediately_before_fork_observed_at_monotonic_ns
            ),
            "blocked_signals_across_fork": list(
                birth.blocked_signals_across_fork
            ),
            "blocked_signals_across_fork_sha256": (
                birth.blocked_signals_across_fork_sha256
            ),
            "blockable_signals_masked_across_fork": (
                birth.blockable_signals_masked_across_fork
            ),
            "native_runtime_attestation_required": (
                birth.native_runtime_attestation_required
            ),
            "native_runtime_scan_interval_ns": (
                birth.native_runtime_scan_interval_ns
            ),
        }
        if (
            registration_identity != birth_identity
            or spawn_intent["spawn_intent_sha256"]
            != birth.spawn_intent_sha256
            or join["spawn_intent_ledger_row_sha256"]
            != birth.spawn_intent_ledger_row_sha256
            or provisional["provisional_record_sha256"]
            != birth.provisional_record_sha256
            or join["provisional_child_ledger_row_sha256"]
            != birth.provisional_child_ledger_row_sha256
            or provisional["provisional_observed_monotonic_ns"]
            != birth.provisional_observed_monotonic_ns
            or any(
                provisional.get(name) != expected
                for name, expected in fork_adjacent_projection.items()
            )
            or child_ready_intent["child_ready_sha256"]
            != birth.child_ready_sha256
            or join["child_ready_intent_ledger_row_sha256"]
            != birth.child_ready_intent_ledger_row_sha256
            or child_ready_intent["spawn_intent_sha256"]
            != birth.spawn_intent_sha256
            or child_ready_intent["provisional_record_sha256"]
            != birth.provisional_record_sha256
            or registration["ppid"] != birth.ppid
            or registration["pgid"] != birth.pgid
            or registration["sid"] != birth.sid
            or registration["registration_sha256"]
            != birth.watchdog_registration_sha256
            or registration["spawn_intent_sha256"]
            != birth.spawn_intent_sha256
            or registration["spawn_intent_ledger_row_sha256"]
            != birth.spawn_intent_ledger_row_sha256
            or registration["provisional_child_ledger_row_sha256"]
            != birth.provisional_child_ledger_row_sha256
            or registration_ack["watchdog_record_sha256"]
            != birth.watchdog_registration_ack_sha256
            or registration_ack["spawn_intent_sha256"]
            != birth.spawn_intent_sha256
            or registration_ack["provisional_child_ledger_row_sha256"]
            != birth.provisional_child_ledger_row_sha256
            or birth_commitment["birth_commitment_sha256"]
            != birth.birth_commitment_sha256
            or any(
                birth_commitment.get(name) != expected
                for name, expected in inventory_projection.items()
            )
            or any(
                birth_commitment.get(name) != expected
                for name, expected in fork_adjacent_projection.items()
            )
            or join["birth_ledger_row_sha256"]
            != birth.birth_ledger_row_sha256
            or birth_event["birth_record_sha256"]
            != birth.birth_commitment_sha256
            or any(
                birth_event.get(name) != expected
                for name, expected in inventory_projection.items()
            )
            or any(
                birth_event.get(name) != expected
                for name, expected in fork_adjacent_projection.items()
            )
            or birth_event["watch_birth_sha256"]
            != birth.watchdog_birth_sha256
            or birth_ack["watchdog_record_sha256"]
            != birth.watchdog_birth_ack_sha256
            or exec_release["birth_commitment_sha256"]
            != birth.birth_commitment_sha256
            or join["exec_release_ledger_row_sha256"]
            != birth.exec_release_ledger_row_sha256
            or _canonical_payload_bytes(wait4)
            != _canonical_payload_bytes(asdict(app_tombstone))
            or reaped_event["tombstone_record_sha256"]
            != tombstone.record_sha256
            or reaped_event["birth_record_sha256"]
            != birth.birth_commitment_sha256
            or reaped_event.get("native_runtime_attestation_sha256")
            != tombstone.native_runtime_attestation.record_sha256
            or reaped_event.get("native_runtime_scan_log_sha256")
            != tombstone.native_runtime_attestation.scan_log_sha256
            or reaped_event.get("native_closure_post_wait4_sha256")
            != tombstone.native_runtime_attestation.static_closure_post_wait4_sha256
            or reaped_ack["tombstone_record_sha256"]
            != tombstone.record_sha256
        ):
            raise RuntimeError("broker child audit projection differs")
        pre_exec_sample = birth_event.get("pre_exec_gated_child_sample")
        if (
            type(pre_exec_sample) is not dict
            or (pre_exec_sample.get("pid"), pre_exec_sample.get("start_abstime"))
            != (birth.pid, birth.start_abstime)
        ):
            raise RuntimeError("broker child gated sample join differs")
        retained.append(
            BrokerChildCpuReceipt(
                birth=birth,
                tombstone=tombstone,
                watchdog_closure_record_sha256=reaped_ack[
                    "watchdog_record_sha256"
                ],
                watchdog_exact_pid_closure_confirmed=True,
                identity_or_group_drift_observed=False,
            )
        )
    request_join_count = sum(
        1
        for join in child_audit_joins.values()
        if join["registration"]["request_id"] == receipt.request_id
    )
    if len(retained) != request_join_count:
        raise RuntimeError("broker request child-audit cardinality differs")
    return tuple(
        sorted(
            retained,
            key=lambda item: (
                item.birth.spawn_sequence,
                item.birth.spawn_nonce_sha256,
                item.birth.pid,
            ),
        )
    )


def _contract_lifecycle_receipt(
    *,
    raw_mapping: Mapping[str, Any],
    child_audit_joins: Mapping[str, Mapping[str, Any]],
    expected_phase: Literal["startup", "shutdown"],
) -> BrokerLifecycleReceiptEvidence:
    from app.services.tesseract_broker_protocol import (
        request_receipt_from_mapping,
    )

    canonical = _canonical_payload_bytes(dict(raw_mapping))
    receipt = request_receipt_from_mapping(
        json.loads(canonical.decode("utf-8", errors="strict"))
    )
    if receipt.logical_phase != expected_phase or receipt.terminal_kind != "end":
        raise RuntimeError("broker lifecycle receipt phase differs")
    return broker_lifecycle_receipt_evidence(
        logical_phase=expected_phase,
        canonical_receipt_json=canonical.decode("utf-8", errors="strict"),
        canonical_receipt_sha256=hashlib.sha256(canonical).hexdigest(),
        receipt_sha256=receipt.receipt_sha256,
        attempt_nonce_sha256=receipt.attempt_nonce_sha256,
        scope_sha256=receipt.scope_sha256,
        request_id=receipt.request_id,
        request_epoch=receipt.request_epoch,
        request_sequence=receipt.request_sequence,
        phase_deadline_monotonic_ns=receipt.phase_deadline_monotonic_ns,
        arm_issued_at_monotonic_ns=receipt.arm_issued_at_monotonic_ns,
        arm_consumed_at_monotonic_ns=receipt.arm_consumed_at_monotonic_ns,
        native_closure_sha256=receipt.native_closure_sha256,
        native_closure=json.loads(
            _canonical_payload_bytes(receipt.native_closure).decode("utf-8")
        ),
        guard_python=json.loads(
            _canonical_payload_bytes(receipt.guard_python).decode("utf-8")
        ),
        guard_python_path_custody=json.loads(
            _canonical_payload_bytes(receipt.guard_python_path_custody).decode(
                "utf-8"
            )
        ),
        guard_python_native_closure=json.loads(
            _canonical_payload_bytes(receipt.guard_python_native_closure).decode(
                "utf-8"
            )
        ),
        guard_python_module_tree_custody=json.loads(
            _canonical_payload_bytes(
                receipt.guard_python_module_tree_custody
            ).decode("utf-8")
        ),
        guard_wrapper_source_hex=receipt.guard_wrapper_source_hex,
        guard_wrapper_source_sha256=receipt.guard_wrapper_source_sha256,
        guard_wrapper_delivery_basis=receipt.guard_wrapper_delivery_basis,
        previous_receipt_sha256=receipt.previous_receipt_sha256,
        begin=_contract_quiescence_receipt(
            receipt=receipt, value=receipt.begin, edge="begin"
        ),
        end=_contract_quiescence_receipt(
            receipt=receipt, value=receipt.end, edge="end"
        ),
        children=_contract_child_receipts(
            receipt=receipt,
            child_audit_joins=child_audit_joins,
            resource_window=None,
        ),
    )


def _assemble_exact_request_boundary(
    *,
    attempt_id: str,
    source: SourceIdentity,
    raw: ProductionRawRequestObservation,
    boundary: _ExternalRequestCpuBoundary,
    child_audit_joins: Mapping[str, Mapping[str, Any]],
) -> RequestResourceBoundary:
    from app.services.tesseract_broker_protocol import (
        request_receipt_from_mapping,
    )

    resource_window = boundary.resource_window
    if resource_window is None:
        raise RuntimeError("controller resource window is absent")
    raw_mapping = raw.model_dump(mode="json")
    if (
        raw.attempt_id != attempt_id
        or raw.source != source
        or raw.request_id != boundary.request_id
        or raw.request_index != boundary.request_sequence
        or raw.request_epoch != boundary.request_epoch
        or boundary.raw_result.get("worker_result") != raw_mapping
        or boundary.raw_result.get("record_sha256")
        != boundary.frame_record_sha256s[5]
    ):
        raise RuntimeError("raw worker/controller result join differs")
    receipt = request_receipt_from_mapping(
        boundary.broker_request_receipt
    )
    receipt_mapping = asdict(receipt)
    if (
        receipt.receipt_sha256
        != boundary.end_blocked["broker_request_receipt_sha256"]
        or receipt.receipt_sha256 != raw.broker_request_receipt_sha256
        or receipt.request_id != boundary.request_id
        or receipt.request_epoch != boundary.request_epoch
        or receipt.request_sequence != boundary.request_sequence
        or receipt.attempt_nonce_sha256
        != boundary.begin_sample_record.attempt_nonce_sha256
        or receipt.scope_sha256 != boundary.begin_sample_record.scope_sha256
        or receipt.phase_deadline_monotonic_ns
        != boundary.arm["request_deadline_monotonic_ns"]
        or receipt.terminal_kind != "end"
        or receipt.logical_phase != "request"
        or receipt.request_binding is None
        or receipt.request_binding.record_sha256
        != raw.request_binding_record_sha256
        or receipt.request_binding.record_sha256
        != boundary.end_blocked["request_binding_record_sha256"]
        or receipt.binding_sha256 != boundary.arm["binding_sha256"]
        or receipt.binding_sha256
        != receipt.request_binding.binding_record_sha256
        or _canonical_payload_bytes(receipt_mapping)
        != _canonical_payload_bytes(boundary.broker_request_receipt)
    ):
        raise RuntimeError("broker request receipt/controller join differs")
    expected_binding = _production_request_binding(source)
    if (
        boundary.arm["binding"] != expected_binding
        or boundary.arm["binding_sha256"] != _canonical_sha256(expected_binding)
        or any(
            getattr(receipt.request_binding, name) != expected
            for name, expected in expected_binding.items()
            if name != "schema_id"
        )
    ):
        raise RuntimeError("broker request binding differs from source")
    request_binding = BrokerRequestBindingEvidence.model_validate(
        asdict(receipt.request_binding)
    )
    asgi_response_witness = AsgiResponseWitness.model_validate(
        boundary.end_blocked["asgi_response_witness"]
    )
    begin = _contract_quiescence_receipt(
        receipt=receipt, value=receipt.begin, edge="begin"
    )
    end = _contract_quiescence_receipt(
        receipt=receipt, value=receipt.end, edge="end"
    )
    children = _contract_child_receipts(
        receipt=receipt,
        child_audit_joins=child_audit_joins,
        resource_window=resource_window,
    )
    boundary_started = boundary.begin_sample_record.worker_sample.cpu.observed_monotonic_ns
    boundary_ended = boundary.end_sample_record.worker_sample.cpu.observed_monotonic_ns
    controller_rows = resource_window.rows
    boundary_rows = tuple(
        row
        for row in controller_rows
        if row.record.boundary_membership != "coverage_only"
    )
    if len(boundary_rows) < 2:
        raise RuntimeError("controller resource boundary rows are insufficient")
    boundary_intervals = tuple(
        (
            row.record.sweep_started_monotonic_ns,
            row.record.sweep_completed_monotonic_ns,
        )
        for row in boundary_rows
    )
    boundary_maximum_gap_ns = max(
        later_start - earlier_completed
        for (_, earlier_completed), (later_start, _) in zip(
            boundary_intervals,
            boundary_intervals[1:],
            strict=False,
        )
    )
    gated_samples = tuple(
        ControllerPreExecGatedChildSample.model_validate(item)
        for item in resource_window.pre_exec_gated_child_samples
    )
    sampled_identity_by_key = {
        (item.pid, item.start_abstime): SampledProcessIdentity(
            role=item.role,
            pid=item.pid,
            start_abstime=item.start_abstime,
            parent_pid=item.ppid,
            process_group_id=item.pgid,
            session_id=item.sid,
        )
        for row in boundary_rows
        for item in row.record.processes
    }
    for sample in gated_samples:
        sampled_identity_by_key[(sample.pid, sample.start_abstime)] = (
            SampledProcessIdentity(
                role="tesseract_child",
                pid=sample.pid,
                start_abstime=sample.start_abstime,
                parent_pid=sample.ppid,
                process_group_id=sample.pgid,
                session_id=sample.sid,
            )
        )
    sampled_identities = tuple(
        sampled_identity_by_key[key] for key in sorted(sampled_identity_by_key)
    )
    child_identity_keys = {
        (item.birth.pid, item.birth.start_abstime) for item in children
    }
    sampled_child_keys = {
        (item.pid, item.start_abstime)
        for item in sampled_identities
        if item.role == "tesseract_child"
    }
    if sampled_child_keys != child_identity_keys:
        raise RuntimeError("controller sampled child/birth set differs")
    worker_before = boundary.begin_sample_record.worker_sample.cpu
    worker_after = boundary.end_sample_record.worker_sample.cpu
    broker_before = boundary.begin_sample_record.broker_sample.cpu
    broker_after = boundary.end_sample_record.broker_sample.cpu
    deltas = (
        worker_after.user_cpu_ns - worker_before.user_cpu_ns,
        worker_after.system_cpu_ns - worker_before.system_cpu_ns,
        broker_after.user_cpu_ns - broker_before.user_cpu_ns,
        broker_after.system_cpu_ns - broker_before.system_cpu_ns,
        sum(item.tombstone.user_cpu_ns for item in children),
        sum(item.tombstone.system_cpu_ns for item in children),
    )
    if min(deltas) < 0:
        raise RuntimeError("exact request CPU counter regressed")
    frame_hashes = boundary.frame_record_sha256s
    exact = ExactBrokerRequestCpuEvidence(
        attempt_id=attempt_id,
        request_id=boundary.request_id,
        attempt_nonce_sha256=receipt.attempt_nonce_sha256,
        scope_sha256=receipt.scope_sha256,
        request_epoch=boundary.request_epoch,
        request_sequence=boundary.request_sequence,
        request_deadline_monotonic_ns=receipt.phase_deadline_monotonic_ns,
        arm_capability_sha256=receipt.arm_capability_sha256,
        arm_issued_at_monotonic_ns=receipt.arm_issued_at_monotonic_ns,
        arm_consumed_at_monotonic_ns=receipt.arm_consumed_at_monotonic_ns,
        binding_sha256=receipt.binding_sha256,
        request_binding=request_binding,
        asgi_response_witness=asgi_response_witness,
        asgi_response_witness_sha256=(
            boundary.end_blocked["asgi_response_witness_sha256"]
        ),
        thread_claim_count=receipt.thread_claim_count,
        thread_transfer_record_sha256s=tuple(
            item.record_sha256 for item in receipt.thread_transfers
        ),
        begin=begin,
        end=end,
        worker_before=worker_before,
        worker_after=worker_after,
        broker_before=broker_before,
        broker_after=broker_after,
        begin_post_sample_scratch_inventory=boundary.begin_scratch,
        end_post_sample_scratch_inventory=boundary.end_scratch,
        begin_external_sample=boundary.begin_sample_record,
        end_external_sample=boundary.end_sample_record,
        begin_external_sample_row_sha256=boundary.begin_sample_row_sha256,
        end_external_sample_row_sha256=boundary.end_sample_row_sha256,
        request_control_arm_record_sha256=frame_hashes[0],
        request_control_begin_blocked_record_sha256=frame_hashes[1],
        request_control_begin_release_record_sha256=frame_hashes[2],
        request_control_end_blocked_record_sha256=frame_hashes[3],
        request_control_receipt_release_record_sha256=frame_hashes[4],
        request_control_result_record_sha256=frame_hashes[5],
        request_control_result_ack_record_sha256=frame_hashes[6],
        request_control_transcript_row_sha256s=boundary.transcript_row_sha256s,
        begin_release_monotonic_ns=boundary.begin_release[
            "begin_release_monotonic_ns"
        ],
        receipt_release_monotonic_ns=boundary.receipt_release[
            "receipt_release_monotonic_ns"
        ],
        broker_request_receipt_sha256=receipt.receipt_sha256,
        pre_exec_gated_child_samples=gated_samples,
        children=children,
        worker_user_cpu_delta_ns=deltas[0],
        worker_system_cpu_delta_ns=deltas[1],
        broker_user_cpu_delta_ns=deltas[2],
        broker_system_cpu_delta_ns=deltas[3],
        tesseract_user_cpu_delta_ns=deltas[4],
        tesseract_system_cpu_delta_ns=deltas[5],
        total_cpu_delta_ns=sum(deltas),
        sampled_process_identities=sampled_identities,
        unmatched_sampled_process_identities=(),
    )
    boundary_started = worker_before.observed_monotonic_ns
    boundary_ended = worker_after.observed_monotonic_ns
    if (
        boundary_ended <= boundary_started
        or raw.client_post_started_monotonic_ns > boundary_started
        or raw.client_post_completed_monotonic_ns
        < exact.receipt_release_monotonic_ns
    ):
        raise RuntimeError("raw client-post/exact boundary chronology differs")
    host_cpu_count = os.cpu_count() or 1
    child_max_rss = max(
        (item.tombstone.maximum_resident_set_bytes for item in children),
        default=0,
    )
    root_begin_rss = (
        exact.begin_external_sample.worker_sample.rss_bytes
        + exact.begin_external_sample.broker_sample.rss_bytes
    )
    root_begin_threads = (
        exact.begin_external_sample.worker_sample.thread_count
        + exact.begin_external_sample.broker_sample.thread_count
    )
    root_begin_fds = (
        exact.begin_external_sample.worker_sample.file_descriptor_count
        + exact.begin_external_sample.broker_sample.file_descriptor_count
    )
    peak_process_count = max(
        max(row.record.aggregate.process_count for row in boundary_rows),
        2 + (1 if gated_samples else 0),
    )
    peak_rss_bytes = max(
        child_max_rss,
        *(row.record.aggregate.rss_bytes for row in boundary_rows),
        *(root_begin_rss + item.rss_bytes for item in gated_samples),
    )
    peak_thread_count = max(
        max(row.record.aggregate.thread_count for row in boundary_rows),
        0,
        *(root_begin_threads + item.thread_count for item in gated_samples),
    )
    peak_fd_count = max(
        max(
            row.record.aggregate.file_descriptor_count for row in boundary_rows
        ),
        0,
        *(root_begin_fds + item.file_descriptor_count for item in gated_samples),
    )
    return RequestResourceBoundary(
        boundary_started_monotonic_ns=boundary_started,
        boundary_ended_monotonic_ns=boundary_ended,
        self_user_cpu_delta_ns=0,
        self_system_cpu_delta_ns=0,
        reaped_child_user_cpu_delta_ns=0,
        reaped_child_system_cpu_delta_ns=0,
        live_descendant_user_cpu_delta_ns=0,
        live_descendant_system_cpu_delta_ns=0,
        live_descendant_process_count=0,
        total_cpu_delta_ns=exact.total_cpu_delta_ns,
        host_logical_cpu_count=host_cpu_count,
        wall_cpu_capacity_ns=(boundary_ended - boundary_started)
        * host_cpu_count,
        descendant_peak_process_count=peak_process_count,
        descendant_peak_rss_bytes=max(1, peak_rss_bytes),
        process_tree_peak_thread_count=peak_thread_count,
        process_tree_peak_file_descriptor_count=peak_fd_count,
        exact_broker_cpu=exact,
        controller_resource_sample_rows=resource_window.rows,
        cpu_accounting_basis=(
            "fork-denied-worker-broker-self-plus-exact-wait4-v2"
        ),
        sampled_concurrently=True,
        descendant_sample_count=len(boundary_rows),
        descendant_first_sample_monotonic_ns=boundary_intervals[0][0],
        descendant_last_sample_monotonic_ns=boundary_intervals[-1][1],
        descendant_maximum_gap_ns=boundary_maximum_gap_ns,
        descendant_target_interval_ns=resource_window.target_interval_ns,
        descendant_edge_tolerance_ns=resource_window.edge_tolerance_ns,
        request_boundary_covered=bool(
            boundary_intervals[0][0]
            <= boundary_started + resource_window.edge_tolerance_ns
            and boundary_intervals[-1][1]
            >= boundary_ended - resource_window.edge_tolerance_ns
            and boundary_maximum_gap_ns <= PEAK_SAMPLE_MAXIMUM_GAP_NS
        ),
        sampled_late=False,
        cumulative_contamination_detected=False,
    )


def _assemble_production_worker_envelope(
    *,
    attempt_id: str,
    mode: RunMode,
    source: SourceIdentity,
    raw: ProductionRawWorkerEnvelope,
    boundaries: tuple[_ExternalRequestCpuBoundary, ...],
    request_control_readiness: RequestControlReadinessEvidence,
    terminal_request_control_transcript: TerminalRequestControlTranscriptEvidence,
    immutable_input_custody: ImmutableRuntimeInputCustodyEvidence,
    child_watch_log_path: Path,
    request_resource_log_sha256: str,
    request_resource_log_row_count: int,
    request_resource_log_size_bytes: int,
) -> WorkerMeasurementEnvelope:
    if (
        raw.mode != mode
        or raw.source != source
        or len(raw.requests) != len(boundaries)
        or raw.request_control_completed_count != len(boundaries)
        or any(item.attempt_id != attempt_id for item in raw.requests)
        or (
            mode is RunMode.PREDECESSOR
            and any(item.converter_sha256 is not None for item in raw.requests)
        )
        or (
            mode is RunMode.ENABLED
            and any(item.converter_sha256 is None for item in raw.requests)
        )
    ):
        raise RuntimeError("raw worker/controller envelope join differs")
    child_audit = _retained_child_audit_joins(child_watch_log_path)
    startup_broker_receipt = _contract_lifecycle_receipt(
        raw_mapping=raw.startup_broker_receipt,
        child_audit_joins=child_audit,
        expected_phase="startup",
    )
    shutdown_broker_receipt = _contract_lifecycle_receipt(
        raw_mapping=raw.shutdown_broker_receipt,
        child_audit_joins=child_audit,
        expected_phase="shutdown",
    )
    requests: list[RequestObservation] = []
    request_peaks: list[ResourceSample] = []
    request_rss: list[int] = []
    for raw_request, boundary in zip(raw.requests, boundaries, strict=True):
        resource_boundary = _assemble_exact_request_boundary(
            attempt_id=attempt_id,
            source=source,
            raw=raw_request,
            boundary=boundary,
            child_audit_joins=child_audit,
        )
        window = boundary.resource_window
        if window is None:
            raise RuntimeError("request resource window disappeared")
        peak = window.peak.model_copy(
            update={
                "rss_bytes": resource_boundary.descendant_peak_rss_bytes,
                "process_count": resource_boundary.descendant_peak_process_count,
                "thread_count": resource_boundary.process_tree_peak_thread_count,
                "file_descriptor_count": (
                    resource_boundary.process_tree_peak_file_descriptor_count
                ),
            }
        )
        request_peaks.append(peak)
        request_rss.append(peak.rss_bytes)
        requests.append(
            RequestObservation(
                request_index=raw_request.request_index,
                latency_ns=(
                    resource_boundary.boundary_ended_monotonic_ns
                    - resource_boundary.boundary_started_monotonic_ns
                ),
                status=AttemptStatus.SUCCESS,
                output=raw_request.output,
                failure=None,
                resource_boundary=resource_boundary,
            )
        )
    request_peak = max(request_peaks, key=lambda item: item.rss_bytes)
    resources = LifecycleResourceEvidence(
        cold_initialization=raw.cold_resource,
        prewarmed_idle=raw.prewarmed_idle_resource,
        request_peak=request_peak,
        repeated_request=raw.repeated_request_resource,
        shutdown=raw.shutdown_resource,
    )
    resource_rows = tuple(
        row
        for boundary in boundaries
        for row in (
            boundary.resource_window.rows
            if boundary.resource_window is not None
            else ()
        )
    )
    resource_log_bytes = b"".join(
        _canonical_payload_bytes(row.model_dump(mode="json")) + b"\n"
        for row in resource_rows
    )
    if (
        not resource_rows
        or tuple(row.row_sequence for row in resource_rows)
        != tuple(range(1, len(resource_rows) + 1))
        or len(resource_rows) != request_resource_log_row_count
        or len(resource_log_bytes) != request_resource_log_size_bytes
        or hashlib.sha256(resource_log_bytes).hexdigest()
        != request_resource_log_sha256
    ):
        raise RuntimeError("controller resource whole-log custody differs")
    child_watch_raw, child_watch_stat = _read_private_payload_with_identity(
        child_watch_log_path,
        maximum_bytes=4_194_304,
    )
    child_watch_bundle = _read_child_watch_bundle(child_watch_log_path)
    terminal_child_watch_log = terminal_child_watch_log_evidence(
        child_watch_raw,
        file_device=child_watch_stat.st_dev,
        file_inode=child_watch_stat.st_ino,
        file_uid=child_watch_stat.st_uid,
        record_blob_root=child_watch_bundle["record_blob_root"],
        record_blobs=child_watch_bundle["record_blobs"],
        record_blob_identities=child_watch_bundle["record_blob_identities"],
        event_blob_root=child_watch_bundle["event_blob_root"],
        event_blobs=child_watch_bundle["event_blobs"],
        event_blob_identities=child_watch_bundle["event_blob_identities"],
    )
    require_terminal_request_control_transcript(
        terminal_request_control_transcript,
        request_control_readiness,
        tuple(
            request.resource_boundary.exact_broker_cpu
            for request in requests
        ),
        request_sources=tuple(request.source for request in raw.requests),
        request_outputs=tuple(request.output for request in raw.requests),
        receipt_blob_root=child_watch_log_path.parent,
    )
    return WorkerMeasurementEnvelope(
        schema_id="phase-latency-prewarm-worker-envelope-v1",
        case_id=raw.case_id,
        mode=mode,
        source=source,
        startup_duration_ns=raw.startup_duration_ns,
        shutdown_duration_ns=raw.shutdown_duration_ns,
        application_identity_validated=raw.application_identity_validated,
        dependency_identity_validated=raw.dependency_identity_validated,
        parser_runtime_identity_validated=(
            raw.parser_runtime_identity_validated
        ),
        runtime_artifact_identity_validated=(
            raw.runtime_artifact_identity_validated
        ),
        configuration_identity_validated=raw.configuration_identity_validated,
        converter_identity_validated=raw.converter_identity_validated,
        ready_after_identity_validation=raw.ready_after_identity_validation,
        prewarm_completed=raw.prewarm_completed,
        requests=tuple(requests),
        resources=resources,
        state_retention_detected=raw.state_retention_detected,
        production_asgi_lifespan_exercised=True,
        network_isolation_validated=raw.network_isolation_validated,
        runtime_before_requests_sha256=raw.runtime_before_requests_sha256,
        runtime_after_requests_sha256=raw.runtime_after_requests_sha256,
        runtime_after_shutdown_sha256=raw.runtime_after_shutdown_sha256,
        runtime_artifact_before_requests=raw.runtime_artifact_before_requests,
        runtime_artifact_after_shutdown=raw.runtime_artifact_after_shutdown,
        fork_denial_evidence=raw.fork_denial_evidence,
        request_control_readiness=request_control_readiness,
        terminal_request_control_transcript=(
            terminal_request_control_transcript
        ),
        immutable_runtime_input_custody=immutable_input_custody,
        startup_broker_receipt=startup_broker_receipt,
        shutdown_broker_receipt=shutdown_broker_receipt,
        terminal_child_watch_log=terminal_child_watch_log,
        oom_observed=False,
        unbounded_rss_growth_observed=_unbounded_rss_growth(request_rss),
        concurrent_descendant_sampling_validated=True,
        controller_resource_sample_log_sha256=(
            request_resource_log_sha256
        ),
        controller_resource_sample_log_row_count=(
            request_resource_log_row_count
        ),
        controller_resource_sample_log_size_bytes=(
            request_resource_log_size_bytes
        ),
        hosted_calls=0,
        egress_bytes=0,
    )


def _assemble_cross_input_observations(
    *,
    attempt_id: str,
    raw: CrossInputRawWorkerEnvelope,
    boundaries: tuple[_ExternalRequestCpuBoundary, ...],
    child_watch_log_path: Path,
    request_resource_log_sha256: str,
    request_resource_log_row_count: int,
    request_resource_log_size_bytes: int,
) -> tuple[CrossInputRequestObservation, ...]:
    expected_sources = (raw.source_a, raw.source_b, raw.source_a)
    if (
        len(boundaries) != 3
        or len(raw.requests) != 3
        or raw.request_control_completed_count != 3
        or any(item.attempt_id != attempt_id for item in raw.requests)
        or tuple(item.source for item in raw.requests) != expected_sources
        or any(item.converter_sha256 is None for item in raw.requests)
    ):
        raise RuntimeError("raw cross-input/controller envelope join differs")
    child_audit = _retained_child_audit_joins(child_watch_log_path)
    observations: list[CrossInputRequestObservation] = []
    for index, (raw_request, boundary, source) in enumerate(
        zip(raw.requests, boundaries, expected_sources, strict=True), start=1
    ):
        resource_boundary = _assemble_exact_request_boundary(
            attempt_id=attempt_id,
            source=source,
            raw=raw_request,
            boundary=boundary,
            child_audit_joins=child_audit,
        )
        converter_sha256 = raw_request.converter_sha256
        if converter_sha256 is None:
            raise RuntimeError("raw cross-input converter identity is absent")
        observations.append(
            CrossInputRequestObservation(
                sequence_index=index,
                source=source,
                latency_ns=(
                    resource_boundary.boundary_ended_monotonic_ns
                    - resource_boundary.boundary_started_monotonic_ns
                ),
                output=raw_request.output,
                runtime_snapshot_sha256=raw_request.runtime_snapshot_sha256,
                converter_sha256=converter_sha256,
                resource_boundary=resource_boundary,
            )
        )
    resource_rows = tuple(
        row
        for boundary in boundaries
        for row in (
            boundary.resource_window.rows
            if boundary.resource_window is not None
            else ()
        )
    )
    resource_bytes = b"".join(
        _canonical_payload_bytes(row.model_dump(mode="json")) + b"\n"
        for row in resource_rows
    )
    if (
        not resource_rows
        or tuple(row.row_sequence for row in resource_rows)
        != tuple(range(1, len(resource_rows) + 1))
        or len(resource_rows) != request_resource_log_row_count
        or len(resource_bytes) != request_resource_log_size_bytes
        or hashlib.sha256(resource_bytes).hexdigest()
        != request_resource_log_sha256
    ):
        raise RuntimeError("cross-input controller resource log differs")
    return tuple(observations)


class _RequestControlController:
    """Controller half of the external stable-edge request/CPU protocol."""

    _READY_KEYS = {
        "schema_id",
        "attempt_id",
        "attempt_nonce_sha256",
        "scope_sha256",
        "worker",
        "broker",
        "expected_request_count",
        "framework_thread_baseline",
        "ready_at_monotonic_ns",
        "previous_record_sha256",
        "record_sha256",
    }
    _COMMON_REQUEST_KEYS = {
        "attempt_id",
        "attempt_nonce_sha256",
        "scope_sha256",
        "request_id",
        "request_epoch",
        "request_sequence",
        "worker",
        "broker",
        "request_deadline_monotonic_ns",
        "previous_record_sha256",
    }

    def __init__(
        self,
        *,
        sock: socket.socket,
        attempt_id: str,
        attempt_nonce_sha256: str,
        scope_sha256: str,
        absolute_deadline_monotonic_ns: int,
        expected_request_count: int,
        worker_identity: Mapping[str, int],
        broker_identity: Mapping[str, int],
        request_root_fd: int,
        transcript_path: Path,
        cpu_sample_path: Path,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        from app.services.tesseract_broker_protocol import FramedChannel

        if expected_request_count <= 0 or request_root_fd < 0:
            raise ValueError("request-control bounds differ")
        self.socket = sock
        self.channel = FramedChannel(sock)
        self.channel.set_absolute_deadline_ns(absolute_deadline_monotonic_ns)
        self.attempt_id = attempt_id
        self.attempt_nonce_sha256 = attempt_nonce_sha256
        self.scope_sha256 = scope_sha256
        self.absolute_deadline_monotonic_ns = absolute_deadline_monotonic_ns
        self._monotonic_ns = monotonic_ns
        self.expected_request_count = expected_request_count
        self.worker_identity = dict(worker_identity)
        self.broker_identity = dict(broker_identity)
        self.request_root_fd = request_root_fd
        self.transcript = _DurableHashChainedLog(
            transcript_path,
            schema_id="phase-latency-request-control-transcript-row-v1",
            maximum_bytes=REQUEST_CONTROL_TRANSCRIPT_MAXIMUM_BYTES,
        )
        self.cpu_samples = _DurableHashChainedLog(
            cpu_sample_path,
            schema_id="phase-latency-external-cpu-sample-row-v1",
            maximum_bytes=REQUEST_CPU_SAMPLE_LOG_MAXIMUM_BYTES,
        )
        self.previous_record_sha256 = "0" * 64
        self.last_transcript_row_sha256 = "0" * 64
        self.ready_record: dict[str, Any] | None = None
        self.framework_thread_baseline: FrameworkThreadBaseline | None = None
        self.broker_pre_release_ready_sha256: str | None = None
        self.readiness_evidence: RequestControlReadinessEvidence | None = None
        self.boundaries: list[_ExternalRequestCpuBoundary] = []
        self.request_receipt_blob_records: list[dict[str, Any]] = []
        self._active_request_deadline_monotonic_ns: int | None = None
        self._active_request_common: dict[str, Any] | None = None
        self._send_terminalized = False
        self._channel_operation_lock = threading.Lock()
        self.closed = False

    def bind_broker_pre_release_ready(self, record_sha256: object) -> None:
        if self.broker_pre_release_ready_sha256 is not None:
            raise RuntimeError("broker pre-release READY was rebound")
        if (
            type(record_sha256) is not str
            or re.fullmatch(r"[0-9a-f]{64}", record_sha256) is None
        ):
            raise RuntimeError("broker pre-release READY identity differs")
        self.broker_pre_release_ready_sha256 = record_sha256

    @staticmethod
    def _self_hashed(fields: Mapping[str, Any]) -> dict[str, Any]:
        value = dict(fields)
        if "record_sha256" in value:
            raise ValueError("request-control record digest is derived")
        return {**value, "record_sha256": _canonical_sha256(value)}

    @staticmethod
    def _require_self_hashed(
        payload: object, *, exact_keys: set[str], label: str
    ) -> dict[str, Any]:
        if type(payload) is not dict or set(payload) != exact_keys:
            raise RuntimeError(f"{label} fields differ")
        value = dict(payload)
        digest = value.pop("record_sha256")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or digest != _canonical_sha256(value)
        ):
            raise RuntimeError(f"{label} digest differs")
        value["record_sha256"] = digest
        return value

    def _retain_frame(
        self,
        *,
        direction: Literal["controller_to_worker", "worker_to_controller"],
        kind: str,
        frame_sha256: str,
        payload: Mapping[str, Any],
    ) -> str:
        row_sha256 = self.transcript.append(
            kind=kind,
            record={
                "direction": direction,
                "frame_sha256": frame_sha256,
                "payload": dict(payload),
            },
        )
        self.last_transcript_row_sha256 = row_sha256
        return row_sha256

    def _preview_empty_frame_sha256(
        self, kind: str, payload: Mapping[str, Any]
    ) -> str:
        """Derive the exact next wire digest without touching the socket."""

        from app.services.tesseract_broker_protocol import (
            BROKER_PROTOCOL_SCHEMA,
            MAX_HEADER_BYTES,
            canonical_json_bytes,
        )

        if not isinstance(kind, str) or not kind or len(kind) > 64:
            raise ValueError("request-control message kind differs")
        envelope = {
            "schema_id": BROKER_PROTOCOL_SCHEMA,
            "sequence": self.channel.next_sequence,
            "previous_sha256": self.channel.previous_sha256,
            "kind": kind,
            "body_bytes": 0,
            "body_sha256": hashlib.sha256(b"").hexdigest(),
            "payload": dict(payload),
        }
        digest = hashlib.sha256(canonical_json_bytes(envelope)).hexdigest()
        if (
            len(
                canonical_json_bytes(
                    {**envelope, "frame_sha256": digest}
                )
            )
            > MAX_HEADER_BYTES
        ):
            raise ValueError("request-control frame header exceeds its bound")
        return digest

    def _effective_send_deadline_monotonic_ns(self) -> int:
        return (
            self._active_request_deadline_monotonic_ns
            or self.absolute_deadline_monotonic_ns
        )

    def _terminalize_send(
        self,
        *,
        kind: str,
        frame_sha256: str,
        payload: Mapping[str, Any],
        failure_code: Literal[
            "deadline_expired_before_authorization",
            "deadline_expired_after_authorization",
            "deadline_expired_during_send",
            "authorized_send_failed",
            "authorized_frame_digest_mismatch",
            "send_completion_retained_after_deadline",
        ],
        authorization_row_sha256: str | None,
        send_completion_row_sha256: str | None = None,
    ) -> None:
        if self._send_terminalized:
            return
        self._send_terminalized = True
        # Closing first prevents a peer from remaining blocked on a partial
        # frame while the terminal row is committed.  The authorization row,
        # when present, was already fsynced before any socket operation.
        self.channel.close()
        row_sha256 = self.transcript.append(
            kind="request_control_send_terminal",
            record={
                "attempt_id": self.attempt_id,
                "attempt_nonce_sha256": self.attempt_nonce_sha256,
                "scope_sha256": self.scope_sha256,
                "message_kind": kind,
                "frame_sha256": frame_sha256,
                "payload": dict(payload),
                "payload_record_sha256": payload.get("record_sha256"),
                "authorization_row_sha256": authorization_row_sha256,
                "send_completion_row_sha256": send_completion_row_sha256,
                "deadline_monotonic_ns": (
                    self._effective_send_deadline_monotonic_ns()
                ),
                "failure_code": failure_code,
                "observed_monotonic_ns": max(1, self._monotonic_ns()),
            },
        )
        self.last_transcript_row_sha256 = row_sha256

    def _retain_send_completed(
        self,
        *,
        kind: str,
        frame_sha256: str,
        payload: Mapping[str, Any],
        authorization_row_sha256: str,
        deadline_monotonic_ns: int,
        send_completed_monotonic_ns: int,
    ) -> str:
        return self.transcript.append(
            kind="request_control_send_completed",
            record={
                "direction": "controller_to_worker",
                "authorization_row_sha256": authorization_row_sha256,
                "message_kind": kind,
                "frame_sha256": frame_sha256,
                "payload_record_sha256": payload["record_sha256"],
                "deadline_monotonic_ns": deadline_monotonic_ns,
                "send_completed_monotonic_ns": send_completed_monotonic_ns,
            },
        )

    def retain_terminal_failure(
        self,
        *,
        failure_code: Literal[
            "peer_aborted_request",
            "peer_protocol_or_eof_failure",
            "controller_custody_failure",
        ],
        stage: Literal["ready", "request", "close"],
        broker_request_receipt_sha256: str | None = None,
        failure_reason_sha256: str | None = None,
    ) -> None:
        """Close the capability, then durably classify a non-send failure."""

        with self._channel_operation_lock:
            if self._send_terminalized or self.closed:
                return
            self._send_terminalized = True
            self.channel.close()
            common = self._active_request_common
            prior_row_sha256 = self.transcript.head_sha256
            row_sha256 = self.transcript.append(
                kind="request_control_terminal_failure",
                record={
                    "attempt_id": self.attempt_id,
                    "attempt_nonce_sha256": self.attempt_nonce_sha256,
                    "scope_sha256": self.scope_sha256,
                    "stage": stage,
                    "failure_code": failure_code,
                    "broker_request_receipt_sha256": (
                        broker_request_receipt_sha256
                    ),
                    "failure_reason_sha256": failure_reason_sha256,
                    "request_id": (
                        common.get("request_id") if common is not None else None
                    ),
                    "request_epoch": (
                        common.get("request_epoch") if common is not None else None
                    ),
                    "request_sequence": (
                        common.get("request_sequence")
                        if common is not None
                        else None
                    ),
                    "request_deadline_monotonic_ns": (
                        common.get("request_deadline_monotonic_ns")
                        if common is not None
                        else None
                    ),
                    "last_payload_record_sha256": (
                        self.previous_record_sha256
                    ),
                    "last_wire_frame_sha256": self.channel.previous_sha256,
                    "last_transcript_row_sha256": prior_row_sha256,
                    "observed_monotonic_ns": max(1, self._monotonic_ns()),
                },
            )
            self.last_transcript_row_sha256 = row_sha256

    def _activate_request_deadline(self, deadline_monotonic_ns: int) -> None:
        if self._active_request_deadline_monotonic_ns is not None:
            raise RuntimeError("request-control deadline was already active")
        if (
            isinstance(deadline_monotonic_ns, bool)
            or not isinstance(deadline_monotonic_ns, int)
            or self._monotonic_ns() >= deadline_monotonic_ns
            or deadline_monotonic_ns > self.absolute_deadline_monotonic_ns
        ):
            raise TimeoutError("request-control request deadline elapsed")
        self._active_request_deadline_monotonic_ns = deadline_monotonic_ns
        self.channel.set_absolute_deadline_ns(deadline_monotonic_ns)

    def _complete_request_deadline(self, deadline_monotonic_ns: int) -> None:
        if self._active_request_deadline_monotonic_ns != deadline_monotonic_ns:
            raise RuntimeError("request-control deadline completion differs")
        self._active_request_deadline_monotonic_ns = None
        self.channel.set_absolute_deadline_ns(
            self.absolute_deadline_monotonic_ns
        )

    def _send(self, kind: str, fields: Mapping[str, Any]) -> dict[str, Any]:
        with self._channel_operation_lock:
            if self._send_terminalized or self.closed:
                raise RuntimeError("request-control send authority is terminal")
            payload = self._self_hashed(fields)
            frame_sha256 = self._preview_empty_frame_sha256(kind, payload)
            deadline = self._effective_send_deadline_monotonic_ns()
            if self._monotonic_ns() >= deadline:
                self._terminalize_send(
                    kind=kind,
                    frame_sha256=frame_sha256,
                    payload=payload,
                    failure_code="deadline_expired_before_authorization",
                    authorization_row_sha256=None,
                )
                raise TimeoutError("request-control send deadline elapsed")
            try:
                authorization_row_sha256 = self._retain_frame(
                    direction="controller_to_worker",
                    kind=kind,
                    frame_sha256=frame_sha256,
                    payload=payload,
                )
            except BaseException:
                self._send_terminalized = True
                self.channel.close()
                raise
            if self._monotonic_ns() >= deadline:
                self._terminalize_send(
                    kind=kind,
                    frame_sha256=frame_sha256,
                    payload=payload,
                    failure_code="deadline_expired_after_authorization",
                    authorization_row_sha256=authorization_row_sha256,
                )
                raise TimeoutError(
                    "request-control send deadline elapsed after authorization"
                )
            try:
                observed_frame_sha256 = self.channel.send(kind, payload, b"")
            except BaseException:
                self._terminalize_send(
                    kind=kind,
                    frame_sha256=frame_sha256,
                    payload=payload,
                    failure_code="authorized_send_failed",
                    authorization_row_sha256=authorization_row_sha256,
                )
                raise
            if observed_frame_sha256 != frame_sha256:
                self._terminalize_send(
                    kind=kind,
                    frame_sha256=frame_sha256,
                    payload=payload,
                    failure_code="authorized_frame_digest_mismatch",
                    authorization_row_sha256=authorization_row_sha256,
                )
                raise RuntimeError("request-control authorized frame differs")
            send_completed_monotonic_ns = self._monotonic_ns()
            if send_completed_monotonic_ns >= deadline:
                self._terminalize_send(
                    kind=kind,
                    frame_sha256=frame_sha256,
                    payload=payload,
                    failure_code="deadline_expired_during_send",
                    authorization_row_sha256=authorization_row_sha256,
                )
                raise TimeoutError("request-control send completed after deadline")
            try:
                send_completion_row_sha256 = self._retain_send_completed(
                    kind=kind,
                    frame_sha256=frame_sha256,
                    payload=payload,
                    authorization_row_sha256=authorization_row_sha256,
                    deadline_monotonic_ns=deadline,
                    send_completed_monotonic_ns=send_completed_monotonic_ns,
                )
            except BaseException:
                self._send_terminalized = True
                self.channel.close()
                raise
            if self._monotonic_ns() >= deadline:
                self._terminalize_send(
                    kind=kind,
                    frame_sha256=frame_sha256,
                    payload=payload,
                    failure_code=(
                        "send_completion_retained_after_deadline"
                    ),
                    authorization_row_sha256=authorization_row_sha256,
                    send_completion_row_sha256=(
                        send_completion_row_sha256
                    ),
                )
                raise TimeoutError(
                    "request-control send completion exceeded deadline"
                )
            self.previous_record_sha256 = str(payload["record_sha256"])
            return payload

    def _receive(
        self, *, kind: str, exact_keys: set[str]
    ) -> tuple[dict[str, Any], str]:
        with self._channel_operation_lock:
            _kind, payload, body = self.channel.receive(expected_kind=kind)
            if body:
                raise RuntimeError("request-control frame body must be empty")
            value = self._require_self_hashed(
                payload, exact_keys=exact_keys, label=kind
            )
            if (
                value.get("previous_record_sha256")
                != self.previous_record_sha256
            ):
                raise RuntimeError("request-control payload chain differs")
            durable_row_sha256 = self._retain_frame(
                direction="worker_to_controller",
                kind=kind,
                frame_sha256=self.channel.previous_sha256,
                payload=value,
            )
            self.previous_record_sha256 = str(value["record_sha256"])
            return value, durable_row_sha256

    def _receive_request_receipt_blob(
        self,
        *,
        manifest_mapping: Mapping[str, Any],
        request_id: str,
        request_epoch: int,
        request_sequence: int,
        deadline_monotonic_ns: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Stream one manifested receipt to an O_EXCL file before release."""

        from app.services.tesseract_broker_protocol import (
            MAX_REQUEST_RECEIPT_BYTES,
            request_receipt_chunk_commitment_from_mapping,
            request_receipt_from_blob,
            request_receipt_manifest_from_mapping,
        )

        try:
            manifest = request_receipt_manifest_from_mapping(manifest_mapping)
        except Exception as error:
            raise RuntimeError("request-control receipt manifest differs") from error
        if (
            manifest.request_id != request_id
            or manifest.request_epoch != request_epoch
            or manifest.request_sequence != request_sequence
            or manifest.logical_phase != "request"
            or manifest.receipt_blob_bytes > MAX_REQUEST_RECEIPT_BYTES
            or self._monotonic_ns() >= deadline_monotonic_ns
        ):
            raise RuntimeError("request-control receipt manifest authority differs")

        path = self.transcript.path.with_name(
            f"{self.attempt_id}-request-{request_sequence:04d}-broker-receipt.json"
        )
        parent = _ensure_private_directory(path.parent)
        if path.parent.resolve(strict=True) != parent or path.exists():
            raise FileExistsError("request-control receipt blob path existed")
        descriptor = -1
        observed: os.stat_result | None = None
        try:
            with _blocked_controller_termination_signals():
                descriptor = os.open(
                    path,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
                parent_descriptor = os.open(
                    parent,
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                )
                try:
                    os.fsync(parent_descriptor)
                finally:
                    os.close(parent_descriptor)

            retained_bytes = 0
            previous_commitment_sha256 = "0" * 64
            chunk_frame_sha256s: list[str] = []
            chunk_transcript_row_sha256s: list[str] = []
            for expected_index in range(1, manifest.chunk_count + 1):
                if self._monotonic_ns() >= deadline_monotonic_ns:
                    raise TimeoutError(
                        "request-control receipt chunk deadline elapsed"
                    )
                with self._channel_operation_lock:
                    _kind, payload, body = self.channel.receive(
                        expected_kind="request_control_receipt_chunk"
                    )
                    frame_sha256 = self.channel.previous_sha256
                    if type(payload) is not dict or set(payload) != {
                        "manifest_sha256",
                        "chunk_commitment",
                    }:
                        raise RuntimeError(
                            "request-control receipt chunk payload differs"
                        )
                    try:
                        commitment = (
                            request_receipt_chunk_commitment_from_mapping(
                                payload["chunk_commitment"]
                            )
                        )
                    except Exception as error:
                        raise RuntimeError(
                            "request-control receipt chunk commitment differs"
                        ) from error
                    if (
                        payload["manifest_sha256"] != manifest.record_sha256
                        or commitment.chunk_index != expected_index
                        or commitment.chunk_offset != retained_bytes
                        or commitment.receipt_sha256 != manifest.receipt_sha256
                        or commitment.receipt_blob_sha256
                        != manifest.receipt_blob_sha256
                        or commitment.previous_chunk_commitment_sha256
                        != previous_commitment_sha256
                        or commitment.body_bytes != len(body)
                        or hashlib.sha256(body).hexdigest()
                        != commitment.body_sha256
                        or retained_bytes + len(body)
                        > manifest.receipt_blob_bytes
                    ):
                        raise RuntimeError(
                            "request-control receipt chunk chain differs"
                        )
                    with _blocked_controller_termination_signals():
                        written = 0
                        while written < len(body):
                            count = os.write(descriptor, body[written:])
                            if count <= 0:
                                raise OSError(
                                    "request-control receipt write did not advance"
                                )
                            written += count
                    retained_row_sha256 = self.transcript.append(
                        kind="request_control_receipt_chunk",
                        record={
                            "direction": "worker_to_controller",
                            "frame_sha256": frame_sha256,
                            "payload": payload,
                            "body_bytes": len(body),
                            "body_sha256": hashlib.sha256(body).hexdigest(),
                        },
                    )
                    if (
                        self.transcript.rows[-1]["retained_monotonic_ns"]
                        >= deadline_monotonic_ns
                        or self._monotonic_ns() >= deadline_monotonic_ns
                    ):
                        raise TimeoutError(
                            "request-control receipt chunk retention exceeded deadline"
                        )
                retained_bytes += len(body)
                previous_commitment_sha256 = commitment.commitment_sha256
                chunk_frame_sha256s.append(frame_sha256)
                chunk_transcript_row_sha256s.append(retained_row_sha256)

            if (
                retained_bytes != manifest.receipt_blob_bytes
                or previous_commitment_sha256
                != manifest.terminal_chunk_commitment_sha256
            ):
                raise RuntimeError("request-control receipt terminal chunk differs")
            with _blocked_controller_termination_signals():
                os.fsync(descriptor)
                observed = os.fstat(descriptor)
            if (
                not stat.S_ISREG(observed.st_mode)
                or stat.S_IMODE(observed.st_mode) != 0o600
                or observed.st_uid != os.geteuid()
                or observed.st_nlink != 1
                or observed.st_size != manifest.receipt_blob_bytes
            ):
                raise RuntimeError("request-control receipt file custody differs")
        finally:
            if descriptor >= 0:
                os.close(descriptor)

        if observed is None or self._monotonic_ns() >= deadline_monotonic_ns:
            raise TimeoutError("request-control receipt retention deadline elapsed")
        retained_blob, reread = _read_private_payload_with_identity(
            path,
            maximum_bytes=MAX_REQUEST_RECEIPT_BYTES,
        )
        try:
            receipt = request_receipt_from_blob(manifest, retained_blob)
        except Exception as error:
            raise RuntimeError(
                "request-control receipt frozen parse differs"
            ) from error
        if (
            _canonical_payload_bytes(asdict(receipt)) != retained_blob
            or self._monotonic_ns() >= deadline_monotonic_ns
            or any(
                getattr(reread, name) != getattr(observed, name)
                for name in (
                    "st_dev",
                    "st_ino",
                    "st_mode",
                    "st_uid",
                    "st_nlink",
                    "st_size",
                    "st_mtime_ns",
                )
            )
        ):
            raise RuntimeError("request-control receipt retained bytes differ")
        blob_record: dict[str, Any] = {
            "schema_id": "phase-latency-request-control-receipt-blob-v1",
            "attempt_id": self.attempt_id,
            "request_id": request_id,
            "request_epoch": request_epoch,
            "request_sequence": request_sequence,
            "relative_path": path.name,
            "manifest_record_sha256": manifest.record_sha256,
            "receipt_sha256": manifest.receipt_sha256,
            "receipt_blob_sha256": manifest.receipt_blob_sha256,
            "receipt_blob_bytes": manifest.receipt_blob_bytes,
            "chunk_count": manifest.chunk_count,
            "terminal_chunk_commitment_sha256": (
                manifest.terminal_chunk_commitment_sha256
            ),
            "chunk_frame_sha256s": chunk_frame_sha256s,
            "chunk_transcript_row_sha256s": chunk_transcript_row_sha256s,
            "file_device": reread.st_dev,
            "file_inode": reread.st_ino,
            "file_mode": stat.S_IMODE(reread.st_mode),
            "file_uid": reread.st_uid,
            "file_nlink": reread.st_nlink,
            "o_excl_created": True,
            "fsynced_before_close": True,
            "reopened_no_follow_after_fsync": True,
        }
        blob_record["record_sha256"] = _canonical_sha256(blob_record)
        blob_row_sha256 = self.transcript.append(
            kind="request_control_receipt_blob_retained",
            record=blob_record,
        )
        if (
            self.transcript.rows[-1]["retained_monotonic_ns"]
            >= deadline_monotonic_ns
            or self._monotonic_ns() >= deadline_monotonic_ns
        ):
            raise TimeoutError(
                "request-control receipt descriptor retention exceeded deadline"
            )
        blob_record["retained_transcript_row_sha256"] = blob_row_sha256
        self.request_receipt_blob_records.append(blob_record)
        return asdict(receipt), blob_record

    def _validate_process_binding(self, value: Mapping[str, Any]) -> None:
        if (
            value.get("attempt_id") != self.attempt_id
            or value.get("attempt_nonce_sha256") != self.attempt_nonce_sha256
            or value.get("scope_sha256") != self.scope_sha256
            or value.get("worker") != self.worker_identity
            or value.get("broker") != self.broker_identity
        ):
            raise RuntimeError("request-control process binding differs")

    def bind_ready(self) -> None:
        ready, row_sha256 = self._receive(
            kind="request_control_ready", exact_keys=self._READY_KEYS
        )
        self._validate_process_binding(ready)
        framework_baseline = FrameworkThreadBaseline.model_validate(
            ready["framework_thread_baseline"]
        )
        broker_pre_release_ready_sha256 = (
            self.broker_pre_release_ready_sha256
        )
        if (
            ready["schema_id"] != "parser-request-control-ready-v1"
            or ready["expected_request_count"] != self.expected_request_count
            or not isinstance(ready["ready_at_monotonic_ns"], int)
            or ready["ready_at_monotonic_ns"] <= 0
            or framework_baseline.observed_at_monotonic_ns
            > ready["ready_at_monotonic_ns"]
            or broker_pre_release_ready_sha256 is None
            or framework_baseline.broker_post_release_baseline.pre_release_ready_sha256
            != broker_pre_release_ready_sha256
            or time.monotonic_ns() >= self.absolute_deadline_monotonic_ns
        ):
            raise RuntimeError("request-control READY binding differs")
        from app.services.tesseract_broker_native import (
            native_detailed_file_descriptor_inventory,
            native_detailed_thread_inventory,
        )

        controller_broker_thread_inventory = NativeThreadInventory.model_validate(
            asdict(
                native_detailed_thread_inventory(
                    int(self.broker_identity["pid"])
                )
            )
        )
        controller_broker_file_descriptor_inventory = (
            NativeFileDescriptorInventory.model_validate(
                asdict(
                    native_detailed_file_descriptor_inventory(
                        int(self.broker_identity["pid"])
                    )
                )
            )
        )
        controller_worker_thread_inventory = NativeThreadInventory.model_validate(
            asdict(
                native_detailed_thread_inventory(
                    int(self.worker_identity["pid"])
                )
            )
        )
        controller_worker_file_descriptor_inventory = (
            NativeFileDescriptorInventory.model_validate(
                asdict(
                    native_detailed_file_descriptor_inventory(
                        int(self.worker_identity["pid"])
                    )
                )
            )
        )
        self.ready_record = ready
        self.framework_thread_baseline = framework_baseline
        worker = ExactProcessIdentity(
            role="parser_worker",
            pid=int(self.worker_identity["pid"]),
            start_abstime=int(self.worker_identity["start_abstime"]),
            parent_pid=int(self.worker_identity["ppid"]),
            process_group_id=int(self.worker_identity["pgid"]),
            session_id=int(self.worker_identity["sid"]),
        )
        broker = ExactProcessIdentity(
            role="tesseract_broker",
            pid=int(self.broker_identity["pid"]),
            start_abstime=int(self.broker_identity["start_abstime"]),
            parent_pid=int(self.broker_identity["ppid"]),
            process_group_id=int(self.broker_identity["pgid"]),
            session_id=int(self.broker_identity["sid"]),
        )
        evidence = request_control_readiness_evidence(
            attempt_id=self.attempt_id,
            attempt_nonce_sha256=self.attempt_nonce_sha256,
            scope_sha256=self.scope_sha256,
            worker=worker,
            broker=broker,
            expected_request_count=self.expected_request_count,
            framework_thread_baseline=framework_baseline,
            controller_worker_thread_inventory=(
                controller_worker_thread_inventory
            ),
            controller_worker_file_descriptor_inventory=(
                controller_worker_file_descriptor_inventory
            ),
            controller_broker_thread_inventory=(
                controller_broker_thread_inventory
            ),
            controller_broker_file_descriptor_inventory=(
                controller_broker_file_descriptor_inventory
            ),
            ready_at_monotonic_ns=int(ready["ready_at_monotonic_ns"]),
            previous_record_sha256=str(ready["previous_record_sha256"]),
            transcript_row_sha256=row_sha256,
        )
        if evidence.ready_record_sha256 != ready["record_sha256"]:
            raise RuntimeError("request-control readiness identity differs")
        self.readiness_evidence = evidence

    def _request_common(
        self,
        *,
        request_id: str,
        request_sequence: int,
        request_deadline_monotonic_ns: int,
    ) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "attempt_nonce_sha256": self.attempt_nonce_sha256,
            "scope_sha256": self.scope_sha256,
            "request_id": request_id,
            "request_epoch": request_sequence + 1,
            "request_sequence": request_sequence,
            "worker": self.worker_identity,
            "broker": self.broker_identity,
            "request_deadline_monotonic_ns": request_deadline_monotonic_ns,
        }

    def _validate_request_common(
        self, value: Mapping[str, Any], expected: Mapping[str, Any]
    ) -> None:
        if any(value.get(key) != expected[key] for key in expected):
            raise RuntimeError("request-control request binding differs")
        deadline = expected["request_deadline_monotonic_ns"]
        if (
            isinstance(deadline, bool)
            or not isinstance(deadline, int)
            or self._monotonic_ns() >= deadline
        ):
            self._send_terminalized = True
            self.channel.close()
            raise TimeoutError("request-control frame arrived after deadline")

    def _sample_scratch(self) -> BrokerScratchInventory:
        started = max(1, time.monotonic_ns())
        before = os.fstat(self.request_root_fd)
        entries = os.listdir(self.request_root_fd)
        completed = max(started, time.monotonic_ns())
        after = os.fstat(self.request_root_fd)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_uid,
            before.st_nlink,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_uid,
            after.st_nlink,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if (
            entries
            or identity_before != identity_after
            or not stat.S_ISDIR(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o700
            or before.st_uid != os.geteuid()
        ):
            raise RuntimeError("controller scratch inventory differs")
        return broker_scratch_inventory(
            root_device=before.st_dev,
            root_inode=before.st_ino,
            root_mode=0o700,
            root_uid=before.st_uid,
            entry_count=0,
            aggregate_bytes=0,
            empty=True,
            scan_started_monotonic_ns=started,
            scan_completed_monotonic_ns=completed,
        )

    def _sample_edge(
        self,
        *,
        edge: Literal["begin", "end"],
        common: Mapping[str, Any],
    ) -> tuple[
        DarwinProcessSelfCpuSample,
        DarwinProcessSelfCpuSample,
        BrokerScratchInventory,
        ExternalCpuStableEdgeRecord,
        str,
    ]:
        from app.services.tesseract_broker_native import (
            native_detailed_file_descriptor_inventory,
            native_thread_inventory,
        )

        framework_baseline = self.framework_thread_baseline
        if framework_baseline is None:
            raise RuntimeError("framework thread baseline is absent")
        broker_thread_ids_before = native_thread_inventory(
            int(self.broker_identity["pid"])
        )
        broker_metrics = sample_darwin_process_group_metrics(
            process_group_id=int(self.broker_identity["pgid"])
        )
        broker_thread_ids_after = native_thread_inventory(
            int(self.broker_identity["pid"])
        )
        broker_fd_inventory = native_detailed_file_descriptor_inventory(
            int(self.broker_identity["pid"])
        )
        worker_thread_ids_before = native_thread_inventory(
            int(self.worker_identity["pid"])
        )
        worker_metrics = sample_darwin_process_group_metrics(
            process_group_id=int(self.worker_identity["pgid"])
        )
        if len(broker_metrics) != 1 or len(worker_metrics) != 1:
            raise RuntimeError("stable-edge process group is not root-only")
        broker_metric = broker_metrics[0]
        worker_metric = worker_metrics[0]
        worker_thread_ids_after = native_thread_inventory(
            int(self.worker_identity["pid"])
        )
        worker_fd_inventory = native_detailed_file_descriptor_inventory(
            int(self.worker_identity["pid"])
        )
        broker = broker_metric.cpu
        worker = worker_metric.cpu
        for sample, expected in (
            (broker, self.broker_identity),
            (worker, self.worker_identity),
        ):
            if (
                sample.pid != expected["pid"]
                or sample.start_abstime != expected["start_abstime"]
                or sample.parent_pid != expected["ppid"]
                or sample.process_group_id != expected["pgid"]
                or sample.session_id != expected["sid"]
            ):
                raise RuntimeError("stable-edge process identity differs")
        readiness = self.readiness_evidence
        if readiness is None:
            raise RuntimeError("request-control readiness evidence is absent")
        if (
            broker_thread_ids_before != broker_thread_ids_after
            or len(broker_thread_ids_after) != broker_metric.thread_count
            or broker_thread_ids_after
            != readiness.controller_broker_thread_inventory.thread_ids
            or broker_fd_inventory.inventory_sha256
            != readiness.controller_broker_file_descriptor_inventory.inventory_sha256
            or worker_thread_ids_before != worker_thread_ids_after
            or len(worker_thread_ids_after) != worker_metric.thread_count
            or worker_thread_ids_after
            != framework_baseline.full_worker_proc_thread_ids
            or worker_fd_inventory.inventory_sha256
            != framework_baseline.full_worker_file_descriptor_inventory.inventory_sha256
        ):
            raise RuntimeError("READY native thread/FD inventory drifted")

        def native_resource(
            *,
            role: Literal["parser_worker", "tesseract_broker"],
            metric: Any,
            native_thread_ids: tuple[int, ...],
            file_descriptor_inventory: Any,
        ) -> NativeProcessResourceSample:
            sample = metric.cpu
            retained_fd_inventory = NativeFileDescriptorInventory.model_validate(
                asdict(file_descriptor_inventory)
            )
            return NativeProcessResourceSample(
                cpu=NativeSelfCpuCounter(
                    identity=ExactProcessIdentity(
                        role=role,
                        pid=sample.pid,
                        start_abstime=sample.start_abstime,
                        parent_pid=sample.parent_pid,
                        process_group_id=sample.process_group_id,
                        session_id=sample.session_id,
                    ),
                    observed_monotonic_ns=sample.observed_monotonic_ns,
                    user_cpu_ns=sample.user_cpu_ns,
                    system_cpu_ns=sample.system_cpu_ns,
                ),
                rss_bytes=metric.rss_bytes,
                thread_count=metric.thread_count,
                native_thread_ids=native_thread_ids,
                file_descriptor_count=metric.file_descriptor_count,
                file_descriptor_inventory=retained_fd_inventory,
            )

        scratch = self._sample_scratch()
        sample_record = external_cpu_stable_edge_record(
            attempt_id=self.attempt_id,
            attempt_nonce_sha256=self.attempt_nonce_sha256,
            scope_sha256=self.scope_sha256,
            request_id=common["request_id"],
            request_epoch=common["request_epoch"],
            request_sequence=common["request_sequence"],
            request_deadline_monotonic_ns=common[
                "request_deadline_monotonic_ns"
            ],
            edge=edge,
            broker_sample=native_resource(
                role="tesseract_broker",
                metric=broker_metric,
                native_thread_ids=broker_thread_ids_after,
                file_descriptor_inventory=broker_fd_inventory,
            ),
            worker_sample=native_resource(
                role="parser_worker",
                metric=worker_metric,
                native_thread_ids=worker_thread_ids_after,
                file_descriptor_inventory=worker_fd_inventory,
            ),
            post_sample_scratch_inventory=scratch,
        )
        row_sha256 = self.cpu_samples.append(
            kind=f"{edge}-samples",
            record={
                "stable_edge": sample_record.model_dump(mode="json"),
                "framework_thread_baseline": framework_baseline.model_dump(
                    mode="json"
                ),
                "worker_native_thread_ids": list(worker_thread_ids_after),
            },
        )
        return broker, worker, scratch, sample_record, row_sha256

    def run_request(
        self,
        *,
        request_sequence: int,
        expected_source: SourceIdentity,
        binding: Mapping[str, Any],
        request_timeout_ns: int,
        resource_sampler: _ControllerOwnedRequestResourceSampler,
    ) -> _ExternalRequestCpuBoundary:
        if self.ready_record is None or request_sequence != len(self.boundaries) + 1:
            raise RuntimeError("request-control request sequence differs")
        if request_timeout_ns <= 0:
            raise ValueError("request-control timeout differs")
        request_id = f"{self.attempt_id}-q{request_sequence:04d}"
        deadline = min(
            self.absolute_deadline_monotonic_ns,
            self._monotonic_ns() + request_timeout_ns,
        )
        self._activate_request_deadline(deadline)
        common = self._request_common(
            request_id=request_id,
            request_sequence=request_sequence,
            request_deadline_monotonic_ns=deadline,
        )
        self._active_request_common = dict(common)
        binding_value = dict(binding)
        if binding_value != _production_request_binding(expected_source):
            raise RuntimeError("request-control source binding differs")
        binding_sha256 = _canonical_sha256(binding_value)
        arm = self._send(
            "request_control_arm",
            {
                "schema_id": "parser-request-control-arm-v1",
                **common,
                "binding": binding_value,
                "binding_sha256": binding_sha256,
                "arm_issued_at_monotonic_ns": max(1, self._monotonic_ns()),
                "previous_record_sha256": self.previous_record_sha256,
            },
        )
        arm_row_sha256 = self.last_transcript_row_sha256
        begin_keys = {
            "schema_id",
            *self._COMMON_REQUEST_KEYS,
            "arm_record_sha256",
            "arm_capability_sha256",
            "arm_consumed_at_monotonic_ns",
            "begin_barrier",
            "record_sha256",
        }
        begin_blocked, begin_row_sha256 = self._receive(
            kind="request_control_begin_blocked", exact_keys=begin_keys
        )
        self._validate_request_common(begin_blocked, common)
        if (
            begin_blocked["schema_id"]
            != "parser-request-control-begin-blocked-v1"
            or begin_blocked["arm_record_sha256"] != arm["record_sha256"]
            or begin_blocked["arm_consumed_at_monotonic_ns"]
            < arm["arm_issued_at_monotonic_ns"]
            or type(begin_blocked["begin_barrier"]) is not dict
            or begin_blocked["begin_barrier"].get("kind") != "BEGIN"
        ):
            raise RuntimeError("request-control BEGIN barrier differs")
        (
            broker_before,
            worker_before,
            begin_scratch,
            begin_sample_record,
            begin_sample_row,
        ) = (
            self._sample_edge(edge="begin", common=common)
        )
        resource_sampler.sample_boundary_edge("begin")
        samples_complete = max(
            broker_before.observed_monotonic_ns,
            worker_before.observed_monotonic_ns,
            begin_scratch.scan_completed_monotonic_ns,
        )
        begin_release = self._send(
            "request_control_begin_release",
            {
                "schema_id": "parser-request-control-begin-release-v1",
                **common,
                "begin_blocked_record_sha256": begin_blocked["record_sha256"],
                "begin_sample_record_sha256": begin_sample_record.record_sha256,
                "begin_samples_completed_monotonic_ns": samples_complete,
                "begin_release_monotonic_ns": max(
                    samples_complete, self._monotonic_ns()
                ),
                "previous_record_sha256": self.previous_record_sha256,
            },
        )
        begin_release_row_sha256 = self.last_transcript_row_sha256
        end_keys = {
            "schema_id",
            *self._COMMON_REQUEST_KEYS,
            "begin_release_record_sha256",
            "end_barrier",
            "broker_request_receipt_manifest",
            "broker_request_receipt_sha256",
            "request_binding_record_sha256",
            "thread_transfer_record_sha256s",
            "asgi_response_witness",
            "asgi_response_witness_sha256",
            "full_inner_asgi_returned",
            "request_task_blocked",
            "record_sha256",
        }
        end_blocked, end_row_sha256 = self._receive(
            kind="request_control_end_blocked", exact_keys=end_keys
        )
        self._validate_request_common(end_blocked, common)
        raw_manifest = end_blocked.get("broker_request_receipt_manifest")
        raw_end_barrier = end_blocked.get("end_barrier")
        if type(raw_manifest) is not dict or type(raw_end_barrier) is not dict:
            self.retain_terminal_failure(
                failure_code="peer_protocol_or_eof_failure",
                stage="request",
            )
            raise RuntimeError("request-control typed END evidence differs")
        try:
            raw_broker_receipt, _receipt_blob_record = (
                self._receive_request_receipt_blob(
                    manifest_mapping=raw_manifest,
                    request_id=request_id,
                    request_epoch=request_sequence + 1,
                    request_sequence=request_sequence,
                    deadline_monotonic_ns=deadline,
                )
            )
        except BaseException:
            self.retain_terminal_failure(
                failure_code="peer_protocol_or_eof_failure",
                stage="request",
            )
            raise
        try:
            from app.services.tesseract_broker_protocol import (
                BrokerBarrierSnapshot,
                request_receipt_from_mapping,
            )

            typed_broker_receipt = request_receipt_from_mapping(
                raw_broker_receipt
            )
            typed_end_barrier = BrokerBarrierSnapshot(
                kind=raw_end_barrier["kind"],
                request_id=raw_end_barrier["request_id"],
                request_epoch=raw_end_barrier["request_epoch"],
                request_sequence=raw_end_barrier["request_sequence"],
                broker_identity=typed_broker_receipt.end.broker_identity,
                quiescence=typed_broker_receipt.end,
                client_protocol_pending_bytes=raw_end_barrier[
                    "client_protocol_pending_bytes"
                ],
                transcript_next_sequence=raw_end_barrier[
                    "transcript_next_sequence"
                ],
                transcript_head_sha256=raw_end_barrier[
                    "transcript_head_sha256"
                ],
                receipt_sha256=raw_end_barrier["receipt_sha256"],
            )
        except (KeyError, TypeError, ValueError) as error:
            self.retain_terminal_failure(
                failure_code="peer_protocol_or_eof_failure",
                stage="request",
            )
            raise RuntimeError(
                "request-control END failed frozen typed validation"
            ) from error
        if (
            _canonical_payload_bytes(asdict(typed_broker_receipt))
            != _canonical_payload_bytes(raw_broker_receipt)
            or _canonical_payload_bytes(asdict(typed_end_barrier))
            != _canonical_payload_bytes(raw_end_barrier)
            or typed_broker_receipt.attempt_nonce_sha256
            != common["attempt_nonce_sha256"]
            or typed_broker_receipt.scope_sha256 != common["scope_sha256"]
            or typed_broker_receipt.request_id != request_id
            or typed_broker_receipt.request_epoch != request_sequence + 1
            or typed_broker_receipt.request_sequence != request_sequence
            or typed_broker_receipt.logical_phase != "request"
            or typed_broker_receipt.phase_deadline_monotonic_ns != deadline
            or typed_broker_receipt.arm_capability_sha256
            != begin_blocked["arm_capability_sha256"]
            or typed_broker_receipt.arm_issued_at_monotonic_ns
            != arm["arm_issued_at_monotonic_ns"]
            or typed_broker_receipt.arm_consumed_at_monotonic_ns
            != begin_blocked["arm_consumed_at_monotonic_ns"]
            or typed_broker_receipt.binding_sha256 != binding_sha256
            or typed_broker_receipt.request_binding is None
            or typed_broker_receipt.request_binding.binding_record_sha256
            != binding_sha256
            or typed_broker_receipt.request_binding.record_sha256
            != end_blocked["request_binding_record_sha256"]
            or [
                item.record_sha256
                for item in typed_broker_receipt.thread_transfers
            ]
            != end_blocked["thread_transfer_record_sha256s"]
            or typed_end_barrier.receipt_sha256
            != typed_broker_receipt.receipt_sha256
            or end_blocked["broker_request_receipt_sha256"]
            != typed_broker_receipt.receipt_sha256
        ):
            self.retain_terminal_failure(
                failure_code="peer_protocol_or_eof_failure",
                stage="request",
            )
            raise RuntimeError("request-control typed END authority differs")
        if end_blocked["full_inner_asgi_returned"] is not True:
            if typed_broker_receipt.terminal_kind != "abort":
                self.retain_terminal_failure(
                    failure_code="peer_protocol_or_eof_failure",
                    stage="request",
                )
                raise RuntimeError("request-control abort disposition differs")
            self.retain_terminal_failure(
                failure_code="peer_aborted_request",
                stage="request",
                broker_request_receipt_sha256=(
                    typed_broker_receipt.receipt_sha256
                ),
                failure_reason_sha256=(
                    typed_broker_receipt.failure_reason_sha256
                ),
            )
            raise RuntimeError("request-control peer aborted request")
        response_witness = end_blocked.get("asgi_response_witness")
        if not isinstance(response_witness, dict):
            raise RuntimeError("request-control ASGI response witness differs")
        try:
            typed_response_witness = AsgiResponseWitness.model_validate(
                response_witness
            )
        except ValidationError as error:
            self.retain_terminal_failure(
                failure_code="peer_protocol_or_eof_failure",
                stage="request",
            )
            raise RuntimeError(
                "request-control ASGI witness failed typed validation"
            ) from error
        if (
            end_blocked["schema_id"] != "parser-request-control-end-blocked-v1"
            or end_blocked["begin_release_record_sha256"]
            != begin_release["record_sha256"]
            or typed_broker_receipt.terminal_kind != "end"
            or end_blocked["request_task_blocked"] is not True
            or typed_response_witness.model_dump(mode="json")
            != response_witness
            or end_blocked["asgi_response_witness_sha256"]
            != typed_response_witness.record_sha256
            or not (
                typed_response_witness.response_start_send_completed_monotonic_ns
                <= typed_response_witness.response_body_send_completed_monotonic_ns
                <= typed_response_witness.inner_asgi_returned_monotonic_ns
                < deadline
            )
        ):
            self.retain_terminal_failure(
                failure_code="peer_protocol_or_eof_failure",
                stage="request",
            )
            raise RuntimeError("request-control END barrier differs")
        # Capture the final concurrent-resource edge while the worker remains
        # END-blocked and before the authoritative worker-after CPU sample.
        resource_sampler.sample_boundary_edge("end")
        (
            broker_after,
            worker_after,
            end_scratch,
            end_sample_record,
            end_sample_row,
        ) = self._sample_edge(edge="end", common=common)
        end_samples_complete = max(
            broker_after.observed_monotonic_ns,
            worker_after.observed_monotonic_ns,
            end_scratch.scan_completed_monotonic_ns,
        )
        receipt_release = self._send(
            "request_control_receipt_release",
            {
                "schema_id": "parser-request-control-receipt-release-v1",
                **common,
                "end_blocked_record_sha256": end_blocked["record_sha256"],
                "end_sample_record_sha256": end_sample_record.record_sha256,
                "end_samples_completed_monotonic_ns": end_samples_complete,
                "broker_request_receipt_sha256": end_blocked[
                    "broker_request_receipt_sha256"
                ],
                "receipt_release_monotonic_ns": max(
                    end_samples_complete + 1, self._monotonic_ns()
                ),
                "previous_record_sha256": self.previous_record_sha256,
            },
        )
        receipt_release_row_sha256 = self.last_transcript_row_sha256
        result_keys = {
            "schema_id",
            *self._COMMON_REQUEST_KEYS,
            "receipt_release_record_sha256",
            "worker_result",
            "record_sha256",
        }
        raw_result, durable_result_row_sha256 = self._receive(
            kind="request_control_result", exact_keys=result_keys
        )
        self._validate_request_common(raw_result, common)
        if (
            raw_result["schema_id"] != "parser-request-control-result-v1"
            or raw_result["receipt_release_record_sha256"]
            != receipt_release["record_sha256"]
            or type(raw_result["worker_result"]) is not dict
        ):
            raise RuntimeError("request-control raw result differs")
        try:
            typed_worker_result = ProductionRawRequestObservation.model_validate(
                raw_result["worker_result"]
            )
        except ValidationError as error:
            raise RuntimeError(
                "request-control worker result failed typed validation"
            ) from error
        if (
            typed_worker_result.attempt_id != self.attempt_id
            or typed_worker_result.request_id != request_id
            or typed_worker_result.request_index != request_sequence
            or typed_worker_result.request_epoch != request_sequence + 1
            or typed_worker_result.source != expected_source
            or typed_worker_result.broker_request_receipt_sha256
            != end_blocked["broker_request_receipt_sha256"]
            or typed_worker_result.request_binding_record_sha256
            != end_blocked["request_binding_record_sha256"]
            or typed_worker_result.materialized_at_monotonic_ns >= deadline
            or typed_worker_result.http_status_code
            != typed_response_witness.status_code
            or typed_worker_result.response_body_sha256
            != typed_response_witness.body_sha256
            or typed_worker_result.response_size_bytes
            != typed_response_witness.body_bytes
            or typed_worker_result.asgi_response_witness_sha256
            != end_blocked["asgi_response_witness_sha256"]
        ):
            raise RuntimeError("request-control typed worker result differs")
        content_type_values: list[bytes] = []
        try:
            for header in typed_response_witness.ordered_headers:
                name = bytes.fromhex(header.name_hex)
                value = bytes.fromhex(header.value_hex)
                if name.lower() == b"content-type":
                    content_type_values.append(value)
        except (TypeError, ValueError) as error:
            raise RuntimeError(
                "request-control ASGI response headers differ"
            ) from error
        if (
            len(content_type_values) != 1
            or hashlib.sha256(content_type_values[0]).hexdigest()
            != typed_worker_result.response_content_type_sha256
        ):
            raise RuntimeError("request-control response content type differs")
        result_ack = self._send(
            "request_control_result_ack",
            {
                "schema_id": "parser-request-control-result-ack-v1",
                **common,
                "result_record_sha256": raw_result["record_sha256"],
                "retained_at_monotonic_ns": max(1, self._monotonic_ns()),
                "previous_record_sha256": self.previous_record_sha256,
            },
        )
        self._complete_request_deadline(deadline)
        self._active_request_common = None
        durable_result_ack_row_sha256 = self.last_transcript_row_sha256
        boundary = _ExternalRequestCpuBoundary(
            request_id=request_id,
            request_epoch=request_sequence + 1,
            request_sequence=request_sequence,
            arm=arm,
            begin_blocked=begin_blocked,
            begin_release=begin_release,
            end_blocked=end_blocked,
            broker_request_receipt=raw_broker_receipt,
            receipt_release=receipt_release,
            raw_result=raw_result,
            result_ack=result_ack,
            broker_before=broker_before,
            worker_before=worker_before,
            broker_after=broker_after,
            worker_after=worker_after,
            begin_scratch=begin_scratch,
            end_scratch=end_scratch,
            begin_sample_record=begin_sample_record,
            end_sample_record=end_sample_record,
            begin_sample_record_sha256=begin_sample_record.record_sha256,
            end_sample_record_sha256=end_sample_record.record_sha256,
            begin_sample_row_sha256=begin_sample_row,
            end_sample_row_sha256=end_sample_row,
            frame_record_sha256s=tuple(
                str(item["record_sha256"])
                for item in (
                    arm,
                    begin_blocked,
                    begin_release,
                    end_blocked,
                    receipt_release,
                    raw_result,
                    result_ack,
                )
            ),
            transcript_row_sha256s=(
                arm_row_sha256,
                begin_row_sha256,
                begin_release_row_sha256,
                end_row_sha256,
                receipt_release_row_sha256,
                durable_result_row_sha256,
                durable_result_ack_row_sha256,
            ),
        )
        self.boundaries.append(boundary)
        return boundary

    def finish(self) -> None:
        close_keys = {
            "schema_id",
            "attempt_id",
            "attempt_nonce_sha256",
            "scope_sha256",
            "worker",
            "broker",
            "completed_request_count",
            "last_request_sequence",
            "previous_record_sha256",
            "record_sha256",
        }
        close, durable_close_row = self._receive(
            kind="request_control_close", exact_keys=close_keys
        )
        self._validate_process_binding(close)
        if (
            close["schema_id"] != "parser-request-control-close-v1"
            or close["completed_request_count"] != self.expected_request_count
            or close["last_request_sequence"] != self.expected_request_count
        ):
            raise RuntimeError("request-control close binding differs")
        self._send(
            "request_control_close_ack",
            {
                "schema_id": "parser-request-control-close-ack-v1",
                "attempt_id": self.attempt_id,
                "attempt_nonce_sha256": self.attempt_nonce_sha256,
                "scope_sha256": self.scope_sha256,
                "worker": self.worker_identity,
                "broker": self.broker_identity,
                "completed_request_count": self.expected_request_count,
                "close_record_sha256": close["record_sha256"],
                "closed_at_monotonic_ns": max(1, time.monotonic_ns()),
                "previous_record_sha256": self.previous_record_sha256,
            },
        )
        self.close()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.channel.close()
        finally:
            self.transcript.close()
            self.cpu_samples.close()


def _parse_watchdog_launcher_rows(
    raw: bytes,
    *,
    require_terminal: bool,
) -> tuple[dict[str, Any], ...]:
    if not raw or len(raw) > 1_048_576:
        raise RuntimeError("watchdog launcher log size differs")
    if not raw.endswith(b"\n"):
        if require_terminal:
            raise RuntimeError("watchdog launcher log has a partial row")
        return ()
    previous = "0" * 64
    rows: list[dict[str, Any]] = []
    for sequence, encoded in enumerate(raw.splitlines(), 1):
        try:
            value = json.loads(encoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError("watchdog launcher row is not canonical JSON") from error
        if (
            type(value) is not dict
            or set(value)
            != {
                "schema_id",
                "row_sequence",
                "previous_row_sha256",
                "kind",
                "record",
                "row_sha256",
            }
            or value["schema_id"] != "phase-latency-watchdog-launcher-log-v1"
            or value["row_sequence"] != sequence
            or value["previous_row_sha256"] != previous
            or type(value["kind"]) is not str
            or type(value["record"]) is not dict
            or _canonical_payload_bytes(value) != encoded
        ):
            raise RuntimeError("watchdog launcher row binding differs")
        digest = value["row_sha256"]
        unhashed = dict(value)
        unhashed.pop("row_sha256")
        record = dict(value["record"])
        record_digest = record.pop("record_sha256", None)
        if (
            type(digest) is not str
            or digest != _canonical_sha256(unhashed)
            or type(record_digest) is not str
            or record_digest != _canonical_sha256(record)
        ):
            raise RuntimeError("watchdog launcher row hash differs")
        previous = digest
        rows.append(value)
    if require_terminal and (
        not rows or rows[-1]["kind"] != "launcher_terminal"
    ):
        raise RuntimeError("watchdog launcher terminal row is absent")
    return tuple(rows)


def _read_watchdog_launcher_rows(
    path: Path,
    *,
    require_terminal: bool,
) -> tuple[tuple[dict[str, Any], ...], bytes, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) != 0o600
            or opened.st_uid != os.geteuid()
            or opened.st_nlink != 1
            or opened.st_size <= 0
            or opened.st_size > 1_048_576
        ):
            raise RuntimeError("watchdog launcher log custody differs")
        raw = b""
        while len(raw) < opened.st_size:
            chunk = os.read(descriptor, opened.st_size - len(raw))
            if not chunk:
                raise RuntimeError("watchdog launcher log read was short")
            raw += chunk
        after = os.fstat(descriptor)
        if any(
            getattr(after, field) != getattr(opened, field)
            for field in ("st_dev", "st_ino", "st_mode", "st_uid", "st_nlink", "st_size")
        ):
            raise RuntimeError("watchdog launcher log changed during reread")
    finally:
        os.close(descriptor)
    rows = _parse_watchdog_launcher_rows(raw, require_terminal=require_terminal)
    return rows, raw, opened


def _decoded_launcher_wait_status(record: Mapping[str, Any]) -> int:
    raw_status = record.get("raw_wait_status")
    status = record.get("wait_status")
    if type(raw_status) is not int or type(status) is not dict:
        raise RuntimeError("watchdog launcher wait4 status differs")
    if os.WIFEXITED(raw_status):
        decoded = int(os.WEXITSTATUS(raw_status))
    elif os.WIFSIGNALED(raw_status):
        decoded = -int(os.WTERMSIG(raw_status))
    else:
        raise RuntimeError("watchdog launcher wait4 status is nonterminal")
    expected_status = {
        "exited": bool(os.WIFEXITED(raw_status)),
        "exit_code": (
            int(os.WEXITSTATUS(raw_status)) if os.WIFEXITED(raw_status) else None
        ),
        "signaled": bool(os.WIFSIGNALED(raw_status)),
        "signal_number": (
            int(os.WTERMSIG(raw_status)) if os.WIFSIGNALED(raw_status) else None
        ),
        "core_dumped": bool(
            getattr(os, "WCOREDUMP", lambda _status: False)(raw_status)
        ),
    }
    if status != expected_status:
        raise RuntimeError("watchdog launcher decoded wait4 status differs")
    return decoded


def _launcher_root_returncode_if_retained(
    *, path: Path, role: str, pid: int
) -> int | None:
    try:
        rows, _raw, _opened = _read_watchdog_launcher_rows(
            path, require_terminal=False
        )
    except FileNotFoundError:
        return None
    for row in rows:
        if row["kind"] != f"{role}_wait4_tombstone":
            continue
        record = row["record"]
        if record.get("role") != role or record.get("root_pid") != pid:
            raise RuntimeError("watchdog launcher wait4 root differs")
        return _decoded_launcher_wait_status(record)
    return None


def _validate_watchdog_launcher_terminal_log(
    *,
    path: Path | None = None,
    raw_log: bytes | None = None,
    attempt_id: str,
    expected_roots: Mapping[str, LauncherOwnedRootIdentity],
    expected_watchdog_result_record_sha256: str,
) -> dict[str, Any]:
    if (path is None) == (raw_log is None):
        raise ValueError("one watchdog launcher log source is required")
    opened: os.stat_result | None
    if path is not None:
        rows, raw, opened = _read_watchdog_launcher_rows(
            path, require_terminal=True
        )
    else:
        assert raw_log is not None
        raw = raw_log
        rows = _parse_watchdog_launcher_rows(raw, require_terminal=True)
        opened = None
    if not rows or rows[0]["kind"] != "launcher_ready":
        raise RuntimeError("watchdog launcher READY row is absent")
    ready = rows[0]["record"]
    if (
        set(ready)
        != {
            "schema_id",
            "attempt_id",
            "controller",
            "launcher",
            "ready_at_monotonic_ns",
            "record_sha256",
        }
        or ready["attempt_id"] != attempt_id
        or type(ready["controller"]) is not dict
        or set(ready["controller"])
        != {"pid", "start_abstime", "create_time_ns", "pgid", "sid"}
        or any(
            type(value) is not int or value <= 0
            for value in ready["controller"].values()
        )
        or type(ready["launcher"]) is not dict
        or ready["launcher"].get("pid") != ready["launcher"].get("pgid")
        or ready["launcher"].get("pid") != ready["launcher"].get("sid")
        or ready["launcher"].get("ppid") != ready["controller"].get("pid")
        or ready["launcher"].get("uid") != ready["launcher"].get("euid")
    ):
        raise RuntimeError("watchdog launcher READY grammar differs")
    spawn_records: dict[str, dict[str, Any]] = {}
    wait_records: dict[str, tuple[dict[str, Any], str, int]] = {}
    esrch_records: dict[str, dict[str, Any]] = {}
    commit: dict[str, Any] | None = None
    for row in rows[1:-1]:
        kind = row["kind"]
        record = row["record"]
        if record.get("attempt_id") != attempt_id:
            raise RuntimeError("watchdog launcher attempt identity differs")
        if kind.endswith("_spawned"):
            role = kind.removesuffix("_spawned")
            if (
                role not in expected_roots
                or role in spawn_records
                or set(record)
                != {
                    "schema_id",
                    "attempt_id",
                    "role",
                    "launcher",
                    "root",
                    "launch_request_sha256",
                    "launch_frame_sha256",
                    "observed_at_monotonic_ns",
                    "record_sha256",
                }
            ):
                raise RuntimeError("watchdog launcher spawn grammar differs")
            expected = expected_roots[role]
            root = record["root"]
            if (
                record["role"] != role
                or type(root) is not dict
                or record["launcher"] != ready["launcher"]
                or root != expected.model_dump(mode="json")
                or root.get("ppid") != ready["launcher"]["pid"]
                or root.get("uid") != ready["launcher"]["uid"]
                or root.get("euid") != ready["launcher"]["euid"]
                or root.get("pid") != root.get("pgid")
                or root.get("pid") != root.get("sid")
                or record["observed_at_monotonic_ns"]
                < ready["ready_at_monotonic_ns"]
            ):
                raise RuntimeError("watchdog launcher spawned root differs")
            spawn_records[role] = record
        elif kind == "launch_committed":
            if commit is not None or set(record) != {
                "schema_id",
                "attempt_id",
                "roles",
                "root_launch_record_sha256s",
                "request_sha256",
                "frame_sha256",
                "committed_at_monotonic_ns",
                "record_sha256",
            }:
                raise RuntimeError("watchdog launcher commit grammar differs")
            commit = record
        elif kind.endswith("_wait4_tombstone"):
            role = kind.removesuffix("_wait4_tombstone")
            if (
                role not in expected_roots
                or role in wait_records
                or set(record)
                != {
                    "schema_id",
                    "attempt_id",
                    "role",
                    "launcher",
                    "root_pid",
                    "root_identity",
                    "launch_record_sha256",
                    "raw_wait_status",
                    "wait_status",
                    "rusage",
                    "maximum_resident_set_size_bytes",
                    "minor_faults",
                    "major_faults",
                    "voluntary_context_switches",
                    "involuntary_context_switches",
                    "nonreaping_wait4_probe_count",
                    "terminal_wait4_reap_count",
                    "observed_at_monotonic_ns",
                    "record_sha256",
                }
                or record["role"] != role
                or record["root_pid"] != expected_roots[role].pid
                or record["terminal_wait4_reap_count"] != 1
                or record["launcher"] != ready["launcher"]
            ):
                raise RuntimeError("watchdog launcher wait4 grammar differs")
            try:
                RawRUsage.model_validate(record["rusage"])
            except (TypeError, ValueError) as error:
                raise RuntimeError(
                    "watchdog launcher wait4 rusage differs"
                ) from error
            nonnegative_wait4_values = (
                record["raw_wait_status"],
                record["maximum_resident_set_size_bytes"],
                record["minor_faults"],
                record["major_faults"],
                record["voluntary_context_switches"],
                record["involuntary_context_switches"],
                record["nonreaping_wait4_probe_count"],
            )
            if (
                any(
                    type(value) is not int or value < 0
                    for value in nonnegative_wait4_values
                )
                or record["nonreaping_wait4_probe_count"] < 1
                or type(record["observed_at_monotonic_ns"]) is not int
                or record["observed_at_monotonic_ns"] <= 0
            ):
                raise RuntimeError("watchdog launcher wait4 counters differ")
            wait_records[role] = (
                record,
                row["row_sha256"],
                _decoded_launcher_wait_status(record),
            )
        elif kind.endswith("_group_esrch"):
            role = kind.removesuffix("_group_esrch")
            if (
                role not in expected_roots
                or role in esrch_records
                or set(record)
                != {
                    "schema_id",
                    "attempt_id",
                    "role",
                    "root_identity",
                    "wait4_record_sha256",
                    "wait4_log_row_sha256",
                    "group_probe",
                    "observed_at_monotonic_ns",
                    "record_sha256",
                }
                or record["role"] != role
                or record["group_probe"] != "killpg-zero-esrch-after-wait4-v1"
            ):
                raise RuntimeError("watchdog launcher ESRCH grammar differs")
            esrch_records[role] = record
        elif kind.endswith("_launch_failed"):
            raise RuntimeError("successful launcher log contains root launch failure")
        else:
            raise RuntimeError("watchdog launcher row kind is unrecognized")
    roles = tuple(expected_roots)
    if (
        tuple(spawn_records) != roles
        or set(wait_records) != set(roles)
        or set(esrch_records) != set(roles)
        or commit is None
        or commit["roles"] != list(roles)
        or commit["root_launch_record_sha256s"]
        != [spawn_records[role]["record_sha256"] for role in roles]
        or commit["committed_at_monotonic_ns"]
        < max(
            record["observed_at_monotonic_ns"]
            for record in spawn_records.values()
        )
    ):
        raise RuntimeError("watchdog launcher root lifecycle is incomplete")
    for role in roles:
        wait, wait_row_sha, _returncode = wait_records[role]
        esrch = esrch_records[role]
        if (
            wait["launch_record_sha256"]
            != spawn_records[role]["record_sha256"]
            or wait["root_identity"] != spawn_records[role]["root"]
            or esrch["wait4_record_sha256"] != wait["record_sha256"]
            or esrch["wait4_log_row_sha256"] != wait_row_sha
            or esrch["root_identity"] != spawn_records[role]["root"]
            or wait["observed_at_monotonic_ns"]
            < commit["committed_at_monotonic_ns"]
            or esrch["observed_at_monotonic_ns"]
            < wait["observed_at_monotonic_ns"]
        ):
            raise RuntimeError("watchdog launcher wait4/ESRCH join differs")
    terminal = rows[-1]["record"]
    expected_terminal_keys = {
        "schema_id",
        "attempt_id",
        "launcher",
        "root_returncodes",
        "root_wait4_record_sha256s",
        "root_wait4_log_row_sha256s",
        "root_groups_esrch",
        "watchdog_result_record_sha256",
        "cleanup_succeeded",
        "cleanup_error_type",
        "observed_at_monotonic_ns",
        "record_sha256",
    }
    if (
        set(terminal) != expected_terminal_keys
        or terminal["attempt_id"] != attempt_id
        or terminal["launcher"] != ready["launcher"]
        or terminal["cleanup_succeeded"] is not True
        or terminal["cleanup_error_type"] is not None
        or terminal["root_returncodes"]
        != {role: wait_records[role][2] for role in roles}
        or terminal["root_wait4_record_sha256s"]
        != {role: wait_records[role][0]["record_sha256"] for role in roles}
        or terminal["root_wait4_log_row_sha256s"]
        != {role: wait_records[role][1] for role in roles}
        or terminal["root_groups_esrch"] != {role: True for role in roles}
        or terminal["watchdog_result_record_sha256"]
        != expected_watchdog_result_record_sha256
        or terminal["observed_at_monotonic_ns"]
        < max(
            record["observed_at_monotonic_ns"]
            for record in esrch_records.values()
        )
    ):
        raise RuntimeError("watchdog launcher terminal custody differs")
    return {
        "raw": raw,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
        "row_count": len(rows),
        "device": opened.st_dev if opened is not None else None,
        "inode": opened.st_ino if opened is not None else None,
        "mode": stat.S_IMODE(opened.st_mode) if opened is not None else None,
        "uid": opened.st_uid if opened is not None else None,
        "nlink": opened.st_nlink if opened is not None else None,
        "controller": ControllerProcessIdentity(
            pid=ready["controller"]["pid"],
            create_time_ns=ready["controller"]["create_time_ns"],
            process_group_id=ready["controller"]["pgid"],
            session_id=ready["controller"]["sid"],
        ),
        "controller_start_abstime": ready["controller"]["start_abstime"],
        "launcher": TrustedLauncherIdentity.model_validate(ready["launcher"]),
        "worker_root": expected_roots["worker"],
        "broker_root": expected_roots.get("broker"),
        "watchdog_result_record_sha256": terminal[
            "watchdog_result_record_sha256"
        ],
        "terminal_record_sha256": terminal["record_sha256"],
        "root_returncodes": terminal["root_returncodes"],
        "root_wait4_record_sha256s": terminal["root_wait4_record_sha256s"],
        "root_wait4_log_row_sha256s": terminal["root_wait4_log_row_sha256s"],
    }


class _WatchdogOwnedProcessProxy:
    """Controller view of a process exclusively waited by the watchdog parent."""

    def __init__(
        self,
        *,
        args: tuple[str, ...],
        identity: ControllerProcessIdentity,
        stdout_fd: int,
        stderr_fd: int,
        launcher_log_path: Path,
        role: Literal["broker", "worker"],
    ) -> None:
        self.args = args
        self.pid = identity.pid
        self.identity = identity
        self.stdout = os.fdopen(stdout_fd, "rb", buffering=0)
        self.stderr = os.fdopen(stderr_fd, "rb", buffering=0)
        self.launcher_log_path = launcher_log_path
        self.role = role
        self.returncode: int | None = None
        self._empty_without_tombstone_observed_at_ns: int | None = None

    def poll(self) -> int | None:
        if self.returncode is not None:
            return self.returncode
        retained = _launcher_root_returncode_if_retained(
            path=self.launcher_log_path, role=self.role, pid=self.pid
        )
        if retained is not None:
            self.returncode = retained
            return self.returncode
        state = _frozen_process_group_state(self.identity)
        if state == "empty":
            # The sole parent performs wait4 before it can append+fsync the
            # authoritative tombstone.  Do not turn that small durability
            # interval into a false disappearance, but fail if the exact row
            # does not become visible within the bounded reap window.
            now_ns = time.monotonic_ns()
            if self._empty_without_tombstone_observed_at_ns is None:
                self._empty_without_tombstone_observed_at_ns = now_ns
                return None
            if now_ns - self._empty_without_tombstone_observed_at_ns <= int(
                POST_DEADLINE_REAP_SECONDS * 1_000_000_000
            ):
                return None
            raise RuntimeError(
                "watchdog-owned root disappeared before durable wait4 custody"
            )
        if state == "unsafe":
            raise RuntimeError("watchdog-owned root identity drifted")
        self._empty_without_tombstone_observed_at_ns = None
        return None

    def wait(self, timeout: float | None = None) -> int:
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(self.args, timeout)
            time.sleep(0.01)
        assert self.returncode is not None
        return self.returncode


class _WatchdogLauncherController:
    """Strict controller side of watchdog-owned root launch custody."""

    def __init__(
        self,
        *,
        sock: socket.socket,
        attempt_id: str,
        controller: ControllerProcessIdentity,
        controller_start_abstime: int,
        deadline_monotonic_ns: int,
    ) -> None:
        self.channel = _WatchdogLauncherChannel(sock)
        self.attempt_id = attempt_id
        self.controller = controller
        self.controller_start_abstime = controller_start_abstime
        self.deadline_ns = deadline_monotonic_ns
        self.launcher_identity: dict[str, int] | None = None
        self.root_acks: dict[str, dict[str, Any]] = {}
        self.cancel_ack: dict[str, Any] | None = None
        self.committed = False
        self.closed = False

    def _receive(
        self, *, expected_kind: str
    ) -> tuple[dict[str, Any], tuple[int, ...], str]:
        while True:
            remaining_ns = self.deadline_ns - time.monotonic_ns()
            if remaining_ns <= 0:
                raise TimeoutError("watchdog launcher control timed out")
            readable, _writable, _exceptional = select.select(
                (self.channel.fileno,),
                (),
                (),
                min(0.05, remaining_ns / 1_000_000_000),
            )
            if not readable:
                continue
            _kind, payload, descriptors, frame_sha = self.channel.receive(
                expected_kind=expected_kind
            )
            return payload, descriptors, frame_sha

    def bind_ready(self) -> dict[str, int]:
        payload, descriptors, _frame_sha = self._receive(
            expected_kind="launcher_ready"
        )
        if descriptors:
            raise RuntimeError("watchdog launcher READY carried descriptors")
        value = dict(payload)
        record_sha = value.pop("record_sha256", None)
        launcher = value.get("launcher")
        expected_controller = {
            "pid": self.controller.pid,
            "start_abstime": self.controller_start_abstime,
            "create_time_ns": self.controller.create_time_ns,
            "pgid": self.controller.process_group_id,
            "sid": self.controller.session_id,
        }
        if (
            value.get("schema_id")
            != "phase-latency-watchdog-launcher-ready-v1"
            or value.get("attempt_id") != self.attempt_id
            or value.get("controller") != expected_controller
            or type(launcher) is not dict
            or set(launcher)
            != {"pid", "start_abstime", "ppid", "pgid", "sid", "uid", "euid"}
            or any(type(item) is not int or item <= 0 for item in launcher.values())
            or launcher["pid"] != launcher["pgid"]
            or launcher["pid"] != launcher["sid"]
            or launcher["ppid"] != self.controller.pid
            or launcher["uid"] != os.getuid()
            or launcher["euid"] != os.geteuid()
            or record_sha != _canonical_sha256(value)
        ):
            raise RuntimeError("watchdog launcher READY custody differs")
        self.launcher_identity = dict(launcher)
        return dict(launcher)

    def launch_root(
        self,
        *,
        role: Literal["broker", "worker"],
        command: tuple[str, ...],
        environment: Mapping[str, str],
        descriptor_bindings: tuple[dict[str, Any], ...],
    ) -> dict[str, Any]:
        if self.launcher_identity is None or role in self.root_acks:
            raise RuntimeError("watchdog root launch order differs")
        descriptors = tuple(int(item["descriptor"]) for item in descriptor_bindings)
        wire_bindings = []
        for item in descriptor_bindings:
            wire = dict(item)
            wire.pop("descriptor")
            wire_bindings.append(wire)
        environment_value = dict(sorted(environment.items()))
        fields = {
            "schema_id": "phase-latency-watchdog-owned-root-launch-v1",
            "attempt_id": self.attempt_id,
            "role": role,
            "command": list(command),
            "command_sha256": _canonical_sha256(list(command)),
            "cwd": str(Path(__file__).resolve(strict=True).parents[2]),
            "environment": environment_value,
            "environment_sha256": _canonical_sha256(environment_value),
            "descriptor_bindings": wire_bindings,
            "start_new_session": True,
        }
        request = {**fields, "request_sha256": _canonical_sha256(fields)}
        request_frame_sha = self.channel.send(
            "launch_root", request, descriptors=descriptors
        )
        ack, ack_descriptors, _ack_frame_sha = self._receive(
            expected_kind="launch_root_ack"
        )
        if ack_descriptors:
            raise RuntimeError("watchdog root ACK carried descriptors")
        ack_value = dict(ack)
        ack_sha = ack_value.pop("record_sha256", None)
        root = ack_value.get("root")
        if (
            ack_value.get("schema_id")
            != "phase-latency-watchdog-owned-root-launch-ack-v1"
            or ack_value.get("attempt_id") != self.attempt_id
            or ack_value.get("role") != role
            or ack_value.get("launcher") != self.launcher_identity
            or ack_value.get("launch_request_sha256")
            != request["request_sha256"]
            or ack_value.get("launch_frame_sha256") != request_frame_sha
            or type(root) is not dict
            or set(root)
            != {
                "pid",
                "start_abstime",
                "create_time_ns",
                "ppid",
                "pgid",
                "sid",
                "uid",
                "euid",
            }
            or any(type(item) is not int or item <= 0 for item in root.values())
            or root["ppid"] != self.launcher_identity["pid"]
            or root["pid"] != root["pgid"]
            or root["pid"] != root["sid"]
            or root["uid"] != self.launcher_identity["uid"]
            or root["euid"] != self.launcher_identity["euid"]
            or ack_sha != _canonical_sha256(ack_value)
        ):
            raise RuntimeError("watchdog-owned root ACK custody differs")
        ack["record_sha256"] = ack_sha
        self.root_acks[role] = dict(ack)
        return dict(ack)

    def commit(self, roles: tuple[str, ...]) -> dict[str, Any]:
        records = [self.root_acks[role]["launch_record_sha256"] for role in roles]
        fields = {
            "schema_id": "phase-latency-watchdog-owned-launch-commit-v1",
            "attempt_id": self.attempt_id,
            "roles": list(roles),
            "root_launch_record_sha256s": records,
        }
        request = {**fields, "request_sha256": _canonical_sha256(fields)}
        self.channel.send("launch_commit", request)
        ack, descriptors, _frame_sha = self._receive(
            expected_kind="launch_commit_ack"
        )
        if descriptors:
            raise RuntimeError("watchdog launch commit ACK carried descriptors")
        value = dict(ack)
        digest = value.pop("record_sha256", None)
        if (
            value.get("schema_id")
            != "phase-latency-watchdog-owned-launch-commit-ack-v1"
            or value.get("attempt_id") != self.attempt_id
            or value.get("launcher") != self.launcher_identity
            or value.get("request_sha256") != request["request_sha256"]
            or digest != _canonical_sha256(value)
        ):
            raise RuntimeError("watchdog launch commit ACK differs")
        ack["record_sha256"] = digest
        self.committed = True
        return dict(ack)

    def request_cleanup(self, *, reason: str) -> dict[str, Any]:
        if self.cancel_ack is not None:
            return dict(self.cancel_ack)
        if reason not in {"controller_cleanup", "stream_limit", "controller_abort"}:
            raise ValueError("watchdog launcher cleanup reason differs")
        fields = {
            "schema_id": "phase-latency-watchdog-owned-launch-cancel-v1",
            "attempt_id": self.attempt_id,
            "reason": reason,
            "root_launch_record_sha256s": [
                value["launch_record_sha256"]
                for _role, value in sorted(self.root_acks.items())
            ],
            "requested_at_monotonic_ns": max(1, time.monotonic_ns()),
        }
        request = {**fields, "record_sha256": _canonical_sha256(fields)}
        self.channel.send("launch_cancel", request)
        prior_deadline = self.deadline_ns
        self.deadline_ns = max(
            self.deadline_ns,
            time.monotonic_ns() + 2_000_000_000,
        )
        try:
            ack, descriptors, _frame_sha = self._receive(
                expected_kind="launch_cancel_ack"
            )
        finally:
            self.deadline_ns = prior_deadline
        if descriptors:
            raise RuntimeError("watchdog launcher cancel ACK carried descriptors")
        value = dict(ack)
        digest = value.pop("record_sha256", None)
        if (
            value.get("schema_id")
            != "phase-latency-watchdog-owned-launch-cancel-ack-v1"
            or value.get("attempt_id") != self.attempt_id
            or value.get("cancel_record_sha256") != request["record_sha256"]
            or type(value.get("cancel_log_row_sha256")) is not str
            or digest != _canonical_sha256(value)
        ):
            raise RuntimeError("watchdog launcher cancel ACK differs")
        ack["record_sha256"] = digest
        self.cancel_ack = dict(ack)
        return dict(ack)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.channel.close()


@dataclass(slots=True)
class _PendingPreIntentLauncher:
    process: subprocess.Popen[bytes]
    identity: ControllerProcessIdentity
    control: _WatchdogLauncherController
    terminal_fd: int
    additional_cleanup: Callable[[], None]


_PENDING_PREINTENT_LAUNCHERS: dict[int, _PendingPreIntentLauncher] = {}
_PENDING_PREINTENT_RESOURCE_CLEANUPS: dict[int, Callable[[], None]] = {}


def _register_pending_preintent_resource_cleanup(
    cleanup: Callable[[], None],
) -> None:
    thread_id = threading.get_ident()
    if thread_id in _PENDING_PREINTENT_RESOURCE_CLEANUPS:
        raise RuntimeError("pre-intent resource custody overlapped")
    _PENDING_PREINTENT_RESOURCE_CLEANUPS[thread_id] = cleanup


def _transfer_pending_preintent_resource_cleanup(
    cleanup: Callable[[], None],
) -> None:
    pending = _PENDING_PREINTENT_RESOURCE_CLEANUPS.pop(
        threading.get_ident(), None
    )
    if pending is not cleanup:
        raise RuntimeError("pre-intent resource custody transfer differs")


def _cleanup_pending_preintent_resources() -> None:
    cleanup = _PENDING_PREINTENT_RESOURCE_CLEANUPS.pop(
        threading.get_ident(), None
    )
    if cleanup is not None:
        cleanup()


def _register_pending_preintent_launcher(
    pending: _PendingPreIntentLauncher,
) -> None:
    thread_id = threading.get_ident()
    if thread_id in _PENDING_PREINTENT_LAUNCHERS:
        raise RuntimeError("pre-intent launcher custody overlapped")
    _PENDING_PREINTENT_LAUNCHERS[thread_id] = pending


def _transfer_pending_preintent_launcher(
    control: _WatchdogLauncherController,
) -> None:
    pending = _PENDING_PREINTENT_LAUNCHERS.pop(threading.get_ident(), None)
    if pending is None or pending.control is not control:
        raise RuntimeError("pre-intent launcher custody transfer differs")


def _cleanup_pending_preintent_launcher() -> None:
    pending = _PENDING_PREINTENT_LAUNCHERS.pop(threading.get_ident(), None)
    if pending is None:
        return
    cleanup_error: BaseException | None = None
    try:
        pending.control.request_cleanup(reason="controller_abort")
    except BaseException as error:
        cleanup_error = error
    try:
        pending.additional_cleanup()
    except BaseException as error:
        if cleanup_error is None:
            cleanup_error = error
    pending.control.close()
    try:
        pending.process.wait(timeout=POST_DEADLINE_REAP_SECONDS)
    except subprocess.TimeoutExpired:
        state = _frozen_process_group_state(pending.identity)
        if state == "unsafe":
            raise RuntimeError("pre-intent launcher identity drifted")
        if state == "exact":
            _signal_frozen_process_group(pending.identity, signal.SIGTERM)
        try:
            pending.process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            state = _frozen_process_group_state(pending.identity)
            if state == "unsafe":
                raise RuntimeError("pre-intent launcher identity drifted")
            if state == "exact":
                _signal_frozen_process_group(pending.identity, signal.SIGKILL)
            pending.process.wait(timeout=POST_DEADLINE_REAP_SECONDS)
    finally:
        with contextlib.suppress(OSError):
            os.close(pending.terminal_fd)
    if _frozen_process_group_state(pending.identity) != "empty":
        raise RuntimeError("pre-intent launcher group survived cleanup")
    if cleanup_error is not None:
        raise cleanup_error


def _with_preintent_launcher_cleanup(function: Callable[..., object]):
    @wraps(function)
    def wrapped(*args: object, **kwargs: object):
        try:
            result = function(*args, **kwargs)
        except BaseException:
            cleanup_error: BaseException | None = None
            try:
                _cleanup_pending_preintent_launcher()
            except BaseException as error:
                cleanup_error = error
            try:
                _cleanup_pending_preintent_resources()
            except BaseException as error:
                if cleanup_error is None:
                    cleanup_error = error
            if cleanup_error is not None:
                raise cleanup_error
            raise
        if threading.get_ident() in _PENDING_PREINTENT_LAUNCHERS:
            _cleanup_pending_preintent_launcher()
            _cleanup_pending_preintent_resources()
            raise RuntimeError("pre-intent launcher custody was not transferred")
        if threading.get_ident() in _PENDING_PREINTENT_RESOURCE_CLEANUPS:
            _cleanup_pending_preintent_resources()
            raise RuntimeError("pre-intent resource custody was not transferred")
        return result

    return wrapped


def _launcher_descriptor_binding(
    *,
    command: tuple[str, ...],
    environment: Mapping[str, str],
    descriptor: int,
    name: str,
    disposition: str,
    argument_options: tuple[str, ...] = (),
    environment_keys: tuple[str, ...] = (),
) -> dict[str, Any]:
    indices: list[int] = []
    for option in argument_options:
        matches = [index for index, value in enumerate(command) if value == option]
        if len(matches) != 1 or matches[0] + 1 >= len(command):
            raise RuntimeError("launcher command FD option differs")
        value_index = matches[0] + 1
        if command[value_index] != str(descriptor):
            raise RuntimeError("launcher command FD value differs")
        indices.append(value_index)
    for key in environment_keys:
        if environment.get(key) != str(descriptor):
            raise RuntimeError("launcher environment FD value differs")
    return {
        "descriptor": descriptor,
        "name": name,
        "original_fd": descriptor,
        "disposition": disposition,
        "argv_indices": indices,
        "environment_keys": list(environment_keys),
    }


def _start_watchdog_owned_launcher(
    *,
    attempt_id: str,
    workspace: Path,
    output_directory: Path,
    controller: ControllerProcessIdentity,
    controller_start_abstime: int,
    absolute_deadline_monotonic_ns: int,
    startup_timeout_ns: int,
    heartbeat_root: Path,
    heartbeat_path: Path,
    ready_path: Path,
    terminal_path: Path,
    phase_control_path: Path,
    phase_ack_path: Path,
    child_watch_log_path: Path | None,
    attempt_nonce_sha256: str | None,
    scope_sha256: str | None,
    watchdog_protocol_sha256: str | None,
    native_closure_sha256: str | None,
    additional_cleanup: Callable[[], None],
) -> tuple[
    subprocess.Popen[bytes],
    ControllerProcessIdentity,
    _WatchdogLauncherController,
    dict[str, int],
    Path,
    int,
]:
    launcher_log_path = (
        output_directory / f"{attempt_id}-watchdog-launcher.jsonl"
    )
    if launcher_log_path.exists():
        raise FileExistsError("watchdog launcher log already exists")
    controller_socket, watchdog_socket = socket.socketpair(
        socket.AF_UNIX, socket.SOCK_STREAM
    )
    terminal_fd = _create_private_empty(terminal_path)
    watchdog_script = (
        workspace / "tests/benchmarks/latency_prewarm_watchdog.py"
    ).resolve(strict=True)
    command = (
        sys.executable,
        "-I",
        str(watchdog_script),
        "--attempt-id",
        attempt_id,
        "--controller-pid",
        str(controller.pid),
        "--controller-start-abstime",
        str(controller_start_abstime),
        "--controller-create-time-ns",
        str(controller.create_time_ns),
        "--controller-pgid",
        str(controller.process_group_id),
        "--controller-sid",
        str(controller.session_id),
        "--heartbeat-root",
        str(heartbeat_root),
        "--heartbeat",
        str(heartbeat_path),
        "--ready",
        str(ready_path),
        "--phase-control",
        str(phase_control_path),
        "--phase-ack",
        str(phase_ack_path),
        "--absolute-deadline-monotonic-ns",
        str(absolute_deadline_monotonic_ns),
        "--launch-control-fd",
        str(watchdog_socket.fileno()),
        "--launcher-log",
        str(launcher_log_path),
    )
    broker_values = (
        child_watch_log_path,
        attempt_nonce_sha256,
        scope_sha256,
        watchdog_protocol_sha256,
        native_closure_sha256,
    )
    if any(value is not None for value in broker_values):
        if not all(value is not None for value in broker_values):
            raise RuntimeError("watchdog launcher broker binding is incomplete")
        command += (
            "--expect-broker",
            "--startup-timeout-ns",
            str(startup_timeout_ns),
            "--child-watch-log",
            str(child_watch_log_path),
            "--attempt-nonce-sha256",
            str(attempt_nonce_sha256),
            "--scope-sha256",
            str(scope_sha256),
            "--watchdog-protocol-sha256",
            str(watchdog_protocol_sha256),
            "--native-closure-sha256",
            str(native_closure_sha256),
        )
    process: subprocess.Popen[bytes] | None = None
    control: _WatchdogLauncherController | None = None
    try:
        with _blocked_controller_termination_signals():
            process = subprocess.Popen(
                command,
                cwd=workspace,
                stdin=subprocess.DEVNULL,
                stdout=terminal_fd,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
                pass_fds=(watchdog_socket.fileno(),),
                env=sanitized_watchdog_environment(),
            )
            watchdog_socket.close()
            control = _WatchdogLauncherController(
                sock=controller_socket,
                attempt_id=attempt_id,
                controller=controller,
                controller_start_abstime=controller_start_abstime,
                deadline_monotonic_ns=min(
                    absolute_deadline_monotonic_ns,
                    time.monotonic_ns() + WATCHDOG_READY_TIMEOUT_NS,
                ),
            )
            launcher_identity = control.bind_ready()
            watchdog_identity = _process_identity(process.pid)
        if (
            watchdog_identity.pid != launcher_identity["pid"]
            or watchdog_identity.create_time_ns <= 0
            or launcher_identity["ppid"] != controller.pid
            or watchdog_identity.process_group_id != process.pid
            or watchdog_identity.session_id != process.pid
        ):
            raise RuntimeError("watchdog launcher process identity differs")
        control.deadline_ns = absolute_deadline_monotonic_ns
        _register_pending_preintent_launcher(
            _PendingPreIntentLauncher(
                process=process,
                identity=watchdog_identity,
                control=control,
                terminal_fd=terminal_fd,
                additional_cleanup=additional_cleanup,
            )
        )
        return (
            process,
            watchdog_identity,
            control,
            launcher_identity,
            launcher_log_path,
            terminal_fd,
        )
    except BaseException:
        _PENDING_PREINTENT_LAUNCHERS.pop(threading.get_ident(), None)
        if control is not None:
            control.close()
        else:
            controller_socket.close()
        with contextlib.suppress(OSError):
            watchdog_socket.close()
        if process is not None:
            with contextlib.suppress(ProcessLookupError, OSError):
                os.killpg(process.pid, signal.SIGKILL)
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=1.0)
        with contextlib.suppress(OSError):
            os.close(terminal_fd)
        raise


@dataclass(slots=True)
class _GuardedWorkerLaunch:
    attempt_id: str
    workspace: Path
    output_directory: Path
    protocol: Path
    environment: dict[str, str]
    controller_before: ControllerResourceSample
    controller_identity: ControllerProcessIdentity
    absolute_deadline_monotonic_ns: int
    intent: ProductionLaunchIntent
    intent_path: Path
    launch_path: Path
    launch_failure_path: Path
    heartbeat_path: Path
    watchdog_ready_path: Path
    watchdog_terminal_path: Path
    prebind_fatal_path: Path
    phase_control_path: Path
    phase_ack_path: Path
    broker_config_path: Path | None = None
    broker_ready_path: Path | None = None
    supervisor_ready_path: Path | None = None
    child_watch_log_path: Path | None = None
    request_control_path: Path | None = None
    request_cpu_sample_path: Path | None = None
    request_resource_sample_path: Path | None = None
    native_closure_post_path: Path | None = None
    source_executable_path: Path | None = None
    staged_executable_path: Path | None = None
    native_fork_probe_path: Path | None = None
    native_spawn_guard_path: Path | None = None
    native_spawn_guard_source_path: Path | None = None
    native_runtime_gate_source_path: Path | None = None
    native_runtime_gate_library_path: Path | None = None
    native_sandbox_probe_path: Path | None = None
    native_sandbox_probe_source_path: Path | None = None
    sandbox_probe_materialization: SandboxProbeMaterialization | None = None
    sandbox_attempt_probe_authority: SandboxAttemptProbeAuthority | None = None
    sandbox_network_terminal: dict[str, object] | None = None
    worker_sandbox_probe_report: dict[str, Any] | None = None
    broker_sandbox_probe_report: dict[str, Any] | None = None
    tessdata_root_path: Path | None = None
    native_closure: dict[str, Any] | None = None
    guard_python: dict[str, Any] | None = None
    guard_python_path_custody: dict[str, Any] | None = None
    guard_python_native_closure: dict[str, Any] | None = None
    guard_python_module_tree_custody: dict[str, Any] | None = None
    guard_wrapper_source_path: Path | None = None
    native_closure_sha256: str | None = None
    source_executable_sha256: str | None = None
    staged_executable_sha256: str | None = None
    native_fork_probe_sha256: str | None = None
    native_fork_probe_source_sha256: str | None = None
    native_spawn_guard_sha256: str | None = None
    native_spawn_guard_source_sha256: str | None = None
    native_sandbox_probe_sha256: str | None = None
    native_sandbox_probe_source_sha256: str | None = None
    tessdata_sha256: str | None = None
    startup_phase_record: PhaseDeadlineRecord | None = None
    startup_phase_ack: PhaseDeadlineAck | None = None
    phase_control_snapshot: AppendOnlyLogSnapshot | None = None
    phase_ack_snapshot: AppendOnlyLogSnapshot | None = None
    process: subprocess.Popen[bytes] | _WatchdogOwnedProcessProxy | None = None
    capture: _BoundedPipeCapture | None = None
    broker: subprocess.Popen[bytes] | _WatchdogOwnedProcessProxy | None = None
    broker_capture: _BoundedPipeCapture | None = None
    watchdog: subprocess.Popen[bytes] | None = None
    launcher_control: _WatchdogLauncherController | None = None
    launcher_identity: dict[str, int] | None = None
    launcher_log_path: Path | None = None
    launcher_log_sha256: str | None = None
    launcher_log_size_bytes: int | None = None
    launcher_log_row_count: int | None = None
    launcher_terminal_record_sha256: str | None = None
    launcher_root_wait4_record_sha256s: dict[str, str] | None = None
    launcher_root_wait4_log_row_sha256s: dict[str, str] | None = None
    launcher_terminal_evidence: LauncherTerminalEvidence | None = None
    worker_launcher_root: LauncherOwnedRootIdentity | None = None
    broker_launcher_root: LauncherOwnedRootIdentity | None = None
    worker_identity: ControllerProcessIdentity | None = None
    broker_identity: ControllerProcessIdentity | None = None
    worker_parent_pid: int | None = None
    broker_parent_pid: int | None = None
    watchdog_identity: ControllerProcessIdentity | None = None
    launch_record: ProductionLaunchRecord | None = None
    launch_failure_record: ProductionLaunchFailureRecord | None = None
    release_read_fd: int | None = None
    release_write_fd: int | None = None
    broker_release_read_fd: int | None = None
    broker_release_write_fd: int | None = None
    broker_ready_read_fd: int | None = None
    broker_ready_write_fd: int | None = None
    supervisor_ready_read_fd: int | None = None
    supervisor_ready_write_fd: int | None = None
    request_root_fd: int | None = None
    worker_sandbox_report_read_fd: int | None = None
    worker_sandbox_report_write_fd: int | None = None
    broker_sandbox_report_read_fd: int | None = None
    broker_sandbox_report_write_fd: int | None = None
    broker_socket: socket.socket | None = None
    worker_socket: socket.socket | None = None
    broker_watch_socket: socket.socket | None = None
    watchdog_broker_socket: socket.socket | None = None
    worker_phase_socket: socket.socket | None = None
    watchdog_phase_socket: socket.socket | None = None
    worker_request_socket: socket.socket | None = None
    controller_request_socket: socket.socket | None = None
    request_control: _RequestControlController | None = None
    watchdog_terminal_fd: int | None = None
    watchdog_terminal: ProductionWatchdogTerminalEvidence | None = None
    watchdog_terminal_sha256: str | None = None
    watchdog_terminal_observed_sha256: str | None = None
    watchdog_terminal_validation_failed: bool = False
    watchdog_reaped: bool = False
    watchdog_group_gone: bool = False
    broker_reaped: bool = False
    broker_group_gone: bool = False
    broker_ready_sha256: str | None = None
    supervisor_ready_sha256: str | None = None
    broker_config_sha256: str | None = None
    child_watch_log_sha256: str | None = None
    child_watch_log_validation_failed: bool = False
    child_watch_broker_row_count: int = 0
    child_watch_event_count: int = 0
    stdout_observed_size_bytes: int = 0
    stdout_observed_sha256: str = hashlib.sha256(b"").hexdigest()
    stderr_observed_size_bytes: int = 0
    stderr_observed_sha256: str = hashlib.sha256(b"").hexdigest()
    stream_limit_exceeded: bool = False
    stream_cleanup_forced: bool = False
    stream_capture_completed: bool = False
    stdout_retained_bytes: bytes = b""
    stderr_retained_bytes: bytes = b""
    broker_stdout_observed_size_bytes: int = 0
    broker_stdout_observed_sha256: str = hashlib.sha256(b"").hexdigest()
    broker_stderr_observed_size_bytes: int = 0
    broker_stderr_observed_sha256: str = hashlib.sha256(b"").hexdigest()
    broker_stream_limit_exceeded: bool = False
    broker_stream_cleanup_forced: bool = False
    broker_stream_capture_completed: bool = False
    phase_deadline_log_sha256: str | None = None
    phase_ack_log_sha256: str | None = None
    phase_sequence_count: int = 0
    request_control_transcript_sha256: str | None = None
    request_control_terminal_transcript: (
        TerminalRequestControlTranscriptEvidence | None
    ) = None
    request_cpu_sample_log_sha256: str | None = None
    request_resource_sample_log_sha256: str | None = None
    request_resource_sample_log_row_count: int | None = None
    request_resource_sample_log_size_bytes: int | None = None
    native_closure_post_sha256: str | None = None
    immutable_input_custody: DarwinImmutableTreeCustody | None = None
    immutable_input_custody_evidence: (
        ImmutableRuntimeInputCustodyEvidence | None
    ) = None
    immutable_input_custody_validation_failed: bool = False
    external_request_boundaries: tuple[_ExternalRequestCpuBoundary, ...] = ()

    def retain_immutable_input_custody(self) -> None:
        custody = self.immutable_input_custody
        if custody is None:
            return
        self.immutable_input_custody = None
        raw_evidence: dict[str, object] | None = None
        try:
            raw_evidence = custody.finish()
            raw_evidence["attempt_id"] = self.attempt_id
            raw_evidence.pop("record_sha256", None)
            raw_evidence["record_sha256"] = _canonical_sha256(raw_evidence)
            evidence = ImmutableRuntimeInputCustodyEvidence.model_validate(
                raw_evidence
            )
            self.immutable_input_custody_evidence = evidence
            self.immutable_input_custody_validation_failed = False
        except ImmutableTreeCustodyViolation as error:
            custody.abort()
            raw_evidence = error.evidence
            self.immutable_input_custody_validation_failed = True
        except BaseException:
            custody.abort()
            self.immutable_input_custody_validation_failed = True
        if raw_evidence is not None:
            raw = _canonical_payload_bytes(raw_evidence) + b"\n"
            _write_private_payload(
                self.output_directory
                / f"{self.attempt_id}-immutable-input-custody.json",
                raw,
                maximum_bytes=MAXIMUM_IMMUTABLE_INPUT_CUSTODY_BYTES,
            )

    def retain_launch_failure(self, error: BaseException) -> None:
        if self.launch_failure_record is not None:
            return
        fields = {
            "schema_id": "phase-latency-prewarm-launch-failure-v1",
            "attempt_id": self.attempt_id,
            "intent_sha256": self.intent.intent_sha256,
            "retained_monotonic_ns": max(1, time.monotonic_ns()),
            "controller": self.controller_identity,
            "worker_started": self.process is not None,
            "broker_started": self.broker is not None,
            "watchdog_started": self.watchdog is not None,
            "launch_record_retained": self.launch_record is not None,
            "error_type_sha256": _canonical_sha256(
                {
                    "error_type": (
                        f"{type(error).__module__}.{type(error).__qualname__}"
                    )
                }
            ),
        }
        record = ProductionLaunchFailureRecord(
            **fields, record_sha256=_canonical_sha256(fields)
        )
        write_private_canonical(self.launch_failure_path, record)
        self.launch_failure_record = record

    def retain_phase_logs(self) -> None:
        if self.phase_deadline_log_sha256 is not None:
            return
        if not self.phase_control_path.exists() or not self.phase_ack_path.exists():
            return
        records, self.phase_control_snapshot = read_phase_deadlines(
            root=self.phase_control_path.parent.resolve(strict=True),
            path=self.phase_control_path.resolve(),
            attempt_id=self.attempt_id,
            whole_deadline_monotonic_ns=self.absolute_deadline_monotonic_ns,
            previous=self.phase_control_snapshot,
        )
        acks, self.phase_ack_snapshot = read_phase_acks(
            root=self.phase_ack_path.parent.resolve(strict=True),
            path=self.phase_ack_path.resolve(),
            attempt_id=self.attempt_id,
            previous=self.phase_ack_snapshot,
        )
        if len(acks) > len(records) or any(
            ack.sequence != record.sequence
            or ack.phase_record_sha256 != record.record_sha256
            for ack, record in zip(acks, records, strict=False)
        ):
            raise RuntimeError("retained phase deadline/ACK chains differ")
        if (
            self.request_control is not None
            and self.watchdog_terminal is not None
            and self.watchdog_terminal.outcome == "worker_exited"
            and self.process is not None
            and self.process.returncode == 0
        ):
            _require_complete_phase_authority(
                records=records,
                acks=acks,
                expected_request_count=(
                    self.request_control.expected_request_count
                ),
                request_boundaries=self.external_request_boundaries,
            )
        phase_raw = _read_private_payload(
            self.phase_control_path, maximum_bytes=65_536
        )
        ack_raw = _read_private_payload(self.phase_ack_path, maximum_bytes=65_536)
        retained_phase_path = (
            self.output_directory / f"{self.attempt_id}-phase-deadlines.jsonl"
        )
        retained_ack_path = (
            self.output_directory / f"{self.attempt_id}-phase-acks.jsonl"
        )
        self.phase_deadline_log_sha256 = (
            hashlib.sha256(phase_raw).hexdigest()
            if self.phase_control_path == retained_phase_path
            else _write_private_payload(retained_phase_path, phase_raw)
        )
        self.phase_ack_log_sha256 = (
            hashlib.sha256(ack_raw).hexdigest()
            if self.phase_ack_path == retained_ack_path
            else _write_private_payload(retained_ack_path, ack_raw)
        )
        self.phase_sequence_count = len(records)

    def validate_child_watch_log(self) -> None:
        if self.child_watch_log_path is None:
            return
        if self.watchdog_terminal is None:
            raise RuntimeError("child-watch log lacks terminal evidence")
        bundle = _read_child_watch_bundle(self.child_watch_log_path)
        event_kinds = {
            "child_watch_register": 0,
            "child_watch_birth": 0,
            "child_watch_reaped": 0,
        }
        for value in bundle["events"]:
            if value["kind"] not in event_kinds:
                raise RuntimeError("child-watch event kind differs")
            event_kinds[value["kind"]] += 1
        if (
            bundle["compact_ledger_size_bytes"]
            != self.watchdog_terminal.child_watch_log_size_bytes
            or bundle["broker_head_sha256"]
            != self.watchdog_terminal.child_watch_log_head_sha256
            or bundle["broker_row_count"]
            != self.watchdog_terminal.child_watch_log_row_count
            or bundle["record_blob_count"]
            != self.watchdog_terminal.child_watch_record_blob_count
            or bundle["record_blob_size_bytes"]
            != self.watchdog_terminal.child_watch_record_blob_size_bytes
            or bundle["record_blob_head_sha256"]
            != self.watchdog_terminal.child_watch_record_blob_head_sha256
            or bundle["record_blob_root"]["record_sha256"]
            != self.watchdog_terminal.child_watch_record_blob_root_sha256
            or bundle["event_count"]
            != self.watchdog_terminal.child_watch_event_blob_count
            or bundle["event_blob_size_bytes"]
            != self.watchdog_terminal.child_watch_event_blob_size_bytes
            or bundle["event_blob_root"]["record_sha256"]
            != self.watchdog_terminal.child_watch_event_blob_root_sha256
            or bundle["event_head_sha256"]
            != self.watchdog_terminal.child_watch_event_head_sha256
            or event_kinds["child_watch_register"]
            != (self.watchdog_terminal.child_watch_registration_count or 0)
            or event_kinds["child_watch_reaped"]
            != (self.watchdog_terminal.child_watch_reaped_count or 0)
            or not (
                event_kinds["child_watch_reaped"]
                <= event_kinds["child_watch_birth"]
                <= event_kinds["child_watch_register"]
            )
        ):
            raise RuntimeError("child-watch terminal chain binding differs")
        self.child_watch_log_sha256 = bundle["compact_ledger_sha256"]
        self.child_watch_broker_row_count = bundle["broker_row_count"]
        self.child_watch_event_count = bundle["event_count"]
        self.child_watch_log_validation_failed = False

    def retain_native_closure_post_observation(self) -> None:
        values = (
            self.native_closure_post_path,
            self.source_executable_path,
            self.staged_executable_path,
            self.native_fork_probe_path,
            self.native_spawn_guard_path,
            self.native_spawn_guard_source_path,
            self.native_sandbox_probe_path,
            self.native_sandbox_probe_source_path,
            self.tessdata_root_path,
            self.native_closure,
            self.native_closure_sha256,
            self.source_executable_sha256,
            self.staged_executable_sha256,
            self.native_fork_probe_sha256,
            self.native_fork_probe_source_sha256,
            self.native_spawn_guard_sha256,
            self.native_spawn_guard_source_sha256,
            self.native_sandbox_probe_sha256,
            self.native_sandbox_probe_source_sha256,
            self.tessdata_sha256,
            self.child_watch_log_path,
            self.guard_python,
            self.guard_python_path_custody,
            self.guard_python_native_closure,
            self.guard_python_module_tree_custody,
            self.guard_wrapper_source_path,
        )
        if all(value is None for value in values):
            return
        if any(value is None for value in values):
            raise RuntimeError("native closure post-custody binding is incomplete")
        assert self.native_closure_post_path is not None
        assert self.source_executable_path is not None
        assert self.staged_executable_path is not None
        assert self.native_fork_probe_path is not None
        assert self.native_spawn_guard_path is not None
        assert self.native_spawn_guard_source_path is not None
        assert self.native_sandbox_probe_path is not None
        assert self.native_sandbox_probe_source_path is not None
        assert self.tessdata_root_path is not None
        assert self.native_closure is not None
        assert self.native_closure_sha256 is not None
        assert self.source_executable_sha256 is not None
        assert self.staged_executable_sha256 is not None
        assert self.native_fork_probe_sha256 is not None
        assert self.native_fork_probe_source_sha256 is not None
        assert self.native_spawn_guard_sha256 is not None
        assert self.native_spawn_guard_source_sha256 is not None
        assert self.native_sandbox_probe_sha256 is not None
        assert self.native_sandbox_probe_source_sha256 is not None
        assert self.tessdata_sha256 is not None
        assert self.child_watch_log_path is not None
        assert self.guard_python is not None
        assert self.guard_python_path_custody is not None
        assert self.guard_python_native_closure is not None
        assert self.guard_python_module_tree_custody is not None
        assert self.guard_wrapper_source_path is not None
        if self.native_closure_post_path.exists():
            raise FileExistsError("native closure post-observation already exists")
        from app.services.tesseract_native_closure import (
            native_closure_sha256,
            validate_native_closure,
        )
        from app.services.tesseract_broker import (
            derive_guard_python_module_tree_custody,
            derive_guard_python_path_custody,
        )
        from app.services.tesseract_broker_protocol import (
            immutable_input_observation_from_mapping,
        )

        reobserved = validate_native_closure(
            self.native_closure, reobserve=True
        )
        reobserved_sha256 = native_closure_sha256(reobserved)
        reobserved_runtime_gate = reobserved.get("runtime_gate")
        if type(reobserved_runtime_gate) is not dict:
            raise RuntimeError("native runtime gate post-observation is absent")
        observed_guard_python = _root_owned_executable_identity(
            Path(str(self.guard_python["resolved_path"]))
        )
        observed_guard_path_custody = derive_guard_python_path_custody(
            str(self.guard_python["resolved_path"])
        )
        observed_guard_native_closure = validate_native_closure(
            self.guard_python_native_closure,
            reobserve=True,
        )
        observed_guard_module_tree = derive_guard_python_module_tree_custody(
            str(self.guard_python_module_tree_custody["resolved_root"])
        )
        observed_guard_wrapper_source_sha256 = _sha256_file(
            self.guard_wrapper_source_path
        )
        tessdata_records, _tessdata_bytes = _tree_content_records(
            self.tessdata_root_path, allow_empty=True
        )
        observed_tessdata_sha256 = _content_records_sha256(tessdata_records)
        observed_source_sha256 = _sha256_file(self.source_executable_path)
        observed_staged_sha256 = _sha256_file(self.staged_executable_path)
        observed_native_fork_probe_sha256 = _sha256_file(
            self.native_fork_probe_path
        )
        native_fork_probe_stat = self.native_fork_probe_path.lstat()
        observed_native_spawn_guard_sha256 = _sha256_file(
            self.native_spawn_guard_path
        )
        native_spawn_guard_stat = self.native_spawn_guard_path.lstat()
        observed_native_spawn_guard_source_sha256 = _sha256_file(
            self.native_spawn_guard_source_path
        )
        observed_native_sandbox_probe_sha256 = _sha256_file(
            self.native_sandbox_probe_path
        )
        native_sandbox_probe_stat = self.native_sandbox_probe_path.lstat()
        observed_native_sandbox_probe_source_sha256 = _sha256_file(
            self.native_sandbox_probe_source_path
        )
        child_watch_bundle = _read_child_watch_bundle(
            self.child_watch_log_path
        )
        immutable_rows = [
            row
            for row in child_watch_bundle["rows"]
            if row["kind"] == "shutdown_immutable_inputs"
        ]
        normal_terminal = bool(
            self.watchdog_terminal is not None
            and self.watchdog_terminal.outcome == "worker_exited"
        )
        if len(immutable_rows) > 1 or (
            normal_terminal and len(immutable_rows) != 1
        ):
            raise RuntimeError("shutdown immutable-input row cardinality differs")
        ledger_observation = None
        if immutable_rows:
            ledger_observation = immutable_input_observation_from_mapping(
                immutable_rows[0]["record"]
            )
        expected_ledger_observation = {
            "schema_id": "parser-tesseract-immutable-input-observation-v1",
            "native_closure_sha256": self.native_closure_sha256,
            "native_trust_model": "frozen-native-closure-trusted-v1",
            "native_containment_claim": (
                "none-trusted-pinned-native-computation"
            ),
            "source_executable_sha256": self.source_executable_sha256,
            "staged_executable_sha256": self.staged_executable_sha256,
            "native_spawn_guard_sha256": self.native_spawn_guard_sha256,
            "native_spawn_guard_source_sha256": (
                self.native_spawn_guard_source_sha256
            ),
            "native_runtime_gate_source_sha256": (
                reobserved_runtime_gate["source"]["sha256"]
            ),
            "native_runtime_gate_library_sha256": (
                reobserved_runtime_gate["library"]["sha256"]
            ),
            "native_runtime_gate_record_sha256": (
                reobserved_runtime_gate["record_sha256"]
            ),
            "guard_python_sha256": self.guard_python["sha256"],
            "guard_python_path_custody_sha256": (
                self.guard_python_path_custody["record_sha256"]
            ),
            "guard_python_native_closure_sha256": (
                self.guard_python_native_closure["closure_sha256"]
            ),
            "guard_python_module_tree_sha256": (
                self.guard_python_module_tree_custody["record_sha256"]
            ),
            "guard_wrapper_source_sha256": (
                observed_guard_wrapper_source_sha256
            ),
            "guard_wrapper_delivery_basis": (
                "execve-python-c-embedded-source-v1"
            ),
            "tessdata_sha256": self.tessdata_sha256,
        }
        if (
            _canonical_payload_bytes(reobserved)
            != _canonical_payload_bytes(self.native_closure)
            or reobserved_sha256 != self.native_closure_sha256
            or observed_guard_python != self.guard_python
            or observed_guard_path_custody
            != self.guard_python_path_custody
            or observed_guard_native_closure
            != self.guard_python_native_closure
            or observed_guard_module_tree
            != self.guard_python_module_tree_custody
            or observed_source_sha256 != self.source_executable_sha256
            or observed_staged_sha256 != self.staged_executable_sha256
            or observed_native_fork_probe_sha256
            != self.native_fork_probe_sha256
            or not stat.S_ISREG(native_fork_probe_stat.st_mode)
            or stat.S_IMODE(native_fork_probe_stat.st_mode) != 0o500
            or native_fork_probe_stat.st_uid != os.geteuid()
            or native_fork_probe_stat.st_nlink != 1
            or observed_native_spawn_guard_sha256
            != self.native_spawn_guard_sha256
            or observed_native_spawn_guard_source_sha256
            != self.native_spawn_guard_source_sha256
            or not stat.S_ISREG(native_spawn_guard_stat.st_mode)
            or stat.S_IMODE(native_spawn_guard_stat.st_mode) != 0o500
            or native_spawn_guard_stat.st_uid != os.geteuid()
            or native_spawn_guard_stat.st_nlink != 1
            or observed_native_sandbox_probe_sha256
            != self.native_sandbox_probe_sha256
            or observed_native_sandbox_probe_source_sha256
            != self.native_sandbox_probe_source_sha256
            or not stat.S_ISREG(native_sandbox_probe_stat.st_mode)
            or stat.S_IMODE(native_sandbox_probe_stat.st_mode) != 0o500
            or native_sandbox_probe_stat.st_uid != os.geteuid()
            or native_sandbox_probe_stat.st_nlink != 1
            or observed_tessdata_sha256 != self.tessdata_sha256
            or (
                ledger_observation is not None
                and (
                    {
                        key: value
                        for key, value in ledger_observation.items()
                        if key != "observed_at_monotonic_ns"
                    }
                    != expected_ledger_observation
                )
            )
        ):
            raise RuntimeError("native closure post-observation drifted")
        fields = {
            "schema_id": "phase-latency-native-closure-post-observation-v1",
            "attempt_id": self.attempt_id,
            "native_closure": reobserved,
            "native_closure_sha256": reobserved_sha256,
            "native_trust_model": "frozen-native-closure-trusted-v1",
            "native_containment_claim": (
                "none-trusted-pinned-native-computation"
            ),
            "source_executable_sha256": observed_source_sha256,
            "staged_executable_sha256": observed_staged_sha256,
            "native_fork_probe_source_sha256": (
                self.native_fork_probe_source_sha256
            ),
            "native_fork_probe_library_sha256": (
                observed_native_fork_probe_sha256
            ),
            "native_fork_probe_device": native_fork_probe_stat.st_dev,
            "native_fork_probe_inode": native_fork_probe_stat.st_ino,
            "native_fork_probe_mode": native_fork_probe_stat.st_mode,
            "native_fork_probe_uid": native_fork_probe_stat.st_uid,
            "native_spawn_guard_source_sha256": (
                observed_native_spawn_guard_source_sha256
            ),
            "native_spawn_guard_library_sha256": (
                observed_native_spawn_guard_sha256
            ),
            "native_spawn_guard_device": native_spawn_guard_stat.st_dev,
            "native_spawn_guard_inode": native_spawn_guard_stat.st_ino,
            "native_spawn_guard_mode": native_spawn_guard_stat.st_mode,
            "native_spawn_guard_uid": native_spawn_guard_stat.st_uid,
            "native_sandbox_probe_source_sha256": (
                observed_native_sandbox_probe_source_sha256
            ),
            "native_sandbox_probe_library_sha256": (
                observed_native_sandbox_probe_sha256
            ),
            "native_sandbox_probe_device": native_sandbox_probe_stat.st_dev,
            "native_sandbox_probe_inode": native_sandbox_probe_stat.st_ino,
            "native_sandbox_probe_mode": native_sandbox_probe_stat.st_mode,
            "native_sandbox_probe_uid": native_sandbox_probe_stat.st_uid,
            "tessdata_sha256": observed_tessdata_sha256,
            "shutdown_immutable_inputs_row_sha256": (
                immutable_rows[0]["row_sha256"] if immutable_rows else None
            ),
            "shutdown_immutable_inputs_observed_at_monotonic_ns": (
                ledger_observation["observed_at_monotonic_ns"]
                if ledger_observation is not None
                else None
            ),
            "broker_shutdown_observation_present": bool(immutable_rows),
            "controller_reobserved_at_monotonic_ns": max(
                1, time.monotonic_ns()
            ),
            "worker_and_broker_groups_esrch": True,
        }
        payload = _canonical_payload_bytes(
            {**fields, "record_sha256": _canonical_sha256(fields)}
        )
        self.native_closure_post_sha256 = _write_private_payload(
            self.native_closure_post_path,
            payload,
            maximum_bytes=MAXIMUM_BROKER_LAUNCH_TEMPLATE_BYTES,
        )

    def _sync_capture(self) -> None:
        if self.capture is None:
            return
        capture = self.capture
        self.stdout_observed_size_bytes = capture.counts["stdout"]
        self.stdout_observed_sha256 = capture.sha256("stdout")
        self.stderr_observed_size_bytes = capture.counts["stderr"]
        self.stderr_observed_sha256 = capture.sha256("stderr")
        self.stdout_retained_bytes = capture.bytes("stdout")
        self.stderr_retained_bytes = capture.bytes("stderr")
        self.stream_limit_exceeded = capture.overflow
        self.stream_capture_completed = capture.complete
        if self.broker_capture is not None:
            broker_capture = self.broker_capture
            self.broker_stdout_observed_size_bytes = broker_capture.counts[
                "stdout"
            ]
            self.broker_stdout_observed_sha256 = broker_capture.sha256("stdout")
            self.broker_stderr_observed_size_bytes = broker_capture.counts[
                "stderr"
            ]
            self.broker_stderr_observed_sha256 = broker_capture.sha256("stderr")
            self.broker_stream_limit_exceeded = broker_capture.overflow
            self.broker_stream_capture_completed = broker_capture.complete

    def _pump_for(self, seconds: float) -> None:
        captures = tuple(
            item
            for item in (self.capture, self.broker_capture)
            if item is not None
        )
        if not captures:
            return
        deadline = time.monotonic() + max(0.0, seconds)
        while any(not item.complete for item in captures) and time.monotonic() < deadline:
            for item in captures:
                if item.complete:
                    continue
                first_overflow = item.pump(
                    min(0.005, max(0.0, deadline - time.monotonic()))
                )
                if first_overflow:
                    if item is self.capture:
                        self.stream_limit_exceeded = True
                    else:
                        self.broker_stream_limit_exceeded = True
                    self.kill_managed_groups_immediately()

    def _bounded_reap_direct_worker(self) -> bool:
        if self.process is None:
            return True
        try:
            self.process.wait(timeout=POST_DEADLINE_REAP_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                self.kill_worker_group_immediately()
            except BaseException:
                pass
            try:
                self.process.wait(timeout=POST_DEADLINE_REAP_SECONDS)
            except subprocess.TimeoutExpired:
                return False
        return self.process.returncode is not None

    def _bounded_reap_direct_broker(self) -> bool:
        if self.broker is None:
            return True
        deadline = time.monotonic() + POST_DEADLINE_REAP_SECONDS
        while self.broker.poll() is None and time.monotonic() < deadline:
            if self.broker_capture is not None:
                if self.broker_capture.pump(0.01):
                    self.broker_stream_limit_exceeded = True
                    self.kill_managed_groups_immediately()
            else:
                time.sleep(0.01)
        if self.broker.poll() is None:
            try:
                self.kill_managed_groups_immediately()
            except BaseException:
                pass
            try:
                self.broker.wait(timeout=POST_DEADLINE_REAP_SECONDS)
            except subprocess.TimeoutExpired:
                return False
        self.broker_reaped = self.broker.returncode is not None
        return self.broker_reaped

    def worker_group_state(self) -> str:
        if self.worker_identity is None:
            return "empty" if self.process is None else "unsafe"
        return _frozen_process_group_state(self.worker_identity)

    def worker_group_disappeared(self) -> bool:
        return self.worker_group_state() == "empty"

    def broker_group_state(self) -> str:
        if self.broker_identity is None:
            return "empty" if self.broker is None else "unsafe"
        return _frozen_process_group_state(self.broker_identity)

    def broker_group_disappeared(self) -> bool:
        return self.broker_group_state() == "empty"

    def close_release(self) -> None:
        if self.request_control is not None:
            try:
                self.request_control.close()
            finally:
                self.request_control = None
                self.controller_request_socket = None
        for field in (
            "release_read_fd",
            "release_write_fd",
            "broker_release_read_fd",
            "broker_release_write_fd",
            "broker_ready_read_fd",
            "broker_ready_write_fd",
            "supervisor_ready_read_fd",
            "supervisor_ready_write_fd",
            "request_root_fd",
            "worker_sandbox_report_read_fd",
            "worker_sandbox_report_write_fd",
            "broker_sandbox_report_read_fd",
            "broker_sandbox_report_write_fd",
        ):
            descriptor = getattr(self, field)
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                setattr(self, field, None)

    def finalize_sandbox_probe_authority(self, *, success: bool) -> None:
        authority = self.sandbox_attempt_probe_authority
        self.sandbox_attempt_probe_authority = None
        try:
            if authority is not None:
                if success:
                    self.sandbox_network_terminal = authority.close_terminal()
                else:
                    authority.abort()
                    self.sandbox_network_terminal = None
        finally:
            if self.sandbox_probe_materialization is not None:
                self.sandbox_probe_materialization.close()
                self.sandbox_probe_materialization = None

    def abort_launcher(self) -> None:
        self.finalize_sandbox_probe_authority(success=False)
        if self.launcher_control is not None:
            with contextlib.suppress(BaseException):
                self.launcher_control.request_cleanup(
                    reason="controller_abort"
                )
                self.launcher_control.close()
            self.launcher_control = None
        if self.watchdog is None:
            if self.watchdog_terminal_fd is not None:
                with contextlib.suppress(OSError):
                    os.close(self.watchdog_terminal_fd)
                self.watchdog_terminal_fd = None
            return
        try:
            self.watchdog.wait(timeout=POST_DEADLINE_REAP_SECONDS)
        except subprocess.TimeoutExpired:
            if self.watchdog_identity is not None:
                with contextlib.suppress(BaseException):
                    _signal_frozen_process_group(
                        self.watchdog_identity, signal.SIGKILL
                    )
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.watchdog.wait(timeout=POST_DEADLINE_REAP_SECONDS)
        if self.watchdog_terminal_fd is not None:
            with contextlib.suppress(OSError):
                os.close(self.watchdog_terminal_fd)
            self.watchdog_terminal_fd = None
        for field in (
            "broker_socket",
            "worker_socket",
            "broker_watch_socket",
            "watchdog_broker_socket",
            "worker_phase_socket",
            "watchdog_phase_socket",
            "worker_request_socket",
            "controller_request_socket",
        ):
            value = getattr(self, field)
            if value is not None:
                try:
                    value.close()
                except OSError:
                    pass
                setattr(self, field, None)

    def _request_watchdog_owned_cleanup(self, *, reason: str) -> bool:
        if self.launcher_control is None or not self.launcher_control.committed:
            return False
        worker_live = self.worker_group_state() != "empty"
        broker_live = self.broker_group_state() != "empty"
        self.launcher_control.request_cleanup(reason=reason)
        deadline = time.monotonic() + POST_DEADLINE_REAP_SECONDS
        while time.monotonic() < deadline:
            self._pump_for(0.01)
            worker_done = self.process is None or self.process.poll() is not None
            broker_done = self.broker is None or self.broker.poll() is not None
            if worker_done and broker_done:
                break
        self.broker_reaped = bool(
            self.broker is not None and self.broker.returncode is not None
        )
        self.broker_group_gone = self.broker_group_disappeared()
        return worker_live or broker_live

    def refresh_heartbeat(self) -> None:
        _touch_private_heartbeat(self.heartbeat_path)

    def cleanup_worker_group(self) -> bool:
        self.close_release()
        if self.process is None:
            return False
        if self.launcher_control is not None and self.launcher_control.committed:
            forced = self._request_watchdog_owned_cleanup(
                reason="controller_cleanup"
            )
            self._pump_for(POST_DEADLINE_REAP_SECONDS)
            if self.capture is not None:
                self.capture.close(forced=not self.capture.complete)
            self._sync_capture()
            return forced
        group_state = self.worker_group_state()
        if group_state == "unsafe":
            raise RuntimeError("worker process-group identity drifted before cleanup")
        forced = group_state == "exact"
        if group_state == "exact":
            forced = True
            _signal_frozen_process_group(self.worker_identity, signal.SIGTERM)  # type: ignore[arg-type]
            grace_deadline = time.monotonic() + 0.250
            while time.monotonic() < grace_deadline:
                self.process.poll()
                group_state = self.worker_group_state()
                if group_state == "empty":
                    break
                if group_state == "unsafe":
                    raise RuntimeError(
                        "worker process-group identity drifted during cleanup"
                    )
                if self.capture is not None:
                    self.capture.pump(0.01)
                try:
                    self.refresh_heartbeat()
                except BaseException:
                    pass
            if self.worker_group_state() == "exact":
                _signal_frozen_process_group(
                    self.worker_identity, signal.SIGKILL  # type: ignore[arg-type]
                )
        self._bounded_reap_direct_worker()
        self._pump_for(POST_DEADLINE_REAP_SECONDS)
        if self.capture is not None and not self.capture.complete:
            self.capture.close(forced=True)
        elif self.capture is not None:
            self.capture.close(forced=False)
        self._sync_capture()
        disappearance_deadline = time.monotonic() + POST_DEADLINE_REAP_SECONDS
        while time.monotonic() < disappearance_deadline:
            self.process.poll()
            group_state = self.worker_group_state()
            if group_state == "empty":
                break
            if group_state == "unsafe":
                raise RuntimeError(
                    "worker process-group identity drifted after cleanup"
                )
            time.sleep(0.01)
        return forced

    def cleanup_broker_group(self) -> bool:
        if self.broker is None:
            return False
        if self.launcher_control is not None and self.launcher_control.committed:
            forced = self._request_watchdog_owned_cleanup(
                reason="controller_cleanup"
            )
            self._pump_for(POST_DEADLINE_REAP_SECONDS)
            if self.broker_capture is not None:
                self.broker_capture.close(forced=not self.broker_capture.complete)
            self._sync_capture()
            return forced
        state = self.broker_group_state()
        if state == "unsafe":
            raise RuntimeError("broker process-group identity drifted before cleanup")
        forced = state == "exact"
        if state == "exact":
            _signal_frozen_process_group(
                self.broker_identity, signal.SIGTERM  # type: ignore[arg-type]
            )
            grace_deadline = time.monotonic() + 0.250
            while time.monotonic() < grace_deadline:
                self.broker.poll()
                state = self.broker_group_state()
                if state == "empty":
                    break
                if state == "unsafe":
                    raise RuntimeError(
                        "broker process-group identity drifted during cleanup"
                    )
                self._pump_for(0.01)
            if self.broker_group_state() == "exact":
                _signal_frozen_process_group(
                    self.broker_identity, signal.SIGKILL  # type: ignore[arg-type]
                )
        try:
            self.broker.wait(timeout=POST_DEADLINE_REAP_SECONDS)
        except subprocess.TimeoutExpired:
            return True
        self.broker_reaped = self.broker.returncode is not None
        self._pump_for(POST_DEADLINE_REAP_SECONDS)
        if self.broker_capture is not None:
            self.broker_capture.close(forced=not self.broker_capture.complete)
        self._sync_capture()
        disappearance_deadline = time.monotonic() + POST_DEADLINE_REAP_SECONDS
        while time.monotonic() < disappearance_deadline:
            self.broker.poll()
            state = self.broker_group_state()
            if state == "empty":
                break
            if state == "unsafe":
                raise RuntimeError(
                    "broker process-group identity drifted after cleanup"
                )
            time.sleep(0.01)
        self.broker_group_gone = self.broker_group_disappeared()
        return forced

    def cleanup_managed_groups(self) -> bool:
        self.close_release()
        worker_forced = self.cleanup_worker_group()
        broker_forced = self.cleanup_broker_group()
        return worker_forced or broker_forced

    def kill_worker_group_immediately(self) -> bool:
        self.close_release()
        if self.process is None:
            return False
        if self.launcher_control is not None and self.launcher_control.committed:
            return self._request_watchdog_owned_cleanup(reason="stream_limit")
        if self.worker_identity is None:
            raise RuntimeError("worker identity is unavailable for group kill")
        return _signal_frozen_process_group(
            self.worker_identity, signal.SIGKILL
        )

    def kill_managed_groups_immediately(self) -> bool:
        self.close_release()
        if self.launcher_control is not None and self.launcher_control.committed:
            return self._request_watchdog_owned_cleanup(reason="stream_limit")
        signalled = self.kill_worker_group_immediately()
        if self.broker is not None:
            if self.broker_identity is None:
                raise RuntimeError("broker identity is unavailable for group kill")
            signalled = (
                _signal_frozen_process_group(
                    self.broker_identity, signal.SIGKILL
                )
                or signalled
            )
        return signalled

    def capture_until_exit(self) -> tuple[bytes, bytes]:
        """Drain both worker pipes incrementally under one 4 MiB hard bound."""

        if self.process is None:
            raise RuntimeError("guarded worker launch is incomplete")
        if self.stream_capture_completed:
            return self.stdout_retained_bytes, self.stderr_retained_bytes
        if self.capture is None:
            self.capture = _BoundedPipeCapture(self.process)
        capture = self.capture
        timed_out = False
        forced_drain_deadline_ns: int | None = None
        try:
            post_exit_drain_deadline_ns: int | None = None
            while not capture.complete:
                self.refresh_heartbeat()
                if (
                    self.watchdog is not None
                    and self.watchdog.poll() is not None
                    and self.process.poll() is None
                ):
                    raise RuntimeError(
                        "worker watchdog exited while worker remained live"
                    )
                if self.broker is not None and self.broker.poll() is not None:
                    self.broker_reaped = True
                    if self.process.poll() is None:
                        raise RuntimeError(
                            "Tesseract broker exited while worker remained live"
                        )
                if self.process.poll() is not None:
                    if not self.worker_group_disappeared():
                        self.stream_cleanup_forced = (
                            self.cleanup_managed_groups()
                            or self.stream_cleanup_forced
                        )
                    if post_exit_drain_deadline_ns is None:
                        post_exit_drain_deadline_ns = (
                            time.monotonic_ns()
                            + int(
                                POST_DEADLINE_REAP_SECONDS * 1_000_000_000
                            )
                        )
                remaining_ns = (
                    self.absolute_deadline_monotonic_ns - time.monotonic_ns()
                )
                if remaining_ns <= 0 and not timed_out:
                    timed_out = True
                    self.stream_cleanup_forced = self.cleanup_managed_groups()
                    forced_drain_deadline_ns = (
                        time.monotonic_ns()
                        + int(POST_DEADLINE_REAP_SECONDS * 1_000_000_000)
                    )
                first_overflow = capture.pump(
                    min(
                        WATCHDOG_HEARTBEAT_INTERVAL_SECONDS,
                        max(0.0, remaining_ns / 1_000_000_000),
                    )
                )
                if first_overflow:
                    self.stream_limit_exceeded = True
                    self.stream_cleanup_forced = (
                        self.kill_managed_groups_immediately()
                        or self.stream_cleanup_forced
                    )
                    forced_drain_deadline_ns = (
                        time.monotonic_ns()
                        + int(POST_DEADLINE_REAP_SECONDS * 1_000_000_000)
                    )
                if self.broker_capture is not None and not self.broker_capture.complete:
                    broker_overflow = self.broker_capture.pump(0.0)
                    if broker_overflow:
                        self.broker_stream_limit_exceeded = True
                        self.broker_stream_cleanup_forced = (
                            self.kill_managed_groups_immediately()
                            or self.broker_stream_cleanup_forced
                        )
                        forced_drain_deadline_ns = (
                            time.monotonic_ns()
                            + int(POST_DEADLINE_REAP_SECONDS * 1_000_000_000)
                        )
                if (
                    forced_drain_deadline_ns is not None
                    and time.monotonic_ns() >= forced_drain_deadline_ns
                    and not capture.complete
                ):
                    capture.close(forced=True)
                    break
                if (
                    post_exit_drain_deadline_ns is not None
                    and time.monotonic_ns() >= post_exit_drain_deadline_ns
                    and not capture.complete
                ):
                    capture.close(forced=True)
                    break
            if not self._bounded_reap_direct_worker():
                raise RuntimeError("direct worker child was not reaped")
            if not self._bounded_reap_direct_broker():
                raise RuntimeError("direct broker child was not reaped")
            self._pump_for(POST_DEADLINE_REAP_SECONDS)
            if self.broker_capture is not None:
                self.broker_capture.close(
                    forced=not self.broker_capture.complete
                )
            self.broker_group_gone = self.broker_group_disappeared()
        finally:
            self._sync_capture()
            if capture.complete:
                capture.close(forced=False)
        if timed_out:
            raise subprocess.TimeoutExpired(self.process.args, timeout=0)
        return self.stdout_retained_bytes, self.stderr_retained_bytes

    def collect_watchdog(self) -> ProductionWatchdogTerminalEvidence | None:
        if self.watchdog_terminal_fd is not None:
            try:
                os.close(self.watchdog_terminal_fd)
            except OSError:
                pass
            self.watchdog_terminal_fd = None
        if self.watchdog is None:
            try:
                self.retain_phase_logs()
            except BaseException:
                self.phase_deadline_log_sha256 = None
                self.phase_ack_log_sha256 = None
            self.retain_immutable_input_custody()
            self.finalize_sandbox_probe_authority(success=False)
            return None
        self.close_release()
        try:
            if self.heartbeat_path.exists():
                self.refresh_heartbeat()
        except BaseException:
            pass
        try:
            self.watchdog.wait(timeout=POST_DEADLINE_REAP_SECONDS)
        except subprocess.TimeoutExpired:
            if self.watchdog_identity is None:
                raise RuntimeError("watchdog cleanup identity is unavailable")
            _signal_frozen_process_group(
                self.watchdog_identity, signal.SIGTERM
            )
            try:
                self.watchdog.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                _signal_frozen_process_group(
                    self.watchdog_identity, signal.SIGKILL
                )
                self.watchdog.wait(timeout=POST_DEADLINE_REAP_SECONDS)
        self.watchdog_reaped = self.watchdog.returncode is not None
        self.watchdog_group_gone = bool(
            self.watchdog_identity is not None
            and _frozen_process_group_state(self.watchdog_identity) == "empty"
        )
        # Keep this channel open for the entire watched lifetime so controller
        # death is an immediate custody signal.  Once the watchdog is reaped it
        # is no longer an authority and the controller copy must not leak.
        if self.launcher_control is not None:
            self.launcher_control.close()
            self.launcher_control = None
        # The immutable input interval closes only after the sole-parent
        # launcher has reaped both roots and the watchdog group is gone.
        self.retain_immutable_input_custody()
        try:
            if (
                self.launcher_log_path is None
                or self.worker_identity is None
                or self.worker_launcher_root is None
            ):
                raise ValueError("watchdog launcher terminal custody is unavailable")
            raw = _read_private_payload(
                self.watchdog_terminal_path,
                maximum_bytes=MAXIMUM_PREWARM_WATCHDOG_EVIDENCE_BYTES + 1,
            )
            self.watchdog_terminal_observed_sha256 = hashlib.sha256(raw).hexdigest()
            if not raw:
                raise ValueError("watchdog terminal bytes differ")
            terminal = ProductionWatchdogTerminalEvidence.model_validate_json(raw)
            if canonical_model_bytes(terminal) != raw:
                raise ValueError("watchdog terminal is not canonical")
            expected_roots = (
                {"worker": self.worker_launcher_root}
                if self.broker_launcher_root is None
                else {
                    "broker": self.broker_launcher_root,
                    "worker": self.worker_launcher_root,
                }
            )
            launcher_evidence = _validate_watchdog_launcher_terminal_log(
                path=self.launcher_log_path,
                attempt_id=self.attempt_id,
                expected_roots=expected_roots,
                expected_watchdog_result_record_sha256=(
                    hashlib.sha256(
                        raw[:-1] if raw.endswith(b"\n") else raw
                    ).hexdigest()
                ),
            )
            self.launcher_log_sha256 = launcher_evidence["sha256"]
            self.launcher_log_size_bytes = launcher_evidence["size_bytes"]
            self.launcher_log_row_count = launcher_evidence["row_count"]
            self.launcher_terminal_record_sha256 = launcher_evidence[
                "terminal_record_sha256"
            ]
            self.launcher_root_wait4_record_sha256s = dict(
                launcher_evidence["root_wait4_record_sha256s"]
            )
            self.launcher_root_wait4_log_row_sha256s = dict(
                launcher_evidence["root_wait4_log_row_sha256s"]
            )
            launcher_raw = launcher_evidence["raw"]
            if type(launcher_raw) is not bytes:
                raise ValueError("watchdog launcher raw custody is unavailable")
            self.launcher_terminal_evidence = _launcher_terminal_evidence(
                attempt_id=self.attempt_id,
                raw_log_canonical_jsonl=launcher_raw.decode(
                    "utf-8", errors="strict"
                ),
                log_sha256=launcher_evidence["sha256"],
                log_size_bytes=launcher_evidence["size_bytes"],
                log_row_count=launcher_evidence["row_count"],
                log_device=launcher_evidence["device"],
                log_inode=launcher_evidence["inode"],
                log_mode=launcher_evidence["mode"],
                log_uid=launcher_evidence["uid"],
                log_nlink=launcher_evidence["nlink"],
                controller=launcher_evidence["controller"],
                controller_start_abstime=launcher_evidence[
                    "controller_start_abstime"
                ],
                launcher=launcher_evidence["launcher"],
                worker_root=self.worker_launcher_root,
                broker_root=self.broker_launcher_root,
                watchdog_result_record_sha256=launcher_evidence[
                    "watchdog_result_record_sha256"
                ],
                terminal_record_sha256=launcher_evidence[
                    "terminal_record_sha256"
                ],
                root_returncodes=launcher_evidence["root_returncodes"],
                root_wait4_record_sha256s=launcher_evidence[
                    "root_wait4_record_sha256s"
                ],
                root_wait4_log_row_sha256s=launcher_evidence[
                    "root_wait4_log_row_sha256s"
                ],
            )
            assert self.process is not None
            self.process.returncode = launcher_evidence["root_returncodes"]["worker"]
            if self.broker is not None:
                self.broker.returncode = launcher_evidence["root_returncodes"]["broker"]
            if self.watchdog.returncode != terminal.exit_code:
                raise ValueError("watchdog terminal/exit code differs")
            if not _launcher_terminal_matches_watchdog(
                self.launcher_terminal_evidence, terminal
            ):
                raise ValueError("watchdog launcher/controller identity differs")
            if self.worker_identity is not None and (
                terminal.worker_pid != self.worker_identity.pid
                or terminal.worker_create_time_ns
                != self.worker_identity.create_time_ns
                or terminal.worker_pgid
                != self.worker_identity.process_group_id
                or terminal.worker_sid != self.worker_identity.session_id
            ):
                raise ValueError("watchdog terminal worker identity differs")
            if self.broker_identity is None:
                if terminal.broker_pid is not None:
                    raise ValueError("brokerless launch retained watchdog broker")
            elif (
                terminal.broker_pid != self.broker_identity.pid
                or terminal.broker_create_time_ns
                != self.broker_identity.create_time_ns
                or terminal.broker_pgid
                != self.broker_identity.process_group_id
                or terminal.broker_sid != self.broker_identity.session_id
            ):
                raise ValueError("watchdog terminal broker identity differs")
            self.watchdog_terminal = terminal
            self.watchdog_terminal_sha256 = hashlib.sha256(raw).hexdigest()
            self.validate_child_watch_log()
            self.retain_native_closure_post_observation()
            self.watchdog_terminal_validation_failed = False
        except BaseException:
            self.watchdog_terminal = None
            self.watchdog_terminal_sha256 = None
            self.child_watch_log_validation_failed = bool(
                self.child_watch_log_path is not None
                and self.child_watch_log_path.exists()
            )
            self.watchdog_terminal_validation_failed = bool(
                self.watchdog_terminal_path.exists()
            )
        try:
            self.retain_phase_logs()
        except BaseException:
            self.phase_deadline_log_sha256 = None
            self.phase_ack_log_sha256 = None
        try:
            self.finalize_sandbox_probe_authority(
                success=self.watchdog_terminal is not None
            )
        except BaseException:
            self.watchdog_terminal = None
            self.watchdog_terminal_sha256 = None
            self.watchdog_terminal_validation_failed = True
        return self.watchdog_terminal

    def controller_boundary(self) -> ControllerResourceBoundary:
        return _controller_resource_boundary(self.controller_before)

    def drive_external_request_control(
        self,
        *,
        sources: tuple[SourceIdentity, ...],
        request_timeout_ns: int,
    ) -> tuple[_ExternalRequestCpuBoundary, ...]:
        """Drive every request edge while a controller-only custody pump runs."""

        control = self.request_control
        if (
            control is None
            or len(sources) != control.expected_request_count
            or request_timeout_ns <= 0
            or self.child_watch_log_path is None
            or self.request_resource_sample_path is None
        ):
            raise RuntimeError("external request-control launch binding differs")
        resource_log = _DurableHashChainedLog(
            self.request_resource_sample_path,
            schema_id="phase-latency-controller-resource-sample-row-v1",
            maximum_bytes=REQUEST_RESOURCE_SAMPLE_LOG_MAXIMUM_BYTES,
        )
        stop = threading.Event()
        errors: list[BaseException] = []

        def pump_custody() -> None:
            try:
                while not stop.is_set():
                    if control.closed:
                        return
                    self.refresh_heartbeat()
                    for capture, label in (
                        (self.capture, "worker"),
                        (self.broker_capture, "broker"),
                    ):
                        if capture is not None and not capture.complete:
                            if capture.pump(0.0):
                                raise RuntimeError(
                                    f"{label} output exceeded cap during request control"
                                )
                    if self.process is None or self.process.poll() is not None:
                        raise RuntimeError(
                            "worker exited before request-control closure"
                        )
                    if self.broker is None or self.broker.poll() is not None:
                        raise RuntimeError(
                            "broker exited before request-control closure"
                        )
                    if self.watchdog is None or self.watchdog.poll() is not None:
                        raise RuntimeError(
                            "watchdog exited before request-control closure"
                        )
                    stop.wait(0.025)
            except BaseException as error:
                errors.append(error)
                try:
                    control.socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        thread = threading.Thread(
            target=pump_custody,
            name="lat-us02-controller-request-custody",
            daemon=False,
        )
        thread.start()
        drive_error: BaseException | None = None
        try:
            control.bind_ready()
            framework_thread_baseline = control.framework_thread_baseline
            if framework_thread_baseline is None:
                raise RuntimeError("framework thread baseline is absent")
            for sequence, source in enumerate(sources, start=1):
                binding = _production_request_binding(source)
                sampler = _ControllerOwnedRequestResourceSampler(
                    attempt_id=self.attempt_id,
                    request_id=f"{self.attempt_id}-q{sequence:04d}",
                    request_epoch=sequence + 1,
                    request_sequence=sequence,
                    worker_identity=control.worker_identity,
                    broker_identity=control.broker_identity,
                    framework_thread_baseline=framework_thread_baseline,
                    child_watch_log_path=self.child_watch_log_path,
                    durable_log=resource_log,
                    fatal_callback=lambda: control.socket.shutdown(
                        socket.SHUT_RDWR
                    ),
                )
                sampler.start()
                boundary: _ExternalRequestCpuBoundary | None = None
                try:
                    boundary = control.run_request(
                        request_sequence=sequence,
                        expected_source=source,
                        binding=binding,
                        request_timeout_ns=request_timeout_ns,
                        resource_sampler=sampler,
                    )
                finally:
                    resource_window = sampler.finish()
                if boundary is None:
                    raise RuntimeError("request-control boundary disappeared")
                completed_boundary = replace(
                    boundary, resource_window=resource_window
                )
                control.boundaries[-1] = completed_boundary
            control.finish()
        except BaseException as error:
            drive_error = error
        finally:
            stop.set()
            thread.join(timeout=2.0)
            resource_log.close()
            if thread.is_alive():
                drive_error = RuntimeError(
                    "controller request custody pump did not stop"
                )
        if errors and drive_error is None:
            drive_error = RuntimeError("controller request custody pump failed")
        if drive_error is not None:
            try:
                control.retain_terminal_failure(
                    failure_code=(
                        "controller_custody_failure"
                        if errors
                        else "peer_protocol_or_eof_failure"
                    ),
                    stage=(
                        "ready"
                        if control.ready_record is None
                        else (
                            "close"
                            if len(control.boundaries)
                            == control.expected_request_count
                            else "request"
                        )
                    ),
                )
            except BaseException as terminal_error:
                drive_error = terminal_error
            control.close()
        self.external_request_boundaries = tuple(control.boundaries)
        if (
            self.request_control_path is None
            or self.request_cpu_sample_path is None
        ):
            raise RuntimeError("request-control retained paths disappeared")
        transcript = control.transcript.validate_retained()
        retained_transcript, transcript_stat = (
            _read_private_payload_with_identity(
                self.request_control_path,
                maximum_bytes=REQUEST_CONTROL_TRANSCRIPT_MAXIMUM_BYTES,
            )
        )
        if retained_transcript != transcript:
            raise RuntimeError("request-control terminal reread differs")
        terminal_transcript = terminal_request_control_transcript_evidence(
            retained_transcript,
            file_device=transcript_stat.st_dev,
            file_inode=transcript_stat.st_ino,
            file_uid=transcript_stat.st_uid,
        )
        if terminal_transcript.outcome != "success":
            if drive_error is None:
                raise RuntimeError(
                    "request-control transcript did not close successfully"
                )
        self.request_control_transcript_sha256 = hashlib.sha256(
            transcript
        ).hexdigest()
        self.request_control_terminal_transcript = terminal_transcript
        if drive_error is not None:
            raise RuntimeError("external request control failed") from drive_error
        cpu_samples = control.cpu_samples.validate_retained()
        resource_samples = resource_log.validate_retained()
        self.request_cpu_sample_log_sha256 = hashlib.sha256(
            cpu_samples
        ).hexdigest()
        self.request_resource_sample_log_sha256 = hashlib.sha256(
            resource_samples
        ).hexdigest()
        self.request_resource_sample_log_row_count = resource_log.sequence
        self.request_resource_sample_log_size_bytes = len(resource_samples)
        return self.external_request_boundaries


@_with_preintent_launcher_cleanup
def _guarded_worker_launch(
    *,
    attempt_id: str,
    workspace: Path,
    output_directory: Path,
    protocol: Path,
    environment: dict[str, str],
    base_command: tuple[str, ...],
    attempt_budget_ns: int,
    startup_timeout_ns: int,
    brokered: BrokeredLaunchInputs | None = None,
    request_count: int | None = None,
    commit_worker_configuration: Callable[[dict[str, str]], None] | None = None,
) -> _GuardedWorkerLaunch:
    if (
        attempt_budget_ns <= 0
        or attempt_budget_ns > MAXIMUM_ATTEMPT_RUNTIME_NS
        or startup_timeout_ns <= 0
        or startup_timeout_ns > attempt_budget_ns
        or (brokered is not None and (request_count is None or request_count <= 0))
        or (brokered is None and request_count is not None)
        or ((brokered is None) != (commit_worker_configuration is None))
    ):
        raise ValueError("guarded worker attempt budget differs")
    before = _controller_resource_sample()
    controller = before.identity
    from app.services.tesseract_broker_native import raw_process_start_abstime

    controller_start_abstime = raw_process_start_abstime(controller.pid)
    deadline = time.monotonic_ns() + attempt_budget_ns
    intent_path = output_directory / f"{attempt_id}-launch-intent.json"
    launch_path = output_directory / f"{attempt_id}-launch-record.json"
    launch_failure_path = (
        output_directory / f"{attempt_id}-launch-failure.json"
    )
    heartbeat_path = protocol / "watchdog-heartbeat"
    watchdog_ready_path = protocol / "watchdog-ready"
    watchdog_terminal_path = (
        output_directory / f"{attempt_id}-watchdog-terminal.json"
    )
    prebind_fatal_path = (
        brokered.worker_scratch_root / "prebind-fatal.json"
        if brokered is not None
        else output_directory / f"{attempt_id}-worker-prebind-fatal.json"
    )
    # Both topologies retain the authoritative phase grammar outside the
    # disposable protocol directory so terminal-manifest replay cannot be
    # defeated by cleanup of controller coordination state.
    phase_control_path = output_directory / f"{attempt_id}-phase-deadlines.jsonl"
    phase_ack_path = output_directory / f"{attempt_id}-phase-acks.jsonl"
    watchdog_path_root = Path(
        os.path.commonpath(
            (
                str(output_directory.resolve(strict=True)),
                str(protocol.resolve(strict=True)),
            )
        )
    ).resolve(strict=True)
    if watchdog_path_root == Path(watchdog_path_root.anchor):
        raise ValueError("watchdog path root is unbounded")
    worker_phase_socket: socket.socket | None = None
    watchdog_phase_socket: socket.socket | None = None
    worker_request_socket: socket.socket | None = None
    controller_request_socket: socket.socket | None = None
    release_read_fd: int | None = None
    release_write_fd: int | None = None
    target_command: tuple[str, ...] = ()
    command: tuple[str, ...] = ()
    broker_command: tuple[str, ...] | None = None
    broker_environment: dict[str, str] | None = None
    broker_template_bytes: bytes | None = None
    broker_template_sha256: str | None = None
    broker_config_path: Path | None = None
    broker_ready_path: Path | None = None
    supervisor_ready_path: Path | None = None
    child_watch_log_path: Path | None = None
    request_control_path: Path | None = None
    request_cpu_sample_path: Path | None = None
    request_resource_sample_path: Path | None = None
    native_closure_post_path: Path | None = None
    broker_attempt_nonce: str | None = None
    broker_scope_sha256: str | None = None
    watchdog_protocol_sha256: str | None = None
    native_closure: dict[str, Any] | None = None
    native_closure_identity: str | None = None
    native_fork_probe_path: Path | None = None
    native_fork_probe_identity: dict[str, object] | None = None
    native_fork_probe_source_sha256: str | None = None
    native_spawn_guard_path: Path | None = None
    native_spawn_guard_identity: dict[str, object] | None = None
    native_spawn_guard_source_path: Path | None = None
    native_spawn_guard_source_sha256: str | None = None
    native_runtime_gate_source_path: Path | None = None
    native_runtime_gate_source_identity: dict[str, object] | None = None
    native_runtime_gate_library_path: Path | None = None
    native_runtime_gate_library_identity: dict[str, object] | None = None
    native_sandbox_probe_path: Path | None = None
    native_sandbox_probe_identity: dict[str, object] | None = None
    native_sandbox_probe_source_path: Path | None = None
    native_sandbox_probe_source_sha256: str | None = None
    sandbox_probe_materialization: SandboxProbeMaterialization | None = None
    sandbox_attempt_probe_authority: SandboxAttemptProbeAuthority | None = None
    guard_python_identity: dict[str, Any] | None = None
    guard_python_path_custody: dict[str, Any] | None = None
    guard_python_native_closure: dict[str, Any] | None = None
    guard_python_module_tree_custody: dict[str, Any] | None = None
    broker_worker_socket_identity: tuple[int, int] | None = None
    broker_watch_socket_identity: tuple[int, int] | None = None
    worker_request_socket_identity: tuple[int, int] | None = None
    worker_profile: str | None = None
    broker_profile: str | None = None
    broker_release_read_fd: int | None = None
    broker_release_write_fd: int | None = None
    broker_ready_read_fd: int | None = None
    broker_ready_write_fd: int | None = None
    supervisor_ready_read_fd: int | None = None
    supervisor_ready_write_fd: int | None = None
    broker_socket: socket.socket | None = None
    worker_socket: socket.socket | None = None
    broker_watch_socket: socket.socket | None = None
    watchdog_broker_socket: socket.socket | None = None
    request_root_fd: int | None = None
    worker_sandbox_report_read_fd: int | None = None
    worker_sandbox_report_write_fd: int | None = None
    broker_sandbox_report_read_fd: int | None = None
    broker_sandbox_report_write_fd: int | None = None
    preintent_previous_signal_mask: set[signal.Signals] | None = None
    preintent_resources_closed = False

    def restore_preintent_signal_mask() -> None:
        nonlocal preintent_previous_signal_mask
        if preintent_previous_signal_mask is None:
            return
        previous = preintent_previous_signal_mask
        preintent_previous_signal_mask = None
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)

    def close_controller_prelaunch_descriptors() -> None:
        nonlocal release_read_fd
        nonlocal release_write_fd
        nonlocal broker_release_read_fd
        nonlocal broker_release_write_fd
        nonlocal broker_ready_read_fd
        nonlocal broker_ready_write_fd
        nonlocal supervisor_ready_read_fd
        nonlocal supervisor_ready_write_fd
        nonlocal request_root_fd
        nonlocal worker_phase_socket
        nonlocal watchdog_phase_socket
        nonlocal worker_request_socket
        nonlocal controller_request_socket
        nonlocal broker_socket
        nonlocal worker_socket
        nonlocal broker_watch_socket
        nonlocal watchdog_broker_socket
        nonlocal sandbox_probe_materialization
        nonlocal sandbox_attempt_probe_authority
        nonlocal worker_sandbox_report_read_fd
        nonlocal worker_sandbox_report_write_fd
        nonlocal broker_sandbox_report_read_fd
        nonlocal broker_sandbox_report_write_fd
        nonlocal preintent_resources_closed
        if preintent_resources_closed:
            return
        preintent_resources_closed = True
        descriptors = (
            release_read_fd,
            release_write_fd,
            broker_release_read_fd,
            broker_release_write_fd,
            broker_ready_read_fd,
            broker_ready_write_fd,
            supervisor_ready_read_fd,
            supervisor_ready_write_fd,
            request_root_fd,
            worker_sandbox_report_read_fd,
            worker_sandbox_report_write_fd,
            broker_sandbox_report_read_fd,
            broker_sandbox_report_write_fd,
        )
        release_read_fd = None
        release_write_fd = None
        broker_release_read_fd = None
        broker_release_write_fd = None
        broker_ready_read_fd = None
        broker_ready_write_fd = None
        supervisor_ready_read_fd = None
        supervisor_ready_write_fd = None
        request_root_fd = None
        worker_sandbox_report_read_fd = None
        worker_sandbox_report_write_fd = None
        broker_sandbox_report_read_fd = None
        broker_sandbox_report_write_fd = None
        endpoints = (
            worker_phase_socket,
            watchdog_phase_socket,
            worker_request_socket,
            controller_request_socket,
            broker_socket,
            worker_socket,
            broker_watch_socket,
            watchdog_broker_socket,
        )
        worker_phase_socket = None
        watchdog_phase_socket = None
        worker_request_socket = None
        controller_request_socket = None
        broker_socket = None
        worker_socket = None
        broker_watch_socket = None
        watchdog_broker_socket = None
        materialization = sandbox_probe_materialization
        sandbox_probe_materialization = None
        attempt_probe_authority = sandbox_attempt_probe_authority
        sandbox_attempt_probe_authority = None
        for descriptor in descriptors:
            if descriptor is not None:
                with contextlib.suppress(OSError):
                    os.close(descriptor)
        for endpoint in endpoints:
            if endpoint is not None:
                with contextlib.suppress(OSError):
                    endpoint.close()
        if attempt_probe_authority is not None:
            attempt_probe_authority.abort()
        if materialization is not None:
            materialization.close()
        restore_preintent_signal_mask()

    def handoff_prelaunch_resources_to_launch(
        launch: _GuardedWorkerLaunch,
    ) -> Callable[[], None]:
        nonlocal release_read_fd
        nonlocal release_write_fd
        nonlocal broker_release_read_fd
        nonlocal broker_release_write_fd
        nonlocal broker_ready_read_fd
        nonlocal broker_ready_write_fd
        nonlocal supervisor_ready_read_fd
        nonlocal supervisor_ready_write_fd
        nonlocal request_root_fd
        nonlocal worker_phase_socket
        nonlocal watchdog_phase_socket
        nonlocal worker_request_socket
        nonlocal controller_request_socket
        nonlocal broker_socket
        nonlocal worker_socket
        nonlocal broker_watch_socket
        nonlocal watchdog_broker_socket
        nonlocal sandbox_probe_materialization
        nonlocal sandbox_attempt_probe_authority
        nonlocal worker_sandbox_report_read_fd
        nonlocal worker_sandbox_report_write_fd
        nonlocal broker_sandbox_report_read_fd
        nonlocal broker_sandbox_report_write_fd
        nonlocal preintent_resources_closed
        thread_id = threading.get_ident()
        pending_cleanup = _PENDING_PREINTENT_RESOURCE_CLEANUPS.get(thread_id)
        pending_launcher = _PENDING_PREINTENT_LAUNCHERS.get(thread_id)
        if (
            preintent_resources_closed
            or pending_cleanup is not close_controller_prelaunch_descriptors
            or pending_launcher is None
            or pending_launcher.additional_cleanup
            is not close_controller_prelaunch_descriptors
        ):
            raise RuntimeError("pre-intent resource handoff differs")

        def cleanup_launch_resources() -> None:
            launch.close_release()
            launch.finalize_sandbox_probe_authority(success=False)
            custody = launch.immutable_input_custody
            if custody is not None:
                launch.immutable_input_custody = None
                custody.abort()
                launch.immutable_input_custody_validation_failed = True
            restore_preintent_signal_mask()

        _PENDING_PREINTENT_RESOURCE_CLEANUPS[thread_id] = (
            cleanup_launch_resources
        )
        pending_launcher.additional_cleanup = cleanup_launch_resources
        preintent_resources_closed = True
        release_read_fd = None
        release_write_fd = None
        broker_release_read_fd = None
        broker_release_write_fd = None
        broker_ready_read_fd = None
        broker_ready_write_fd = None
        supervisor_ready_read_fd = None
        supervisor_ready_write_fd = None
        request_root_fd = None
        worker_sandbox_report_read_fd = None
        worker_sandbox_report_write_fd = None
        broker_sandbox_report_read_fd = None
        broker_sandbox_report_write_fd = None
        worker_phase_socket = None
        watchdog_phase_socket = None
        worker_request_socket = None
        controller_request_socket = None
        broker_socket = None
        worker_socket = None
        broker_watch_socket = None
        watchdog_broker_socket = None
        sandbox_probe_materialization = None
        sandbox_attempt_probe_authority = None
        return cleanup_launch_resources

    _register_pending_preintent_resource_cleanup(
        close_controller_prelaunch_descriptors
    )
    if brokered is not None:
        worker_phase_socket, watchdog_phase_socket = socket.socketpair(
            socket.AF_UNIX, socket.SOCK_STREAM
        )
        worker_request_socket, controller_request_socket = socket.socketpair(
            socket.AF_UNIX, socket.SOCK_STREAM
        )
    release_read_fd, release_write_fd = os.pipe()
    phase_target_arguments = (
        ()
        if worker_phase_socket is not None
        else (
            "--phase-control",
            str(phase_control_path),
            "--phase-ack",
            str(phase_ack_path),
        )
    )
    target_command = (
        *base_command,
        "--attempt-id",
        attempt_id,
        "--controller-pid",
        str(controller.pid),
        "--controller-create-time-ns",
        str(controller.create_time_ns),
        "--controller-pgid",
        str(controller.process_group_id),
        "--controller-sid",
        str(controller.session_id),
        "--absolute-deadline-monotonic-ns",
        str(deadline),
        "--controller-release-fd",
        str(release_read_fd),
        "--prebind-fatal",
        str(prebind_fatal_path),
        *phase_target_arguments,
    )
    command = target_command

    if brokered is not None:
        if base_command[:3] != (
            sys.executable,
            "-m",
            "tests.benchmarks.latency_prewarm_production_worker",
        ):
            raise ValueError("brokered worker target command differs")
        request_root = brokered.request_root.resolve(strict=True)
        if request_root.parent != protocol.resolve():
            raise ValueError("broker request root escaped private protocol custody")
        worker_scratch_root = brokered.worker_scratch_root.resolve(strict=True)
        if (
            worker_scratch_root != request_root
            or not stat.S_ISDIR(worker_scratch_root.lstat().st_mode)
            or stat.S_IMODE(worker_scratch_root.lstat().st_mode) != 0o700
            or worker_scratch_root.lstat().st_uid != os.geteuid()
        ):
            raise ValueError("worker scratch root custody differs")
        source_executable = brokered.tesseract_executable.resolve(strict=True)
        source_executable_stat = source_executable.lstat()
        staged_executable_root = brokered.staged_executable_root.resolve(
            strict=True
        )
        if (
            staged_executable_root.parent != protocol.resolve()
            or staged_executable_root == request_root
            or not stat.S_ISDIR(staged_executable_root.lstat().st_mode)
            or stat.S_IMODE(staged_executable_root.lstat().st_mode) != 0o700
            or staged_executable_root.lstat().st_uid != os.geteuid()
        ):
            raise ValueError("staged executable root custody differs")
        staged_executable = staged_executable_root / "tesseract-executable"
        staged_executable_identity = _stage_private_executable(
            source=source_executable,
            target=staged_executable,
        )
        (
            native_fork_probe_path,
            native_fork_probe_identity,
            native_fork_probe_source_sha256,
        ) = _build_and_stage_native_fork_probe(
            workspace=workspace,
            target_root=staged_executable_root,
        )
        (
            native_spawn_guard_path,
            native_spawn_guard_identity,
            native_spawn_guard_source_path,
            native_spawn_guard_source_sha256,
        ) = _build_and_stage_native_spawn_guard(
            workspace=workspace,
            target_root=staged_executable_root,
        )
        (
            native_runtime_gate_source_path,
            native_runtime_gate_source_identity,
            native_runtime_gate_library_path,
            native_runtime_gate_library_identity,
        ) = _build_and_stage_native_runtime_gate(
            workspace=workspace,
            target_root=staged_executable_root,
        )
        (
            native_sandbox_probe_path,
            native_sandbox_probe_identity,
            native_sandbox_probe_source_path,
            native_sandbox_probe_source_sha256,
        ) = _build_and_stage_native_sandbox_probe(
            workspace=workspace,
            target_root=staged_executable_root,
        )
        from app.services.tesseract_native_closure import (
            derive_native_closure,
            native_closure_sha256,
            validate_native_closure,
        )

        native_closure = derive_native_closure(
            str(source_executable),
            str(staged_executable),
            runtime_gate_source_path=str(native_runtime_gate_source_path),
            runtime_gate_library_path=str(native_runtime_gate_library_path),
        )
        native_closure = validate_native_closure(
            native_closure, reobserve=True
        )
        native_closure_identity = native_closure_sha256(native_closure)
        if (
            native_closure.get("closure_sha256")
            != native_closure_identity
            or native_closure.get("trust_model")
            != "frozen-native-closure-trusted-v1"
            or native_closure.get("containment_claim")
            != "none-trusted-pinned-native-computation"
        ):
            raise ValueError("native Tesseract closure custody differs")
        runtime_gate = native_closure.get("runtime_gate")
        if (
            type(runtime_gate) is not dict
            or any(
                runtime_gate.get(kind, {}).get(name) != identity[name]
                for kind, identity in (
                    ("source", native_runtime_gate_source_identity),
                    ("library", native_runtime_gate_library_identity),
                )
                for name in identity
            )
        ):
            raise ValueError("native runtime gate closure identity differs")
        from app.services.tesseract_broker import (
            derive_guard_python_module_tree_custody,
            derive_guard_python_path_custody,
        )

        guard_python_path = Path(
            "/Library/Developer/CommandLineTools/Library/Frameworks/"
            "Python3.framework/Versions/3.9/bin/python3.9"
        ).resolve(strict=True)
        guard_python_identity = _root_owned_executable_identity(
            guard_python_path
        )
        guard_python_path_custody = derive_guard_python_path_custody(
            str(guard_python_path)
        )
        guard_python_native_closure = validate_native_closure(
            derive_native_closure(
                str(guard_python_path), str(guard_python_path)
            ),
            reobserve=True,
        )
        guard_python_module_tree_custody = (
            derive_guard_python_module_tree_custody(
                str(guard_python_path.parents[1])
            )
        )
        artifact_probe_source = select_bounded_probe_source(
            brokered.immutable_artifact_root.resolve(strict=True)
        )
        tessdata_probe_source = (
            brokered.tesseract_data_path.resolve(strict=True)
            / f"{brokered.allowed_languages[0]}.traineddata"
        ).resolve(strict=True)
        sandbox_probe_materialization = materialize_sandbox_probe_roots(
            base_root=protocol.resolve(strict=True),
            artifact_source=artifact_probe_source,
            tessdata_source=tessdata_probe_source,
            staged_executable_source=staged_executable.resolve(strict=True),
            input_source=native_sandbox_probe_source_path.resolve(strict=True),
        )
        sandbox_probe_materialization.run_dac_positive_controls(
            control_nonce=secrets.token_bytes(32)
        )
        sandbox_probe_materialization.verify_restored()
        input_probe_root = sandbox_probe_materialization.roots[
            "input_probe_root"
        ]
        network_trap_root = sandbox_probe_materialization.roots[
            "network_trap_root"
        ]
        artifact_probe_clone_root = sandbox_probe_materialization.roots[
            "artifact_probe_clone"
        ]
        tessdata_probe_clone_root = sandbox_probe_materialization.roots[
            "tessdata_probe_clone"
        ]
        staged_executable_probe_clone_root = (
            sandbox_probe_materialization.roots[
                "staged_executable_probe_clone"
            ]
        )
        worker_profile = _production_seatbelt_profile(
            artifact_root=brokered.immutable_artifact_root,
            tessdata_root=brokered.tesseract_data_path,
            request_root=request_root,
            input_probe_root=input_probe_root,
            network_trap_root=network_trap_root,
            artifact_probe_clone_root=artifact_probe_clone_root,
            tessdata_probe_clone_root=tessdata_probe_clone_root,
            staged_executable_probe_clone_root=(
                staged_executable_probe_clone_root
            ),
            worker_scratch_root=brokered.worker_scratch_root,
            immutable_executable=staged_executable,
            deny_process_fork=True,
        )
        broker_profile = _production_seatbelt_profile(
            artifact_root=brokered.immutable_artifact_root,
            tessdata_root=brokered.tesseract_data_path,
            request_root=request_root,
            input_probe_root=input_probe_root,
            network_trap_root=network_trap_root,
            artifact_probe_clone_root=artifact_probe_clone_root,
            tessdata_probe_clone_root=tessdata_probe_clone_root,
            staged_executable_probe_clone_root=(
                staged_executable_probe_clone_root
            ),
            worker_scratch_root=None,
            immutable_executable=staged_executable,
            deny_process_fork=False,
            deny_all_file_writes=True,
        )
        broker_attempt_nonce = secrets.token_hex(32)
        watchdog_protocol_path = Path(__file__).with_name(
            "latency_prewarm_watchdog.py"
        ).resolve(strict=True)
        watchdog_protocol_sha256 = _sha256_file(watchdog_protocol_path)
        child_wrapper = brokered.child_wrapper_path.resolve(strict=True)
        tessdata = brokered.tesseract_data_path.resolve(strict=True)
        tessdata_records, _tessdata_bytes = _tree_content_records(
            tessdata, allow_empty=True
        )
        tessdata_sha256 = _content_records_sha256(tessdata_records)
        if raw_process_start_abstime(controller.pid) != controller_start_abstime:
            raise RuntimeError("logical controller start identity drifted")
        child_watch_log_path = (
            output_directory.resolve(strict=True)
            / f"{attempt_id}-child-watch.jsonl"
        )
        request_control_path = (
            output_directory.resolve(strict=True)
            / f"{attempt_id}-request-control.jsonl"
        )
        request_cpu_sample_path = (
            output_directory.resolve(strict=True)
            / f"{attempt_id}-external-cpu-samples.jsonl"
        )
        request_resource_sample_path = (
            output_directory.resolve(strict=True)
            / f"{attempt_id}-controller-resource-samples.jsonl"
        )
        native_closure_post_path = (
            output_directory.resolve(strict=True)
            / f"{attempt_id}-native-closure-post.json"
        )
        if any(
            path.exists()
            for path in (
                child_watch_log_path,
                request_control_path,
                request_cpu_sample_path,
                request_resource_sample_path,
                native_closure_post_path,
            )
        ):
            raise FileExistsError("brokered controller ledger path existed before launch")
        broker_scope_sha256 = _canonical_sha256(
            {
                "attempt_id": attempt_id,
                "controller_pid": controller.pid,
                "controller_start_abstime": controller_start_abstime,
                "target_command": list(target_command),
                "worker_profile_sha256": hashlib.sha256(
                    worker_profile.encode("ascii")
                ).hexdigest(),
                "broker_profile_sha256": hashlib.sha256(
                    broker_profile.encode("ascii")
                ).hexdigest(),
                "native_closure_sha256": native_closure_identity,
            }
        )
        nonce_sha256 = hashlib.sha256(
            broker_attempt_nonce.encode("ascii")
        ).hexdigest()
        request_root_fd = os.open(
            request_root,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        sandbox_attempt_probe_authority = SandboxAttemptProbeAuthority.open(
            materialization=sandbox_probe_materialization,
            attempt_id=attempt_id,
            attempt_nonce_sha256=nonce_sha256,
            scope_sha256=broker_scope_sha256,
            worker_profile_sha256=hashlib.sha256(
                worker_profile.encode("ascii")
            ).hexdigest(),
            broker_profile_sha256=hashlib.sha256(
                broker_profile.encode("ascii")
            ).hexdigest(),
            native_closure_sha256=native_closure_identity,
            artifact_read_path=artifact_probe_source,
            tessdata_read_path=tessdata_probe_source,
            staged_executable_read_path=staged_executable,
            worker_scratch_root=worker_scratch_root,
            worker_scratch_fd=request_root_fd,
            probe_library_path=native_sandbox_probe_path,
            probe_library_sha256=str(native_sandbox_probe_identity["sha256"]),
            control_nonce=secrets.token_bytes(32),
        )
        (
            worker_sandbox_report_read_fd,
            worker_sandbox_report_write_fd,
        ) = os.pipe()
        (
            broker_sandbox_report_read_fd,
            broker_sandbox_report_write_fd,
        ) = os.pipe()
        preintent_previous_signal_mask = signal.pthread_sigmask(
            signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGHUP}
        )
        try:
            (
                watchdog_process,
                watchdog_identity,
                launcher_control,
                launcher_identity,
                launcher_log_path,
                watchdog_terminal_fd,
            ) = _start_watchdog_owned_launcher(
                    attempt_id=attempt_id,
                    workspace=workspace,
                    output_directory=output_directory,
                    controller=controller,
                    controller_start_abstime=controller_start_abstime,
                    absolute_deadline_monotonic_ns=deadline,
                    startup_timeout_ns=startup_timeout_ns,
                    heartbeat_root=watchdog_path_root,
                    heartbeat_path=heartbeat_path.resolve(),
                    ready_path=watchdog_ready_path.resolve(),
                    terminal_path=watchdog_terminal_path.resolve(),
                    phase_control_path=phase_control_path.resolve(),
                    phase_ack_path=phase_ack_path.resolve(),
                    child_watch_log_path=child_watch_log_path,
                    attempt_nonce_sha256=nonce_sha256,
                    scope_sha256=broker_scope_sha256,
                    watchdog_protocol_sha256=watchdog_protocol_sha256,
                    native_closure_sha256=native_closure_identity,
                additional_cleanup=close_controller_prelaunch_descriptors,
            )
        except BaseException:
            close_controller_prelaunch_descriptors()
            raise
        from app.services.tesseract_broker_protocol import (
            MAX_REQUEST_RECEIPT_CHILDREN,
            MAX_RUN_INPUT_BYTES,
            MAX_RUN_STDOUT_BYTES,
            MAX_STDERR_BYTES,
        )

        broker_template = {
            "schema_id": "parser-tesseract-broker-launch-template-v1",
            "attempt_nonce": broker_attempt_nonce,
            "scope_sha256": broker_scope_sha256,
            "attempt_deadline_monotonic_ns": deadline,
            "controller": {
                "pid": controller.pid,
                "start_abstime": controller_start_abstime,
            },
            "launcher": dict(launcher_identity),
            "source_executable": {
                "resolved_path": str(source_executable),
                "sha256": _sha256_file(source_executable),
                "device": source_executable_stat.st_dev,
                "inode": source_executable_stat.st_ino,
                "mode": source_executable_stat.st_mode,
                "uid": source_executable_stat.st_uid,
                "nlink": source_executable_stat.st_nlink,
                "size": source_executable_stat.st_size,
            },
            "executable": staged_executable_identity,
            "native_spawn_guard": native_spawn_guard_identity,
            "native_spawn_guard_source_sha256": (
                native_spawn_guard_source_sha256
            ),
            "native_closure": native_closure,
            "broker_sandbox_probe_plan": dict(
                sandbox_attempt_probe_authority.broker_plan
            ),
            "child_sandbox_probe_executor": {
                "authority": (
                    "embedded-clt-python39-native-ctypes-seatbelt-probe-v1"
                ),
                "source_hex": (
                    sandbox_attempt_probe_authority.child_executor_source_hex
                ),
                "source_sha256": (
                    sandbox_attempt_probe_authority.child_executor_source_sha256
                ),
            },
            "child_sandbox_probe_plan": dict(
                sandbox_attempt_probe_authority.child_plan
            ),
            "guard_python": guard_python_identity,
            "guard_python_path_custody": guard_python_path_custody,
            "guard_python_native_closure": guard_python_native_closure,
            "guard_python_module_tree_custody": (
                guard_python_module_tree_custody
            ),
            "tessdata": {
                "resolved_root": str(tessdata),
                "tree_sha256": tessdata_sha256,
            },
            "allowed_languages": list(brokered.allowed_languages),
            "request_root": _filesystem_identity(request_root),
            "ledger": {"maximum_bytes": 4_194_304},
            "broker_profile_sha256": hashlib.sha256(
                broker_profile.encode("ascii")
            ).hexdigest(),
            "child_wrapper_sha256": _sha256_file(child_wrapper),
            "watchdog_protocol_sha256": watchdog_protocol_sha256,
            "limits": {
                "max_input_bytes": MAX_RUN_INPUT_BYTES,
                "max_stdout_bytes": MAX_RUN_STDOUT_BYTES,
                "max_stderr_bytes": MAX_STDERR_BYTES,
                "max_jobs_per_phase": MAX_REQUEST_RECEIPT_CHILDREN,
            },
        }
        from app.services.tesseract_broker import BrokerLaunchConfig

        template_smoke = BrokerLaunchConfig(broker_template)
        try:
            if template_smoke.mapping != broker_template:
                raise RuntimeError("broker launch template smoke mapping differs")
        finally:
            os.close(template_smoke.request_root_fd)
        broker_template_bytes = _broker_launch_template_bytes(
            broker_template
        )
        broker_template_sha256 = hashlib.sha256(
            broker_template_bytes
        ).hexdigest()
        broker_config_path = (
            output_directory / f"{attempt_id}-broker-launch-template.json"
        )
        broker_ready_path = output_directory / f"{attempt_id}-broker-ready.json"
        supervisor_ready_path = (
            output_directory / f"{attempt_id}-supervisor-ready.json"
        )
        broker_socket, worker_socket = socket.socketpair(
            socket.AF_UNIX, socket.SOCK_STREAM
        )
        broker_watch_socket, watchdog_broker_socket = socket.socketpair(
            socket.AF_UNIX, socket.SOCK_STREAM
        )
        assert worker_request_socket is not None
        broker_worker_stat = os.fstat(broker_socket.fileno())
        broker_watch_stat = os.fstat(broker_watch_socket.fileno())
        worker_request_stat = os.fstat(worker_request_socket.fileno())
        broker_worker_socket_identity = (
            broker_worker_stat.st_dev,
            broker_worker_stat.st_ino,
        )
        broker_watch_socket_identity = (
            broker_watch_stat.st_dev,
            broker_watch_stat.st_ino,
        )
        worker_request_socket_identity = (
            worker_request_stat.st_dev,
            worker_request_stat.st_ino,
        )
        broker_release_read_fd, broker_release_write_fd = os.pipe()
        broker_ready_read_fd, broker_ready_write_fd = os.pipe()
        supervisor_ready_read_fd, supervisor_ready_write_fd = os.pipe()
        broker_environment = sanitized_watchdog_environment()
        for name in ("TMPDIR", "TMP", "TEMP"):
            broker_environment[name] = str(request_root)
        broker_command = _sandboxed_exact_profile_command(
            (
                sys.executable,
                "-m",
                "app.services.tesseract_broker",
                "--capability-fd",
                str(broker_socket.fileno()),
                "--ready-fd",
                str(broker_ready_write_fd),
                "--release-fd",
                str(broker_release_read_fd),
                "--watchdog-fd",
                str(broker_watch_socket.fileno()),
                "--sandbox-probe-report-fd",
                str(broker_sandbox_report_write_fd),
                "--config-json",
                str(broker_config_path),
                "--config-sha256",
                broker_template_sha256,
            ),
            broker_profile,
        )
        command = _sandboxed_exact_profile_command(
            (
                sys.executable,
                "-m",
                "app.services.parser_worker_supervisor",
                "--ready-fd",
                str(supervisor_ready_write_fd),
                "--sandbox-probe-report-fd",
                str(worker_sandbox_report_write_fd),
                "--target-module",
                "tests.benchmarks.latency_prewarm_production_worker",
                "--",
                *target_command[3:],
            ),
            worker_profile,
        )
    if brokered is None:
        preintent_previous_signal_mask = signal.pthread_sigmask(
            signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGHUP}
        )
        try:
            (
                watchdog_process,
                watchdog_identity,
                launcher_control,
                launcher_identity,
                launcher_log_path,
                watchdog_terminal_fd,
            ) = _start_watchdog_owned_launcher(
                    attempt_id=attempt_id,
                    workspace=workspace,
                    output_directory=output_directory,
                    controller=controller,
                    controller_start_abstime=controller_start_abstime,
                    absolute_deadline_monotonic_ns=deadline,
                    startup_timeout_ns=startup_timeout_ns,
                    heartbeat_root=watchdog_path_root,
                    heartbeat_path=heartbeat_path.resolve(),
                    ready_path=watchdog_ready_path.resolve(),
                    terminal_path=watchdog_terminal_path.resolve(),
                    phase_control_path=phase_control_path.resolve(),
                    phase_ack_path=phase_ack_path.resolve(),
                    child_watch_log_path=None,
                    attempt_nonce_sha256=None,
                    scope_sha256=None,
                    watchdog_protocol_sha256=None,
                    native_closure_sha256=None,
                additional_cleanup=close_controller_prelaunch_descriptors,
            )
        except BaseException:
            close_controller_prelaunch_descriptors()
            raise
    fields = {
        "schema_id": "phase-latency-prewarm-launch-intent-v1",
        "attempt_id": attempt_id,
        "retained_at_utc": datetime.now(UTC),
        "controller": controller,
        "absolute_deadline_monotonic_ns": deadline,
        "worker_command_sha256": _canonical_sha256(list(command)),
        "worker_environment_sha256": worker_environment_sha256(environment),
        "broker_command_template_sha256": (
            _canonical_sha256(list(broker_command))
            if broker_command is not None
            else None
        ),
        "broker_environment_sha256": (
            worker_environment_sha256(broker_environment)
            if broker_environment is not None
            else None
        ),
        "capability_scope_sha256": broker_scope_sha256,
        "capability_nonce_sha256": (
            hashlib.sha256(broker_attempt_nonce.encode("ascii")).hexdigest()
            if broker_attempt_nonce is not None
            else None
        ),
        "managed_group_policy": (
            "fork-denied-worker-plus-tesseract-broker-v1"
            if brokered is not None
            else "direct-worker-default-off-v1"
        ),
        "release_policy": (
            "o-excl-intent-then-watchdog-ready-then-one-byte-release-v1"
        ),
        "watchdog_policy": (
            "separate-session-exact-identity-absolute-deadline-term-kill-v1"
        ),
    }
    intent = ProductionLaunchIntent(
        **fields, intent_sha256=_canonical_sha256(fields)
    )
    if brokered is not None and request_root_fd is None:
        request_root_fd = os.open(
            request_root,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
    # Construct custody before committing the intent.  TERM/HUP is blocked by
    # ``write_private_canonical`` through its durable commit point, then may be
    # delivered as that helper unmasks.  The caller must still receive this
    # launch object so it can retain a terminal receipt and artifact observation.
    launch = _GuardedWorkerLaunch(
        attempt_id=attempt_id,
        workspace=workspace,
        output_directory=output_directory,
        protocol=protocol,
        environment=environment,
        controller_before=before,
        controller_identity=controller,
        absolute_deadline_monotonic_ns=deadline,
        intent=intent,
        intent_path=intent_path,
        launch_path=launch_path,
        launch_failure_path=launch_failure_path,
        heartbeat_path=heartbeat_path,
        watchdog_ready_path=watchdog_ready_path,
        watchdog_terminal_path=watchdog_terminal_path,
        prebind_fatal_path=prebind_fatal_path,
        phase_control_path=phase_control_path,
        phase_ack_path=phase_ack_path,
        broker_config_path=broker_config_path,
        broker_ready_path=broker_ready_path,
        supervisor_ready_path=supervisor_ready_path,
        child_watch_log_path=child_watch_log_path,
        request_control_path=request_control_path,
        request_cpu_sample_path=request_cpu_sample_path,
        request_resource_sample_path=request_resource_sample_path,
        native_closure_post_path=native_closure_post_path,
        source_executable_path=(
            source_executable if brokered is not None else None
        ),
        staged_executable_path=(
            staged_executable if brokered is not None else None
        ),
        native_fork_probe_path=(
            native_fork_probe_path if brokered is not None else None
        ),
        native_spawn_guard_path=(
            native_spawn_guard_path if brokered is not None else None
        ),
        native_spawn_guard_source_path=(
            native_spawn_guard_source_path if brokered is not None else None
        ),
        native_runtime_gate_source_path=(
            native_runtime_gate_source_path if brokered is not None else None
        ),
        native_runtime_gate_library_path=(
            native_runtime_gate_library_path if brokered is not None else None
        ),
        native_sandbox_probe_path=(
            native_sandbox_probe_path if brokered is not None else None
        ),
        native_sandbox_probe_source_path=(
            native_sandbox_probe_source_path if brokered is not None else None
        ),
        sandbox_probe_materialization=(
            sandbox_probe_materialization if brokered is not None else None
        ),
        sandbox_attempt_probe_authority=(
            sandbox_attempt_probe_authority
            if brokered is not None
            else None
        ),
        worker_sandbox_report_read_fd=(
            worker_sandbox_report_read_fd if brokered is not None else None
        ),
        worker_sandbox_report_write_fd=(
            worker_sandbox_report_write_fd if brokered is not None else None
        ),
        broker_sandbox_report_read_fd=(
            broker_sandbox_report_read_fd if brokered is not None else None
        ),
        broker_sandbox_report_write_fd=(
            broker_sandbox_report_write_fd if brokered is not None else None
        ),
        tessdata_root_path=(tessdata if brokered is not None else None),
        native_closure=native_closure,
        guard_python=(
            guard_python_identity if brokered is not None else None
        ),
        guard_python_path_custody=(
            guard_python_path_custody if brokered is not None else None
        ),
        guard_python_native_closure=(
            guard_python_native_closure if brokered is not None else None
        ),
        guard_python_module_tree_custody=(
            guard_python_module_tree_custody
            if brokered is not None
            else None
        ),
        guard_wrapper_source_path=(
            child_wrapper if brokered is not None else None
        ),
        native_closure_sha256=native_closure_identity,
        source_executable_sha256=(
            str(broker_template["source_executable"]["sha256"])
            if brokered is not None
            else None
        ),
        staged_executable_sha256=(
            str(staged_executable_identity["sha256"])
            if brokered is not None
            else None
        ),
        native_fork_probe_sha256=(
            str(native_fork_probe_identity["sha256"])
            if native_fork_probe_identity is not None
            else None
        ),
        native_fork_probe_source_sha256=native_fork_probe_source_sha256,
        native_spawn_guard_sha256=(
            str(native_spawn_guard_identity["sha256"])
            if native_spawn_guard_identity is not None
            else None
        ),
        native_spawn_guard_source_sha256=native_spawn_guard_source_sha256,
        native_sandbox_probe_sha256=(
            str(native_sandbox_probe_identity["sha256"])
            if native_sandbox_probe_identity is not None
            else None
        ),
        native_sandbox_probe_source_sha256=native_sandbox_probe_source_sha256,
        tessdata_sha256=(tessdata_sha256 if brokered is not None else None),
        release_read_fd=release_read_fd,
        release_write_fd=release_write_fd,
        broker_release_read_fd=broker_release_read_fd,
        broker_release_write_fd=broker_release_write_fd,
        broker_ready_read_fd=broker_ready_read_fd,
        broker_ready_write_fd=broker_ready_write_fd,
        supervisor_ready_read_fd=supervisor_ready_read_fd,
        supervisor_ready_write_fd=supervisor_ready_write_fd,
        request_root_fd=request_root_fd,
        broker_socket=broker_socket,
        worker_socket=worker_socket,
        broker_watch_socket=broker_watch_socket,
        watchdog_broker_socket=watchdog_broker_socket,
        worker_phase_socket=worker_phase_socket,
        watchdog_phase_socket=watchdog_phase_socket,
        worker_request_socket=worker_request_socket,
        controller_request_socket=controller_request_socket,
        watchdog=watchdog_process,
        watchdog_identity=watchdog_identity,
        launcher_control=launcher_control,
        launcher_identity=launcher_identity,
        launcher_log_path=launcher_log_path,
        watchdog_terminal_fd=watchdog_terminal_fd,
    )
    launch_resource_cleanup = handoff_prelaunch_resources_to_launch(launch)
    try:
        if brokered is not None:
            monitored_targets: list[tuple[str, Path]] = [
                (
                    "docling_artifacts",
                    brokered.immutable_artifact_root.resolve(strict=True),
                ),
                (
                    "staged_execution_inputs",
                    brokered.staged_executable_root.resolve(strict=True),
                ),
                (
                    "tessdata",
                    brokered.tesseract_data_path.resolve(strict=True),
                ),
            ]
            if launch.sandbox_probe_materialization is None:
                raise RuntimeError("sandbox probe materialization disappeared")
            monitored_targets.extend(
                launch.sandbox_probe_materialization.custody_roots()
            )
            protected_directories = tuple(path for _role, path in monitored_targets)
            seen_paths = set(protected_directories)
            if not isinstance(native_closure, dict):
                raise RuntimeError("native closure disappeared before custody arm")
            images = native_closure.get("images")
            if not isinstance(images, list):
                raise RuntimeError("native closure images differ before custody arm")
            additional_images: list[Path] = []
            for image in images:
                if not isinstance(image, dict) or not isinstance(
                    image.get("resolved_path"), str
                ):
                    raise RuntimeError("native closure image path differs")
                image_path = Path(image["resolved_path"]).resolve(strict=True)
                if image_path in seen_paths:
                    continue
                if any(
                    image_path == root or root in image_path.parents
                    for root in protected_directories
                ):
                    continue
                seen_paths.add(image_path)
                additional_images.append(image_path)
            monitored_targets.extend(
                (
                    f"native_closure_{index:04d}",
                    path,
                )
                for index, path in enumerate(
                    sorted(additional_images, key=str), start=1
                )
            )
            launch.immutable_input_custody = DarwinImmutableTreeCustody(
                tuple(sorted(monitored_targets, key=lambda item: item[0]))
            )
        _transfer_pending_preintent_launcher(launcher_control)
        _transfer_pending_preintent_resource_cleanup(
            launch_resource_cleanup
        )
        restore_preintent_signal_mask()
        write_private_canonical(intent_path, intent)
    except BaseException as error:
        launch.close_release()
        try:
            intent_committed = (
                intent_path.read_bytes() == canonical_model_bytes(intent)
                and stat.S_IMODE(intent_path.stat().st_mode) == 0o600
            )
        except BaseException:
            intent_committed = False
        if isinstance(error, _ControllerTerminationSignal):
            try:
                launch.retain_launch_failure(error)
            except BaseException as retention_error:
                launch.abort_launcher()
                raise _GuardedLaunchError(launch, retention_error) from error
            launch.abort_launcher()
            raise _GuardedLaunchError(launch, error) from error
        if not intent_committed:
            launch.abort_launcher()
            raise
        launch.abort_launcher()
        raise
    try:
        if launch.broker_config_path is not None:
            if broker_template_bytes is None or broker_template_sha256 is None:
                raise RuntimeError("broker launch template bytes disappeared")
            retained_template_sha256 = _write_private_payload(
                launch.broker_config_path,
                broker_template_bytes,
                maximum_bytes=MAXIMUM_BROKER_LAUNCH_TEMPLATE_BYTES,
            )
            if retained_template_sha256 != broker_template_sha256:
                raise RuntimeError("broker launch template hash differs")
            launch.broker_config_sha256 = retained_template_sha256
        heartbeat_fd = _create_private_empty(launch.heartbeat_path)
        os.close(heartbeat_fd)
        if brokered is None:
            phase_fd = _create_private_empty(launch.phase_control_path)
            os.close(phase_fd)
            ack_fd = _create_private_empty(launch.phase_ack_path)
            os.close(ack_fd)
            launch.startup_phase_record = append_phase_deadline(
                root=launch.phase_control_path.parent.resolve(strict=True),
                path=launch.phase_control_path.resolve(),
                attempt_id=attempt_id,
                phase="startup",
                timeout_ns=startup_timeout_ns,
                whole_deadline_monotonic_ns=deadline,
            )
        elif launch.phase_control_path.exists() or launch.phase_ack_path.exists():
            raise FileExistsError("authoritative phase log path existed before watchdog")
    except BaseException as error:
        launch.close_release()
        try:
            launch.retain_launch_failure(error)
        except BaseException as retention_error:
            raise _GuardedLaunchError(launch, retention_error) from error
        raise _GuardedLaunchError(launch, error) from error
    try:
        broker_native_identity = None
        worker_native_identity = None
        controller_start_abstime: int | None = None
        nonce_sha256 = (
            hashlib.sha256(str(broker_attempt_nonce).encode("ascii")).hexdigest()
            if brokered is not None
            else None
        )
        if brokered is not None:
            from app.services.tesseract_broker_native import (
                kernel_process_identity,
                raw_process_start_abstime,
            )

            if any(
                value is None
                for value in (
                    broker_command,
                    broker_environment,
                    broker_template_sha256,
                    broker_scope_sha256,
                    watchdog_protocol_sha256,
                    launch.broker_socket,
                    launch.broker_watch_socket,
                    launch.broker_ready_read_fd,
                    launch.broker_ready_write_fd,
                    launch.broker_release_read_fd,
                    launch.worker_socket,
                    launch.supervisor_ready_read_fd,
                    launch.supervisor_ready_write_fd,
                    launch.request_root_fd,
                    launch.watchdog_broker_socket,
                    launch.child_watch_log_path,
                    launch.worker_request_socket,
                    launch.controller_request_socket,
                    launch.request_control_path,
                    launch.request_cpu_sample_path,
                    launch.sandbox_attempt_probe_authority,
                    launch.broker_sandbox_report_read_fd,
                    launch.broker_sandbox_report_write_fd,
                    launch.worker_sandbox_report_read_fd,
                    launch.worker_sandbox_report_write_fd,
                )
            ):
                raise RuntimeError("brokered launch descriptors are incomplete")
            if raw_process_start_abstime(controller.pid) != controller_start_abstime:
                raise RuntimeError("logical controller start identity drifted")
            if (
                launch.launcher_control is None
                or launch.launcher_identity is None
                or launch.launcher_log_path is None
            ):
                raise RuntimeError("watchdog launcher custody is unavailable")
            broker_stdout_read, broker_stdout_write = os.pipe()
            broker_stderr_read, broker_stderr_write = os.pipe()
            broker_bindings = (
                _launcher_descriptor_binding(
                    command=broker_command,
                    environment=broker_environment,
                    descriptor=launch.broker_socket.fileno(),
                    name="broker-worker-capability",
                    disposition="child_pass",
                    argument_options=("--capability-fd",),
                ),
                _launcher_descriptor_binding(
                    command=broker_command,
                    environment=broker_environment,
                    descriptor=launch.broker_ready_write_fd,
                    name="broker-ready",
                    disposition="child_pass",
                    argument_options=("--ready-fd",),
                ),
                _launcher_descriptor_binding(
                    command=broker_command,
                    environment=broker_environment,
                    descriptor=launch.broker_release_read_fd,
                    name="broker-release",
                    disposition="child_pass",
                    argument_options=("--release-fd",),
                ),
                _launcher_descriptor_binding(
                    command=broker_command,
                    environment=broker_environment,
                    descriptor=launch.broker_watch_socket.fileno(),
                    name="broker-watch-child",
                    disposition="child_pass",
                    argument_options=("--watchdog-fd",),
                ),
                _launcher_descriptor_binding(
                    command=broker_command,
                    environment=broker_environment,
                    descriptor=launch.broker_sandbox_report_write_fd,
                    name="broker-sandbox-probe-report",
                    disposition="child_pass",
                    argument_options=("--sandbox-probe-report-fd",),
                ),
                _launcher_descriptor_binding(
                    command=broker_command,
                    environment=broker_environment,
                    descriptor=launch.watchdog_broker_socket.fileno(),
                    name="broker-watch-watchdog",
                    disposition="watchdog_broker",
                ),
                _launcher_descriptor_binding(
                    command=broker_command,
                    environment=broker_environment,
                    descriptor=broker_stdout_write,
                    name="broker-stdout",
                    disposition="stdout",
                ),
                _launcher_descriptor_binding(
                    command=broker_command,
                    environment=broker_environment,
                    descriptor=broker_stderr_write,
                    name="broker-stderr",
                    disposition="stderr",
                ),
                *tuple(
                    _launcher_descriptor_binding(
                        command=broker_command,
                        environment=broker_environment,
                        descriptor=descriptor,
                        name=f"broker-sandbox-held-root-{index:02d}",
                        disposition="child_pass",
                    )
                    for index, descriptor in enumerate(
                        launch.sandbox_attempt_probe_authority.broker_directory_descriptors,
                        start=1,
                    )
                ),
            )
            with _blocked_controller_termination_signals():
                broker_ack = launch.launcher_control.launch_root(
                    role="broker",
                    command=broker_command,
                    environment=broker_environment,
                    descriptor_bindings=broker_bindings,
                )
                broker_root = broker_ack["root"]
                launch.broker_launcher_root = (
                    LauncherOwnedRootIdentity.model_validate(broker_root)
                )
                launch.broker_identity = ControllerProcessIdentity(
                    pid=broker_root["pid"],
                    create_time_ns=broker_root["create_time_ns"],
                    process_group_id=broker_root["pgid"],
                    session_id=broker_root["sid"],
                )
                launch.broker_parent_pid = broker_root["ppid"]
                launch.broker = _WatchdogOwnedProcessProxy(
                    args=broker_command,
                    identity=launch.broker_identity,
                    stdout_fd=broker_stdout_read,
                    stderr_fd=broker_stderr_read,
                    launcher_log_path=launch.launcher_log_path,
                    role="broker",
                )
                launch.broker_capture = _BoundedPipeCapture(launch.broker)
                os.close(broker_stdout_write)
                os.close(broker_stderr_write)
                launch.broker_socket.close()
                launch.broker_socket = None
                launch.broker_watch_socket.close()
                launch.broker_watch_socket = None
                os.close(launch.broker_sandbox_report_write_fd)
                launch.broker_sandbox_report_write_fd = None
                os.close(launch.broker_ready_write_fd)
                launch.broker_ready_write_fd = None
                os.close(launch.broker_release_read_fd)
                launch.broker_release_read_fd = None
                launch.watchdog_broker_socket.close()
                launch.watchdog_broker_socket = None
                broker_native_identity = kernel_process_identity(launch.broker.pid)
            if (
                launch.broker_identity.pid != launch.broker_identity.process_group_id
                or launch.broker_identity.pid != launch.broker_identity.session_id
                or broker_native_identity.pid != launch.broker.pid
                or broker_native_identity.ppid != launch.launcher_identity["pid"]
                or broker_native_identity.pgid != launch.broker.pid
                or broker_native_identity.sid != launch.broker.pid
            ):
                raise RuntimeError("Tesseract broker lacks a fresh exact session")
            assert launch.broker_sandbox_report_read_fd is not None
            assert launch.sandbox_attempt_probe_authority is not None

            def pump_broker_sandbox_report() -> None:
                launch.refresh_heartbeat()
                if (
                    launch.broker_capture is not None
                    and launch.broker_capture.pump(0.0)
                ):
                    launch.broker_stream_limit_exceeded = True
                    launch.kill_managed_groups_immediately()

            _broker_sandbox_raw, broker_sandbox_report = (
                _read_bounded_ready_pipe(
                    launch.broker_sandbox_report_read_fd,
                    maximum_bytes=256 * 1024,
                    deadline_monotonic_ns=min(
                        deadline,
                        time.monotonic_ns() + WATCHDOG_READY_TIMEOUT_NS,
                    ),
                    pump=pump_broker_sandbox_report,
                    producers=(launch.broker,),
                )
            )
            os.close(launch.broker_sandbox_report_read_fd)
            launch.broker_sandbox_report_read_fd = None
            launch.broker_sandbox_probe_report = (
                _validate_root_sandbox_probe_report(
                    broker_sandbox_report,
                    plan=launch.sandbox_attempt_probe_authority.broker_plan,
                    expected_pid=broker_native_identity.pid,
                    expected_start_abstime=(
                        broker_native_identity.start_abstime
                    ),
                    expected_ppid=broker_native_identity.ppid,
                    expected_pgid=broker_native_identity.pgid,
                    expected_sid=broker_native_identity.sid,
                )
            )

            assert launch.worker_socket is not None
            assert launch.request_root_fd is not None
            assert launch.worker_phase_socket is not None
            assert launch.worker_request_socket is not None
            worker_profile_sha256 = hashlib.sha256(
                str(worker_profile).encode("ascii")
            ).hexdigest()
            supervisor_path = (
                workspace / "app/services/parser_worker_supervisor.py"
            ).resolve(strict=True)
            sandbox_path = Path(OS_NETWORK_SANDBOX_EXECUTABLE).resolve(strict=True)
            if (
                launch.native_fork_probe_path is None
                or launch.native_fork_probe_sha256 is None
                or launch.native_fork_probe_source_sha256 is None
                or launch.native_spawn_guard_path is None
                or launch.native_spawn_guard_source_path is None
                or launch.native_spawn_guard_sha256 is None
                or launch.native_spawn_guard_source_sha256 is None
                or launch.native_sandbox_probe_path is None
                or launch.native_sandbox_probe_source_path is None
                or launch.native_sandbox_probe_sha256 is None
                or launch.native_sandbox_probe_source_sha256 is None
            ):
                raise RuntimeError("native process guard launch custody is incomplete")
            environment = dict(environment)
            from app.services.tesseract_broker_protocol import (
                watchdog_ledger_schema_sha256,
            )

            environment.update(
                {
                    "TMPDIR": str(worker_scratch_root),
                    "TMP": str(worker_scratch_root),
                    "TEMP": str(worker_scratch_root),
                    "PARSER_TESSERACT_BROKER_FD": str(launch.worker_socket.fileno()),
                    "PARSER_TESSERACT_PHASE_CONTROL_FD": str(
                        launch.worker_phase_socket.fileno()
                    ),
                    "PARSER_TESSERACT_REQUEST_CONTROL_FD": str(
                        launch.worker_request_socket.fileno()
                    ),
                    "PARSER_TESSERACT_EXPECTED_REQUEST_COUNT": str(
                        request_count
                    ),
                    "PARSER_TESSERACT_ATTEMPT_ID": attempt_id,
                    "PARSER_TESSERACT_BROKER_NONCE_SHA256": str(nonce_sha256),
                    "PARSER_TESSERACT_BROKER_SCOPE_SHA256": str(broker_scope_sha256),
                    "PARSER_TESSERACT_BROKER_PID": str(broker_native_identity.pid),
                    "PARSER_TESSERACT_BROKER_START_ABSTIME": str(
                        broker_native_identity.start_abstime
                    ),
                    "PARSER_TESSERACT_BROKER_PGID": str(broker_native_identity.pgid),
                    "PARSER_TESSERACT_BROKER_SID": str(broker_native_identity.sid),
                    "PARSER_TESSERACT_EXECUTABLE": str(
                        brokered.tesseract_executable.resolve(strict=True)
                    ),
                    "PARSER_TESSERACT_EXECUTABLE_SHA256": _sha256_file(
                        brokered.tesseract_executable.resolve(strict=True)
                    ),
                    "PARSER_TESSERACT_STAGED_EXECUTABLE": str(
                        staged_executable.resolve(strict=True)
                    ),
                    "PARSER_TESSERACT_STAGED_EXECUTABLE_SHA256": str(
                        staged_executable_identity["sha256"]
                    ),
                    "PARSER_TESSERACT_NATIVE_CLOSURE_SHA256": str(
                        native_closure_identity
                    ),
                    "PARSER_TESSERACT_NATIVE_RUNTIME_GATE_SOURCE_SHA256": str(
                        runtime_gate["source"]["sha256"]
                    ),
                    "PARSER_TESSERACT_NATIVE_RUNTIME_GATE_LIBRARY_SHA256": str(
                        runtime_gate["library"]["sha256"]
                    ),
                    "PARSER_TESSERACT_NATIVE_RUNTIME_GATE_RECORD_SHA256": str(
                        runtime_gate["record_sha256"]
                    ),
                    "PARSER_TESSERACT_GUARD_PYTHON_SHA256": str(
                        guard_python_identity["sha256"]
                    ),
                    "PARSER_TESSERACT_GUARD_PYTHON_PATH_CUSTODY_SHA256": str(
                        guard_python_path_custody["record_sha256"]
                    ),
                    "PARSER_TESSERACT_GUARD_PYTHON_NATIVE_CLOSURE_SHA256": str(
                        guard_python_native_closure["closure_sha256"]
                    ),
                    "PARSER_TESSERACT_GUARD_PYTHON_MODULE_TREE_SHA256": str(
                        guard_python_module_tree_custody["record_sha256"]
                    ),
                    "PARSER_TESSERACT_GUARD_WRAPPER_SOURCE_SHA256": str(
                        broker_template["child_wrapper_sha256"]
                    ),
                    "PARSER_TESSERACT_TESSDATA_ROOT": str(
                        brokered.tesseract_data_path.resolve(strict=True)
                    ),
                    "PARSER_TESSERACT_TESSDATA_SHA256": str(tessdata_sha256),
                    "PARSER_TESSERACT_LANGUAGES": ",".join(
                        brokered.allowed_languages
                    ),
                    "PARSER_TESSERACT_REQUEST_ROOT": str(
                        brokered.request_root.resolve(strict=True)
                    ),
                    "PARSER_TESSERACT_REQUEST_ROOT_FD": str(launch.request_root_fd),
                    "PARSER_TESSERACT_WORKER_SCRATCH": str(worker_scratch_root),
                    "PARSER_TESSERACT_WORKER_SCRATCH_FD": str(
                        launch.request_root_fd
                    ),
                    "PARSER_TESSERACT_WORKER_SCRATCH_IDENTITY_SHA256": (
                        _canonical_sha256(
                            _filesystem_identity(worker_scratch_root)
                        )
                    ),
                    "PARSER_TESSERACT_EXTERNAL_BARRIERS": "true",
                    "PARSER_TESSERACT_ATTEMPT_DEADLINE_MONOTONIC_NS": str(deadline),
                    "PARSER_TESSERACT_BROKER_CONFIG_SHA256": str(
                        broker_template_sha256
                    ),
                    "PARSER_TESSERACT_BROKER_PROFILE_SHA256": hashlib.sha256(
                        str(broker_profile).encode("ascii")
                    ).hexdigest(),
                    "PARSER_TESSERACT_WATCHDOG_PROTOCOL_SHA256": str(
                        watchdog_protocol_sha256
                    ),
                    "PARSER_TESSERACT_WATCHDOG_LEDGER_SCHEMA_SHA256": (
                        watchdog_ledger_schema_sha256()
                    ),
                    "PARSER_TESSERACT_WORKER_PROFILE_SHA256": worker_profile_sha256,
                    "PARSER_TESSERACT_CONTROLLER_PID": str(controller.pid),
                    "PARSER_TESSERACT_CONTROLLER_START_ABSTIME": str(
                        controller_start_abstime
                    ),
                    "PARSER_TESSERACT_LAUNCHER_PID": str(
                        launch.launcher_identity["pid"]
                    ),
                    "PARSER_TESSERACT_LAUNCHER_START_ABSTIME": str(
                        launch.launcher_identity["start_abstime"]
                    ),
                    "PARSER_TESSERACT_LAUNCHER_PPID": str(
                        launch.launcher_identity["ppid"]
                    ),
                    "PARSER_TESSERACT_LAUNCHER_PGID": str(
                        launch.launcher_identity["pgid"]
                    ),
                    "PARSER_TESSERACT_LAUNCHER_SID": str(
                        launch.launcher_identity["sid"]
                    ),
                    "PARSER_TESSERACT_LAUNCHER_UID": str(
                        launch.launcher_identity["uid"]
                    ),
                    "PARSER_TESSERACT_LAUNCHER_EUID": str(
                        launch.launcher_identity["euid"]
                    ),
                    "PARSER_TESSERACT_SEATBELT_EXECUTABLE_SHA256": _sha256_file(
                        sandbox_path
                    ),
                    "PARSER_TESSERACT_SUPERVISOR_CAPABILITY_SHA256": _sha256_file(
                        supervisor_path
                    ),
                    "PARSER_TESSERACT_NATIVE_FORK_PROBE_PATH": str(
                        launch.native_fork_probe_path.resolve(strict=True)
                    ),
                    "PARSER_TESSERACT_NATIVE_FORK_PROBE_SHA256": (
                        launch.native_fork_probe_sha256
                    ),
                    "PARSER_TESSERACT_NATIVE_SPAWN_GUARD_SHA256": (
                        launch.native_spawn_guard_sha256
                    ),
                    "PARSER_TESSERACT_NATIVE_SPAWN_GUARD_SOURCE_SHA256": (
                        launch.native_spawn_guard_source_sha256
                    ),
                    "PARSER_TESSERACT_WORKER_SANDBOX_PLAN_HEX": (
                        _canonical_payload_bytes(
                            launch.sandbox_attempt_probe_authority.worker_plan
                        ).hex()
                        if launch.sandbox_attempt_probe_authority is not None
                        else ""
                    ),
                }
            )
            if environment.get("PARSER_LATENCY_PREWARM_ENABLED") != "true":
                environment["PARSER_LATENCY_PRIVATE_BROKER_PREDECESSOR"] = "true"
            environment = dict(sorted(environment.items()))
            launch.environment = environment
            assert commit_worker_configuration is not None
            commit_worker_configuration(environment)

        if (
            launch.launcher_control is None
            or launch.launcher_identity is None
            or launch.launcher_log_path is None
        ):
            raise RuntimeError("watchdog launcher custody is unavailable")
        worker_stdout_read, worker_stdout_write = os.pipe()
        worker_stderr_read, worker_stderr_write = os.pipe()
        worker_bindings: list[dict[str, Any]] = [
            _launcher_descriptor_binding(
                command=command,
                environment=environment,
                descriptor=launch.release_read_fd,
                name="worker-release",
                disposition="child_pass",
                argument_options=("--controller-release-fd",),
            )
        ]
        if brokered is not None:
            assert launch.worker_socket is not None
            assert launch.supervisor_ready_write_fd is not None
            assert launch.request_root_fd is not None
            assert launch.worker_phase_socket is not None
            assert launch.watchdog_phase_socket is not None
            assert launch.worker_request_socket is not None
            worker_bindings.extend(
                (
                    _launcher_descriptor_binding(
                        command=command,
                        environment=environment,
                        descriptor=launch.worker_socket.fileno(),
                        name="worker-broker-capability",
                        disposition="child_pass",
                        environment_keys=("PARSER_TESSERACT_BROKER_FD",),
                    ),
                    _launcher_descriptor_binding(
                        command=command,
                        environment=environment,
                        descriptor=launch.supervisor_ready_write_fd,
                        name="worker-supervisor-ready",
                        disposition="child_pass",
                        argument_options=("--ready-fd",),
                    ),
                    _launcher_descriptor_binding(
                        command=command,
                        environment=environment,
                        descriptor=launch.request_root_fd,
                        name="worker-scratch-dirfd",
                        disposition="child_pass",
                        environment_keys=(
                            "PARSER_TESSERACT_REQUEST_ROOT_FD",
                            "PARSER_TESSERACT_WORKER_SCRATCH_FD",
                        ),
                    ),
                    _launcher_descriptor_binding(
                        command=command,
                        environment=environment,
                        descriptor=launch.worker_phase_socket.fileno(),
                        name="worker-phase-control",
                        disposition="child_pass",
                        environment_keys=("PARSER_TESSERACT_PHASE_CONTROL_FD",),
                    ),
                    _launcher_descriptor_binding(
                        command=command,
                        environment=environment,
                        descriptor=launch.watchdog_phase_socket.fileno(),
                        name="watchdog-phase-control",
                        disposition="watchdog_phase",
                    ),
                    _launcher_descriptor_binding(
                        command=command,
                        environment=environment,
                        descriptor=launch.worker_request_socket.fileno(),
                        name="worker-request-control",
                        disposition="child_pass",
                        environment_keys=("PARSER_TESSERACT_REQUEST_CONTROL_FD",),
                    ),
                    _launcher_descriptor_binding(
                        command=command,
                        environment=environment,
                        descriptor=launch.worker_sandbox_report_write_fd,
                        name="worker-sandbox-probe-report",
                        disposition="child_pass",
                        argument_options=("--sandbox-probe-report-fd",),
                    ),
                    *tuple(
                        _launcher_descriptor_binding(
                            command=command,
                            environment=environment,
                            descriptor=descriptor,
                            name=f"worker-sandbox-held-root-{index:02d}",
                            disposition="child_pass",
                        )
                        for index, descriptor in enumerate(
                            launch.sandbox_attempt_probe_authority.worker_directory_descriptors,
                            start=1,
                        )
                        if descriptor != launch.request_root_fd
                    ),
                )
            )
        worker_bindings.extend(
            (
                _launcher_descriptor_binding(
                    command=command,
                    environment=environment,
                    descriptor=worker_stdout_write,
                    name="worker-stdout",
                    disposition="stdout",
                ),
                _launcher_descriptor_binding(
                    command=command,
                    environment=environment,
                    descriptor=worker_stderr_write,
                    name="worker-stderr",
                    disposition="stderr",
                ),
            )
        )
        with _blocked_controller_termination_signals():
            worker_ack = launch.launcher_control.launch_root(
                role="worker",
                command=command,
                environment=environment,
                descriptor_bindings=tuple(worker_bindings),
            )
            worker_root = worker_ack["root"]
            launch.worker_launcher_root = (
                LauncherOwnedRootIdentity.model_validate(worker_root)
            )
            launch.worker_identity = ControllerProcessIdentity(
                pid=worker_root["pid"],
                create_time_ns=worker_root["create_time_ns"],
                process_group_id=worker_root["pgid"],
                session_id=worker_root["sid"],
            )
            launch.worker_parent_pid = worker_root["ppid"]
            launch.process = _WatchdogOwnedProcessProxy(
                args=command,
                identity=launch.worker_identity,
                stdout_fd=worker_stdout_read,
                stderr_fd=worker_stderr_read,
                launcher_log_path=launch.launcher_log_path,
                role="worker",
            )
            launch.capture = _BoundedPipeCapture(launch.process)
            os.close(worker_stdout_write)
            os.close(worker_stderr_write)
            os.close(launch.release_read_fd)
            launch.release_read_fd = None
            if launch.worker_socket is not None:
                launch.worker_socket.close()
                launch.worker_socket = None
            if launch.supervisor_ready_write_fd is not None:
                os.close(launch.supervisor_ready_write_fd)
                launch.supervisor_ready_write_fd = None
            if launch.worker_phase_socket is not None:
                launch.worker_phase_socket.close()
                launch.worker_phase_socket = None
            if launch.watchdog_phase_socket is not None:
                launch.watchdog_phase_socket.close()
                launch.watchdog_phase_socket = None
            if launch.worker_request_socket is not None:
                launch.worker_request_socket.close()
                launch.worker_request_socket = None
            if launch.worker_sandbox_report_write_fd is not None:
                os.close(launch.worker_sandbox_report_write_fd)
                launch.worker_sandbox_report_write_fd = None
            if brokered is not None:
                worker_native_identity = kernel_process_identity(launch.process.pid)
        if (
            launch.worker_identity.pid != launch.worker_identity.process_group_id
            or launch.worker_identity.pid != launch.worker_identity.session_id
            or launch.worker_parent_pid != launch.launcher_identity["pid"]
            or os.getpgid(launch.process.pid) != launch.process.pid
        ):
            raise RuntimeError("production worker lacks a fresh exact session")

        if brokered is not None:
            assert launch.worker_sandbox_report_read_fd is not None
            assert launch.sandbox_attempt_probe_authority is not None
            assert worker_native_identity is not None

            def pump_worker_sandbox_report() -> None:
                launch.refresh_heartbeat()
                if launch.capture is not None and launch.capture.pump(0.0):
                    launch.stream_limit_exceeded = True
                    launch.kill_managed_groups_immediately()

            _worker_sandbox_raw, worker_sandbox_report = (
                _read_bounded_ready_pipe(
                    launch.worker_sandbox_report_read_fd,
                    maximum_bytes=256 * 1024,
                    deadline_monotonic_ns=min(
                        deadline,
                        time.monotonic_ns() + WATCHDOG_READY_TIMEOUT_NS,
                    ),
                    pump=pump_worker_sandbox_report,
                    producers=(launch.process,),
                )
            )
            os.close(launch.worker_sandbox_report_read_fd)
            launch.worker_sandbox_report_read_fd = None
            launch.worker_sandbox_probe_report = (
                _validate_root_sandbox_probe_report(
                    worker_sandbox_report,
                    plan=launch.sandbox_attempt_probe_authority.worker_plan,
                    expected_pid=worker_native_identity.pid,
                    expected_start_abstime=(
                        worker_native_identity.start_abstime
                    ),
                    expected_ppid=worker_native_identity.ppid,
                    expected_pgid=worker_native_identity.pgid,
                    expected_sid=worker_native_identity.sid,
                )
            )
            if any(
                value is None
                for value in (
                    launch.controller_request_socket,
                    launch.request_root_fd,
                    launch.request_control_path,
                    launch.request_cpu_sample_path,
                    worker_native_identity,
                    broker_native_identity,
                    nonce_sha256,
                    broker_scope_sha256,
                    request_count,
                )
            ):
                raise RuntimeError("request-control custody is incomplete")
            launch.request_control = _RequestControlController(
                sock=launch.controller_request_socket,
                attempt_id=attempt_id,
                attempt_nonce_sha256=str(nonce_sha256),
                scope_sha256=str(broker_scope_sha256),
                absolute_deadline_monotonic_ns=deadline,
                expected_request_count=int(request_count),
                worker_identity=asdict(worker_native_identity),
                broker_identity=asdict(broker_native_identity),
                request_root_fd=launch.request_root_fd,
                transcript_path=launch.request_control_path,
                cpu_sample_path=launch.request_cpu_sample_path,
            )

        if launch.launcher_control is None or launch.watchdog is None:
            raise RuntimeError("watchdog launcher disappeared before commit")
        with _blocked_controller_termination_signals():
            launch.launcher_control.commit(
                ("broker", "worker") if brokered is not None else ("worker",)
            )
        if (
            launch.watchdog_identity.pid
            != launch.watchdog_identity.process_group_id
            or launch.watchdog_identity.pid
            != launch.watchdog_identity.session_id
        ):
            raise RuntimeError("production watchdog lacks a fresh exact session")
        ready_deadline = min(
            deadline, time.monotonic_ns() + WATCHDOG_READY_TIMEOUT_NS
        )
        while not launch.watchdog_ready_path.exists():
            launch.refresh_heartbeat()
            if launch.capture.pump(0.01):
                launch.stream_limit_exceeded = True
                launch.stream_cleanup_forced = (
                    launch.kill_managed_groups_immediately()
                )
                raise RuntimeError("worker output exceeded cap before release")
            if (
                launch.broker_capture is not None
                and launch.broker_capture.pump(0.0)
            ):
                launch.broker_stream_limit_exceeded = True
                launch.broker_stream_cleanup_forced = (
                    launch.kill_managed_groups_immediately()
                )
                raise RuntimeError("broker output exceeded cap before release")
            if (
                launch.process.poll() is not None
                or launch.watchdog.poll() is not None
                or (
                    launch.broker is not None
                    and launch.broker.poll() is not None
                )
            ):
                raise RuntimeError("production watchdog failed before READY")
            if time.monotonic_ns() >= ready_deadline:
                raise TimeoutError("production watchdog READY timed out")
        ready = launch.watchdog_ready_path.lstat()
        if (
            launch.watchdog_ready_path.is_symlink()
            or not stat.S_ISREG(ready.st_mode)
            or stat.S_IMODE(ready.st_mode) != 0o600
            or ready.st_uid != os.getuid()
            or launch.watchdog_ready_path.read_bytes() != b"READY\n"
        ):
            raise RuntimeError("production watchdog READY custody differs")

        if brokered is not None:
            assert launch.broker is not None
            assert launch.broker_ready_read_fd is not None
            assert broker_native_identity is not None
            assert controller_start_abstime is not None
            assert launch.child_watch_log_path is not None

            def pump_broker_ready() -> None:
                launch.refresh_heartbeat()
                if launch.broker_capture is not None and launch.broker_capture.pump(0.0):
                    launch.broker_stream_limit_exceeded = True
                    launch.kill_managed_groups_immediately()

            broker_ready_raw, broker_ready = _read_bounded_ready_pipe(
                launch.broker_ready_read_fd,
                maximum_bytes=MAXIMUM_BROKER_READY_BYTES,
                deadline_monotonic_ns=min(
                    deadline, time.monotonic_ns() + WATCHDOG_READY_TIMEOUT_NS
                ),
                pump=pump_broker_ready,
                producers=(launch.broker,),
            )
            os.close(launch.broker_ready_read_fd)
            launch.broker_ready_read_fd = None
            from app.services.tesseract_broker import validate_broker_ready_record

            validate_broker_ready_record(
                broker_ready,
                config_sha256=str(broker_template_sha256),
                expected_pid=broker_native_identity.pid,
                expected_start_abstime=broker_native_identity.start_abstime,
                expected_launcher=dict(launch.launcher_identity),
            )
            if launch.request_control is None:
                raise RuntimeError("request control is absent at broker READY")
            launch.request_control.bind_broker_pre_release_ready(
                broker_ready.get("ready_sha256")
            )
            ledger_stat = launch.child_watch_log_path.lstat()
            capability = broker_ready.get("capability")
            expected_capability = {
                "worker": {
                    "family": "AF_UNIX",
                    "type": "SOCK_STREAM",
                    "cloexec": True,
                    "device": broker_worker_socket_identity[0],
                    "inode": broker_worker_socket_identity[1],
                },
                "watchdog": {
                    "family": "AF_UNIX",
                    "type": "SOCK_STREAM",
                    "cloexec": True,
                    "device": broker_watch_socket_identity[0],
                    "inode": broker_watch_socket_identity[1],
                },
            }
            expected_ledger = {
                "resolved_path": str(launch.child_watch_log_path),
                "device": ledger_stat.st_dev,
                "inode": ledger_stat.st_ino,
                "mode": ledger_stat.st_mode,
                "uid": ledger_stat.st_uid,
                "nlink": ledger_stat.st_nlink,
                "size_bytes": 0,
                "head_sha256": "0" * 64,
            }
            if (
                broker_ready.get("attempt_nonce_sha256") != nonce_sha256
                or broker_ready.get("scope_sha256") != broker_scope_sha256
                or broker_ready.get("controller")
                != {"pid": controller.pid, "start_abstime": controller_start_abstime}
                or broker_ready.get("launcher") != launch.launcher_identity
                or broker_ready.get("broker")
                != {
                    "pid": broker_native_identity.pid,
                    "start_abstime": broker_native_identity.start_abstime,
                    "ppid": broker_native_identity.ppid,
                    "pgid": broker_native_identity.pgid,
                    "sid": broker_native_identity.sid,
                    "uid": os.getuid(),
                    "euid": os.geteuid(),
                }
                or capability != expected_capability
                or broker_ready.get("profile_sha256")
                != hashlib.sha256(str(broker_profile).encode("ascii")).hexdigest()
                or broker_ready.get("executable_sha256")
                != staged_executable_identity["sha256"]
                or broker_ready.get("tessdata_sha256") != tessdata_sha256
                or broker_ready.get("watchdog_protocol_sha256")
                != watchdog_protocol_sha256
                or broker_ready.get("native_closure_sha256")
                != native_closure_identity
                or broker_ready.get("native_trust_model")
                != "frozen-native-closure-trusted-v1"
                or broker_ready.get("native_containment_claim")
                != "none-trusted-pinned-native-computation"
                or broker_ready.get("native_spawn_guard_sha256")
                != launch.native_spawn_guard_sha256
                or broker_ready.get("native_spawn_guard_source_sha256")
                != launch.native_spawn_guard_source_sha256
                or broker_ready.get("ledger") != expected_ledger
                or not stat.S_ISREG(ledger_stat.st_mode)
                or stat.S_IMODE(ledger_stat.st_mode) != 0o600
                or ledger_stat.st_uid != os.geteuid()
                or ledger_stat.st_nlink != 1
                or ledger_stat.st_size != 0
            ):
                raise RuntimeError("Tesseract broker READY custody differs")
            assert launch.broker_ready_path is not None
            launch.broker_ready_sha256 = _write_private_payload(
                launch.broker_ready_path, broker_ready_raw
            )
            if launch.broker_release_write_fd is None or os.write(
                launch.broker_release_write_fd, b"R"
            ) != 1:
                raise RuntimeError("broker release write made no progress")
            os.close(launch.broker_release_write_fd)
            launch.broker_release_write_fd = None

            assert launch.supervisor_ready_read_fd is not None
            assert launch.supervisor_ready_path is not None
            assert worker_native_identity is not None

            def pump_supervisor_ready() -> None:
                launch.refresh_heartbeat()
                if launch.capture is not None and launch.capture.pump(0.0):
                    launch.stream_limit_exceeded = True
                    launch.kill_managed_groups_immediately()
                if launch.broker_capture is not None and launch.broker_capture.pump(0.0):
                    launch.broker_stream_limit_exceeded = True
                    launch.kill_managed_groups_immediately()

            supervisor_ready_raw, supervisor_ready = _read_bounded_ready_pipe(
                launch.supervisor_ready_read_fd,
                maximum_bytes=MAXIMUM_SUPERVISOR_READY_BYTES,
                deadline_monotonic_ns=min(
                    deadline, time.monotonic_ns() + WATCHDOG_READY_TIMEOUT_NS
                ),
                pump=pump_supervisor_ready,
                producers=(launch.process, launch.broker),
            )
            os.close(launch.supervisor_ready_read_fd)
            launch.supervisor_ready_read_fd = None
            from app.services.parser_worker_supervisor import (
                validate_worker_ready_record,
            )

            validate_worker_ready_record(
                supervisor_ready,
                expected_pid=worker_native_identity.pid,
                expected_start_abstime=worker_native_identity.start_abstime,
                expected_scope_sha256=str(broker_scope_sha256),
                expected_launcher=dict(launch.launcher_identity),
            )
            fork_denial = supervisor_ready.get("fork_denial")
            request_control_module = (
                workspace / "app/services/parser_request_control.py"
            ).resolve(strict=True)
            scratch_stat = os.fstat(launch.request_root_fd)
            assert launch.native_fork_probe_path is not None
            assert launch.native_fork_probe_sha256 is not None
            assert launch.native_fork_probe_source_sha256 is not None
            assert launch.native_spawn_guard_sha256 is not None
            assert launch.native_spawn_guard_source_sha256 is not None
            native_probe_stat = launch.native_fork_probe_path.lstat()
            if (
                supervisor_ready.get("attempt_nonce_sha256") != nonce_sha256
                or type(fork_denial) is not dict
                or fork_denial.get("worker", {}).get("pid")
                != worker_native_identity.pid
                or fork_denial.get("worker", {}).get("start_abstime")
                != worker_native_identity.start_abstime
                or fork_denial.get("broker", {}).get("pid")
                != broker_native_identity.pid
                or fork_denial.get("broker", {}).get("start_abstime")
                != broker_native_identity.start_abstime
                or fork_denial.get("launcher") != launch.launcher_identity
                or fork_denial.get("launcher_pid")
                != launch.launcher_identity["pid"]
                or fork_denial.get("launcher_start_abstime")
                != launch.launcher_identity["start_abstime"]
                or fork_denial.get("worker_parent_is_launcher") is not True
                or fork_denial.get("broker_parent_is_launcher") is not True
                or fork_denial.get("broker_real_uid") != os.getuid()
                or fork_denial.get("broker_effective_uid") != os.geteuid()
                or fork_denial.get("hard_limit_before_first_app_import")
                is not True
                or not isinstance(
                    fork_denial.get("hard_limit_installed_at_monotonic_ns"),
                    int,
                )
                or not isinstance(
                    fork_denial.get("first_app_import_started_at_monotonic_ns"),
                    int,
                )
                or fork_denial.get("hard_limit_installed_at_monotonic_ns", 0)
                > fork_denial.get("first_app_import_started_at_monotonic_ns", 0)
                or fork_denial.get("rlimit_nproc_soft") != 0
                or fork_denial.get("rlimit_nproc_hard") != 0
                or fork_denial.get("seatbelt_profile_sha256")
                != hashlib.sha256(str(worker_profile).encode("ascii")).hexdigest()
                or fork_denial.get("request_control_sha256")
                != _sha256_file(request_control_module)
                or worker_request_socket_identity is None
                or fork_denial.get("request_control_device")
                != worker_request_socket_identity[0]
                or fork_denial.get("request_control_inode")
                != worker_request_socket_identity[1]
                or fork_denial.get("request_control_family")
                != int(socket.AF_UNIX)
                or fork_denial.get("request_control_socket_type")
                != int(socket.SOCK_STREAM)
                or fork_denial.get("request_control_peer_binding")
                != "controller-pass-fds-transcript-v1"
                or fork_denial.get("expected_request_count") != request_count
                or fork_denial.get("worker_scratch_path_sha256")
                != hashlib.sha256(
                    str(worker_scratch_root).encode("utf-8")
                ).hexdigest()
                or fork_denial.get("worker_scratch_device") != scratch_stat.st_dev
                or fork_denial.get("worker_scratch_inode") != scratch_stat.st_ino
                or fork_denial.get("worker_scratch_mode") != 0o700
                or fork_denial.get("worker_scratch_uid") != scratch_stat.st_uid
                or fork_denial.get("worker_tmpdir_bound") is not True
                or fork_denial.get("worker_scratch_root_empty_at_ready") is not True
                or fork_denial.get("native_fork_probe_source_sha256")
                != launch.native_fork_probe_source_sha256
                or fork_denial.get("native_fork_probe_library_sha256")
                != launch.native_fork_probe_sha256
                or fork_denial.get("native_fork_probe_device")
                != native_probe_stat.st_dev
                or fork_denial.get("native_fork_probe_inode")
                != native_probe_stat.st_ino
                or fork_denial.get("native_fork_probe_mode")
                != native_probe_stat.st_mode
                or fork_denial.get("native_fork_probe_uid")
                != native_probe_stat.st_uid
                or fork_denial.get("native_fork_probe_kind")
                != "pinned-darwin-c-vfork-safe-v1"
                or fork_denial.get("native_fork_probe_loaded_after_hard_limit")
                is not True
                or not isinstance(
                    fork_denial.get("native_fork_probe_loaded_at_monotonic_ns"),
                    int,
                )
                or fork_denial.get("broker_native_spawn_guard_source_sha256")
                != launch.native_spawn_guard_source_sha256
                or fork_denial.get("broker_native_spawn_guard_library_sha256")
                != launch.native_spawn_guard_sha256
                or fork_denial.get("native_import_time_fork_errno")
                not in {1, 35}
            ):
                raise RuntimeError("worker supervisor READY custody differs")
            launch.supervisor_ready_sha256 = _write_private_payload(
                launch.supervisor_ready_path, supervisor_ready_raw
            )
        phase_records, launch.phase_control_snapshot = read_phase_deadlines(
            root=launch.phase_control_path.parent.resolve(strict=True),
            path=launch.phase_control_path.resolve(),
            attempt_id=attempt_id,
            whole_deadline_monotonic_ns=deadline,
        )
        phase_acks, launch.phase_ack_snapshot = read_phase_acks(
            root=launch.phase_ack_path.parent.resolve(strict=True),
            path=launch.phase_ack_path.resolve(),
            attempt_id=attempt_id,
        )
        if launch.startup_phase_record is None and len(phase_records) == 1:
            launch.startup_phase_record = phase_records[0]
        if (
            phase_records != (launch.startup_phase_record,)
            or len(phase_acks) != 1
            or phase_acks[0].phase_record_sha256
            != launch.startup_phase_record.record_sha256
        ):
            raise RuntimeError("watchdog startup phase ACK differs")
        launch.startup_phase_ack = phase_acks[0]
        worker_tree = read_process_tree_snapshot(
            launch.process.pid, observed_monotonic_ns=time.monotonic_ns()
        )
        if any(
            member.identity.pid
            in {
                launch.watchdog.pid,
                *(
                    (launch.broker.pid,)
                    if launch.broker is not None
                    else ()
                ),
            }
            for member in worker_tree.members
        ):
            raise RuntimeError("controller-owned peer entered worker resource tree")
        launch_fields = {
            "schema_id": "phase-latency-prewarm-launch-record-v1",
            "attempt_id": attempt_id,
            "intent_sha256": intent.intent_sha256,
            "retained_before_release_monotonic_ns": max(1, time.monotonic_ns()),
            "worker": launch.worker_identity,
            "broker": launch.broker_identity,
            "watchdog": launch.watchdog_identity,
            "watchdog_ready_mode": 0o600,
            "watchdog_terminal_filename": launch.watchdog_terminal_path.name,
            "broker_ready_filename": (
                launch.broker_ready_path.name
                if launch.broker_ready_path is not None
                else None
            ),
            "broker_ready_sha256": launch.broker_ready_sha256,
            "supervisor_ready_filename": (
                launch.supervisor_ready_path.name
                if launch.supervisor_ready_path is not None
                else None
            ),
            "supervisor_ready_sha256": launch.supervisor_ready_sha256,
            "broker_config_filename": (
                launch.broker_config_path.name
                if launch.broker_config_path is not None
                else None
            ),
            "broker_config_sha256": launch.broker_config_sha256,
            "released_worker_command_sha256": _canonical_sha256(list(command)),
            "released_worker_environment_sha256": worker_environment_sha256(
                environment
            ),
            "broker_command_sha256": (
                _canonical_sha256(list(broker_command))
                if broker_command is not None
                else None
            ),
            "broker_environment_sha256": (
                worker_environment_sha256(broker_environment)
                if broker_environment is not None
                else None
            ),
            "startup_phase_record_sha256": (
                launch.startup_phase_record.record_sha256
            ),
            "startup_phase_ack_sha256": launch.startup_phase_ack.record_sha256,
            "startup_phase_deadline_acknowledged": True,
            "release_token_sha256": hashlib.sha256(b"\x01").hexdigest(),
            "release_authorized": True,
            "watchdog_excluded_from_worker_request_tree": True,
        }
        launch.launch_record = ProductionLaunchRecord(
            **launch_fields, launch_sha256=_canonical_sha256(launch_fields)
        )
        write_private_canonical(launch.launch_path, launch.launch_record)
        if launch.release_write_fd is None:
            raise RuntimeError("worker release descriptor disappeared")
        if os.write(launch.release_write_fd, b"\x01") != 1:
            raise RuntimeError("worker release write made no progress")
        os.close(launch.release_write_fd)
        launch.release_write_fd = None
        return launch
    except BaseException as error:
        launch.close_release()
        try:
            launch.retain_launch_failure(error)
        except BaseException as retention_error:
            raise _GuardedLaunchError(launch, retention_error) from error
        raise _GuardedLaunchError(launch, error) from error


def _attempt_environment(
    *,
    workspace: Path,
    prepared: PreparedProductionRuntime,
    guard_root: Path,
    mode: RunMode,
    worker_scratch_root: Path | None = None,
) -> dict[str, str]:
    environment = controlled_worker_environment(
        workspace,
        prepared.common_environment,
        child_guard_root=guard_root,
    )
    environment.update(prepared.common_environment)
    environment["PARSER_LATENCY_PREWARM_ENABLED"] = (
        "true" if mode is RunMode.ENABLED else "false"
    )
    if worker_scratch_root is not None:
        scratch = str(worker_scratch_root.resolve(strict=True))
        for name in ("TMPDIR", "TMP", "TEMP"):
            environment[name] = scratch
    return dict(sorted(environment.items()))


def _prebound_broker_projection_environment(
    environment: dict[str, str], *, request_root: Path
) -> dict[str, str]:
    """Close the scratch alias group before numeric capability FDs are minted.

    The launch record replaces the two prebind FD tokens with the exact equal
    inherited descriptor value.  Keeping the path and descriptor aliases in
    the pre-intent projection makes signal/failure receipts independently
    valid without claiming that a broker capability was launched.
    """

    projected = dict(environment)
    resolved = str(request_root.resolve(strict=True))
    projected.update(
        {
            "PARSER_TESSERACT_REQUEST_ROOT": resolved,
            "PARSER_TESSERACT_WORKER_SCRATCH": resolved,
            "PARSER_TESSERACT_REQUEST_ROOT_FD": "prebound-dirfd-v1",
            "PARSER_TESSERACT_WORKER_SCRATCH_FD": "prebound-dirfd-v1",
        }
    )
    return dict(sorted(projected.items()))


def _production_request_binding(source: SourceIdentity) -> dict[str, object]:
    """Build the exact controller ARM binding for one retained source."""

    from app.services.parser_worker import canonical_parse_query_sha256

    return {
        "schema_id": "parser-broker-request-binding-v2",
        "method": "POST",
        "path": "/v1/parse",
        "query_sha256": canonical_parse_query_sha256(b"output_format=json"),
        "output_format": "json",
        "source_sha256": source.sha256,
        "source_bytes": source.size_bytes,
        "safe_filename_sha256": hashlib.sha256(
            source.filename.encode("utf-8")
        ).hexdigest(),
        "upload_content_type_sha256": hashlib.sha256(
            b"application/pdf"
        ).hexdigest(),
    }


def _sandboxed_production_worker_command(
    command: tuple[str, ...],
) -> tuple[str, ...]:
    wrapped = sandboxed_worker_command(command)
    expected_prefix = (
        OS_NETWORK_SANDBOX_EXECUTABLE,
        "-p",
        OS_NETWORK_SANDBOX_PROFILE,
    )
    if wrapped[:3] != expected_prefix or wrapped[3:] != command:
        raise RuntimeError("production worker sandbox command identity differs")
    return wrapped


def _prebind_fatal_sha256(launch: _GuardedWorkerLaunch) -> str | None:
    try:
        raw = launch.prebind_fatal_path.read_bytes()
    except FileNotFoundError:
        return None
    if not raw or len(raw) > 16 * 1024:
        raise ValueError("worker prebind fatal record is empty or oversized")
    record = PrebindFatalRecord.model_validate_json(raw)
    if canonical_model_bytes(record) != raw:
        raise ValueError("worker prebind fatal record is not canonical")
    if (
        record.attempt_id != launch.attempt_id
        or launch.worker_identity is None
        or record.worker_pid != launch.worker_identity.pid
        or record.worker_create_time_ns != launch.worker_identity.create_time_ns
        or record.worker_pgid != launch.worker_identity.process_group_id
        or record.worker_sid != launch.worker_identity.session_id
        or record.absolute_deadline_monotonic_ns
        != launch.absolute_deadline_monotonic_ns
    ):
        raise ValueError("worker prebind fatal binding differs")
    return hashlib.sha256(raw).hexdigest()


def _prebind_fatal_receipt_identity(
    launch: _GuardedWorkerLaunch,
) -> tuple[str | None, bool]:
    """Never let non-authoritative protocol parsing suppress a failed receipt."""

    try:
        return _prebind_fatal_sha256(launch), False
    except BaseException:
        try:
            raw = launch.prebind_fatal_path.read_bytes()
        except BaseException:
            return None, True
        if not raw or len(raw) > 16 * 1024:
            return None, True
        return hashlib.sha256(raw).hexdigest(), True


def _launch_custody_receipt_fields(
    launch: _GuardedWorkerLaunch,
    controller_resources: ControllerResourceBoundary,
) -> dict[str, object]:
    prebind_sha256, prebind_validation_failed = (
        _prebind_fatal_receipt_identity(launch)
    )
    return {
        "controller_resources": controller_resources,
        "launch_intent_sha256": launch.intent.intent_sha256,
        "launch_record_sha256": (
            launch.launch_record.launch_sha256
            if launch.launch_record is not None
            else None
        ),
        "launch_failure_record_sha256": (
            launch.launch_failure_record.record_sha256
            if launch.launch_failure_record is not None
            else None
        ),
        "phase_deadline_log_sha256": launch.phase_deadline_log_sha256,
        "phase_ack_log_sha256": launch.phase_ack_log_sha256,
        "phase_sequence_count": launch.phase_sequence_count,
        "watchdog_terminal_sha256": launch.watchdog_terminal_sha256,
        "watchdog_terminal_observed_sha256": (
            launch.watchdog_terminal_observed_sha256
        ),
        "watchdog_terminal_validation_failed": (
            launch.watchdog_terminal_validation_failed
        ),
        "watchdog_terminal": launch.watchdog_terminal,
        "launcher_terminal_evidence": getattr(
            launch, "launcher_terminal_evidence", None
        ),
        "terminal_request_control_transcript": (
            getattr(launch, "request_control_terminal_transcript", None)
        ),
        "immutable_input_custody": (
            getattr(launch, "immutable_input_custody_evidence", None)
        ),
        "immutable_input_custody_validation_failed": (
            getattr(
                launch,
                "immutable_input_custody_validation_failed",
                False,
            )
        ),
        "watchdog_reaped": launch.watchdog_reaped,
        "watchdog_process_group_gone": launch.watchdog_group_gone,
        "watchdog_excluded_from_worker_request_tree": True,
        "prebind_fatal_record_sha256": prebind_sha256,
        "prebind_fatal_record_validation_failed": prebind_validation_failed,
    }


def _worker_stream_receipt_fields(
    launch: _GuardedWorkerLaunch,
) -> dict[str, object]:
    disposition = (
        launch.capture.disposition
        if launch.capture is not None
        else "incomplete_observed_prefix_forced_close"
    )
    broker_capture = getattr(launch, "broker_capture", None)
    broker_process = getattr(launch, "broker", None)
    broker_disposition = (
        broker_capture.disposition
        if broker_capture is not None
        else "not_applicable"
    )
    return {
        "stdout_size_bytes": launch.stdout_observed_size_bytes,
        "stdout_sha256": launch.stdout_observed_sha256,
        "stderr_size_bytes": launch.stderr_observed_size_bytes,
        "stderr_sha256": launch.stderr_observed_sha256,
        "worker_stream_capture_disposition": disposition,
        "worker_combined_output_limit_bytes": MAXIMUM_WORKER_COMBINED_BYTES,
        "broker_process_group_count": 1 if broker_process is not None else 0,
        "broker_return_code": (
            broker_process.returncode if broker_process is not None else None
        ),
        "broker_stdout_size_bytes": getattr(
            launch, "broker_stdout_observed_size_bytes", 0
        ),
        "broker_stdout_sha256": getattr(
            launch,
            "broker_stdout_observed_sha256",
            hashlib.sha256(b"").hexdigest(),
        ),
        "broker_stderr_size_bytes": getattr(
            launch, "broker_stderr_observed_size_bytes", 0
        ),
        "broker_stderr_sha256": getattr(
            launch,
            "broker_stderr_observed_sha256",
            hashlib.sha256(b"").hexdigest(),
        ),
        "broker_stream_capture_disposition": broker_disposition,
        "broker_reaped": getattr(launch, "broker_reaped", False),
        "broker_process_group_gone": getattr(
            launch, "broker_group_gone", False
        ),
    }


def _retain_post_launch_failure_receipt(
    *,
    path: Path,
    attempt_id: str,
    source: SourceIdentity,
    execution: ExecutionIdentity,
    configuration: ConfigurationIdentity,
    started_at_utc: datetime,
    started_monotonic_ns: int,
    process: subprocess.Popen[bytes] | None,
    stdout: bytes,
    stderr: bytes,
    forced_group_cleanup_required: bool,
    all_group_members_gone: bool,
    error: BaseException,
    controller_resources: ControllerResourceBoundary,
    launch: _GuardedWorkerLaunch,
) -> ProductionAttemptReceipt:
    """O_EXCL-retain a valid failed receipt for any post-launch exception."""

    completed_at = datetime.now(UTC)
    failure = FailureRecord(
        code=FailureCode.WORKER_PROTOCOL_FAILED,
        stage="shutdown",
        detail_sha256=_canonical_sha256(
            {
                "error_type": f"{type(error).__module__}.{type(error).__qualname__}"
            }
        ),
    )
    receipt = ProductionAttemptReceipt(
        schema_id="phase-latency-prewarm-attempt-receipt-v1",
        attempt_id=attempt_id,
        source=source,
        execution=execution,
        configuration=configuration,
        started_at_utc=started_at_utc,
        completed_at_utc=completed_at,
        controller_elapsed_ns=max(
            0, time.monotonic_ns() - started_monotonic_ns
        ),
        worker_return_code=(
            process.returncode
            if process is not None and process.returncode is not None
            else -1
        ),
        forced_group_cleanup_required=forced_group_cleanup_required,
        all_group_members_gone=all_group_members_gone,
        status=AttemptStatus.ERROR,
        failure=failure,
        attempt=None,
        **_worker_stream_receipt_fields(launch),
        **_launch_custody_receipt_fields(launch, controller_resources),
    )
    write_private_canonical(path, receipt)
    return receipt


def run_direct_rollback_attempt(
    *,
    workspace: Path,
    output_directory: Path,
    prepared: PreparedProductionRuntime,
    source: SourceIdentity,
    expectation: CurrentRuntimeOutputExpectation,
) -> tuple[
    DirectRollbackAttemptReceipt,
    UninstrumentedRollbackObservation,
    Path,
    Path,
]:
    """Run one direct flag-off request with no private broker capability."""

    attempt_id = f"lat-us02-rollback-{source.case_id}"
    protocol = Path(
        tempfile.mkdtemp(prefix=f".{attempt_id}-", dir=output_directory)
    )
    os.chmod(protocol, 0o700)
    guard_root = protocol / "guard"
    guard_root.mkdir(mode=0o700)
    materialize_private_child_network_guard(workspace, guard_root)
    environment = _attempt_environment(
        workspace=workspace,
        prepared=prepared,
        guard_root=guard_root,
        mode=RunMode.PREDECESSOR,
    )
    if any(
        name.startswith("PARSER_TESSERACT_")
        or name == "PARSER_LATENCY_PRIVATE_BROKER_PREDECESSOR"
        for name in environment
    ):
        raise RuntimeError("direct rollback environment contains broker authority")
    settings = _settings_from_environment(environment)
    configuration = rollback_output_configuration_identity(
        startup_timeout_ns=300_000_000_000,
        application_settings_sha256=_settings_sha256(settings),
        worker_environment_sha256=worker_environment_sha256(environment),
        application_settings_projection=sanitized_configuration_projection(
            domain="application_settings", values=asdict(settings)
        ),
        worker_environment_projection=sanitized_configuration_projection(
            domain="worker_environment", values=environment
        ),
        artifacts_path=prepared.artifact_identity.path,
        artifacts_path_identity_sha256=_resolved_path_identity(
            Path(str(settings.docling_artifacts_path))
        ),
        tesseract_executable=settings.tesseract_cmd,
        tesseract_data_path=str(settings.tesseract_data_path),
    )
    source_contract = protocol / "source.json"
    configuration_contract = protocol / "configuration.json"
    write_private_canonical(source_contract, source)
    write_private_canonical(configuration_contract, configuration)
    command = _sandboxed_production_worker_command(
        (
            sys.executable,
            "-m",
            "tests.benchmarks.latency_prewarm_production_worker",
            "--workspace",
            str(workspace),
            "--source",
            str((workspace / source.path).resolve(strict=True)),
            "--source-identity",
            str(source_contract),
            "--configuration",
            str(configuration_contract),
            "--mode",
            RunMode.PREDECESSOR.value,
            "--application-sha256",
            prepared.execution.application_code_sha256,
            "--dependency-manifest-sha256",
            prepared.execution.dependency_manifest_sha256,
            "--dependency-runtime-sha256",
            str(prepared.execution.dependency_runtime_sha256),
            "--parser-runtime-sha256",
            prepared.execution.parser_runtime_sha256,
            "--runtime-artifacts-sha256",
            prepared.artifact_identity.sha256,
            "--harness-sha256",
            prepared.execution.harness_sha256,
            "--network-isolation-sha256",
            str(prepared.execution.network_isolation_sha256),
        )
    )
    receipt_path = output_directory / f"{attempt_id}-receipt.json"
    started_at = datetime.now(UTC)
    started_ns = time.monotonic_ns()
    launch: _GuardedWorkerLaunch | None = None
    failure_stage: Literal[
        "startup", "identity_validation", "request", "shutdown"
    ] = "startup"
    try:
        try:
            launch = _guarded_worker_launch(
                attempt_id=attempt_id,
                workspace=workspace,
                output_directory=output_directory,
                protocol=protocol,
                environment=environment,
                base_command=command,
                attempt_budget_ns=(300 + 330 + 30) * 1_000_000_000,
                startup_timeout_ns=int(configuration.startup_timeout_ns or 0),
            )
        except _GuardedLaunchError as error:
            launch = error.launch
            raise error.error
        process = launch.process
        if process is None:
            raise RuntimeError("direct rollback worker process is absent")
        failure_stage = "request"
        stdout, stderr = launch.capture_until_exit()
        failure_stage = "shutdown"
        launch.collect_watchdog()
        controller_resources = launch.controller_boundary()
        if (
            process.returncode != 0
            or stderr
            or launch.stream_limit_exceeded
            or launch.stream_cleanup_forced
            or not launch.worker_group_disappeared()
            or launch.broker is not None
            or launch.watchdog_terminal is None
            or launch.watchdog_terminal.outcome != "worker_exited"
            or not launch.watchdog_reaped
            or not launch.watchdog_group_gone
            or launch.launch_record is None
            or launch.phase_deadline_log_sha256 is None
            or launch.phase_ack_log_sha256 is None
            or launch.phase_sequence_count != 3
            or launch.watchdog_terminal_sha256 is None
            or launch.watchdog_terminal_observed_sha256
            != launch.watchdog_terminal_sha256
            or not controller_resources.threads_returned_to_baseline
            or not controller_resources.file_descriptors_returned_to_baseline
        ):
            raise RuntimeError("direct rollback process custody differs")
        failure_stage = "identity_validation"
        raw_worker = DirectRollbackRawWorkerEnvelope.model_validate_json(stdout)
        if canonical_model_bytes(raw_worker) != stdout:
            raise RuntimeError("direct rollback raw worker is not canonical")
        if (
            raw_worker.source != source
            or raw_worker.configuration_sha256 != configuration.sha256
            or raw_worker.output.semantic_sha256 != expectation.semantic_sha256
        ):
            raise RuntimeError("direct rollback output expectation differs")
        completed_at = datetime.now(UTC)
        receipt = _direct_rollback_attempt_receipt(
            attempt_id=attempt_id,
            source=source,
            execution=prepared.execution,
            configuration=configuration,
            started_at_utc=started_at,
            completed_at_utc=completed_at,
            controller_elapsed_ns=max(0, time.monotonic_ns() - started_ns),
            worker_return_code=0,
            stdout_size_bytes=len(stdout),
            stdout_sha256=hashlib.sha256(stdout).hexdigest(),
            stderr_size_bytes=0,
            stderr_sha256=hashlib.sha256(b"").hexdigest(),
            launch_intent_sha256=launch.intent.intent_sha256,
            launch_record_sha256=launch.launch_record.launch_sha256,
            phase_deadline_log_sha256=launch.phase_deadline_log_sha256,
            phase_ack_log_sha256=launch.phase_ack_log_sha256,
            phase_sequence_count=3,
            watchdog_terminal_sha256=launch.watchdog_terminal_sha256,
            watchdog_terminal_observed_sha256=(
                launch.watchdog_terminal_observed_sha256
            ),
            watchdog_terminal=launch.watchdog_terminal,
            launcher_terminal_evidence=launch.launcher_terminal_evidence,
            watchdog_reaped=True,
            watchdog_process_group_gone=True,
            worker_reaped=True,
            worker_process_group_gone=True,
            forced_group_cleanup_required=False,
            controller_resources=controller_resources,
            raw_worker=raw_worker,
            status=AttemptStatus.SUCCESS,
        )
        write_private_canonical(receipt_path, receipt)
        artifact_path = _retain_and_require_artifact_observation(
            output_directory=output_directory,
            attempt_id=attempt_id,
            prepared=prepared,
            artifacts_path=Path(
                prepared.artifact_materialization.target_resolved_runtime_path
            ),
        )
        cleanup = CleanupEvidence(
            shutdown_duration_ns=raw_worker.shutdown_duration_ns,
            cleanup_completed=True,
            worker_exited=True,
            worker_reaped=True,
            exit_code=0,
            owned_process_count_after_shutdown=0,
            all_owned_processes_reaped=True,
            threads_returned_to_baseline=True,
            file_descriptors_returned_to_baseline=True,
            state_retention_detected=False,
            oom_observed=False,
            unbounded_rss_growth_observed=False,
            worker_process_group_count=1,
            broker_process_group_count=0,
            controller_watchdog_process_group_count=1,
            owned_process_group_count=2,
        )
        receipt_sha256 = hashlib.sha256(
            canonical_model_bytes(receipt)
        ).hexdigest()
        artifact_sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        observation = UninstrumentedRollbackObservation(
            case_id=source.case_id,
            source=source,
            expectation=expectation,
            configuration=configuration,
            output=raw_worker.output,
            normalized_output_witness=raw_worker.normalized_output_witness,
            runtime_artifact_before_requests=(
                raw_worker.runtime_artifact_before_requests
            ),
            runtime_artifact_after_shutdown=(
                raw_worker.runtime_artifact_after_shutdown
            ),
            cleanup=cleanup,
            canonical_receipt_jsonl=canonical_model_bytes(receipt).decode(
                "utf-8", errors="strict"
            ),
            receipt_sha256=receipt_sha256,
            artifact_observation_sha256=artifact_sha256,
        )
        return receipt, observation, receipt_path, artifact_path
    except BaseException as error:
        if launch is not None:
            with contextlib.suppress(BaseException):
                launch.cleanup_managed_groups()
            with contextlib.suppress(BaseException):
                launch.collect_watchdog()
        if not receipt_path.exists():
            controller_resources: ControllerResourceBoundary | None = None
            controller_resources_validation_failed = True
            worker_process_group_gone = False
            if launch is not None:
                try:
                    controller_resources = launch.controller_boundary()
                    controller_resources_validation_failed = False
                except BaseException:
                    controller_resources = None
                    controller_resources_validation_failed = True
                with contextlib.suppress(BaseException):
                    worker_process_group_gone = launch.worker_group_disappeared()
            empty_sha256 = hashlib.sha256(b"").hexdigest()
            watchdog_terminal = (
                launch.watchdog_terminal if launch is not None else None
            )
            failure_receipt = _direct_rollback_failure_receipt(
                attempt_id=attempt_id,
                source=source,
                execution=prepared.execution,
                configuration=configuration,
                started_at_utc=started_at,
                completed_at_utc=datetime.now(UTC),
                controller_elapsed_ns=max(0, time.monotonic_ns() - started_ns),
                worker_return_code=(
                    launch.process.returncode
                    if launch is not None
                    and launch.process is not None
                    and launch.process.returncode is not None
                    else None
                ),
                stdout_size_bytes=(
                    launch.stdout_observed_size_bytes
                    if launch is not None
                    else 0
                ),
                stdout_sha256=(
                    launch.stdout_observed_sha256
                    if launch is not None
                    else empty_sha256
                ),
                stderr_size_bytes=(
                    launch.stderr_observed_size_bytes
                    if launch is not None
                    else 0
                ),
                stderr_sha256=(
                    launch.stderr_observed_sha256
                    if launch is not None
                    else empty_sha256
                ),
                launch_intent_sha256=(
                    launch.intent.intent_sha256 if launch is not None else None
                ),
                launch_record_sha256=(
                    launch.launch_record.launch_sha256
                    if launch is not None and launch.launch_record is not None
                    else None
                ),
                phase_deadline_log_sha256=(
                    launch.phase_deadline_log_sha256
                    if launch is not None
                    else None
                ),
                phase_ack_log_sha256=(
                    launch.phase_ack_log_sha256 if launch is not None else None
                ),
                watchdog_terminal_sha256=(
                    hashlib.sha256(
                        canonical_model_bytes(watchdog_terminal)
                    ).hexdigest()
                    if watchdog_terminal is not None
                    else None
                ),
                watchdog_terminal=watchdog_terminal,
                launcher_terminal_evidence=(
                    launch.launcher_terminal_evidence
                    if launch is not None
                    else None
                ),
                cleanup_attempted=True,
                worker_process_group_gone=worker_process_group_gone,
                watchdog_reaped=(
                    launch.watchdog_reaped if launch is not None else False
                ),
                watchdog_process_group_gone=(
                    launch.watchdog_group_gone if launch is not None else False
                ),
                controller_resources=controller_resources,
                controller_resources_validation_failed=(
                    controller_resources_validation_failed
                ),
                status=AttemptStatus.ERROR,
                failure=FailureRecord(
                    code=(
                        FailureCode.STARTUP_CANCELLED
                        if isinstance(error, _ControllerTerminationSignal)
                        else FailureCode.REQUEST_FAILED
                        if failure_stage == "request"
                        else FailureCode.IDENTITY_VALIDATION_FAILED
                        if failure_stage == "identity_validation"
                        else FailureCode.CLEANUP_FAILED
                        if failure_stage == "shutdown"
                        else FailureCode.WORKER_PROTOCOL_FAILED
                    ),
                    stage=failure_stage,
                    detail_sha256=_canonical_sha256(
                        {
                            "error_type": (
                                f"{type(error).__module__}."
                                f"{type(error).__qualname__}"
                            ),
                            "failure_stage": failure_stage,
                            "controller_signal": (
                                error.signum
                                if isinstance(
                                    error, _ControllerTerminationSignal
                                )
                                else None
                            ),
                        }
                    ),
                ),
            )
            write_private_canonical(receipt_path, failure_receipt)
        raise
    finally:
        shutil.rmtree(protocol, ignore_errors=True)


@_with_scoped_signal_cleanup
def run_production_attempt(
    *,
    workspace: Path,
    output_directory: Path,
    prepared: PreparedProductionRuntime,
    source: SourceIdentity,
    mode: RunMode,
    repetition_index: int,
    request_count: int,
) -> ProductionAttemptReceipt:
    attempt_id = f"lat-us02-{source.case_id}-{mode.value}-r{repetition_index:02d}"
    protocol = Path(
        tempfile.mkdtemp(prefix=f".{attempt_id}-", dir=output_directory)
    )
    os.chmod(protocol, 0o700)
    guard_root = protocol / "guard"
    guard_root.mkdir(mode=0o700)
    materialize_private_child_network_guard(workspace, guard_root)
    broker_request_root = protocol / "broker-requests"
    broker_request_root.mkdir(mode=0o700)
    staged_executable_root = protocol / "staged-executable"
    staged_executable_root.mkdir(mode=0o700)
    environment = _attempt_environment(
        workspace=workspace,
        prepared=prepared,
        guard_root=guard_root,
        mode=mode,
        worker_scratch_root=broker_request_root,
    )
    settings = _settings_from_environment(environment)
    configuration = production_configuration_identity(
        prewarm_enabled=mode is RunMode.ENABLED,
        startup_timeout_ns=300_000_000_000,
        request_count=request_count,
        application_settings_sha256=_settings_sha256(settings),
        worker_environment_sha256=worker_environment_sha256(environment),
        application_settings_projection=sanitized_configuration_projection(
            domain="application_settings", values=asdict(settings)
        ),
        worker_environment_projection=sanitized_configuration_projection(
            domain="worker_environment",
            values=_prebound_broker_projection_environment(
                environment, request_root=broker_request_root
            ),
        ),
        artifacts_path=prepared.artifact_identity.path,
        artifacts_path_identity_sha256=_resolved_path_identity(
            Path(str(settings.docling_artifacts_path))
        ),
        tesseract_executable=settings.tesseract_cmd,
        tesseract_data_path=str(settings.tesseract_data_path),
    )
    source_path = workspace / source.path
    source_contract = protocol / "source.json"
    configuration_contract = protocol / "configuration.json"
    write_private_canonical(source_contract, source)

    def commit_configuration(final_environment: dict[str, str]) -> None:
        nonlocal configuration
        configuration = production_configuration_identity(
            prewarm_enabled=mode is RunMode.ENABLED,
            startup_timeout_ns=300_000_000_000,
            request_count=request_count,
            application_settings_sha256=_settings_sha256(settings),
            worker_environment_sha256=worker_environment_sha256(environment),
            application_settings_projection=sanitized_configuration_projection(
                domain="application_settings", values=asdict(settings)
            ),
            worker_environment_projection=sanitized_configuration_projection(
                domain="worker_environment", values=final_environment
            ),
            artifacts_path=prepared.artifact_identity.path,
            artifacts_path_identity_sha256=_resolved_path_identity(
                Path(str(settings.docling_artifacts_path))
            ),
            tesseract_executable=settings.tesseract_cmd,
            tesseract_data_path=str(settings.tesseract_data_path),
        )
        write_private_canonical(configuration_contract, configuration)
    command = (
            sys.executable,
            "-m",
            "tests.benchmarks.latency_prewarm_production_worker",
            "--workspace",
            str(workspace),
            "--source",
            str(source_path),
            "--source-identity",
            str(source_contract),
            "--configuration",
            str(configuration_contract),
            "--mode",
            mode.value,
            "--application-sha256",
            prepared.execution.application_code_sha256,
            "--dependency-manifest-sha256",
            prepared.execution.dependency_manifest_sha256,
            "--dependency-runtime-sha256",
            str(prepared.execution.dependency_runtime_sha256),
            "--parser-runtime-sha256",
            prepared.execution.parser_runtime_sha256,
            "--runtime-artifacts-sha256",
            prepared.artifact_identity.sha256,
            "--harness-sha256",
            prepared.execution.harness_sha256,
            "--network-isolation-sha256",
            str(prepared.execution.network_isolation_sha256),
    )
    started_at = datetime.now(UTC)
    started_ns = time.monotonic_ns()
    receipt_path = output_directory / f"{attempt_id}.json"
    stdout = b""
    stderr = b""
    forced_cleanup = False
    group_gone = False
    launch: _GuardedWorkerLaunch | None = None
    try:
        try:
            launch = _guarded_worker_launch(
                attempt_id=attempt_id,
                workspace=workspace,
                output_directory=output_directory,
                protocol=protocol,
                environment=environment,
                base_command=command,
                attempt_budget_ns=(
                    300 + request_count * 330 + 30
                )
                * 1_000_000_000,
                startup_timeout_ns=int(configuration.startup_timeout_ns or 0),
                brokered=BrokeredLaunchInputs(
                    tesseract_executable=Path(settings.tesseract_cmd).resolve(
                        strict=True
                    ),
                    tesseract_data_path=Path(
                        str(settings.tesseract_data_path)
                    ).resolve(strict=True),
                    immutable_artifact_root=Path(
                        str(settings.docling_artifacts_path)
                    ).resolve(strict=True),
                    allowed_languages=tuple(
                        sorted(set(settings.ocr_languages))
                    ),
                    request_root=broker_request_root.resolve(strict=True),
                    worker_scratch_root=broker_request_root.resolve(strict=True),
                    staged_executable_root=staged_executable_root.resolve(
                        strict=True
                    ),
                    child_wrapper_path=(
                        workspace / "app/services/tesseract_child_exec.py"
                    ).resolve(strict=True),
                ),
                request_count=request_count,
                commit_worker_configuration=commit_configuration,
            )
        except _GuardedLaunchError as error:
            launch = error.launch
            raise error.error
        process = launch.process
        if process is None:
            raise RuntimeError("production worker process is absent after launch")
        timed_out = False
        try:
            launch.drive_external_request_control(
                sources=tuple(source for _index in range(request_count)),
                request_timeout_ns=int(configuration.request_timeout_ns or 0),
            )
            stdout, stderr = launch.capture_until_exit()
        except subprocess.TimeoutExpired:
            timed_out = True
            forced_cleanup = launch.cleanup_managed_groups()
            stdout, stderr = launch.capture_until_exit()
        forced_cleanup = launch.cleanup_managed_groups() or forced_cleanup
        forced_cleanup = launch.stream_cleanup_forced or forced_cleanup
        group_gone = (
            launch.worker_group_disappeared()
            and launch.broker_group_disappeared()
        )
        launch.collect_watchdog()
        controller_resources = launch.controller_boundary()
        completed_at = datetime.now(UTC)
        elapsed_ns = time.monotonic_ns() - started_ns
        failure: FailureRecord | None = None
        attempt: LocalPrewarmAttempt | None = None
        status = AttemptStatus.SUCCESS
        custody_ok = bool(
            launch.watchdog_terminal is not None
            and launch.watchdog_terminal.outcome == "worker_exited"
            and launch.watchdog_reaped
            and launch.watchdog_group_gone
            and launch.broker is not None
            and launch.broker_reaped
            and launch.broker_group_gone
            and launch.broker_identity is not None
            and launch.watchdog_terminal.broker_group_disappearance_confirmed
            is True
            and launch.broker_capture is not None
            and launch.broker_capture.complete
            and not launch.broker_capture.overflow
            and not launch.broker_stream_limit_exceeded
            and launch.immutable_input_custody_evidence is not None
            and not launch.immutable_input_custody_validation_failed
            and controller_resources.threads_returned_to_baseline
            and controller_resources.file_descriptors_returned_to_baseline
            and _prebind_fatal_sha256(launch) is None
            and launch.capture is not None
            and launch.capture.complete
            and not launch.capture.overflow
            and len(stdout) == launch.stdout_observed_size_bytes
            and hashlib.sha256(stdout).hexdigest()
            == launch.stdout_observed_sha256
            and len(stderr) == launch.stderr_observed_size_bytes
            and hashlib.sha256(stderr).hexdigest()
            == launch.stderr_observed_sha256
        )
        if (
            timed_out
            or process.returncode != 0
            or len(stdout) > MAXIMUM_WORKER_STDOUT_BYTES
            or len(stderr) > MAXIMUM_WORKER_STDERR_BYTES
            or launch.stream_limit_exceeded
            or forced_cleanup
            or not group_gone
            or not custody_ok
        ):
            status = AttemptStatus.TIMEOUT if timed_out else AttemptStatus.ERROR
            failure = FailureRecord(
                code=(
                    FailureCode.STARTUP_TIMEOUT
                    if timed_out
                    else FailureCode.WORKER_PROTOCOL_FAILED
                ),
                stage="startup" if timed_out else "shutdown",
                detail_sha256=hashlib.sha256(stderr).hexdigest(),
            )
        else:
            try:
                raw_worker = ProductionRawWorkerEnvelope.model_validate_json(
                    stdout
                )
                if canonical_model_bytes(raw_worker) != stdout:
                    raise ValueError(
                        "production raw worker envelope is not canonical"
                    )
                if (
                    launch.child_watch_log_path is None
                    or launch.request_control is None
                    or launch.request_control.readiness_evidence is None
                    or launch.request_control_terminal_transcript is None
                    or launch.immutable_input_custody_evidence is None
                    or launch.immutable_input_custody_validation_failed
                    or launch.request_resource_sample_log_sha256 is None
                    or launch.request_resource_sample_log_row_count is None
                    or launch.request_resource_sample_log_size_bytes is None
                ):
                    raise ValueError(
                        "production controller evidence custody is incomplete"
                    )
                worker = _assemble_production_worker_envelope(
                    attempt_id=attempt_id,
                    mode=mode,
                    source=source,
                    raw=raw_worker,
                    boundaries=launch.external_request_boundaries,
                    request_control_readiness=(
                        launch.request_control.readiness_evidence
                    ),
                    terminal_request_control_transcript=(
                        launch.request_control_terminal_transcript
                    ),
                    immutable_input_custody=(
                        launch.immutable_input_custody_evidence
                    ),
                    child_watch_log_path=launch.child_watch_log_path,
                    request_resource_log_sha256=(
                        launch.request_resource_sample_log_sha256
                    ),
                    request_resource_log_row_count=(
                        launch.request_resource_sample_log_row_count
                    ),
                    request_resource_log_size_bytes=(
                        launch.request_resource_sample_log_size_bytes
                    ),
                )
                cleanup_ok = bool(
                    worker.resources.shutdown.process_count == 1
                    and worker.resources.shutdown.thread_count
                    <= worker.resources.cold_initialization.thread_count
                    and worker.resources.shutdown.file_descriptor_count
                    <= worker.resources.cold_initialization.file_descriptor_count
                    and not worker.state_retention_detected
                    and not worker.oom_observed
                    and not worker.unbounded_rss_growth_observed
                    and custody_ok
                )
                if not cleanup_ok:
                    status = AttemptStatus.ERROR
                    failure = FailureRecord(
                        code=FailureCode.CLEANUP_FAILED,
                        stage="shutdown",
                        detail_sha256=_canonical_sha256(
                            worker.resources.model_dump(mode="json")
                        ),
                    )
                cleanup = CleanupEvidence(
                    shutdown_duration_ns=worker.shutdown_duration_ns,
                    cleanup_completed=cleanup_ok,
                    worker_exited=True,
                    worker_reaped=True,
                    exit_code=process.returncode,
                    owned_process_count_after_shutdown=0,
                    all_owned_processes_reaped=True,
                    threads_returned_to_baseline=(
                        worker.resources.shutdown.thread_count
                        <= worker.resources.cold_initialization.thread_count
                    ),
                    file_descriptors_returned_to_baseline=(
                        worker.resources.shutdown.file_descriptor_count
                        <= worker.resources.cold_initialization.file_descriptor_count
                    ),
                    state_retention_detected=worker.state_retention_detected,
                    oom_observed=worker.oom_observed,
                    unbounded_rss_growth_observed=(
                        worker.unbounded_rss_growth_observed
                    ),
                    controller_watchdog_process_group_count=1,
                    broker_process_group_count=1,
                    owned_process_group_count=3,
                )
                attempt = LocalPrewarmAttempt(
                    schema_id="phase-latency-prewarm-attempt-v1",
                    attempt_id=attempt_id,
                    case_id=source.case_id,
                    repetition_index=repetition_index,
                    mode=mode,
                    started_at_utc=started_at,
                    completed_at_utc=completed_at,
                    source=source,
                    execution=prepared.execution,
                    configuration=configuration,
                    worker=worker,
                    cleanup=cleanup,
                    status=status,
                    failure=failure,
                )
                if status is AttemptStatus.SUCCESS:
                    blocking = evaluate_local_prewarm_attempt_blocking_failures(
                        attempt, production_required=True
                    )
                    if blocking:
                        failure = FailureRecord(
                            code=FailureCode.IDENTITY_VALIDATION_FAILED,
                            stage="identity_validation",
                            detail_sha256=_canonical_sha256(
                                [str(item) for item in blocking]
                            ),
                        )
                        status = AttemptStatus.ERROR
                        attempt = LocalPrewarmAttempt.model_validate(
                            {
                                **attempt.model_dump(mode="python"),
                                "status": status,
                                "failure": failure,
                            }
                        )
            except BaseException as error:
                status = AttemptStatus.ERROR
                failure = FailureRecord(
                    code=FailureCode.WORKER_PROTOCOL_FAILED,
                    stage="shutdown",
                    detail_sha256=_canonical_sha256(
                        {
                            "error_type": (
                                f"{type(error).__module__}."
                                f"{type(error).__qualname__}"
                            )
                        }
                    ),
                )
                attempt = None
        receipt = ProductionAttemptReceipt(
            schema_id="phase-latency-prewarm-attempt-receipt-v1",
            attempt_id=attempt_id,
            source=source,
            execution=prepared.execution,
            configuration=configuration,
            started_at_utc=started_at,
            completed_at_utc=completed_at,
            controller_elapsed_ns=elapsed_ns,
            worker_return_code=(
                process.returncode if process.returncode is not None else -1
            ),
            forced_group_cleanup_required=forced_cleanup,
            all_group_members_gone=group_gone,
            status=status,
            failure=failure,
            attempt=attempt,
            **_worker_stream_receipt_fields(launch),
            **_launch_custody_receipt_fields(launch, controller_resources),
        )
        write_private_canonical(receipt_path, receipt)
        return receipt
    except _ControllerTerminationSignal as error:
        if launch is None:
            raise
        process = launch.process
        if process is not None:
            try:
                forced_cleanup = launch.cleanup_managed_groups() or forced_cleanup
            except BaseException:
                forced_cleanup = True
            try:
                stdout, stderr = launch.capture_until_exit()
            except BaseException:
                pass
            try:
                group_gone = (
                    launch.worker_group_disappeared()
                    and launch.broker_group_disappeared()
                )
            except BaseException:
                group_gone = False
        else:
            launch.close_release()
            group_gone = True
        launch.collect_watchdog()
        controller_resources = launch.controller_boundary()
        if not receipt_path.exists():
            _retain_post_launch_failure_receipt(
                path=receipt_path,
                attempt_id=attempt_id,
                source=source,
                execution=prepared.execution,
                configuration=configuration,
                started_at_utc=started_at,
                started_monotonic_ns=started_ns,
                process=process,
                stdout=stdout,
                stderr=stderr,
                forced_group_cleanup_required=forced_cleanup,
                all_group_members_gone=group_gone,
                error=error,
                controller_resources=controller_resources,
                launch=launch,
            )
        try:
            _retain_and_require_artifact_observation(
                output_directory=output_directory,
                attempt_id=attempt_id,
                prepared=prepared,
                artifacts_path=Path(
                    prepared.artifact_materialization.target_resolved_runtime_path
                ),
            )
        except BaseException as artifact_error:
            raise artifact_error from error
        raise
    except BaseException as error:
        if launch is None:
            raise
        process = launch.process
        if process is not None:
            try:
                forced_cleanup = launch.cleanup_managed_groups() or forced_cleanup
            except BaseException:
                forced_cleanup = True
            try:
                stdout, stderr = launch.capture_until_exit()
            except BaseException:
                pass
            try:
                group_gone = (
                    launch.worker_group_disappeared()
                    and launch.broker_group_disappeared()
                )
            except BaseException:
                group_gone = False
        else:
            launch.close_release()
            group_gone = True
        launch.collect_watchdog()
        controller_resources = launch.controller_boundary()
        if receipt_path.exists():
            raise
        return _retain_post_launch_failure_receipt(
            path=receipt_path,
            attempt_id=attempt_id,
            source=source,
            execution=prepared.execution,
            configuration=configuration,
            started_at_utc=started_at,
            started_monotonic_ns=started_ns,
            process=process,
            stdout=stdout,
            stderr=stderr,
            forced_group_cleanup_required=forced_cleanup,
            all_group_members_gone=group_gone,
            error=error,
            controller_resources=controller_resources,
            launch=launch,
        )
    finally:
        shutil.rmtree(protocol, ignore_errors=True)


def _retain_and_require_artifact_observation(
    *,
    output_directory: Path,
    attempt_id: str,
    prepared: PreparedProductionRuntime,
    artifacts_path: Path,
) -> Path:
    path = output_directory / f"{attempt_id}-artifact-observation.json"
    if path.exists():
        raw = path.read_bytes()
        observation = PostAttemptArtifactObservation.model_validate_json(raw)
        if canonical_model_bytes(observation) != raw:
            raise RuntimeError("retained artifact observation is not canonical")
        if (
            observation.attempt_id != attempt_id
            or observation.preflight_manifest_sha256
            != prepared.artifact_materialization.manifest_sha256
            or observation.target_resolved_runtime_path
            != str(artifacts_path.resolve(strict=True))
        ):
            raise RuntimeError("retained artifact observation binding differs")
    else:
        observation = _observe_post_attempt_artifact(
            attempt_id=attempt_id,
            prepared=prepared,
            artifacts_path=artifacts_path,
        )
        write_private_canonical(path, observation)
    if not observation.matches_preflight:
        raise RuntimeError(
            f"artifact custody failed after retained {attempt_id}"
        )
    return path


def _output_parity_signature(attempt: LocalPrewarmAttempt) -> tuple[tuple[str, ...], ...]:
    signatures = []
    for request in attempt.worker.requests:
        if request.output is None:
            raise RuntimeError("successful attempt lacks retained output identity")
        output = request.output
        if any(
            value is None
            for value in (
                output.api_contract_sha256,
                output.provenance_sha256,
                output.concerns_sha256,
                output.deterministic_ids_sha256,
            )
        ):
            raise RuntimeError("production output component identity is incomplete")
        signatures.append(
            (
                output.normalized_sha256,
                output.semantic_sha256,
                str(output.api_contract_sha256),
                str(output.provenance_sha256),
                str(output.concerns_sha256),
                str(output.deterministic_ids_sha256),
                output.media_type,
            )
        )
    return tuple(signatures)


def _require_current_runtime_output(
    attempt: LocalPrewarmAttempt,
    expectation: CurrentRuntimeOutputExpectation,
) -> None:
    if (
        attempt.case_id != expectation.case_id
        or attempt.source.sha256 != expectation.source_sha256
        or not attempt.worker.requests
        or any(
            request.output is None
            or request.output.semantic_sha256 != expectation.semantic_sha256
            for request in attempt.worker.requests
        )
    ):
        raise RuntimeError(
            f"current-runtime output identity mismatch for {attempt.case_id}"
        )


def _require_enabled_pair_output_parity(
    *,
    predecessor: LocalPrewarmAttempt,
    enabled: LocalPrewarmAttempt,
    expectation: CurrentRuntimeOutputExpectation,
) -> None:
    _require_current_runtime_output(predecessor, expectation)
    _require_current_runtime_output(enabled, expectation)
    signatures = _output_parity_signature(predecessor) + _output_parity_signature(
        enabled
    )
    if not signatures or len(set(signatures)) != 1:
        raise RuntimeError(
            f"enabled/predecessor output parity mismatch for {enabled.case_id}"
        )


def _require_completed_case_gates(
    attempts: tuple[LocalPrewarmAttempt, ...],
    expectation: CurrentRuntimeOutputExpectation,
) -> None:
    predecessor = tuple(
        item for item in attempts if item.mode is RunMode.PREDECESSOR
    )
    enabled = tuple(item for item in attempts if item.mode is RunMode.ENABLED)
    if len(predecessor) != len(enabled) or len(predecessor) < MINIMUM_REPETITIONS:
        raise RuntimeError("case gate lacks minimum paired repetitions")
    for item in attempts:
        _require_current_runtime_output(item, expectation)
    signatures = tuple(
        signature
        for item in attempts
        for signature in _output_parity_signature(item)
    )
    if len(set(signatures)) != 1:
        raise RuntimeError(f"case output parity mismatch for {expectation.case_id}")
    predecessor_latency = tuple(item.worker.requests[0].latency_ns for item in predecessor)
    enabled_latency = tuple(item.worker.requests[0].latency_ns for item in enabled)

    def percentile(values: tuple[int, ...], fraction: float) -> int:
        ordered = sorted(values)
        return ordered[max(0, ceil(fraction * len(ordered)) - 1)]

    if (
        int(median(enabled_latency)) > int(median(predecessor_latency))
        or percentile(enabled_latency, 0.95)
        > percentile(predecessor_latency, 0.95)
    ):
        raise RuntimeError(
            f"blocking first-request latency regression for {expectation.case_id}"
        )


def _require_passing_final_evaluation(
    evaluation: LocalPrewarmEvaluation,
) -> None:
    if not evaluation.non_rss_blocking_gates_passed:
        raise RuntimeError("retained LAT-US02 evaluation has blocking failures")


@_with_scoped_signal_cleanup
def run_cross_input_isolation_control(
    *,
    workspace: Path,
    output_directory: Path,
    prepared: PreparedProductionRuntime,
    source_a: SourceIdentity,
    source_b: SourceIdentity,
    expected_a: CurrentRuntimeOutputExpectation,
    expected_b: CurrentRuntimeOutputExpectation,
) -> CrossInputControlReceipt:
    """Launch the bounded real enabled A-B-A state-isolation control."""

    control_id = "lat-us02-cross-input-isolation"
    receipt_path = output_directory / f"{control_id}-receipt.json"
    protocol = Path(tempfile.mkdtemp(prefix=f".{control_id}-", dir=output_directory))
    os.chmod(protocol, 0o700)
    guard_root = protocol / "guard"
    guard_root.mkdir(mode=0o700)
    materialize_private_child_network_guard(workspace, guard_root)
    broker_request_root = protocol / "broker-requests"
    broker_request_root.mkdir(mode=0o700)
    staged_executable_root = protocol / "staged-executable"
    staged_executable_root.mkdir(mode=0o700)
    environment = _attempt_environment(
        workspace=workspace,
        prepared=prepared,
        guard_root=guard_root,
        mode=RunMode.ENABLED,
        worker_scratch_root=broker_request_root,
    )
    settings = _settings_from_environment(environment)
    configuration = cross_input_configuration_identity(
        application_settings_sha256=_settings_sha256(settings),
        worker_environment_sha256=worker_environment_sha256(environment),
        application_settings_projection=sanitized_configuration_projection(
            domain="application_settings", values=asdict(settings)
        ),
        worker_environment_projection=sanitized_configuration_projection(
            domain="worker_environment",
            values=_prebound_broker_projection_environment(
                environment, request_root=broker_request_root
            ),
        ),
        artifacts_path=prepared.artifact_identity.path,
        artifacts_path_identity_sha256=_resolved_path_identity(
            Path(str(settings.docling_artifacts_path))
        ),
        tesseract_executable=settings.tesseract_cmd,
        tesseract_data_path=str(settings.tesseract_data_path),
    )
    source_a_contract = protocol / "source-a.json"
    source_b_contract = protocol / "source-b.json"
    configuration_contract = protocol / "configuration.json"
    write_private_canonical(source_a_contract, source_a)
    write_private_canonical(source_b_contract, source_b)

    def commit_configuration(final_environment: dict[str, str]) -> None:
        nonlocal configuration
        configuration = cross_input_configuration_identity(
            application_settings_sha256=_settings_sha256(settings),
            worker_environment_sha256=worker_environment_sha256(environment),
            application_settings_projection=sanitized_configuration_projection(
                domain="application_settings", values=asdict(settings)
            ),
            worker_environment_projection=sanitized_configuration_projection(
                domain="worker_environment", values=final_environment
            ),
            artifacts_path=prepared.artifact_identity.path,
            artifacts_path_identity_sha256=_resolved_path_identity(
                Path(str(settings.docling_artifacts_path))
            ),
            tesseract_executable=settings.tesseract_cmd,
            tesseract_data_path=str(settings.tesseract_data_path),
        )
        write_private_canonical(configuration_contract, configuration)
    command = (
            sys.executable,
            "-m",
            "tests.benchmarks.latency_prewarm_production_worker",
            "--workspace",
            str(workspace),
            "--source",
            str(workspace / source_a.path),
            "--source-identity",
            str(source_a_contract),
            "--cross-input-secondary",
            str(workspace / source_b.path),
            "--secondary-source-identity",
            str(source_b_contract),
            "--configuration",
            str(configuration_contract),
            "--mode",
            RunMode.ENABLED.value,
            "--application-sha256",
            prepared.execution.application_code_sha256,
            "--dependency-manifest-sha256",
            prepared.execution.dependency_manifest_sha256,
            "--dependency-runtime-sha256",
            str(prepared.execution.dependency_runtime_sha256),
            "--parser-runtime-sha256",
            prepared.execution.parser_runtime_sha256,
            "--runtime-artifacts-sha256",
            prepared.artifact_identity.sha256,
            "--harness-sha256",
            prepared.execution.harness_sha256,
            "--network-isolation-sha256",
            str(prepared.execution.network_isolation_sha256),
    )
    started_at = datetime.now(UTC)
    started_ns = time.monotonic_ns()
    stdout = b""
    stderr = b""
    forced_cleanup = False
    group_gone = False
    launch: _GuardedWorkerLaunch | None = None
    try:
        try:
            launch = _guarded_worker_launch(
                attempt_id=control_id,
                workspace=workspace,
                output_directory=output_directory,
                protocol=protocol,
                environment=environment,
                base_command=command,
                attempt_budget_ns=(300 + 3 * 330 + 30) * 1_000_000_000,
                startup_timeout_ns=int(configuration.startup_timeout_ns or 0),
                brokered=BrokeredLaunchInputs(
                    tesseract_executable=Path(settings.tesseract_cmd).resolve(
                        strict=True
                    ),
                    tesseract_data_path=Path(
                        str(settings.tesseract_data_path)
                    ).resolve(strict=True),
                    immutable_artifact_root=Path(
                        str(settings.docling_artifacts_path)
                    ).resolve(strict=True),
                    allowed_languages=tuple(
                        sorted(set(settings.ocr_languages))
                    ),
                    request_root=broker_request_root.resolve(strict=True),
                    worker_scratch_root=broker_request_root.resolve(strict=True),
                    staged_executable_root=staged_executable_root.resolve(
                        strict=True
                    ),
                    child_wrapper_path=(
                        workspace / "app/services/tesseract_child_exec.py"
                    ).resolve(strict=True),
                ),
                request_count=3,
                commit_worker_configuration=commit_configuration,
            )
        except _GuardedLaunchError as error:
            launch = error.launch
            raise error.error
        process = launch.process
        if process is None:
            raise RuntimeError("cross-input worker is absent after guarded launch")
        launch.drive_external_request_control(
            sources=(source_a, source_b, source_a),
            request_timeout_ns=int(configuration.request_timeout_ns or 0),
        )
        stdout, stderr = launch.capture_until_exit()
        forced_cleanup = launch.cleanup_managed_groups()
        forced_cleanup = launch.stream_cleanup_forced or forced_cleanup
        group_gone = (
            launch.worker_group_disappeared()
            and launch.broker_group_disappeared()
        )
        launch.collect_watchdog()
        controller_resources = launch.controller_boundary()
        completed_at = datetime.now(UTC)
        custody_ok = bool(
            launch.watchdog_terminal is not None
            and launch.watchdog_terminal.outcome == "worker_exited"
            and launch.watchdog_reaped
            and launch.watchdog_group_gone
            and launch.broker is not None
            and launch.broker_reaped
            and launch.broker_group_gone
            and launch.broker_identity is not None
            and launch.watchdog_terminal.broker_group_disappearance_confirmed
            is True
            and launch.broker_capture is not None
            and launch.broker_capture.complete
            and not launch.broker_capture.overflow
            and not launch.broker_stream_limit_exceeded
            and launch.immutable_input_custody_evidence is not None
            and not launch.immutable_input_custody_validation_failed
            and controller_resources.threads_returned_to_baseline
            and controller_resources.file_descriptors_returned_to_baseline
            and _prebind_fatal_sha256(launch) is None
            and launch.capture is not None
            and launch.capture.complete
            and not launch.capture.overflow
            and len(stdout) == launch.stdout_observed_size_bytes
            and hashlib.sha256(stdout).hexdigest()
            == launch.stdout_observed_sha256
            and len(stderr) == launch.stderr_observed_size_bytes
            and hashlib.sha256(stderr).hexdigest()
            == launch.stderr_observed_sha256
        )
        if (
            process.returncode != 0
            or len(stdout) > MAXIMUM_WORKER_STDOUT_BYTES
            or len(stderr) > MAXIMUM_WORKER_STDERR_BYTES
            or launch.stream_limit_exceeded
            or forced_cleanup
            or not group_gone
            or not custody_ok
        ):
            raise RuntimeError("cross-input worker process failed")
        worker = CrossInputRawWorkerEnvelope.model_validate_json(stdout)
        if canonical_model_bytes(worker) != stdout:
            raise ValueError("cross-input raw worker envelope is not canonical")
        if (
            worker.source_a != source_a
            or worker.source_b != source_b
            or launch.child_watch_log_path is None
            or launch.request_resource_sample_log_sha256 is None
            or launch.request_resource_sample_log_row_count is None
            or launch.request_resource_sample_log_size_bytes is None
        ):
            raise ValueError("cross-input controller evidence is incomplete")
        observations = _assemble_cross_input_observations(
            attempt_id=control_id,
            raw=worker,
            boundaries=launch.external_request_boundaries,
            child_watch_log_path=launch.child_watch_log_path,
            request_resource_log_sha256=(
                launch.request_resource_sample_log_sha256
            ),
            request_resource_log_row_count=(
                launch.request_resource_sample_log_row_count
            ),
            request_resource_log_size_bytes=(
                launch.request_resource_sample_log_size_bytes
            ),
        )
        runtime_stable = len(
            {item.runtime_snapshot_sha256 for item in observations}
        ) == 1
        converter_stable = len(
            {item.converter_sha256 for item in observations}
        ) == 1
        cleanup_ok = bool(
            worker.runtime_closed
            and worker.shutdown_resource.process_count == 1
            and worker.shutdown_resource.thread_count
            <= worker.cold_resource.thread_count
            and worker.shutdown_resource.file_descriptor_count
            <= worker.cold_resource.file_descriptor_count
            and worker.artifact_before_requests == worker.artifact_after_shutdown
            and all(
                (
                    worker.application_identity_validated,
                    worker.dependency_identity_validated,
                    worker.parser_runtime_identity_validated,
                    worker.runtime_artifact_identity_validated,
                    worker.configuration_identity_validated,
                    worker.converter_identity_validated,
                    worker.network_isolation_validated,
                    runtime_stable,
                    converter_stable,
                    custody_ok,
                )
            )
        )
        cleanup = CleanupEvidence(
            shutdown_duration_ns=worker.shutdown_duration_ns,
            cleanup_completed=cleanup_ok,
            worker_exited=True,
            worker_reaped=True,
            exit_code=process.returncode,
            owned_process_count_after_shutdown=0,
            all_owned_processes_reaped=True,
            threads_returned_to_baseline=(
                worker.shutdown_resource.thread_count
                <= worker.cold_resource.thread_count
            ),
            file_descriptors_returned_to_baseline=(
                worker.shutdown_resource.file_descriptor_count
                <= worker.cold_resource.file_descriptor_count
            ),
            state_retention_detected=not (runtime_stable and converter_stable),
            oom_observed=False,
            unbounded_rss_growth_observed=False,
            controller_watchdog_process_group_count=1,
            broker_process_group_count=1,
            owned_process_group_count=3,
        )
        terminal_child_raw, terminal_child_stat = (
            _read_private_payload_with_identity(
                launch.child_watch_log_path, maximum_bytes=4_194_304
            )
        )
        terminal_child_bundle = _read_child_watch_bundle(
            launch.child_watch_log_path
        )
        terminal_child_watch_log = terminal_child_watch_log_evidence(
            terminal_child_raw,
            file_device=terminal_child_stat.st_dev,
            file_inode=terminal_child_stat.st_ino,
            file_uid=terminal_child_stat.st_uid,
            record_blob_root=terminal_child_bundle["record_blob_root"],
            record_blobs=terminal_child_bundle["record_blobs"],
            record_blob_identities=(
                terminal_child_bundle["record_blob_identities"]
            ),
            event_blob_root=terminal_child_bundle["event_blob_root"],
            event_blobs=terminal_child_bundle["event_blobs"],
            event_blob_identities=(
                terminal_child_bundle["event_blob_identities"]
            ),
        )
        if (
            launch.request_control is None
            or launch.request_control.readiness_evidence is None
            or launch.request_control_terminal_transcript is None
            or launch.immutable_input_custody_evidence is None
            or launch.immutable_input_custody_validation_failed
        ):
            raise RuntimeError("cross-input request-control readiness is absent")
        child_audit = _retained_child_audit_joins(launch.child_watch_log_path)
        startup_broker_receipt = _contract_lifecycle_receipt(
            raw_mapping=worker.startup_broker_receipt,
            child_audit_joins=child_audit,
            expected_phase="startup",
        )
        shutdown_broker_receipt = _contract_lifecycle_receipt(
            raw_mapping=worker.shutdown_broker_receipt,
            child_audit_joins=child_audit,
            expected_phase="shutdown",
        )
        require_terminal_request_control_transcript(
            launch.request_control_terminal_transcript,
            launch.request_control.readiness_evidence,
            tuple(
                observation.resource_boundary.exact_broker_cpu
                for observation in observations
            ),
            request_sources=tuple(
                observation.source for observation in observations
            ),
            request_outputs=tuple(
                observation.output for observation in observations
            ),
            receipt_blob_root=launch.child_watch_log_path.parent,
        )
        evidence = CrossInputIsolationEvidence(
            schema_id="phase-latency-prewarm-cross-input-isolation-v1",
            source_a=source_a,
            source_b=source_b,
            execution=prepared.execution,
            application_settings_sha256=str(
                configuration.application_settings_sha256
            ),
            worker_environment_sha256=str(configuration.worker_environment_sha256),
            pairing_sha256=str(configuration.pairing_sha256),
            expected_a_semantic_sha256=expected_a.semantic_sha256,
            expected_b_semantic_sha256=expected_b.semantic_sha256,
            observations=observations,
            controller_resource_sample_log_sha256=(
                str(launch.request_resource_sample_log_sha256)
            ),
            controller_resource_sample_log_row_count=(
                int(launch.request_resource_sample_log_row_count)
            ),
            controller_resource_sample_log_size_bytes=(
                int(launch.request_resource_sample_log_size_bytes)
            ),
            terminal_child_watch_log=terminal_child_watch_log,
            artifact_before_requests=worker.artifact_before_requests,
            artifact_after_shutdown=worker.artifact_after_shutdown,
            startup_duration_ns=worker.startup_duration_ns,
            shutdown_duration_ns=worker.shutdown_duration_ns,
            cleanup=cleanup,
            fork_denial_evidence=worker.fork_denial_evidence,
            request_control_readiness=(
                launch.request_control.readiness_evidence
            ),
            terminal_request_control_transcript=(
                launch.request_control_terminal_transcript
            ),
            immutable_runtime_input_custody=(
                launch.immutable_input_custody_evidence
            ),
            startup_broker_receipt=startup_broker_receipt,
            shutdown_broker_receipt=shutdown_broker_receipt,
            network_isolation_validated=worker.network_isolation_validated,
            runtime_identity_stable=runtime_stable,
            converter_identity_stable=converter_stable,
            output_isolation_validated=True,
        )
        receipt = CrossInputControlReceipt(
            schema_id="phase-latency-prewarm-cross-input-receipt-v1",
            started_at_utc=started_at,
            completed_at_utc=completed_at,
            controller_elapsed_ns=time.monotonic_ns() - started_ns,
            worker_return_code=process.returncode,
            forced_group_cleanup_required=forced_cleanup,
            all_group_members_gone=group_gone,
            status=AttemptStatus.SUCCESS,
            failure=None,
            evidence=evidence,
            **_worker_stream_receipt_fields(launch),
            **_launch_custody_receipt_fields(launch, controller_resources),
        )
    except _ControllerTerminationSignal as error:
        if launch is None:
            raise
        process = launch.process
        if process is not None:
            try:
                forced_cleanup = launch.cleanup_managed_groups() or forced_cleanup
            except BaseException:
                forced_cleanup = True
            try:
                stdout, stderr = launch.capture_until_exit()
            except BaseException:
                pass
            try:
                group_gone = (
                    launch.worker_group_disappeared()
                    and launch.broker_group_disappeared()
                )
            except BaseException:
                group_gone = False
        else:
            launch.close_release()
            group_gone = True
        launch.collect_watchdog()
        controller_resources = launch.controller_boundary()
        completed_at = datetime.now(UTC)
        failure = FailureRecord(
            code=FailureCode.WORKER_PROTOCOL_FAILED,
            stage="shutdown",
            detail_sha256=_canonical_sha256(
                {
                    "error_type": (
                        f"{type(error).__module__}.{type(error).__qualname__}"
                    )
                }
            ),
        )
        receipt = CrossInputControlReceipt(
            schema_id="phase-latency-prewarm-cross-input-receipt-v1",
            started_at_utc=started_at,
            completed_at_utc=completed_at,
            controller_elapsed_ns=time.monotonic_ns() - started_ns,
            worker_return_code=(
                process.returncode
                if process is not None and process.returncode is not None
                else -1
            ),
            forced_group_cleanup_required=forced_cleanup,
            all_group_members_gone=group_gone,
            status=AttemptStatus.ERROR,
            failure=failure,
            evidence=None,
            **_worker_stream_receipt_fields(launch),
            **_launch_custody_receipt_fields(launch, controller_resources),
        )
        write_private_canonical(receipt_path, receipt)
        try:
            _retain_and_require_artifact_observation(
                output_directory=output_directory,
                attempt_id=control_id,
                prepared=prepared,
                artifacts_path=Path(
                    prepared.artifact_materialization.target_resolved_runtime_path
                ),
            )
        except BaseException as artifact_error:
            raise artifact_error from error
        raise
    except BaseException as error:
        if launch is None:
            raise
        process = launch.process
        if process is not None:
            try:
                forced_cleanup = launch.cleanup_managed_groups() or forced_cleanup
            except BaseException:
                forced_cleanup = True
            try:
                stdout, stderr = launch.capture_until_exit()
            except BaseException:
                pass
            try:
                group_gone = (
                    launch.worker_group_disappeared()
                    and launch.broker_group_disappeared()
                )
            except BaseException:
                group_gone = False
        else:
            launch.close_release()
            group_gone = True
        launch.collect_watchdog()
        controller_resources = launch.controller_boundary()
        completed_at = datetime.now(UTC)
        failure = FailureRecord(
            code=FailureCode.WORKER_PROTOCOL_FAILED,
            stage="shutdown",
            detail_sha256=_canonical_sha256(
                {
                    "error_type": (
                        f"{type(error).__module__}.{type(error).__qualname__}"
                    )
                }
            ),
        )
        receipt = CrossInputControlReceipt(
            schema_id="phase-latency-prewarm-cross-input-receipt-v1",
            started_at_utc=started_at,
            completed_at_utc=completed_at,
            controller_elapsed_ns=time.monotonic_ns() - started_ns,
            worker_return_code=(
                process.returncode
                if process is not None and process.returncode is not None
                else -1
            ),
            forced_group_cleanup_required=forced_cleanup,
            all_group_members_gone=group_gone,
            status=AttemptStatus.ERROR,
            failure=failure,
            evidence=None,
            **_worker_stream_receipt_fields(launch),
            **_launch_custody_receipt_fields(launch, controller_resources),
        )
    finally:
        shutil.rmtree(protocol, ignore_errors=True)
    write_private_canonical(receipt_path, receipt)
    return receipt


def build_production_plan(
    *,
    workspace: Path,
    registry_path: Path,
    llama_reference_path: Path,
    prepared: PreparedProductionRuntime,
    repetitions: int,
    request_count: int,
) -> tuple[
    ProductionCampaignPlan,
    tuple[DirectionalLlamaReference, ...],
    tuple[CurrentRuntimeOutputExpectation, ...],
]:
    registry = load_corpus_registry(registry_path)
    verify_current_artifacts(registry, workspace)
    sources = _source_identities(registry)
    references = _directional_llama_references(llama_reference_path, sources)
    expectations = _current_runtime_expectations(sources)
    plan = ProductionCampaignPlan(
        schema_id="phase-latency-prewarm-production-plan-v1",
        generated_at_utc=datetime.now(UTC),
        corpus_registry=_file_identity(workspace, registry_path),
        llama_reference=_file_identity(workspace, llama_reference_path),
        sources=sources,
        repetitions=repetitions,
        requests_per_attempt=request_count,
        execution=prepared.execution,
        artifact_materialization=prepared.artifact_materialization,
        pairing_sha256=prepared.pairing_sha256,
    )
    return plan, references, expectations


def _run_production_campaign_with_success_closure(
    *,
    workspace: Path,
    output_directory: Path,
    registry_path: Path,
    llama_reference_path: Path,
    artifacts_path: Path,
    artifacts_label: str,
    workspace_model_source: Path,
    classifier_source: Path,
    tesseract_executable: Path,
    tesseract_data_path: Path,
    repetitions: int = 2,
    request_count: int = PRODUCTION_MINIMUM_REQUESTS,
) -> ProductionCampaignResult:
    root = workspace.resolve()
    output = _ensure_private_directory(output_directory)
    terminal_output = _ensure_private_directory(output / "terminal")
    prepared = prepare_production_runtime(
        workspace=root,
        artifacts_path=artifacts_path,
        artifacts_label=artifacts_label,
        workspace_model_source=workspace_model_source,
        classifier_source=classifier_source,
        tesseract_executable=tesseract_executable,
        tesseract_data_path=tesseract_data_path,
    )
    plan, references, expectations = build_production_plan(
        workspace=root,
        registry_path=registry_path,
        llama_reference_path=llama_reference_path,
        prepared=prepared,
        repetitions=repetitions,
        request_count=request_count,
    )
    plan_path = output / "lat-us02-production-plan.json"
    write_private_canonical(plan_path, plan)
    plan_sha256 = hashlib.sha256(canonical_model_bytes(plan)).hexdigest()
    receipts: list[Path] = []
    artifact_observations: list[Path] = []
    attempts: list[LocalPrewarmAttempt] = []
    terminal_entries: list[TerminalRecordDescriptor] = []
    producer_quiescence: list[bool] = []
    expectation_by_case = {item.case_id: item for item in expectations}
    source_by_case = {item.case_id: item for item in plan.sources}

    # The exact direct flag-off gate is intentionally complete before any
    # private broker/watchdog child channel or paired attempt is launched.
    rollback_observations: list[UninstrumentedRollbackObservation] = []
    for case_ordinal, source in enumerate(plan.sources, start=1):
        expectation = expectation_by_case[source.case_id]
        (
            rollback_receipt,
            rollback_observation,
            rollback_receipt_path,
            rollback_artifact_path,
        ) = run_direct_rollback_attempt(
            workspace=root,
            output_directory=terminal_output,
            prepared=prepared,
            source=source,
            expectation=expectation,
        )
        rollback_observations.append(rollback_observation)
        producer_quiescence.append(
            bool(
                rollback_receipt.watchdog_process_group_gone
                and rollback_receipt.worker_process_group_gone
                and rollback_receipt.launcher_terminal_evidence is not None
                and all(
                    value == 0
                    for value in rollback_receipt.launcher_terminal_evidence.root_returncodes.values()
                )
            )
        )
        rollback_attempt_id = f"lat-us02-rollback-{source.case_id}"
        rollback_paths = (
            ("launch-intent", terminal_output / f"{rollback_attempt_id}-launch-intent.json"),
            ("launch-record", terminal_output / f"{rollback_attempt_id}-launch-record.json"),
            ("phase-deadlines", terminal_output / f"{rollback_attempt_id}-phase-deadlines.jsonl"),
            ("phase-acks", terminal_output / f"{rollback_attempt_id}-phase-acks.jsonl"),
            ("watchdog-terminal", terminal_output / f"{rollback_attempt_id}-watchdog-terminal.json"),
            ("launcher-ledger", terminal_output / f"{rollback_attempt_id}-watchdog-launcher.jsonl"),
            ("attempt-receipt", rollback_receipt_path),
            ("artifact-observation", rollback_artifact_path),
        )
        for record_kind, record_path in rollback_paths:
            _append_terminal_record_descriptor(
                terminal_entries,
                output_root=output,
                path=record_path,
                segment="rollback",
                record_kind=record_kind,
                topology="direct-default-off-v1",
                attempt_id=rollback_attempt_id,
                case_id=source.case_id,
                case_ordinal=case_ordinal,
                attempt_status=(
                    AttemptStatus.SUCCESS
                    if record_kind == "attempt-receipt"
                    else None
                ),
            )
        if len(terminal_entries) != case_ordinal * 8:
            raise RuntimeError("rollback terminal prefix retention differs")
    rollback_submanifest = terminal_record_submanifest(tuple(terminal_entries))
    rollback_evidence = UninstrumentedRollbackEvidence(
        schema_id="phase-latency-prewarm-rollback-output-gate-v1",
        generated_at_utc=datetime.now(UTC),
        execution=prepared.execution,
        observations=tuple(rollback_observations),
        terminal_records=rollback_submanifest,
        terminal_record_manifest_sha256=rollback_submanifest.manifest_sha256,
    )
    rollback_evidence_path = terminal_output / "lat-us02-rollback-evidence.json"
    rollback_submanifest_path = (
        terminal_output / "lat-us02-rollback-submanifest.json"
    )
    write_private_canonical(rollback_evidence_path, rollback_evidence)
    write_private_canonical(rollback_submanifest_path, rollback_submanifest)
    _append_terminal_record_descriptor(
        terminal_entries,
        output_root=output,
        path=rollback_evidence_path,
        segment="rollback_gate",
        record_kind="rollback-evidence",
        topology="campaign-controller-v1",
    )
    _append_terminal_record_descriptor(
        terminal_entries,
        output_root=output,
        path=rollback_submanifest_path,
        segment="rollback_gate",
        record_kind="rollback-submanifest",
        topology="campaign-controller-v1",
    )
    if any(
        path.name.startswith("lat-us02-cross-input-")
        or any(
            path.name.startswith(f"lat-us02-{case_id}-")
            for case_id in PRODUCTION_CASE_IDS
        )
        for path in terminal_output.iterdir()
        if path.is_file()
    ):
        raise RuntimeError("brokered campaign bytes predated rollback closure")
    try:
        cross_input_receipt = run_cross_input_isolation_control(
            workspace=root,
            output_directory=terminal_output,
            prepared=prepared,
            source_a=source_by_case["insurance-acord"],
            source_b=source_by_case["clean-energy"],
            expected_a=expectation_by_case["insurance-acord"],
            expected_b=expectation_by_case["clean-energy"],
        )
    except BaseException as cross_error:
        try:
            artifact_observations.append(
                _retain_and_require_artifact_observation(
                    output_directory=terminal_output,
                    attempt_id="lat-us02-cross-input-isolation",
                    prepared=prepared,
                    artifacts_path=artifacts_path,
                )
            )
        except BaseException as artifact_error:
            raise artifact_error from cross_error
        raise
    cross_input_receipt_path = (
        terminal_output / "lat-us02-cross-input-isolation-receipt.json"
    )
    receipts.append(cross_input_receipt_path)
    artifact_observations.append(
        _retain_and_require_artifact_observation(
            output_directory=terminal_output,
            attempt_id="lat-us02-cross-input-isolation",
            prepared=prepared,
            artifacts_path=artifacts_path,
        )
    )
    if (
        cross_input_receipt.status is not AttemptStatus.SUCCESS
        or cross_input_receipt.evidence is None
    ):
        raise RuntimeError("production campaign stopped after cross-input control")
    cross_input_isolation = cross_input_receipt.evidence
    producer_quiescence.append(
        bool(
            cross_input_receipt.watchdog_process_group_gone
            and cross_input_receipt.broker_process_group_gone
            and cross_input_receipt.all_group_members_gone
            and cross_input_receipt.launcher_terminal_evidence is not None
            and all(
                value == 0
                for value in cross_input_receipt.launcher_terminal_evidence.root_returncodes.values()
            )
        )
    )
    _append_unindexed_attempt_records(
        terminal_entries,
        output_root=output,
        terminal_directory=terminal_output,
        attempt_id="lat-us02-cross-input-isolation",
        receipt_filename="lat-us02-cross-input-isolation-receipt.json",
        segment="cross_input",
        case_id=None,
        case_ordinal=None,
        attempt_status=cross_input_receipt.status,
    )
    for source in plan.sources:
        case_attempts: list[LocalPrewarmAttempt] = []
        for repetition in range(1, repetitions + 1):
            paired_predecessor: LocalPrewarmAttempt | None = None
            for mode in (RunMode.PREDECESSOR, RunMode.ENABLED):
                attempt_id = (
                    f"lat-us02-{source.case_id}-{mode.value}-r{repetition:02d}"
                )
                try:
                    receipt = run_production_attempt(
                        workspace=root,
                        output_directory=terminal_output,
                        prepared=prepared,
                        source=source,
                        mode=mode,
                        repetition_index=repetition,
                        request_count=request_count,
                    )
                except BaseException as attempt_error:
                    try:
                        artifact_observations.append(
                            _retain_and_require_artifact_observation(
                                output_directory=terminal_output,
                                attempt_id=attempt_id,
                                prepared=prepared,
                                artifacts_path=artifacts_path,
                            )
                        )
                    except BaseException as artifact_error:
                        raise artifact_error from attempt_error
                    raise
                receipt_path = terminal_output / f"{attempt_id}.json"
                if not receipt_path.is_file():
                    raise RuntimeError("launched attempt lacks its retained receipt")
                receipts.append(receipt_path)
                artifact_observations.append(
                    _retain_and_require_artifact_observation(
                        output_directory=terminal_output,
                        attempt_id=attempt_id,
                        prepared=prepared,
                        artifacts_path=artifacts_path,
                    )
                )
                if receipt.attempt is None or receipt.status is not AttemptStatus.SUCCESS:
                    raise RuntimeError(
                        f"production campaign stopped after retained {receipt.attempt_id}"
                    )
                attempt = receipt.attempt
                producer_quiescence.append(
                    bool(
                        receipt.watchdog_process_group_gone
                        and receipt.broker_process_group_gone
                        and receipt.all_group_members_gone
                        and receipt.launcher_terminal_evidence is not None
                        and all(
                            value == 0
                            for value in receipt.launcher_terminal_evidence.root_returncodes.values()
                        )
                    )
                )
                if mode is RunMode.PREDECESSOR:
                    _require_current_runtime_output(
                        attempt, expectation_by_case[source.case_id]
                    )
                    paired_predecessor = attempt
                else:
                    if paired_predecessor is None:
                        raise RuntimeError("enabled attempt lacks its retained predecessor")
                    _require_enabled_pair_output_parity(
                        predecessor=paired_predecessor,
                        enabled=attempt,
                        expectation=expectation_by_case[source.case_id],
                    )
                attempts.append(attempt)
                case_attempts.append(attempt)
                _append_unindexed_attempt_records(
                    terminal_entries,
                    output_root=output,
                    terminal_directory=terminal_output,
                    attempt_id=attempt_id,
                    receipt_filename=f"{attempt_id}.json",
                    segment="paired",
                    case_id=source.case_id,
                    case_ordinal=PRODUCTION_CASE_IDS.index(source.case_id) + 1,
                    attempt_status=receipt.status,
                )
            if repetition >= MINIMUM_REPETITIONS:
                _require_completed_case_gates(
                    tuple(case_attempts), expectation_by_case[source.case_id]
                )
    campaign_final_artifact_path = _retain_and_require_artifact_observation(
        output_directory=terminal_output,
        attempt_id="campaign-final",
        prepared=prepared,
        artifacts_path=artifacts_path,
    )
    artifact_observations.append(campaign_final_artifact_path)
    _append_terminal_record_descriptor(
        terminal_entries,
        output_root=output,
        path=campaign_final_artifact_path,
        segment="campaign_final",
        record_kind="artifact-observation",
        topology="campaign-controller-v1",
    )
    final_artifact_materialization = (
        _finalize_production_artifact_materialization(
            prepared=prepared,
            artifacts_path=artifacts_path,
            workspace_model_source=workspace_model_source,
            classifier_source=classifier_source,
        )
    )
    final_artifact_manifest_path = (
        output / "lat-us02-production-final-artifact-manifest.json"
    )
    write_private_canonical(
        final_artifact_manifest_path, final_artifact_materialization
    )
    case_indexes = tuple(
        CaseAttemptIndex(
            case_id=source.case_id,
            predecessor_attempt_ids=tuple(
                f"lat-us02-{source.case_id}-{RunMode.PREDECESSOR.value}-r{index:02d}"
                for index in range(1, repetitions + 1)
            ),
            enabled_attempt_ids=tuple(
                f"lat-us02-{source.case_id}-{RunMode.ENABLED.value}-r{index:02d}"
                for index in range(1, repetitions + 1)
            ),
        )
        for source in plan.sources
    )
    indexed_terminal_paths = {item.relative_path for item in terminal_entries}
    actual_terminal_paths = {
        path.resolve(strict=True).relative_to(output).as_posix()
        for path in terminal_output.iterdir()
        if path.is_file() and not path.is_symlink()
    }
    if indexed_terminal_paths != actual_terminal_paths:
        raise RuntimeError("terminal directory contains unindexed execution records")
    terminal_manifest = terminal_record_manifest(
        entries=tuple(terminal_entries), rollback_prefix=rollback_submanifest
    )
    terminal_manifest_path = output / "lat-us02-terminal-record-manifest.json"
    write_private_canonical(terminal_manifest_path, terminal_manifest)
    bundle = LocalPrewarmEvidenceBundle(
        schema_id="phase-latency-prewarm-evidence-v1",
        evidence_scope="local_story_evidence",
        generated_at_utc=datetime.now(UTC),
        attempts=tuple(attempts),
        case_indexes=case_indexes,
        directional_llama_references=references,
        current_runtime_output_expectations=expectations,
        corpus_registry=plan.corpus_registry,
        campaign_plan_sha256=plan_sha256,
        final_artifact_materialization_sha256=(
            final_artifact_materialization.manifest_sha256
        ),
        terminal_record_manifest=terminal_manifest,
        terminal_record_manifest_sha256=terminal_manifest.manifest_sha256,
        terminal_record_manifest_entry_count=terminal_manifest.entry_count,
        terminal_record_manifest_policy=terminal_manifest.policy,
        uninstrumented_rollback=rollback_evidence,
        cross_input_isolation=cross_input_isolation,
        r34_exact_output_identity_claimed=True,
        r34_artifact_scope_disposition=(
            "approved_combined_tree_full_15_output_verified"
        ),
    )
    evaluation = evaluate_retained_local_prewarm_bundle(
        bundle,
        output_root=output,
    )
    bundle_path = output / "lat-us02-production-evidence.json"
    evaluation_path = output / "lat-us02-production-evaluation.json"
    write_private_canonical(bundle_path, bundle)
    write_private_canonical(evaluation_path, evaluation)
    _require_passing_final_evaluation(evaluation)
    bundle_sha256 = hashlib.sha256(canonical_model_bytes(bundle)).hexdigest()
    evaluation_sha256 = hashlib.sha256(
        canonical_model_bytes(evaluation)
    ).hexdigest()
    expected_closure_paths = {
        item.relative_path for item in terminal_manifest.entries
    } | {
        plan_path.relative_to(output).as_posix(),
        final_artifact_manifest_path.relative_to(output).as_posix(),
        terminal_manifest_path.relative_to(output).as_posix(),
        bundle_path.relative_to(output).as_posix(),
        evaluation_path.relative_to(output).as_posix(),
    }
    campaign_closure_manifest_path = _write_campaign_closure_manifest(
        output_root=output,
        expected_relative_paths=expected_closure_paths,
        producer_groups_esrch=(
            bool(producer_quiescence) and all(producer_quiescence)
        ),
        terminal_manifest_sha256=terminal_manifest.manifest_sha256,
        bundle_sha256=bundle_sha256,
        evaluation_sha256=evaluation_sha256,
    )
    return ProductionCampaignResult(
        plan=plan,
        bundle=bundle,
        evaluation=evaluation,
        receipt_paths=tuple(receipts),
        artifact_observation_paths=tuple(artifact_observations),
        final_artifact_manifest_path=final_artifact_manifest_path,
        campaign_closure_manifest_path=campaign_closure_manifest_path,
    )


@_with_scoped_signal_cleanup
def run_production_campaign(
    *,
    workspace: Path,
    output_directory: Path,
    registry_path: Path,
    llama_reference_path: Path,
    artifacts_path: Path,
    artifacts_label: str,
    workspace_model_source: Path,
    classifier_source: Path,
    tesseract_executable: Path,
    tesseract_data_path: Path,
    repetitions: int = 2,
    request_count: int = PRODUCTION_MINIMUM_REQUESTS,
) -> ProductionCampaignResult:
    """Run the campaign and close every post-plan failure prefix exactly once."""

    try:
        return _run_production_campaign_with_success_closure(
            workspace=workspace,
            output_directory=output_directory,
            registry_path=registry_path,
            llama_reference_path=llama_reference_path,
            artifacts_path=artifacts_path,
            artifacts_label=artifacts_label,
            workspace_model_source=workspace_model_source,
            classifier_source=classifier_source,
            tesseract_executable=tesseract_executable,
            tesseract_data_path=tesseract_data_path,
            repetitions=repetitions,
            request_count=request_count,
        )
    except BaseException as error:
        output = output_directory.resolve()
        plan_path = output / "lat-us02-production-plan.json"
        closure_path = output / "campaign-closure.json"
        marker_path = output / "campaign-failure-marker.json"
        if (
            plan_path.is_file()
            and not closure_path.exists()
            and not marker_path.exists()
        ):
            failure = FailureRecord(
                code=FailureCode.WORKER_PROTOCOL_FAILED,
                stage="shutdown",
                detail_sha256=_canonical_sha256(
                    {
                        "error_type": (
                            f"{type(error).__module__}."
                            f"{type(error).__qualname__}"
                        )
                    }
                ),
            )
            try:
                _write_quiescent_campaign_failure_closure(
                    output_root=output, failure=failure
                )
            except _CampaignFailureClosureUnavailable:
                _write_campaign_failure_marker(output_root=output, failure=failure)
            except BaseException as closure_error:
                raise closure_error from error
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--registry", default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--llama-reference", default=DEFAULT_LLAMA_REFERENCE_PATH)
    parser.add_argument("--artifacts-path", required=True)
    parser.add_argument(
        "--artifacts-label",
        default="runtime-artifacts/approved-combined-tree",
    )
    parser.add_argument("--workspace-model-source", required=True)
    parser.add_argument("--classifier-source", required=True)
    parser.add_argument("--tesseract-executable", required=True)
    parser.add_argument("--tesseract-data-path", required=True)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument(
        "--requests-per-attempt", type=int, default=PRODUCTION_MINIMUM_REQUESTS
    )
    parser.add_argument(
        "--execute-reviewed-local-campaign",
        action="store_true",
        help="required acknowledgement before launching all local attempts",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if not args.execute_reviewed_local_campaign:
        raise SystemExit(
            "refusing to launch: pass --execute-reviewed-local-campaign after "
            "lifecycle bytes are frozen"
        )
    if args.repetitions < MINIMUM_REPETITIONS:
        raise SystemExit("at least two retained repetitions are required")
    if args.requests_per_attempt < MINIMUM_REQUESTS:
        raise SystemExit("at least four requests per attempt are required")
    workspace = Path(args.workspace).resolve()
    run_production_campaign(
        workspace=workspace,
        output_directory=Path(args.output_directory),
        registry_path=(workspace / args.registry).resolve(),
        llama_reference_path=(workspace / args.llama_reference).resolve(),
        artifacts_path=Path(args.artifacts_path),
        artifacts_label=args.artifacts_label,
        workspace_model_source=Path(args.workspace_model_source),
        classifier_source=Path(args.classifier_source),
        tesseract_executable=Path(args.tesseract_executable),
        tesseract_data_path=Path(args.tesseract_data_path),
        repetitions=args.repetitions,
        request_count=args.requests_per_attempt,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
