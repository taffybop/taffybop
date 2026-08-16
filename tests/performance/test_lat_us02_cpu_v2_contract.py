"""Fail-closed CPU-v2 evidence contracts for LAT-US02 brokered parsing."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import stat
import struct
import warnings
from dataclasses import asdict, fields as dataclass_fields

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services.tesseract_broker_protocol import BrokerProtocolError

from tests.benchmarks.latency_prewarm_contracts import (
    BrokerChildBirth,
    BrokerChildBirthCommitment,
    BrokerChildCpuReceipt,
    BrokerChildFileDescriptorIdentity,
    BrokerChildWait4Tombstone,
    BrokerExecutableIdentity,
    BrokerForkDenialIdentity,
    BrokerQuiescenceReceipt,
    BrokerScratchInventory,
    ControllerChildWatchPrefix,
    ControllerRequestResourceSample,
    ControllerResourceAggregate,
    ControllerResourceProcessSample,
    ExactBrokerRequestCpuEvidence,
    ExactProcessIdentity,
    NativeKernelProcessIdentity,
    NativeRuntimeImageAttestation,
    NativeRuntimeScanSample,
    NativeSelfCpuCounter,
    NativeVnodeFileDescriptorIdentity,
    NativeProcessResourceSample,
    PEAK_SAMPLE_EDGE_TOLERANCE_NS,
    RawRUsage,
    RawTimeval,
    RequestResourceBoundary,
    SampledProcessIdentity,
    asgi_response_witness,
    broker_request_binding_evidence,
    broker_child_birth_commitment_sha256,
    broker_scratch_inventory,
    external_cpu_stable_edge_record,
    native_file_descriptor_identity,
    native_file_descriptor_inventory,
    configuration_rollback_equivalence_projection,
    controller_pre_exec_gated_child_sample,
    controller_resource_sample_log_row,
    production_configuration_identity,
    rollback_output_configuration_identity,
    sanitized_configuration_projection,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _record(model_type, **fields):
    provisional = model_type.model_construct(
        **fields,
        record_sha256="0" * 64,
    )
    if model_type is BrokerChildBirth:
        fields["birth_commitment_sha256"] = (
            broker_child_birth_commitment_sha256(provisional)
        )
        provisional = model_type.model_construct(
            **fields,
            record_sha256="0" * 64,
        )
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message="Pydantic serializer warnings"
        )
        projection = provisional.model_dump(
            mode="json", exclude={"record_sha256"}
        )
    return model_type(
        **fields,
        record_sha256=_canonical_sha(projection),
    )


def _record_copy(record, **updates):
    fields = record.model_dump(mode="python", exclude={"record_sha256"})
    fields.update(updates)
    return _record(type(record), **fields)


def _external_copy(record, **updates):
    fields = {
        name: getattr(record, name)
        for name in type(record).model_fields
        if name != "record_sha256"
    }
    fields.update(updates)
    return external_cpu_stable_edge_record(**fields)


def _identities() -> tuple[ExactProcessIdentity, ExactProcessIdentity]:
    return (
        ExactProcessIdentity(
            role="parser_worker",
            pid=100,
            start_abstime=1,
            parent_pid=50,
            process_group_id=100,
            session_id=100,
        ),
        ExactProcessIdentity(
            role="tesseract_broker",
            pid=200,
            start_abstime=2,
            parent_pid=50,
            process_group_id=200,
            session_id=200,
        ),
    )


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


def _native_runtime_attestation(
    *,
    pid: int,
    start_abstime: int,
    operation: str,
    native_closure_sha256: str,
    executable_sha256: str,
    child_projection: dict[str, object],
    native_runtime_gate_source_sha256: str,
    native_runtime_gate_record_sha256: str,
    exec_release_e_monotonic_ns: int,
) -> NativeRuntimeImageAttestation:
    process = {
        "pid": pid,
        "start_abstime": start_abstime,
        "ppid": 200,
        "pgid": 200,
        "sid": 200,
    }
    path = "/private/tmp/tesseract"
    region = {
        "address": 4096,
        "size": 4096,
        "file_offset": 0,
        "protection": 5,
        "maximum_protection": 5,
        "user_tag": 0,
        "object_id": 0,
        "resolved_path": path,
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
        "resolved_path": path,
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
        "closure_image_sha256": executable_sha256,
        "executable_regions": [region],
        "executable_region_count": 1,
    }
    image = {**image_fields, "record_sha256": _canonical_sha(image_fields)}
    system_cache_sha256 = _sha("system-cache")
    non_system_projection_sha256 = _sha("non-system-projection")
    raw_inventory_sha256 = _canonical_sha(
        {"process": process, "regions": [region]}
    )

    def full_scan(
        *, started: int, kernel_started: int, kernel_completed: int, completed: int
    ) -> dict[str, object]:
        fields: dict[str, object] = {
            "schema_id": "parser-tesseract-native-runtime-scan-v1",
            "authority": "darwin-libproc-executable-regions-v1",
            "process": process,
            "native_closure_sha256": native_closure_sha256,
            "system_cache_sha256": system_cache_sha256,
            "staged_executable_sha256": executable_sha256,
            "staged_executable_device": 1,
            "staged_executable_inode": 2,
            "staged_executable_content_stable": True,
            "bracket_started_monotonic_ns": started,
            "kernel_scan_started_monotonic_ns": kernel_started,
            "kernel_scan_completed_monotonic_ns": kernel_completed,
            "bracket_completed_monotonic_ns": completed,
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
        return {**fields, "record_sha256": _canonical_sha(fields)}

    scans = (
        full_scan(started=22, kernel_started=23, kernel_completed=24, completed=25),
        full_scan(started=26, kernel_started=27, kernel_completed=28, completed=29),
    )
    samples = tuple(
        _record(
            NativeRuntimeScanSample,
            scan_sequence=index,
            bracket_started_monotonic_ns=int(scan["bracket_started_monotonic_ns"]),
            kernel_scan_started_monotonic_ns=int(
                scan["kernel_scan_started_monotonic_ns"]
            ),
            kernel_scan_completed_monotonic_ns=int(
                scan["kernel_scan_completed_monotonic_ns"]
            ),
            bracket_completed_monotonic_ns=int(
                scan["bracket_completed_monotonic_ns"]
            ),
            total_region_count=int(scan["total_region_count"]),
            raw_kernel_inventory_sha256=str(scan["raw_kernel_inventory_sha256"]),
            full_scan_record_sha256=str(scan["record_sha256"]),
        )
        for index, scan in enumerate(scans, 1)
    )
    logical_environment = child_projection["environment"]
    assert isinstance(logical_environment, dict)
    logical_environment_sha256 = _canonical_sha(logical_environment)
    actual_environment_projection = {
        "schema_id": "parser-tesseract-actual-exec-environment-v1",
        "logical_environment": logical_environment,
        "logical_environment_sha256": logical_environment_sha256,
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
    thread_digest = {
        "schema_id": "darwin-detailed-thread-inventory-v1",
        "process": process,
        "identity_basis": (
            "darwin-proc_pidinfo-PROC_PIDLISTTHREADS-uint64-v1"
        ),
        "thread_ids": [3_001],
        "thread_count": 1,
    }
    stopped_thread_inventory = {
        **thread_digest,
        "first_scan_started_monotonic_ns": 18,
        "first_scan_completed_monotonic_ns": 19,
        "second_scan_started_monotonic_ns": 20,
        "second_scan_completed_monotonic_ns": 21,
        "inventory_sha256": _canonical_sha(thread_digest),
    }
    detailed_descriptors: list[dict[str, object]] = []
    for fd in (0, 1, 2):
        pipe = {
            "device": 1,
            "inode": 90_000 + fd,
            "mode": stat.S_IFIFO | 0o600,
            "nlink": 1,
            "uid": 501,
            "gid": 20,
            "pipe_status": 0,
            "local_handle_sha256": _sha(f"runtime-pipe-local-{fd}"),
            "peer_handle_sha256": _sha(f"runtime-pipe-peer-{fd}"),
        }
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
            "pipe": pipe,
            "kqueue": None,
        }
        detailed_descriptors.append(
            {
                **descriptor_fields,
                "record_sha256": _canonical_sha(descriptor_fields),
            }
        )
    descriptor_digest = {
        "schema_id": "darwin-detailed-file-descriptor-inventory-v1",
        "process": process,
        "descriptors": detailed_descriptors,
    }
    stopped_descriptor_inventory = {
        **descriptor_digest,
        "first_scan_started_monotonic_ns": 18,
        "first_scan_completed_monotonic_ns": 19,
        "second_scan_started_monotonic_ns": 20,
        "second_scan_completed_monotonic_ns": 21,
        "inventory_sha256": _canonical_sha(descriptor_digest),
    }
    runtime_gate_nonce = b"n" * 32
    runtime_gate_c_ns = 123_456_789
    raw_gate_ack = struct.pack(
        "!8sQQ32s", b"RTGATE1!", pid, runtime_gate_c_ns, runtime_gate_nonce
    )
    runtime_gate_ack_sha256 = _canonical_sha(
        {
            "authority": "native-fixed-binary-pipe-RTGATE1-big-endian-v1",
            "pid": pid,
            "observed_c_monotonic_ns": runtime_gate_c_ns,
            "nonce_sha256": child_projection["runtime_gate_nonce_sha256"],
        }
    )
    transition = {
        "schema_id": "parser-tesseract-runtime-gate-transition-v1",
        "pid": pid,
        "start_abstime": start_abstime,
        "native_runtime_gate_authority": (
            "dyld-inserted-frozen-constructor-self-sigstop-before-main-v1"
        ),
        "native_runtime_gate_initializer_order_limitation": (
            "before-main-not-before-every-trusted-dependency-initializer-v1"
        ),
        "native_runtime_gate_source_sha256": (
            native_runtime_gate_source_sha256
        ),
        "native_runtime_gate_library_sha256": child_projection[
            "runtime_gate_library_sha256"
        ],
        "native_runtime_gate_record_sha256": (
            native_runtime_gate_record_sha256
        ),
        "runtime_gate_nonce_sha256": child_projection[
            "runtime_gate_nonce_sha256"
        ],
        "runtime_gate_ack_authority": (
            "native-fixed-binary-pipe-RTGATE1-big-endian-v1"
        ),
        "runtime_gate_ack_c_clock_authority": (
            "darwin-clock_gettime-CLOCK_MONOTONIC-nanoseconds-v1"
        ),
        "runtime_gate_ack_pid": pid,
        "runtime_gate_ack_c_monotonic_ns": runtime_gate_c_ns,
        "runtime_gate_raw_ack_hex": raw_gate_ack.hex(),
        "runtime_gate_raw_ack_sha256": hashlib.sha256(raw_gate_ack).hexdigest(),
        "runtime_gate_ack_sha256": runtime_gate_ack_sha256,
        "exec_release_e_monotonic_ns": exec_release_e_monotonic_ns,
        "runtime_gate_ack_observed_monotonic_ns": 14,
        "runtime_gate_fd_eof_observed_monotonic_ns": 15,
        "same_pid_exec_observed_monotonic_ns": 16,
        "constructor_stop_observed_monotonic_ns": 17,
        "pre_exec_ready_fd": 3,
        "pre_exec_ready_fd_close_on_exec": True,
        "runtime_gate_fd": 3,
        "runtime_gate_fd_inheritable_for_exec": True,
        "runtime_gate_fd_closed_before_continue": True,
        "stopped_thread_inventory": stopped_thread_inventory,
        "stopped_file_descriptor_inventory": stopped_descriptor_inventory,
        "first_stopped_scan_sha256": scans[0]["record_sha256"],
        "second_stopped_scan_sha256": scans[1]["record_sha256"],
    }
    runtime_gate_transition_sha256 = _canonical_sha(transition)
    return _record(
        NativeRuntimeImageAttestation,
        schema_id="parser-tesseract-native-runtime-attestation-v1",
        authority="darwin-libproc-executable-regions-v1",
        operation=operation,
        operation_family_sha256=_sha(f"operation-family-{operation}"),
        logical_environment_sha256=logical_environment_sha256,
        actual_environment_projection=actual_environment_projection,
        actual_environment_projection_sha256=_canonical_sha(
            actual_environment_projection
        ),
        native_closure_sha256=native_closure_sha256,
        expected_non_system_image_count=1,
        expected_non_system_projection_sha256=non_system_projection_sha256,
        observed_non_system_image_count=1,
        observed_non_system_projection_sha256=non_system_projection_sha256,
        system_cache_sha256=system_cache_sha256,
        dynamic_loader_imports_sha256=_sha("dynamic-loader-imports"),
        dynamic_loader_importing_image_count=0,
        native_trust_model="frozen-native-closure-trusted-v1",
        native_containment_claim="none-trusted-pinned-native-computation",
        polling_completeness=(
            "bounded-100ms-not-event-complete-trusted-pinned-code-v1"
        ),
        scan_interval_limit_ns=100_000_000,
        native_runtime_gate_authority=transition[
            "native_runtime_gate_authority"
        ],
        native_runtime_gate_initializer_order_limitation=transition[
            "native_runtime_gate_initializer_order_limitation"
        ],
        native_runtime_gate_source_sha256=native_runtime_gate_source_sha256,
        native_runtime_gate_library_sha256=child_projection[
            "runtime_gate_library_sha256"
        ],
        native_runtime_gate_record_sha256=native_runtime_gate_record_sha256,
        runtime_gate_nonce_sha256=child_projection[
            "runtime_gate_nonce_sha256"
        ],
        runtime_gate_ack_authority=transition["runtime_gate_ack_authority"],
        runtime_gate_ack_c_clock_authority=transition[
            "runtime_gate_ack_c_clock_authority"
        ],
        runtime_gate_ack_pid=pid,
        runtime_gate_ack_c_monotonic_ns=runtime_gate_c_ns,
        runtime_gate_raw_ack_hex=raw_gate_ack.hex(),
        runtime_gate_raw_ack_sha256=hashlib.sha256(raw_gate_ack).hexdigest(),
        runtime_gate_ack_sha256=runtime_gate_ack_sha256,
        exec_release_e_monotonic_ns=exec_release_e_monotonic_ns,
        runtime_gate_ack_observed_monotonic_ns=14,
        runtime_gate_fd_eof_observed_monotonic_ns=15,
        same_pid_exec_observed_monotonic_ns=16,
        constructor_stop_observed_monotonic_ns=17,
        stopped_signal_number=signal.SIGSTOP,
        stopped_thread_inventory=stopped_thread_inventory,
        stopped_file_descriptor_inventory=stopped_descriptor_inventory,
        runtime_gate_transition_sha256=runtime_gate_transition_sha256,
        runtime_gate_transition_ledger_row_sha256=_sha(
            "runtime-gate-ledger-row"
        ),
        guard_to_exec_transition_sha256=_sha("guard-to-exec-transition"),
        continued_signal_sent_monotonic_ns=30,
        continued_observed_monotonic_ns=31,
        actual_child_stop_gated=True,
        initial_scan=scans[0],
        scan_samples=samples,
        scan_count=len(samples),
        stopped_scan_count=2,
        post_continue_scan_count=0,
        fast_terminal_after_gate=True,
        scan_log_sha256=_canonical_sha(
            {"scan_samples": [item.model_dump(mode="json") for item in samples]}
        ),
        first_scan_started_monotonic_ns=22,
        double_stable_completed_monotonic_ns=29,
        first_input_write_monotonic_ns=0,
        last_scan_completed_monotonic_ns=29,
        terminal_waitid_code=os.CLD_EXITED,
        terminal_waitid_status=0,
        terminal_nonreaping_observed_monotonic_ns=32,
        maximum_scan_gap_ns=1,
        all_scans_same_inventory=True,
        instrumentation_through_terminal=True,
        static_closure_revalidated_after_wait4=True,
        static_closure_post_wait4_sha256=native_closure_sha256,
        transient_dlopen_polling_gap_disclosed=True,
    )


def _child(
    *,
    request_id: str = "attempt-request-1",
    request_sequence: int = 1,
    spawn_sequence: int = 1,
    pid: int = 300,
) -> BrokerChildCpuReceipt:
    nonce = f"{spawn_sequence:064x}"
    descriptor_roles = (
        (0, 6, "stdin_pipe", False, stat.S_IFIFO | 0o600),
        (1, 6, "stdout_pipe", False, stat.S_IFIFO | 0o600),
        (2, 6, "stderr_pipe", False, stat.S_IFIFO | 0o600),
        (3, 6, "ready_pipe", True, stat.S_IFIFO | 0o600),
        (4, 6, "release_pipe", True, stat.S_IFIFO | 0o600),
        (5, 1, "staged_executable", True, stat.S_IFREG | 0o500),
    )
    descriptors = tuple(
        BrokerChildFileDescriptorIdentity(
            fd=fd,
            kernel_fd_type=kernel_type,
            role=role,
            close_on_exec=close_on_exec,
            stat_device=1,
            stat_inode=10 + fd,
            stat_mode=mode,
            stat_mode_type=stat.S_IFMT(mode),
        )
        for fd, kernel_type, role, close_on_exec, mode in descriptor_roles
    )
    open_fd_inventory_sha256 = _canonical_sha(
        {
            "open_file_descriptors": [
                item.model_dump(mode="json") for item in descriptors
            ]
        }
    )
    native_thread_ids = (3_001,)
    native_thread_inventory_sha256 = _canonical_sha(
        {"native_thread_ids": list(native_thread_ids)}
    )
    prior_signal_mask = (1, 2, 15)
    blocked_signals = tuple(
        sorted(
            int(item)
            for item in signal.valid_signals()
            if int(item) not in {int(signal.SIGKILL), int(signal.SIGSTOP)}
        )
    )
    runtime_gate_nonce_sha256 = hashlib.sha256(b"n" * 32).hexdigest()
    native_runtime_gate_source_sha256 = _sha("runtime-gate-source")
    native_runtime_gate_library_sha256 = _sha("runtime-gate-library")
    native_runtime_gate_record_sha256 = _sha("runtime-gate-record")
    native_child_config_sha256 = _sha("native-child-config")
    logical_environment = {
        "LANG": "C",
        "LC_ALL": "C",
        "OMP_THREAD_LIMIT": "1",
        "TESSDATA_PREFIX": "/frozen/tessdata",
    }
    child_projection: dict[str, object] = {
        "schema_id": "parser-tesseract-native-child-config-projection-v1",
        "attempt_nonce_sha256": _sha("attempt-nonce"),
        "scope_sha256": _sha("scope"),
        "request_id": request_id,
        "request_epoch": request_sequence + 1,
        "request_sequence": request_sequence,
        "spawn_sequence": spawn_sequence,
        "spawn_nonce_sha256": nonce,
        "broker_pid": 200,
        "broker_start_abstime": 2,
        "broker_pgid": 200,
        "broker_sid": 200,
        "config_fd": 10,
        "native_state_fd": 11,
        "ready_fd": 12,
        "release_fd": 13,
        "stdin_fd": 14,
        "stdout_fd": 15,
        "stderr_fd": 16,
        "executable": "/private/tmp/tesseract",
        "expected_executable_sha256": "1" * 64,
        "expected_executable_device": 1,
        "expected_executable_inode": 2,
        "argv": ["/private/tmp/tesseract", "--version"],
        "environment": logical_environment,
        "native_spawn_guard_sha256": _sha("native-spawn-guard"),
        "previous_signal_mask": list(prior_signal_mask),
        "previous_signal_mask_sha256": _canonical_sha(
            {"signal_mask": list(prior_signal_mask)}
        ),
        "runtime_gate_library": "/frozen/runtime-gate.dylib",
        "runtime_gate_library_sha256": native_runtime_gate_library_sha256,
        "runtime_gate_library_device": 3,
        "runtime_gate_library_inode": 4,
        "runtime_gate_nonce_sha256": runtime_gate_nonce_sha256,
        "guard_python_path": "/usr/bin/python3",
        "guard_python_sha256": _sha("guard-python"),
        "guard_python_device": 5,
        "guard_python_inode": 6,
        "guard_python_path_custody_sha256": _sha(
            "guard-python-path-custody"
        ),
        "guard_python_native_closure_sha256": _sha(
            "guard-python-native-closure"
        ),
        "guard_python_module_tree_root": "/Library/Python/3.9",
        "guard_python_module_tree_sha256": _sha(
            "guard-python-module-tree"
        ),
        "guard_wrapper_sha256": _sha("child-wrapper"),
        "guard_wrapper_delivery_basis": (
            "execve-python-c-embedded-source-v1"
        ),
        "guard_exec_argv_sha256": _sha("guard-exec-argv"),
        "guard_exec_environment_sha256": _sha("guard-exec-environment"),
        "native_child_config_sha256": native_child_config_sha256,
    }
    actual_environment_projection = {
        "schema_id": "parser-tesseract-actual-exec-environment-v1",
        "logical_environment": logical_environment,
        "logical_environment_sha256": _canonical_sha(logical_environment),
        "runtime_gate_library_path": child_projection[
            "runtime_gate_library"
        ],
        "runtime_gate_library_sha256": native_runtime_gate_library_sha256,
        "runtime_gate_fd": 3,
        "runtime_gate_nonce_sha256": runtime_gate_nonce_sha256,
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
    child_release_fields = {
        "schema_id": "parser-tesseract-child-release-v1",
        "pid": pid,
        "released_monotonic_ns": 2,
        "ready_record_sha256": _sha("child-ready"),
    }
    birth = _record(
        BrokerChildBirth,
        request_id=request_id,
        request_epoch=request_sequence + 1,
        request_sequence=request_sequence,
        spawn_sequence=spawn_sequence,
        spawn_nonce_sha256=nonce,
        record_sequence=1,
        previous_record_sha256="0" * 64,
        pid=pid,
        start_abstime=spawn_sequence + 10,
        ppid=200,
        pgid=200,
        sid=200,
        broker_pid=200,
        broker_start_abstime=2,
        born_monotonic_ns=4,
        spawn_intent_sha256=_sha("spawn-intent"),
        spawn_intent_ledger_row_sha256=_sha("spawn-intent-ledger-row"),
        spawn_intent_durable_acknowledged_monotonic_ns=3,
        provisional_record_sha256=_sha("child-provisional"),
        provisional_child_ledger_row_sha256=_sha(
            "child-provisional-ledger-row"
        ),
        provisional_observed_monotonic_ns=7,
        child_ready_sha256=_sha("child-ready"),
        child_ready_intent_ledger_row_sha256=_sha(
            "child-ready-intent-ledger-row"
        ),
        open_file_descriptors=descriptors,
        open_fd_inventory_sha256=open_fd_inventory_sha256,
        native_thread_ids=native_thread_ids,
        native_thread_inventory_sha256=native_thread_inventory_sha256,
        broker_thread_inventory_sha256=_sha("broker-threads"),
        broker_thread_observed_at_monotonic_ns=2,
        broker_thread_inventory_immediately_before_fork_sha256=_sha(
            "broker-threads"
        ),
        broker_thread_immediately_before_fork_observed_at_monotonic_ns=3,
        blocked_signals_across_fork=blocked_signals,
        blocked_signals_across_fork_sha256=_canonical_sha(
            {"blocked_signals": list(blocked_signals)}
        ),
        registration_acknowledged_monotonic_ns=8,
        guard_release_a_monotonic_ns=11,
        child_reported_guard_release_a_monotonic_ns=2,
        child_guard_release_a_record_sha256=_canonical_sha(
            child_release_fields
        ),
        birth_durable_acknowledged_monotonic_ns=12,
        exec_release_e_monotonic_ns=13,
        operation="version",
        logical_argv_sha256="2" * 64,
        actual_argv_sha256=_canonical_sha(
            {"argv": child_projection["argv"]}
        ),
        logical_environment_sha256=_canonical_sha(logical_environment),
        actual_environment_projection_sha256=_canonical_sha(
            actual_environment_projection
        ),
        input_sha256="5" * 64,
        input_bytes=0,
        executable=BrokerExecutableIdentity(
            resolved_path="/private/tmp/tesseract",
            sha256="1" * 64,
            device=1,
            inode=2,
            mode=0o100755,
            uid=501,
            size=1,
        ),
        native_closure_sha256=_sha("native-closure"),
        native_trust_model="frozen-native-closure-trusted-v1",
        native_containment_claim=(
            "none-trusted-pinned-native-computation"
        ),
        native_runtime_attestation_required=True,
        native_runtime_scan_interval_ns=100_000_000,
        native_runtime_gate_authority=(
            "dyld-inserted-frozen-constructor-self-sigstop-before-main-v1"
        ),
        native_runtime_gate_initializer_order_limitation=(
            "before-main-not-before-every-trusted-dependency-initializer-v1"
        ),
        native_runtime_gate_source_sha256=native_runtime_gate_source_sha256,
        native_runtime_gate_library_sha256=native_runtime_gate_library_sha256,
        native_runtime_gate_record_sha256=native_runtime_gate_record_sha256,
        runtime_gate_nonce_sha256=runtime_gate_nonce_sha256,
        runtime_gate_ack_authority=(
            "native-fixed-binary-pipe-RTGATE1-big-endian-v1"
        ),
        guard_python_sha256=child_projection["guard_python_sha256"],
        guard_python_path_custody_sha256=child_projection[
            "guard_python_path_custody_sha256"
        ],
        guard_python_native_closure_sha256=child_projection[
            "guard_python_native_closure_sha256"
        ],
        guard_python_module_tree_sha256=child_projection[
            "guard_python_module_tree_sha256"
        ],
        guard_python_path_exec_trust_model=(
            "root-owned-pinned-clt-python-native-closure-v1"
        ),
        guard_python_path_exec_containment_claim=(
            "none-trusted-host-path-exec"
        ),
        guard_wrapper_delivery_basis=(
            "execve-python-c-embedded-source-v1"
        ),
        guard_config_fd=10,
        guard_ready_fd=12,
        guard_exec_argv_sha256=child_projection["guard_exec_argv_sha256"],
        guard_exec_environment_sha256=child_projection[
            "guard_exec_environment_sha256"
        ],
        guard_post_exec_environment_sha256=_sha(
            "guard-post-exec-environment"
        ),
        native_child_config_sha256=native_child_config_sha256,
        native_child_config_projection=child_projection,
        native_child_config_projection_sha256=_canonical_sha(
            child_projection
        ),
        fork_denial=BrokerForkDenialIdentity(
            profile_sha256=_sha("child-profile"),
            wrapper_sha256=_sha("child-wrapper"),
            native_spawn_guard_source_sha256=_sha("native-spawn-source"),
            native_spawn_guard_sha256=_sha("native-spawn-guard"),
            guard_python_sha256=child_projection["guard_python_sha256"],
            guard_python_path_custody_sha256=child_projection[
                "guard_python_path_custody_sha256"
            ],
            guard_python_native_closure_sha256=child_projection[
                "guard_python_native_closure_sha256"
            ],
            guard_python_module_tree_sha256=child_projection[
                "guard_python_module_tree_sha256"
            ],
            guard_python_path_exec_trust_model=(
                "root-owned-pinned-clt-python-native-closure-v1"
            ),
            guard_python_path_exec_containment_claim=(
                "none-trusted-host-path-exec"
            ),
            guard_exec_argv_sha256=child_projection[
                "guard_exec_argv_sha256"
            ],
            guard_exec_environment_sha256=child_projection[
                "guard_exec_environment_sha256"
            ],
            guard_post_exec_environment_sha256=_sha(
                "guard-post-exec-environment"
            ),
            native_child_config_sha256=native_child_config_sha256,
            real_uid=501,
            effective_uid=501,
            native_child_limit_applied_monotonic_ns=4,
            native_child_limit_applied_clock_authority=(
                "darwin-clock_gettime-CLOCK_MONOTONIC-nanoseconds-v1"
            ),
            native_child_limit_ack_pid=pid,
            native_child_limit_ack_sha256=hashlib.sha256(
                struct.pack("!8sQQQQ", b"PN0ACK1!", pid, 4, 0, 0)
            ).hexdigest(),
            native_fork_parent_returned_monotonic_ns=5,
            native_child_limit_acknowledged_monotonic_ns=6,
            native_python_release_n_monotonic_ns=9,
            prior_signal_mask=prior_signal_mask,
            prior_signal_mask_sha256=_canonical_sha(
                {"signal_mask": list(prior_signal_mask)}
            ),
            restored_signal_mask=prior_signal_mask,
            restored_signal_mask_sha256=_canonical_sha(
                {"signal_mask": list(prior_signal_mask)}
            ),
            applied_at_monotonic_ns=1,
            child_guard_applied_clock_authority=(
                "clt-python39-time-monotonic-clock-monotonic-v1"
            ),
            child_reported_guard_release_a_monotonic_ns=2,
            child_guard_release_a_record_sha256=_canonical_sha(
                child_release_fields
            ),
            child_guard_ready_observed_monotonic_ns=10,
            ready_record_sha256=_sha("child-ready"),
        ),
        watchdog_registration_sha256="7" * 64,
        watchdog_registration_ack_sha256="8" * 64,
        birth_commitment_sha256=_sha("birth-commitment"),
        birth_ledger_row_sha256=_sha("birth-ledger-row"),
        watchdog_birth_sha256=_sha("watchdog-birth"),
        watchdog_birth_ack_sha256=_sha("watchdog-birth-ack"),
        exec_release_ledger_row_sha256=_sha("exec-release-ledger-row"),
    )
    tombstone = _record(
        BrokerChildWait4Tombstone,
        request_id=request_id,
        request_epoch=request_sequence + 1,
        request_sequence=request_sequence,
        spawn_sequence=spawn_sequence,
        spawn_nonce_sha256=nonce,
        record_sequence=2,
        previous_record_sha256=birth.record_sha256,
        birth_record_sha256=birth.record_sha256,
        pid=pid,
        start_abstime=birth.start_abstime,
        raw_wait_status=0,
        exited=True,
        exit_code=0,
        signaled=False,
        signal_number=None,
        core_dumped=False,
        rusage=RawRUsage(
            user=RawTimeval(
                seconds=0,
                microseconds=100,
                derived_ns=100_000,
            ),
            system=RawTimeval(
                seconds=0,
                microseconds=200,
                derived_ns=200_000,
            ),
        ),
        stdout_bytes=1,
        stdout_retained_bytes=1,
        stdout_sha256=hashlib.sha256(b"x").hexdigest(),
        stdout_disposition="captured",
        stderr_bytes=0,
        stderr_retained_bytes=0,
        stderr_sha256=hashlib.sha256(b"").hexdigest(),
        stderr_disposition="captured",
        overflowed=False,
        observed_monotonic_ns=33,
        maximum_resident_set_size_bytes=1,
        minor_faults=0,
        major_faults=0,
        voluntary_context_switches=0,
        involuntary_context_switches=0,
        nonreaping_wait4_probe_count=1,
        terminal_wait4_reap_count=1,
        direct_parent_waited=True,
        native_runtime_attestation=_native_runtime_attestation(
            pid=pid,
            start_abstime=birth.start_abstime,
            operation=birth.operation,
            native_closure_sha256=birth.native_closure_sha256,
            executable_sha256=birth.executable.sha256,
            child_projection=child_projection,
            native_runtime_gate_source_sha256=(
                native_runtime_gate_source_sha256
            ),
            native_runtime_gate_record_sha256=(
                native_runtime_gate_record_sha256
            ),
            exec_release_e_monotonic_ns=birth.exec_release_e_monotonic_ns,
        ),
    )
    return BrokerChildCpuReceipt(
        birth=birth,
        tombstone=tombstone,
        watchdog_closure_record_sha256="9" * 64,
    )


def _exact_cpu(
    *,
    children: tuple[BrokerChildCpuReceipt, ...] | None = None,
) -> ExactBrokerRequestCpuEvidence:
    worker, broker = _identities()
    request_id = "attempt-request-1"
    retained_children = (_child(),) if children is None else children
    attempt_nonce = "d" * 64
    scope = "e" * 64
    binding = broker_request_binding_evidence(
        query_sha256="f" * 64,
        output_format="json",
        source_sha256="1" * 64,
        source_bytes=1,
        safe_filename_sha256="2" * 64,
        upload_content_type_sha256="3" * 64,
        binding_record_sha256="4" * 64,
        matched_at_monotonic_ns=4,
    )
    begin_scratch = broker_scratch_inventory(
        root_device=10,
        root_inode=20,
        root_uid=501,
        scan_started_monotonic_ns=1,
        scan_completed_monotonic_ns=1,
    )
    begin = BrokerQuiescenceReceipt(
        request_id=request_id,
        attempt_nonce_sha256=attempt_nonce,
        scope_sha256=scope,
        request_epoch=2,
        request_sequence=1,
        edge="begin",
        observed_monotonic_ns=1,
        worker=worker,
        broker=broker,
        ledger_head_sha256="8" * 64,
        completed_spawn_count=0,
        worker_group_member_pids=(worker.pid,),
        broker_group_member_pids=(broker.pid,),
        broker_thread_inventory_sha256=_sha("broker-threads"),
        broker_thread_observed_at_monotonic_ns=1,
        request_root_inventory=begin_scratch,
    )
    end = begin.model_copy(
        update={
                "edge": "end",
                "observed_monotonic_ns": 40,
            "ledger_head_sha256": "9" * 64,
            "completed_spawn_count": len(retained_children),
            "request_root_inventory": broker_scratch_inventory(
                root_device=10,
                root_inode=20,
                root_uid=501,
                    scan_started_monotonic_ns=40,
                    scan_completed_monotonic_ns=40,
            ),
        }
    )
    worker_before = NativeSelfCpuCounter(
        identity=worker,
        observed_monotonic_ns=3,
        user_cpu_ns=100,
        system_cpu_ns=200,
    )
    worker_after = worker_before.model_copy(
        update={
            "observed_monotonic_ns": 42,
            "user_cpu_ns": 110,
            "system_cpu_ns": 220,
        }
    )
    broker_before = NativeSelfCpuCounter(
        identity=broker,
        observed_monotonic_ns=2,
        user_cpu_ns=300,
        system_cpu_ns=400,
    )
    broker_after = broker_before.model_copy(
        update={
            "observed_monotonic_ns": 41,
            "user_cpu_ns": 330,
            "system_cpu_ns": 440,
        }
    )
    begin_post_scratch = broker_scratch_inventory(
        root_device=10,
        root_inode=20,
        root_uid=501,
        scan_started_monotonic_ns=3,
        scan_completed_monotonic_ns=3,
    )
    end_post_scratch = broker_scratch_inventory(
        root_device=10,
        root_inode=20,
        root_uid=501,
        scan_started_monotonic_ns=42,
        scan_completed_monotonic_ns=42,
    )
    begin_external = external_cpu_stable_edge_record(
        attempt_id="attempt",
        attempt_nonce_sha256=attempt_nonce,
        scope_sha256=scope,
        request_id=request_id,
        request_epoch=2,
        request_sequence=1,
        request_deadline_monotonic_ns=100,
        edge="begin",
        broker_sample=NativeProcessResourceSample(
            cpu=broker_before,
            rss_bytes=1_000,
            thread_count=1,
            native_thread_ids=(2_001,),
            file_descriptor_count=3,
            file_descriptor_inventory=_native_fd_inventory(
                broker, 3, broker_before.observed_monotonic_ns
            ),
        ),
        worker_sample=NativeProcessResourceSample(
            cpu=worker_before,
            rss_bytes=2_000,
            thread_count=4,
            native_thread_ids=(1_001, 1_002, 1_003, 1_004),
            file_descriptor_count=5,
            file_descriptor_inventory=_native_fd_inventory(
                worker, 5, worker_before.observed_monotonic_ns
            ),
        ),
        post_sample_scratch_inventory=begin_post_scratch,
    )
    end_external = external_cpu_stable_edge_record(
        attempt_id="attempt",
        attempt_nonce_sha256=attempt_nonce,
        scope_sha256=scope,
        request_id=request_id,
        request_epoch=2,
        request_sequence=1,
        request_deadline_monotonic_ns=100,
        edge="end",
        broker_sample=NativeProcessResourceSample(
            cpu=broker_after,
            rss_bytes=1_100,
            thread_count=1,
            native_thread_ids=(2_001,),
            file_descriptor_count=3,
            file_descriptor_inventory=_native_fd_inventory(
                broker, 3, broker_after.observed_monotonic_ns
            ),
        ),
        worker_sample=NativeProcessResourceSample(
            cpu=worker_after,
            rss_bytes=2_100,
            thread_count=4,
            native_thread_ids=(1_001, 1_002, 1_003, 1_004),
            file_descriptor_count=5,
            file_descriptor_inventory=_native_fd_inventory(
                worker, 5, worker_after.observed_monotonic_ns
            ),
        ),
        post_sample_scratch_inventory=end_post_scratch,
    )
    tesseract_user = sum(
        item.tombstone.user_cpu_ns for item in retained_children
    )
    tesseract_system = sum(
        item.tombstone.system_cpu_ns for item in retained_children
    )
    gated_samples = tuple(
        controller_pre_exec_gated_child_sample(
            pid=item.birth.pid,
            start_abstime=item.birth.start_abstime,
            ppid=item.birth.ppid,
            pgid=item.birth.pgid,
            sid=item.birth.sid,
            observed_monotonic_ns=item.birth.exec_release_e_monotonic_ns - 1,
            user_cpu_ns=1,
            system_cpu_ns=1,
            rss_bytes=1,
            thread_count=1,
            file_descriptor_count=6,
            native_thread_ids=item.birth.native_thread_ids,
            open_fd_inventory_sha256=item.birth.open_fd_inventory_sha256,
            native_thread_inventory_sha256=(
                item.birth.native_thread_inventory_sha256
            ),
            child_ready_sha256=item.birth.child_ready_sha256,
        )
        for item in retained_children
    )
    return ExactBrokerRequestCpuEvidence(
        attempt_id="attempt",
        request_id=request_id,
        attempt_nonce_sha256=attempt_nonce,
        scope_sha256=scope,
        request_epoch=2,
        request_sequence=1,
        request_deadline_monotonic_ns=100,
        arm_capability_sha256="5" * 64,
        arm_issued_at_monotonic_ns=1,
        arm_consumed_at_monotonic_ns=1,
        binding_sha256=binding.binding_record_sha256,
        request_binding=binding,
        asgi_response_witness=(
            witness := asgi_response_witness(
                ordered_headers=(
                    {
                        "name_hex": b"content-type".hex(),
                        "value_hex": b"application/json".hex(),
                    },
                ),
                response_start_send_completed_monotonic_ns=4,
                response_body_message_keys=("body", "type"),
                body_sha256=_sha("response-body"),
                body_bytes=1,
                response_body_send_completed_monotonic_ns=5,
                inner_asgi_returned_monotonic_ns=6,
            )
        ),
        asgi_response_witness_sha256=witness.record_sha256,
        thread_transfer_record_sha256s=("6" * 64, "7" * 64),
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
        begin_external_sample_row_sha256=_sha("begin-sample-row"),
        end_external_sample_row_sha256=_sha("end-sample-row"),
        request_control_arm_record_sha256=_sha("arm"),
        request_control_begin_blocked_record_sha256=_sha("begin-blocked"),
        request_control_begin_release_record_sha256=_sha("begin-release"),
        request_control_end_blocked_record_sha256=_sha("end-blocked"),
        request_control_receipt_release_record_sha256=_sha("receipt-release"),
        request_control_result_record_sha256=_sha("result"),
        request_control_result_ack_record_sha256=_sha("result-ack"),
        request_control_transcript_row_sha256s=tuple(
            _sha(f"transcript-{index}") for index in range(1, 8)
        ),
        begin_release_monotonic_ns=3,
        receipt_release_monotonic_ns=43,
        broker_request_receipt_sha256="a" * 64,
        pre_exec_gated_child_samples=gated_samples,
        children=retained_children,
        worker_user_cpu_delta_ns=10,
        worker_system_cpu_delta_ns=20,
        broker_user_cpu_delta_ns=30,
        broker_system_cpu_delta_ns=40,
        tesseract_user_cpu_delta_ns=tesseract_user,
        tesseract_system_cpu_delta_ns=tesseract_system,
        total_cpu_delta_ns=(100 + tesseract_user + tesseract_system),
        sampled_process_identities=tuple(
            sorted(
                (
                    SampledProcessIdentity(
                        role="parser_worker",
                        pid=worker.pid,
                        start_abstime=worker.start_abstime,
                        parent_pid=worker.parent_pid,
                        process_group_id=worker.process_group_id,
                        session_id=worker.session_id,
                    ),
                    SampledProcessIdentity(
                        role="tesseract_broker",
                        pid=broker.pid,
                        start_abstime=broker.start_abstime,
                        parent_pid=broker.parent_pid,
                        process_group_id=broker.process_group_id,
                        session_id=broker.session_id,
                    ),
                    *(
                        SampledProcessIdentity(
                            role="tesseract_child",
                            pid=item.birth.pid,
                            start_abstime=item.birth.start_abstime,
                            parent_pid=item.birth.ppid,
                            process_group_id=item.birth.pgid,
                            session_id=item.birth.sid,
                        )
                        for item in retained_children
                    ),
                ),
                key=lambda item: (item.pid, item.start_abstime),
            )
        ),
    )


def _boundary(exact: ExactBrokerRequestCpuEvidence) -> RequestResourceBoundary:
    worker = exact.begin.worker
    broker = exact.begin.broker
    child = exact.children[0].birth

    def process(
        *,
        role: str,
        pid: int,
        start_abstime: int,
        ppid: int,
        pgid: int,
        sid: int,
        observed: int,
        user: int,
        system: int,
        rss: int,
        threads: int,
        fds: int,
    ) -> ControllerResourceProcessSample:
        return ControllerResourceProcessSample(
            role=role,
            pid=pid,
            start_abstime=start_abstime,
            ppid=ppid,
            pgid=pgid,
            sid=sid,
            sample_started_monotonic_ns=observed - 1,
            observed_monotonic_ns=observed,
            sample_completed_monotonic_ns=observed + 1,
            user_cpu_ns=user,
            system_cpu_ns=system,
            rss_bytes=rss,
            thread_count=threads,
            native_thread_ids=tuple(range(pid * 10, pid * 10 + threads)),
            file_descriptor_count=fds,
        )

    def resource_record(
        observed: int,
        processes: tuple[ControllerResourceProcessSample, ...],
        *,
        boundary_membership: str,
        prefix: str,
        prefix_count: int,
        terminal_wait4_count: int,
        gated_sha256s: tuple[str, ...] = (),
    ) -> ControllerRequestResourceSample:
        sweep_started = min(
            item.sample_started_monotonic_ns for item in processes
        )
        sweep_completed = max(
            item.sample_completed_monotonic_ns for item in processes
        )
        return ControllerRequestResourceSample(
            attempt_id=exact.attempt_id,
            request_id=exact.request_id,
            request_epoch=exact.request_epoch,
            request_sequence=exact.request_sequence,
            observed_monotonic_ns=sweep_completed,
            sweep_started_monotonic_ns=sweep_started,
            sweep_completed_monotonic_ns=sweep_completed,
            sweep_span_ns=sweep_completed - sweep_started,
            maximum_sweep_span_ns=PEAK_SAMPLE_EDGE_TOLERANCE_NS,
            boundary_membership=boundary_membership,
            processes=processes,
            aggregate=ControllerResourceAggregate(
                process_count=len(processes),
                rss_bytes=sum(item.rss_bytes for item in processes),
                thread_count=sum(item.thread_count for item in processes),
                file_descriptor_count=sum(
                    item.file_descriptor_count for item in processes
                ),
            ),
            child_watch_prefix=ControllerChildWatchPrefix(
                size_bytes=prefix_count,
                sha256=(
                    "0" * 64 if prefix_count == 0 else _sha(f"{prefix}-raw")
                ),
                broker_row_count=prefix_count,
                broker_head_sha256=(
                    "0" * 64
                    if prefix_count == 0
                    else _sha(f"{prefix}-broker")
                ),
                record_blob_count=prefix_count,
                record_blob_size_bytes=prefix_count,
                record_blob_head_sha256=(
                    "0" * 64
                    if prefix_count == 0
                    else _sha(f"{prefix}-record-blob-head")
                ),
                record_blob_root_sha256=(
                    "0" * 64
                    if prefix_count == 0
                    else _sha(f"{prefix}-record-blob-root")
                ),
                event_count=prefix_count,
                event_blob_size_bytes=prefix_count,
                event_blob_root_sha256=(
                    "0" * 64
                    if prefix_count == 0
                    else _sha(f"{prefix}-event-blob-root")
                ),
                event_head_sha256=(
                    "0" * 64
                    if prefix_count == 0
                    else _sha(f"{prefix}-event")
                ),
                open_registration_count=0,
                terminal_wait4_count=terminal_wait4_count,
                current_request_pre_exec_gated_sample_record_sha256s=(
                    gated_sha256s
                ),
            ),
        )

    start_processes = (
        process(
            role="parser_worker",
            pid=worker.pid,
            start_abstime=worker.start_abstime,
            ppid=worker.parent_pid,
            pgid=worker.process_group_id,
            sid=worker.session_id,
            observed=3,
            user=100,
            system=200,
            rss=2_000,
            threads=4,
            fds=5,
        ),
        process(
            role="tesseract_broker",
            pid=broker.pid,
            start_abstime=broker.start_abstime,
            ppid=broker.parent_pid,
            pgid=broker.process_group_id,
            sid=broker.session_id,
            observed=3,
            user=300,
            system=400,
            rss=1_000,
            threads=1,
            fds=3,
        ),
    )
    middle_processes = (
        start_processes[0].model_copy(
            update={
                "sample_started_monotonic_ns": 9,
                "observed_monotonic_ns": 10,
                "sample_completed_monotonic_ns": 11,
                "user_cpu_ns": 105,
                "system_cpu_ns": 210,
                "rss_bytes": 2_050,
            }
        ),
        start_processes[1].model_copy(
            update={
                "sample_started_monotonic_ns": 9,
                "observed_monotonic_ns": 10,
                "sample_completed_monotonic_ns": 11,
                "user_cpu_ns": 310,
                "system_cpu_ns": 420,
                "rss_bytes": 1_050,
            }
        ),
        process(
            role="tesseract_child",
            pid=child.pid,
            start_abstime=child.start_abstime,
            ppid=child.ppid,
            pgid=child.pgid,
            sid=child.sid,
            observed=10,
            user=50,
            system=50,
            rss=1,
            threads=1,
            fds=0,
        ),
    )
    end_processes = (
        start_processes[0].model_copy(
            update={
                "sample_started_monotonic_ns": 41,
                "observed_monotonic_ns": 42,
                "sample_completed_monotonic_ns": 43,
                "user_cpu_ns": 110,
                "system_cpu_ns": 220,
                "rss_bytes": 2_100,
            }
        ),
        start_processes[1].model_copy(
            update={
                "sample_started_monotonic_ns": 41,
                "observed_monotonic_ns": 42,
                "sample_completed_monotonic_ns": 43,
                "user_cpu_ns": 330,
                "system_cpu_ns": 440,
                "rss_bytes": 1_100,
            }
        ),
    )
    records = (
        resource_record(
            3,
            start_processes,
            boundary_membership="boundary_begin",
            prefix="start",
            prefix_count=0,
            terminal_wait4_count=0,
        ),
        resource_record(
            10,
            middle_processes,
            boundary_membership="boundary_interior",
            prefix="middle",
            prefix_count=1,
            terminal_wait4_count=0,
            gated_sha256s=tuple(
                sorted(item.record_sha256
                for item in exact.pre_exec_gated_child_samples
                )
            ),
        ),
        resource_record(
            42,
            end_processes,
            boundary_membership="boundary_end",
            prefix="end",
            prefix_count=2,
            terminal_wait4_count=1,
            gated_sha256s=tuple(
                sorted(item.record_sha256
                for item in exact.pre_exec_gated_child_samples
                )
            ),
        ),
    )
    rows = []
    previous = "0" * 64
    for sequence, record in enumerate(records, start=1):
        row = controller_resource_sample_log_row(
            row_sequence=sequence,
            previous_row_sha256=previous,
            record=record,
            retained_monotonic_ns=record.observed_monotonic_ns + 1,
        )
        rows.append(row)
        previous = row.row_sha256
    return RequestResourceBoundary(
        boundary_started_monotonic_ns=3,
        boundary_ended_monotonic_ns=42,
        self_user_cpu_delta_ns=0,
        self_system_cpu_delta_ns=0,
        reaped_child_user_cpu_delta_ns=0,
        reaped_child_system_cpu_delta_ns=0,
        live_descendant_user_cpu_delta_ns=0,
        live_descendant_system_cpu_delta_ns=0,
        live_descendant_process_count=0,
        total_cpu_delta_ns=exact.total_cpu_delta_ns,
        host_logical_cpu_count=20_000,
        wall_cpu_capacity_ns=780_000,
        descendant_peak_process_count=3,
        descendant_peak_rss_bytes=3_200,
        process_tree_peak_thread_count=6,
        process_tree_peak_file_descriptor_count=14,
        exact_broker_cpu=exact,
        controller_resource_sample_rows=tuple(rows),
        cpu_accounting_basis=(
            "fork-denied-worker-broker-self-plus-exact-wait4-v2"
        ),
        sampled_concurrently=True,
        descendant_sample_count=3,
        descendant_first_sample_monotonic_ns=2,
        descendant_last_sample_monotonic_ns=43,
        descendant_maximum_gap_ns=30,
        descendant_target_interval_ns=10,
        descendant_edge_tolerance_ns=50,
        request_boundary_covered=True,
    )


def test_exact_cpu_v2_recomputes_three_disjoint_owners() -> None:
    exact = _exact_cpu()
    boundary = _boundary(exact)

    assert exact.total_cpu_delta_ns == 300_100
    assert boundary.cpu_before is None
    assert boundary.cpu_after is None
    assert boundary.total_cpu_delta_ns == exact.total_cpu_delta_ns


def test_arm_request_binding_and_transfer_custody_is_fail_closed() -> None:
    exact = _exact_cpu()
    binding = exact.request_binding.model_dump(mode="python")
    with pytest.raises(ValidationError, match="request-binding evidence identity"):
        type(exact.request_binding).model_validate(
            {**binding, "source_sha256": "f" * 64}
        )
    with pytest.raises(ValidationError, match="ARM/request binding"):
        ExactBrokerRequestCpuEvidence.model_validate(
            {
                **exact.model_dump(mode="python"),
                "arm_consumed_at_monotonic_ns": (
                    exact.begin.observed_monotonic_ns + 1
                ),
            }
        )
    with pytest.raises(ValidationError, match="ARM/request binding"):
        ExactBrokerRequestCpuEvidence.model_validate(
            {
                **exact.model_dump(mode="python"),
                "thread_transfer_record_sha256s": ("6" * 64, "6" * 64),
            }
        )
    with pytest.raises(ValidationError, match="quiescence request binding"):
        ExactBrokerRequestCpuEvidence.model_validate(
            {
                **exact.model_dump(mode="python"),
                "end": exact.end.model_copy(update={"scope_sha256": "0" * 64}),
            }
        )


def test_wait4_timeval_must_be_integral_and_recomputed() -> None:
    tombstone = _child().tombstone
    probed = _record_copy(tombstone, nonreaping_wait4_probe_count=3)
    assert probed.nonreaping_wait4_probe_count == 3
    assert probed.terminal_wait4_reap_count == 1
    with pytest.raises(ValidationError):
        _record_copy(tombstone, terminal_wait4_reap_count=2)
    rusage = tombstone.rusage.model_dump(mode="python")
    bad_user = {**rusage["user"], "derived_ns": 100_001}
    with pytest.raises(ValidationError, match="timeval nanoseconds"):
        _record_copy(
            tombstone,
            rusage={**rusage, "user": bad_user},
        )
    with pytest.raises(ValidationError):
        _record_copy(
            tombstone,
            rusage={
                **rusage,
                "user": {**rusage["user"], "microseconds": 1.5},
            },
        )
    with pytest.raises(ValidationError, match="wait4 tombstone status"):
        _record_copy(
            tombstone,
            raw_wait_status=9,
            exit_code=0,
            signal_number=None,
        )


def test_wait4_stream_disposition_controls_retention_without_false_overflow() -> None:
    tombstone = _child().tombstone
    discarded = _record_copy(
        tombstone,
        stdout_disposition="discarded",
        stdout_retained_bytes=0,
    )
    assert discarded.stdout_bytes == 1
    assert discarded.stdout_retained_bytes == 0
    assert discarded.overflowed is False
    with pytest.raises(ValidationError, match="stream custody"):
        _record_copy(tombstone, stdout_disposition="discarded")
    with pytest.raises(ValidationError, match="stream custody"):
        _record_copy(tombstone, stdout_retained_bytes=0)


def test_birth_and_tombstone_cannot_cross_request_or_spawn_token() -> None:
    receipt = _child()
    with pytest.raises(ValidationError, match="identity differs"):
        BrokerChildCpuReceipt(
            birth=receipt.birth,
            tombstone=receipt.tombstone.model_copy(
                update={"spawn_nonce_sha256": "f" * 64}
            ),
            watchdog_closure_record_sha256=(
                receipt.watchdog_closure_record_sha256
            ),
        )
    with pytest.raises(ValidationError, match="identity differs"):
        BrokerChildCpuReceipt(
            birth=receipt.birth,
            tombstone=receipt.tombstone.model_copy(
                update={"birth_record_sha256": "e" * 64}
            ),
            watchdog_closure_record_sha256=(
                receipt.watchdog_closure_record_sha256
            ),
        )
    changed_birth = _child(request_id="another-request").birth
    changed_tombstone = _record_copy(
        receipt.tombstone,
        request_id="another-request",
        previous_record_sha256=changed_birth.record_sha256,
        birth_record_sha256=changed_birth.record_sha256,
    )
    with pytest.raises(ValidationError, match="crossed a request"):
        _exact_cpu(
            children=(
                BrokerChildCpuReceipt(
                    birth=changed_birth,
                    tombstone=changed_tombstone,
                    watchdog_closure_record_sha256=(
                        receipt.watchdog_closure_record_sha256
                    ),
                ),
            )
        )


def test_duplicate_or_unmatched_process_lineage_is_rejected() -> None:
    exact = _exact_cpu()
    duplicate = (exact.children[0], exact.children[0])
    with pytest.raises(ValidationError, match="canonical and unique"):
        ExactBrokerRequestCpuEvidence.model_validate(
            {
                **exact.model_dump(mode="python"),
                "children": duplicate,
                "tesseract_user_cpu_delta_ns": 200_000,
                "tesseract_system_cpu_delta_ns": 400_000,
                "total_cpu_delta_ns": 600_100,
            }
        )
    with pytest.raises(ValidationError, match="lacks broker lineage"):
        unmatched = SampledProcessIdentity(
            role="tesseract_child",
            pid=999,
            start_abstime=999,
            parent_pid=200,
            process_group_id=200,
            session_id=200,
        )
        ExactBrokerRequestCpuEvidence.model_validate(
            {
                **exact.model_dump(mode="python"),
                "sampled_process_identities": (
                    *exact.sampled_process_identities,
                    unmatched,
                ),
            }
        )


def test_sampled_child_pid_reuse_cannot_match_birth_identity() -> None:
    exact = _exact_cpu()
    child_sample = exact.sampled_process_identities[-1]
    reused = child_sample.model_copy(
        update={"start_abstime": child_sample.start_abstime + 1}
    )
    with pytest.raises(ValidationError, match="lacks broker lineage"):
        ExactBrokerRequestCpuEvidence.model_validate(
            {
                **exact.model_dump(mode="python"),
                "sampled_process_identities": (
                    *exact.sampled_process_identities[:-1],
                    reused,
                ),
            }
        )


def test_counter_regression_and_legacy_cpu_mix_are_rejected() -> None:
    exact = _exact_cpu()
    regressed_after = exact.worker_after.model_copy(update={"user_cpu_ns": 99})
    regressed_external = _external_copy(
        exact.end_external_sample,
        worker_sample=exact.end_external_sample.worker_sample.model_copy(
            update={"cpu": regressed_after}
        ),
    )
    with pytest.raises(ValidationError, match="counter regressed"):
        ExactBrokerRequestCpuEvidence.model_validate(
            {
                **exact.model_dump(mode="python"),
                "worker_after": regressed_after,
                "end_external_sample": regressed_external,
            }
        )
    boundary = _boundary(exact)
    with pytest.raises(ValidationError, match="legacy aggregate"):
        RequestResourceBoundary.model_validate(
            {**boundary.model_dump(mode="python"), "self_user_cpu_delta_ns": 1}
        )
    with pytest.raises(ValidationError, match="BEGIN was released before"):
        ExactBrokerRequestCpuEvidence.model_validate(
            {**exact.model_dump(mode="python"), "begin_release_monotonic_ns": 2}
        )
    with pytest.raises(ValidationError, match="receipt was released before"):
        ExactBrokerRequestCpuEvidence.model_validate(
            {**exact.model_dump(mode="python"), "receipt_release_monotonic_ns": 32}
        )


def test_quiescence_requires_separate_root_only_groups_and_echild() -> None:
    exact = _exact_cpu()
    begin = exact.begin
    with pytest.raises(ValidationError, match="root-only"):
        BrokerQuiescenceReceipt.model_validate(
            {
                **begin.model_dump(mode="python"),
                "broker_group_member_pids": (begin.broker.pid, 300),
            }
        )
    with pytest.raises(ValidationError):
        BrokerQuiescenceReceipt.model_validate(
            {**begin.model_dump(mode="python"), "wait4_nohang_disposition": "empty"}
        )
    with pytest.raises(ValidationError, match="fresh group and session"):
        type(begin.worker).model_validate(
            {**begin.worker.model_dump(mode="python"), "process_group_id": 999}
        )


def test_scratch_root_is_empty_stable_and_bracketed_after_external_samples() -> None:
    exact = _exact_cpu()
    inventory = exact.begin.request_root_inventory
    with pytest.raises(ValidationError, match="identity differs"):
        BrokerScratchInventory.model_validate(
            {**inventory.model_dump(mode="python"), "root_inode": 999}
        )
    changed_root = broker_scratch_inventory(
        root_device=inventory.root_device,
        root_inode=inventory.root_inode + 1,
        root_uid=inventory.root_uid,
        scan_started_monotonic_ns=3,
        scan_completed_monotonic_ns=3,
    )
    with pytest.raises(ValidationError, match="scratch-root identity changed"):
        ExactBrokerRequestCpuEvidence.model_validate(
            {
                **exact.model_dump(mode="python"),
                "begin_post_sample_scratch_inventory": changed_root,
                "begin_external_sample": _external_copy(
                    exact.begin_external_sample,
                    post_sample_scratch_inventory=changed_root,
                ),
            }
        )
    early_scan = broker_scratch_inventory(
        root_device=inventory.root_device,
        root_inode=inventory.root_inode,
        root_uid=inventory.root_uid,
        scan_started_monotonic_ns=2,
        scan_completed_monotonic_ns=2,
    )
    with pytest.raises(ValidationError, match="stable-edge sample custody"):
        ExactBrokerRequestCpuEvidence.model_validate(
            {
                **exact.model_dump(mode="python"),
                "begin_post_sample_scratch_inventory": early_scan,
                "begin_external_sample": _external_copy(
                    exact.begin_external_sample,
                    post_sample_scratch_inventory=early_scan,
                ),
            }
        )


def test_worker_and_broker_thread_fd_counts_must_return_to_request_baseline() -> None:
    exact = _exact_cpu()
    drifted_worker = exact.end_external_sample.worker_sample.model_copy(
        update={
            "thread_count": exact.end_external_sample.worker_sample.thread_count + 1,
            "native_thread_ids": (
                *exact.end_external_sample.worker_sample.native_thread_ids,
                1_005,
            ),
        }
    )
    with pytest.raises(ValidationError, match="thread/FD baseline drifted"):
        ExactBrokerRequestCpuEvidence.model_validate(
            {
                **exact.model_dump(mode="python"),
                "end_external_sample": _external_copy(
                    exact.end_external_sample, worker_sample=drifted_worker
                ),
            }
        )

    same_count_thread_replacement = (
        exact.end_external_sample.worker_sample.model_copy(
            update={
                "native_thread_ids": (
                    *exact.end_external_sample.worker_sample.native_thread_ids[:-1],
                    1_005,
                )
            }
        )
    )
    with pytest.raises(ValidationError, match="thread/FD baseline drifted"):
        ExactBrokerRequestCpuEvidence.model_validate(
            {
                **exact.model_dump(mode="python"),
                "end_external_sample": _external_copy(
                    exact.end_external_sample,
                    worker_sample=same_count_thread_replacement,
                ),
            }
        )

    original_inventory = (
        exact.end_external_sample.worker_sample.file_descriptor_inventory
    )
    original_descriptor = original_inventory.descriptors[0]
    assert original_descriptor.vnode is not None
    replacement_descriptor = native_file_descriptor_identity(
        **original_descriptor.model_dump(
            mode="python", exclude={"record_sha256", "vnode"}
        ),
        vnode=original_descriptor.vnode.model_copy(
            update={"resolved_path_sha256": _sha("replacement-fd-target")}
        ),
    )
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
        descriptors=(
            replacement_descriptor,
            *original_inventory.descriptors[1:],
        ),
    )
    same_count_fd_replacement = exact.end_external_sample.worker_sample.model_copy(
        update={"file_descriptor_inventory": replacement_inventory}
    )
    with pytest.raises(ValidationError, match="thread/FD baseline drifted"):
        ExactBrokerRequestCpuEvidence.model_validate(
            {
                **exact.model_dump(mode="python"),
                "end_external_sample": _external_copy(
                    exact.end_external_sample,
                    worker_sample=same_count_fd_replacement,
                ),
            }
        )


def test_raw_controller_resource_rows_are_recomputed_and_child_complete() -> None:
    exact = _exact_cpu()
    boundary = _boundary(exact)
    middle = boundary.controller_resource_sample_rows[1]
    with pytest.raises(ValidationError, match="resource sweep/aggregate differs"):
        ControllerRequestResourceSample.model_validate(
            {
                **middle.record.model_dump(mode="python"),
                "aggregate": middle.record.aggregate.model_copy(
                    update={
                        "rss_bytes": middle.record.aggregate.rss_bytes + 1
                    }
                ),
            }
        )
    delayed_worker = middle.record.processes[0].model_copy(
        update={
            "sample_started_monotonic_ns": middle.record.sweep_started_monotonic_ns,
            "sample_completed_monotonic_ns": (
                middle.record.sweep_started_monotonic_ns
                + PEAK_SAMPLE_EDGE_TOLERANCE_NS
                + 1
            ),
        }
    )
    delayed_processes = (delayed_worker, *middle.record.processes[1:])
    with pytest.raises(ValidationError, match="resource sweep/aggregate differs"):
        ControllerRequestResourceSample.model_validate(
            {
                **middle.record.model_dump(mode="python"),
                "processes": delayed_processes,
                "observed_monotonic_ns": max(
                    item.observed_monotonic_ns for item in delayed_processes
                ),
                "sweep_started_monotonic_ns": min(
                    item.sample_started_monotonic_ns
                    for item in delayed_processes
                ),
                "sweep_completed_monotonic_ns": max(
                    item.sample_completed_monotonic_ns
                    for item in delayed_processes
                ),
                "sweep_span_ns": (
                    max(
                        item.sample_completed_monotonic_ns
                        for item in delayed_processes
                    )
                    - min(
                        item.sample_started_monotonic_ns
                        for item in delayed_processes
                    )
                ),
            }
        )
    with pytest.raises(ValidationError, match="resource sweep/aggregate differs"):
        ControllerRequestResourceSample.model_validate(
            {
                **middle.record.model_dump(mode="python"),
                "sweep_span_ns": middle.record.sweep_span_ns + 1,
            }
        )
    with pytest.raises(ValidationError, match="row identity differs"):
        type(middle).model_validate(
            {**middle.model_dump(mode="python"), "row_sha256": "f" * 64}
        )

    start, _, end = boundary.controller_resource_sample_rows
    changed_prefix = end.record.child_watch_prefix.model_copy(
        update={"current_request_pre_exec_gated_sample_record_sha256s": ()}
    )
    relinked_end = controller_resource_sample_log_row(
        row_sequence=start.row_sequence + 1,
        previous_row_sha256=start.row_sha256,
        record=end.record.model_copy(update={"child_watch_prefix": changed_prefix}),
        retained_monotonic_ns=end.retained_monotonic_ns,
    )
    with pytest.raises(ValidationError, match="omit a broker child"):
        RequestResourceBoundary.model_validate(
            {
                **boundary.model_dump(mode="python"),
                "controller_resource_sample_rows": (start, relinked_end),
                "descendant_sample_count": 2,
                "descendant_maximum_gap_ns": 29,
                "descendant_peak_process_count": 2,
                "process_tree_peak_thread_count": 5,
            }
        )


def test_child_lineage_and_completed_count_bind_to_frozen_broker() -> None:
    exact = _exact_cpu()
    child = exact.children[0]
    with pytest.raises(
        (ValidationError, BrokerProtocolError),
        match="birth.*(?:chronology|custody)",
    ):
        _record_copy(child.birth, ppid=999)
    with pytest.raises(ValidationError, match="completed-spawn count"):
        ExactBrokerRequestCpuEvidence.model_validate(
            {
                **exact.model_dump(mode="python"),
                "end": exact.end.model_copy(update={"completed_spawn_count": 2}),
            }
        )
    with pytest.raises(
        (ValidationError, BrokerProtocolError),
        match="birth.*chronology",
    ):
        _record_copy(
            child.birth,
            registration_acknowledged_monotonic_ns=(
                child.birth.guard_release_a_monotonic_ns + 1
            ),
        )
    with pytest.raises(
        (ValidationError, BrokerProtocolError),
        match="birth.*chronology",
    ):
        _record_copy(
            child.birth,
            born_monotonic_ns=100,
            provisional_observed_monotonic_ns=101,
            registration_acknowledged_monotonic_ns=102,
            guard_release_a_monotonic_ns=103,
            birth_durable_acknowledged_monotonic_ns=104,
            exec_release_e_monotonic_ns=105,
        )
    early_birth = _record_copy(
        child.birth,
        born_monotonic_ns=2,
        broker_thread_observed_at_monotonic_ns=1,
        spawn_intent_durable_acknowledged_monotonic_ns=2,
        broker_thread_immediately_before_fork_observed_at_monotonic_ns=2,
        provisional_observed_monotonic_ns=2,
        registration_acknowledged_monotonic_ns=2,
        guard_release_a_monotonic_ns=2,
        birth_durable_acknowledged_monotonic_ns=2,
        exec_release_e_monotonic_ns=2,
        fork_denial=child.birth.fork_denial.model_copy(
            update={
                "native_fork_parent_returned_monotonic_ns": 2,
                "native_child_limit_acknowledged_monotonic_ns": 2,
                "native_python_release_n_monotonic_ns": 2,
                "child_guard_ready_observed_monotonic_ns": 2,
                "applied_at_monotonic_ns": 2,
            }
        ),
    )
    early_attestation = _native_runtime_attestation(
        pid=early_birth.pid,
        start_abstime=early_birth.start_abstime,
        operation=early_birth.operation,
        native_closure_sha256=early_birth.native_closure_sha256,
        executable_sha256=early_birth.executable.sha256,
        child_projection=dict(early_birth.native_child_config_projection),
        native_runtime_gate_source_sha256=(
            early_birth.native_runtime_gate_source_sha256
        ),
        native_runtime_gate_record_sha256=(
            early_birth.native_runtime_gate_record_sha256
        ),
        exec_release_e_monotonic_ns=2,
    )
    early_tombstone = _record_copy(
        child.tombstone,
        previous_record_sha256=early_birth.record_sha256,
        birth_record_sha256=early_birth.record_sha256,
        native_runtime_attestation=early_attestation,
    )
    early_child = BrokerChildCpuReceipt(
        birth=early_birth,
        tombstone=early_tombstone,
        watchdog_closure_record_sha256=child.watchdog_closure_record_sha256,
    )
    early_gated_sample = controller_pre_exec_gated_child_sample(
        pid=early_birth.pid,
        start_abstime=early_birth.start_abstime,
        ppid=early_birth.ppid,
        pgid=early_birth.pgid,
        sid=early_birth.sid,
        observed_monotonic_ns=2,
        user_cpu_ns=1,
        system_cpu_ns=1,
        rss_bytes=1,
        thread_count=1,
        file_descriptor_count=6,
        native_thread_ids=early_birth.native_thread_ids,
        open_fd_inventory_sha256=early_birth.open_fd_inventory_sha256,
        native_thread_inventory_sha256=(
            early_birth.native_thread_inventory_sha256
        ),
        child_ready_sha256=early_birth.child_ready_sha256,
    )
    with pytest.raises(ValidationError, match="predates BEGIN CPU samples"):
        ExactBrokerRequestCpuEvidence.model_validate(
            {
                **exact.model_dump(mode="python"),
                "children": (early_child,),
                "pre_exec_gated_child_samples": (early_gated_sample,),
            }
        )


def test_cpu_v2_boundary_rejects_late_sample_and_total_drift() -> None:
    exact = _exact_cpu()
    boundary = _boundary(exact)
    with pytest.raises(ValidationError, match="escaped request boundary"):
        RequestResourceBoundary.model_validate(
            {
                **boundary.model_dump(mode="python"),
                "boundary_ended_monotonic_ns": 30,
                "wall_cpu_capacity_ns": 580_000,
            }
        )
    with pytest.raises(ValidationError, match="total differs"):
        RequestResourceBoundary.model_validate(
            {**boundary.model_dump(mode="python"), "total_cpu_delta_ns": 1}
        )
    with pytest.raises(ValidationError, match="resource aggregates"):
        RequestResourceBoundary.model_validate(
            {
                **boundary.model_dump(mode="python"),
                "descendant_peak_rss_bytes": (
                    boundary.descendant_peak_rss_bytes - 1
                ),
            }
        )


def test_configuration_matrix_separates_direct_rollback_from_paired_broker() -> None:
    def projections(enabled: bool) -> dict[str, object]:
        settings = sanitized_configuration_projection(
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
        )
        environment_values = {
            "PATH": "/usr/bin",
            "PARSER_LATENCY_PREWARM_ENABLED": (
                "true" if enabled else "false"
            ),
            "PARSER_LATENCY_PREWARM_ARTIFACTS_SHA256": "a" * 64,
            "PARSER_LATENCY_PREWARM_DEPENDENCY_SHA256": "b" * 64,
            "PARSER_LATENCY_PREWARM_SHUTDOWN_GRACE_SECONDS": "2",
            "PARSER_LATENCY_PREWARM_TIMEOUT_SECONDS": "300",
            "PARSER_TESSERACT_EXECUTABLE": "/opt/tesseract",
            "PARSER_TESSERACT_EXECUTABLE_SHA256": "c" * 64,
            "PARSER_TESSERACT_EXTERNAL_BARRIERS": "true",
            "PARSER_TESSERACT_LANGUAGES": "eng",
            "PARSER_TESSERACT_NATIVE_CLOSURE_SHA256": "6" * 64,
            "PARSER_TESSERACT_NATIVE_FORK_PROBE_PATH": (
                "/private/tmp/fork-on.dylib"
                if enabled
                else "/private/tmp/fork-off.dylib"
            ),
            "PARSER_TESSERACT_NATIVE_FORK_PROBE_SHA256": (
                "7" * 64 if enabled else "8" * 64
            ),
            "PARSER_TESSERACT_NATIVE_SPAWN_GUARD_SHA256": (
                "9" * 64 if enabled else "0" * 64
            ),
            "PARSER_TESSERACT_NATIVE_SPAWN_GUARD_SOURCE_SHA256": "5" * 64,
            "PARSER_TESSERACT_SEATBELT_EXECUTABLE_SHA256": "d" * 64,
            "PARSER_TESSERACT_STAGED_EXECUTABLE_SHA256": "c" * 64,
            "PARSER_TESSERACT_TESSDATA_ROOT": "/opt/tessdata",
            "PARSER_TESSERACT_WORKER_PROFILE_SHA256": "e" * 64,
            "PARSER_TESSERACT_BROKER_PID": "201" if enabled else "200",
        }
        if not enabled:
            environment_values["PARSER_LATENCY_PRIVATE_BROKER_PREDECESSOR"] = (
                "true"
            )
        environment = sanitized_configuration_projection(
            domain="worker_environment",
            values=environment_values,
        )
        return {
            "application_settings_projection": settings,
            "worker_environment_projection": environment,
        }

    common = {
        "startup_timeout_ns": 300_000_000_000,
        "application_settings_sha256": "1" * 64,
        "worker_environment_sha256": "2" * 64,
        "artifacts_path": "approved/docling",
        "artifacts_path_identity_sha256": "3" * 64,
        "tesseract_executable": "/opt/tesseract",
        "tesseract_data_path": "/opt/tessdata",
    }
    direct = rollback_output_configuration_identity(**common, **projections(False))
    paired_off = production_configuration_identity(
        **common,
        **projections(False),
        prewarm_enabled=False,
        request_count=4,
    )
    paired_on = production_configuration_identity(
        **common,
        **projections(True),
        prewarm_enabled=True,
        request_count=4,
    )

    assert direct.execution_topology == "direct-default-off-v1"
    assert direct.broker_evidence_capability == "absent"
    assert paired_off.execution_topology == paired_on.execution_topology
    assert paired_off.broker_evidence_capability == "private-harness-v1"
    assert paired_off.prewarm_enabled is False
    assert paired_on.prewarm_enabled is True
    assert paired_off.pairing_sha256 == paired_on.pairing_sha256

    mutated = paired_on.model_dump(mode="json")
    mutated["pairing_sha256"] = "f" * 64
    mutated["sha256"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in mutated.items() if key != "sha256"},
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    with pytest.raises(ValidationError, match="pairing projection"):
        type(paired_on).model_validate(
            mutated
        )

    changed_settings = sanitized_configuration_projection(
        domain="application_settings",
        values={
            **asdict(Settings()),
            "max_pages": 101,
            "parser_latency_prewarm_artifacts_sha256": "a" * 64,
            "parser_latency_prewarm_dependency_sha256": "b" * 64,
            "parser_latency_prewarm_enabled": True,
            "parser_latency_prewarm_shutdown_grace_seconds": 2.0,
            "parser_latency_prewarm_timeout_seconds": 300.0,
        },
    )
    changed = production_configuration_identity(
        **common,
        application_settings_projection=changed_settings,
        worker_environment_projection=projections(True)[
            "worker_environment_projection"
        ],
        prewarm_enabled=True,
        request_count=4,
    )
    assert changed.pairing_sha256 != paired_on.pairing_sha256
    changed_fixed_environment = sanitized_configuration_projection(
        domain="worker_environment",
        values={
            "PATH": "/usr/bin",
            "PARSER_LATENCY_PREWARM_ENABLED": "true",
            "PARSER_LATENCY_PRIVATE_BROKER_PREDECESSOR": "false",
            "PARSER_LATENCY_PREWARM_ARTIFACTS_SHA256": "a" * 64,
            "PARSER_LATENCY_PREWARM_DEPENDENCY_SHA256": "b" * 64,
            "PARSER_LATENCY_PREWARM_SHUTDOWN_GRACE_SECONDS": "2",
            "PARSER_LATENCY_PREWARM_TIMEOUT_SECONDS": "300",
            "PARSER_TESSERACT_EXECUTABLE": "/opt/tesseract",
            "PARSER_TESSERACT_EXECUTABLE_SHA256": "c" * 64,
            "PARSER_TESSERACT_EXTERNAL_BARRIERS": "true",
            "PARSER_TESSERACT_LANGUAGES": "deu",
            "PARSER_TESSERACT_NATIVE_CLOSURE_SHA256": "6" * 64,
            "PARSER_TESSERACT_NATIVE_FORK_PROBE_PATH": "/private/tmp/fork-on.dylib",
            "PARSER_TESSERACT_NATIVE_FORK_PROBE_SHA256": "7" * 64,
            "PARSER_TESSERACT_NATIVE_SPAWN_GUARD_SHA256": "9" * 64,
            "PARSER_TESSERACT_NATIVE_SPAWN_GUARD_SOURCE_SHA256": "5" * 64,
            "PARSER_TESSERACT_SEATBELT_EXECUTABLE_SHA256": "d" * 64,
            "PARSER_TESSERACT_STAGED_EXECUTABLE_SHA256": "c" * 64,
            "PARSER_TESSERACT_TESSDATA_ROOT": "/opt/tessdata",
            "PARSER_TESSERACT_WORKER_PROFILE_SHA256": "e" * 64,
            "PARSER_TESSERACT_BROKER_PID": "201",
        },
    )
    changed_fixed = production_configuration_identity(
        **common,
        application_settings_projection=projections(True)[
            "application_settings_projection"
        ],
        worker_environment_projection=changed_fixed_environment,
        prewarm_enabled=True,
        request_count=4,
    )
    assert changed_fixed.pairing_sha256 != paired_on.pairing_sha256

    direct_projection = rollback_output_configuration_identity(
        **common,
        application_settings_projection=projections(False)[
            "application_settings_projection"
        ],
        worker_environment_projection=sanitized_configuration_projection(
            domain="worker_environment",
            values={
                key: value
                for key, value in {
                    "PATH": "/usr/bin",
                    "PARSER_LATENCY_PREWARM_ENABLED": "false",
                    "PARSER_LATENCY_PREWARM_ARTIFACTS_SHA256": "a" * 64,
                    "PARSER_LATENCY_PREWARM_DEPENDENCY_SHA256": "b" * 64,
                    "PARSER_LATENCY_PREWARM_SHUTDOWN_GRACE_SECONDS": "2",
                    "PARSER_LATENCY_PREWARM_TIMEOUT_SECONDS": "300",
                    "PARSER_TESSERACT_EXECUTABLE": "/opt/tesseract",
                    "PARSER_TESSERACT_EXECUTABLE_SHA256": "c" * 64,
                    "PARSER_TESSERACT_EXTERNAL_BARRIERS": "true",
                    "PARSER_TESSERACT_LANGUAGES": "eng",
                    "PARSER_TESSERACT_NATIVE_CLOSURE_SHA256": "6" * 64,
                    "PARSER_TESSERACT_NATIVE_SPAWN_GUARD_SOURCE_SHA256": "5" * 64,
                    "PARSER_TESSERACT_SEATBELT_EXECUTABLE_SHA256": "d" * 64,
                    "PARSER_TESSERACT_STAGED_EXECUTABLE_SHA256": "c" * 64,
                    "PARSER_TESSERACT_TESSDATA_ROOT": "/opt/tessdata",
                    "PARSER_TESSERACT_WORKER_PROFILE_SHA256": "e" * 64,
                }.items()
            },
        ),
    )
    assert configuration_rollback_equivalence_projection(direct_projection) == (
        configuration_rollback_equivalence_projection(paired_off)
    )


@pytest.mark.parametrize("enabled", (False, True))
def test_application_settings_projection_rejects_rehashed_behavior_omission(
    enabled: bool,
) -> None:
    values = asdict(Settings())
    values.update(
        {
            "parser_latency_prewarm_artifacts_sha256": (
                "a" * 64 if enabled else None
            ),
            "parser_latency_prewarm_dependency_sha256": (
                "b" * 64 if enabled else None
            ),
            "parser_latency_prewarm_enabled": enabled,
            "parser_latency_prewarm_shutdown_grace_seconds": 2.0,
            "parser_latency_prewarm_timeout_seconds": 300.0,
        }
    )
    values.pop("max_pages")
    with pytest.raises(ValidationError, match="closed key set"):
        sanitized_configuration_projection(
            domain="application_settings",
            values=values,
        )


def test_sanitized_pairing_projection_rejects_secret_or_unapproved_keys() -> None:
    hashed_only = sanitized_configuration_projection(
        domain="worker_environment",
        values={"PATH": "/private/sensitive/path"},
    )
    assert "/private/sensitive/path" not in hashed_only.model_dump_json()
    with pytest.raises(ValidationError, match="keys differ"):
        sanitized_configuration_projection(
            domain="worker_environment",
            values={"PATH": "/usr/bin", "SERVICE_API_KEY": "secret"},
        )
    with pytest.raises(ValidationError, match="allowlist"):
        projection = sanitized_configuration_projection(
            domain="worker_environment",
            values={"PATH": "/usr/bin"},
        )
        type(projection).model_validate(
            {
                **projection.model_dump(mode="python"),
                "instrumentation_values": (
                    {
                        "key": "UNAPPROVED_CAPABILITY",
                        "value_sha256": "a" * 64,
                        "classification": "dynamic_capability",
                    },
                ),
                "key_count": 2,
            }
        )


def test_production_configuration_requires_one_exact_worker_scratch_alias() -> None:
    settings = sanitized_configuration_projection(
        domain="application_settings",
        values={
            **asdict(Settings()),
            "max_pages": 100,
            "parser_latency_prewarm_artifacts_sha256": "a" * 64,
            "parser_latency_prewarm_dependency_sha256": "b" * 64,
            "parser_latency_prewarm_enabled": True,
            "parser_latency_prewarm_shutdown_grace_seconds": 2.0,
            "parser_latency_prewarm_timeout_seconds": 300.0,
        },
    )
    environment_values = {
        "PATH": "/usr/bin",
        "PARSER_LATENCY_PREWARM_ENABLED": "true",
        "PARSER_TESSERACT_WORKER_SCRATCH": "/private/tmp/worker-scratch",
        "PARSER_TESSERACT_REQUEST_ROOT": "/private/tmp/worker-scratch",
        "TMPDIR": "/private/tmp/worker-scratch",
        "TMP": "/private/tmp/worker-scratch",
        "TEMP": "/private/tmp/worker-scratch",
        "PARSER_TESSERACT_WORKER_SCRATCH_FD": "17",
        "PARSER_TESSERACT_REQUEST_ROOT_FD": "17",
    }

    def configuration(values: dict[str, str]):
        return production_configuration_identity(
            prewarm_enabled=True,
            startup_timeout_ns=300_000_000_000,
            request_count=4,
            application_settings_sha256="1" * 64,
            worker_environment_sha256="2" * 64,
            application_settings_projection=settings,
            worker_environment_projection=sanitized_configuration_projection(
                domain="worker_environment", values=values
            ),
            artifacts_path="approved/docling",
            artifacts_path_identity_sha256="3" * 64,
            tesseract_executable="/opt/tesseract",
            tesseract_data_path="/opt/tessdata",
        )

    assert configuration(environment_values).execution_topology == (
        "fork-denied-worker-external-tesseract-broker-v1"
    )
    with pytest.raises(ValidationError, match="scratch/request-root alias"):
        configuration({**environment_values, "TEMP": "/private/tmp/other"})
    with pytest.raises(ValidationError, match="scratch/request-root alias"):
        configuration(
            {
                key: value
                for key, value in environment_values.items()
                if key != "PARSER_TESSERACT_REQUEST_ROOT_FD"
            }
        )


def test_shared_child_runtime_models_losslessly_mirror_app_protocol() -> None:
    from app.services import tesseract_broker_protocol as app_protocol

    shared_types = (
        BrokerForkDenialIdentity,
        BrokerChildBirthCommitment,
        BrokerChildBirth,
        BrokerChildWait4Tombstone,
        NativeRuntimeImageAttestation,
        NativeRuntimeScanSample,
    )
    for shared_type in shared_types:
        app_type = getattr(app_protocol, shared_type.__name__)
        assert set(shared_type.model_fields) == {
            item.name for item in dataclass_fields(app_type)
        }
