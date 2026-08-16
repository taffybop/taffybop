"""Adversarial contracts for the LAT-US02 real production adapter."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import select
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import textwrap
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest
import psutil
from pydantic import ValidationError
from app.config import Settings
from app.services.parser_phase_control import ParserPhaseControlClient
from app.services.tesseract_broker import DurableLedger
from app.services.tesseract_broker_protocol import (
    BrokerChildWait4Tombstone as AppBrokerChildWait4Tombstone,
    BROKER_AUDIT_COMMITMENT_BYTES,
    MAX_BROKER_AUDIT_BLOB_BYTES,
    BrokerProtocolError,
    FramedChannel,
    NATIVE_CHILD_LIMIT_ACK_AUTHORITY,
    NATIVE_CHILD_LIMIT_APPLIED_CLOCK_AUTHORITY,
    NATIVE_RUNTIME_GATE_ACK_AUTHORITY,
    NATIVE_RUNTIME_GATE_C_CLOCK_AUTHORITY,
    NativeRuntimeImageAttestation as AppNativeRuntimeImageAttestation,
    NativeRuntimeScanSample as AppNativeRuntimeScanSample,
    RawRUsage as AppRawRUsage,
    RawTimeval as AppRawTimeval,
    KernelProcessIdentity as AppKernelProcessIdentity,
    broker_audit_row_mapping,
    canonical_json_bytes,
    canonical_sha256,
    child_tombstone_from_mapping,
    child_watch_birth_from_commitment,
    native_child_limit_ack_sha256,
    native_runtime_gate_ack_sha256,
    request_receipt_from_mapping,
    native_runtime_gate_transition_from_mapping,
)
from app.services.tesseract_broker_native import (
    NativeFileDescriptorIdentity as AppNativeFileDescriptorIdentity,
    NativeFileDescriptorInventory as AppNativeFileDescriptorInventory,
    NativePipeFileDescriptorIdentity as AppNativePipeFileDescriptorIdentity,
    NativeThreadInventory as AppNativeThreadInventory,
    raw_process_start_abstime,
)
from app.services import parser_worker_supervisor

from tests.benchmarks import latency_prewarm_contracts as contracts
from tests.benchmarks import latency_prewarm_production_runner as production_runner
from tests.benchmarks import latency_prewarm_production_worker as production_worker
from tests.benchmarks.latency_prewarm_contracts import (
    ArtifactIdentity,
    AttemptStatus,
    CrossInputIsolationEvidence,
    CrossInputRequestObservation,
    FailureCode,
    FailureRecord,
    EvaluationFailureCode,
    FileTreeIdentityEvidence,
    FrameworkThreadBaseline,
    ImmutableRuntimeInputCustodyEvidence,
    ImmutableRuntimeInputDirectoryMember,
    ImmutableRuntimeInputDirectoryMembership,
    ImmutableRuntimeInputEntry,
    ImmutableRuntimeInputPathIdentity,
    ImmutableRuntimeInputRootAuthority,
    CurrentRuntimeOutputExpectation,
    BrokerQuiescenceReceipt,
    BrokerLifecycleReceiptEvidence,
    ControllerChildWatchPrefix,
    ControllerRequestResourceSample,
    ControllerResourceAggregate,
    ControllerResourceProcessSample,
    ExactBrokerRequestCpuEvidence,
    ExactProcessIdentity,
    LocalPrewarmAttempt,
    LocalPrewarmEvaluation,
    LocalPrewarmEvidenceBundle,
    NativeKernelProcessIdentity,
    NativeSelfCpuCounter,
    NativeProcessResourceSample,
    NativeThreadInventory,
    NativeVnodeFileDescriptorIdentity,
    PEAK_SAMPLE_EDGE_TOLERANCE_NS,
    OutputIdentity,
    ProcessCpuCounter,
    ProcessCpuSnapshot,
    RequestResourceBoundary,
    RequestControlReadinessEvidence,
    ResourcePhase,
    ResourceSample,
    RunMode,
    SampledProcessIdentity,
    SourceIdentity,
    TrustedLauncherIdentity,
    WorkerMeasurementEnvelope,
    asgi_response_witness,
    canonical_model_bytes,
    broker_request_binding_evidence,
    broker_lifecycle_receipt_evidence,
    broker_post_release_baseline,
    broker_scratch_inventory,
    controller_resource_sample_log_row,
    external_cpu_stable_edge_record,
    native_file_descriptor_identity,
    native_file_descriptor_inventory,
    native_thread_inventory,
    framework_thread_baseline,
    request_control_readiness_evidence,
    cross_input_configuration_identity,
    evaluate_local_prewarm_attempt_blocking_failures,
    evaluate_local_prewarm_bundle,
    production_configuration_identity,
    sanitized_configuration_projection,
    terminal_child_watch_log_evidence,
    terminal_request_control_transcript_evidence,
    worker_fork_denial_evidence,
)
from tests.benchmarks.latency_prewarm_production_runner import (
    _attempt_environment,
    _BoundedPipeCapture,
    _finalize_production_artifact_materialization,
    _materialization_manifest,
    _require_completed_case_gates,
    _require_current_runtime_output,
    _require_enabled_pair_output_parity,
    _require_passing_final_evaluation,
    _retain_and_require_artifact_observation,
    _retain_post_launch_failure_receipt,
    _guarded_worker_launch,
    _GuardedLaunchError,
    _frozen_process_group_state,
    _process_identity,
    _scoped_signal_cleanup,
    _signal_frozen_process_group,
    _ControllerTerminationSignal,
    _sandboxed_production_worker_command,
    PostAttemptArtifactObservation,
    PreparedProductionRuntime,
    ControllerProcessIdentity,
    ControllerResourceBoundary,
    ControllerResourceSample,
    ProductionAttemptReceipt,
    BrokeredLaunchInputs,
    MAXIMUM_WORKER_COMBINED_BYTES,
    ProductionWatchdogTerminalEvidence,
    run_cross_input_isolation_control,
    run_production_attempt,
    write_private_canonical,
)
from tests.benchmarks.latency_prewarm_production_worker import (
    _PeakSampler,
    _request_cpu_delta,
    _unbounded_rss_growth,
    output_identity_from_json,
)
from tests.benchmarks.latency_prewarm_watchdog import (
    PhaseDeadlineRecord,
    PrewarmWatchdogConfig,
    PrewarmWatchdogExitCode,
    PrewarmWatchdogOutcome,
    _acknowledged_phase_expired_before_advance,
    _PhaseControlRegistry,
    _ChildWatchLedger,
    _ChildWatchRegistry,
    _require_pre_exec_gated_resource_shape,
    _validate_reported_gated_child_inventory,
    _frozen_group_state,
    _worker_exit_outcome_at_terminal_observation,
    append_phase_ack,
    append_phase_deadline,
    build_prewarm_watchdog_command,
    read_phase_acks,
    read_phase_deadlines,
)
from tests.benchmarks.latency_watchdog import (
    ProcessSnapshot,
    WorkerBinding,
    sanitized_watchdog_environment,
)
from tests.benchmarks.latency_prewarm_runner import (
    LocalCase,
    run_synthetic_local_campaign,
)
from tests.benchmarks.latency_isolation import (
    OS_NETWORK_SANDBOX_EXECUTABLE,
    OS_NETWORK_SANDBOX_PROFILE,
    materialize_private_child_network_guard,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _native_fd_inventory(
    identity: ExactProcessIdentity,
    count: int,
    observed_monotonic_ns: int,
):
    descriptors = tuple(
        native_file_descriptor_identity(
            fd=fd,
            kernel_type=1,
            open_flags=0,
            kernel_status_flags=0,
            descriptor_offset=0,
            descriptor_type=1,
            guard_flags=0,
            close_on_exec=False,
            close_on_fork=False,
            guarded=False,
            shared=False,
            vnode=NativeVnodeFileDescriptorIdentity(
                device=1,
                inode=10_000 + identity.pid * 100 + fd,
                mode=stat.S_IFREG | 0o400,
                nlink=1,
                uid=501,
                gid=20,
                size=1,
                vnode_type=1,
                resolved_path_sha256=_sha(
                    f"fd-path:{identity.pid}:{fd}"
                ),
            ),
            socket=None,
            pipe=None,
            kqueue=None,
        )
        for fd in range(count)
    )
    return native_file_descriptor_inventory(
        process=NativeKernelProcessIdentity(
            pid=identity.pid,
            start_abstime=identity.start_abstime,
            ppid=identity.parent_pid,
            pgid=identity.process_group_id,
            sid=identity.session_id,
        ),
        first_scan_started_monotonic_ns=observed_monotonic_ns,
        first_scan_completed_monotonic_ns=observed_monotonic_ns,
        second_scan_started_monotonic_ns=observed_monotonic_ns,
        second_scan_completed_monotonic_ns=observed_monotonic_ns,
        descriptors=descriptors,
    )


def _native_thread_inventory(
    identity: ExactProcessIdentity,
    thread_ids: tuple[int, ...],
    observed_monotonic_ns: int,
) -> NativeThreadInventory:
    return native_thread_inventory(
        process=NativeKernelProcessIdentity(
            pid=identity.pid,
            start_abstime=identity.start_abstime,
            ppid=identity.parent_pid,
            pgid=identity.process_group_id,
            sid=identity.session_id,
        ),
        first_scan_started_monotonic_ns=observed_monotonic_ns,
        first_scan_completed_monotonic_ns=observed_monotonic_ns,
        second_scan_started_monotonic_ns=observed_monotonic_ns,
        second_scan_completed_monotonic_ns=observed_monotonic_ns,
        thread_ids=thread_ids,
    )


def _parse_result_bytes(*, duration_ms: int, engine: str = "local") -> bytes:
    return json.dumps(
        {
            "schema_version": "1.0",
            "document": {
                "filename": "case.pdf",
                "mime_type": "application/pdf",
                "sha256": "a" * 64,
                "page_count": 0,
            },
            "pages": [],
            "processing": {
                "engine": engine,
                "ocr_engine": "tesseract",
                "ocr_languages": ["eng"],
                "duration_ms": duration_ms,
            },
            "warnings": [],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _configuration_projections(enabled: bool) -> dict[str, object]:
    return {
        "application_settings_projection": sanitized_configuration_projection(
            domain="application_settings",
            values={
                **asdict(Settings()),
                "max_pages": 100,
                "parser_latency_prewarm_artifacts_sha256": (
                    "a" * 64 if enabled else None
                ),
                "parser_latency_prewarm_dependency_sha256": (
                    "b" * 64 if enabled else None
                ),
                "parser_latency_prewarm_enabled": enabled,
                "parser_latency_prewarm_shutdown_grace_seconds": 2.0,
                "parser_latency_prewarm_timeout_seconds": 300.0,
            },
        ),
        "worker_environment_projection": sanitized_configuration_projection(
            domain="worker_environment",
            values={
                "PATH": "/usr/bin",
                "PARSER_LATENCY_PREWARM_ENABLED": (
                    "true" if enabled else "false"
                ),
            },
        ),
    }


def _replace_attempt(
    bundle: LocalPrewarmEvidenceBundle,
    changed: LocalPrewarmAttempt,
) -> LocalPrewarmEvidenceBundle:
    return LocalPrewarmEvidenceBundle.model_validate(
        {
            **bundle.model_dump(mode="python"),
            "attempts": tuple(
                changed if item.attempt_id == changed.attempt_id else item
                for item in bundle.attempts
            ),
        }
    )


def _controller_boundary() -> ControllerResourceBoundary:
    identity = ControllerProcessIdentity(
        pid=999,
        create_time_ns=1,
        process_group_id=999,
        session_id=999,
    )
    before = _controller_resource_fixture(
        identity=identity,
        observed_monotonic_ns=1,
        thread_ids=(9_001,),
        file_descriptor_count=1,
    )
    after = before.model_copy(update={"observed_monotonic_ns": 2})
    return ControllerResourceBoundary(
        before=before,
        after=after,
        threads_returned_to_baseline=True,
        file_descriptors_returned_to_baseline=True,
    )


def _controller_resource_fixture(
    *,
    identity: ControllerProcessIdentity,
    observed_monotonic_ns: int,
    thread_ids: tuple[int, ...],
    file_descriptor_count: int,
) -> ControllerResourceSample:
    exact = ExactProcessIdentity(
        role="parser_worker",
        pid=identity.pid,
        start_abstime=1,
        parent_pid=1,
        process_group_id=identity.process_group_id,
        session_id=identity.session_id,
    )
    thread_inventory = _native_thread_inventory(
        exact, thread_ids, observed_monotonic_ns
    )
    file_descriptor_inventory = _native_fd_inventory(
        exact, file_descriptor_count, observed_monotonic_ns
    )
    return ControllerResourceSample(
        observed_monotonic_ns=observed_monotonic_ns,
        identity=identity,
        thread_count=len(thread_ids),
        file_descriptor_count=file_descriptor_count,
        thread_inventory=thread_inventory,
        file_descriptor_inventory=file_descriptor_inventory,
        file_descriptor_membership_sha256=(
            production_runner._native_fd_membership_sha256(
                file_descriptor_inventory
            )
        ),
    )


_CACHED_TERMINAL_CHILD_WATCH_FIXTURE = None


def _terminal_child_watch_fixture():
    global _CACHED_TERMINAL_CHILD_WATCH_FIXTURE
    if _CACHED_TERMINAL_CHILD_WATCH_FIXTURE is not None:
        return _CACHED_TERMINAL_CHILD_WATCH_FIXTURE
    native_closure = _synthetic_native_closure(
        resolved_path="/synthetic/tesseract",
        image_sha256=_sha("synthetic-tesseract"),
        uid=501,
    )
    (
        guard_python,
        guard_python_path_custody,
        guard_python_native_closure,
        guard_python_module_tree_custody,
    ) = _synthetic_guard_authority()
    immutable_observation = {
        "schema_id": "parser-tesseract-immutable-input-observation-v1",
        "native_closure_sha256": native_closure["closure_sha256"],
        "native_trust_model": "frozen-native-closure-trusted-v1",
        "native_containment_claim": (
            "none-trusted-pinned-native-computation"
        ),
        "source_executable_sha256": _sha("synthetic-source-tesseract"),
        "staged_executable_sha256": _sha("synthetic-tesseract"),
        "native_spawn_guard_sha256": "e" * 64,
        "native_spawn_guard_source_sha256": "d" * 64,
        "native_runtime_gate_source_sha256": _sha(
            "runtime-gate-source"
        ),
        "native_runtime_gate_library_sha256": _sha(
            "runtime-gate-library"
        ),
        "native_runtime_gate_record_sha256": _sha(
            "runtime-gate-record"
        ),
        "guard_python_sha256": guard_python["sha256"],
        "guard_python_path_custody_sha256": (
            guard_python_path_custody["record_sha256"]
        ),
        "guard_python_native_closure_sha256": (
            guard_python_native_closure["closure_sha256"]
        ),
        "guard_python_module_tree_sha256": (
            guard_python_module_tree_custody["record_sha256"]
        ),
        "guard_wrapper_source_sha256": hashlib.sha256(b"\x00").hexdigest(),
        "guard_wrapper_delivery_basis": (
            "execve-python-c-embedded-source-v1"
        ),
        "tessdata_sha256": canonical_sha256(
            (
                {
                    "path": "eng.traineddata",
                    "sha256": _sha("eng-traineddata"),
                    "size_bytes": 1,
                },
            )
        ),
        "observed_at_monotonic_ns": 1,
    }
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        root.chmod(0o700)
        path = root / "child-watch.bin"
        ledger = _ChildWatchLedger(path)
        first = broker_audit_row_mapping(
            row_sequence=1,
            previous_row_sha256="0" * 64,
            kind="shutdown_immutable_inputs",
            record=immutable_observation,
        )
        ledger.append_broker_row(first)
        second = broker_audit_row_mapping(
            row_sequence=2,
            previous_row_sha256=str(first["row_sha256"]),
            kind="shutdown",
            record={"schema_id": "fixture-shutdown-v1"},
        )
        ledger.append_broker_row(second)
        ledger.close()
        raw, observed = production_runner._read_private_payload_with_identity(
            path, maximum_bytes=4_194_304
        )
        bundle = production_runner._read_child_watch_bundle(path)
        retained = terminal_child_watch_log_evidence(
            raw,
            file_device=observed.st_dev,
            file_inode=observed.st_ino,
            file_uid=observed.st_uid,
            record_blob_root=bundle["record_blob_root"],
            record_blobs=bundle["record_blobs"],
            record_blob_identities=bundle["record_blob_identities"],
            event_blob_root=bundle["event_blob_root"],
            event_blobs=bundle["event_blobs"],
            event_blob_identities=bundle["event_blob_identities"],
        )
        _CACHED_TERMINAL_CHILD_WATCH_FIXTURE = retained
        return retained


def _empty_child_watch_prefix_fixture() -> ControllerChildWatchPrefix:
    terminal = _terminal_child_watch_fixture()
    decoded = terminal._decoded()
    record_root = dict(decoded["record_root"])
    record_root.update(
        entry_count=0,
        aggregate_bytes=0,
        head_sha256="0" * 64,
    )
    record_root.pop("record_sha256", None)
    event_root = dict(decoded["event_root"])
    event_root.update(
        entry_count=0,
        aggregate_bytes=0,
        head_sha256="0" * 64,
    )
    event_root.pop("record_sha256", None)
    return ControllerChildWatchPrefix(
        size_bytes=0,
        sha256=hashlib.sha256(b"").hexdigest(),
        broker_row_count=0,
        broker_head_sha256="0" * 64,
        record_blob_count=0,
        record_blob_size_bytes=0,
        record_blob_head_sha256="0" * 64,
        record_blob_root_sha256=canonical_sha256(record_root),
        event_count=0,
        event_blob_size_bytes=0,
        event_blob_root_sha256=canonical_sha256(event_root),
        event_head_sha256="0" * 64,
        open_registration_count=0,
        terminal_wait4_count=0,
    )


def _synthetic_native_closure(
    *, resolved_path: str, image_sha256: str, uid: int
) -> dict[str, object]:
    dependency_projection_sha256 = canonical_sha256({"dependencies": []})
    image = {
        "resolved_path": resolved_path,
        "sha256": image_sha256,
        "device": 1,
        "inode": 11,
        "mode": stat.S_IFREG | 0o500,
        "uid": uid,
        "gid": 20,
        "nlink": 1,
        "size": 1,
        "mtime_ns": 1,
        "ctime_ns": 1,
        "slices": [],
        "dynamic_loader_imports": [],
        "imports_dynamic_loader_family": False,
    }
    closure: dict[str, object] = {
        "schema_id": "parser-tesseract-native-closure-v1",
        "trust_model": "frozen-native-closure-trusted-v1",
        "containment_claim": "none-trusted-pinned-native-computation",
        "non_system_image_owner_policy": "root-or-effective-user-v1",
        "non_system_image_mutability_policy": (
            "single-link-non-setid-not-group-or-world-writable-v1"
        ),
        "runpath_resolution_policy": (
            "loader-or-main-rpath-with-proven-zero-ancestor-only-edges-v1"
        ),
        "ancestor_only_runpath_edge_count": 0,
        "dynamic_loader_import_markers": [
            "dlopen",
            "NSBundle",
            "CFBundleLoadExecutable",
            "NSCreateObjectFileImageFromFile",
        ],
        "dynamic_loader_importing_images": [],
        "dynamic_loader_importing_image_count": 0,
        "dynamic_loader_imports_sha256": canonical_sha256(
            {
                "markers": [
                    "dlopen",
                    "NSBundle",
                    "CFBundleLoadExecutable",
                    "NSCreateObjectFileImageFromFile",
                ],
                "images": [],
            }
        ),
        "roots": {
            "source_executable": resolved_path,
            "staged_executable": resolved_path,
            "source_sha256": image_sha256,
            "staged_sha256": image_sha256,
            "source_dependency_projection_sha256": (
                dependency_projection_sha256
            ),
            "staged_dependency_projection_sha256": (
                dependency_projection_sha256
            ),
        },
        "runtime_gate": None,
        "images": [image],
        "edges": [],
        "system_cache": {},
        "total_hashed_bytes": 1,
        "image_count": 1,
        "edge_count": 0,
    }
    closure["closure_sha256"] = canonical_sha256(closure)
    return closure


def _synthetic_guard_authority() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    guard_path = "/synthetic/bin/python3"
    guard_sha256 = _sha("synthetic-guard-python")
    guard_python = {
        "resolved_path": guard_path,
        "sha256": guard_sha256,
        "device": 1,
        "inode": 21,
        "mode": stat.S_IFREG | 0o555,
        "uid": 0,
        "nlink": 1,
        "size": 1,
    }
    ancestor_paths = (
        guard_path,
        "/synthetic/bin",
        "/synthetic",
        "/",
    )
    ancestors = [
        {
            "resolved_path": path,
            "device": 1,
            "inode": 21 + index,
            "mode": (
                stat.S_IFREG | 0o555
                if index == 0
                else stat.S_IFDIR | 0o755
            ),
            "uid": 0,
            "gid": 0,
            "nlink": 1,
        }
        for index, path in enumerate(ancestor_paths)
    ]
    path_custody: dict[str, object] = {
        "schema_id": "parser-root-owned-guard-python-path-v1",
        "resolved_path": guard_path,
        "path_resolution_authority": (
            "darwin-root-owned-non-group-world-writable-ancestor-chain-v1"
        ),
        "ancestors": ancestors,
    }
    path_custody["record_sha256"] = canonical_sha256(path_custody)
    module_tree: dict[str, object] = {
        "schema_id": "parser-root-owned-guard-python-module-tree-v1",
        "resolved_root": "/synthetic",
        "entry_count": 1,
        "aggregate_bytes": 1,
        "root_owned_non_writable": True,
        "records_sha256": _sha("synthetic-guard-modules"),
    }
    module_tree["record_sha256"] = canonical_sha256(module_tree)
    guard_closure = _synthetic_native_closure(
        resolved_path=guard_path,
        image_sha256=guard_sha256,
        uid=0,
    )
    return guard_python, path_custody, guard_closure, module_tree


def _broker_lifecycle_receipt_fixture(
    *,
    logical_phase: str,
    attempt_nonce_sha256: str,
    scope_sha256: str,
    request_id: str,
    request_epoch: int,
    request_sequence: int,
    previous_receipt_sha256: str,
    worker: ExactProcessIdentity,
    broker: ExactProcessIdentity,
    observed_monotonic_ns: int,
    native_closure_sha256: str,
) -> BrokerLifecycleReceiptEvidence:
    begin_inventory = broker_scratch_inventory(
        root_device=1,
        root_inode=3,
        root_uid=501,
        scan_started_monotonic_ns=observed_monotonic_ns,
        scan_completed_monotonic_ns=observed_monotonic_ns,
    )
    end_inventory = broker_scratch_inventory(
        root_device=1,
        root_inode=3,
        root_uid=501,
        scan_started_monotonic_ns=observed_monotonic_ns + 2,
        scan_completed_monotonic_ns=observed_monotonic_ns + 2,
    )
    begin = BrokerQuiescenceReceipt(
        request_id=request_id,
        attempt_nonce_sha256=attempt_nonce_sha256,
        scope_sha256=scope_sha256,
        request_epoch=request_epoch,
        request_sequence=request_sequence,
        edge="begin",
        observed_monotonic_ns=observed_monotonic_ns,
        worker=worker,
        broker=broker,
        broker_thread_count=1,
        broker_thread_inventory_sha256=_sha(f"{request_id}-broker-thread"),
        broker_thread_observed_at_monotonic_ns=observed_monotonic_ns,
        ledger_head_sha256=previous_receipt_sha256,
        completed_spawn_count=0,
        worker_group_member_pids=(worker.pid,),
        broker_group_member_pids=(broker.pid,),
        request_root_inventory=begin_inventory,
    )
    end = begin.model_copy(
        update={
            "edge": "end",
            "observed_monotonic_ns": observed_monotonic_ns + 2,
            "broker_thread_observed_at_monotonic_ns": observed_monotonic_ns + 2,
            "request_root_inventory": end_inventory,
        }
    )

    def raw_identity(identity: ExactProcessIdentity) -> dict[str, int]:
        return {
            "pid": identity.pid,
            "start_abstime": identity.start_abstime,
            "ppid": identity.parent_pid,
            "pgid": identity.process_group_id,
            "sid": identity.session_id,
        }

    def raw_quiescence(
        retained: BrokerQuiescenceReceipt,
        *,
        phase: str,
    ) -> dict[str, object]:
        raw: dict[str, object] = {
            "request_id": retained.request_id,
            "request_epoch": retained.request_epoch,
            "request_sequence": retained.request_sequence,
            "phase": phase,
            "worker_identity": raw_identity(retained.worker),
            "active_job_count": 0,
            "launched_spawn_sequences": [],
            "reaped_spawn_sequences": [],
            "wait4_echild": True,
            "broker_identity": raw_identity(retained.broker),
            "broker_group_members": [raw_identity(retained.broker)],
            "worker_group_members": [raw_identity(retained.worker)],
            "recursive_descendants": [],
            "protocol_pending_bytes": 0,
            "ledger_head_sha256": retained.ledger_head_sha256,
            "completed_spawn_count": retained.completed_spawn_count,
            "process_group_scan_complete": True,
            "admission_lock_held": True,
            "broker_armed_and_blocked": True,
            "worker_fork_denial_active": True,
            "broker_thread_count": retained.broker_thread_count,
            "broker_thread_inventory_sha256": (
                retained.broker_thread_inventory_sha256
            ),
            "broker_thread_observed_at_monotonic_ns": (
                retained.broker_thread_observed_at_monotonic_ns
            ),
            "request_root_inventory": retained.request_root_inventory.model_dump(
                mode="json"
            ),
            "observed_at_monotonic_ns": retained.observed_monotonic_ns,
        }
        raw["observation_sha256"] = canonical_sha256(raw)
        return raw

    native_closure = _synthetic_native_closure(
        resolved_path="/synthetic/tesseract",
        image_sha256=_sha("synthetic-tesseract"),
        uid=501,
    )
    if native_closure["closure_sha256"] != native_closure_sha256:
        raise ValueError("synthetic native closure authority differs")
    guard_wrapper_source_hex = "00"
    guard_wrapper_source_sha256 = hashlib.sha256(b"\x00").hexdigest()
    (
        guard_python,
        guard_python_path_custody,
        guard_python_native_closure,
        guard_python_module_tree_custody,
    ) = _synthetic_guard_authority()
    raw: dict[str, object] = {
        "schema_id": "parser-tesseract-broker-v1",
        "attempt_nonce_sha256": attempt_nonce_sha256,
        "scope_sha256": scope_sha256,
        "request_id": request_id,
        "request_epoch": request_epoch,
        "request_sequence": request_sequence,
        "worker_thread_id": 1,
        "arm_capability_sha256": _sha(f"{request_id}-arm"),
        "arm_issued_at_monotonic_ns": observed_monotonic_ns,
        "arm_consumed_at_monotonic_ns": observed_monotonic_ns,
        "arm_terminal_disposition": "ended",
        "thread_transfer_required": False,
        "logical_phase": logical_phase,
        "terminal_kind": "end",
        "phase_deadline_monotonic_ns": observed_monotonic_ns + 10,
        "binding_sha256": canonical_sha256({}),
        "request_binding": None,
        "thread_claim_count": 0,
        "failure_reason_sha256": hashlib.sha256(b"").hexdigest(),
        "native_closure_sha256": native_closure_sha256,
        "native_closure": native_closure,
        "guard_python": guard_python,
        "guard_python_path_custody": guard_python_path_custody,
        "guard_python_native_closure": guard_python_native_closure,
        "guard_python_module_tree_custody": (
            guard_python_module_tree_custody
        ),
        "guard_wrapper_source_hex": guard_wrapper_source_hex,
        "guard_wrapper_source_sha256": guard_wrapper_source_sha256,
        "guard_wrapper_delivery_basis": "execve-python-c-embedded-source-v1",
        "begin": raw_quiescence(begin, phase="begin"),
        "thread_transfers": [],
        "births": [],
        "tombstones": [],
        "end": raw_quiescence(end, phase="end"),
        "previous_receipt_sha256": previous_receipt_sha256,
    }
    raw["receipt_sha256"] = canonical_sha256(raw)
    encoded = json.dumps(
        raw,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return broker_lifecycle_receipt_evidence(
        logical_phase=logical_phase,
        canonical_receipt_json=encoded,
        canonical_receipt_sha256=hashlib.sha256(encoded.encode()).hexdigest(),
        receipt_sha256=raw["receipt_sha256"],
        attempt_nonce_sha256=attempt_nonce_sha256,
        scope_sha256=scope_sha256,
        request_id=request_id,
        request_epoch=request_epoch,
        request_sequence=request_sequence,
        phase_deadline_monotonic_ns=observed_monotonic_ns + 10,
        arm_issued_at_monotonic_ns=observed_monotonic_ns,
        arm_consumed_at_monotonic_ns=observed_monotonic_ns,
        native_closure_sha256=native_closure_sha256,
        native_closure=native_closure,
        guard_python=guard_python,
        guard_python_path_custody=guard_python_path_custody,
        guard_python_native_closure=guard_python_native_closure,
        guard_python_module_tree_custody=guard_python_module_tree_custody,
        guard_wrapper_source_hex=guard_wrapper_source_hex,
        guard_wrapper_source_sha256=guard_wrapper_source_sha256,
        guard_wrapper_delivery_basis="execve-python-c-embedded-source-v1",
        previous_receipt_sha256=previous_receipt_sha256,
        begin=begin,
        end=end,
        children=(),
    )


def _raw_process_identity(identity: ExactProcessIdentity) -> dict[str, int]:
    return {
        "pid": identity.pid,
        "start_abstime": identity.start_abstime,
        "ppid": identity.parent_pid,
        "pgid": identity.process_group_id,
        "sid": identity.session_id,
    }


def _raw_quiescence_fixture(
    retained: BrokerQuiescenceReceipt,
    *,
    phase: str,
) -> dict[str, object]:
    raw: dict[str, object] = {
        "request_id": retained.request_id,
        "request_epoch": retained.request_epoch,
        "request_sequence": retained.request_sequence,
        "phase": phase,
        "worker_identity": _raw_process_identity(retained.worker),
        "active_job_count": 0,
        "launched_spawn_sequences": [],
        "reaped_spawn_sequences": [],
        "wait4_echild": True,
        "broker_identity": _raw_process_identity(retained.broker),
        "broker_group_members": [_raw_process_identity(retained.broker)],
        "worker_group_members": [_raw_process_identity(retained.worker)],
        "recursive_descendants": [],
        "protocol_pending_bytes": 0,
        "ledger_head_sha256": retained.ledger_head_sha256,
        "completed_spawn_count": retained.completed_spawn_count,
        "process_group_scan_complete": True,
        "admission_lock_held": True,
        "broker_armed_and_blocked": True,
        "worker_fork_denial_active": True,
        "broker_thread_count": retained.broker_thread_count,
        "broker_thread_inventory_sha256": (
            retained.broker_thread_inventory_sha256
        ),
        "broker_thread_observed_at_monotonic_ns": (
            retained.broker_thread_observed_at_monotonic_ns
        ),
        "request_root_inventory": retained.request_root_inventory.model_dump(
            mode="json"
        ),
        "observed_at_monotonic_ns": retained.observed_monotonic_ns,
    }
    raw["observation_sha256"] = canonical_sha256(raw)
    return raw


def _request_receipt_fixture(
    *,
    exact: ExactBrokerRequestCpuEvidence,
    previous_receipt_sha256: str,
    static_authority: BrokerLifecycleReceiptEvidence,
) -> tuple[dict[str, object], tuple[str, str]]:
    static = json.loads(static_authority.canonical_receipt_json)
    common = {
        "attempt_nonce_sha256": exact.attempt_nonce_sha256,
        "scope_sha256": exact.scope_sha256,
        "request_id": exact.request_id,
        "request_epoch": exact.request_epoch,
        "request_sequence": exact.request_sequence,
        "worker_pid": exact.begin.worker.pid,
        "worker_start_abstime": exact.begin.worker.start_abstime,
        "arm_capability_sha256": exact.arm_capability_sha256,
        "logical_phase": "request",
        "binding_sha256": exact.binding_sha256,
        "phase_deadline_monotonic_ns": exact.request_deadline_monotonic_ns,
        "first_permitted_spawn_sequence": 1,
        "last_permitted_spawn_sequence": 0,
    }
    claim: dict[str, object] = {
        **common,
        "transfer_sequence": 1,
        "kind": "claim",
        "from_python_thread_id": 11,
        "from_native_thread_id": 21,
        "to_python_thread_id": 13,
        "to_native_thread_id": 23,
        "previous_transfer_sha256": "0" * 64,
        "issued_at_monotonic_ns": exact.arm_consumed_at_monotonic_ns,
        "acknowledged_at_monotonic_ns": exact.arm_consumed_at_monotonic_ns,
    }
    claim["record_sha256"] = canonical_sha256(claim)
    release: dict[str, object] = {
        **common,
        "transfer_sequence": 2,
        "kind": "release",
        "from_python_thread_id": 13,
        "from_native_thread_id": 23,
        "to_python_thread_id": 11,
        "to_native_thread_id": 21,
        "previous_transfer_sha256": claim["record_sha256"],
        "issued_at_monotonic_ns": exact.end.observed_monotonic_ns - 1,
        "acknowledged_at_monotonic_ns": exact.end.observed_monotonic_ns - 1,
    }
    release["record_sha256"] = canonical_sha256(release)
    raw: dict[str, object] = {
        "schema_id": "parser-tesseract-broker-v1",
        "attempt_nonce_sha256": exact.attempt_nonce_sha256,
        "scope_sha256": exact.scope_sha256,
        "request_id": exact.request_id,
        "request_epoch": exact.request_epoch,
        "request_sequence": exact.request_sequence,
        "worker_thread_id": 21,
        "arm_capability_sha256": exact.arm_capability_sha256,
        "arm_issued_at_monotonic_ns": exact.arm_issued_at_monotonic_ns,
        "arm_consumed_at_monotonic_ns": exact.arm_consumed_at_monotonic_ns,
        "arm_terminal_disposition": "ended",
        "thread_transfer_required": True,
        "logical_phase": "request",
        "terminal_kind": "end",
        "phase_deadline_monotonic_ns": exact.request_deadline_monotonic_ns,
        "binding_sha256": exact.binding_sha256,
        "request_binding": exact.request_binding.model_dump(mode="json"),
        "thread_claim_count": 1,
        "failure_reason_sha256": hashlib.sha256(b"").hexdigest(),
        "native_closure_sha256": static["native_closure_sha256"],
        "native_closure": static["native_closure"],
        "guard_python": static["guard_python"],
        "guard_python_path_custody": static["guard_python_path_custody"],
        "guard_python_native_closure": static["guard_python_native_closure"],
        "guard_python_module_tree_custody": static[
            "guard_python_module_tree_custody"
        ],
        "guard_wrapper_source_hex": static["guard_wrapper_source_hex"],
        "guard_wrapper_source_sha256": static[
            "guard_wrapper_source_sha256"
        ],
        "guard_wrapper_delivery_basis": static[
            "guard_wrapper_delivery_basis"
        ],
        "begin": _raw_quiescence_fixture(exact.begin, phase="begin"),
        "thread_transfers": [claim, release],
        "births": [
            item.birth.model_dump(mode="json") for item in exact.children
        ],
        "tombstones": [
            item.tombstone.model_dump(mode="json") for item in exact.children
        ],
        "end": _raw_quiescence_fixture(exact.end, phase="end"),
        "previous_receipt_sha256": previous_receipt_sha256,
    }
    raw["receipt_sha256"] = canonical_sha256(raw)
    request_receipt_from_mapping(raw)
    return raw, (str(claim["record_sha256"]), str(release["record_sha256"]))


def _terminal_request_control_fixture(
    *,
    attempt_id: str,
    mode: RunMode,
    request_sources: tuple[SourceIdentity, ...],
    readiness: RequestControlReadinessEvidence,
    requests: tuple[contracts.RequestObservation, ...],
    startup_broker_receipt: BrokerLifecycleReceiptEvidence,
) -> tuple[
    RequestControlReadinessEvidence,
    tuple[contracts.RequestObservation, ...],
    contracts.TerminalRequestControlTranscriptEvidence,
    str,
]:
    zero = "0" * 64
    payload_previous = zero
    wire_previous = zero
    wire_sequence = 0
    retained_monotonic_ns = 0
    rows: list[dict[str, object]] = []

    def row_bytes(value: object) -> bytes:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    def append_row(
        kind: str,
        record: dict[str, object],
        *,
        retained_at: int,
    ) -> str:
        nonlocal retained_monotonic_ns
        retained_monotonic_ns = max(retained_monotonic_ns + 1, retained_at)
        row: dict[str, object] = {
            "schema_id": "phase-latency-request-control-transcript-row-v1",
            "row_sequence": len(rows) + 1,
            "previous_row_sha256": (
                str(rows[-1]["row_sha256"]) if rows else zero
            ),
            "kind": kind,
            "record": record,
            "retained_monotonic_ns": retained_monotonic_ns,
        }
        row["row_sha256"] = hashlib.sha256(row_bytes(row)).hexdigest()
        rows.append(row)
        return str(row["row_sha256"])

    def retain_frame(
        kind: str,
        direction: str,
        fields: dict[str, object],
        *,
        retained_at: int,
        send_deadline: int | None = None,
    ) -> tuple[dict[str, object], str]:
        nonlocal payload_previous, wire_previous, wire_sequence
        payload_without_hash = {
            **fields,
            "previous_record_sha256": payload_previous,
        }
        payload = {
            **payload_without_hash,
            "record_sha256": canonical_sha256(payload_without_hash),
        }
        frame_sha256 = contracts._request_control_frame_sha256(
            sequence=wire_sequence + 1,
            previous_sha256=wire_previous,
            kind=kind,
            payload=payload,
        )
        authorization_row_sha256 = append_row(
            kind,
            {
                "direction": direction,
                "frame_sha256": frame_sha256,
                "payload": payload,
            },
            retained_at=retained_at,
        )
        if direction == "controller_to_worker":
            deadline = send_deadline
            if deadline is None or retained_monotonic_ns >= deadline:
                raise ValueError("synthetic request-control send deadline differs")
            completed = retained_monotonic_ns
            append_row(
                "request_control_send_completed",
                {
                    "direction": direction,
                    "authorization_row_sha256": authorization_row_sha256,
                    "message_kind": kind,
                    "frame_sha256": frame_sha256,
                    "payload_record_sha256": payload["record_sha256"],
                    "deadline_monotonic_ns": deadline,
                    "send_completed_monotonic_ns": completed,
                },
                retained_at=completed,
            )
        wire_sequence += 1
        wire_previous = frame_sha256
        payload_previous = str(payload["record_sha256"])
        return payload, authorization_row_sha256

    ready_payload, ready_row_sha256 = retain_frame(
        "request_control_ready",
        "worker_to_controller",
        {
            "schema_id": "parser-request-control-ready-v1",
            "attempt_id": readiness.attempt_id,
            "attempt_nonce_sha256": readiness.attempt_nonce_sha256,
            "scope_sha256": readiness.scope_sha256,
            "worker": RequestControlReadinessEvidence._identity_mapping(
                readiness.worker
            ),
            "broker": RequestControlReadinessEvidence._identity_mapping(
                readiness.broker
            ),
            "expected_request_count": readiness.expected_request_count,
            "framework_thread_baseline": (
                readiness.framework_thread_baseline.model_dump(mode="json")
            ),
            "ready_at_monotonic_ns": readiness.ready_at_monotonic_ns,
        },
        retained_at=readiness.ready_at_monotonic_ns,
    )
    if ready_payload["record_sha256"] != readiness.ready_record_sha256:
        raise ValueError("synthetic request-control READY identity differs")
    retained_readiness = request_control_readiness_evidence(
        attempt_id=readiness.attempt_id,
        attempt_nonce_sha256=readiness.attempt_nonce_sha256,
        scope_sha256=readiness.scope_sha256,
        worker=readiness.worker,
        broker=readiness.broker,
        expected_request_count=readiness.expected_request_count,
        framework_thread_baseline=readiness.framework_thread_baseline,
        controller_worker_thread_inventory=(
            readiness.controller_worker_thread_inventory
        ),
        controller_worker_file_descriptor_inventory=(
            readiness.controller_worker_file_descriptor_inventory
        ),
        controller_broker_thread_inventory=(
            readiness.controller_broker_thread_inventory
        ),
        controller_broker_file_descriptor_inventory=(
            readiness.controller_broker_file_descriptor_inventory
        ),
        ready_at_monotonic_ns=readiness.ready_at_monotonic_ns,
        transcript_row_sha256=ready_row_sha256,
    )

    previous_receipt_sha256 = startup_broker_receipt.receipt_sha256
    retained_requests: list[contracts.RequestObservation] = []
    final_request_deadline = 0
    if len(request_sources) != len(requests):
        raise ValueError("synthetic request-control source count differs")
    for observation, request_source in zip(
        requests, request_sources, strict=True
    ):
        if (
            observation.output is None
            or observation.resource_boundary is None
            or observation.resource_boundary.exact_broker_cpu is None
        ):
            raise ValueError("synthetic request-control request is incomplete")
        boundary = observation.resource_boundary
        original_exact = boundary.exact_broker_cpu
        begin = original_exact.begin.model_copy(
            update={"ledger_head_sha256": previous_receipt_sha256}
        )
        end = original_exact.end.model_copy(
            update={"ledger_head_sha256": previous_receipt_sha256}
        )
        staged_exact = ExactBrokerRequestCpuEvidence.model_validate(
            {
                **original_exact.model_dump(mode="python"),
                "begin": begin,
                "end": end,
            }
        )
        raw_receipt, transfer_sha256s = _request_receipt_fixture(
            exact=staged_exact,
            previous_receipt_sha256=previous_receipt_sha256,
            static_authority=startup_broker_receipt,
        )
        receipt_sha256 = str(raw_receipt["receipt_sha256"])
        request_sequence = staged_exact.request_sequence
        deadline = staged_exact.request_deadline_monotonic_ns
        final_request_deadline = deadline
        identity_common: dict[str, object] = {
            "attempt_id": attempt_id,
            "attempt_nonce_sha256": staged_exact.attempt_nonce_sha256,
            "scope_sha256": staged_exact.scope_sha256,
            "request_id": staged_exact.request_id,
            "request_epoch": staged_exact.request_epoch,
            "request_sequence": request_sequence,
            "worker": RequestControlReadinessEvidence._identity_mapping(
                retained_readiness.worker
            ),
            "broker": RequestControlReadinessEvidence._identity_mapping(
                retained_readiness.broker
            ),
            "request_deadline_monotonic_ns": deadline,
        }
        wire_binding = {
            "schema_id": "parser-broker-request-binding-v2",
            "method": staged_exact.request_binding.method,
            "path": staged_exact.request_binding.path,
            "query_sha256": staged_exact.request_binding.query_sha256,
            "output_format": staged_exact.request_binding.output_format,
            "source_sha256": staged_exact.request_binding.source_sha256,
            "source_bytes": staged_exact.request_binding.source_bytes,
            "safe_filename_sha256": (
                staged_exact.request_binding.safe_filename_sha256
            ),
            "upload_content_type_sha256": (
                staged_exact.request_binding.upload_content_type_sha256
            ),
        }
        arm, arm_row = retain_frame(
            "request_control_arm",
            "controller_to_worker",
            {
                "schema_id": "parser-request-control-arm-v1",
                **identity_common,
                "binding": wire_binding,
                "binding_sha256": staged_exact.binding_sha256,
                "arm_issued_at_monotonic_ns": (
                    staged_exact.arm_issued_at_monotonic_ns
                ),
            },
            retained_at=staged_exact.arm_issued_at_monotonic_ns,
            send_deadline=deadline,
        )
        begin_barrier = {
            "kind": "BEGIN",
            "request_id": staged_exact.request_id,
            "request_epoch": staged_exact.request_epoch,
            "request_sequence": request_sequence,
            "broker_identity": raw_receipt["begin"]["broker_identity"],
            "quiescence": raw_receipt["begin"],
            "client_protocol_pending_bytes": 0,
            "transcript_next_sequence": request_sequence * 2,
            "transcript_head_sha256": _sha(
                f"{attempt_id}-{request_sequence}-broker-begin"
            ),
            "receipt_sha256": None,
        }
        begin_blocked, begin_blocked_row = retain_frame(
            "request_control_begin_blocked",
            "worker_to_controller",
            {
                "schema_id": "parser-request-control-begin-blocked-v1",
                **identity_common,
                "arm_record_sha256": arm["record_sha256"],
                "arm_capability_sha256": staged_exact.arm_capability_sha256,
                "arm_consumed_at_monotonic_ns": (
                    staged_exact.arm_consumed_at_monotonic_ns
                ),
                "begin_barrier": begin_barrier,
            },
            retained_at=staged_exact.arm_consumed_at_monotonic_ns,
        )
        begin_release, begin_release_row = retain_frame(
            "request_control_begin_release",
            "controller_to_worker",
            {
                "schema_id": "parser-request-control-begin-release-v1",
                **identity_common,
                "begin_blocked_record_sha256": begin_blocked[
                    "record_sha256"
                ],
                "begin_sample_record_sha256": (
                    staged_exact.begin_external_sample.record_sha256
                ),
                "begin_samples_completed_monotonic_ns": (
                    staged_exact.worker_before.observed_monotonic_ns
                ),
                "begin_release_monotonic_ns": (
                    staged_exact.begin_release_monotonic_ns
                ),
            },
            retained_at=staged_exact.begin_release_monotonic_ns,
            send_deadline=deadline,
        )
        end_barrier = {
            "kind": "END",
            "request_id": staged_exact.request_id,
            "request_epoch": staged_exact.request_epoch,
            "request_sequence": request_sequence,
            "broker_identity": raw_receipt["end"]["broker_identity"],
            "quiescence": raw_receipt["end"],
            "client_protocol_pending_bytes": 0,
            "transcript_next_sequence": request_sequence * 2 + 1,
            "transcript_head_sha256": _sha(
                f"{attempt_id}-{request_sequence}-broker-end"
            ),
            "receipt_sha256": receipt_sha256,
        }
        response_witness = staged_exact.asgi_response_witness.model_dump(
            mode="json"
        )
        end_blocked, end_blocked_row = retain_frame(
            "request_control_end_blocked",
            "worker_to_controller",
            {
                "schema_id": "parser-request-control-end-blocked-v1",
                **identity_common,
                "begin_release_record_sha256": begin_release[
                    "record_sha256"
                ],
                "end_barrier": end_barrier,
                "broker_request_receipt": raw_receipt,
                "broker_request_receipt_sha256": receipt_sha256,
                "request_binding_record_sha256": (
                    staged_exact.request_binding.record_sha256
                ),
                "thread_transfer_record_sha256s": list(transfer_sha256s),
                "asgi_response_witness": response_witness,
                "asgi_response_witness_sha256": (
                    staged_exact.asgi_response_witness_sha256
                ),
                "full_inner_asgi_returned": True,
                "request_task_blocked": True,
            },
            retained_at=staged_exact.end.observed_monotonic_ns,
        )
        receipt_release, receipt_release_row = retain_frame(
            "request_control_receipt_release",
            "controller_to_worker",
            {
                "schema_id": "parser-request-control-receipt-release-v1",
                **identity_common,
                "end_blocked_record_sha256": end_blocked["record_sha256"],
                "end_sample_record_sha256": (
                    staged_exact.end_external_sample.record_sha256
                ),
                "end_samples_completed_monotonic_ns": (
                    staged_exact.worker_after.observed_monotonic_ns
                ),
                "broker_request_receipt_sha256": receipt_sha256,
                "receipt_release_monotonic_ns": (
                    staged_exact.receipt_release_monotonic_ns
                ),
            },
            retained_at=staged_exact.receipt_release_monotonic_ns,
            send_deadline=deadline,
        )
        worker_result = production_worker.production_raw_request_observation(
            attempt_id=attempt_id,
            request_id=staged_exact.request_id,
            request_index=request_sequence,
            request_epoch=staged_exact.request_epoch,
            source=request_source,
            client_post_started_monotonic_ns=(
                staged_exact.begin_release_monotonic_ns
            ),
            client_post_completed_monotonic_ns=(
                staged_exact.receipt_release_monotonic_ns + 1
            ),
            client_post_elapsed_ns=(
                staged_exact.receipt_release_monotonic_ns
                + 1
                - staged_exact.begin_release_monotonic_ns
            ),
            response_content_type_sha256=hashlib.sha256(
                b"application/json"
            ).hexdigest(),
            response_body_sha256=observation.output.sha256,
            asgi_response_witness_sha256=(
                staged_exact.asgi_response_witness_sha256
            ),
            response_size_bytes=observation.output.size_bytes,
            output=observation.output,
            runtime_snapshot_sha256=_sha(
                f"{attempt_id}-{request_sequence}-runtime"
            ),
            converter_sha256=(
                None
                if mode is RunMode.PREDECESSOR
                else _sha(f"{attempt_id}-converter")
            ),
            broker_request_receipt_sha256=receipt_sha256,
            request_binding_record_sha256=(
                staged_exact.request_binding.record_sha256
            ),
            materialized_at_monotonic_ns=(
                staged_exact.receipt_release_monotonic_ns + 2
            ),
        )
        result, result_row = retain_frame(
            "request_control_result",
            "worker_to_controller",
            {
                "schema_id": "parser-request-control-result-v1",
                **identity_common,
                "receipt_release_record_sha256": receipt_release[
                    "record_sha256"
                ],
                "worker_result": worker_result.model_dump(mode="json"),
            },
            retained_at=worker_result.materialized_at_monotonic_ns,
        )
        result_ack, result_ack_row = retain_frame(
            "request_control_result_ack",
            "controller_to_worker",
            {
                "schema_id": "parser-request-control-result-ack-v1",
                **identity_common,
                "result_record_sha256": result["record_sha256"],
                "retained_at_monotonic_ns": (
                    worker_result.materialized_at_monotonic_ns + 1
                ),
            },
            retained_at=worker_result.materialized_at_monotonic_ns + 1,
            send_deadline=deadline,
        )
        del result_ack
        retained_exact = ExactBrokerRequestCpuEvidence.model_validate(
            {
                **staged_exact.model_dump(mode="python"),
                "thread_transfer_record_sha256s": transfer_sha256s,
                "broker_request_receipt_sha256": receipt_sha256,
                "request_control_arm_record_sha256": arm[
                    "record_sha256"
                ],
                "request_control_begin_blocked_record_sha256": (
                    begin_blocked["record_sha256"]
                ),
                "request_control_begin_release_record_sha256": (
                    begin_release["record_sha256"]
                ),
                "request_control_end_blocked_record_sha256": (
                    end_blocked["record_sha256"]
                ),
                "request_control_receipt_release_record_sha256": (
                    receipt_release["record_sha256"]
                ),
                "request_control_result_record_sha256": result[
                    "record_sha256"
                ],
                "request_control_result_ack_record_sha256": (
                    payload_previous
                ),
                "request_control_transcript_row_sha256s": (
                    arm_row,
                    begin_blocked_row,
                    begin_release_row,
                    end_blocked_row,
                    receipt_release_row,
                    result_row,
                    result_ack_row,
                ),
            }
        )
        retained_boundary = RequestResourceBoundary.model_validate(
            {
                **boundary.model_dump(mode="python"),
                "exact_broker_cpu": retained_exact,
            }
        )
        retained_requests.append(
            observation.model_copy(
                update={"resource_boundary": retained_boundary}
            )
        )
        previous_receipt_sha256 = receipt_sha256

    if not retained_requests or final_request_deadline <= 0:
        raise ValueError("synthetic request-control transcript lacks requests")
    close, _close_row = retain_frame(
        "request_control_close",
        "worker_to_controller",
        {
            "schema_id": "parser-request-control-close-v1",
            "attempt_id": attempt_id,
            "attempt_nonce_sha256": retained_readiness.attempt_nonce_sha256,
            "scope_sha256": retained_readiness.scope_sha256,
            "worker": RequestControlReadinessEvidence._identity_mapping(
                retained_readiness.worker
            ),
            "broker": RequestControlReadinessEvidence._identity_mapping(
                retained_readiness.broker
            ),
            "completed_request_count": len(retained_requests),
            "last_request_sequence": len(retained_requests),
        },
        retained_at=retained_monotonic_ns + 1,
    )
    close_deadline = max(final_request_deadline, retained_monotonic_ns + 2)
    retain_frame(
        "request_control_close_ack",
        "controller_to_worker",
        {
            "schema_id": "parser-request-control-close-ack-v1",
            "attempt_id": attempt_id,
            "attempt_nonce_sha256": retained_readiness.attempt_nonce_sha256,
            "scope_sha256": retained_readiness.scope_sha256,
            "worker": RequestControlReadinessEvidence._identity_mapping(
                retained_readiness.worker
            ),
            "broker": RequestControlReadinessEvidence._identity_mapping(
                retained_readiness.broker
            ),
            "completed_request_count": len(retained_requests),
            "close_record_sha256": close["record_sha256"],
            "closed_at_monotonic_ns": retained_monotonic_ns + 1,
        },
        retained_at=retained_monotonic_ns + 1,
        send_deadline=close_deadline,
    )
    raw = b"".join(row_bytes(row) + b"\n" for row in rows)
    terminal = terminal_request_control_transcript_evidence(
        raw,
        file_device=1,
        file_inode=int(hashlib.sha256(attempt_id.encode()).hexdigest()[:12], 16)
        + 1,
        file_uid=501,
    )
    retained_exact = tuple(
        item.resource_boundary.exact_broker_cpu
        for item in retained_requests
        if item.resource_boundary is not None
        and item.resource_boundary.exact_broker_cpu is not None
    )
    contracts.require_terminal_request_control_transcript(
        terminal,
        retained_readiness,
        retained_exact,
        request_sources=request_sources,
        request_outputs=tuple(
            item.output
            for item in retained_requests
            if item.output is not None
            and item.resource_boundary is not None
            and item.resource_boundary.exact_broker_cpu is not None
        ),
    )
    return (
        retained_readiness,
        tuple(retained_requests),
        terminal,
        previous_receipt_sha256,
    )


def _terminal_transcript_with_rehashed_result_witness_mismatch(
    raw: bytes,
) -> bytes:
    """Re-chain a success transcript after changing one valid raw-result field."""

    rows = [json.loads(line) for line in raw.splitlines()]
    changed = False
    for row in rows:
        if row.get("kind") != "request_control_result":
            continue
        record = row.get("record")
        if not isinstance(record, dict):
            raise AssertionError("request-control result row differs")
        payload = record.get("payload")
        if not isinstance(payload, dict):
            raise AssertionError("request-control result payload differs")
        worker_result = payload.get("worker_result")
        if not isinstance(worker_result, dict):
            raise AssertionError("request-control raw result differs")
        worker_result["asgi_response_witness_sha256"] = _sha(
            "rehashed-wrong-asgi-witness"
        )
        worker_result.pop("record_sha256", None)
        worker_result["record_sha256"] = canonical_sha256(worker_result)
        changed = True
        break
    if not changed:
        raise AssertionError("request-control transcript lacks a result")

    zero = "0" * 64
    outer_previous = zero
    payload_previous = zero
    wire_previous = zero
    wire_sequence = 0
    pending_authorization: dict[str, object] | None = None
    retained_payloads: dict[str, dict[str, object]] = {}
    linked_payloads = {
        "request_control_begin_blocked": (
            "arm_record_sha256",
            "request_control_arm",
        ),
        "request_control_begin_release": (
            "begin_blocked_record_sha256",
            "request_control_begin_blocked",
        ),
        "request_control_end_blocked": (
            "begin_release_record_sha256",
            "request_control_begin_release",
        ),
        "request_control_receipt_release": (
            "end_blocked_record_sha256",
            "request_control_end_blocked",
        ),
        "request_control_result": (
            "receipt_release_record_sha256",
            "request_control_receipt_release",
        ),
        "request_control_result_ack": (
            "result_record_sha256",
            "request_control_result",
        ),
        "request_control_close_ack": (
            "close_record_sha256",
            "request_control_close",
        ),
    }
    encoded: list[bytes] = []

    for row_sequence, row in enumerate(rows, 1):
        kind = row.get("kind")
        record = row.get("record")
        if not isinstance(kind, str) or not isinstance(record, dict):
            raise AssertionError("request-control transcript row differs")
        row["row_sequence"] = row_sequence
        row["previous_row_sha256"] = outer_previous
        row.pop("row_sha256", None)

        if kind == "request_control_send_completed":
            if pending_authorization is None:
                raise AssertionError("request-control completion lacks authority")
            record.update(
                {
                    "authorization_row_sha256": pending_authorization[
                        "row_sha256"
                    ],
                    "message_kind": pending_authorization["kind"],
                    "frame_sha256": pending_authorization["frame_sha256"],
                    "payload_record_sha256": pending_authorization[
                        "payload_record_sha256"
                    ],
                }
            )
            row["record"] = record
        else:
            direction = record.get("direction")
            payload = record.get("payload")
            if direction not in {
                "controller_to_worker",
                "worker_to_controller",
            } or not isinstance(payload, dict):
                raise AssertionError("request-control retained frame differs")
            payload["previous_record_sha256"] = payload_previous
            link = linked_payloads.get(kind)
            if link is not None:
                field, previous_kind = link
                prior = retained_payloads.get(previous_kind)
                if prior is None:
                    raise AssertionError("request-control explicit link differs")
                payload[field] = prior["record_sha256"]
            payload.pop("record_sha256", None)
            payload["record_sha256"] = canonical_sha256(payload)
            frame_sha256 = contracts._request_control_frame_sha256(
                sequence=wire_sequence + 1,
                previous_sha256=wire_previous,
                kind=kind,
                payload=payload,
            )
            row["record"] = {
                "direction": direction,
                "frame_sha256": frame_sha256,
                "payload": payload,
            }
            retained_payloads[kind] = payload

        row["row_sha256"] = canonical_sha256(row)
        outer_previous = str(row["row_sha256"])
        encoded.append(
            json.dumps(
                row,
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )

        if kind == "request_control_send_completed":
            assert pending_authorization is not None
            wire_sequence += 1
            wire_previous = str(pending_authorization["frame_sha256"])
            payload_previous = str(
                pending_authorization["payload_record_sha256"]
            )
            pending_authorization = None
        else:
            retained_record = row["record"]
            assert isinstance(retained_record, dict)
            retained_payload = retained_record["payload"]
            assert isinstance(retained_payload, dict)
            if retained_record["direction"] == "controller_to_worker":
                pending_authorization = {
                    "kind": kind,
                    "frame_sha256": retained_record["frame_sha256"],
                    "payload_record_sha256": retained_payload["record_sha256"],
                    "row_sha256": row["row_sha256"],
                }
            else:
                wire_sequence += 1
                wire_previous = str(retained_record["frame_sha256"])
                payload_previous = str(retained_payload["record_sha256"])

    if pending_authorization is not None:
        raise AssertionError("request-control transcript ended before completion")
    return b"".join(encoded)


def _immutable_runtime_input_custody_fixture(
    *,
    attempt_id: str,
    artifact: FileTreeIdentityEvidence,
) -> ImmutableRuntimeInputCustodyEvidence:
    files_by_role: dict[str, tuple[dict[str, object], ...]] = {
        "docling_artifacts": (
            {
                "path": "artifact-a.bin",
                "sha256": _sha("artifact-a"),
                "size_bytes": 1,
            },
            {
                "path": "artifact-b.bin",
                "sha256": _sha("artifact-b"),
                "size_bytes": 1,
            },
        ),
        "staged_execution_inputs": (
            {
                "path": "tesseract",
                "sha256": _sha("synthetic-tesseract"),
                "size_bytes": 1,
            },
            {
                "path": "source-tesseract",
                "sha256": _sha("synthetic-source-tesseract"),
                "size_bytes": 1,
            },
            {
                "path": "native-fork-probe.c",
                "sha256": "3" * 64,
                "size_bytes": 1,
            },
            {
                "path": "native-fork-probe.dylib",
                "sha256": "4" * 64,
                "size_bytes": 1,
            },
            {
                "path": "native-spawn-guard.c",
                "sha256": "d" * 64,
                "size_bytes": 1,
            },
            {
                "path": "native-spawn-guard.dylib",
                "sha256": "e" * 64,
                "size_bytes": 1,
            },
            {
                "path": "native-runtime-gate.c",
                "sha256": _sha("runtime-gate-source"),
                "size_bytes": 1,
            },
            {
                "path": "native-runtime-gate.dylib",
                "sha256": _sha("runtime-gate-library"),
                "size_bytes": 1,
            },
        ),
        "tessdata": (
            {
                "path": "eng.traineddata",
                "sha256": _sha("eng-traineddata"),
                "size_bytes": 1,
            },
        ),
    }
    def manifest_sha256(records: tuple[dict[str, object], ...]) -> str:
        return canonical_sha256(
            tuple(sorted(records, key=lambda item: str(item["path"])))
        )

    if artifact.sha256 != manifest_sha256(files_by_role["docling_artifacts"]):
        raise ValueError("synthetic artifact/custody manifest differs")
    authorities = (
        ImmutableRuntimeInputRootAuthority(
            role="docling_artifacts",
            resolved_path="/synthetic/docling-artifacts",
            device=1,
            inode=101,
            kind="directory",
            content_manifest_sha256=artifact.sha256,
            file_count=artifact.file_count,
            aggregate_bytes=artifact.aggregate_bytes,
        ),
        ImmutableRuntimeInputRootAuthority(
            role="staged_execution_inputs",
            resolved_path="/synthetic/staged-execution-inputs",
            device=1,
            inode=102,
            kind="directory",
            content_manifest_sha256=manifest_sha256(
                files_by_role["staged_execution_inputs"]
            ),
            file_count=len(files_by_role["staged_execution_inputs"]),
            aggregate_bytes=sum(
                int(item["size_bytes"])
                for item in files_by_role["staged_execution_inputs"]
            ),
        ),
        ImmutableRuntimeInputRootAuthority(
            role="tessdata",
            resolved_path="/synthetic/tessdata",
            device=1,
            inode=103,
            kind="directory",
            content_manifest_sha256=manifest_sha256(files_by_role["tessdata"]),
            file_count=len(files_by_role["tessdata"]),
            aggregate_bytes=sum(
                int(item["size_bytes"])
                for item in files_by_role["tessdata"]
            ),
        ),
    )
    identities = tuple(
        ImmutableRuntimeInputPathIdentity(
            role=item.role,
            resolved_path=item.resolved_path,
            device=item.device,
            inode=item.inode,
            kind=item.kind,
        )
        for item in authorities
    )
    entries: list[ImmutableRuntimeInputEntry] = []
    memberships: list[ImmutableRuntimeInputDirectoryMembership] = []
    for authority in authorities:
        entries.append(
            ImmutableRuntimeInputEntry(
                role=authority.role,
                root=authority.resolved_path,
                vnode_filter_registered_at_monotonic_ns=1,
                relative_path=".",
                kind="directory",
                device=authority.device,
                inode=authority.inode,
                mode=stat.S_IFDIR | 0o700,
                uid=501,
                gid=20,
                nlink=2,
                size_bytes=0,
                content_sha256=None,
            )
        )
        members: list[ImmutableRuntimeInputDirectoryMember] = []
        for offset, record in enumerate(
            files_by_role[authority.role], start=1
        ):
            inode = authority.inode * 100 + offset
            entries.append(
                ImmutableRuntimeInputEntry(
                    role=authority.role,
                    root=authority.resolved_path,
                    vnode_filter_registered_at_monotonic_ns=1,
                    relative_path=str(record["path"]),
                    kind="file",
                    device=authority.device,
                    inode=inode,
                    mode=stat.S_IFREG | 0o400,
                    uid=501,
                    gid=20,
                    nlink=1,
                    size_bytes=int(record["size_bytes"]),
                    content_sha256=str(record["sha256"]),
                )
            )
            members.append(
                ImmutableRuntimeInputDirectoryMember(
                    name=str(record["path"]),
                    kind="file",
                    device=authority.device,
                    inode=inode,
                )
            )
        memberships.append(
            ImmutableRuntimeInputDirectoryMembership(
                role=authority.role,
                root=authority.resolved_path,
                relative_path=".",
                device=authority.device,
                inode=authority.inode,
                members=tuple(sorted(members, key=lambda item: item.name)),
            )
        )
    projection_sha256 = canonical_sha256(
        [item.model_dump(mode="json") for item in entries]
    )
    fields: dict[str, object] = {
        "schema_id": "parser-darwin-immutable-tree-custody-v1",
        "attempt_id": attempt_id,
        "event_authority": "darwin-kqueue-EVFILT_VNODE-held-fd-v1",
        "monitored_note_flags": (
            "WRITE",
            "EXTEND",
            "ATTRIB",
            "LINK",
            "RENAME",
            "DELETE",
            "REVOKE",
        ),
        "armed_at_monotonic_ns": 1,
        "completed_at_monotonic_ns": 5_000_000_000,
        "maximum_entries": 4_096,
        "maximum_bytes": 17_179_869_184,
        "entry_count": len(entries),
        "aggregate_file_bytes": sum(
            item.aggregate_bytes for item in authorities
        ),
        "root_authorities": authorities,
        "root_path_identities_before": identities,
        "root_path_identities_after": identities,
        "entry_projection": tuple(entries),
        "directory_membership_projection": tuple(memberships),
        "initial_projection_sha256": projection_sha256,
        "final_projection_sha256": projection_sha256,
        "event_count": 0,
        "events": (),
        "root_paths_stable": True,
        "held_vnodes_unchanged": True,
        "no_relevant_vnode_events": True,
    }
    provisional = ImmutableRuntimeInputCustodyEvidence.model_construct(
        **fields,
        record_sha256="0" * 64,
    )
    return ImmutableRuntimeInputCustodyEvidence(
        **fields,
        record_sha256=canonical_sha256(
            provisional.model_dump(mode="json", exclude={"record_sha256"})
        ),
    )


@pytest.fixture(scope="module")
def production_flagged_control(
    tmp_path_factory: pytest.TempPathFactory,
) -> LocalPrewarmEvidenceBundle:
    directory = tmp_path_factory.mktemp("lat-us02-production-gates")
    source_path = directory / "bounded.pdf"
    source_path.write_bytes(b"%PDF-1.7\n% production gate control\n%%EOF\n")
    result = run_synthetic_local_campaign(
        workspace=Path(__file__).resolve().parents[2],
        cases=(
            LocalCase(
                case_id="production-gate-control",
                source_path=source_path,
                source_label="tests/fixtures/phase_latency/production-gate-control.pdf",
                page_count=1,
            ),
        ),
        repetitions=2,
        request_count=4,
    )
    bundle = result.bundle
    changed_attempts = []
    artifact_boundary = FileTreeIdentityEvidence(
        sha256=canonical_sha256(
            (
                {
                    "path": "artifact-a.bin",
                    "sha256": _sha("artifact-a"),
                    "size_bytes": 1,
                },
                {
                    "path": "artifact-b.bin",
                    "sha256": _sha("artifact-b"),
                    "size_bytes": 1,
                },
            )
        ),
        metadata_sha256="2" * 64,
        file_count=2,
        aggregate_bytes=2,
    )
    worker_identity = ExactProcessIdentity(
        role="parser_worker",
        pid=100,
        start_abstime=1,
        parent_pid=60,
        process_group_id=100,
        session_id=100,
    )
    broker_identity = ExactProcessIdentity(
        role="tesseract_broker",
        pid=200,
        start_abstime=2,
        parent_pid=60,
        process_group_id=200,
        session_id=200,
    )
    synthetic_tesseract_closure = _synthetic_native_closure(
        resolved_path="/synthetic/tesseract",
        image_sha256=_sha("synthetic-tesseract"),
        uid=501,
    )
    fork_denial = worker_fork_denial_evidence(
        effective_uid=501,
        real_uid=501,
        broker_effective_uid=501,
        broker_real_uid=501,
        seatbelt_executable_sha256="3" * 64,
        seatbelt_profile_sha256="4" * 64,
        native_exec_guard_sha256="5" * 64,
        supervisor_capability_sha256="6" * 64,
        broker_protocol_sha256="7" * 64,
        broker_client_sha256="8" * 64,
        request_control_sha256="0" * 64,
        supervisor_sha256="9" * 64,
        broker_server_sha256="a" * 64,
        broker_native_sha256="b" * 64,
        broker_native_spawn_guard_source_sha256="d" * 64,
        broker_native_spawn_guard_library_sha256="e" * 64,
        native_runtime_gate_source_sha256=_sha("runtime-gate-source"),
        native_runtime_gate_library_sha256=_sha("runtime-gate-library"),
        native_runtime_gate_record_sha256=_sha("runtime-gate-record"),
        python_executable_sha256="c" * 64,
        watchdog_protocol_sha256="d" * 64,
        watchdog_ledger_schema_sha256="e" * 64,
        broker_profile_sha256="f" * 64,
        worker_profile_sha256="1" * 64,
        native_closure_sha256=str(
            synthetic_tesseract_closure["closure_sha256"]
        ),
        platform_release="25.0.0",
        machine_architecture="arm64",
        kernel_identity_sha256="2" * 64,
        native_fork_probe_source_sha256="3" * 64,
        native_fork_probe_library_sha256="4" * 64,
        native_fork_probe_device=1,
        native_fork_probe_inode=5,
        native_fork_probe_mode=stat.S_IFREG | 0o500,
        native_fork_probe_uid=501,
        hard_limit_installed_at_monotonic_ns=1,
        first_app_import_started_at_monotonic_ns=2,
        native_fork_probe_loaded_at_monotonic_ns=1,
        python_implementation="cpython",
        python_version="3.13.0",
        raw_fork_errno=1,
        raw_vfork_errno=1,
        raw_posix_spawn_errno=1,
        python_subprocess_errno=1,
        native_import_time_fork_errno=1,
        worker=worker_identity,
        broker=broker_identity,
        launcher=TrustedLauncherIdentity(
            pid=60,
            start_abstime=4,
            ppid=50,
            pgid=60,
            sid=60,
            uid=501,
            euid=501,
        ),
        controller_pid=50,
        controller_start_abstime=3,
        launcher_pid=60,
        launcher_start_abstime=4,
        capability_device=-1,
        capability_inode=2,
        capability_family=1,
        capability_socket_type=1,
        request_control_device=-1,
        request_control_inode=4,
        request_control_family=1,
        request_control_socket_type=1,
        expected_request_count=4,
        worker_scratch_path_sha256="5" * 64,
        worker_scratch_device=1,
        worker_scratch_inode=3,
        worker_scratch_uid=501,
        installed_at_monotonic_ns=2,
    )
    for attempt in bundle.attempts:
        baseline_worker_threads = _native_thread_inventory(
            worker_identity, (1_001, 1_002, 1_003, 1_004), 9
        )
        broker_ready_threads = _native_thread_inventory(
            broker_identity, (2_001,), 9
        )
        broker_pre_release_threads = _native_thread_inventory(
            broker_identity, broker_ready_threads.thread_ids, 8
        )
        broker_post_release = broker_post_release_baseline(
            broker=broker_pre_release_threads.process,
            pre_release_ready_sha256=_sha("broker-pre-release-ready"),
            retired_descriptor_fds=(3, 4),
            pre_release_thread_inventory=broker_pre_release_threads,
            pre_release_file_descriptor_inventory=_native_fd_inventory(
                broker_identity, 5, 8
            ),
            post_release_thread_inventory=broker_ready_threads,
            post_release_file_descriptor_inventory=_native_fd_inventory(
                broker_identity, 3, 9
            ),
            transition_observed_at_monotonic_ns=9,
        )
        framework_baseline = framework_thread_baseline(
            worker_pid=worker_identity.pid,
            worker_start_abstime=worker_identity.start_abstime,
            worker_ppid=worker_identity.parent_pid,
            worker_pgid=worker_identity.process_group_id,
            worker_sid=worker_identity.session_id,
            event_loop_python_thread_id=11,
            event_loop_native_thread_id=21,
            asyncio_executor_python_thread_id=12,
            asyncio_executor_native_thread_id=22,
            anyio_worker_python_thread_id=13,
            anyio_worker_native_thread_id=23,
            full_worker_proc_thread_ids=baseline_worker_threads.thread_ids,
            full_worker_proc_thread_count=baseline_worker_threads.thread_count,
            full_worker_proc_thread_inventory_sha256=(
                baseline_worker_threads.inventory_sha256
            ),
            first_full_inventory_observed_at_monotonic_ns=9,
            second_full_inventory_observed_at_monotonic_ns=9,
            full_worker_file_descriptor_inventory=_native_fd_inventory(
                worker_identity, 5, 9
            ),
            broker_post_release_baseline=broker_post_release,
            observed_at_monotonic_ns=10,
        )
        controller_worker_threads = _native_thread_inventory(
            worker_identity, baseline_worker_threads.thread_ids, 12
        )
        controller_broker_threads = _native_thread_inventory(
            broker_identity, broker_ready_threads.thread_ids, 12
        )
        readiness = request_control_readiness_evidence(
            attempt_id=attempt.attempt_id,
            attempt_nonce_sha256="b" * 64,
            scope_sha256="c" * 64,
            worker=worker_identity,
            broker=broker_identity,
            expected_request_count=4,
            framework_thread_baseline=framework_baseline,
            controller_worker_thread_inventory=controller_worker_threads,
            controller_worker_file_descriptor_inventory=_native_fd_inventory(
                worker_identity, 5, 12
            ),
            controller_broker_thread_inventory=controller_broker_threads,
            controller_broker_file_descriptor_inventory=_native_fd_inventory(
                broker_identity, 3, 12
            ),
            ready_at_monotonic_ns=11,
            transcript_row_sha256=_sha(
                f"{attempt.attempt_id}-request-control-ready-row"
            ),
        )
        requests = []
        resource_rows = []
        previous_resource_row_sha256 = "0" * 64
        resource_row_sequence = 0
        startup_broker_receipt = _broker_lifecycle_receipt_fixture(
            logical_phase="startup",
            attempt_nonce_sha256="b" * 64,
            scope_sha256="c" * 64,
            request_id=f"{attempt.attempt_id}-startup",
            request_epoch=1,
            request_sequence=1,
            previous_receipt_sha256="0" * 64,
            worker=worker_identity,
            broker=broker_identity,
            observed_monotonic_ns=20,
            native_closure_sha256=fork_denial.native_closure_sha256,
        )
        previous_broker_receipt_sha256 = (
            startup_broker_receipt.receipt_sha256
        )
        for request in attempt.worker.requests:
            started = request.request_index * 1_000_000_000
            ended = started + request.latency_ns
            attempt_nonce = "b" * 64
            scope = "c" * 64
            binding = broker_request_binding_evidence(
                query_sha256="d" * 64,
                output_format="json",
                source_sha256=attempt.source.sha256,
                source_bytes=attempt.source.size_bytes,
                safe_filename_sha256=hashlib.sha256(
                    attempt.source.filename.encode("utf-8")
                ).hexdigest(),
                upload_content_type_sha256="f" * 64,
                binding_record_sha256=canonical_sha256(
                    {
                        "schema_id": "parser-broker-request-binding-v2",
                        "method": "POST",
                        "path": "/v1/parse",
                        "query_sha256": "d" * 64,
                        "output_format": "json",
                        "source_sha256": attempt.source.sha256,
                        "source_bytes": attempt.source.size_bytes,
                        "safe_filename_sha256": hashlib.sha256(
                            attempt.source.filename.encode("utf-8")
                        ).hexdigest(),
                        "upload_content_type_sha256": "f" * 64,
                    }
                ),
                matched_at_monotonic_ns=started + 1,
            )
            begin = BrokerQuiescenceReceipt(
                request_id=(
                    f"{attempt.attempt_id}-q{request.request_index:04d}"
                ),
                attempt_nonce_sha256=attempt_nonce,
                scope_sha256=scope,
                request_epoch=request.request_index + 1,
                request_sequence=request.request_index,
                edge="begin",
                observed_monotonic_ns=started - 2,
                worker=worker_identity,
                broker=broker_identity,
                broker_thread_count=1,
                broker_thread_inventory_sha256="8" * 64,
                broker_thread_observed_at_monotonic_ns=started - 3,
                ledger_head_sha256=previous_broker_receipt_sha256,
                completed_spawn_count=0,
                worker_group_member_pids=(worker_identity.pid,),
                broker_group_member_pids=(broker_identity.pid,),
                request_root_inventory=broker_scratch_inventory(
                    root_device=1,
                    root_inode=3,
                    root_uid=501,
                    scan_started_monotonic_ns=started - 4,
                    scan_completed_monotonic_ns=started - 3,
                ),
            )
            end = begin.model_copy(
                update={
                    "edge": "end",
                    "observed_monotonic_ns": ended - 2,
                    "broker_thread_observed_at_monotonic_ns": ended - 3,
                    "ledger_head_sha256": previous_broker_receipt_sha256,
                    "request_root_inventory": broker_scratch_inventory(
                        root_device=1,
                        root_inode=3,
                        root_uid=501,
                        scan_started_monotonic_ns=ended - 4,
                        scan_completed_monotonic_ns=ended - 3,
                    ),
                }
            )
            worker_before = NativeSelfCpuCounter(
                identity=worker_identity,
                observed_monotonic_ns=started,
                user_cpu_ns=100,
                system_cpu_ns=200,
            )
            worker_after = worker_before.model_copy(
                update={
                    "observed_monotonic_ns": ended,
                    "user_cpu_ns": 110,
                    "system_cpu_ns": 220,
                }
            )
            broker_before = NativeSelfCpuCounter(
                identity=broker_identity,
                observed_monotonic_ns=started - 1,
                user_cpu_ns=300,
                system_cpu_ns=400,
            )
            broker_after = broker_before.model_copy(
                update={
                    "observed_monotonic_ns": ended - 1,
                    "user_cpu_ns": 330,
                    "system_cpu_ns": 440,
                }
            )
            begin_post_scratch = broker_scratch_inventory(
                root_device=1,
                root_inode=3,
                root_uid=501,
                scan_started_monotonic_ns=started,
                scan_completed_monotonic_ns=started,
            )
            end_post_scratch = broker_scratch_inventory(
                root_device=1,
                root_inode=3,
                root_uid=501,
                scan_started_monotonic_ns=ended,
                scan_completed_monotonic_ns=ended,
            )
            attempt_deadline = ended + 10_000_000
            begin_external = external_cpu_stable_edge_record(
                attempt_id=attempt.attempt_id,
                attempt_nonce_sha256=attempt_nonce,
                scope_sha256=scope,
                request_id=begin.request_id,
                request_epoch=request.request_index + 1,
                request_sequence=request.request_index,
                request_deadline_monotonic_ns=attempt_deadline,
                edge="begin",
                broker_sample=NativeProcessResourceSample(
                    cpu=broker_before,
                    rss_bytes=1_000,
                    thread_count=1,
                    native_thread_ids=(2_001,),
                    file_descriptor_count=3,
                    file_descriptor_inventory=_native_fd_inventory(
                        broker_identity,
                        3,
                        broker_before.observed_monotonic_ns,
                    ),
                ),
                worker_sample=NativeProcessResourceSample(
                    cpu=worker_before,
                    rss_bytes=2_000,
                    thread_count=4,
                    native_thread_ids=(1_001, 1_002, 1_003, 1_004),
                    file_descriptor_count=5,
                    file_descriptor_inventory=_native_fd_inventory(
                        worker_identity,
                        5,
                        worker_before.observed_monotonic_ns,
                    ),
                ),
                post_sample_scratch_inventory=begin_post_scratch,
            )
            end_external = external_cpu_stable_edge_record(
                attempt_id=attempt.attempt_id,
                attempt_nonce_sha256=attempt_nonce,
                scope_sha256=scope,
                request_id=begin.request_id,
                request_epoch=request.request_index + 1,
                request_sequence=request.request_index,
                request_deadline_monotonic_ns=attempt_deadline,
                edge="end",
                broker_sample=NativeProcessResourceSample(
                    cpu=broker_after,
                    rss_bytes=1_100,
                    thread_count=1,
                    native_thread_ids=(2_001,),
                    file_descriptor_count=3,
                    file_descriptor_inventory=_native_fd_inventory(
                        broker_identity,
                        3,
                        broker_after.observed_monotonic_ns,
                    ),
                ),
                worker_sample=NativeProcessResourceSample(
                    cpu=worker_after,
                    rss_bytes=2_100,
                    thread_count=4,
                    native_thread_ids=(1_001, 1_002, 1_003, 1_004),
                    file_descriptor_count=5,
                    file_descriptor_inventory=_native_fd_inventory(
                        worker_identity,
                        5,
                        worker_after.observed_monotonic_ns,
                    ),
                ),
                post_sample_scratch_inventory=end_post_scratch,
            )
            exact_cpu = ExactBrokerRequestCpuEvidence(
                attempt_id=attempt.attempt_id,
                request_id=begin.request_id,
                attempt_nonce_sha256=attempt_nonce,
                scope_sha256=scope,
                request_epoch=request.request_index + 1,
                request_sequence=request.request_index,
                request_deadline_monotonic_ns=attempt_deadline,
                arm_capability_sha256="2" * 64,
                arm_issued_at_monotonic_ns=started - 3,
                arm_consumed_at_monotonic_ns=started - 2,
                binding_sha256=binding.binding_record_sha256,
                request_binding=binding,
                asgi_response_witness=(
                    response_witness := asgi_response_witness(
                        ordered_headers=(
                            {
                                "name_hex": b"content-type".hex(),
                                "value_hex": b"application/json".hex(),
                            },
                        ),
                        response_start_send_completed_monotonic_ns=(
                            started + 1
                        ),
                        response_body_message_keys=("body", "type"),
                        body_sha256=request.output.sha256,
                        body_bytes=request.output.size_bytes,
                        response_body_send_completed_monotonic_ns=(
                            started + 2
                        ),
                        inner_asgi_returned_monotonic_ns=ended - 3,
                    )
                ),
                asgi_response_witness_sha256=(
                    response_witness.record_sha256
                ),
                thread_transfer_record_sha256s=("3" * 64, "4" * 64),
                begin=begin,
                end=end,
                worker_before=worker_before,
                worker_after=worker_after,
                broker_before=broker_before,
                broker_after=broker_after,
                begin_post_sample_scratch_inventory=begin_post_scratch,
                end_post_sample_scratch_inventory=end_post_scratch,
                begin_external_sample=begin_external,
                end_external_sample=end_external,
                begin_external_sample_row_sha256=_sha(
                    f"{attempt.attempt_id}-{request.request_index}-begin-sample"
                ),
                end_external_sample_row_sha256=_sha(
                    f"{attempt.attempt_id}-{request.request_index}-end-sample"
                ),
                request_control_arm_record_sha256=_sha(
                    f"{attempt.attempt_id}-{request.request_index}-arm"
                ),
                request_control_begin_blocked_record_sha256=_sha(
                    f"{attempt.attempt_id}-{request.request_index}-begin-blocked"
                ),
                request_control_begin_release_record_sha256=_sha(
                    f"{attempt.attempt_id}-{request.request_index}-begin-release"
                ),
                request_control_end_blocked_record_sha256=_sha(
                    f"{attempt.attempt_id}-{request.request_index}-end-blocked"
                ),
                request_control_receipt_release_record_sha256=_sha(
                    f"{attempt.attempt_id}-{request.request_index}-receipt-release"
                ),
                request_control_result_record_sha256=_sha(
                    f"{attempt.attempt_id}-{request.request_index}-result"
                ),
                request_control_result_ack_record_sha256=_sha(
                    f"{attempt.attempt_id}-{request.request_index}-result-ack"
                ),
                request_control_transcript_row_sha256s=tuple(
                    _sha(
                        f"{attempt.attempt_id}-{request.request_index}-transcript-{index}"
                    )
                    for index in range(1, 8)
                ),
                begin_release_monotonic_ns=started,
                receipt_release_monotonic_ns=ended + 1,
                broker_request_receipt_sha256=_sha(
                    f"{attempt.attempt_id}-{request.request_index}-broker-receipt"
                ),
                worker_user_cpu_delta_ns=10,
                worker_system_cpu_delta_ns=20,
                broker_user_cpu_delta_ns=30,
                broker_system_cpu_delta_ns=40,
                tesseract_user_cpu_delta_ns=0,
                tesseract_system_cpu_delta_ns=0,
                total_cpu_delta_ns=100,
                sampled_process_identities=(
                    SampledProcessIdentity(
                        role="parser_worker",
                        pid=worker_identity.pid,
                        start_abstime=worker_identity.start_abstime,
                        parent_pid=worker_identity.parent_pid,
                        process_group_id=worker_identity.process_group_id,
                        session_id=worker_identity.session_id,
                    ),
                    SampledProcessIdentity(
                        role="tesseract_broker",
                        pid=broker_identity.pid,
                        start_abstime=broker_identity.start_abstime,
                        parent_pid=broker_identity.parent_pid,
                        process_group_id=broker_identity.process_group_id,
                        session_id=broker_identity.session_id,
                    ),
                ),
            )
            previous_broker_receipt_sha256 = (
                exact_cpu.broker_request_receipt_sha256
            )
            start_processes = (
                ControllerResourceProcessSample(
                    role="parser_worker",
                    pid=worker_identity.pid,
                    start_abstime=worker_identity.start_abstime,
                    ppid=worker_identity.parent_pid,
                    pgid=worker_identity.process_group_id,
                    sid=worker_identity.session_id,
                    sample_started_monotonic_ns=started - 2,
                    observed_monotonic_ns=started,
                    sample_completed_monotonic_ns=started,
                    user_cpu_ns=worker_before.user_cpu_ns,
                    system_cpu_ns=worker_before.system_cpu_ns,
                    rss_bytes=2_000,
                    thread_count=4,
                    native_thread_ids=(1_001, 1_002, 1_003, 1_004),
                    file_descriptor_count=5,
                ),
                ControllerResourceProcessSample(
                    role="tesseract_broker",
                    pid=broker_identity.pid,
                    start_abstime=broker_identity.start_abstime,
                    ppid=broker_identity.parent_pid,
                    pgid=broker_identity.process_group_id,
                    sid=broker_identity.session_id,
                    sample_started_monotonic_ns=started - 2,
                    observed_monotonic_ns=started - 1,
                    sample_completed_monotonic_ns=started,
                    user_cpu_ns=broker_before.user_cpu_ns,
                    system_cpu_ns=broker_before.system_cpu_ns,
                    rss_bytes=1_000,
                    thread_count=1,
                    native_thread_ids=(2_001,),
                    file_descriptor_count=3,
                ),
            )
            end_processes = (
                start_processes[0].model_copy(
                    update={
                        "sample_started_monotonic_ns": ended - 2,
                        "observed_monotonic_ns": ended,
                        "sample_completed_monotonic_ns": ended,
                        "user_cpu_ns": worker_after.user_cpu_ns,
                        "system_cpu_ns": worker_after.system_cpu_ns,
                        "rss_bytes": 2_100,
                    }
                ),
                start_processes[1].model_copy(
                    update={
                        "sample_started_monotonic_ns": ended - 2,
                        "observed_monotonic_ns": ended - 1,
                        "sample_completed_monotonic_ns": ended,
                        "user_cpu_ns": broker_after.user_cpu_ns,
                        "system_cpu_ns": broker_after.system_cpu_ns,
                        "rss_bytes": 1_100,
                    }
                ),
            )
            request_rows = []
            for label, observed, processes in (
                ("begin", started, start_processes),
                ("end", ended, end_processes),
            ):
                aggregate = ControllerResourceAggregate(
                    process_count=len(processes),
                    rss_bytes=sum(item.rss_bytes for item in processes),
                    thread_count=sum(item.thread_count for item in processes),
                    file_descriptor_count=sum(
                        item.file_descriptor_count for item in processes
                    ),
                )
                record = ControllerRequestResourceSample(
                    attempt_id=attempt.attempt_id,
                    request_id=begin.request_id,
                    request_epoch=request.request_index + 1,
                    request_sequence=request.request_index,
                    observed_monotonic_ns=observed,
                    sweep_started_monotonic_ns=min(
                        item.sample_started_monotonic_ns for item in processes
                    ),
                    sweep_completed_monotonic_ns=max(
                        item.sample_completed_monotonic_ns for item in processes
                    ),
                    sweep_span_ns=(
                        max(
                            item.sample_completed_monotonic_ns
                            for item in processes
                        )
                        - min(
                            item.sample_started_monotonic_ns
                            for item in processes
                        )
                    ),
                    maximum_sweep_span_ns=PEAK_SAMPLE_EDGE_TOLERANCE_NS,
                    boundary_membership=(
                        "boundary_begin" if label == "begin" else "boundary_end"
                    ),
                    processes=processes,
                    aggregate=aggregate,
                    child_watch_prefix=_empty_child_watch_prefix_fixture(),
                )
                resource_row_sequence += 1
                row = controller_resource_sample_log_row(
                    row_sequence=resource_row_sequence,
                    previous_row_sha256=previous_resource_row_sha256,
                    record=record,
                    retained_monotonic_ns=observed + 1,
                )
                previous_resource_row_sha256 = row.row_sha256
                request_rows.append(row)
                resource_rows.append(row)
            boundary = RequestResourceBoundary(
                boundary_started_monotonic_ns=started,
                boundary_ended_monotonic_ns=ended,
                self_user_cpu_delta_ns=0,
                self_system_cpu_delta_ns=0,
                reaped_child_user_cpu_delta_ns=0,
                reaped_child_system_cpu_delta_ns=0,
                live_descendant_user_cpu_delta_ns=0,
                live_descendant_system_cpu_delta_ns=0,
                live_descendant_process_count=0,
                total_cpu_delta_ns=100,
                host_logical_cpu_count=2,
                wall_cpu_capacity_ns=request.latency_ns * 2,
                descendant_peak_process_count=2,
                descendant_peak_rss_bytes=3_200,
                process_tree_peak_thread_count=5,
                process_tree_peak_file_descriptor_count=8,
                exact_broker_cpu=exact_cpu,
                controller_resource_sample_rows=tuple(request_rows),
                cpu_accounting_basis=(
                    "fork-denied-worker-broker-self-plus-exact-wait4-v2"
                ),
                sampled_concurrently=True,
                descendant_sample_count=2,
                    descendant_first_sample_monotonic_ns=started - 2,
                descendant_last_sample_monotonic_ns=(
                    started + request.latency_ns
                ),
                    descendant_maximum_gap_ns=request.latency_ns - 2,
                descendant_target_interval_ns=10_000_000,
                descendant_edge_tolerance_ns=50_000_000,
                request_boundary_covered=True,
            )
            requests.append(request.model_copy(update={"resource_boundary": boundary}))
        (
            readiness,
            retained_requests,
            terminal_request_control_transcript,
            previous_broker_receipt_sha256,
        ) = _terminal_request_control_fixture(
            attempt_id=attempt.attempt_id,
            mode=attempt.mode,
            request_sources=tuple(attempt.source for _ in requests),
            readiness=readiness,
            requests=tuple(requests),
            startup_broker_receipt=startup_broker_receipt,
        )
        requests = list(retained_requests)
        shutdown_broker_receipt = _broker_lifecycle_receipt_fixture(
            logical_phase="shutdown",
            attempt_nonce_sha256="b" * 64,
            scope_sha256="c" * 64,
            request_id=f"{attempt.attempt_id}-shutdown",
            request_epoch=len(requests) + 2,
            request_sequence=len(requests),
            previous_receipt_sha256=previous_broker_receipt_sha256,
            worker=worker_identity,
            broker=broker_identity,
            observed_monotonic_ns=(len(requests) + 1) * 1_000_000_000,
            native_closure_sha256=fork_denial.native_closure_sha256,
        )
        resource_log_bytes = b"".join(
            canonical_model_bytes(row) for row in resource_rows
        )
        worker = attempt.worker.model_copy(
            update={
                "requests": tuple(requests),
                "production_asgi_lifespan_exercised": True,
                "network_isolation_validated": True,
                "concurrent_descendant_sampling_validated": True,
                "runtime_before_requests_sha256": "a" * 64,
                "runtime_after_requests_sha256": "b" * 64,
                "runtime_after_shutdown_sha256": "c" * 64,
                "runtime_artifact_before_requests": artifact_boundary,
                "runtime_artifact_after_shutdown": artifact_boundary,
                "fork_denial_evidence": fork_denial,
                "request_control_readiness": readiness,
                "terminal_request_control_transcript": (
                    terminal_request_control_transcript
                ),
                "immutable_runtime_input_custody": (
                    _immutable_runtime_input_custody_fixture(
                        attempt_id=attempt.attempt_id,
                        artifact=artifact_boundary,
                    )
                ),
                "startup_broker_receipt": startup_broker_receipt,
                "shutdown_broker_receipt": shutdown_broker_receipt,
                "controller_resource_sample_log_sha256": hashlib.sha256(
                    resource_log_bytes
                ).hexdigest(),
                "controller_resource_sample_log_row_count": len(resource_rows),
                "controller_resource_sample_log_size_bytes": len(
                    resource_log_bytes
                ),
                "terminal_child_watch_log": _terminal_child_watch_fixture(),
            }
        )
        cleanup = attempt.cleanup.model_copy(
            update={
                "broker_process_group_count": 1,
                "controller_watchdog_process_group_count": 1,
                "owned_process_group_count": 3,
            }
        )
        changed_attempts.append(
            attempt.model_copy(update={"worker": worker, "cleanup": cleanup})
        )
    return LocalPrewarmEvidenceBundle.model_validate(
        {
            **bundle.model_dump(mode="python"),
            "attempts": tuple(changed_attempts),
        }
    )


def test_json_normalization_excludes_only_processing_duration() -> None:
    first = output_identity_from_json(_parse_result_bytes(duration_ms=1))
    second = output_identity_from_json(_parse_result_bytes(duration_ms=999))

    assert first.sha256 != second.sha256
    assert first.normalized_sha256 == second.normalized_sha256
    assert first.semantic_sha256 == second.semantic_sha256
    assert first.api_contract_sha256 == second.api_contract_sha256
    assert first.provenance_sha256 == second.provenance_sha256
    assert first.concerns_sha256 == second.concerns_sha256
    assert first.deterministic_ids_sha256 == second.deterministic_ids_sha256

    changed = output_identity_from_json(
        _parse_result_bytes(duration_ms=1, engine="changed-local")
    )
    assert changed.normalized_sha256 != first.normalized_sha256
    assert changed.provenance_sha256 != first.provenance_sha256


def test_terminal_transcript_rejects_rehashed_raw_witness_mismatch(
    production_flagged_control: LocalPrewarmEvidenceBundle,
) -> None:
    attempt = production_flagged_control.attempts[0]
    readiness = attempt.worker.request_control_readiness
    terminal = attempt.worker.terminal_request_control_transcript
    assert readiness is not None and terminal is not None
    changed_raw = _terminal_transcript_with_rehashed_result_witness_mismatch(
        terminal.raw_bytes()
    )
    changed_terminal = terminal_request_control_transcript_evidence(
        changed_raw,
        file_device=terminal.file_device,
        file_inode=terminal.file_inode,
        file_uid=terminal.file_uid,
    )
    replay = contracts._replay_request_control_transcript_jsonl(changed_raw)
    replayed_requests = replay["request_records"]
    assert isinstance(replayed_requests, tuple)
    changed_exact_requests: list[ExactBrokerRequestCpuEvidence] = []
    request_sources: list[SourceIdentity] = []
    request_outputs: list[OutputIdentity] = []
    for observation, replayed in zip(
        attempt.worker.requests, replayed_requests, strict=True
    ):
        assert (
            observation.resource_boundary is not None
            and observation.resource_boundary.exact_broker_cpu is not None
            and observation.output is not None
            and isinstance(replayed, dict)
        )
        exact = observation.resource_boundary.exact_broker_cpu
        record_sha256s = replayed["record_sha256s"]
        transcript_row_sha256s = replayed["transcript_row_sha256s"]
        assert isinstance(record_sha256s, tuple)
        assert isinstance(transcript_row_sha256s, tuple)
        changed_exact_requests.append(
            ExactBrokerRequestCpuEvidence.model_validate(
                {
                    **exact.model_dump(mode="python"),
                    "request_control_arm_record_sha256": record_sha256s[0],
                    "request_control_begin_blocked_record_sha256": (
                        record_sha256s[1]
                    ),
                    "request_control_begin_release_record_sha256": (
                        record_sha256s[2]
                    ),
                    "request_control_end_blocked_record_sha256": (
                        record_sha256s[3]
                    ),
                    "request_control_receipt_release_record_sha256": (
                        record_sha256s[4]
                    ),
                    "request_control_result_record_sha256": record_sha256s[5],
                    "request_control_result_ack_record_sha256": (
                        record_sha256s[6]
                    ),
                    "request_control_transcript_row_sha256s": (
                        transcript_row_sha256s
                    ),
                }
            )
        )
        request_sources.append(attempt.source)
        request_outputs.append(observation.output)

    with pytest.raises(
        ValueError, match="terminal request-control request custody"
    ):
        contracts.require_terminal_request_control_transcript(
            changed_terminal,
            readiness,
            tuple(changed_exact_requests),
            request_sources=tuple(request_sources),
            request_outputs=tuple(request_outputs),
        )


def test_output_contract_rejects_more_than_64_mib() -> None:
    with pytest.raises(ValidationError):
        OutputIdentity(
            sha256="a" * 64,
            normalized_sha256="a" * 64,
            semantic_sha256="a" * 64,
            size_bytes=67_108_865,
            media_type="application/json",
            validation="synthetic_contract_control",
            normalization_policy="json_exclude_processing_duration_ms_v1",
        )


def test_request_cpu_delta_detects_cumulative_counter_regression() -> None:
    root = ProcessCpuCounter(
        pid=100,
        create_time_ns=1,
        ownership="worker",
        user_cpu_ns=0,
        system_cpu_ns=0,
    )
    before = ProcessCpuSnapshot(
        observed_monotonic_ns=1,
        rusage_self_user_cpu_ns=100,
        rusage_self_system_cpu_ns=200,
        rusage_reaped_child_user_cpu_ns=300,
        rusage_reaped_child_system_cpu_ns=400,
        members=(root,),
    )
    after = ProcessCpuSnapshot(
        observed_monotonic_ns=2,
        rusage_self_user_cpu_ns=110,
        rusage_self_system_cpu_ns=190,
        rusage_reaped_child_user_cpu_ns=330,
        rusage_reaped_child_system_cpu_ns=440,
        members=(root,),
    )
    deltas, contaminated = _request_cpu_delta(
        before, after
    )
    assert deltas == (10, 0, 30, 40, 0, 0)
    assert contaminated is True


def test_persistent_descendant_cpu_is_nonzero_and_cannot_be_omitted() -> None:
    root_before = ProcessCpuCounter(
        pid=100,
        create_time_ns=1,
        ownership="worker",
        user_cpu_ns=10,
        system_cpu_ns=20,
    )
    child_before = ProcessCpuCounter(
        pid=101,
        create_time_ns=2,
        ownership="descendant",
        user_cpu_ns=30,
        system_cpu_ns=40,
    )
    root_after = root_before.model_copy(
        update={"user_cpu_ns": 15, "system_cpu_ns": 26}
    )
    child_after = child_before.model_copy(
        update={"user_cpu_ns": 60, "system_cpu_ns": 80}
    )
    before = ProcessCpuSnapshot(
        observed_monotonic_ns=10,
        rusage_self_user_cpu_ns=10,
        rusage_self_system_cpu_ns=20,
        rusage_reaped_child_user_cpu_ns=0,
        rusage_reaped_child_system_cpu_ns=0,
        members=(root_before, child_before),
    )
    after = ProcessCpuSnapshot(
        observed_monotonic_ns=90,
        rusage_self_user_cpu_ns=15,
        rusage_self_system_cpu_ns=26,
        rusage_reaped_child_user_cpu_ns=0,
        rusage_reaped_child_system_cpu_ns=0,
        members=(root_after, child_after),
    )
    deltas, contaminated = _request_cpu_delta(before, after)
    assert deltas == (5, 6, 0, 0, 30, 40)
    assert contaminated is False
    fields = {
        "boundary_started_monotonic_ns": 1,
        "boundary_ended_monotonic_ns": 101,
        "self_user_cpu_delta_ns": 5,
        "self_system_cpu_delta_ns": 6,
        "reaped_child_user_cpu_delta_ns": 0,
        "reaped_child_system_cpu_delta_ns": 0,
        "live_descendant_user_cpu_delta_ns": 30,
        "live_descendant_system_cpu_delta_ns": 40,
        "live_descendant_process_count": 1,
        "total_cpu_delta_ns": 81,
        "host_logical_cpu_count": 1,
        "wall_cpu_capacity_ns": 100,
        "descendant_peak_process_count": 2,
        "descendant_peak_rss_bytes": 1,
        "process_tree_peak_thread_count": 1,
        "process_tree_peak_file_descriptor_count": 0,
        "cpu_before": before,
        "cpu_after": after,
        "sampled_concurrently": True,
        "descendant_sample_count": 2,
        "descendant_first_sample_monotonic_ns": 1,
        "descendant_last_sample_monotonic_ns": 101,
        "descendant_maximum_gap_ns": 100,
        "descendant_target_interval_ns": 100,
        "descendant_edge_tolerance_ns": 100,
        "request_boundary_covered": True,
    }
    boundary = RequestResourceBoundary(**fields)
    assert boundary.live_descendant_user_cpu_delta_ns == 30
    with pytest.raises(ValidationError, match="live-descendant CPU delta"):
        RequestResourceBoundary.model_validate(
            {
                **fields,
                "live_descendant_user_cpu_delta_ns": 0,
                "total_cpu_delta_ns": 51,
            }
        )
    with pytest.raises(ValidationError, match="request CPU total"):
        RequestResourceBoundary.model_validate(
            {**fields, "total_cpu_delta_ns": 151}
        )


@pytest.mark.parametrize(
    ("field", "delta"),
    (
        ("thread_count", 1),
        ("thread_count", -1),
        ("file_descriptor_count", 1),
        ("file_descriptor_count", -1),
    ),
)
def test_controller_restoration_requires_exact_equality(
    field: str, delta: int
) -> None:
    identity = ControllerProcessIdentity(
        pid=99,
        create_time_ns=1,
        process_group_id=99,
        session_id=99,
    )
    before = _controller_resource_fixture(
        identity=identity,
        observed_monotonic_ns=1,
        thread_ids=(101, 102),
        file_descriptor_count=2,
    )
    if field == "thread_count":
        replacement_count = before.thread_count + delta
        replacement_ids = tuple(range(201, 201 + replacement_count))
        after = _controller_resource_fixture(
            identity=identity,
            observed_monotonic_ns=2,
            thread_ids=replacement_ids,
            file_descriptor_count=before.file_descriptor_count,
        )
    else:
        after = _controller_resource_fixture(
            identity=identity,
            observed_monotonic_ns=2,
            thread_ids=before.thread_inventory.thread_ids,
            file_descriptor_count=before.file_descriptor_count + delta,
        )
    with pytest.raises(ValidationError, match="restoration claim differs"):
        ControllerResourceBoundary(
            before=before,
            after=after,
            threads_returned_to_baseline=True,
            file_descriptors_returned_to_baseline=True,
        )


def test_controller_restoration_rejects_same_count_identity_substitution() -> None:
    identity = ControllerProcessIdentity(
        pid=99,
        create_time_ns=1,
        process_group_id=99,
        session_id=99,
    )
    before = _controller_resource_fixture(
        identity=identity,
        observed_monotonic_ns=1,
        thread_ids=(101, 102),
        file_descriptor_count=2,
    )
    replaced_thread = _controller_resource_fixture(
        identity=identity,
        observed_monotonic_ns=2,
        thread_ids=(101, 103),
        file_descriptor_count=2,
    )
    with pytest.raises(ValidationError, match="thread restoration claim differs"):
        ControllerResourceBoundary(
            before=before,
            after=replaced_thread,
            threads_returned_to_baseline=True,
            file_descriptors_returned_to_baseline=True,
        )

    original_inventory = before.file_descriptor_inventory
    original_descriptor = original_inventory.descriptors[0]
    assert original_descriptor.vnode is not None
    replacement_descriptor = native_file_descriptor_identity(
        **original_descriptor.model_dump(
            mode="python", exclude={"record_sha256", "vnode"}
        ),
        vnode=original_descriptor.vnode.model_copy(
            update={"resolved_path_sha256": _sha("controller-fd-replacement")}
        ),
    )
    replacement_inventory = native_file_descriptor_inventory(
        process=original_inventory.process,
        first_scan_started_monotonic_ns=2,
        first_scan_completed_monotonic_ns=2,
        second_scan_started_monotonic_ns=2,
        second_scan_completed_monotonic_ns=2,
        descriptors=(
            replacement_descriptor,
            *original_inventory.descriptors[1:],
        ),
    )
    replaced_fd = before.model_copy(
        update={
            "observed_monotonic_ns": 2,
            "file_descriptor_inventory": replacement_inventory,
            "file_descriptor_membership_sha256": (
                production_runner._native_fd_membership_sha256(
                    replacement_inventory
                )
            ),
        }
    )
    with pytest.raises(ValidationError, match="FD restoration claim differs"):
        ControllerResourceBoundary(
            before=before,
            after=replaced_fd,
            threads_returned_to_baseline=True,
            file_descriptors_returned_to_baseline=True,
        )


def test_peak_sampler_retains_independent_thread_and_fd_maxima() -> None:
    sampler = _PeakSampler()
    sampler._samples = [
        ResourceSample(
            phase=ResourcePhase.REQUEST_PEAK,
            observed_monotonic_ns=1,
            rss_bytes=300,
            user_cpu_ns=0,
            system_cpu_ns=0,
            process_count=1,
            thread_count=2,
            file_descriptor_count=3,
        ),
        ResourceSample(
            phase=ResourcePhase.REQUEST_PEAK,
            observed_monotonic_ns=2,
            rss_bytes=200,
            user_cpu_ns=0,
            system_cpu_ns=0,
            process_count=2,
            thread_count=9,
            file_descriptor_count=4,
        ),
        ResourceSample(
            phase=ResourcePhase.REQUEST_PEAK,
            observed_monotonic_ns=3,
            rss_bytes=100,
            user_cpu_ns=0,
            system_cpu_ns=0,
            process_count=1,
            thread_count=3,
            file_descriptor_count=11,
        ),
    ]
    assert sampler.peak().rss_bytes == 300
    assert sampler.peak_thread_count() == 9
    assert sampler.peak_file_descriptor_count() == 11


@pytest.mark.parametrize("stream_fd", (1, 2))
def test_bounded_capture_kills_on_stdout_or_stderr_flood(stream_fd: int) -> None:
    command = (
        sys.executable,
        "-c",
        (
            "import os;"
            f"os.write({stream_fd},b'x'*({MAXIMUM_WORKER_COMBINED_BYTES}+65536))"
        ),
    )
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    capture = _BoundedPipeCapture(process)
    deadline = time.monotonic() + 10
    killed = False
    while not capture.complete and time.monotonic() < deadline:
        if capture.pump(0.05) and not killed:
            os.killpg(process.pid, 9)
            killed = True
    process.wait(timeout=5)
    while not capture.complete and time.monotonic() < deadline:
        capture.pump(0.01)
    assert killed is True
    assert capture.overflow is True
    assert capture.retained_size_bytes == MAXIMUM_WORKER_COMBINED_BYTES
    assert sum(capture.counts.values()) == MAXIMUM_WORKER_COMBINED_BYTES
    capture.close(forced=not capture.complete)


def test_phase_deadline_log_rejects_same_inode_prefix_mutation(tmp_path: Path) -> None:
    root = tmp_path / "protocol"
    root.mkdir(mode=0o700)
    control = root / "phase.jsonl"
    ack = root / "ack.jsonl"
    control.touch(mode=0o600)
    ack.touch(mode=0o600)
    whole = time.monotonic_ns() + 10_000_000_000
    append_phase_deadline(
        root=root,
        path=control,
        attempt_id="phase-test",
        phase="startup",
        timeout_ns=1_000_000_000,
        whole_deadline_monotonic_ns=whole,
    )
    _records, snapshot = read_phase_deadlines(
        root=root,
        path=control,
        attempt_id="phase-test",
        whole_deadline_monotonic_ns=whole,
    )
    raw = control.read_bytes()
    control.write_bytes(raw.replace(b'"phase":"startup"', b'"phase":"request"'))
    with pytest.raises(ValueError):
        read_phase_deadlines(
            root=root,
            path=control,
            attempt_id="phase-test",
            whole_deadline_monotonic_ns=whole,
            previous=snapshot,
        )
    assert read_phase_acks(
        root=root,
        path=ack,
        attempt_id="phase-test",
    )[0] == ()


def test_phase_chain_grammar_and_ack_deadline_are_fail_closed(
    tmp_path: Path,
) -> None:
    root = tmp_path / "phase-grammar"
    root.mkdir(mode=0o700)
    control = root / "phase.jsonl"
    ack = root / "ack.jsonl"
    control.touch(mode=0o600)
    ack.touch(mode=0o600)
    whole = 10_000
    startup = append_phase_deadline(
        root=root,
        path=control,
        attempt_id="phase-grammar",
        phase="startup",
        timeout_ns=1_000,
        whole_deadline_monotonic_ns=whole,
        clock=lambda: 100,
    )
    with pytest.raises(TimeoutError, match="before ACK"):
        append_phase_ack(
            root=root,
            path=ack,
            attempt_id="phase-grammar",
            phase_record=startup,
            clock=lambda: startup.deadline_monotonic_ns,
        )
    assert ack.read_bytes() == b""
    append_phase_deadline(
        root=root,
        path=control,
        attempt_id="phase-grammar",
        phase="shutdown",
        timeout_ns=1_000,
        whole_deadline_monotonic_ns=whole,
        clock=lambda: 200,
    )
    append_phase_deadline(
        root=root,
        path=control,
        attempt_id="phase-grammar",
        phase="request",
        timeout_ns=1_000,
        whole_deadline_monotonic_ns=whole,
        clock=lambda: 300,
    )
    with pytest.raises(ValueError, match="grammar"):
        read_phase_deadlines(
            root=root,
            path=control,
            attempt_id="phase-grammar",
            whole_deadline_monotonic_ns=whole,
        )


def test_prior_phase_expiry_is_assessed_before_advance_or_exit() -> None:
    current = PhaseDeadlineRecord(
        attempt_id="ordering",
        sequence=2,
        phase="request",
        issued_monotonic_ns=100,
        deadline_monotonic_ns=200,
        previous_record_sha256="1" * 64,
        record_sha256="2" * 64,
    )
    timely_advance = PhaseDeadlineRecord(
        attempt_id="ordering",
        sequence=3,
        phase="shutdown",
        issued_monotonic_ns=199,
        deadline_monotonic_ns=300,
        previous_record_sha256=current.record_sha256,
        record_sha256="3" * 64,
    )
    late_advance = PhaseDeadlineRecord(
        attempt_id="ordering",
        sequence=3,
        phase="shutdown",
        issued_monotonic_ns=200,
        deadline_monotonic_ns=300,
        previous_record_sha256=current.record_sha256,
        record_sha256="4" * 64,
    )
    assert not _acknowledged_phase_expired_before_advance(
        current,
        observed_monotonic_ns=199,
        proposed_phase_record=timely_advance,
    )
    assert _acknowledged_phase_expired_before_advance(
        current,
        observed_monotonic_ns=199,
        proposed_phase_record=late_advance,
    )
    assert _acknowledged_phase_expired_before_advance(
        current,
        observed_monotonic_ns=200,
    )


@pytest.mark.parametrize("timed_phase", ("startup", "request"))
def test_external_watchdog_enforces_native_gil_phase_deadline(
    tmp_path: Path, timed_phase: str
) -> None:
    root = tmp_path / timed_phase
    root.mkdir(mode=0o700)
    heartbeat = root / "heartbeat"
    ready = root / "ready"
    control = root / "phase.jsonl"
    ack = root / "ack.jsonl"
    terminal_path = root / "terminal.json"
    for path in (heartbeat, control, ack):
        path.touch(mode=0o600)
    controller_process = psutil.Process(os.getpid())
    controller_create_time_ns = int(
        controller_process.create_time() * 1_000_000_000
    )
    worker = subprocess.Popen(
        (
            sys.executable,
            "-c",
            "import ctypes; ctypes.PyDLL(None).sleep(60)",
        ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    watchdog: subprocess.Popen[bytes] | None = None
    terminal_fd: int | None = None
    try:
        worker_process = psutil.Process(worker.pid)
        worker_create_time_ns = int(
            worker_process.create_time() * 1_000_000_000
        )
        whole_deadline = time.monotonic_ns() + 5_000_000_000
        first_timeout = (
            600_000_000 if timed_phase == "startup" else 4_000_000_000
        )
        append_phase_deadline(
            root=root,
            path=control,
            attempt_id=f"native-{timed_phase}",
            phase="startup",
            timeout_ns=first_timeout,
            whole_deadline_monotonic_ns=whole_deadline,
        )
        config = PrewarmWatchdogConfig(
            attempt_id=f"native-{timed_phase}",
            controller_pid=os.getpid(),
            controller_start_abstime=raw_process_start_abstime(os.getpid()),
            controller_create_time_ns=controller_create_time_ns,
            controller_pgid=os.getpgrp(),
            controller_sid=os.getsid(0),
            worker_pid=worker.pid,
            worker_create_time_ns=worker_create_time_ns,
            worker_pgid=worker.pid,
            worker_sid=worker.pid,
            heartbeat_root=root,
            heartbeat_path=heartbeat,
            ready_path=ready,
            phase_control_path=control,
            phase_ack_path=ack,
            absolute_deadline_monotonic_ns=whole_deadline,
        )
        terminal_fd = os.open(
            terminal_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        watchdog = subprocess.Popen(
            build_prewarm_watchdog_command(
                python_executable=sys.executable,
                config=config,
            ),
            stdin=subprocess.DEVNULL,
            stdout=terminal_fd,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=sanitized_watchdog_environment(),
        )
        os.close(terminal_fd)
        terminal_fd = None
        ready_deadline = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < ready_deadline:
            os.utime(heartbeat, None, follow_symlinks=False)
            time.sleep(0.02)
        assert ready.read_bytes() == b"READY\n"
        ack_deadline = time.monotonic() + 2
        while time.monotonic() < ack_deadline:
            acks, _snapshot = read_phase_acks(
                root=root,
                path=ack,
                attempt_id=f"native-{timed_phase}",
            )
            if acks:
                break
            time.sleep(0.01)
        assert len(acks) == 1
        if timed_phase == "request":
            append_phase_deadline(
                root=root,
                path=control,
                attempt_id="native-request",
                phase="request",
                timeout_ns=600_000_000,
                whole_deadline_monotonic_ns=whole_deadline,
            )
        watchdog_deadline = time.monotonic() + 4
        while watchdog.poll() is None and time.monotonic() < watchdog_deadline:
            worker.poll()  # reap the direct child once the watchdog terminates it
            os.utime(heartbeat, None, follow_symlinks=False)
            time.sleep(0.05)
        assert watchdog.poll() is not None
        worker.wait(timeout=3)
        terminal = ProductionWatchdogTerminalEvidence.model_validate_json(
            terminal_path.read_bytes()
        )
        assert terminal.outcome == "phase_deadline_worker_terminated"
        assert terminal.phase == timed_phase
        assert terminal.phase_deadline_acknowledged is True
        assert terminal.worker_kill_attempted is True
        assert terminal.worker_group_disappearance_confirmed is True
    finally:
        if terminal_fd is not None:
            os.close(terminal_fd)
        for process in (watchdog, worker):
            if process is None:
                continue
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass


@pytest.mark.parametrize("race", ("advance", "exit"))
def test_watchdog_rejects_between_poll_phase_overrun_races(race: str) -> None:
    """Model the poll gap with fixed timestamps, without scheduler/SIGSTOP races."""

    request = PhaseDeadlineRecord(
        attempt_id=f"phase-race-{race}",
        sequence=2,
        phase="request",
        issued_monotonic_ns=100,
        deadline_monotonic_ns=200,
        previous_record_sha256="1" * 64,
        record_sha256="2" * 64,
    )
    # The preceding poll was timely.  The next observable event occurs exactly
    # at the strict deadline and therefore cannot erase the prior overrun.
    assert not _acknowledged_phase_expired_before_advance(
        request,
        observed_monotonic_ns=199,
    )
    if race == "advance":
        shutdown = PhaseDeadlineRecord(
            attempt_id="phase-race-advance",
            sequence=3,
            phase="shutdown",
            issued_monotonic_ns=200,
            deadline_monotonic_ns=300,
            previous_record_sha256=request.record_sha256,
            record_sha256="3" * 64,
        )
        assert _acknowledged_phase_expired_before_advance(
            request,
            observed_monotonic_ns=199,
            proposed_phase_record=shutdown,
        )
    else:
        outcome, code = _worker_exit_outcome_at_terminal_observation(
            request,
            terminal_observed_monotonic_ns=200,
            absolute_deadline_monotonic_ns=400,
        )
        assert outcome is PrewarmWatchdogOutcome.PHASE_DEADLINE_TERMINATED
        assert code is PrewarmWatchdogExitCode.PHASE_DEADLINE_TERMINATED


def test_watchdog_empty_requires_kernel_esrch_not_enumeration() -> None:
    binding = WorkerBinding(
        pid=100,
        create_time_ns=10,
        process_group_id=100,
        session_id=100,
        controller_pid=200,
        watchdog_pid=300,
        watchdog_process_group_id=300,
        controller_process_group_id=200,
    )

    class Runtime:
        def __init__(self, *, exists: bool, members: object) -> None:
            self.exists = exists
            self.members = members

        def process_snapshot(self, _pid: int) -> None:
            return None

        def process_group_exists(self, _pgid: int) -> bool:
            return self.exists

        def process_group_members(self, _pgid: int):
            if isinstance(self.members, BaseException):
                raise self.members
            return self.members

    assert _frozen_group_state(
        binding, Runtime(exists=False, members=())
    ) == "empty"
    assert _frozen_group_state(
        binding, Runtime(exists=True, members=())
    ) == "unknown"
    assert _frozen_group_state(
        binding, Runtime(exists=True, members=None)
    ) == "unknown"
    assert _frozen_group_state(
        binding, Runtime(exists=True, members=OSError("raced listing"))
    ) == "unknown"


def test_live_exact_leader_keeps_raced_enumeration_nonempty() -> None:
    binding = WorkerBinding(
        pid=100,
        create_time_ns=10,
        process_group_id=100,
        session_id=100,
        controller_pid=200,
        watchdog_pid=300,
        watchdog_process_group_id=300,
        controller_process_group_id=200,
    )
    worker = ProcessSnapshot(
        pid=100,
        create_time_ns=10,
        parent_pid=200,
        process_group_id=100,
        session_id=100,
        terminal=False,
    )
    runtime = SimpleNamespace(
        process_snapshot=lambda _pid: worker,
        process_group_exists=lambda _pgid: True,
        process_group_members=lambda _pgid: (),
    )
    assert _frozen_group_state(binding, runtime) == "active"


def test_terminal_schema_rejects_late_normal_worker_exit() -> None:
    fields = {
        "schema_id": "phase-latency-prewarm-watchdog-terminal-v1",
        "attempt_id": "terminal-boundary",
        "controller_pid": 200,
        "controller_start_abstime": 19,
        "controller_create_time_ns": 20,
        "controller_pgid": 200,
        "controller_sid": 200,
        "worker_pid": 100,
        "worker_create_time_ns": 10,
        "worker_pgid": 100,
        "worker_sid": 100,
        "broker_pid": None,
        "broker_start_abstime": None,
        "broker_create_time_ns": None,
        "broker_pgid": None,
        "broker_sid": None,
        "absolute_deadline_monotonic_ns": 300,
        "observed_monotonic_ns": 199,
        "outcome": "worker_exited",
        "exit_code": 0,
        "termination_policy": "sigterm-250ms-then-sigkill-v1",
        "watchdog_excluded_from_worker_request_tree": True,
        "worker_kill_attempted": False,
        "sigterm_attempted": False,
        "sigkill_attempted": False,
        "worker_group_disappearance_confirmed": True,
        "broker_kill_attempted": False,
        "broker_sigterm_attempted": False,
        "broker_sigkill_attempted": False,
        "broker_group_disappearance_confirmed": None,
        "child_watch_registration_count": None,
        "child_watch_reaped_count": None,
        "child_watch_open_registration_count": None,
        "child_watch_all_disappearance_confirmed": None,
        "child_watch_identity_drift_observed": None,
        "child_watch_sigterm_attempted": None,
        "child_watch_sigkill_attempted": None,
        "child_watch_audit_closed": None,
        "child_watch_channel_eof": None,
        "child_watch_log_size_bytes": None,
        "child_watch_log_head_sha256": None,
        "child_watch_log_row_count": None,
        "child_watch_record_blob_root_sha256": None,
        "child_watch_record_blob_count": None,
        "child_watch_record_blob_size_bytes": None,
        "child_watch_record_blob_head_sha256": None,
        "child_watch_event_blob_count": None,
        "child_watch_event_blob_size_bytes": None,
        "child_watch_event_blob_root_sha256": None,
        "child_watch_event_head_sha256": None,
        "child_deadline_violation_observed": False,
        "phase_sequence": 3,
        "phase": "shutdown",
        "phase_deadline_monotonic_ns": 200,
        "phase_record_sha256": "1" * 64,
        "phase_ack_sha256": "2" * 64,
        "phase_deadline_acknowledged": True,
        "phase_deadline_violation_observed": False,
        "rejected_phase_sequence": None,
        "rejected_phase_record_sha256": None,
    }

    def with_identity(values: dict[str, object]) -> dict[str, object]:
        result = dict(values)
        result["record_sha256"] = hashlib.sha256(
            json.dumps(
                values,
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("ascii")
        ).hexdigest()
        return result

    assert ProductionWatchdogTerminalEvidence.model_validate(
        with_identity(fields)
    ).observed_monotonic_ns == 199
    late = {**fields, "observed_monotonic_ns": 200}
    with pytest.raises(ValidationError, match="normal watchdog terminal"):
        ProductionWatchdogTerminalEvidence.model_validate(with_identity(late))


def test_controller_sigkill_cannot_orphan_native_gil_worker(tmp_path: Path) -> None:
    workspace = Path(__file__).resolve().parents[2]
    state_path = tmp_path / "state.json"
    terminal_path = tmp_path / "watchdog-terminal.json"
    protocol = tmp_path / "protocol"
    controller_code = textwrap.dedent(
        """
        import json, os, psutil, subprocess, sys, time
        from pathlib import Path
        from tests.benchmarks.latency_prewarm_watchdog import (
            PrewarmWatchdogConfig,
            append_phase_deadline,
            build_prewarm_watchdog_command,
        )
        from tests.benchmarks.latency_watchdog import sanitized_watchdog_environment
        from app.services.tesseract_broker_native import raw_process_start_abstime

        protocol = Path(sys.argv[1])
        state_path = Path(sys.argv[2])
        terminal_path = Path(sys.argv[3])
        protocol.mkdir(mode=0o700)
        heartbeat = protocol / 'heartbeat'
        control = protocol / 'phase.jsonl'
        ack = protocol / 'ack.jsonl'
        ready = protocol / 'ready'
        for path in (heartbeat, control, ack):
            path.touch(mode=0o600)
        controller = psutil.Process(os.getpid())
        worker = subprocess.Popen(
            (sys.executable, '-c',
             'import ctypes; ctypes.PyDLL(None).sleep(60)'),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        worker_process = psutil.Process(worker.pid)
        whole = time.monotonic_ns() + 20_000_000_000
        append_phase_deadline(
            root=protocol,
            path=control,
            attempt_id='controller-sigkill',
            phase='startup',
            timeout_ns=15_000_000_000,
            whole_deadline_monotonic_ns=whole,
        )
        config = PrewarmWatchdogConfig(
            attempt_id='controller-sigkill',
            controller_pid=os.getpid(),
            controller_start_abstime=raw_process_start_abstime(os.getpid()),
            controller_create_time_ns=int(controller.create_time()*1_000_000_000),
            controller_pgid=os.getpgrp(),
            controller_sid=os.getsid(0),
            worker_pid=worker.pid,
            worker_create_time_ns=int(worker_process.create_time()*1_000_000_000),
            worker_pgid=worker.pid,
            worker_sid=worker.pid,
            heartbeat_root=protocol,
            heartbeat_path=heartbeat,
            ready_path=ready,
            phase_control_path=control,
            phase_ack_path=ack,
            absolute_deadline_monotonic_ns=whole,
        )
        terminal_fd = os.open(
            terminal_path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600
        )
        watcher = subprocess.Popen(
            build_prewarm_watchdog_command(
                python_executable=sys.executable, config=config
            ),
            stdin=subprocess.DEVNULL,
            stdout=terminal_fd,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=sanitized_watchdog_environment(),
        )
        os.close(terminal_fd)
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            os.utime(heartbeat, None, follow_symlinks=False)
            time.sleep(0.02)
        if not ready.exists():
            raise SystemExit(70)
        state = {
            'controller_pid': os.getpid(),
            'controller_create_time_ns': int(controller.create_time()*1_000_000_000),
            'worker_pid': worker.pid,
            'worker_create_time_ns': int(worker_process.create_time()*1_000_000_000),
            'watchdog_pid': watcher.pid,
            'watchdog_create_time_ns': int(psutil.Process(watcher.pid).create_time()*1_000_000_000),
        }
        raw = json.dumps(state, separators=(',', ':'), sort_keys=True).encode()
        descriptor = os.open(
            state_path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600
        )
        os.write(descriptor, raw)
        os.fsync(descriptor)
        os.close(descriptor)
        while True:
            os.utime(heartbeat, None, follow_symlinks=False)
            time.sleep(0.1)
        """
    )
    controller = subprocess.Popen(
        (
            sys.executable,
            "-c",
            controller_code,
            str(protocol),
            str(state_path),
            str(terminal_path),
        ),
        cwd=workspace,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    identities: dict[str, int] = {}
    try:
        state_deadline = time.monotonic() + 8
        while not state_path.exists() and time.monotonic() < state_deadline:
            if controller.poll() is not None:
                break
            time.sleep(0.02)
        assert state_path.is_file()
        identities = json.loads(state_path.read_bytes())
        os.killpg(controller.pid, signal.SIGKILL)
        controller.wait(timeout=3)
        terminal_deadline = time.monotonic() + 8
        while time.monotonic() < terminal_deadline:
            worker_gone = not psutil.pid_exists(identities["worker_pid"])
            watchdog_gone = not psutil.pid_exists(identities["watchdog_pid"])
            if terminal_path.stat().st_size and worker_gone and watchdog_gone:
                break
            time.sleep(0.05)
        terminal = ProductionWatchdogTerminalEvidence.model_validate_json(
            terminal_path.read_bytes()
        )
        assert terminal.outcome == "controller_dead_worker_terminated"
        assert terminal.worker_kill_attempted is True
        assert terminal.worker_group_disappearance_confirmed is True
        assert not psutil.pid_exists(identities["worker_pid"])
        assert not psutil.pid_exists(identities["watchdog_pid"])
        assert psutil.pid_exists(os.getpid())
    finally:
        if controller.poll() is None:
            try:
                os.killpg(controller.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            controller.wait(timeout=3)
        for key in ("worker_pid", "watchdog_pid"):
            pid = identities.get(key)
            if pid and psutil.pid_exists(pid):
                try:
                    os.killpg(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass


def test_watchdog_kills_group_when_leader_exits_but_child_persists(
    tmp_path: Path,
) -> None:
    root = tmp_path / "leader-exit"
    root.mkdir(mode=0o700)
    heartbeat = root / "heartbeat"
    ready = root / "ready"
    control = root / "phase.jsonl"
    ack = root / "ack.jsonl"
    child_path = root / "child-pid"
    terminal_path = root / "terminal.json"
    for path in (heartbeat, control, ack):
        path.touch(mode=0o600)
    child_code = (
        "import signal,time;"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        "time.sleep(60)"
    )
    leader_code = (
        "import subprocess,sys,time,pathlib;"
        f"p=subprocess.Popen([sys.executable,'-c',{child_code!r}]);"
        f"pathlib.Path({str(child_path)!r}).write_text(str(p.pid));"
        "time.sleep(1)"
    )
    worker = subprocess.Popen(
        (sys.executable, "-c", leader_code),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    watchdog: subprocess.Popen[bytes] | None = None
    terminal_fd: int | None = None
    child_pid: int | None = None
    try:
        controller = psutil.Process(os.getpid())
        worker_process = psutil.Process(worker.pid)
        whole = time.monotonic_ns() + 10_000_000_000
        append_phase_deadline(
            root=root,
            path=control,
            attempt_id="leader-exit",
            phase="startup",
            timeout_ns=8_000_000_000,
            whole_deadline_monotonic_ns=whole,
        )
        config = PrewarmWatchdogConfig(
            attempt_id="leader-exit",
            controller_pid=os.getpid(),
            controller_start_abstime=raw_process_start_abstime(os.getpid()),
            controller_create_time_ns=int(
                controller.create_time() * 1_000_000_000
            ),
            controller_pgid=os.getpgrp(),
            controller_sid=os.getsid(0),
            worker_pid=worker.pid,
            worker_create_time_ns=int(
                worker_process.create_time() * 1_000_000_000
            ),
            worker_pgid=worker.pid,
            worker_sid=worker.pid,
            heartbeat_root=root,
            heartbeat_path=heartbeat,
            ready_path=ready,
            phase_control_path=control,
            phase_ack_path=ack,
            absolute_deadline_monotonic_ns=whole,
        )
        terminal_fd = os.open(
            terminal_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        watchdog = subprocess.Popen(
            build_prewarm_watchdog_command(
                python_executable=sys.executable, config=config
            ),
            stdin=subprocess.DEVNULL,
            stdout=terminal_fd,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=sanitized_watchdog_environment(),
        )
        os.close(terminal_fd)
        terminal_fd = None
        deadline = time.monotonic() + 7
        while watchdog.poll() is None and time.monotonic() < deadline:
            worker.poll()
            os.utime(heartbeat, None, follow_symlinks=False)
            if child_path.exists() and child_pid is None:
                child_pid = int(child_path.read_text())
            time.sleep(0.02)
        assert watchdog.poll() is not None
        worker.wait(timeout=2)
        assert child_pid is not None
        terminal = ProductionWatchdogTerminalEvidence.model_validate_json(
            terminal_path.read_bytes()
        )
        assert terminal.outcome == "worker_group_residue_terminated"
        assert terminal.sigterm_attempted is True
        assert terminal.sigkill_attempted is True
        assert terminal.worker_group_disappearance_confirmed is True
        gone_deadline = time.monotonic() + 3
        while psutil.pid_exists(child_pid) and time.monotonic() < gone_deadline:
            time.sleep(0.02)
        assert not psutil.pid_exists(child_pid)
    finally:
        if terminal_fd is not None:
            os.close(terminal_fd)
        for process in (watchdog, worker):
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=3)
        if child_pid and psutil.pid_exists(child_pid):
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_unreaped_zombie_never_proves_process_group_disappearance() -> None:
    worker = subprocess.Popen(
        (sys.executable, "-c", "import time; time.sleep(0.1)"),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    identity = _process_identity(worker.pid)
    try:
        zombie_deadline = time.monotonic() + 3
        while time.monotonic() < zombie_deadline:
            try:
                if psutil.Process(worker.pid).status() == psutil.STATUS_ZOMBIE:
                    break
            except psutil.NoSuchProcess:
                break
            time.sleep(0.01)
        assert psutil.Process(worker.pid).status() == psutil.STATUS_ZOMBIE
        assert _frozen_process_group_state(identity) != "empty"
        worker.wait(timeout=2)
        assert _frozen_process_group_state(identity) == "empty"
    finally:
        if worker.returncode is None:
            worker.wait(timeout=2)


def test_reused_worker_identity_never_signals_numeric_process_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = subprocess.Popen(
        (sys.executable, "-c", "import time; time.sleep(60)"),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    identity = _process_identity(worker.pid)
    drifted = identity.model_copy(
        update={"create_time_ns": identity.create_time_ns + 1}
    )
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "tests.benchmarks.latency_prewarm_production_runner.os.killpg",
        lambda process_group_id, signum: signals.append(
            (process_group_id, signum)
        ),
    )
    try:
        with pytest.raises(RuntimeError, match="drifted"):
            _signal_frozen_process_group(drifted, signal.SIGKILL)
        assert signals == []
    finally:
        worker.kill()
        worker.wait(timeout=2)


def test_guarded_launch_normal_exit_reaps_without_false_group_residue(
    tmp_path: Path,
) -> None:
    output = tmp_path / "output"
    protocol = tmp_path / "protocol"
    output.mkdir(mode=0o700)
    protocol.mkdir(mode=0o700)
    worker_code = textwrap.dedent(
        """
        import os, sys
        from pathlib import Path
        from tests.benchmarks.latency_prewarm_watchdog import (
            append_phase_deadline, wait_for_phase_ack
        )
        values = dict(zip(sys.argv[1::2], sys.argv[2::2], strict=True))
        if os.read(int(values['--controller-release-fd']), 1) != b'\x01':
            raise SystemExit(70)
        control = Path(values['--phase-control'])
        ack = Path(values['--phase-ack'])
        record = append_phase_deadline(
            root=control.parent,
            path=control,
            attempt_id=values['--attempt-id'],
            phase='shutdown',
            timeout_ns=1_000_000_000,
            whole_deadline_monotonic_ns=int(
                values['--absolute-deadline-monotonic-ns']
            ),
        )
        wait_for_phase_ack(
            root=control.parent,
            path=ack,
            attempt_id=values['--attempt-id'],
            phase_record=record,
        )
        os.write(1, b'{}')
        """
    )
    launch = _guarded_worker_launch(
        attempt_id="normal-guarded-launch",
        workspace=Path(__file__).resolve().parents[2],
        output_directory=output,
        protocol=protocol,
        environment={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"},
        base_command=(sys.executable, "-c", worker_code),
        attempt_budget_ns=5_000_000_000,
        startup_timeout_ns=2_000_000_000,
    )
    stdout, stderr = launch.capture_until_exit()
    assert stdout == b"{}"
    assert stderr == b""
    assert launch.process is not None and launch.process.returncode == 0
    launch.collect_watchdog()
    assert launch.watchdog_terminal is not None
    assert launch.watchdog_terminal.outcome == "worker_exited"
    assert launch.watchdog_terminal.worker_kill_attempted is False
    assert launch.watchdog_terminal.worker_group_disappearance_confirmed is True
    assert launch.watchdog_reaped is True
    assert launch.watchdog_group_gone is True
    assert launch.launcher_terminal_evidence is not None
    launcher_evidence = launch.launcher_terminal_evidence
    assert launcher_evidence.root_returncodes == {"worker": 0}
    assert launch.phase_sequence_count == 2
    launcher_evidence = launch.launcher_terminal_evidence
    assert launcher_evidence is not None
    assert launcher_evidence.watchdog_result_record_sha256 == hashlib.sha256(
        canonical_model_bytes(launch.watchdog_terminal)[:-1]
    ).hexdigest()
    launcher_fields = launcher_evidence.model_dump(
        mode="python", exclude={"record_sha256"}
    )

    def rechained_launcher_log(
        mutate: Callable[[list[dict[str, Any]]], None],
    ) -> str:
        rows = [
            json.loads(encoded)
            for encoded in launcher_evidence.raw_log_canonical_jsonl.splitlines()
        ]
        mutate(rows)
        previous = "0" * 64
        wait_record_sha256s: dict[str, str] = {}
        wait_row_sha256s: dict[str, str] = {}
        encoded_rows: list[str] = []
        for sequence, row in enumerate(rows, 1):
            record = dict(row["record"])
            if row["kind"].endswith("_group_esrch"):
                role = row["kind"].removesuffix("_group_esrch")
                record["wait4_record_sha256"] = wait_record_sha256s[role]
                record["wait4_log_row_sha256"] = wait_row_sha256s[role]
            elif row["kind"] == "launcher_terminal":
                record["root_wait4_record_sha256s"] = wait_record_sha256s
                record["root_wait4_log_row_sha256s"] = wait_row_sha256s
            record["record_sha256"] = production_runner._canonical_sha256(
                {
                    key: value
                    for key, value in record.items()
                    if key != "record_sha256"
                }
            )
            row["record"] = record
            row["row_sequence"] = sequence
            row["previous_row_sha256"] = previous
            row["row_sha256"] = production_runner._canonical_sha256(
                {
                    key: value
                    for key, value in row.items()
                    if key != "row_sha256"
                }
            )
            previous = row["row_sha256"]
            if row["kind"].endswith("_wait4_tombstone"):
                role = row["kind"].removesuffix("_wait4_tombstone")
                wait_record_sha256s[role] = record["record_sha256"]
                wait_row_sha256s[role] = row["row_sha256"]
            encoded_rows.append(
                json.dumps(
                    row,
                    allow_nan=False,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
        return "\n".join(encoded_rows) + "\n"

    def with_replayed_log(raw_log: str, **updates: object) -> dict[str, object]:
        raw = raw_log.encode("utf-8")
        terminal = json.loads(raw_log.splitlines()[-1])["record"]
        changed: dict[str, object] = {
            **launcher_fields,
            "raw_log_canonical_jsonl": raw_log,
            "log_sha256": hashlib.sha256(raw).hexdigest(),
            "log_size_bytes": len(raw),
            "terminal_record_sha256": terminal["record_sha256"],
            "root_returncodes": terminal["root_returncodes"],
            "root_wait4_record_sha256s": terminal[
                "root_wait4_record_sha256s"
            ],
            "root_wait4_log_row_sha256s": terminal[
                "root_wait4_log_row_sha256s"
            ],
            **updates,
        }
        changed["record_sha256"] = production_runner._canonical_sha256(changed)
        return changed

    changed_wait = {
        **launcher_fields,
        "root_wait4_record_sha256s": {"worker": "f" * 64},
    }
    changed_wait["record_sha256"] = production_runner._canonical_sha256(
        changed_wait
    )
    with pytest.raises(ValidationError, match="launcher terminal evidence"):
        type(launcher_evidence).model_validate(changed_wait)
    changed_worker_root = {
        **launcher_fields,
        "worker_root": {
            **launcher_evidence.worker_root.model_dump(mode="python"),
            "start_abstime": launcher_evidence.worker_root.start_abstime + 1,
        },
    }
    changed_worker_root["record_sha256"] = production_runner._canonical_sha256(
        changed_worker_root
    )
    with pytest.raises(
        (RuntimeError, ValidationError),
        match="spawned root differs|launcher terminal evidence",
    ):
        type(launcher_evidence).model_validate(changed_worker_root)
    with pytest.raises(
        (RuntimeError, ValidationError),
        match="watchdog launcher terminal custody|launcher terminal evidence",
    ):
        changed_terminal = {
            **launcher_fields,
            "watchdog_result_record_sha256": "e" * 64,
        }
        changed_terminal["record_sha256"] = production_runner._canonical_sha256(
            changed_terminal
        )
        type(launcher_evidence).model_validate(changed_terminal)

    mutated_controller_start = launcher_evidence.controller_start_abstime + 1

    def mutate_ready_controller(rows: list[dict[str, Any]]) -> None:
        assert rows[0]["kind"] == "launcher_ready"
        rows[0]["record"]["controller"]["start_abstime"] = (
            mutated_controller_start
        )

    mutated_ready_log = rechained_launcher_log(mutate_ready_controller)
    internally_valid_mutation = type(launcher_evidence).model_validate(
        with_replayed_log(
            mutated_ready_log,
            controller_start_abstime=mutated_controller_start,
        )
    )
    assert not production_runner._launcher_terminal_matches_watchdog(
        internally_valid_mutation,
        launch.watchdog_terminal,
    )

    def mutate_wait4_rusage(rows: list[dict[str, Any]]) -> None:
        wait4 = next(
            row["record"]
            for row in rows
            if row["kind"] == "worker_wait4_tombstone"
        )
        wait4["rusage"]["user"]["derived_ns"] += 1

    invalid_rusage_log = rechained_launcher_log(mutate_wait4_rusage)
    with pytest.raises(
        (RuntimeError, ValidationError),
        match="wait4 rusage|native timeval nanoseconds",
    ):
        type(launcher_evidence).model_validate(
            with_replayed_log(invalid_rusage_log)
        )
    boundary = launch.controller_boundary()
    assert boundary.threads_returned_to_baseline
    assert boundary.file_descriptors_returned_to_baseline


def test_campaign_closure_is_final_self_excluding_exact_membership(
    tmp_path: Path,
) -> None:
    output = tmp_path / "output"
    terminal = output / "terminal"
    output.mkdir(mode=0o700)
    terminal.mkdir(mode=0o700)
    for path, raw in (
        (output / "plan.json", b"{}"),
        (terminal / "receipt.json", b"{\"ok\":true}"),
    ):
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            assert os.write(descriptor, raw) == len(raw)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    closure_path = production_runner._write_campaign_closure_manifest(
        output_root=output,
        expected_relative_paths={"plan.json", "terminal/receipt.json"},
        producer_groups_esrch=True,
        terminal_manifest_sha256="1" * 64,
        bundle_sha256="2" * 64,
        evaluation_sha256="3" * 64,
    )
    closure = production_runner.CampaignClosureManifest.model_validate_json(
        closure_path.read_bytes()
    )
    assert tuple(item.relative_path for item in closure.entries) == (
        "plan.json",
        "terminal/receipt.json",
    )
    assert closure.sole_self_exclusion == "campaign-closure.json"
    assert {path.name for path in output.iterdir()} == {
        "campaign-closure.json",
        "plan.json",
        "terminal",
    }


def test_campaign_closure_rejects_unindexed_and_hardlinked_files(
    tmp_path: Path,
) -> None:
    for variant in ("unindexed", "hardlink"):
        output = tmp_path / variant
        terminal = output / "terminal"
        output.mkdir(mode=0o700)
        terminal.mkdir(mode=0o700)
        retained = output / "plan.json"
        retained.write_bytes(b"{}")
        os.chmod(retained, 0o600)
        if variant == "unindexed":
            unexpected = output / "unexpected.json"
            unexpected.write_bytes(b"{}")
            os.chmod(unexpected, 0o600)
        else:
            os.link(retained, terminal / "hardlink.json")
        with pytest.raises(RuntimeError, match="campaign (closure|output)"):
            production_runner._write_campaign_closure_manifest(
                output_root=output,
                expected_relative_paths={"plan.json"},
                producer_groups_esrch=True,
                terminal_manifest_sha256="1" * 64,
                bundle_sha256="2" * 64,
                evaluation_sha256="3" * 64,
            )


def test_campaign_closure_indexes_compact_child_watch_blob_roots(
    tmp_path: Path,
) -> None:
    output = tmp_path / "compact-child-watch-output"
    terminal = output / "terminal"
    output.mkdir(mode=0o700)
    terminal.mkdir(mode=0o700)
    ledger_path = terminal / "attempt-child-watch.jsonl"
    ledger = _ChildWatchLedger(ledger_path)
    row = broker_audit_row_mapping(
        row_sequence=1,
        previous_row_sha256="0" * 64,
        kind="shutdown",
        record={"schema_id": "fixture-shutdown-v1"},
    )
    ledger.append_broker_row(row)
    ledger.close()
    closure_path = production_runner._write_campaign_closure_manifest(
        output_root=output,
        expected_relative_paths={"terminal/attempt-child-watch.jsonl"},
        producer_groups_esrch=True,
        terminal_manifest_sha256="1" * 64,
        bundle_sha256="2" * 64,
        evaluation_sha256="3" * 64,
    )
    closure = production_runner.CampaignClosureManifest.model_validate_json(
        closure_path.read_bytes()
    )
    retained_paths = {item.relative_path for item in closure.entries}
    assert "terminal/attempt-child-watch.jsonl" in retained_paths
    assert any(
        path.startswith(
            "terminal/attempt-child-watch.jsonl.records/r00000001-"
        )
        for path in retained_paths
    )
    assert (terminal / "attempt-child-watch.jsonl.events").is_dir()


def test_repeated_tail_rss_growth_blocks_noisy_and_small_linear_trends() -> None:
    mib = 1024 * 1024
    with pytest.raises(ValueError, match="four"):
        _unbounded_rss_growth([512 * mib, 800 * mib])
    assert _unbounded_rss_growth([700 * mib, 512 * mib, 516 * mib, 520 * mib])
    assert _unbounded_rss_growth([700 * mib, 512 * mib, 590 * mib, 580 * mib])
    assert not _unbounded_rss_growth(
        [700 * mib, 512 * mib, 516 * mib, 513 * mib]
    )


def test_successful_worker_envelope_rejects_artifact_mutation_after_validation(
    production_flagged_control: LocalPrewarmEvidenceBundle,
) -> None:
    worker = production_flagged_control.attempts[0].worker
    assert worker.runtime_artifact_after_shutdown is not None
    mutated_after = worker.runtime_artifact_after_shutdown.model_copy(
        update={"metadata_sha256": "f" * 64}
    )
    with pytest.raises(ValidationError, match="artifact changed"):
        WorkerMeasurementEnvelope.model_validate(
            {
                **worker.model_dump(mode="python"),
                "runtime_artifact_after_shutdown": mutated_after,
            }
        )


@pytest.mark.parametrize(
    "field",
    (
        "controller_resource_sample_log_sha256",
        "controller_resource_sample_log_row_count",
        "controller_resource_sample_log_size_bytes",
    ),
)
def test_successful_worker_recomputes_complete_controller_resource_log(
    production_flagged_control: LocalPrewarmEvidenceBundle,
    field: str,
) -> None:
    worker = production_flagged_control.attempts[0].worker
    mutation: object = "f" * 64
    if field == "controller_resource_sample_log_row_count":
        assert worker.controller_resource_sample_log_row_count is not None
        mutation = worker.controller_resource_sample_log_row_count + 1
    elif field == "controller_resource_sample_log_size_bytes":
        assert worker.controller_resource_sample_log_size_bytes is not None
        mutation = worker.controller_resource_sample_log_size_bytes + 1
    with pytest.raises(ValidationError, match="controller resource log"):
        WorkerMeasurementEnvelope.model_validate(
            {**worker.model_dump(mode="python"), field: mutation}
        )


@pytest.mark.parametrize(
    "field",
    (
        "attempt_id",
        "source",
        "execution",
        "configuration",
        "started_at_utc",
        "completed_at_utc",
        "status_failure",
    ),
)
def test_receipt_rejects_every_top_level_attempt_binding_mismatch(
    production_flagged_control: LocalPrewarmEvidenceBundle,
    field: str,
) -> None:
    attempt = production_flagged_control.attempts[0]
    retained_failure = FailureRecord(
        code=FailureCode.WORKER_PROTOCOL_FAILED,
        stage="shutdown",
    )
    embedded = attempt.model_copy(
        update={"status": AttemptStatus.ERROR, "failure": retained_failure}
    )
    fields = {
        "schema_id": "phase-latency-prewarm-attempt-receipt-v1",
        "attempt_id": attempt.attempt_id,
        "source": attempt.source,
        "execution": attempt.execution,
        "configuration": attempt.configuration,
        "started_at_utc": attempt.started_at_utc,
        "completed_at_utc": attempt.completed_at_utc,
        "controller_elapsed_ns": 1,
        "worker_return_code": 0,
        "stdout_size_bytes": 1,
        "stdout_sha256": "a" * 64,
        "stderr_size_bytes": 0,
        "stderr_sha256": hashlib.sha256(b"").hexdigest(),
        "forced_group_cleanup_required": False,
        "all_group_members_gone": True,
        "worker_stream_capture_disposition": (
            "incomplete_observed_prefix_forced_close"
        ),
        "controller_resources": _controller_boundary(),
        "launch_intent_sha256": "1" * 64,
        "phase_sequence_count": 0,
        "watchdog_reaped": False,
        "watchdog_process_group_gone": False,
        "status": embedded.status,
        "failure": embedded.failure,
        "attempt": embedded,
    }
    if field == "attempt_id":
        fields[field] = f"{attempt.attempt_id}-changed"
    elif field == "source":
        fields[field] = attempt.source.model_copy(update={"sha256": "f" * 64})
    elif field == "execution":
        fields[field] = attempt.execution.model_copy(
            update={"application_code_sha256": "f" * 64}
        )
    elif field == "configuration":
        fields[field] = next(
            item.configuration
            for item in production_flagged_control.attempts
            if item.configuration != attempt.configuration
        )
    elif field in {"started_at_utc", "completed_at_utc"}:
        fields[field] = fields[field] + timedelta(microseconds=1)
    else:
        fields["status"] = "success"
        fields["failure"] = None
    with pytest.raises(ValidationError, match="fields differ"):
        ProductionAttemptReceipt.model_validate(fields)


def test_post_launch_exception_retains_private_failed_receipt(
    tmp_path: Path,
    production_flagged_control: LocalPrewarmEvidenceBundle,
) -> None:
    attempt = production_flagged_control.attempts[0]
    path = tmp_path / "post-launch-failure.json"
    launch = SimpleNamespace(
        capture=None,
        stdout_observed_size_bytes=0,
        stdout_observed_sha256=hashlib.sha256(b"").hexdigest(),
        stderr_observed_size_bytes=0,
        stderr_observed_sha256=hashlib.sha256(b"").hexdigest(),
        intent=SimpleNamespace(intent_sha256="1" * 64),
        launch_record=None,
        launch_failure_record=None,
        phase_deadline_log_sha256=None,
        phase_ack_log_sha256=None,
        phase_sequence_count=0,
        watchdog_terminal_sha256=None,
        watchdog_terminal_observed_sha256=None,
        watchdog_terminal_validation_failed=False,
        watchdog_terminal=None,
        watchdog_reaped=False,
        watchdog_group_gone=False,
        prebind_fatal_path=tmp_path / "absent-prebind.json",
    )
    boundary = _controller_boundary()
    receipt = _retain_post_launch_failure_receipt(
        path=path,
        attempt_id=attempt.attempt_id,
        source=attempt.source,
        execution=attempt.execution,
        configuration=attempt.configuration,
        started_at_utc=attempt.started_at_utc,
        started_monotonic_ns=0,
        process=SimpleNamespace(returncode=-1),
        stdout=b"partial",
        stderr=b"getpgid failed",
        forced_group_cleanup_required=True,
        all_group_members_gone=True,
        error=RuntimeError("representative post-launch failure"),
        controller_resources=boundary,
        launch=launch,
    )
    assert receipt.status.value == "error"
    assert receipt.attempt is None
    assert path.is_file()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        _retain_post_launch_failure_receipt(
            path=path,
            attempt_id=attempt.attempt_id,
            source=attempt.source,
            execution=attempt.execution,
            configuration=attempt.configuration,
            started_at_utc=attempt.started_at_utc,
            started_monotonic_ns=0,
            process=SimpleNamespace(returncode=-1),
            stdout=b"",
            stderr=b"",
            forced_group_cleanup_required=True,
            all_group_members_gone=True,
            error=RuntimeError("second write"),
            controller_resources=boundary,
            launch=launch,
        )


def test_launcher_popen_failure_precedes_intent_and_closes_terminal_fd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "output"
    protocol = tmp_path / "protocol"
    output.mkdir(mode=0o700)
    protocol.mkdir(mode=0o700)

    def fail_popen(*_args: object, **_kwargs: object) -> None:
        raise OSError("forced Popen failure")

    monkeypatch.setattr(
        "tests.benchmarks.latency_prewarm_production_runner.subprocess.Popen",
        fail_popen,
    )
    before_fds = psutil.Process().num_fds()
    with pytest.raises(OSError, match="forced Popen failure"):
        _guarded_worker_launch(
            attempt_id="popen-failure",
            workspace=Path(__file__).resolve().parents[2],
            output_directory=output,
            protocol=protocol,
            environment={"PATH": os.defpath},
            base_command=(sys.executable, "-c", "pass"),
            attempt_budget_ns=2_000_000_000,
            startup_timeout_ns=1_000_000_000,
        )
    terminal = output / "popen-failure-watchdog-terminal.json"
    assert terminal.is_file()
    assert terminal.read_bytes() == b""
    assert stat.S_IMODE(terminal.stat().st_mode) == 0o600
    assert not (output / "popen-failure-launch-intent.json").exists()
    assert not (output / "popen-failure-launch-failure.json").exists()
    assert psutil.Process().num_fds() == before_fds


def test_brokered_prevalidation_failure_restores_controller_descriptors(
    tmp_path: Path,
) -> None:
    output = tmp_path / "output"
    protocol = tmp_path / "protocol"
    output.mkdir(mode=0o700)
    protocol.mkdir(mode=0o700)
    before_fds = {
        int(entry.name)
        for entry in Path("/dev/fd").iterdir()
        if entry.name.isdecimal()
    }

    with pytest.raises(ValueError, match="brokered worker target command"):
        _guarded_worker_launch(
            attempt_id="brokered-prevalidation-failure",
            workspace=Path(__file__).resolve().parents[2],
            output_directory=output,
            protocol=protocol,
            environment={"PATH": os.defpath},
            base_command=(sys.executable, "-c", "pass"),
            attempt_budget_ns=2_000_000_000,
            startup_timeout_ns=1_000_000_000,
            brokered=SimpleNamespace(worker_scratch_root=protocol),
            request_count=1,
            commit_worker_configuration=lambda _values: None,
        )

    after_fds = {
        int(entry.name)
        for entry in Path("/dev/fd").iterdir()
        if entry.name.isdecimal()
    }
    assert after_fds == before_fds
    assert production_runner._PENDING_PREINTENT_LAUNCHERS == {}
    assert production_runner._PENDING_PREINTENT_RESOURCE_CLEANUPS == {}
    assert not (
        output / "brokered-prevalidation-failure-launch-intent.json"
    ).exists()


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason="brokered materialization custody uses the frozen Darwin toolchain",
)
@pytest.mark.parametrize(
    "failure_window",
    (
        "materializer",
        "post_launcher_template",
        "request_root_open",
        "immutable_custody",
        "resource_transfer",
    ),
)
def test_brokered_preintent_failure_closes_every_held_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_window: str,
) -> None:
    workspace = Path(__file__).resolve().parents[2]
    output = tmp_path / "output"
    protocol = tmp_path / "protocol"
    artifact = tmp_path / "artifact"
    request_root = protocol / "broker-requests"
    staged_root = protocol / "staged-executable"
    for directory in (
        output,
        protocol,
        artifact,
        request_root,
        staged_root,
    ):
        directory.mkdir(mode=0o700)
    (artifact / "model.bin").write_bytes(b"bounded-artifact-probe")
    tesseract = Path("/opt/homebrew/bin/tesseract").resolve(strict=True)
    tessdata = Path("/opt/homebrew/share/tessdata").resolve(strict=True)
    captured: list[object] = []
    real_materialize = production_runner.materialize_sandbox_probe_roots
    sentinel_fds: list[int] = []

    def capture_materialization(**kwargs: object):
        materialization = real_materialize(**kwargs)
        captured.append(materialization)
        return materialization

    def fail_positive_controls(self: object, **_kwargs: object) -> None:
        raise RuntimeError("forced sandbox positive-control failure")

    monkeypatch.setattr(
        production_runner,
        "materialize_sandbox_probe_roots",
        capture_materialization,
    )
    if failure_window == "materializer":
        monkeypatch.setattr(
            production_runner.SandboxProbeMaterialization,
            "run_dac_positive_controls",
            fail_positive_controls,
        )
        expected_failure = "forced sandbox positive-control failure"
        failure_type: type[BaseException] = RuntimeError
    elif failure_window == "post_launcher_template":
        def fail_template_bytes(_mapping: object) -> bytes:
            raise RuntimeError("forced post-launcher template failure")

        monkeypatch.setattr(
            production_runner,
            "_broker_launch_template_bytes",
            fail_template_bytes,
        )
        real_launcher_cleanup = (
            production_runner._cleanup_pending_preintent_launcher
        )

        def cleanup_launcher_then_reuse_fds() -> None:
            real_launcher_cleanup()
            sentinel_fds.extend(
                os.open("/dev/null", os.O_RDONLY) for _ in range(32)
            )

        monkeypatch.setattr(
            production_runner,
            "_cleanup_pending_preintent_launcher",
            cleanup_launcher_then_reuse_fds,
        )
        expected_failure = "forced post-launcher template failure"
        failure_type = RuntimeError
    elif failure_window == "request_root_open":
        real_open = os.open

        def fail_request_root_open(
            path: object, flags: int, *args: object, **kwargs: object
        ) -> int:
            if (
                isinstance(path, (str, os.PathLike))
                and Path(path).resolve() == request_root.resolve(strict=True)
                and flags & getattr(os, "O_DIRECTORY", 0)
            ):
                raise OSError(errno.EIO, "forced request-root open failure")
            return real_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(production_runner.os, "open", fail_request_root_open)
        expected_failure = "forced request-root open failure"
        failure_type = OSError
    else:
        real_launch_close = production_runner._GuardedWorkerLaunch.close_release

        def close_launch_then_reuse_fds(self: object) -> None:
            real_launch_close(self)
            if not sentinel_fds:
                sentinel_fds.extend(
                    os.open("/dev/null", os.O_RDONLY) for _ in range(32)
                )

        monkeypatch.setattr(
            production_runner._GuardedWorkerLaunch,
            "close_release",
            close_launch_then_reuse_fds,
        )
        if failure_window == "immutable_custody":
            def fail_immutable_custody(_targets: object) -> None:
                raise RuntimeError("forced immutable-custody failure")

            monkeypatch.setattr(
                production_runner,
                "DarwinImmutableTreeCustody",
                fail_immutable_custody,
            )
            expected_failure = "forced immutable-custody failure"
        else:
            def fail_resource_transfer(_cleanup: object) -> None:
                raise RuntimeError("forced resource-transfer failure")

            monkeypatch.setattr(
                production_runner,
                "_transfer_pending_preintent_resource_cleanup",
                fail_resource_transfer,
            )
            expected_failure = "forced resource-transfer failure"
        failure_type = RuntimeError
    before_fds = {
        int(entry.name)
        for entry in Path("/dev/fd").iterdir()
        if entry.name.isdecimal()
    }

    with pytest.raises(failure_type, match=expected_failure):
        _guarded_worker_launch(
            attempt_id=f"brokered-{failure_window}-failure",
            workspace=workspace,
            output_directory=output,
            protocol=protocol,
            environment={"PATH": os.defpath},
            base_command=(
                sys.executable,
                "-m",
                "tests.benchmarks.latency_prewarm_production_worker",
            ),
            attempt_budget_ns=30_000_000_000,
            startup_timeout_ns=10_000_000_000,
            brokered=BrokeredLaunchInputs(
                tesseract_executable=tesseract,
                tesseract_data_path=tessdata,
                immutable_artifact_root=artifact.resolve(strict=True),
                allowed_languages=("eng",),
                request_root=request_root.resolve(strict=True),
                worker_scratch_root=request_root.resolve(strict=True),
                staged_executable_root=staged_root.resolve(strict=True),
                child_wrapper_path=(
                    workspace / "app/services/tesseract_child_exec.py"
                ).resolve(strict=True),
            ),
            request_count=1,
            commit_worker_configuration=lambda _values: None,
        )

    assert len(captured) == 1
    materialization = captured[0]
    assert materialization._closed is True
    for descriptor in sentinel_fds:
        os.fstat(descriptor)
    for descriptor in sentinel_fds:
        os.close(descriptor)
    for descriptor in materialization.root_fds.values():
        with pytest.raises(OSError) as error:
            os.fstat(descriptor)
        assert error.value.errno == errno.EBADF
    after_fds = {
        int(entry.name)
        for entry in Path("/dev/fd").iterdir()
        if entry.name.isdecimal()
    }
    assert after_fds == before_fds
    assert production_runner._PENDING_PREINTENT_LAUNCHERS == {}
    assert production_runner._PENDING_PREINTENT_RESOURCE_CLEANUPS == {}
    assert not (
        output / f"brokered-{failure_window}-failure-launch-intent.json"
    ).exists()


def test_watchdog_owned_worker_spawn_failure_is_durable_and_has_no_orphan(
    tmp_path: Path,
) -> None:
    output = tmp_path / "output"
    protocol = tmp_path / "protocol"
    output.mkdir(mode=0o700)
    protocol.mkdir(mode=0o700)
    with pytest.raises(_GuardedLaunchError) as captured:
        _guarded_worker_launch(
            attempt_id="watchdog-popen-failure",
            workspace=Path(__file__).resolve().parents[2],
            output_directory=output,
            protocol=protocol,
            environment={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"},
            base_command=(str(tmp_path / "missing-worker-executable"),),
            attempt_budget_ns=3_000_000_000,
            startup_timeout_ns=2_000_000_000,
        )
    launch = captured.value.launch
    assert launch.process is None
    assert launch.watchdog is not None
    assert launch.intent_path.is_file()
    assert launch.launch_failure_path.is_file()
    launch.collect_watchdog()
    assert launch.watchdog_terminal_fd is None
    assert launch.watchdog_reaped
    assert launch.watchdog_group_gone
    assert launch.launcher_log_path is not None
    rows, _raw, _opened = production_runner._read_watchdog_launcher_rows(
        launch.launcher_log_path,
        require_terminal=True,
    )
    assert any(row["kind"] == "worker_launch_failed" for row in rows)
    assert rows[-1]["kind"] == "launcher_terminal"


def test_exception_after_launcher_ready_before_intent_uses_cancel_custody(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "output"
    protocol = tmp_path / "protocol"
    output.mkdir(mode=0o700)
    protocol.mkdir(mode=0o700)

    def fail_intent_environment(_environment: dict[str, str]) -> str:
        raise RuntimeError("forced pre-intent failure")

    monkeypatch.setattr(
        production_runner,
        "worker_environment_sha256",
        fail_intent_environment,
    )
    with pytest.raises(RuntimeError, match="forced pre-intent failure"):
        _guarded_worker_launch(
            attempt_id="preintent-exception",
            workspace=Path(__file__).resolve().parents[2],
            output_directory=output,
            protocol=protocol,
            environment={"PATH": os.defpath},
            base_command=(sys.executable, "-c", "pass"),
            attempt_budget_ns=3_000_000_000,
            startup_timeout_ns=1_000_000_000,
        )

    assert not (output / "preintent-exception-launch-intent.json").exists()
    rows, _raw, _opened = production_runner._read_watchdog_launcher_rows(
        output / "preintent-exception-watchdog-launcher.jsonl",
        require_terminal=True,
    )
    assert tuple(row["kind"] for row in rows) == (
        "launcher_ready",
        "launch_cancelled",
        "launcher_terminal",
    )
    terminal = rows[-1]["record"]
    assert terminal["root_returncodes"] == {}
    assert terminal["root_groups_esrch"] == {}
    assert terminal["cleanup_succeeded"] is True


@pytest.mark.parametrize("signum", (signal.SIGTERM, signal.SIGHUP))
def test_signal_after_launcher_ready_before_intent_has_terminal_custody(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    signum: int,
) -> None:
    output = tmp_path / "output"
    protocol = tmp_path / "protocol"
    output.mkdir(mode=0o700)
    protocol.mkdir(mode=0o700)
    original_environment_sha256 = production_runner.worker_environment_sha256
    injected = False

    def signal_while_building_intent(environment: dict[str, str]) -> str:
        nonlocal injected
        if not injected:
            injected = True
            os.kill(os.getpid(), signum)
        return original_environment_sha256(environment)

    monkeypatch.setattr(
        production_runner,
        "worker_environment_sha256",
        signal_while_building_intent,
    )
    launch = None
    with pytest.raises(_ControllerTerminationSignal):
        with _scoped_signal_cleanup():
            try:
                _guarded_worker_launch(
                    attempt_id=f"preintent-signal-{signum}",
                    workspace=Path(__file__).resolve().parents[2],
                    output_directory=output,
                    protocol=protocol,
                    environment={"PATH": os.defpath},
                    base_command=(sys.executable, "-c", "pass"),
                    attempt_budget_ns=3_000_000_000,
                    startup_timeout_ns=1_000_000_000,
                )
            except _GuardedLaunchError as wrapped:
                launch = wrapped.launch
                launch.collect_watchdog()
                raise wrapped.error
    assert injected
    assert launch is not None
    assert launch.process is None
    assert launch.watchdog_reaped
    assert launch.watchdog_group_gone
    assert launch.launch_failure_path.is_file()
    assert launch.launcher_log_path is not None
    rows, _raw, _opened = production_runner._read_watchdog_launcher_rows(
        launch.launcher_log_path,
        require_terminal=True,
    )
    assert rows[-1]["kind"] == "launcher_terminal"


def _provisional_sampler_fixture(
    *,
    monkeypatch: pytest.MonkeyPatch,
    snapshots: list[object],
    broker_group_members: tuple[int, ...] = (200, 300),
) -> production_runner._ControllerOwnedRequestResourceSampler:
    """Build a deterministic controller sampler around synthetic kernel facts."""

    worker_identity = ExactProcessIdentity(
        role="parser_worker",
        pid=100,
        start_abstime=1_000,
        parent_pid=50,
        process_group_id=100,
        session_id=100,
    )
    baseline_threads = _native_thread_inventory(
        worker_identity, (11, 12, 13), 1
    )
    broker_identity = ExactProcessIdentity(
        role="tesseract_broker",
        pid=200,
        start_abstime=2_000,
        parent_pid=50,
        process_group_id=200,
        session_id=200,
    )
    broker_threads = _native_thread_inventory(broker_identity, (21,), 1)
    broker_baseline = broker_post_release_baseline(
        broker=broker_threads.process,
        pre_release_ready_sha256=_sha("sampler-broker-ready"),
        retired_descriptor_fds=(3, 4),
        pre_release_thread_inventory=broker_threads,
        pre_release_file_descriptor_inventory=_native_fd_inventory(
            broker_identity, 5, 1
        ),
        post_release_thread_inventory=broker_threads,
        post_release_file_descriptor_inventory=_native_fd_inventory(
            broker_identity, 3, 1
        ),
        transition_observed_at_monotonic_ns=1,
    )
    baseline = framework_thread_baseline(
        worker_pid=worker_identity.pid,
        worker_start_abstime=worker_identity.start_abstime,
        worker_ppid=worker_identity.parent_pid,
        worker_pgid=worker_identity.process_group_id,
        worker_sid=worker_identity.session_id,
        event_loop_python_thread_id=101,
        event_loop_native_thread_id=201,
        asyncio_executor_python_thread_id=102,
        asyncio_executor_native_thread_id=202,
        anyio_worker_python_thread_id=103,
        anyio_worker_native_thread_id=203,
        full_worker_proc_thread_ids=baseline_threads.thread_ids,
        full_worker_proc_thread_count=baseline_threads.thread_count,
        full_worker_proc_thread_inventory_sha256=(
            baseline_threads.inventory_sha256
        ),
        first_full_inventory_observed_at_monotonic_ns=1,
        second_full_inventory_observed_at_monotonic_ns=1,
        full_worker_file_descriptor_inventory=_native_fd_inventory(
            worker_identity, 4, 1
        ),
        broker_post_release_baseline=broker_baseline,
        observed_at_monotonic_ns=2,
    )

    class _DurableRows:
        def __init__(self) -> None:
            self.rows: list[dict[str, object]] = []
            self.count = 0

        def append(self, *, kind: str, record: object) -> str:
            assert kind == "controller-resource-sample"
            assert isinstance(record, dict)
            self.count += 1
            return f"{self.count:064x}"

    snapshot_iter = iter(snapshots)
    monkeypatch.setattr(
        production_runner,
        "_read_live_child_watch_snapshot",
        lambda _path: next(snapshot_iter),
    )

    def group_members(pgid: int) -> tuple[int, ...]:
        if pgid == 100:
            return (100,)
        if pgid == 200:
            return broker_group_members
        raise AssertionError(f"unexpected group {pgid}")

    monkeypatch.setattr(
        production_runner, "darwin_process_group_pids", group_members
    )

    def observed_identity(pid: int):
        if pid not in broker_group_members[1:]:
            raise AssertionError(f"unexpected child {pid}")
        return production_runner.DarwinProcessSelfCpuSample(
            pid=pid,
            start_abstime=pid * 10,
            parent_pid=200,
            process_group_id=200,
            session_id=200,
            observed_monotonic_ns=1_000,
            user_cpu_ns=0,
            system_cpu_ns=0,
        )

    monkeypatch.setattr(
        production_runner, "read_darwin_process_identity", observed_identity
    )

    def sample_metric(expected: dict[str, object]):
        pid = int(expected["pid"])
        native_thread_ids = (11, 12, 13) if pid == 100 else (pid + 1,)
        return production_runner._ExactProcessMetricObservation(
            cpu=production_runner.DarwinProcessSelfCpuSample(
                pid=pid,
                start_abstime=int(expected["start_abstime"]),
                parent_pid=int(expected["ppid"]),
                process_group_id=int(expected["pgid"]),
                session_id=int(expected["sid"]),
                observed_monotonic_ns=1_000,
                user_cpu_ns=pid,
                system_cpu_ns=pid,
            ),
            sample_started_monotonic_ns=999,
            sample_completed_monotonic_ns=1_001,
            rss_bytes=pid,
            thread_count=len(native_thread_ids),
            native_thread_ids=native_thread_ids,
            file_descriptor_count=4,
        )

    monkeypatch.setattr(
        production_runner, "_sample_exact_process_metric", sample_metric
    )
    return production_runner._ControllerOwnedRequestResourceSampler(
        attempt_id="attempt-provisional",
        request_id="request-1",
        request_epoch=2,
        request_sequence=1,
        worker_identity={
            "pid": 100,
            "start_abstime": 1_000,
            "ppid": 50,
            "pgid": 100,
            "sid": 100,
        },
        broker_identity={
            "pid": 200,
            "start_abstime": 2_000,
            "ppid": 50,
            "pgid": 200,
            "sid": 200,
        },
        framework_thread_baseline=baseline,
        child_watch_log_path=Path("/synthetic/child-watch.jsonl"),
        durable_log=_DurableRows(),  # type: ignore[arg-type]
        fatal_callback=lambda: None,
    )


def test_exact_process_metric_brackets_all_reads_and_rechecks_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = {
        "pid": 100,
        "start_abstime": 1_000,
        "ppid": 50,
        "pgid": 100,
        "sid": 100,
    }

    def identity(parent_pid: int = 50):
        return production_runner.DarwinProcessSelfCpuSample(
            pid=100,
            start_abstime=1_000,
            parent_pid=parent_pid,
            process_group_id=100,
            session_id=100,
            observed_monotonic_ns=150,
            user_cpu_ns=10,
            system_cpu_ns=20,
        )

    class FakeProcess:
        def __init__(self, pid: int) -> None:
            assert pid == 100

        def oneshot(self) -> "FakeProcess":
            return self

        def __enter__(self) -> "FakeProcess":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def memory_info(self) -> SimpleNamespace:
            return SimpleNamespace(rss=4_096)

        def num_threads(self) -> int:
            return 2

        def num_fds(self) -> int:
            return 6

    monotonic_values = iter((100, 200))
    monkeypatch.setattr(
        production_runner.time, "monotonic_ns", lambda: next(monotonic_values)
    )
    monkeypatch.setattr(
        production_runner, "read_darwin_process_identity", lambda _pid: identity()
    )
    monkeypatch.setattr(
        production_runner,
        "sample_darwin_process_self_cpu",
        lambda **_kwargs: identity(),
    )
    monkeypatch.setattr(production_runner.psutil, "Process", FakeProcess)
    monkeypatch.setattr(
        "app.services.tesseract_broker_native.native_thread_inventory",
        lambda _pid: (11, 12),
    )
    observed = production_runner._sample_exact_process_metric(expected)
    assert observed.sample_started_monotonic_ns == 100
    assert observed.cpu.observed_monotonic_ns == 150
    assert observed.sample_completed_monotonic_ns == 200


def test_exact_process_metric_rejects_final_lineage_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = {
        "pid": 100,
        "start_abstime": 1_000,
        "ppid": 50,
        "pgid": 100,
        "sid": 100,
    }

    def identity(parent_pid: int):
        return production_runner.DarwinProcessSelfCpuSample(
            pid=100,
            start_abstime=1_000,
            parent_pid=parent_pid,
            process_group_id=100,
            session_id=100,
            observed_monotonic_ns=150,
            user_cpu_ns=10,
            system_cpu_ns=20,
        )

    class FakeProcess:
        def __init__(self, _pid: int) -> None:
            pass

        def oneshot(self) -> "FakeProcess":
            return self

        def __enter__(self) -> "FakeProcess":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def memory_info(self) -> SimpleNamespace:
            return SimpleNamespace(rss=1)

        def num_threads(self) -> int:
            return 1

        def num_fds(self) -> int:
            return 1

    identities = iter((identity(50), identity(51)))
    monotonic_values = iter((100, 200))
    monkeypatch.setattr(
        production_runner.time, "monotonic_ns", lambda: next(monotonic_values)
    )
    monkeypatch.setattr(
        production_runner,
        "read_darwin_process_identity",
        lambda _pid: next(identities),
    )
    monkeypatch.setattr(
        production_runner,
        "sample_darwin_process_self_cpu",
        lambda **_kwargs: identity(50),
    )
    monkeypatch.setattr(production_runner.psutil, "Process", FakeProcess)
    monkeypatch.setattr(
        "app.services.tesseract_broker_native.native_thread_inventory",
        lambda _pid: (11,),
    )
    with pytest.raises(RuntimeError, match="identity/thread inventory drifted"):
        production_runner._sample_exact_process_metric(expected)


def _live_child_snapshot(
    *,
    pending: bool,
    provisional_pid: int | None = None,
) -> production_runner._LiveChildWatchSnapshot:
    token = ("request-1", 2, 1, 1, "a" * 64)
    spawn_record = {
        "request_id": token[0],
        "request_epoch": token[1],
        "request_sequence": token[2],
        "spawn_sequence": token[3],
        "spawn_nonce_sha256": token[4],
        "spawn_intent_sha256": "b" * 64,
    }
    pending_values = (
        {token: {"record": spawn_record, "row_sha256": "c" * 64}}
        if pending
        else {}
    )
    provisional_values: dict[tuple[int, int], dict[str, object]] = {}
    if provisional_pid is not None:
        key = (provisional_pid, provisional_pid * 10)
        provisional_values[key] = {
            **spawn_record,
            "pid": key[0],
            "start_abstime": key[1],
            "ppid": 200,
            "pgid": 200,
            "sid": 200,
        }
    return production_runner._LiveChildWatchSnapshot(
        raw_size_bytes=1,
        raw_sha256="d" * 64,
        broker_row_count=1,
        broker_head_sha256="e" * 64,
        event_count=0,
        event_head_sha256="0" * 64,
        pending_spawn_intents=pending_values,
        provisional_children=provisional_values,
        known_children=dict(provisional_values),
        open_registrations={},
        terminal_wait4_identities=frozenset(),
        pre_exec_gated_samples={},
        record_blob_count=1,
        record_blob_size_bytes=1,
        record_blob_head_sha256="f" * 64,
        record_blob_root={"record_sha256": "1" * 64},
        event_blob_size_bytes=0,
        event_blob_root={"record_sha256": "2" * 64},
    )


def test_controller_sampler_joins_held_post_fork_child_to_spawn_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = _live_child_snapshot(pending=True)
    joined = _live_child_snapshot(pending=False, provisional_pid=300)
    sampler = _provisional_sampler_fixture(
        monkeypatch=monkeypatch,
        # The first tick rereads once before accepting the unknown child.  The
        # second tick observes the exact durable provisional row.
        snapshots=[pending, pending, joined],
    )

    sampler._sample_once_locked(boundary_membership="boundary_interior")
    assert sampler._provisional_child_tokens == {
        (300, 3_000): ("request-1", 2, 1, 1, "a" * 64)
    }
    assert sampler._samples[-1]["aggregate"]["process_count"] == 3

    sampler._sample_once_locked(boundary_membership="boundary_interior")
    assert sampler._provisional_child_tokens == {
        (300, 3_000): ("request-1", 2, 1, 1, "a" * 64)
    }
    assert sampler._samples[-1]["aggregate"]["process_count"] == 3


def test_controller_sampler_rejects_second_child_before_provisional_custody(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = _live_child_snapshot(pending=True)
    sampler = _provisional_sampler_fixture(
        monkeypatch=monkeypatch,
        snapshots=[pending, pending],
        broker_group_members=(200, 300, 301),
    )

    with pytest.raises(
        RuntimeError, match="multiple children preceded provisional custody"
    ):
        sampler._sample_once_locked(boundary_membership="boundary_interior")


@pytest.mark.parametrize("signal_window", ("before_ready", "after_worker_exit"))
def test_controller_signal_windows_retain_failed_receipt_and_reap_groups(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    production_flagged_control: LocalPrewarmEvidenceBundle,
    signal_window: str,
) -> None:
    output = tmp_path / signal_window / "output"
    protocol = tmp_path / signal_window / "protocol"
    output.mkdir(parents=True, mode=0o700)
    protocol.mkdir(mode=0o700)
    attempt = production_flagged_control.attempts[0]
    worker_code = textwrap.dedent(
        """
        import os, sys
        from pathlib import Path
        from tests.benchmarks.latency_prewarm_watchdog import (
            append_phase_deadline, wait_for_phase_ack
        )
        values = dict(zip(sys.argv[1::2], sys.argv[2::2], strict=True))
        if os.read(int(values['--controller-release-fd']), 1) != b'\x01':
            raise SystemExit(70)
        if values['--attempt-id'].endswith('after-worker-exit'):
            control = Path(values['--phase-control'])
            record = append_phase_deadline(
                root=control.parent,
                path=control,
                attempt_id=values['--attempt-id'],
                phase='shutdown',
                timeout_ns=1_000_000_000,
                whole_deadline_monotonic_ns=int(
                    values['--absolute-deadline-monotonic-ns']
                ),
            )
            wait_for_phase_ack(
                root=control.parent,
                path=Path(values['--phase-ack']),
                attempt_id=values['--attempt-id'],
                phase_record=record,
            )
        """
    )
    attempt_id = f"signal-{signal_window.replace('_', '-')}"
    signal_threads: list[threading.Thread] = []
    signal_armed = False

    if signal_window == "before_ready":
        original_launch_root = (
            production_runner._WatchdogLauncherController.launch_root
        )

        def signal_after_worker_binding(
            control: object, *args: object, **kwargs: object
        ) -> dict[str, object]:
            nonlocal signal_armed
            ack = original_launch_root(control, *args, **kwargs)
            if kwargs.get("role") == "worker" and not signal_armed:
                signal_armed = True
                thread = threading.Thread(
                    target=lambda: os.kill(os.getpid(), signal.SIGTERM),
                    name="lat-us02-before-ready-signal",
                )
                signal_threads.append(thread)
                thread.start()
            return ack

        monkeypatch.setattr(
            production_runner._WatchdogLauncherController,
            "launch_root",
            signal_after_worker_binding,
        )

    launch = None
    receipt_path = output / f"{attempt_id}.json"
    with pytest.raises(_ControllerTerminationSignal):
        with _scoped_signal_cleanup():
            try:
                try:
                    launch = _guarded_worker_launch(
                        attempt_id=attempt_id,
                        workspace=Path(__file__).resolve().parents[2],
                        output_directory=output,
                        protocol=protocol,
                        environment={
                            "PATH": os.defpath,
                            "PYTHONDONTWRITEBYTECODE": "1",
                        },
                        base_command=(sys.executable, "-c", worker_code),
                        attempt_budget_ns=5_000_000_000,
                        startup_timeout_ns=2_000_000_000,
                    )
                except _GuardedLaunchError as wrapped:
                    launch = wrapped.launch
                    raise wrapped.error
                assert launch.process is not None
                launch.capture_until_exit()
                assert signal_window == "after_worker_exit"
                os.kill(os.getpid(), signal.SIGTERM)
            except _ControllerTerminationSignal as error:
                assert launch is not None
                for thread in signal_threads:
                    thread.join(timeout=2)
                forced_cleanup = False
                if launch.process is not None:
                    try:
                        forced_cleanup = launch.cleanup_worker_group()
                    except BaseException:
                        forced_cleanup = True
                    try:
                        launch.capture_until_exit()
                    except BaseException:
                        pass
                launch.collect_watchdog()
                boundary = launch.controller_boundary()
                group_gone = bool(
                    launch.worker_identity is not None
                    and launch.worker_group_disappeared()
                )
                receipt = _retain_post_launch_failure_receipt(
                    path=receipt_path,
                    attempt_id=attempt_id,
                    source=attempt.source,
                    execution=attempt.execution,
                    configuration=attempt.configuration,
                    started_at_utc=attempt.started_at_utc,
                    started_monotonic_ns=time.monotonic_ns(),
                    process=launch.process,
                    stdout=launch.stdout_retained_bytes,
                    stderr=launch.stderr_retained_bytes,
                    forced_group_cleanup_required=forced_cleanup,
                    all_group_members_gone=group_gone,
                    error=error,
                    controller_resources=boundary,
                    launch=launch,
                )
                assert receipt.status is AttemptStatus.ERROR
                assert boundary.threads_returned_to_baseline
                assert boundary.file_descriptors_returned_to_baseline
                raise
    assert launch is not None
    assert receipt_path.is_file()
    assert launch.process is not None and launch.process.returncode is not None
    assert launch.worker_identity is not None
    assert launch.worker_group_disappeared()
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600


def test_controller_signal_cannot_leave_partial_o_excl_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "signal-during-commit.json"
    boundary = _controller_boundary()
    real_write = os.write
    write_count = 0

    def signal_during_first_short_write(descriptor: int, payload: bytes) -> int:
        nonlocal write_count
        write_count += 1
        if write_count == 1:
            signal.raise_signal(signal.SIGTERM)
        return real_write(descriptor, payload[:7])

    monkeypatch.setattr(
        "tests.benchmarks.latency_prewarm_production_runner.os.write",
        signal_during_first_short_write,
    )
    with pytest.raises(_ControllerTerminationSignal):
        with _scoped_signal_cleanup():
            write_private_canonical(path, boundary)
    assert write_count > 1
    assert path.read_bytes() == canonical_model_bytes(boundary)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def _signal_custody_prepared_runtime(
    root: Path,
    production_flagged_control: LocalPrewarmEvidenceBundle,
) -> PreparedProductionRuntime:
    from app.services.parser_worker import artifact_identity

    base = root / "base"
    classifier = root / "f859dfbff5c9916cd996942d4b0db7fa25808220"
    target = root / "target"
    base_model = base / "docling-project--docling-models" / "model.bin"
    classifier_model = classifier / "model.bin"
    target_model = target / "docling-project--docling-models" / "model.bin"
    target_classifier = (
        target
        / "docling-project--DocumentFigureClassifier-v2.5"
        / "model.bin"
    )
    for path in (base_model, classifier_model, target_model, target_classifier):
        path.parent.mkdir(parents=True, exist_ok=True)
    base_model.write_bytes(b"base")
    classifier_model.write_bytes(b"classifier")
    target_model.write_bytes(b"base")
    target_classifier.write_bytes(b"classifier")
    target.chmod(0o700)
    tessdata = root / "tessdata"
    tessdata.mkdir()
    (tessdata / "eng.traineddata").write_bytes(b"bounded-test-traineddata")
    tesseract_source = root / "immutable-tesseract-test"
    tesseract_source.write_bytes(Path("/usr/bin/true").resolve().read_bytes())
    tesseract_source.chmod(0o500)
    observed = artifact_identity(target)
    target_identity = ArtifactIdentity(
        path="runtime-artifacts/signal-custody-tree",
        sha256=observed.sha256,
        size_bytes=observed.aggregate_bytes,
    )
    materialization = _materialization_manifest(
        target_path=target,
        target=target_identity,
        workspace_model_source=base,
        classifier_source=classifier,
        target_metadata_sha256=observed.metadata_sha256,
        target_file_count=observed.file_count,
        target_aggregate_bytes=observed.aggregate_bytes,
    )
    dependency_sha256 = "d" * 64
    common_environment = {
        "PATH": os.defpath,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "DOCLING_ARTIFACTS_PATH": str(target.resolve()),
        "TESSERACT_CMD": str(tesseract_source.resolve()),
        "TESSERACT_DATA_PATH": str(tessdata.resolve()),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "PARSER_LATENCY_PREWARM_TIMEOUT_SECONDS": "300",
        "PARSER_LATENCY_PREWARM_SHUTDOWN_GRACE_SECONDS": "2",
        "PARSER_LATENCY_PREWARM_ARTIFACTS_SHA256": observed.sha256,
        "PARSER_LATENCY_PREWARM_DEPENDENCY_SHA256": dependency_sha256,
    }
    return PreparedProductionRuntime(
        common_environment=common_environment,
        artifact_identity=target_identity,
        dependency_runtime_sha256=dependency_sha256,
        execution=production_flagged_control.attempts[0].execution,
        pairing_sha256="c" * 64,
        artifact_materialization=materialization,
    )


@pytest.mark.parametrize("signum", (signal.SIGTERM, signal.SIGHUP))
@pytest.mark.parametrize("control_kind", ("normal", "cross_input"))
def test_intent_commit_signal_retains_terminal_and_artifact_custody(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    production_flagged_control: LocalPrewarmEvidenceBundle,
    signum: int,
    control_kind: str,
) -> None:
    workspace = Path(__file__).resolve().parents[2]
    output = tmp_path / "output"
    output.mkdir(mode=0o700)
    prepared = _signal_custody_prepared_runtime(
        tmp_path / "runtime", production_flagged_control
    )
    source_a = production_flagged_control.attempts[0].source
    source_b = source_a.model_copy(
        update={
            "case_id": f"{source_a.case_id}-secondary",
            "filename": f"secondary-{source_a.filename}",
        }
    )
    output_identity = production_flagged_control.attempts[0].worker.requests[0].output
    assert output_identity is not None
    expected_a = CurrentRuntimeOutputExpectation(
        case_id=source_a.case_id,
        source_sha256=source_a.sha256,
        semantic_sha256=output_identity.semantic_sha256,
    )
    expected_b = CurrentRuntimeOutputExpectation(
        case_id=source_b.case_id,
        source_sha256=source_b.sha256,
        semantic_sha256=output_identity.semantic_sha256,
    )
    original_private_write = production_runner.write_private_canonical
    real_os_write = os.write
    signal_count = 0

    def signal_during_intent_commit(path: Path, model: object) -> None:
        nonlocal signal_count
        if not path.name.endswith("-launch-intent.json"):
            original_private_write(path, model)  # type: ignore[arg-type]
            return

        def short_write(descriptor: int, payload: bytes) -> int:
            nonlocal signal_count
            if signal_count == 0:
                signal_count = 1
                signal.raise_signal(signum)
            return real_os_write(descriptor, payload[:7])

        production_runner.os.write = short_write
        try:
            original_private_write(path, model)  # type: ignore[arg-type]
        finally:
            production_runner.os.write = real_os_write

    monkeypatch.setattr(
        production_runner,
        "write_private_canonical",
        signal_during_intent_commit,
    )
    if control_kind == "normal":
        attempt_id = (
            f"lat-us02-{source_a.case_id}-{RunMode.PREDECESSOR.value}-r01"
        )
        with pytest.raises(_ControllerTerminationSignal) as captured:
            run_production_attempt(
                workspace=workspace,
                output_directory=output,
                prepared=prepared,
                source=source_a,
                mode=RunMode.PREDECESSOR,
                repetition_index=1,
                request_count=4,
            )
        receipt_path = output / f"{attempt_id}.json"
        receipt = ProductionAttemptReceipt.model_validate_json(
            receipt_path.read_bytes()
        )
        assert receipt.status is AttemptStatus.ERROR
        assert receipt.launch_failure_record_sha256 is not None
    else:
        attempt_id = "lat-us02-cross-input-isolation"
        with pytest.raises(_ControllerTerminationSignal) as captured:
            run_cross_input_isolation_control(
                workspace=workspace,
                output_directory=output,
                prepared=prepared,
                source_a=source_a,
                source_b=source_b,
                expected_a=expected_a,
                expected_b=expected_b,
            )
        receipt_path = output / f"{attempt_id}-receipt.json"
        retained = json.loads(receipt_path.read_bytes())
        assert retained["status"] == "error"
        assert retained["launch_failure_record_sha256"] is not None
    assert captured.value.signum == signum
    assert signal_count == 1
    assert (output / f"{attempt_id}-launch-intent.json").is_file()
    assert (output / f"{attempt_id}-launch-failure.json").is_file()
    observation_path = output / f"{attempt_id}-artifact-observation.json"
    observation = PostAttemptArtifactObservation.model_validate_json(
        observation_path.read_bytes()
    )
    assert observation.matches_preflight is True
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(observation_path.stat().st_mode) == 0o600


def test_shared_attempt_gate_blocks_false_production_evidence(
    production_flagged_control: LocalPrewarmEvidenceBundle,
) -> None:
    attempt = production_flagged_control.attempts[0]
    worker = attempt.worker.model_copy(
        update={
            "production_asgi_lifespan_exercised": False,
            "network_isolation_validated": False,
        }
    )
    changed = attempt.model_copy(update={"worker": worker})
    failures = evaluate_local_prewarm_attempt_blocking_failures(
        changed, production_required=True
    )
    assert EvaluationFailureCode.PRODUCTION_LIFESPAN_NOT_EXERCISED in failures
    assert EvaluationFailureCode.NETWORK_ISOLATION_FAILED in failures

    boolean_only_worker = attempt.worker.model_copy(
        update={
            "production_asgi_lifespan_exercised": True,
            "network_isolation_validated": True,
            "kernel_sandbox_evidence": None,
        }
    )
    boolean_only = attempt.model_copy(update={"worker": boolean_only_worker})
    boolean_only_failures = evaluate_local_prewarm_attempt_blocking_failures(
        boolean_only, production_required=True
    )
    assert EvaluationFailureCode.NETWORK_ISOLATION_FAILED in boolean_only_failures


def test_fail_fast_semantic_pair_and_case_latency_gates(
    production_flagged_control: LocalPrewarmEvidenceBundle,
) -> None:
    def with_components(attempt: LocalPrewarmAttempt) -> LocalPrewarmAttempt:
        requests = []
        for request in attempt.worker.requests:
            assert request.output is not None
            output = request.output.model_copy(
                update={
                    "api_contract_sha256": request.output.semantic_sha256,
                    "provenance_sha256": "a" * 64,
                    "concerns_sha256": "b" * 64,
                    "deterministic_ids_sha256": "c" * 64,
                }
            )
            requests.append(request.model_copy(update={"output": output}))
        return attempt.model_copy(
            update={"worker": attempt.worker.model_copy(update={"requests": tuple(requests)})}
        )

    predecessor = with_components(next(
        item
        for item in production_flagged_control.attempts
        if item.mode is RunMode.PREDECESSOR
    ))
    enabled = with_components(next(
        item
        for item in production_flagged_control.attempts
        if item.mode is RunMode.ENABLED
        and item.repetition_index == predecessor.repetition_index
    ))
    output = predecessor.worker.requests[0].output
    assert output is not None
    expectation = CurrentRuntimeOutputExpectation(
        case_id=predecessor.case_id,
        source_sha256=predecessor.source.sha256,
        semantic_sha256=output.semantic_sha256,
    )
    wrong_expectation = expectation.model_copy(
        update={"semantic_sha256": "f" * 64}
    )
    with pytest.raises(RuntimeError, match="current-runtime"):
        _require_current_runtime_output(predecessor, wrong_expectation)

    changed_output = output.model_copy(update={"normalized_sha256": "e" * 64})
    changed_request = enabled.worker.requests[0].model_copy(
        update={"output": changed_output}
    )
    changed_worker = enabled.worker.model_copy(
        update={"requests": (changed_request, *enabled.worker.requests[1:])}
    )
    changed_enabled = enabled.model_copy(update={"worker": changed_worker})
    with pytest.raises(RuntimeError, match="output parity"):
        _require_enabled_pair_output_parity(
            predecessor=predecessor,
            enabled=changed_enabled,
            expectation=expectation,
        )

    case_attempts = []
    for original in production_flagged_control.attempts:
        attempt = with_components(original)
        if attempt.mode is RunMode.ENABLED:
            first = attempt.worker.requests[0]
            slow = first.model_copy(update={"latency_ns": 10**18})
            worker = attempt.worker.model_copy(
                update={"requests": (slow, *attempt.worker.requests[1:])}
            )
            attempt = attempt.model_copy(update={"worker": worker})
        case_attempts.append(attempt)
    with pytest.raises(RuntimeError, match="latency regression"):
        _require_completed_case_gates(tuple(case_attempts), expectation)


def test_cross_input_contract_rejects_a_b_a_contamination(
    production_flagged_control: LocalPrewarmEvidenceBundle,
) -> None:
    attempt = production_flagged_control.attempts[0]
    source_a = attempt.source
    source_b = SourceIdentity(
        case_id="distinct-b",
        path="fixtures/distinct-b.pdf",
        filename="distinct-b.pdf",
        sha256="b" * 64,
        size_bytes=1,
        page_count=1,
    )
    output = attempt.worker.requests[0].output
    assert output is not None
    base_boundary = attempt.worker.requests[0].resource_boundary
    assert base_boundary is not None and base_boundary.exact_broker_cpu is not None
    previous_cross_resource_row_sha256 = "0" * 64
    base_exact = base_boundary.exact_broker_cpu
    assert attempt.worker.fork_denial_evidence is not None
    cross_startup_receipt = _broker_lifecycle_receipt_fixture(
        logical_phase="startup",
        attempt_nonce_sha256=base_exact.attempt_nonce_sha256,
        scope_sha256=base_exact.scope_sha256,
        request_id="cross-input-startup",
        request_epoch=1,
        request_sequence=1,
        previous_receipt_sha256="0" * 64,
        worker=base_exact.begin.worker,
        broker=base_exact.begin.broker,
        observed_monotonic_ns=20,
        native_closure_sha256=(
            attempt.worker.fork_denial_evidence.native_closure_sha256
        ),
    )
    previous_cross_broker_receipt_sha256 = (
        cross_startup_receipt.receipt_sha256
    )

    def cross_input_boundary(
        index: int, request_source: SourceIdentity
    ) -> RequestResourceBoundary:
        nonlocal previous_cross_resource_row_sha256
        nonlocal previous_cross_broker_receipt_sha256
        source_boundary = attempt.worker.requests[index - 1].resource_boundary
        assert (
            source_boundary is not None
            and source_boundary.exact_broker_cpu is not None
        )
        exact = source_boundary.exact_broker_cpu
        request_id = f"{attempt.attempt_id}-q{index:04d}"
        wire_binding = {
            "schema_id": "parser-broker-request-binding-v2",
            "method": "POST",
            "path": "/v1/parse",
            "query_sha256": exact.request_binding.query_sha256,
            "output_format": "json",
            "source_sha256": request_source.sha256,
            "source_bytes": request_source.size_bytes,
            "safe_filename_sha256": hashlib.sha256(
                request_source.filename.encode("utf-8")
            ).hexdigest(),
            "upload_content_type_sha256": (
                exact.request_binding.upload_content_type_sha256
            ),
        }
        changed_binding = broker_request_binding_evidence(
            query_sha256=str(wire_binding["query_sha256"]),
            output_format="json",
            source_sha256=request_source.sha256,
            source_bytes=request_source.size_bytes,
            safe_filename_sha256=str(wire_binding["safe_filename_sha256"]),
            upload_content_type_sha256=str(
                wire_binding["upload_content_type_sha256"]
            ),
            binding_record_sha256=canonical_sha256(wire_binding),
            matched_at_monotonic_ns=(
                exact.request_binding.matched_at_monotonic_ns + index
            ),
        )
        begin = exact.begin.model_copy(
            update={
                "request_id": request_id,
                "request_epoch": index + 1,
                "request_sequence": index,
                "binding_sha256": changed_binding.binding_record_sha256,
                "request_binding": changed_binding,
                "ledger_head_sha256": previous_cross_broker_receipt_sha256,
            }
        )
        end = exact.end.model_copy(
            update={
                "request_id": request_id,
                "request_epoch": index + 1,
                "request_sequence": index,
                "ledger_head_sha256": previous_cross_broker_receipt_sha256,
            }
        )
        begin_external = external_cpu_stable_edge_record(
            attempt_id=exact.begin_external_sample.attempt_id,
            attempt_nonce_sha256=(
                exact.begin_external_sample.attempt_nonce_sha256
            ),
            scope_sha256=exact.begin_external_sample.scope_sha256,
            request_id=request_id,
            request_epoch=index + 1,
            request_sequence=index,
            request_deadline_monotonic_ns=(
                exact.begin_external_sample.request_deadline_monotonic_ns
            ),
            edge="begin",
            broker_sample=exact.begin_external_sample.broker_sample,
            worker_sample=exact.begin_external_sample.worker_sample,
            post_sample_scratch_inventory=(
                exact.begin_external_sample.post_sample_scratch_inventory
            ),
        )
        end_external = external_cpu_stable_edge_record(
            attempt_id=exact.end_external_sample.attempt_id,
            attempt_nonce_sha256=exact.end_external_sample.attempt_nonce_sha256,
            scope_sha256=exact.end_external_sample.scope_sha256,
            request_id=request_id,
            request_epoch=index + 1,
            request_sequence=index,
            request_deadline_monotonic_ns=(
                exact.end_external_sample.request_deadline_monotonic_ns
            ),
            edge="end",
            broker_sample=exact.end_external_sample.broker_sample,
            worker_sample=exact.end_external_sample.worker_sample,
            post_sample_scratch_inventory=(
                exact.end_external_sample.post_sample_scratch_inventory
            ),
        )
        changed_exact = ExactBrokerRequestCpuEvidence.model_validate(
            {
                **exact.model_dump(mode="python"),
                "request_id": request_id,
                "request_epoch": index + 1,
                "request_sequence": index,
                "binding_sha256": changed_binding.binding_record_sha256,
                "request_binding": changed_binding,
                "begin": begin,
                "end": end,
                "broker_request_receipt_sha256": _sha(
                    f"cross-input-{index}-broker-receipt"
                ),
                "begin_external_sample": begin_external,
                "end_external_sample": end_external,
            }
        )
        previous_cross_broker_receipt_sha256 = (
            changed_exact.broker_request_receipt_sha256
        )
        changed_resource_rows = []
        first_row_sequence = (
            (index - 1)
            * len(source_boundary.controller_resource_sample_rows)
            + 1
        )
        for row_sequence, row in enumerate(
            source_boundary.controller_resource_sample_rows, start=1
        ):
            changed_record = row.record.model_copy(
                update={
                    "request_id": request_id,
                    "request_epoch": index + 1,
                    "request_sequence": index,
                }
            )
            changed_row = controller_resource_sample_log_row(
                row_sequence=first_row_sequence + row_sequence - 1,
                previous_row_sha256=previous_cross_resource_row_sha256,
                record=changed_record,
                retained_monotonic_ns=row.retained_monotonic_ns,
            )
            changed_resource_rows.append(changed_row)
            previous_cross_resource_row_sha256 = changed_row.row_sha256
        return RequestResourceBoundary.model_validate(
            {
                **source_boundary.model_dump(mode="python"),
                "exact_broker_cpu": changed_exact,
                "controller_resource_sample_rows": tuple(
                    changed_resource_rows
                ),
            }
        )

    observations = tuple(
        CrossInputRequestObservation(
            sequence_index=index,
            source=source,
            latency_ns=1,
            output=output,
            runtime_snapshot_sha256="c" * 64,
            converter_sha256="d" * 64,
            resource_boundary=cross_input_boundary(index, source),
        )
        for index, source in enumerate((source_a, source_b, source_a), start=1)
    )
    cross_shutdown_receipt = _broker_lifecycle_receipt_fixture(
        logical_phase="shutdown",
        attempt_nonce_sha256=base_exact.attempt_nonce_sha256,
        scope_sha256=base_exact.scope_sha256,
        request_id="cross-input-shutdown",
        request_epoch=5,
        request_sequence=3,
        previous_receipt_sha256=previous_cross_broker_receipt_sha256,
        worker=base_exact.begin.worker,
        broker=base_exact.begin.broker,
        observed_monotonic_ns=5_000_000_000,
        native_closure_sha256=(
            attempt.worker.fork_denial_evidence.native_closure_sha256
        ),
    )
    production_cleanup = attempt.cleanup.model_copy(
        update={
            "controller_watchdog_process_group_count": 1,
            "owned_process_group_count": 3,
        }
    )
    cross_resource_log_bytes = b"".join(
        canonical_model_bytes(row)
        for observation in observations
        for row in observation.resource_boundary.controller_resource_sample_rows
    )
    original_readiness = attempt.worker.request_control_readiness
    assert original_readiness is not None
    cross_readiness = request_control_readiness_evidence(
        attempt_id=original_readiness.attempt_id,
        attempt_nonce_sha256=original_readiness.attempt_nonce_sha256,
        scope_sha256=original_readiness.scope_sha256,
        worker=original_readiness.worker,
        broker=original_readiness.broker,
        expected_request_count=3,
        framework_thread_baseline=original_readiness.framework_thread_baseline,
        controller_worker_thread_inventory=(
            original_readiness.controller_worker_thread_inventory
        ),
        controller_worker_file_descriptor_inventory=(
            original_readiness.controller_worker_file_descriptor_inventory
        ),
        controller_broker_thread_inventory=(
            original_readiness.controller_broker_thread_inventory
        ),
        controller_broker_file_descriptor_inventory=(
            original_readiness.controller_broker_file_descriptor_inventory
        ),
        ready_at_monotonic_ns=original_readiness.ready_at_monotonic_ns,
        previous_record_sha256=original_readiness.previous_record_sha256,
        transcript_row_sha256=original_readiness.transcript_row_sha256,
    )
    request_sources = (source_a, source_b, source_a)
    synthetic_cross_requests = tuple(
        attempt.worker.requests[index - 1].model_copy(
            update={
                "request_index": index,
                "latency_ns": observation.latency_ns,
                "output": observation.output,
                "resource_boundary": observation.resource_boundary,
            }
        )
        for index, observation in enumerate(observations, start=1)
    )
    (
        cross_readiness,
        retained_cross_requests,
        cross_terminal_request_control_transcript,
        previous_cross_broker_receipt_sha256,
    ) = _terminal_request_control_fixture(
        attempt_id=cross_readiness.attempt_id,
        mode=RunMode.ENABLED,
        request_sources=request_sources,
        readiness=cross_readiness,
        requests=synthetic_cross_requests,
        startup_broker_receipt=cross_startup_receipt,
    )
    observations = tuple(
        observation.model_copy(
            update={"resource_boundary": retained.resource_boundary}
        )
        for observation, retained in zip(
            observations, retained_cross_requests, strict=True
        )
    )
    cross_shutdown_receipt = _broker_lifecycle_receipt_fixture(
        logical_phase="shutdown",
        attempt_nonce_sha256=cross_readiness.attempt_nonce_sha256,
        scope_sha256=cross_readiness.scope_sha256,
        request_id="cross-input-shutdown",
        request_epoch=5,
        request_sequence=3,
        previous_receipt_sha256=previous_cross_broker_receipt_sha256,
        worker=cross_readiness.worker,
        broker=cross_readiness.broker,
        observed_monotonic_ns=5_000_000_000,
        native_closure_sha256=(
            attempt.worker.fork_denial_evidence.native_closure_sha256
        ),
    )
    cross_resource_log_bytes = b"".join(
        canonical_model_bytes(row)
        for observation in observations
        for row in observation.resource_boundary.controller_resource_sample_rows
    )
    evidence = CrossInputIsolationEvidence(
        schema_id="phase-latency-prewarm-cross-input-isolation-v1",
        source_a=source_a,
        source_b=source_b,
        execution=attempt.execution,
        application_settings_sha256="e" * 64,
        worker_environment_sha256="f" * 64,
        pairing_sha256="1" * 64,
        expected_a_semantic_sha256=output.semantic_sha256,
        expected_b_semantic_sha256=output.semantic_sha256,
        observations=observations,
        controller_resource_sample_log_sha256=hashlib.sha256(
            cross_resource_log_bytes
        ).hexdigest(),
        controller_resource_sample_log_row_count=sum(
            len(
                observation.resource_boundary.controller_resource_sample_rows
            )
            for observation in observations
        ),
        controller_resource_sample_log_size_bytes=len(
            cross_resource_log_bytes
        ),
        terminal_child_watch_log=_terminal_child_watch_fixture(),
        artifact_before_requests=attempt.worker.runtime_artifact_before_requests,
        artifact_after_shutdown=attempt.worker.runtime_artifact_after_shutdown,
        startup_duration_ns=1,
        shutdown_duration_ns=1,
        cleanup=production_cleanup,
        fork_denial_evidence=attempt.worker.fork_denial_evidence,
        request_control_readiness=cross_readiness,
        terminal_request_control_transcript=(
            cross_terminal_request_control_transcript
        ),
        immutable_runtime_input_custody=(
            _immutable_runtime_input_custody_fixture(
                attempt_id=cross_readiness.attempt_id,
                artifact=attempt.worker.runtime_artifact_before_requests,
            )
        ),
        startup_broker_receipt=cross_startup_receipt,
        shutdown_broker_receipt=cross_shutdown_receipt,
    )
    with pytest.raises(ValidationError, match="startup broker lifecycle"):
        CrossInputIsolationEvidence.model_validate(
            {
                **evidence.model_dump(mode="python"),
                "startup_broker_receipt": cross_shutdown_receipt,
                "shutdown_broker_receipt": cross_startup_receipt,
            }
        )
    with pytest.raises(ValidationError, match="broker lifecycle receipt"):
        CrossInputIsolationEvidence.model_validate(
            {
                **evidence.model_dump(mode="python"),
                "shutdown_broker_receipt": cross_shutdown_receipt.model_copy(
                    update={"previous_receipt_sha256": "f" * 64}
                ),
            }
        )
    changed_output = output.model_copy(update={"normalized_sha256": "9" * 64})
    changed_last = observations[2].model_copy(update={"output": changed_output})
    with pytest.raises(ValidationError, match="output isolation"):
        CrossInputIsolationEvidence.model_validate(
            {
                **evidence.model_dump(mode="python"),
                "observations": (*observations[:2], changed_last),
            }
        )

    def observations_with_worker_edge_sample(
        transform: Callable[
            [NativeProcessResourceSample], NativeProcessResourceSample
        ],
    ) -> tuple[CrossInputRequestObservation, ...]:
        changed: list[CrossInputRequestObservation] = []
        for observation in observations:
            boundary = observation.resource_boundary
            exact = boundary.exact_broker_cpu
            assert exact is not None

            def changed_edge(
                edge: Any,
            ) -> Any:
                return external_cpu_stable_edge_record(
                    attempt_id=edge.attempt_id,
                    attempt_nonce_sha256=edge.attempt_nonce_sha256,
                    scope_sha256=edge.scope_sha256,
                    request_id=edge.request_id,
                    request_epoch=edge.request_epoch,
                    request_sequence=edge.request_sequence,
                    request_deadline_monotonic_ns=(
                        edge.request_deadline_monotonic_ns
                        ),
                        edge=edge.edge,
                        broker_sample=edge.broker_sample,
                        worker_sample=transform(edge.worker_sample),
                    post_sample_scratch_inventory=(
                        edge.post_sample_scratch_inventory
                    ),
                )

            changed_exact = ExactBrokerRequestCpuEvidence.model_validate(
                {
                    **exact.model_dump(mode="python"),
                    "begin_external_sample": changed_edge(
                        exact.begin_external_sample
                    ),
                    "end_external_sample": changed_edge(
                        exact.end_external_sample
                    ),
                }
            )
            changed_boundary = RequestResourceBoundary.model_validate(
                {
                    **boundary.model_dump(mode="python"),
                    "exact_broker_cpu": changed_exact,
                }
            )
            changed.append(
                CrossInputRequestObservation.model_validate(
                    {
                        **observation.model_dump(mode="python"),
                        "resource_boundary": changed_boundary,
                    }
                )
            )
        return tuple(changed)

    base_worker_sample = (
        observations[0]
        .resource_boundary.exact_broker_cpu.begin_external_sample.worker_sample
    )
    replacement_thread_id = base_worker_sample.native_thread_ids[-1] + 1
    while replacement_thread_id in base_worker_sample.native_thread_ids:
        replacement_thread_id += 1
    def replace_thread(
        sample: NativeProcessResourceSample,
    ) -> NativeProcessResourceSample:
        return sample.model_copy(
            update={
                "native_thread_ids": (
                    *sample.native_thread_ids[:-1],
                    replacement_thread_id,
                )
            }
        )

    with pytest.raises(
        ValidationError, match="cross-input CPU request/identity custody"
    ):
        CrossInputIsolationEvidence.model_validate(
            {
                **evidence.model_dump(mode="python"),
                "observations": observations_with_worker_edge_sample(
                    replace_thread
                ),
            }
        )

    def replace_file_descriptor(
        sample: NativeProcessResourceSample,
    ) -> NativeProcessResourceSample:
        original_inventory = sample.file_descriptor_inventory
        replacement_index, original_descriptor = next(
            (index, descriptor)
            for index, descriptor in enumerate(original_inventory.descriptors)
            if descriptor.vnode is not None
        )
        assert original_descriptor.vnode is not None
        replacement_descriptor = native_file_descriptor_identity(
            **original_descriptor.model_dump(
                mode="python", exclude={"record_sha256", "vnode"}
            ),
            vnode=original_descriptor.vnode.model_copy(
                update={"resolved_path_sha256": _sha("cross-input-fd-swap")}
            ),
        )
        replacement_descriptors = list(original_inventory.descriptors)
        replacement_descriptors[replacement_index] = replacement_descriptor
        replacement_inventory = native_file_descriptor_inventory(
            process=original_inventory.process,
            first_scan_started_monotonic_ns=(
                original_inventory.first_scan_started_monotonic_ns
            ),
            first_scan_completed_monotonic_ns=(
                original_inventory.first_scan_completed_monotonic_ns
            ),
            second_scan_started_monotonic_ns=(
                original_inventory.second_scan_started_monotonic_ns
            ),
            second_scan_completed_monotonic_ns=(
                original_inventory.second_scan_completed_monotonic_ns
            ),
            descriptors=tuple(replacement_descriptors),
        )
        return sample.model_copy(
            update={"file_descriptor_inventory": replacement_inventory}
        )

    with pytest.raises(
        ValidationError, match="cross-input CPU request/identity custody"
    ):
        CrossInputIsolationEvidence.model_validate(
            {
                **evidence.model_dump(mode="python"),
                "observations": observations_with_worker_edge_sample(
                    replace_file_descriptor
                ),
            }
        )


def test_failed_final_evaluation_is_retained_but_cannot_return_success(
    production_flagged_control: LocalPrewarmEvidenceBundle,
) -> None:
    evaluation = evaluate_local_prewarm_bundle(production_flagged_control)
    retainedless_production = production_flagged_control.model_copy(
        update={"evidence_scope": "local_story_evidence"}
    )
    retainedless_evaluation = evaluate_local_prewarm_bundle(
        retainedless_production
    )
    assert (
        EvaluationFailureCode.RETAINED_RECEIPT_CUSTODY_FAILED
        in retainedless_evaluation.failure_codes
    )
    assert retainedless_evaluation.retained_receipt_authority_sha256 is None
    failed = LocalPrewarmEvaluation.model_validate(
        {
            **evaluation.model_dump(mode="python"),
            "non_rss_blocking_gates_passed": False,
            "completion_eligible_under_owner_rss_deferral": False,
            "failure_codes": (
                EvaluationFailureCode.NETWORK_ISOLATION_FAILED,
            ),
        }
    )
    with pytest.raises(RuntimeError, match="blocking failures"):
        _require_passing_final_evaluation(failed)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        ("cpu_capacity", EvaluationFailureCode.REQUEST_CPU_BOUNDARY_FAILED),
        ("sampled_late", EvaluationFailureCode.REQUEST_CPU_BOUNDARY_FAILED),
        ("cumulative", EvaluationFailureCode.REQUEST_CPU_BOUNDARY_FAILED),
        ("not_concurrent", EvaluationFailureCode.REQUEST_CPU_BOUNDARY_FAILED),
        ("coverage_gap", EvaluationFailureCode.REQUEST_CPU_BOUNDARY_FAILED),
        ("descendant_sampler", EvaluationFailureCode.DESCENDANT_SAMPLING_FAILED),
        ("worker_groups", EvaluationFailureCode.OWNED_PROCESS_GROUP_MISMATCH),
    ),
)
def test_cpu_descendant_and_worker_group_failures_are_blocking(
    production_flagged_control: LocalPrewarmEvidenceBundle,
    mutation: str,
    expected: EvaluationFailureCode,
) -> None:
    bundle = production_flagged_control
    attempt = bundle.attempts[0]
    worker = attempt.worker
    cleanup = attempt.cleanup
    if mutation == "descendant_sampler":
        worker = worker.model_copy(
            update={"concurrent_descendant_sampling_validated": False}
        )
    elif mutation == "worker_groups":
        cleanup = cleanup.model_copy(update={"owned_process_group_count": 2})
    else:
        request = worker.requests[0]
        assert request.resource_boundary is not None
        boundary = request.resource_boundary
        if mutation == "cpu_capacity":
            excess = boundary.wall_cpu_capacity_ns + 1
            boundary = boundary.model_copy(
                update={
                    "self_user_cpu_delta_ns": excess,
                    "self_system_cpu_delta_ns": 0,
                    "reaped_child_user_cpu_delta_ns": 0,
                    "reaped_child_system_cpu_delta_ns": 0,
                    "total_cpu_delta_ns": excess,
                }
            )
        elif mutation == "sampled_late":
            boundary = boundary.model_copy(update={"sampled_late": True})
        elif mutation == "cumulative":
            boundary = boundary.model_copy(
                update={"cumulative_contamination_detected": True}
            )
        elif mutation == "coverage_gap":
            boundary = boundary.model_copy(
                update={
                    "descendant_maximum_gap_ns": 100_000_001,
                    "request_boundary_covered": False,
                }
            )
        else:
            boundary = boundary.model_copy(update={"sampled_concurrently": False})
        requests = (
            request.model_copy(update={"resource_boundary": boundary}),
            *worker.requests[1:],
        )
        worker = worker.model_copy(update={"requests": requests})
    changed = attempt.model_copy(update={"worker": worker, "cleanup": cleanup})
    evaluation = evaluate_local_prewarm_bundle(_replace_attempt(bundle, changed))
    assert expected in evaluation.failure_codes
    assert evaluation.non_rss_blocking_gates_passed is False


def test_configuration_accepts_deployment_supplied_path_identities() -> None:
    configuration = production_configuration_identity(
        prewarm_enabled=True,
        startup_timeout_ns=300_000_000_000,
        request_count=4,
        application_settings_sha256="a" * 64,
        worker_environment_sha256="b" * 64,
        **_configuration_projections(True),
        artifacts_path="runtime-artifacts/approved-tree",
        artifacts_path_identity_sha256="d" * 64,
        tesseract_executable="/deployment/bin/tesseract",
        tesseract_data_path="/deployment/share/tessdata",
    )
    assert configuration.artifacts_path == "runtime-artifacts/approved-tree"
    assert configuration.tesseract_executable == "/deployment/bin/tesseract"
    isolation = cross_input_configuration_identity(
        application_settings_sha256="a" * 64,
        worker_environment_sha256="b" * 64,
        **_configuration_projections(True),
        artifacts_path="runtime-artifacts/approved-tree",
        artifacts_path_identity_sha256="d" * 64,
        tesseract_executable="/deployment/bin/tesseract",
        tesseract_data_path="/deployment/share/tessdata",
    )
    assert isolation.measurement_kind == "cross_input_aba"
    assert isolation.request_count == 3


def test_materialization_manifest_binds_both_sources_and_target(
    tmp_path: Path,
) -> None:
    from app.services.parser_worker import artifact_identity

    base = tmp_path / "base"
    classifier_revision = "f859dfbff5c9916cd996942d4b0db7fa25808220"
    classifier = tmp_path / classifier_revision
    target = tmp_path / "target"
    (base / "docling-project--docling-models").mkdir(parents=True)
    classifier.mkdir()
    (target / "docling-project--docling-models").mkdir(parents=True)
    (target / "docling-project--DocumentFigureClassifier-v2.5").mkdir()
    target.chmod(0o700)
    (base / "docling-project--docling-models" / "model.bin").write_bytes(b"base")
    (classifier / "model.bin").write_bytes(b"classifier")
    (target / "docling-project--docling-models" / "model.bin").write_bytes(b"base")
    (
        target / "docling-project--DocumentFigureClassifier-v2.5" / "model.bin"
    ).write_bytes(b"classifier")
    observed = artifact_identity(target)
    target_identity = ArtifactIdentity(
        path="runtime-artifacts/approved-tree",
        sha256=observed.sha256,
        size_bytes=observed.aggregate_bytes,
    )
    manifest = _materialization_manifest(
        target_path=target,
        target=target_identity,
        workspace_model_source=base,
        classifier_source=classifier,
        target_metadata_sha256=observed.metadata_sha256,
        target_file_count=observed.file_count,
        target_aggregate_bytes=observed.aggregate_bytes,
    )
    assert manifest.source_union_equals_target is True
    assert len(manifest.sources) == 2
    assert manifest.target_content_manifest_sha256
    assert manifest.target_resolved_runtime_path == str(target.resolve())
    assert manifest.target_before_artifact_sha256 == manifest.target_after_artifact_sha256
    assert manifest.before_after_identity_unchanged is True
    assert manifest.no_write_observed is True
    assert manifest.sources[0].portable_label == ".models/docling"
    assert manifest.sources[1].snapshot_revision == classifier_revision
    assert manifest.target_content_manifest_sha256 == target_identity.sha256

    fabricated = target_identity.model_copy(update={"sha256": "e" * 64})
    with pytest.raises(ValidationError, match="materialization target changed"):
        _materialization_manifest(
            target_path=target,
            target=fabricated,
            workspace_model_source=base,
            classifier_source=classifier,
            target_metadata_sha256=observed.metadata_sha256,
            target_file_count=observed.file_count,
            target_aggregate_bytes=observed.aggregate_bytes,
        )


def test_final_campaign_gate_rejects_target_mutation_after_preflight(
    tmp_path: Path,
) -> None:
    from app.services.parser_worker import artifact_identity

    base = tmp_path / "base"
    classifier_revision = "f859dfbff5c9916cd996942d4b0db7fa25808220"
    classifier = tmp_path / classifier_revision
    target = tmp_path / "target"
    base_model = base / "docling-project--docling-models" / "model.bin"
    target_model = target / "docling-project--docling-models" / "model.bin"
    target_classifier = (
        target
        / "docling-project--DocumentFigureClassifier-v2.5"
        / "model.bin"
    )
    base_model.parent.mkdir(parents=True)
    classifier.mkdir()
    target_model.parent.mkdir(parents=True)
    target_classifier.parent.mkdir()
    base_model.write_bytes(b"base")
    (classifier / "model.bin").write_bytes(b"classifier")
    target_model.write_bytes(b"base")
    target_classifier.write_bytes(b"classifier")
    target.chmod(0o700)
    observed = artifact_identity(target)
    target_identity = ArtifactIdentity(
        path="runtime-artifacts/approved-tree",
        sha256=observed.sha256,
        size_bytes=observed.aggregate_bytes,
    )
    preflight = _materialization_manifest(
        target_path=target,
        target=target_identity,
        workspace_model_source=base,
        classifier_source=classifier,
        target_metadata_sha256=observed.metadata_sha256,
        target_file_count=observed.file_count,
        target_aggregate_bytes=observed.aggregate_bytes,
    )
    prepared = SimpleNamespace(
        artifact_identity=target_identity,
        artifact_materialization=preflight,
    )
    target_model.write_bytes(b"mutated-after-preflight")

    with pytest.raises(RuntimeError, match="artifact custody failed"):
        _retain_and_require_artifact_observation(
            output_directory=tmp_path,
            attempt_id="failed-attempt",
            prepared=prepared,
            artifacts_path=target,
        )
    observation_path = tmp_path / "failed-attempt-artifact-observation.json"
    retained_observation = PostAttemptArtifactObservation.model_validate_json(
        observation_path.read_bytes()
    )
    assert retained_observation.status == "mismatch"
    assert retained_observation.matches_preflight is False
    assert stat.S_IMODE(observation_path.stat().st_mode) == 0o600

    with pytest.raises((RuntimeError, ValueError)):
        _finalize_production_artifact_materialization(
            prepared=prepared,
            artifacts_path=target,
            workspace_model_source=base,
            classifier_source=classifier,
        )


@pytest.mark.parametrize("mode", (RunMode.PREDECESSOR, RunMode.ENABLED))
def test_both_production_modes_use_exact_os_sandbox_and_private_guard(
    tmp_path: Path,
    mode: RunMode,
) -> None:
    workspace = Path(__file__).resolve().parents[2]
    guard_root = tmp_path / mode.value
    guard_root.mkdir(mode=0o700)
    materialize_private_child_network_guard(workspace, guard_root)
    environment = _attempt_environment(
        workspace=workspace,
        prepared=SimpleNamespace(common_environment={}),
        guard_root=guard_root,
        mode=mode,
    )
    assert environment["PARSER_LATENCY_PREWARM_ENABLED"] == (
        "true" if mode is RunMode.ENABLED else "false"
    )
    assert environment["PHASE_LATENCY_CHILD_GUARD"] == "all-python-processes-v1"
    assert environment["PYTHONPATH"].split(os.pathsep) == [
        str(guard_root.resolve()),
        str(workspace.resolve()),
    ]
    raw = (
        sys.executable,
        "-m",
        "tests.benchmarks.latency_prewarm_production_worker",
        "--mode",
        mode.value,
    )
    assert _sandboxed_production_worker_command(raw) == (
        OS_NETWORK_SANDBOX_EXECUTABLE,
        "-p",
        OS_NETWORK_SANDBOX_PROFILE,
        *raw,
    )


def test_private_canonical_writer_is_mode_0600_and_no_overwrite(
    tmp_path: Path,
) -> None:
    source = SourceIdentity(
        case_id="private-write",
        path="fixtures/private-write.pdf",
        filename="private-write.pdf",
        sha256="a" * 64,
        size_bytes=1,
        page_count=1,
    )
    path = tmp_path / "evidence.json"
    write_private_canonical(path, source)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_bytes().endswith(b"\n")
    with pytest.raises(FileExistsError):
        write_private_canonical(path, source)


def test_dual_group_watchdog_reaps_term_responder_and_kills_resister(
    tmp_path: Path,
) -> None:
    """One managed group exiting on TERM cannot hide residue in the other."""

    root = tmp_path / "dual-watchdog"
    root.mkdir(mode=0o700)
    heartbeat = root / "heartbeat"
    ready = root / "ready"
    control = root / "phase.jsonl"
    ack = root / "ack.jsonl"
    terminal_path = root / "terminal.json"
    heartbeat.touch(mode=0o600)
    controller = psutil.Process(os.getpid())
    controller_created = int(controller.create_time() * 1_000_000_000)
    worker = subprocess.Popen(
        (sys.executable, "-c", "import time; time.sleep(60)"),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    broker = subprocess.Popen(
        (
            sys.executable,
            "-c",
            "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)",
        ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    watchdog: subprocess.Popen[bytes] | None = None
    terminal_fd: int | None = None
    broker_watch, watchdog_watch = socket.socketpair(
        socket.AF_UNIX, socket.SOCK_STREAM
    )
    worker_phase, watchdog_phase = socket.socketpair(
        socket.AF_UNIX, socket.SOCK_STREAM
    )
    try:
        whole_deadline = time.monotonic_ns() + 5_000_000_000
        from app.services.tesseract_broker_native import raw_process_start_abstime

        worker_created = int(
            psutil.Process(worker.pid).create_time() * 1_000_000_000
        )
        broker_created = int(
            psutil.Process(broker.pid).create_time() * 1_000_000_000
        )
        config = PrewarmWatchdogConfig(
            attempt_id="dual-term-kill",
            controller_pid=os.getpid(),
            controller_start_abstime=raw_process_start_abstime(os.getpid()),
            controller_create_time_ns=controller_created,
            controller_pgid=os.getpgrp(),
            controller_sid=os.getsid(0),
            worker_pid=worker.pid,
            worker_create_time_ns=worker_created,
            worker_pgid=worker.pid,
            worker_sid=worker.pid,
            heartbeat_root=root,
            heartbeat_path=heartbeat,
            ready_path=ready,
            phase_control_path=control,
            phase_ack_path=ack,
            absolute_deadline_monotonic_ns=whole_deadline,
            phase_control_fd=watchdog_phase.fileno(),
            startup_timeout_ns=4_000_000_000,
            worker_start_abstime=raw_process_start_abstime(worker.pid),
            broker_pid=broker.pid,
            broker_start_abstime=raw_process_start_abstime(broker.pid),
            broker_create_time_ns=broker_created,
            broker_pgid=broker.pid,
            broker_sid=broker.pid,
            broker_watchdog_fd=watchdog_watch.fileno(),
            child_watch_log_path=root / "child-watch.jsonl",
            attempt_nonce_sha256="a" * 64,
            scope_sha256="b" * 64,
            watchdog_protocol_sha256=hashlib.sha256(
                Path(production_runner.__file__)
                .with_name("latency_prewarm_watchdog.py")
                .read_bytes()
            ).hexdigest(),
            native_closure_sha256="c" * 64,
        )
        terminal_fd = os.open(
            terminal_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        watchdog = subprocess.Popen(
            build_prewarm_watchdog_command(
                python_executable=sys.executable, config=config
            ),
            stdin=subprocess.DEVNULL,
            stdout=terminal_fd,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            pass_fds=(watchdog_watch.fileno(), watchdog_phase.fileno()),
            env=sanitized_watchdog_environment(),
        )
        watchdog_watch.close()
        watchdog_phase.close()
        os.close(terminal_fd)
        terminal_fd = None
        ready_deadline = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < ready_deadline:
            os.utime(heartbeat, None, follow_symlinks=False)
            time.sleep(0.01)
        assert ready.read_bytes() == b"READY\n"
        watchdog.send_signal(signal.SIGTERM)
        exit_deadline = time.monotonic() + 4
        while watchdog.poll() is None and time.monotonic() < exit_deadline:
            worker.poll()
            broker.poll()
            os.utime(heartbeat, None, follow_symlinks=False)
            time.sleep(0.01)
        worker.wait(timeout=2)
        broker.wait(timeout=2)
        watchdog.wait(timeout=2)
        terminal = ProductionWatchdogTerminalEvidence.model_validate_json(
            terminal_path.read_bytes()
        )
        assert terminal.outcome == "signal_worker_terminated"
        assert terminal.worker_group_disappearance_confirmed
        assert terminal.broker_group_disappearance_confirmed
        assert terminal.sigterm_attempted
        assert terminal.broker_sigterm_attempted
        assert terminal.broker_sigkill_attempted
        assert not production_runner._group_exists(worker.pid)
        assert not production_runner._group_exists(broker.pid)
    finally:
        for channel in (
            broker_watch,
            watchdog_watch,
            worker_phase,
            watchdog_phase,
        ):
            try:
                channel.close()
            except OSError:
                pass
        if terminal_fd is not None:
            os.close(terminal_fd)
        for process in (watchdog, worker, broker):
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=2)


@pytest.mark.parametrize(
    ("request_count", "duplicate_writer"),
    ((1, False), (4, False), (1, True)),
)
def test_direct_phase_capability_durably_acks_strict_outer_deadlines(
    tmp_path: Path,
    request_count: int,
    duplicate_writer: bool,
) -> None:
    """The brokered worker never needs write access to watchdog phase logs."""

    root = tmp_path / "phase-capability"
    root.mkdir(mode=0o700)
    control = root / "phase-deadlines.jsonl"
    ack = root / "phase-acks.jsonl"
    worker_socket, watchdog_socket = socket.socketpair(
        socket.AF_UNIX, socket.SOCK_STREAM
    )
    deadline = time.monotonic_ns() + 5_000_000_000
    runtime = SimpleNamespace(monotonic_ns=time.monotonic_ns)
    attempt_id = f"phase-capability-{request_count}-{int(duplicate_writer)}"
    registry = _PhaseControlRegistry(
        descriptor=watchdog_socket.detach(),
        root=root,
        control_path=control,
        ack_path=ack,
        attempt_id=attempt_id,
        attempt_nonce_sha256="1" * 64,
        scope_sha256="2" * 64,
        worker_pid=41001,
        worker_start_abstime=51001,
        worker_pgid=41001,
        worker_sid=41001,
        startup_timeout_ns=4_000_000_000,
        absolute_deadline_monotonic_ns=deadline,
        runtime=runtime,
    )
    client = ParserPhaseControlClient(
        descriptor=worker_socket.detach(),
        attempt_id=attempt_id,
        attempt_nonce_sha256="1" * 64,
        scope_sha256="2" * 64,
        worker_pid=41001,
        worker_start_abstime=51001,
        worker_pgid=41001,
        worker_sid=41001,
        absolute_deadline_monotonic_ns=deadline,
    )
    failure: list[BaseException] = []
    stop = threading.Event()

    def serve() -> None:
        try:
            while not stop.is_set():
                registry.service_available()
                time.sleep(0.001)
        except BaseException as error:  # pragma: no cover - asserted below
            failure.append(error)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        client.bind_initial_startup()
        requested_phase_deadlines: list[int] = []
        for _request in range(request_count + int(duplicate_writer)):
            requested_deadline = min(
                deadline, time.monotonic_ns() + 2_000_000_000
            )
            requested_phase_deadlines.append(requested_deadline)
            client.advance("request", requested_deadline)
        shutdown_deadline = min(
            deadline, time.monotonic_ns() + 2_000_000_000
        )
        requested_phase_deadlines.append(shutdown_deadline)
        client.advance("shutdown", shutdown_deadline)
        client.close()
        eof_deadline = time.monotonic() + 1
        while not registry.channel_eof and time.monotonic() < eof_deadline:
            time.sleep(0.005)
        assert registry.bound
        assert registry.current_record.phase == "shutdown"
        assert registry.channel_eof
        records, _record_snapshot = read_phase_deadlines(
            root=root,
            path=control,
            attempt_id=attempt_id,
            whole_deadline_monotonic_ns=deadline,
        )
        acks, _ack_snapshot = read_phase_acks(
            root=root,
            path=ack,
            attempt_id=attempt_id,
        )
        actual_request_count = request_count + int(duplicate_writer)
        assert tuple(record.phase for record in records) == (
            "startup",
            *("request" for _ in range(actual_request_count)),
            "shutdown",
        )
        assert len(acks) == len(records) == actual_request_count + 2
        assert tuple(record.deadline_monotonic_ns for record in records[1:]) == tuple(
            requested_phase_deadlines
        )
        assert all(
            phase_ack.phase_record_sha256 == phase_record.record_sha256
            for phase_ack, phase_record in zip(acks, records, strict=True)
        )
        request_boundaries = tuple(
            SimpleNamespace(
                request_sequence=sequence,
                arm={
                    "request_sequence": sequence,
                    "request_deadline_monotonic_ns": record.deadline_monotonic_ns,
                },
                end_blocked={
                    "broker_request_receipt": {
                        "phase_deadline_monotonic_ns": (
                            record.deadline_monotonic_ns
                        )
                    }
                },
            )
            for sequence, record in enumerate(records[1:-1], start=1)
        )
        if duplicate_writer:
            with pytest.raises(
                RuntimeError,
                match="complete phase deadline/ACK authority",
            ):
                production_runner._require_complete_phase_authority(
                    records=records,
                    acks=acks,
                    expected_request_count=request_count,
                    request_boundaries=request_boundaries[:request_count],
                )
        else:
            production_runner._require_complete_phase_authority(
                records=records,
                acks=acks,
                expected_request_count=request_count,
                request_boundaries=request_boundaries,
            )
            mismatched_boundaries = list(request_boundaries)
            first = mismatched_boundaries[0]
            mismatched_boundaries[0] = SimpleNamespace(
                request_sequence=first.request_sequence,
                arm={
                    **first.arm,
                    "request_deadline_monotonic_ns": (
                        first.arm["request_deadline_monotonic_ns"] + 1
                    ),
                },
                end_blocked=first.end_blocked,
            )
            with pytest.raises(
                RuntimeError,
                match="request phase deadline/ARM/receipt join",
            ):
                production_runner._require_complete_phase_authority(
                    records=records,
                    acks=acks,
                    expected_request_count=request_count,
                    request_boundaries=tuple(mismatched_boundaries),
                )
        assert not failure
    finally:
        stop.set()
        thread.join(timeout=1)
        registry.close()


def test_phase_control_delayed_handler_never_extends_absolute_deadline(
    tmp_path: Path,
) -> None:
    """Transport delay cannot turn a caller-owned absolute deadline into now+D."""

    root = tmp_path / "phase-absolute-deadline"
    root.mkdir(mode=0o700)
    control = root / "phase-deadlines.jsonl"
    ack = root / "phase-acks.jsonl"
    worker_socket, watchdog_socket = socket.socketpair(
        socket.AF_UNIX, socket.SOCK_STREAM
    )
    base_ns = time.monotonic_ns()
    clock_ns = [base_ns]
    attempt_deadline_ns = base_ns + 10_000_000_000
    attempt_id = "phase-absolute-deadline"
    runtime = SimpleNamespace(monotonic_ns=lambda: clock_ns[0])
    registry = _PhaseControlRegistry(
        descriptor=watchdog_socket.detach(),
        root=root,
        control_path=control,
        ack_path=ack,
        attempt_id=attempt_id,
        attempt_nonce_sha256="a" * 64,
        scope_sha256="b" * 64,
        worker_pid=41002,
        worker_start_abstime=51002,
        worker_pgid=41002,
        worker_sid=41002,
        startup_timeout_ns=9_000_000_000,
        absolute_deadline_monotonic_ns=attempt_deadline_ns,
        runtime=runtime,
    )
    peer = FramedChannel(worker_socket)

    def advance_request(deadline_ns: int) -> dict[str, object]:
        fields: dict[str, object] = {
            "schema_id": "phase-latency-prewarm-phase-advance-v1",
            "attempt_id": attempt_id,
            "attempt_nonce_sha256": "a" * 64,
            "scope_sha256": "b" * 64,
            "worker_pid": 41002,
            "worker_start_abstime": 51002,
            "worker_pgid": 41002,
            "worker_sid": 41002,
            "phase": "request",
            "deadline_monotonic_ns": deadline_ns,
            "requested_sequence": registry.current_record.sequence + 1,
            "previous_phase_record_sha256": (
                registry.current_record.record_sha256
            ),
            "previous_phase_ack_sha256": registry.current_ack.record_sha256,
        }
        return {**fields, "request_sha256": canonical_sha256(fields)}

    try:
        registry.bound = True
        requested_deadline_ns = base_ns + 5_000_000_000
        delayed_request = advance_request(requested_deadline_ns)
        peer.send("phase_control_advance", delayed_request)

        # The frame was created against ``base_ns`` but is not serviced until
        # four seconds later. The durable deadline must remain the exact D on
        # the wire, not be recomputed from watchdog receive time.
        clock_ns[0] = base_ns + 4_000_000_000
        registry.service_available()
        _, response, body = peer.receive(
            expected_kind="phase_control_advance_ack"
        )
        assert body == b""
        assert response["phase_record"]["issued_monotonic_ns"] == clock_ns[0]
        assert (
            response["phase_record"]["deadline_monotonic_ns"]
            == requested_deadline_ns
        )

        records, before_invalid = read_phase_deadlines(
            root=root,
            path=control,
            attempt_id=attempt_id,
            whole_deadline_monotonic_ns=attempt_deadline_ns,
        )
        assert records[-1].deadline_monotonic_ns == requested_deadline_ns

        # A deadline that was valid when a caller considered sending it but is
        # late when received must fail without a durable append.
        clock_ns[0] = base_ns + 4_500_000_000
        peer.send(
            "phase_control_advance",
            advance_request(base_ns + 4_400_000_000),
        )
        with pytest.raises(
            BrokerProtocolError, match="deadline authority"
        ):
            registry.service_available()
        _, after_late = read_phase_deadlines(
            root=root,
            path=control,
            attempt_id=attempt_id,
            whole_deadline_monotonic_ns=attempt_deadline_ns,
            previous=before_invalid,
        )
        assert after_late == before_invalid

        peer.send(
            "phase_control_advance",
            advance_request(attempt_deadline_ns + 1),
        )
        with pytest.raises(
            BrokerProtocolError, match="deadline authority"
        ):
            registry.service_available()
        _, after_outside_attempt = read_phase_deadlines(
            root=root,
            path=control,
            attempt_id=attempt_id,
            whole_deadline_monotonic_ns=attempt_deadline_ns,
            previous=after_late,
        )
        assert after_outside_attempt == before_invalid

        # Later phases may legitimately receive a later absolute deadline; the
        # authority is the immutable attempt ceiling, not a nonincreasing rule.
        later_deadline_ns = base_ns + 8_000_000_000
        peer.send(
            "phase_control_advance", advance_request(later_deadline_ns)
        )
        registry.service_available()
        _, later_response, body = peer.receive(
            expected_kind="phase_control_advance_ack"
        )
        assert body == b""
        assert (
            later_response["phase_record"]["deadline_monotonic_ns"]
            == later_deadline_ns
        )

        peer.send("phase_control_advance", delayed_request)
        with pytest.raises(
            BrokerProtocolError, match="advance binding"
        ):
            registry.service_available()
        final_records, _ = read_phase_deadlines(
            root=root,
            path=control,
            attempt_id=attempt_id,
            whole_deadline_monotonic_ns=attempt_deadline_ns,
        )
        assert tuple(record.deadline_monotonic_ns for record in final_records[1:]) == (
            requested_deadline_ns,
            later_deadline_ns,
        )
    finally:
        peer.close()
        registry.close()


def _production_worker_required_argv(*, attempt_id: str) -> list[str]:
    return [
        "--workspace",
        "/private/tmp/lat-us02-worker",
        "--source",
        "/private/tmp/lat-us02-source.pdf",
        "--source-identity",
        "/private/tmp/lat-us02-source.json",
        "--configuration",
        "/private/tmp/lat-us02-configuration.json",
        "--mode",
        RunMode.ENABLED.value,
        "--application-sha256",
        "0" * 64,
        "--dependency-manifest-sha256",
        "1" * 64,
        "--dependency-runtime-sha256",
        "2" * 64,
        "--parser-runtime-sha256",
        "3" * 64,
        "--runtime-artifacts-sha256",
        "4" * 64,
        "--harness-sha256",
        "5" * 64,
        "--network-isolation-sha256",
        "6" * 64,
        "--attempt-id",
        attempt_id,
        "--controller-pid",
        "41001",
        "--controller-create-time-ns",
        "51001",
        "--controller-pgid",
        "41001",
        "--controller-sid",
        "41001",
        "--absolute-deadline-monotonic-ns",
        str(time.monotonic_ns() + 5_000_000_000),
        "--controller-release-fd",
        "19",
        "--prebind-fatal",
        "/private/tmp/lat-us02-prebind-fatal.json",
    ]


def test_supervisor_forwards_brokered_worker_argv_without_file_phase_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact supervisor target argv parses without legacy phase paths."""

    attempt_id = "supervisor-brokered-argv-smoke"
    worker_arguments = _production_worker_required_argv(attempt_id=attempt_id)
    transferred: dict[str, object] = {}

    class _TargetTransferred(RuntimeError):
        pass

    def transfer(
        module: str,
        arguments: tuple[str, ...],
        *,
        ready_fd: int,
    ) -> None:
        transferred.update(
            module=module,
            arguments=arguments,
            ready_fd=ready_fd,
        )
        raise _TargetTransferred

    monkeypatch.setenv("PARSER_LATENCY_PREWARM_ENABLED", "false")
    monkeypatch.setenv(
        parser_worker_supervisor.PRIVATE_PREDECESSOR_ENV,
        "false",
    )
    monkeypatch.setattr(parser_worker_supervisor, "_exec_exact_target", transfer)
    with pytest.raises(_TargetTransferred):
        parser_worker_supervisor.main(
            [
                "--ready-fd",
                "23",
                "--target-module",
                "tests.benchmarks.latency_prewarm_production_worker",
                "--",
                *worker_arguments,
            ]
        )

    assert transferred == {
        "module": "tests.benchmarks.latency_prewarm_production_worker",
        "arguments": tuple(worker_arguments),
        "ready_fd": 23,
    }
    parsed = production_worker._parser().parse_args(
        list(transferred["arguments"])
    )
    assert parsed.attempt_id == attempt_id
    assert parsed.phase_control is None
    assert parsed.phase_ack is None


def test_worker_phase_authority_selects_exactly_one_topology(
    tmp_path: Path,
) -> None:
    attempt_id = "worker-phase-authority"
    whole_deadline = time.monotonic_ns() + 5_000_000_000
    root = tmp_path / "direct-phase"
    root.mkdir(mode=0o700)
    control = root / "phase-control.jsonl"
    ack = root / "phase-ack.jsonl"
    for path in (control, ack):
        path.touch(mode=0o600)
        path.chmod(0o600)
    startup = append_phase_deadline(
        root=root,
        path=control,
        attempt_id=attempt_id,
        phase="startup",
        timeout_ns=4_000_000_000,
        whole_deadline_monotonic_ns=whole_deadline,
    )
    append_phase_ack(
        root=root,
        path=ack,
        attempt_id=attempt_id,
        phase_record=startup,
        clock=time.monotonic_ns,
    )
    direct_configuration = SimpleNamespace(
        measurement_kind="rollback_output_gate",
        execution_topology="direct-default-off-v1",
    )
    phase_client = production_worker._bind_worker_phase_authority(
        configuration=direct_configuration,
        phase_control_argument=str(control),
        phase_ack_argument=str(ack),
        attempt_id=attempt_id,
        absolute_deadline_monotonic_ns=whole_deadline,
    )
    assert isinstance(phase_client, production_worker._PhaseDeadlineClient)
    assert phase_client.latest == startup

    broker_attempt_id = "brokered-phase-authority"
    broker_deadline = time.monotonic_ns() + 5_000_000_000
    broker_record = SimpleNamespace(
        attempt_id=broker_attempt_id,
        phase="startup",
        sequence=1,
        record_sha256="7" * 64,
        deadline_monotonic_ns=broker_deadline - 1_000_000_000,
    )
    broker_ack = SimpleNamespace(
        sequence=1,
        phase_record_sha256=broker_record.record_sha256,
        observed_monotonic_ns=time.monotonic_ns(),
    )
    socket_authority = SimpleNamespace(
        attempt_id=broker_attempt_id,
        deadline_ns=broker_deadline,
        snapshot=lambda: SimpleNamespace(
            phase_record=broker_record,
            phase_ack=broker_ack,
        ),
    )
    broker_configuration = SimpleNamespace(
        measurement_kind="paired_case",
        execution_topology=(
            "fork-denied-worker-external-tesseract-broker-v1"
        ),
    )
    assert (
        production_worker._bind_worker_phase_authority(
            configuration=broker_configuration,
            phase_control_argument=None,
            phase_ack_argument=None,
            attempt_id=broker_attempt_id,
            absolute_deadline_monotonic_ns=broker_deadline,
            socket_resolver=lambda: socket_authority,
        )
        is None
    )


@pytest.mark.parametrize(
    ("measurement_kind", "topology", "control_present", "ack_present"),
    (
        ("rollback_output_gate", "direct-default-off-v1", False, False),
        ("rollback_output_gate", "direct-default-off-v1", True, False),
        ("rollback_output_gate", "direct-default-off-v1", False, True),
        (
            "paired_case",
            "fork-denied-worker-external-tesseract-broker-v1",
            True,
            True,
        ),
        (
            "paired_case",
            "fork-denied-worker-external-tesseract-broker-v1",
            True,
            False,
        ),
        ("paired_case", "direct-default-off-v1", False, False),
        (
            "rollback_output_gate",
            "fork-denied-worker-external-tesseract-broker-v1",
            True,
            True,
        ),
    ),
)
def test_worker_phase_authority_rejects_wrong_argument_topology_combinations(
    tmp_path: Path,
    measurement_kind: str,
    topology: str,
    control_present: bool,
    ack_present: bool,
) -> None:
    control = str(tmp_path / "control.jsonl") if control_present else None
    ack = str(tmp_path / "ack.jsonl") if ack_present else None
    with pytest.raises((ValueError, RuntimeError), match="phase authority"):
        production_worker._bind_worker_phase_authority(
            configuration=SimpleNamespace(
                measurement_kind=measurement_kind,
                execution_topology=topology,
            ),
            phase_control_argument=control,
            phase_ack_argument=ack,
            attempt_id="wrong-phase-authority",
            absolute_deadline_monotonic_ns=time.monotonic_ns()
            + 5_000_000_000,
            socket_resolver=lambda: None,
        )


@pytest.mark.skipif(
    sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file(),
    reason="real Seatbelt write-denial probe requires Darwin",
)
def test_worker_seatbelt_allows_only_exact_private_scratch(
    tmp_path: Path,
) -> None:
    root = tmp_path / "seatbelt-write-custody"
    root.mkdir(mode=0o700)
    artifact = root / "artifact"
    tessdata = root / "tessdata"
    request_root = root / "broker-request"
    scratch = request_root
    executable_root = root / "staged-executable"
    input_probe_root = root / "input-probe"
    network_trap_root = root / "network-traps"
    artifact_probe_clone_root = root / "artifact-probe-clone"
    tessdata_probe_clone_root = root / "tessdata-probe-clone"
    staged_executable_probe_clone_root = root / "staged-probe-clone"
    for directory in (
        artifact,
        tessdata,
        request_root,
        executable_root,
        input_probe_root,
        network_trap_root,
        artifact_probe_clone_root,
        tessdata_probe_clone_root,
        staged_executable_probe_clone_root,
    ):
        directory.mkdir(mode=0o700)
    executable = executable_root / "tesseract"
    executable.write_bytes(b"staged-executable")
    executable.chmod(0o500)
    child_watch = root / "attempt-child-watch.jsonl"
    terminal = root / "attempt-watchdog-terminal.json"
    child_watch.write_bytes(b"child-watch\n")
    terminal.write_bytes(b"terminal\n")
    child_watch.chmod(0o600)
    terminal.chmod(0o600)
    profile = production_runner._production_seatbelt_profile(
        artifact_root=artifact,
        tessdata_root=tessdata,
        request_root=request_root,
        input_probe_root=input_probe_root,
        network_trap_root=network_trap_root,
        artifact_probe_clone_root=artifact_probe_clone_root,
        tessdata_probe_clone_root=tessdata_probe_clone_root,
        staged_executable_probe_clone_root=(
            staged_executable_probe_clone_root
        ),
        worker_scratch_root=scratch,
        immutable_executable=executable,
        deny_process_fork=True,
    )
    script = textwrap.dedent(
        """
        import errno, os, pathlib, sys
        protected = [pathlib.Path(value) for value in sys.argv[1:3]]
        for path in protected:
            for operation in (
                lambda p=path: open(p, "ab").close(),
                lambda p=path: open(p, "wb").close(),
                lambda p=path: os.rename(p, str(p) + ".moved"),
                lambda p=path: os.unlink(p),
            ):
                try:
                    operation()
                except OSError as error:
                    if error.errno not in {errno.EPERM, errno.EACCES}:
                        raise
                else:
                    raise SystemExit(91)
        scratch = pathlib.Path(sys.argv[3])
        first = scratch / "positive.tmp"
        second = scratch / "positive.final"
        first.write_bytes(b"scratch-positive")
        os.rename(first, second)
        second.write_bytes(b"scratch-positive-final")
        """
    )
    completed = subprocess.run(
        (
            "/usr/bin/sandbox-exec",
            "-p",
            profile,
            sys.executable,
            "-I",
            "-c",
            script,
            str(child_watch),
            str(terminal),
            str(scratch),
        ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
        timeout=5,
        check=False,
    )
    if completed.returncode == 71 and b"sandbox_apply: Operation not permitted" in (
        completed.stderr
    ):
        pytest.skip("host sandbox forbids nested Seatbelt application")
    assert completed.returncode == 0, completed.stderr[:4096]
    assert child_watch.read_bytes() == b"child-watch\n"
    assert terminal.read_bytes() == b"terminal\n"
    assert (scratch / "positive.final").read_bytes() == b"scratch-positive-final"


def _native_child_config_projection_fixture(
    *, broker_pid: int,
) -> dict[str, Any]:
    previous_signal_mask: list[int] = []
    return {
        "schema_id": "parser-tesseract-native-child-config-projection-v1",
        "attempt_nonce_sha256": "3" * 64,
        "scope_sha256": "4" * 64,
        "request_id": "request-1",
        "request_epoch": 2,
        "request_sequence": 1,
        "spawn_sequence": 1,
        "spawn_nonce_sha256": "7" * 64,
        "broker_pid": broker_pid,
        "broker_start_abstime": 52_001,
        "broker_pgid": broker_pid,
        "broker_sid": broker_pid,
        "config_fd": 10,
        "native_state_fd": 11,
        "ready_fd": 12,
        "release_fd": 13,
        "stdin_fd": 14,
        "stdout_fd": 15,
        "stderr_fd": 16,
        "executable": "/frozen/tesseract",
        "expected_executable_sha256": "1" * 64,
        "expected_executable_device": 1,
        "expected_executable_inode": 2,
        "argv": ["/frozen/tesseract", "--version"],
        "environment": {
            "LANG": "C",
            "LC_ALL": "C",
            "OMP_THREAD_LIMIT": "1",
            "TESSDATA_PREFIX": "/frozen/tessdata",
        },
        "native_spawn_guard_sha256": "2" * 64,
        "previous_signal_mask": previous_signal_mask,
        "previous_signal_mask_sha256": canonical_sha256(
            {"signal_mask": previous_signal_mask}
        ),
        "runtime_gate_library": "/frozen/runtime-gate.dylib",
        "runtime_gate_library_sha256": "5" * 64,
        "runtime_gate_library_device": 3,
        "runtime_gate_library_inode": 4,
        "runtime_gate_nonce_sha256": hashlib.sha256(b"n" * 32).hexdigest(),
        "guard_python_path": "/frozen/root-owned-python3",
        "guard_python_sha256": "f" * 64,
        "guard_python_device": 5,
        "guard_python_inode": 6,
        "guard_python_path_custody_sha256": "1" * 64,
        "guard_python_native_closure_sha256": "2" * 64,
        "guard_python_module_tree_root": "/frozen/root-owned-python-modules",
        "guard_python_module_tree_sha256": "3" * 64,
        "guard_wrapper_sha256": "4" * 64,
        "guard_wrapper_delivery_basis": (
            "execve-python-c-embedded-source-v1"
        ),
        "guard_exec_argv_sha256": "5" * 64,
        "guard_exec_environment_sha256": "6" * 64,
        "native_child_config_sha256": "d" * 64,
    }


def _actual_exec_environment_projection_fixture(
    child_projection: dict[str, Any],
) -> dict[str, Any]:
    logical_environment = child_projection["environment"]
    return {
        "schema_id": "parser-tesseract-actual-exec-environment-v1",
        "logical_environment": logical_environment,
        "logical_environment_sha256": canonical_sha256(
            logical_environment
        ),
        "runtime_gate_library_path": child_projection[
            "runtime_gate_library"
        ],
        "runtime_gate_library_sha256": child_projection[
            "runtime_gate_library_sha256"
        ],
        "runtime_gate_fd": 3,
        "runtime_gate_nonce_sha256": child_projection[
            "runtime_gate_nonce_sha256"
        ],
        "exact_exec_environment_keys": sorted(
            (
                *logical_environment,
                "DYLD_INSERT_LIBRARIES",
                "PARSER_TESSERACT_RUNTIME_GATE_FD",
                "PARSER_TESSERACT_RUNTIME_GATE_NONCE",
            )
        ),
        "dyld_search_or_fallback_environment_absent": True,
    }


def _child_watch_native_ack_registration_fixture(
    root: Path,
) -> tuple[_ChildWatchRegistry, FramedChannel, dict[str, Any]]:
    root.mkdir(mode=0o700)
    broker_socket, watchdog_socket = socket.socketpair(
        socket.AF_UNIX, socket.SOCK_STREAM
    )
    broker_pid = 42_001
    child_pid = 43_001
    child_identity = SimpleNamespace(
        pid=child_pid,
        start_abstime=53_001,
        ppid=broker_pid,
        pgid=broker_pid,
        sid=broker_pid,
    )
    deadline = time.monotonic_ns() + 5_000_000_000
    registry = _ChildWatchRegistry(
        descriptor=watchdog_socket.detach(),
        log_path=root / "audit.jsonl",
        attempt_nonce_sha256="3" * 64,
        scope_sha256="4" * 64,
        watchdog_protocol_sha256="5" * 64,
        native_closure_sha256="6" * 64,
        broker_pid=broker_pid,
        broker_start_abstime=52_001,
        broker_ppid=os.getpid(),
        broker_pgid=broker_pid,
        broker_sid=broker_pid,
        absolute_deadline_monotonic_ns=deadline,
        runtime=SimpleNamespace(
            monotonic_ns=time.monotonic_ns,
            kernel_process_identity=lambda pid: (
                child_identity
                if pid == child_pid
                else (_ for _ in ()).throw(ProcessLookupError(pid))
            ),
        ),
    )
    peer = FramedChannel(broker_socket)
    open_fields = {
        "attempt_nonce_sha256": "3" * 64,
        "scope_sha256": "4" * 64,
        "maximum_bytes": 4_194_304,
        "maximum_record_blob_bytes": MAX_BROKER_AUDIT_BLOB_BYTES,
        "compact_commitment_bytes": BROKER_AUDIT_COMMITMENT_BYTES,
        "watchdog_protocol_sha256": "5" * 64,
    }
    peer.send(
        "broker_audit_open",
        {**open_fields, "record_sha256": canonical_sha256(open_fields)},
    )
    registry.service_available()
    peer.receive(expected_kind="broker_audit_open_ack")

    anchor = time.monotonic_ns() - 1_000_000
    child_projection = _native_child_config_projection_fixture(
        broker_pid=broker_pid
    )
    actual_environment_projection = (
        _actual_exec_environment_projection_fixture(child_projection)
    )
    intent = {
        "schema_id": "parser-tesseract-spawn-intent-v1",
        "request_id": "request-1",
        "request_epoch": 2,
        "request_sequence": 1,
        "spawn_sequence": 1,
        "spawn_nonce_sha256": "7" * 64,
        "runtime_gate_nonce_sha256": child_projection[
            "runtime_gate_nonce_sha256"
        ],
        "native_runtime_gate_record_sha256": "a" * 64,
        "logical_environment_sha256": canonical_sha256(
            child_projection["environment"]
        ),
        "actual_environment_projection_sha256": canonical_sha256(
            actual_environment_projection
        ),
        "native_child_config_sha256": child_projection[
            "native_child_config_sha256"
        ],
        "native_child_config_projection_sha256": canonical_sha256(
            child_projection
        ),
        "guard_python_sha256": child_projection["guard_python_sha256"],
        "guard_python_path_custody_sha256": child_projection[
            "guard_python_path_custody_sha256"
        ],
        "guard_python_native_closure_sha256": child_projection[
            "guard_python_native_closure_sha256"
        ],
        "guard_python_module_tree_sha256": child_projection[
            "guard_python_module_tree_sha256"
        ],
        "guard_wrapper_sha256": child_projection[
            "guard_wrapper_sha256"
        ],
        "guard_wrapper_delivery_basis": (
            "execve-python-c-embedded-source-v1"
        ),
        "guard_exec_argv_sha256": child_projection[
            "guard_exec_argv_sha256"
        ],
        "guard_exec_environment_sha256": child_projection[
            "guard_exec_environment_sha256"
        ],
        "broker_pid": broker_pid,
        "broker_start_abstime": 52_001,
        "broker_pgid": broker_pid,
        "broker_sid": broker_pid,
        "child_deadline_monotonic_ns": deadline - 1,
        "broker_thread_count_before_fork": 1,
        "broker_thread_inventory_sha256": "8" * 64,
        "broker_thread_observed_at_monotonic_ns": anchor,
        "intent_created_monotonic_ns": anchor + 100_000,
    }
    intent["spawn_intent_sha256"] = canonical_sha256(intent)

    def append_broker_row(
        *,
        sequence: int,
        previous: str,
        kind: str,
        record: dict[str, Any],
    ) -> str:
        fields = broker_audit_row_mapping(
            row_sequence=sequence,
            previous_row_sha256=previous,
            kind=kind,
            record=record,
        )
        row_sha256 = fields["row_sha256"]
        peer.send(
            "broker_audit_append",
            fields,
        )
        registry.service_available()
        peer.receive(expected_kind="broker_audit_append_ack")
        return row_sha256

    spawn_row_sha256 = append_broker_row(
        sequence=1,
        previous="0" * 64,
        kind="spawn_intent",
        record=intent,
    )
    blockable_signals = sorted(
        int(item)
        for item in signal.valid_signals()
        if int(item) not in {int(signal.SIGKILL), int(signal.SIGSTOP)}
    )
    applied_ns = 123_456_789
    native_ack_sha256 = native_child_limit_ack_sha256(
        pid=child_pid,
        applied_monotonic_ns=applied_ns,
    )
    provisional = {
        "schema_id": "parser-tesseract-child-provisional-v1",
        "request_id": "request-1",
        "request_epoch": 2,
        "request_sequence": 1,
        "spawn_sequence": 1,
        "spawn_nonce_sha256": "7" * 64,
        "pid": child_identity.pid,
        "start_abstime": child_identity.start_abstime,
        "ppid": child_identity.ppid,
        "pgid": child_identity.pgid,
        "sid": child_identity.sid,
        "spawn_intent_sha256": intent["spawn_intent_sha256"],
        "spawn_intent_ledger_row_sha256": spawn_row_sha256,
        "broker_thread_count_immediately_before_fork": 1,
        "broker_thread_inventory_immediately_before_fork_sha256": "8" * 64,
        "broker_thread_immediately_before_fork_observed_at_monotonic_ns": (
            anchor + 200_000
        ),
        "born_monotonic_ns": anchor + 250_000,
        "blocked_signals_across_fork": blockable_signals,
        "blocked_signals_across_fork_sha256": canonical_sha256(
            {"blocked_signals": blockable_signals}
        ),
        "blockable_signals_masked_across_fork": True,
        "native_child_limit_ack_authority": NATIVE_CHILD_LIMIT_ACK_AUTHORITY,
        "native_child_limit_applied_clock_authority": (
            NATIVE_CHILD_LIMIT_APPLIED_CLOCK_AUTHORITY
        ),
        "native_child_limit_ack_pid": child_pid,
        "native_child_limit_applied_monotonic_ns": applied_ns,
        "native_child_limit_ack_sha256": native_ack_sha256,
        "native_fork_parent_returned_monotonic_ns": anchor + 300_000,
        "native_child_limit_acknowledged_monotonic_ns": anchor + 400_000,
        "provisional_observed_monotonic_ns": anchor + 500_000,
    }
    provisional["provisional_record_sha256"] = canonical_sha256(provisional)
    provisional_row_sha256 = append_broker_row(
        sequence=2,
        previous=spawn_row_sha256,
        kind="child_provisional",
        record=provisional,
    )
    registration = {
        "attempt_nonce_sha256": "3" * 64,
        "scope_sha256": "4" * 64,
        "request_id": "request-1",
        "request_epoch": 2,
        "request_sequence": 1,
        "spawn_sequence": 1,
        "spawn_nonce_sha256": "7" * 64,
        "pid": child_identity.pid,
        "start_abstime": child_identity.start_abstime,
        "ppid": child_identity.ppid,
        "pgid": child_identity.pgid,
        "sid": child_identity.sid,
        "child_deadline_monotonic_ns": deadline - 1,
        "provisional_child_ledger_row_sha256": provisional_row_sha256,
        "spawn_intent_sha256": intent["spawn_intent_sha256"],
        "spawn_intent_ledger_row_sha256": spawn_row_sha256,
        "native_child_limit_ack_authority": NATIVE_CHILD_LIMIT_ACK_AUTHORITY,
        "native_child_limit_applied_clock_authority": (
            NATIVE_CHILD_LIMIT_APPLIED_CLOCK_AUTHORITY
        ),
        "native_child_limit_ack_pid": child_pid,
        "native_child_limit_applied_monotonic_ns": applied_ns,
        "native_child_limit_ack_sha256": native_ack_sha256,
        "native_fork_parent_returned_monotonic_ns": anchor + 300_000,
        "native_child_limit_acknowledged_monotonic_ns": anchor + 400_000,
    }
    registration["registration_sha256"] = canonical_sha256(registration)
    return registry, peer, registration


def test_child_watch_registration_echoes_native_nproc_ack_exactly(
    tmp_path: Path,
) -> None:
    registry, peer, registration = _child_watch_native_ack_registration_fixture(
        tmp_path / "native-nproc-register"
    )
    try:
        peer.send("child_watch_register", registration)
        registry.service_available()
        _, ack, body = peer.receive(
            expected_kind="child_watch_register_ack"
        )
        assert body == b""
        assert isinstance(ack, dict)
        ack_sha256 = ack.pop("watchdog_record_sha256")
        watchdog_observed_ns = ack.pop("watchdog_observed_monotonic_ns")
        echoed_names = {
            "request_id",
            "request_epoch",
            "request_sequence",
            "spawn_sequence",
            "spawn_nonce_sha256",
            "pid",
            "start_abstime",
            "ppid",
            "pgid",
            "sid",
            "registration_sha256",
            "spawn_intent_sha256",
            "spawn_intent_ledger_row_sha256",
            "provisional_child_ledger_row_sha256",
            "native_child_limit_ack_authority",
            "native_child_limit_applied_clock_authority",
            "native_child_limit_ack_pid",
            "native_child_limit_applied_monotonic_ns",
            "native_child_limit_ack_sha256",
            "native_fork_parent_returned_monotonic_ns",
            "native_child_limit_acknowledged_monotonic_ns",
        }
        assert set(ack) == echoed_names
        assert ack == {name: registration[name] for name in echoed_names}
        joined_provisional = registry.audit_joins[
            registration["registration_sha256"]
        ]["provisional"]
        assert watchdog_observed_ns >= joined_provisional[
            "provisional_observed_monotonic_ns"
        ]
        assert ack_sha256 == canonical_sha256(
            {**ack, "watchdog_observed_monotonic_ns": watchdog_observed_ns}
        )
    finally:
        peer.close()
        registry.close()


def test_child_watch_cleanup_never_signals_a_numeric_child_pid(
    tmp_path: Path,
) -> None:
    registry, peer, registration = _child_watch_native_ack_registration_fixture(
        tmp_path / "child-watch-no-numeric-kill"
    )
    numeric_kill_attempts: list[tuple[int, int]] = []
    try:
        peer.send("child_watch_register", registration)
        registry.service_available()
        peer.receive(expected_kind="child_watch_register_ack")
        registry.runtime.kill_process = (
            lambda pid, signum: numeric_kill_attempts.append((pid, signum))
        )
        registry.record_broker_group_signal(signal.SIGTERM)
        registry.runtime.kernel_process_identity = lambda pid: SimpleNamespace(
            pid=registration["pid"],
            start_abstime=registration["start_abstime"] + 1,
            ppid=registration["ppid"],
            pgid=registration["pgid"],
            sid=registration["sid"],
        )
        registry.record_broker_group_signal(signal.SIGKILL)
        assert numeric_kill_attempts == []
        assert registry.any_sigterm_attempted is True
        assert registry.any_sigkill_attempted is False
        assert registry.all_disappearance_confirmed is False
        child = next(iter(registry.open.values()))
        assert child.sigterm_attempted is True
        assert child.sigkill_attempted is False
    finally:
        peer.close()
        registry.close()


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("native_child_limit_ack_authority", "wrong-native-authority"),
        ("native_child_limit_applied_clock_authority", "wrong-clock"),
        ("native_child_limit_ack_pid", 43_002),
        ("native_child_limit_applied_monotonic_ns", 123_456_790),
        ("native_child_limit_ack_sha256", "f" * 64),
        ("native_fork_parent_returned_monotonic_ns", 1),
        ("native_child_limit_acknowledged_monotonic_ns", 1),
    ),
)
def test_child_watch_registration_rejects_native_nproc_ack_drift(
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    registry, peer, registration = _child_watch_native_ack_registration_fixture(
        tmp_path / field
    )
    try:
        mutated = {**registration, field: replacement}
        mutated["registration_sha256"] = canonical_sha256(
            {
                key: value
                for key, value in mutated.items()
                if key != "registration_sha256"
            }
        )
        peer.send("child_watch_register", mutated)
        with pytest.raises(BrokerProtocolError, match="NPROC ACK|registration"):
            registry.service_available()
    finally:
        peer.close()
        registry.close()


def _send_child_watch_frame_while_servicing(
    registry: _ChildWatchRegistry,
    peer: FramedChannel,
    *,
    kind: str,
    payload: dict[str, Any],
) -> None:
    """Drive both socketpair endpoints when a closed frame exceeds SO_SNDBUF."""
    send_errors: list[BaseException] = []

    def _send() -> None:
        try:
            peer.send(kind, payload)
        except BaseException as error:  # pragma: no cover - assertion path
            send_errors.append(error)

    sender = threading.Thread(target=_send, daemon=True)
    sender.start()
    assert select.select([registry.fileno], [], [], 5)[0]
    registry.service_available()
    sender.join(timeout=5)
    assert not sender.is_alive()
    if send_errors:
        raise send_errors[0]


def _append_child_watch_audit_row(
    registry: _ChildWatchRegistry,
    peer: FramedChannel,
    *,
    kind: str,
    record: dict[str, Any],
) -> str:
    fields = broker_audit_row_mapping(
        row_sequence=registry.ledger.row_sequence + 1,
        previous_row_sha256=registry.ledger.head_sha256,
        kind=kind,
        record=record,
    )
    row_sha256 = fields["row_sha256"]
    _send_child_watch_frame_while_servicing(
        registry,
        peer,
        kind="broker_audit_append",
        payload=fields,
    )
    peer.receive(expected_kind="broker_audit_append_ack")
    return row_sha256


def test_child_watch_v2_uses_compact_chain_and_o_excl_record_blobs(
    tmp_path: Path,
) -> None:
    root = tmp_path / "compact-child-watch"
    root.mkdir(mode=0o700)
    ledger = _ChildWatchLedger(root / "audit.bin")
    try:
        record = {"request_id": "q0001", "phase": "begin"}
        row = broker_audit_row_mapping(
            row_sequence=1,
            previous_row_sha256="0" * 64,
            kind="quiescence",
            record=record,
        )
        blob = ledger.append_broker_row(row)

        assert ledger.size_bytes == BROKER_AUDIT_COMMITMENT_BYTES
        assert (root / "audit.bin").read_bytes() == bytes.fromhex(
            row["compact_commitment_hex"]
        )
        blob_path = Path(blob["resolved_path"])
        assert blob_path.read_bytes() == canonical_json_bytes(record)
        assert stat.S_IMODE(blob_path.stat().st_mode) == 0o600
        assert ledger.record_blob_count == 1
        assert ledger.record_blob_size_bytes == len(canonical_json_bytes(record))
        with pytest.raises(FileExistsError):
            descriptor = os.open(
                blob_path.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=ledger.record_blob_root_fd,
            )
            os.close(descriptor)

        prior_main_size = ledger.size_bytes
        ledger.append_watch_event(
            kind="child_watch_register",
            frame_sha256="a" * 64,
            payload={"registration_sha256": "b" * 64},
            observed_monotonic_ns=time.monotonic_ns(),
        )
        assert ledger.size_bytes == prior_main_size
        assert ledger.event_sequence == 1
        assert len(tuple((root / "audit.bin.events").iterdir())) == 1
    finally:
        ledger.close()


def test_durable_ledger_and_watchdog_v2_open_append_roundtrip(
    tmp_path: Path,
) -> None:
    root = tmp_path / "durable-ledger-v2"
    root.mkdir(mode=0o700)
    broker_socket, watchdog_socket = socket.socketpair()
    registry = _ChildWatchRegistry(
        descriptor=watchdog_socket.detach(),
        log_path=root / "audit.bin",
        attempt_nonce_sha256=hashlib.sha256(("f" * 64).encode("ascii")).hexdigest(),
        scope_sha256="e" * 64,
        watchdog_protocol_sha256="5" * 64,
        native_closure_sha256="6" * 64,
        broker_pid=42_001,
        broker_start_abstime=52_001,
        broker_ppid=os.getpid(),
        broker_pgid=42_001,
        broker_sid=42_001,
        absolute_deadline_monotonic_ns=time.monotonic_ns() + 5_000_000_000,
        runtime=SimpleNamespace(monotonic_ns=time.monotonic_ns),
    )
    channel = FramedChannel(broker_socket)
    config = SimpleNamespace(
        attempt_nonce="f" * 64,
        scope_sha256="e" * 64,
        watchdog_protocol_sha256="5" * 64,
    )
    created: list[DurableLedger] = []
    errors: list[BaseException] = []

    def create_ledger() -> None:
        try:
            created.append(DurableLedger(channel, config))
        except BaseException as error:
            errors.append(error)

    creator = threading.Thread(target=create_ledger, daemon=True)
    creator.start()
    assert select.select([registry.fileno], [], [], 5)[0]
    registry.service_available()
    creator.join(5)
    assert not creator.is_alive()
    assert not errors
    ledger = created[0]
    assert ledger.record_blob_root["entry_count"] == 0

    row_results: list[str] = []
    appender = threading.Thread(
        target=lambda: row_results.append(
            ledger.append("quiescence", {"phase": "begin"})
        ),
        daemon=True,
    )
    appender.start()
    assert select.select([registry.fileno], [], [], 5)[0]
    registry.service_available()
    appender.join(5)
    assert not appender.is_alive()
    assert row_results == [ledger.head_sha256]
    assert ledger.size_bytes == BROKER_AUDIT_COMMITMENT_BYTES
    assert ledger.record_blob_count == 1
    assert ledger.record_blob_size_bytes == len(
        canonical_json_bytes({"phase": "begin"})
    )
    assert registry.ledger.head_sha256 == ledger.head_sha256
    assert registry.ledger.record_blob_head_sha256 == (
        ledger.record_blob_head_sha256
    )
    channel.close()
    registry.close()


def _child_birth_commitment_fixture(
    *,
    registry: _ChildWatchRegistry,
    registration: dict[str, Any],
) -> dict[str, Any]:
    registration_sha256 = registration["registration_sha256"]
    join = registry.audit_joins[registration_sha256]
    provisional = join["provisional"]
    spawn_intent = join["spawn_intent"]
    if registry.pending_intent is None:
        child_ready_sha256 = "9" * 64
        child_ready_intent_row_sha256 = "a" * 64
        join["registration_ack_row_sha256"] = "b" * 64
        join["child_ready_sha256"] = child_ready_sha256
        join["child_ready_intent_row_sha256"] = (
            child_ready_intent_row_sha256
        )
        registry.pending_intent = {
            "request_id": registration["request_id"],
            "request_epoch": registration["request_epoch"],
            "request_sequence": registration["request_sequence"],
            "spawn_sequence": registration["spawn_sequence"],
            "spawn_nonce_sha256": registration["spawn_nonce_sha256"],
            "pid": registration["pid"],
            "start_abstime": registration["start_abstime"],
            "child_ready_sha256": child_ready_sha256,
            "spawn_intent_sha256": registration["spawn_intent_sha256"],
            "spawn_intent_ledger_row_sha256": registration[
                "spawn_intent_ledger_row_sha256"
            ],
            "provisional_child_ledger_row_sha256": registration[
                "provisional_child_ledger_row_sha256"
            ],
            "provisional_record_sha256": provisional[
                "provisional_record_sha256"
            ],
            "watchdog_registration_sha256": registration_sha256,
            "watchdog_registration_ack_sha256": join[
                "registration_ack_sha256"
            ],
            "row_sha256": child_ready_intent_row_sha256,
        }
    else:
        child_ready_sha256 = registry.pending_intent[
            "child_ready_sha256"
        ]
        child_ready_intent_row_sha256 = registry.pending_intent[
            "row_sha256"
        ]
    descriptors = [
        {
            "fd": fd,
            "kernel_fd_type": kernel_type,
            "role": role,
            "close_on_exec": close_on_exec,
            "stat_device": 1,
            "stat_inode": 60_000 + fd,
            "stat_mode": (
                (stat.S_IFREG | 0o500)
                if fd == 5
                else (stat.S_IFIFO | 0o600)
            ),
            "stat_mode_type": stat.S_IFREG if fd == 5 else stat.S_IFIFO,
        }
        for fd, kernel_type, role, close_on_exec in (
            (0, 6, "stdin_pipe", False),
            (1, 6, "stdout_pipe", False),
            (2, 6, "stderr_pipe", False),
            (3, 6, "ready_pipe", True),
            (4, 6, "release_pipe", True),
            (5, 1, "staged_executable", True),
        )
    ]
    thread_ids = [70_001]
    prior_signal_mask: list[int] = []
    child_projection = _native_child_config_projection_fixture(
        broker_pid=registration["ppid"]
    )
    registration_observed_ns = join[
        "registration_acknowledged_monotonic_ns"
    ]
    fields: dict[str, Any] = {
        "schema_id": "parser-tesseract-child-birth-commitment-v1",
        "request_id": registration["request_id"],
        "request_epoch": registration["request_epoch"],
        "request_sequence": registration["request_sequence"],
        "spawn_sequence": registration["spawn_sequence"],
        "spawn_nonce_sha256": registration["spawn_nonce_sha256"],
        "pid": registration["pid"],
        "start_abstime": registration["start_abstime"],
        "ppid": registration["ppid"],
        "pgid": registration["pgid"],
        "sid": registration["sid"],
        "broker_pid": registration["ppid"],
        "broker_start_abstime": 52_001,
        "operation": "version",
        "logical_argv_sha256": "c" * 64,
        "actual_argv_sha256": canonical_sha256(
            {"argv": child_projection["argv"]}
        ),
        "logical_environment_sha256": canonical_sha256(
            child_projection["environment"]
        ),
        "actual_environment_projection_sha256": spawn_intent[
            "actual_environment_projection_sha256"
        ],
        "input_sha256": "f" * 64,
        "input_bytes": 0,
        "executable_sha256": "1" * 64,
        "native_closure_sha256": "6" * 64,
        "native_trust_model": "frozen-native-closure-trusted-v1",
        "native_containment_claim": (
            "none-trusted-pinned-native-computation"
        ),
        "native_runtime_attestation_required": True,
        "native_runtime_scan_interval_ns": 100_000_000,
        "native_runtime_gate_authority": (
            "dyld-inserted-frozen-constructor-self-sigstop-before-main-v1"
        ),
        "native_runtime_gate_initializer_order_limitation": (
            "before-main-not-before-every-trusted-dependency-initializer-v1"
        ),
        "native_runtime_gate_source_sha256": "4" * 64,
        "native_runtime_gate_library_sha256": child_projection[
            "runtime_gate_library_sha256"
        ],
        "native_runtime_gate_record_sha256": spawn_intent[
            "native_runtime_gate_record_sha256"
        ],
        "runtime_gate_nonce_sha256": child_projection[
            "runtime_gate_nonce_sha256"
        ],
        "runtime_gate_ack_authority": (
            "native-fixed-binary-pipe-RTGATE1-big-endian-v1"
        ),
        "watchdog_registration_sha256": registration_sha256,
        "watchdog_registration_ack_sha256": join[
            "registration_ack_sha256"
        ],
        "broker_thread_count_before_fork": 1,
        "broker_thread_inventory_sha256": spawn_intent[
            "broker_thread_inventory_sha256"
        ],
        "broker_thread_observed_at_monotonic_ns": spawn_intent[
            "broker_thread_observed_at_monotonic_ns"
        ],
        "broker_thread_count_immediately_before_fork": provisional[
            "broker_thread_count_immediately_before_fork"
        ],
        "broker_thread_inventory_immediately_before_fork_sha256": provisional[
            "broker_thread_inventory_immediately_before_fork_sha256"
        ],
        "broker_thread_immediately_before_fork_observed_at_monotonic_ns": provisional[
            "broker_thread_immediately_before_fork_observed_at_monotonic_ns"
        ],
        "born_monotonic_ns": provisional["born_monotonic_ns"],
        "blocked_signals_across_fork": provisional[
            "blocked_signals_across_fork"
        ],
        "blocked_signals_across_fork_sha256": provisional[
            "blocked_signals_across_fork_sha256"
        ],
        "blockable_signals_masked_across_fork": True,
        "registration_acknowledged_monotonic_ns": registration_observed_ns,
        "guard_release_a_monotonic_ns": registration_observed_ns + 300,
        "spawn_intent_sha256": registration["spawn_intent_sha256"],
        "spawn_intent_ledger_row_sha256": registration[
            "spawn_intent_ledger_row_sha256"
        ],
        "spawn_intent_durable_acknowledged_monotonic_ns": spawn_intent[
            "intent_created_monotonic_ns"
        ],
        "provisional_record_sha256": provisional[
            "provisional_record_sha256"
        ],
        "provisional_child_ledger_row_sha256": registration[
            "provisional_child_ledger_row_sha256"
        ],
        "provisional_observed_monotonic_ns": provisional[
            "provisional_observed_monotonic_ns"
        ],
        "child_ready_sha256": child_ready_sha256,
        "child_ready_intent_ledger_row_sha256": (
            child_ready_intent_row_sha256
        ),
        "open_fd_count": len(descriptors),
        "open_file_descriptors": descriptors,
        "open_fd_inventory_sha256": canonical_sha256(
            {"open_file_descriptors": descriptors}
        ),
        "native_thread_count": len(thread_ids),
        "native_thread_ids": thread_ids,
        "native_thread_inventory_sha256": canonical_sha256(
            {"native_thread_ids": thread_ids}
        ),
        "native_spawn_guard_sha256": "2" * 64,
        "native_spawn_guard_source_sha256": "3" * 64,
        "native_spawn_guard_kind": (
            "darwin-__fork-child-nproc0-before-python-v1"
        ),
        "guard_python_sha256": child_projection["guard_python_sha256"],
        "guard_python_path_custody_sha256": child_projection[
            "guard_python_path_custody_sha256"
        ],
        "guard_python_native_closure_sha256": child_projection[
            "guard_python_native_closure_sha256"
        ],
        "guard_python_module_tree_sha256": child_projection[
            "guard_python_module_tree_sha256"
        ],
        "guard_python_path_exec_trust_model": (
            "root-owned-pinned-clt-python-native-closure-v1"
        ),
        "guard_python_path_exec_containment_claim": (
            "none-trusted-host-path-exec"
        ),
        "guard_wrapper_delivery_basis": child_projection[
            "guard_wrapper_delivery_basis"
        ],
        "guard_config_fd": child_projection["config_fd"],
        "guard_ready_fd": child_projection["ready_fd"],
        "guard_exec_argv_sha256": child_projection[
            "guard_exec_argv_sha256"
        ],
        "guard_exec_environment_sha256": child_projection[
            "guard_exec_environment_sha256"
        ],
        "guard_post_exec_environment_sha256": "8" * 64,
        "native_child_config_sha256": child_projection[
            "native_child_config_sha256"
        ],
        "native_child_config_projection": child_projection,
        "native_child_config_projection_sha256": canonical_sha256(
            child_projection
        ),
        "native_child_limit_applied_monotonic_ns": registration[
            "native_child_limit_applied_monotonic_ns"
        ],
        "native_child_limit_applied_clock_authority": registration[
            "native_child_limit_applied_clock_authority"
        ],
        "native_child_limit_ack_authority": registration[
            "native_child_limit_ack_authority"
        ],
        "native_child_limit_ack_pid": registration[
            "native_child_limit_ack_pid"
        ],
        "native_child_limit_ack_sha256": registration[
            "native_child_limit_ack_sha256"
        ],
        "native_fork_parent_returned_monotonic_ns": registration[
            "native_fork_parent_returned_monotonic_ns"
        ],
        "native_child_limit_acknowledged_monotonic_ns": registration[
            "native_child_limit_acknowledged_monotonic_ns"
        ],
        "native_python_release_n_monotonic_ns": registration_observed_ns + 100,
        "child_guard_applied_at_monotonic_ns": 100,
        "child_guard_applied_clock_authority": (
            "clt-python39-time-monotonic-clock-monotonic-v1"
        ),
        "child_reported_guard_release_a_monotonic_ns": 200,
        "child_guard_release_a_record_sha256": canonical_sha256(
            {
                "schema_id": "parser-tesseract-child-release-v1",
                "pid": registration["pid"],
                "released_monotonic_ns": 200,
                "ready_record_sha256": child_ready_sha256,
            }
        ),
        "child_guard_ready_observed_monotonic_ns": (
            registration_observed_ns + 200
        ),
        "hard_limit_installed_before_python_return": True,
        "pthread_atfork_callbacks_bypassed": True,
        "prior_signal_mask": prior_signal_mask,
        "prior_signal_mask_sha256": canonical_sha256(
            {"signal_mask": prior_signal_mask}
        ),
        "restored_signal_mask": prior_signal_mask,
        "restored_signal_mask_sha256": canonical_sha256(
            {"signal_mask": prior_signal_mask}
        ),
        "exact_prior_signal_mask_restored_before_ready": True,
    }
    fields["birth_commitment_sha256"] = canonical_sha256(fields)
    return fields


def test_child_birth_commitment_retains_full_native_spawn_authority(
    tmp_path: Path,
) -> None:
    registry, peer, registration = _child_watch_native_ack_registration_fixture(
        tmp_path / "native-birth-commitment"
    )
    try:
        peer.send("child_watch_register", registration)
        registry.service_available()
        peer.receive(expected_kind="child_watch_register_ack")
        commitment = _child_birth_commitment_fixture(
            registry=registry,
            registration=registration,
        )
        registry._validate_child_birth_row(commitment, "4" * 64)
        assert registry.pending_birth is not None
        assert set(registry.pending_birth) == {
            *commitment,
            "row_sha256",
            "registration_sha256",
        }
        for name in (
            "native_spawn_guard_sha256",
            "native_spawn_guard_source_sha256",
            "native_spawn_guard_kind",
            "native_child_limit_applied_monotonic_ns",
            "native_child_limit_applied_clock_authority",
            "native_child_limit_ack_authority",
            "native_child_limit_ack_pid",
            "native_child_limit_ack_sha256",
            "native_fork_parent_returned_monotonic_ns",
            "native_child_limit_acknowledged_monotonic_ns",
            "native_python_release_n_monotonic_ns",
            "child_guard_applied_at_monotonic_ns",
            "hard_limit_installed_before_python_return",
            "pthread_atfork_callbacks_bypassed",
            "prior_signal_mask",
            "prior_signal_mask_sha256",
            "restored_signal_mask",
            "restored_signal_mask_sha256",
            "exact_prior_signal_mask_restored_before_ready",
        ):
            assert registry.pending_birth[name] == commitment[name]
    finally:
        peer.close()
        registry.close()


def test_child_birth_commitment_rejects_registration_nproc_rebinding(
    tmp_path: Path,
) -> None:
    registry, peer, registration = _child_watch_native_ack_registration_fixture(
        tmp_path / "native-birth-rebinding"
    )
    try:
        peer.send("child_watch_register", registration)
        registry.service_available()
        peer.receive(expected_kind="child_watch_register_ack")
        commitment = _child_birth_commitment_fixture(
            registry=registry,
            registration=registration,
        )
        changed_applied_ns = (
            commitment["native_child_limit_applied_monotonic_ns"] + 1
        )
        commitment["native_child_limit_applied_monotonic_ns"] = (
            changed_applied_ns
        )
        commitment["native_child_limit_ack_sha256"] = (
            native_child_limit_ack_sha256(
                pid=commitment["pid"],
                applied_monotonic_ns=changed_applied_ns,
            )
        )
        commitment["birth_commitment_sha256"] = canonical_sha256(
            {
                key: value
                for key, value in commitment.items()
                if key != "birth_commitment_sha256"
            }
        )
        with pytest.raises(BrokerProtocolError, match="commitment join"):
            registry._validate_child_birth_row(commitment, "4" * 64)
    finally:
        peer.close()
        registry.close()


def _runtime_gate_tombstone_fixture(
    *,
    commitment: dict[str, Any],
    exec_release_e_monotonic_ns: int,
    runtime_gate_row_sha256: str,
) -> tuple[dict[str, Any], AppBrokerChildWait4Tombstone]:
    process = AppKernelProcessIdentity(
        pid=commitment["pid"],
        start_abstime=commitment["start_abstime"],
        ppid=commitment["ppid"],
        pgid=commitment["pgid"],
        sid=commitment["sid"],
    )
    tick = exec_release_e_monotonic_ns
    thread_fields = {
        "schema_id": "darwin-detailed-thread-inventory-v1",
        "process": asdict(process),
        "identity_basis": (
            "darwin-proc_pidinfo-PROC_PIDLISTTHREADS-uint64-v1"
        ),
        "thread_ids": [80_001],
        "thread_count": 1,
    }
    stopped_threads = AppNativeThreadInventory(
        schema_id=thread_fields["schema_id"],
        process=process,
        identity_basis=thread_fields["identity_basis"],
        first_scan_started_monotonic_ns=tick + 5,
        first_scan_completed_monotonic_ns=tick + 6,
        second_scan_started_monotonic_ns=tick + 7,
        second_scan_completed_monotonic_ns=tick + 8,
        thread_ids=(80_001,),
        thread_count=1,
        inventory_sha256=canonical_sha256(thread_fields),
    )
    descriptors: list[AppNativeFileDescriptorIdentity] = []
    for fd in (0, 1, 2):
        pipe = AppNativePipeFileDescriptorIdentity(
            device=1,
            inode=90_000 + fd,
            mode=stat.S_IFIFO | 0o600,
            nlink=1,
            uid=501,
            gid=20,
            pipe_status=0,
            local_handle_sha256=_sha(f"runtime-pipe-local-{fd}"),
            peer_handle_sha256=_sha(f"runtime-pipe-peer-{fd}"),
        )
        descriptor_fields = {
            "fd": fd,
            "kernel_type": 6,
            "open_flags": 0,
            "kernel_status_flags": 0,
            "descriptor_offset": 0,
            "descriptor_type": 6,
            "guard_flags": 0,
            "close_on_exec": False,
            "close_on_fork": False,
            "guarded": False,
            "shared": False,
            "vnode": None,
            "socket": None,
            "pipe": asdict(pipe),
            "kqueue": None,
        }
        descriptors.append(
            AppNativeFileDescriptorIdentity(
                **{
                    key: value
                    for key, value in descriptor_fields.items()
                    if key != "pipe"
                },
                pipe=pipe,
                record_sha256=canonical_sha256(descriptor_fields),
            )
        )
    descriptor_digest = {
        "schema_id": "darwin-detailed-file-descriptor-inventory-v1",
        "process": asdict(process),
        "descriptors": [asdict(item) for item in descriptors],
    }
    stopped_descriptors = AppNativeFileDescriptorInventory(
        schema_id=descriptor_digest["schema_id"],
        process=process,
        first_scan_started_monotonic_ns=tick + 5,
        first_scan_completed_monotonic_ns=tick + 6,
        second_scan_started_monotonic_ns=tick + 7,
        second_scan_completed_monotonic_ns=tick + 8,
        descriptors=tuple(descriptors),
        inventory_sha256=canonical_sha256(descriptor_digest),
    )
    stopped_thread_mapping = json.loads(json.dumps(asdict(stopped_threads)))
    stopped_descriptor_mapping = json.loads(
        json.dumps(asdict(stopped_descriptors))
    )
    runtime_nonce = b"n" * 32
    runtime_ack_c_ns = 123_456_789
    raw_ack = struct.pack(
        "!8sQQ32s",
        b"RTGATE1!",
        commitment["pid"],
        runtime_ack_c_ns,
        runtime_nonce,
    )
    raw_ack_sha256 = hashlib.sha256(raw_ack).hexdigest()

    system_cache_sha256 = _sha("runtime-system-cache")
    non_system_projection_sha256 = _sha("runtime-non-system-projection")
    region = {
        "address": 4096,
        "size": 4096,
        "file_offset": 0,
        "protection": 5,
        "maximum_protection": 5,
        "user_tag": 0,
        "object_id": 0,
        "resolved_path": "/frozen/tesseract",
        "device": 1,
        "inode": 2,
        "mode": stat.S_IFREG | 0o500,
        "uid": 501,
        "gid": 20,
        "nlink": 1,
        "file_size": 1,
        "mtime_ns": 1,
        "ctime_ns": 1,
        "vnode_type": stat.S_IFREG,
    }
    image_fields = {
        "resolved_path": "/frozen/tesseract",
        "device": 1,
        "inode": 2,
        "mode": stat.S_IFREG | 0o500,
        "uid": 501,
        "gid": 20,
        "nlink": 1,
        "size": 1,
        "mtime_ns": 1,
        "ctime_ns": 1,
        "system_image": False,
        "closure_image_sha256": commitment["executable_sha256"],
        "executable_regions": [region],
        "executable_region_count": 1,
    }
    image = {
        **image_fields,
        "record_sha256": canonical_sha256(image_fields),
    }
    raw_inventory_sha256 = canonical_sha256(
        {"process": asdict(process), "regions": [region]}
    )

    def full_scan(start: int) -> dict[str, Any]:
        fields = {
            "schema_id": "parser-tesseract-native-runtime-scan-v1",
            "authority": "darwin-libproc-executable-regions-v1",
            "process": asdict(process),
            "native_closure_sha256": commitment[
                "native_closure_sha256"
            ],
            "system_cache_sha256": system_cache_sha256,
            "staged_executable_sha256": commitment["executable_sha256"],
            "staged_executable_device": 1,
            "staged_executable_inode": 2,
            "staged_executable_content_stable": True,
            "bracket_started_monotonic_ns": start,
            "kernel_scan_started_monotonic_ns": start + 1,
            "kernel_scan_completed_monotonic_ns": start + 2,
            "bracket_completed_monotonic_ns": start + 3,
            "total_region_count": 1,
            "executable_region_count": 1,
            "mapped_image_count": 1,
            "mapped_images": [image],
            "expected_non_system_image_count": 1,
            "expected_non_system_projection_sha256": (
                non_system_projection_sha256
            ),
            "observed_non_system_image_count": 1,
            "observed_non_system_projection_sha256": (
                non_system_projection_sha256
            ),
            "raw_kernel_inventory_sha256": raw_inventory_sha256,
            "all_non_system_images_in_frozen_closure": True,
            "sealed_system_images_bound_to_cache": True,
        }
        return {**fields, "record_sha256": canonical_sha256(fields)}

    scans = (full_scan(tick + 10), full_scan(tick + 14))
    samples: list[AppNativeRuntimeScanSample] = []
    for sequence, scan in enumerate(scans, 1):
        sample_fields = {
            "scan_sequence": sequence,
            "bracket_started_monotonic_ns": scan[
                "bracket_started_monotonic_ns"
            ],
            "kernel_scan_started_monotonic_ns": scan[
                "kernel_scan_started_monotonic_ns"
            ],
            "kernel_scan_completed_monotonic_ns": scan[
                "kernel_scan_completed_monotonic_ns"
            ],
            "bracket_completed_monotonic_ns": scan[
                "bracket_completed_monotonic_ns"
            ],
            "total_region_count": scan["total_region_count"],
            "raw_kernel_inventory_sha256": scan[
                "raw_kernel_inventory_sha256"
            ],
            "full_scan_record_sha256": scan["record_sha256"],
        }
        samples.append(
            AppNativeRuntimeScanSample(
                **sample_fields,
                record_sha256=canonical_sha256(sample_fields),
            )
        )
    transition = {
        "schema_id": "parser-tesseract-runtime-gate-transition-v1",
        "pid": commitment["pid"],
        "start_abstime": commitment["start_abstime"],
        "native_runtime_gate_authority": commitment[
            "native_runtime_gate_authority"
        ],
        "native_runtime_gate_initializer_order_limitation": commitment[
            "native_runtime_gate_initializer_order_limitation"
        ],
        "native_runtime_gate_source_sha256": commitment[
            "native_runtime_gate_source_sha256"
        ],
        "native_runtime_gate_library_sha256": commitment[
            "native_runtime_gate_library_sha256"
        ],
        "native_runtime_gate_record_sha256": commitment[
            "native_runtime_gate_record_sha256"
        ],
        "runtime_gate_nonce_sha256": commitment[
            "runtime_gate_nonce_sha256"
        ],
        "runtime_gate_ack_authority": NATIVE_RUNTIME_GATE_ACK_AUTHORITY,
        "runtime_gate_ack_c_clock_authority": (
            NATIVE_RUNTIME_GATE_C_CLOCK_AUTHORITY
        ),
        "runtime_gate_ack_pid": commitment["pid"],
        "runtime_gate_ack_c_monotonic_ns": runtime_ack_c_ns,
        "runtime_gate_raw_ack_hex": raw_ack.hex(),
        "runtime_gate_raw_ack_sha256": raw_ack_sha256,
        "runtime_gate_ack_sha256": native_runtime_gate_ack_sha256(
            pid=commitment["pid"],
            observed_c_monotonic_ns=runtime_ack_c_ns,
            nonce_sha256=commitment["runtime_gate_nonce_sha256"],
        ),
        "exec_release_e_monotonic_ns": exec_release_e_monotonic_ns,
        "runtime_gate_ack_observed_monotonic_ns": tick + 1,
        "runtime_gate_fd_eof_observed_monotonic_ns": tick + 2,
        "same_pid_exec_observed_monotonic_ns": tick + 3,
        "constructor_stop_observed_monotonic_ns": tick + 4,
        "pre_exec_ready_fd": 3,
        "pre_exec_ready_fd_close_on_exec": True,
        "runtime_gate_fd": 3,
        "runtime_gate_fd_inheritable_for_exec": True,
        "runtime_gate_fd_closed_before_continue": True,
        "stopped_thread_inventory": stopped_thread_mapping,
        "stopped_file_descriptor_inventory": stopped_descriptor_mapping,
        "first_stopped_scan_sha256": scans[0]["record_sha256"],
        "second_stopped_scan_sha256": scans[1]["record_sha256"],
    }
    transition["record_sha256"] = canonical_sha256(transition)
    actual_environment = _actual_exec_environment_projection_fixture(
        commitment["native_child_config_projection"]
    )
    attestation_fields = {
        "schema_id": "parser-tesseract-native-runtime-attestation-v1",
        "authority": "darwin-libproc-executable-regions-v1",
        "operation": commitment["operation"],
        "operation_family_sha256": _sha("runtime-operation-family"),
        "logical_environment_sha256": commitment[
            "logical_environment_sha256"
        ],
        "actual_environment_projection": actual_environment,
        "actual_environment_projection_sha256": canonical_sha256(
            actual_environment
        ),
        "native_closure_sha256": commitment["native_closure_sha256"],
        "expected_non_system_image_count": 1,
        "expected_non_system_projection_sha256": (
            non_system_projection_sha256
        ),
        "observed_non_system_image_count": 1,
        "observed_non_system_projection_sha256": (
            non_system_projection_sha256
        ),
        "system_cache_sha256": system_cache_sha256,
        "dynamic_loader_imports_sha256": _sha("runtime-dlopen-imports"),
        "dynamic_loader_importing_image_count": 0,
        "native_trust_model": "frozen-native-closure-trusted-v1",
        "native_containment_claim": "none-trusted-pinned-native-computation",
        "polling_completeness": (
            "bounded-100ms-not-event-complete-trusted-pinned-code-v1"
        ),
        "scan_interval_limit_ns": 100_000_000,
        "native_runtime_gate_authority": transition[
            "native_runtime_gate_authority"
        ],
        "native_runtime_gate_initializer_order_limitation": transition[
            "native_runtime_gate_initializer_order_limitation"
        ],
        "native_runtime_gate_source_sha256": transition[
            "native_runtime_gate_source_sha256"
        ],
        "native_runtime_gate_library_sha256": transition[
            "native_runtime_gate_library_sha256"
        ],
        "native_runtime_gate_record_sha256": transition[
            "native_runtime_gate_record_sha256"
        ],
        "runtime_gate_nonce_sha256": transition[
            "runtime_gate_nonce_sha256"
        ],
        "runtime_gate_ack_authority": transition[
            "runtime_gate_ack_authority"
        ],
        "runtime_gate_ack_c_clock_authority": transition[
            "runtime_gate_ack_c_clock_authority"
        ],
        "runtime_gate_ack_pid": commitment["pid"],
        "runtime_gate_ack_c_monotonic_ns": runtime_ack_c_ns,
        "runtime_gate_raw_ack_hex": raw_ack.hex(),
        "runtime_gate_raw_ack_sha256": raw_ack_sha256,
        "runtime_gate_ack_sha256": transition[
            "runtime_gate_ack_sha256"
        ],
        "exec_release_e_monotonic_ns": exec_release_e_monotonic_ns,
        "runtime_gate_ack_observed_monotonic_ns": tick + 1,
        "runtime_gate_fd_eof_observed_monotonic_ns": tick + 2,
        "same_pid_exec_observed_monotonic_ns": tick + 3,
        "constructor_stop_observed_monotonic_ns": tick + 4,
        "stopped_signal_number": signal.SIGSTOP,
        "stopped_thread_inventory": stopped_thread_mapping,
        "stopped_file_descriptor_inventory": stopped_descriptor_mapping,
        "runtime_gate_transition_sha256": transition["record_sha256"],
        "runtime_gate_transition_ledger_row_sha256": (
            runtime_gate_row_sha256
        ),
        "guard_to_exec_transition_sha256": _sha(
            "guard-to-exec-transition"
        ),
        "continued_signal_sent_monotonic_ns": tick + 18,
        "continued_observed_monotonic_ns": tick + 19,
        "actual_child_stop_gated": True,
        "initial_scan": scans[0],
        "scan_samples": [asdict(item) for item in samples],
        "scan_count": 2,
        "stopped_scan_count": 2,
        "post_continue_scan_count": 0,
        "fast_terminal_after_gate": True,
        "scan_log_sha256": canonical_sha256(
            {"scan_samples": [asdict(item) for item in samples]}
        ),
        "first_scan_started_monotonic_ns": tick + 10,
        "double_stable_completed_monotonic_ns": tick + 17,
        "first_input_write_monotonic_ns": 0,
        "last_scan_completed_monotonic_ns": tick + 17,
        "terminal_waitid_code": os.CLD_EXITED,
        "terminal_waitid_status": 0,
        "terminal_nonreaping_observed_monotonic_ns": tick + 20,
        "maximum_scan_gap_ns": 1,
        "all_scans_same_inventory": True,
        "instrumentation_through_terminal": True,
        "static_closure_revalidated_after_wait4": True,
        "static_closure_post_wait4_sha256": commitment[
            "native_closure_sha256"
        ],
        "transient_dlopen_polling_gap_disclosed": True,
    }
    attestation_mapping = {
        **attestation_fields,
        "record_sha256": canonical_sha256(attestation_fields),
    }
    attestation = AppNativeRuntimeImageAttestation(
        **{
            **attestation_mapping,
            "scan_samples": tuple(samples),
        }
    )
    final_birth_sha256 = _sha("final-child-birth")
    tombstone_fields = {
        "request_id": commitment["request_id"],
        "request_epoch": commitment["request_epoch"],
        "request_sequence": commitment["request_sequence"],
        "spawn_sequence": commitment["spawn_sequence"],
        "spawn_nonce_sha256": commitment["spawn_nonce_sha256"],
        "record_sequence": 2,
        "previous_record_sha256": final_birth_sha256,
        "birth_record_sha256": final_birth_sha256,
        "pid": commitment["pid"],
        "start_abstime": commitment["start_abstime"],
        "raw_wait_status": 0,
        "exited": True,
        "exit_code": 0,
        "signaled": False,
        "signal_number": None,
        "core_dumped": False,
        "rusage": asdict(
            AppRawRUsage(
                user=AppRawTimeval(0, 1, 1_000),
                system=AppRawTimeval(0, 1, 1_000),
            )
        ),
        "stdout_bytes": 0,
        "stdout_retained_bytes": 0,
        "stdout_sha256": hashlib.sha256(b"").hexdigest(),
        "stdout_disposition": "captured",
        "stderr_bytes": 0,
        "stderr_retained_bytes": 0,
        "stderr_sha256": hashlib.sha256(b"").hexdigest(),
        "stderr_disposition": "captured",
        "overflowed": False,
        "observed_monotonic_ns": tick + 21,
        "maximum_resident_set_size_bytes": 1,
        "minor_faults": 0,
        "major_faults": 0,
        "voluntary_context_switches": 0,
        "involuntary_context_switches": 0,
        "nonreaping_wait4_probe_count": 1,
        "terminal_wait4_reap_count": 1,
        "direct_parent_waited": True,
        "native_runtime_attestation": asdict(attestation),
    }
    tombstone_mapping = {
        **tombstone_fields,
        "record_sha256": canonical_sha256(tombstone_fields),
    }
    tombstone = AppBrokerChildWait4Tombstone(
        **{
            **tombstone_mapping,
            "rusage": AppRawRUsage(
                user=AppRawTimeval(0, 1, 1_000),
                system=AppRawTimeval(0, 1, 1_000),
            ),
            "native_runtime_attestation": attestation,
        }
    )
    return transition, tombstone


def test_runtime_gate_tombstone_fixture_is_closed_and_replayable(
    tmp_path: Path,
) -> None:
    registry, peer, registration = _child_watch_native_ack_registration_fixture(
        tmp_path / "native-runtime-gate-fixture"
    )
    try:
        peer.send("child_watch_register", registration)
        registry.service_available()
        peer.receive(expected_kind="child_watch_register_ack")
        commitment = _child_birth_commitment_fixture(
            registry=registry,
            registration=registration,
        )
        registry._validate_child_birth_row(commitment, "4" * 64)
        transition, tombstone = _runtime_gate_tombstone_fixture(
            commitment=commitment,
            exec_release_e_monotonic_ns=(
                commitment["guard_release_a_monotonic_ns"] + 1
            ),
            runtime_gate_row_sha256="5" * 64,
        )
        assert native_runtime_gate_transition_from_mapping(transition) == transition
        wire_tombstone = json.loads(json.dumps(asdict(tombstone)))
        assert child_tombstone_from_mapping(wire_tombstone) == tombstone
    finally:
        peer.close()
        registry.close()


def test_child_watch_full_birth_runtime_gate_and_reap_transcript(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, peer, registration = _child_watch_native_ack_registration_fixture(
        tmp_path / "native-runtime-gate-transcript"
    )
    try:
        peer.send("child_watch_register", registration)
        registry.service_available()
        _, register_ack, body = peer.receive(
            expected_kind="child_watch_register_ack"
        )
        assert body == b""
        assert isinstance(register_ack, dict)
        _append_child_watch_audit_row(
            registry,
            peer,
            kind="watchdog_register_ack",
            record=register_ack,
        )

        join = registry.audit_joins[registration["registration_sha256"]]
        child_ready_sha256 = _sha("transcript-child-ready")
        child_intent = {
            "request_id": registration["request_id"],
            "request_epoch": registration["request_epoch"],
            "request_sequence": registration["request_sequence"],
            "spawn_sequence": registration["spawn_sequence"],
            "spawn_nonce_sha256": registration["spawn_nonce_sha256"],
            "pid": registration["pid"],
            "start_abstime": registration["start_abstime"],
            "child_ready_sha256": child_ready_sha256,
            "spawn_intent_sha256": registration["spawn_intent_sha256"],
            "spawn_intent_ledger_row_sha256": registration[
                "spawn_intent_ledger_row_sha256"
            ],
            "provisional_child_ledger_row_sha256": registration[
                "provisional_child_ledger_row_sha256"
            ],
            "provisional_record_sha256": join[
                "provisional_record_sha256"
            ],
            "watchdog_registration_sha256": registration[
                "registration_sha256"
            ],
            "watchdog_registration_ack_sha256": register_ack[
                "watchdog_record_sha256"
            ],
        }
        _append_child_watch_audit_row(
            registry,
            peer,
            kind="child_intent",
            record=child_intent,
        )
        commitment = _child_birth_commitment_fixture(
            registry=registry,
            registration=registration,
        )
        birth_row_sha256 = _append_child_watch_audit_row(
            registry,
            peer,
            kind="child_birth",
            record=commitment,
        )

        reported_fd_inventory = tuple(
            (item["fd"], item["kernel_fd_type"])
            for item in commitment["open_file_descriptors"]
        )
        reported_thread_ids = tuple(commitment["native_thread_ids"])
        from app.services import tesseract_broker_native as native_module
        from tests.benchmarks import latency_prewarm_cpu as cpu_module

        monkeypatch.setattr(
            native_module,
            "native_file_descriptor_inventory",
            lambda _pid: reported_fd_inventory,
        )
        monkeypatch.setattr(
            native_module,
            "native_thread_inventory",
            lambda _pid: reported_thread_ids,
        )
        monkeypatch.setattr(
            cpu_module,
            "sample_darwin_process_self_cpu",
            lambda **_kwargs: SimpleNamespace(
                pid=registration["pid"],
                start_abstime=registration["start_abstime"],
                parent_pid=registration["ppid"],
                process_group_id=registration["pgid"],
                session_id=registration["sid"],
                observed_monotonic_ns=time.monotonic_ns(),
                user_cpu_ns=1,
                system_cpu_ns=1,
            ),
        )

        class _FakeChildProcess:
            def __init__(self, pid: int) -> None:
                assert pid == registration["pid"]

            def __enter__(self) -> _FakeChildProcess:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def oneshot(self) -> _FakeChildProcess:
                return self

            @staticmethod
            def memory_info() -> SimpleNamespace:
                return SimpleNamespace(rss=1)

            @staticmethod
            def num_threads() -> int:
                return 1

            @staticmethod
            def num_fds() -> int:
                return 6

        monkeypatch.setattr(psutil, "Process", _FakeChildProcess)
        birth_record = child_watch_birth_from_commitment(
            commitment,
            birth_ledger_row_sha256=birth_row_sha256,
        )
        birth_payload = {
            **birth_record,
            "watch_birth_sha256": canonical_sha256(birth_record),
        }
        _send_child_watch_frame_while_servicing(
            registry,
            peer,
            kind="child_watch_birth",
            payload=birth_payload,
        )
        _, birth_ack, body = peer.receive(
            expected_kind="child_watch_birth_ack"
        )
        assert body == b""
        assert isinstance(birth_ack, dict)
        _append_child_watch_audit_row(
            registry,
            peer,
            kind="watchdog_birth_ack",
            record=birth_ack,
        )

        exec_release_e = max(
            commitment["guard_release_a_monotonic_ns"],
            birth_ack["watchdog_observed_monotonic_ns"],
        ) + 1
        exec_release = {
            "request_id": registration["request_id"],
            "request_epoch": registration["request_epoch"],
            "request_sequence": registration["request_sequence"],
            "spawn_sequence": registration["spawn_sequence"],
            "spawn_nonce_sha256": registration["spawn_nonce_sha256"],
            "pid": registration["pid"],
            "start_abstime": registration["start_abstime"],
            "birth_commitment_sha256": commitment[
                "birth_commitment_sha256"
            ],
            "watchdog_birth_ack_sha256": birth_ack[
                "watchdog_record_sha256"
            ],
            "exec_release_e_monotonic_ns": exec_release_e,
        }
        _append_child_watch_audit_row(
            registry,
            peer,
            kind="child_exec_release",
            record=exec_release,
        )
        transition, _ = _runtime_gate_tombstone_fixture(
            commitment=commitment,
            exec_release_e_monotonic_ns=exec_release_e,
            runtime_gate_row_sha256="5" * 64,
        )
        runtime_gate_row_sha256 = _append_child_watch_audit_row(
            registry,
            peer,
            kind="child_runtime_gate",
            record=transition,
        )
        replayed_transition, tombstone = _runtime_gate_tombstone_fixture(
            commitment=commitment,
            exec_release_e_monotonic_ns=exec_release_e,
            runtime_gate_row_sha256=runtime_gate_row_sha256,
        )
        assert replayed_transition == transition
        wire_tombstone = json.loads(json.dumps(asdict(tombstone)))
        tombstone_row_sha256 = _append_child_watch_audit_row(
            registry,
            peer,
            kind="child_wait4",
            record=wire_tombstone,
        )

        registry.runtime.kernel_process_identity = (
            lambda pid: (_ for _ in ()).throw(ProcessLookupError(pid))
        )
        attestation = wire_tombstone["native_runtime_attestation"]
        reaped = {
            "request_id": registration["request_id"],
            "request_epoch": registration["request_epoch"],
            "request_sequence": registration["request_sequence"],
            "spawn_sequence": registration["spawn_sequence"],
            "spawn_nonce_sha256": registration["spawn_nonce_sha256"],
            "pid": registration["pid"],
            "start_abstime": registration["start_abstime"],
            "registration_sha256": registration["registration_sha256"],
            "birth_record_sha256": commitment[
                "birth_commitment_sha256"
            ],
            "tombstone_record_sha256": tombstone.record_sha256,
            "raw_wait_status": tombstone.raw_wait_status,
            "wait4_observed_monotonic_ns": tombstone.observed_monotonic_ns,
            "tombstone_ledger_row_sha256": tombstone_row_sha256,
            "native_runtime_attestation_sha256": attestation[
                "record_sha256"
            ],
            "native_runtime_scan_log_sha256": attestation[
                "scan_log_sha256"
            ],
            "guard_to_exec_transition_sha256": attestation[
                "guard_to_exec_transition_sha256"
            ],
            "native_closure_post_wait4_sha256": attestation[
                "static_closure_post_wait4_sha256"
            ],
        }
        reaped["reaped_record_sha256"] = canonical_sha256(reaped)
        _send_child_watch_frame_while_servicing(
            registry,
            peer,
            kind="child_watch_reaped",
            payload=reaped,
        )
        _, reaped_ack, body = peer.receive(
            expected_kind="child_watch_reaped_ack"
        )
        assert body == b""
        assert isinstance(reaped_ack, dict)
        _append_child_watch_audit_row(
            registry,
            peer,
            kind="watchdog_reaped_ack",
            record=reaped_ack,
        )
        final_join = registry.audit_joins[registration["registration_sha256"]]
        assert final_join["runtime_gate_row_sha256"] == runtime_gate_row_sha256
        assert final_join["wait4_row_sha256"] == tombstone_row_sha256
        assert final_join["reaped_ack_row_sha256"] == registry.ledger.head_sha256
        assert registry.open == {}
        assert registry.registered_count == registry.reaped_count == 1
    finally:
        peer.close()
        registry.close()


def test_child_watch_rejects_unconsumed_intent_before_next_audit_row(
    tmp_path: Path,
) -> None:
    root = tmp_path / "child-watch-join"
    root.mkdir(mode=0o700)
    broker_socket, watchdog_socket = socket.socketpair(
        socket.AF_UNIX, socket.SOCK_STREAM
    )
    deadline = time.monotonic_ns() + 5_000_000_000
    registry = _ChildWatchRegistry(
        descriptor=watchdog_socket.detach(),
        log_path=root / "audit.jsonl",
        attempt_nonce_sha256="3" * 64,
        scope_sha256="4" * 64,
        watchdog_protocol_sha256="5" * 64,
        native_closure_sha256="6" * 64,
        broker_pid=42001,
        broker_start_abstime=52001,
        broker_ppid=os.getpid(),
        broker_pgid=42001,
        broker_sid=42001,
        absolute_deadline_monotonic_ns=deadline,
        runtime=SimpleNamespace(monotonic_ns=time.monotonic_ns),
    )
    peer = FramedChannel(broker_socket)
    try:
        open_fields = {
            "attempt_nonce_sha256": "3" * 64,
            "scope_sha256": "4" * 64,
            "maximum_bytes": 4_194_304,
            "maximum_record_blob_bytes": MAX_BROKER_AUDIT_BLOB_BYTES,
            "compact_commitment_bytes": BROKER_AUDIT_COMMITMENT_BYTES,
            "watchdog_protocol_sha256": "5" * 64,
        }
        peer.send(
            "broker_audit_open",
            {**open_fields, "record_sha256": canonical_sha256(open_fields)},
        )
        registry.service_available()
        peer.receive(expected_kind="broker_audit_open_ack")
        intent_created = time.monotonic_ns()
        intent = {
            "schema_id": "parser-tesseract-spawn-intent-v1",
            "request_id": "request-1",
            "request_epoch": 2,
            "request_sequence": 1,
            "spawn_sequence": 1,
            "spawn_nonce_sha256": "6" * 64,
            "runtime_gate_nonce_sha256": "8" * 64,
            "native_runtime_gate_record_sha256": "9" * 64,
            "logical_environment_sha256": "a" * 64,
            "actual_environment_projection_sha256": "b" * 64,
            "native_child_config_sha256": "c" * 64,
            "native_child_config_projection_sha256": "d" * 64,
            "guard_python_sha256": "e" * 64,
            "guard_python_path_custody_sha256": "f" * 64,
            "guard_python_native_closure_sha256": "1" * 64,
            "guard_python_module_tree_sha256": "2" * 64,
            "guard_wrapper_sha256": "3" * 64,
            "guard_wrapper_delivery_basis": (
                "execve-python-c-embedded-source-v1"
            ),
            "guard_exec_argv_sha256": "4" * 64,
            "guard_exec_environment_sha256": "5" * 64,
            "broker_pid": 42001,
            "broker_start_abstime": 52001,
            "broker_pgid": 42001,
            "broker_sid": 42001,
            "child_deadline_monotonic_ns": deadline - 1,
            "broker_thread_count_before_fork": 1,
            "broker_thread_inventory_sha256": "7" * 64,
            "broker_thread_observed_at_monotonic_ns": intent_created - 1,
            "intent_created_monotonic_ns": intent_created,
        }
        intent["spawn_intent_sha256"] = canonical_sha256(intent)
        row = broker_audit_row_mapping(
            row_sequence=1,
            previous_row_sha256="0" * 64,
            kind="spawn_intent",
            record=intent,
        )
        row_sha = row["row_sha256"]
        peer.send("broker_audit_append", row)
        registry.service_available()
        peer.receive(expected_kind="broker_audit_append_ack")
        skipped = broker_audit_row_mapping(
            row_sequence=2,
            previous_row_sha256=row_sha,
            kind="quiescence",
            record={},
        )
        peer.send(
            "broker_audit_append",
            skipped,
        )
        with pytest.raises(
            BrokerProtocolError,
            match="row kind/order differs",
        ):
            registry.service_available()
    finally:
        peer.close()
        registry.close()


def test_child_watch_terminal_close_binds_hard_fork_denial_and_eof(
    tmp_path: Path,
) -> None:
    root = tmp_path / "child-watch-terminal-close"
    root.mkdir(mode=0o700)
    broker_socket, watchdog_socket = socket.socketpair(
        socket.AF_UNIX, socket.SOCK_STREAM
    )
    broker_identity = {
        "pid": 42011,
        "start_abstime": 52011,
        "ppid": os.getpid(),
        "pgid": 42011,
        "sid": 42011,
    }
    deadline = time.monotonic_ns() + 5_000_000_000
    runtime = SimpleNamespace(
        monotonic_ns=time.monotonic_ns,
        kernel_process_identity=lambda _pid: SimpleNamespace(**broker_identity),
        native_thread_inventory=lambda _pid: (9001,),
    )
    registry = _ChildWatchRegistry(
        descriptor=watchdog_socket.detach(),
        log_path=root / "audit.jsonl",
        attempt_nonce_sha256="3" * 64,
        scope_sha256="4" * 64,
        watchdog_protocol_sha256="5" * 64,
        native_closure_sha256="6" * 64,
        broker_pid=broker_identity["pid"],
        broker_start_abstime=broker_identity["start_abstime"],
        broker_ppid=broker_identity["ppid"],
        broker_pgid=broker_identity["pgid"],
        broker_sid=broker_identity["sid"],
        absolute_deadline_monotonic_ns=deadline,
        runtime=runtime,
    )
    peer = FramedChannel(broker_socket)
    try:
        open_fields = {
            "attempt_nonce_sha256": "3" * 64,
            "scope_sha256": "4" * 64,
            "maximum_bytes": 4_194_304,
            "maximum_record_blob_bytes": MAX_BROKER_AUDIT_BLOB_BYTES,
            "compact_commitment_bytes": BROKER_AUDIT_COMMITMENT_BYTES,
            "watchdog_protocol_sha256": "5" * 64,
        }
        peer.send(
            "broker_audit_open",
            {**open_fields, "record_sha256": canonical_sha256(open_fields)},
        )
        registry.service_available()
        peer.receive(expected_kind="broker_audit_open_ack")
        close_fields = {
            "row_sequence": 0,
            "head_sha256": "0" * 64,
            "size_bytes": 0,
            "record_blob_count": 0,
            "record_blob_size_bytes": 0,
            "record_blob_head_sha256": "0" * 64,
            "broker": broker_identity,
            "broker_thread_count": 1,
            "broker_thread_inventory_sha256": canonical_sha256(
                {
                    "schema_id": "parser-tesseract-broker-thread-inventory-v1",
                    "broker_pid": broker_identity["pid"],
                    "broker_start_abstime": broker_identity["start_abstime"],
                    "thread_ids": [9001],
                }
            ),
            "broker_thread_observed_at_monotonic_ns": time.monotonic_ns(),
            "rlimit_nproc_soft": 0,
            "rlimit_nproc_hard": 0,
            "terminal_fork_denial_applied_at_monotonic_ns": time.monotonic_ns(),
            "terminal_no_fork": True,
        }
        peer.send(
            "broker_audit_close",
            {**close_fields, "record_sha256": canonical_sha256(close_fields)},
        )
        registry.service_available()
        _, ack, body = peer.receive(expected_kind="broker_audit_close_ack")
        assert body == b""
        assert isinstance(ack, dict)
        ack_digest = ack.pop("watchdog_record_sha256")
        assert ack_digest == canonical_sha256(ack)
        assert ack["broker"] == broker_identity
        assert (ack["rlimit_nproc_soft"], ack["rlimit_nproc_hard"]) == (0, 0)
        assert ack["terminal_no_fork"] is True
        peer.close()
        registry.service_available()
        assert registry.audit_closed
        assert registry.channel_eof
        assert registry.terminal_snapshot()["child_watch_channel_eof"] is True
    finally:
        peer.close()
        registry.close()


def test_child_watch_terminal_close_rejects_nonzero_nproc(
    tmp_path: Path,
) -> None:
    root = tmp_path / "child-watch-terminal-close-invalid"
    root.mkdir(mode=0o700)
    broker_socket, watchdog_socket = socket.socketpair(
        socket.AF_UNIX, socket.SOCK_STREAM
    )
    broker_identity = {
        "pid": 42012,
        "start_abstime": 52012,
        "ppid": os.getpid(),
        "pgid": 42012,
        "sid": 42012,
    }
    registry = _ChildWatchRegistry(
        descriptor=watchdog_socket.detach(),
        log_path=root / "audit.jsonl",
        attempt_nonce_sha256="6" * 64,
        scope_sha256="7" * 64,
        watchdog_protocol_sha256="8" * 64,
        native_closure_sha256="9" * 64,
        broker_pid=broker_identity["pid"],
        broker_start_abstime=broker_identity["start_abstime"],
        broker_ppid=broker_identity["ppid"],
        broker_pgid=broker_identity["pgid"],
        broker_sid=broker_identity["sid"],
        absolute_deadline_monotonic_ns=time.monotonic_ns() + 5_000_000_000,
        runtime=SimpleNamespace(
            monotonic_ns=time.monotonic_ns,
            kernel_process_identity=lambda _pid: SimpleNamespace(
                **broker_identity
            ),
            native_thread_inventory=lambda _pid: (9002,),
        ),
    )
    peer = FramedChannel(broker_socket)
    try:
        open_fields = {
            "attempt_nonce_sha256": "6" * 64,
            "scope_sha256": "7" * 64,
            "maximum_bytes": 4_194_304,
            "maximum_record_blob_bytes": MAX_BROKER_AUDIT_BLOB_BYTES,
            "compact_commitment_bytes": BROKER_AUDIT_COMMITMENT_BYTES,
            "watchdog_protocol_sha256": "8" * 64,
        }
        peer.send(
            "broker_audit_open",
            {**open_fields, "record_sha256": canonical_sha256(open_fields)},
        )
        registry.service_available()
        peer.receive(expected_kind="broker_audit_open_ack")
        close_fields = {
            "row_sequence": 0,
            "head_sha256": "0" * 64,
            "size_bytes": 0,
            "record_blob_count": 0,
            "record_blob_size_bytes": 0,
            "record_blob_head_sha256": "0" * 64,
            "broker": broker_identity,
            "broker_thread_count": 1,
            "broker_thread_inventory_sha256": canonical_sha256(
                {
                    "schema_id": "parser-tesseract-broker-thread-inventory-v1",
                    "broker_pid": broker_identity["pid"],
                    "broker_start_abstime": broker_identity["start_abstime"],
                    "thread_ids": [9002],
                }
            ),
            "broker_thread_observed_at_monotonic_ns": time.monotonic_ns(),
            "rlimit_nproc_soft": 1,
            "rlimit_nproc_hard": 1,
            "terminal_fork_denial_applied_at_monotonic_ns": time.monotonic_ns(),
            "terminal_no_fork": True,
        }
        peer.send(
            "broker_audit_close",
            {**close_fields, "record_sha256": canonical_sha256(close_fields)},
        )
        with pytest.raises(BrokerProtocolError, match="audit close"):
            registry.service_available()
        assert not registry.audit_closed
        assert not registry.channel_eof
    finally:
        peer.close()
        registry.close()


def test_native_closure_template_uses_512k_bounded_custody(
    tmp_path: Path,
) -> None:
    if sys.platform != "darwin":
        pytest.skip("native closure custody is Darwin-only")
    from app.services.tesseract_native_closure import derive_native_closure

    stage_root = tmp_path / "native-closure-stage"
    stage_root.mkdir(mode=0o700)
    staged = stage_root / "tesseract-executable"
    tesseract = production_runner.shutil.which("tesseract")
    if tesseract is None:
        pytest.skip("host has no frozen Tesseract executable")
    source = Path(tesseract).resolve(strict=True)
    production_runner._stage_private_executable(source=source, target=staged)
    closure = derive_native_closure(source, staged.resolve(strict=True))
    payload = production_runner._broker_launch_template_bytes(
        {"native_closure": closure}
    )
    assert 65_536 < len(payload) <= (
        production_runner.MAXIMUM_BROKER_LAUNCH_TEMPLATE_BYTES
    )
    with pytest.raises(ValueError, match="exceeded its bound"):
        production_runner._broker_launch_template_bytes(
            {
                "padding": "x"
                * production_runner.MAXIMUM_BROKER_LAUNCH_TEMPLATE_BYTES
            }
        )


def test_native_spawn_guard_build_is_private_and_source_bound(
    tmp_path: Path,
) -> None:
    if sys.platform != "darwin":
        pytest.skip("native broker spawn guard is Darwin-only")
    stage_root = tmp_path / "native-spawn-guard-stage"
    stage_root.mkdir(mode=0o700)
    path, identity, source, source_sha256 = (
        production_runner._build_and_stage_native_spawn_guard(
            workspace=Path(__file__).resolve().parents[2],
            target_root=stage_root,
        )
    )
    observed = path.lstat()
    assert source.name == "tesseract_broker_spawn.c"
    assert source_sha256 == production_runner._sha256_file(source)
    assert identity == {
        "resolved_path": str(path.resolve(strict=True)),
        "sha256": production_runner._sha256_file(path),
        "device": observed.st_dev,
        "inode": observed.st_ino,
        "mode": observed.st_mode,
        "uid": observed.st_uid,
        "nlink": observed.st_nlink,
        "size": observed.st_size,
    }
    assert stat.S_IMODE(observed.st_mode) == 0o500
    assert observed.st_uid == os.geteuid()
    assert observed.st_nlink == 1
    assert 0 < observed.st_size <= (
        production_runner.MAXIMUM_NATIVE_SPAWN_GUARD_BYTES
    )


def test_native_sandbox_probe_build_is_private_and_source_bound(
    tmp_path: Path,
) -> None:
    if sys.platform != "darwin":
        pytest.skip("native Seatbelt probe is Darwin-only")
    stage_root = tmp_path / "native-sandbox-probe-stage"
    stage_root.mkdir(mode=0o700)
    path, identity, source, source_sha256 = (
        production_runner._build_and_stage_native_sandbox_probe(
            workspace=Path(__file__).resolve().parents[2],
            target_root=stage_root,
        )
    )
    observed = path.lstat()
    assert source.name == "parser_sandbox_probe.c"
    assert source_sha256 == production_runner._sha256_file(source)
    assert identity == {
        "resolved_path": str(path.resolve(strict=True)),
        "sha256": production_runner._sha256_file(path),
        "device": observed.st_dev,
        "inode": observed.st_ino,
        "mode": observed.st_mode,
        "uid": observed.st_uid,
        "nlink": observed.st_nlink,
        "size": observed.st_size,
    }
    assert stat.S_IMODE(observed.st_mode) == 0o500
    assert observed.st_uid == os.geteuid()
    assert observed.st_nlink == 1
    assert 0 < observed.st_size <= (
        production_runner.MAXIMUM_NATIVE_SANDBOX_PROBE_BYTES
    )


@pytest.mark.parametrize(
    ("thread_count", "file_descriptor_count"), ((2, 6), (1, 7))
)
def test_pre_exec_gated_child_rejects_extra_thread_or_fd(
    thread_count: int, file_descriptor_count: int
) -> None:
    with pytest.raises(BrokerProtocolError, match="resource shape"):
        _require_pre_exec_gated_resource_shape(
            rss_bytes=1,
            thread_count=thread_count,
            file_descriptor_count=file_descriptor_count,
        )


def _reported_gated_child_inventory() -> dict[str, object]:
    descriptor_rows = []
    for fd, fd_type, role, cloexec in (
        (0, 6, "stdin_pipe", False),
        (1, 6, "stdout_pipe", False),
        (2, 6, "stderr_pipe", False),
        (3, 6, "ready_pipe", True),
        (4, 6, "release_pipe", True),
        (5, 1, "staged_executable", True),
    ):
        mode = (stat.S_IFIFO | 0o600) if fd < 5 else (stat.S_IFREG | 0o500)
        descriptor_rows.append(
            {
                "fd": fd,
                "kernel_fd_type": fd_type,
                "role": role,
                "close_on_exec": cloexec,
                "stat_device": 101,
                "stat_inode": 201 + fd,
                "stat_mode": mode,
                "stat_mode_type": stat.S_IFMT(mode),
            }
        )
    thread_ids = [901]
    return {
        "open_file_descriptors": descriptor_rows,
        "open_fd_inventory_sha256": canonical_sha256(
            {"open_file_descriptors": descriptor_rows}
        ),
        "native_thread_count": 1,
        "native_thread_ids": thread_ids,
        "native_thread_inventory_sha256": canonical_sha256(
            {"native_thread_ids": thread_ids}
        ),
    }


@pytest.mark.parametrize(
    "mutation",
    ("leaked_descriptor", "descriptor_type", "extra_thread", "digest"),
)
def test_pre_exec_gated_child_rejects_reported_inventory_drift(
    mutation: str,
) -> None:
    value = _reported_gated_child_inventory()
    if mutation == "leaked_descriptor":
        value["open_file_descriptors"] = [
            *value["open_file_descriptors"],  # type: ignore[misc]
            dict(value["open_file_descriptors"][0], fd=6),  # type: ignore[index]
        ]
    elif mutation == "descriptor_type":
        value["open_file_descriptors"][0]["kernel_fd_type"] = 1  # type: ignore[index]
    elif mutation == "extra_thread":
        value["native_thread_count"] = 2
        value["native_thread_ids"] = [901, 902]
    else:
        value["open_fd_inventory_sha256"] = "f" * 64
    with pytest.raises(BrokerProtocolError, match="gated child"):
        _validate_reported_gated_child_inventory(value)
