from __future__ import annotations

from copy import deepcopy
import hashlib
import os
import signal
import socket
import struct
from types import SimpleNamespace
from typing import Any

import pytest

from app.services import tesseract_child_sandbox_probe as child_probe
from app.services.tesseract_broker_protocol import (
    BrokerProtocolError,
    NATIVE_CHILD_LIMIT_ACK_AUTHORITY,
    canonical_sha256,
    child_sandbox_probe_report_from_mapping,
    validate_child_sandbox_probe_report_against_plan,
)


def _plan(*, descriptor_count: int = 9) -> dict[str, Any]:
    executor_sha256 = "9" * 64
    operations: list[dict[str, Any]] = []
    for index in range(descriptor_count):
        operations.append(
            {
                "operation": f"read-root-{index}",
                "kind": "path",
                "operation_code": 5,
                "held_directory_fd": 10 + index,
                "primary_relative_path": "fixture.bin",
                "secondary_relative_path": None,
                "open_flags": os.O_RDONLY | getattr(os, "O_CLOEXEC", 0),
                "create_mode": None,
                "payload_hex": "",
            }
        )
    # Non-AF_UNIX calls have no directory capability and therefore do not
    # alter the exact nine-root cardinality.
    operations.append(
        {
            "operation": "tcp-connect",
            "kind": "network",
            "operation_code": 1,
            "held_directory_fd": -1,
            "domain": int(socket.AF_INET),
            "socket_type": int(socket.SOCK_STREAM),
            "protocol": 0,
            "sockaddr_hex": "0100",
            "payload_hex": "",
        }
    )
    plan: dict[str, Any] = {
        "schema_id": child_probe.CHILD_SANDBOX_PLAN_SCHEMA,
        "attempt_id": "child-probe-attempt",
        "attempt_nonce_sha256": "1" * 64,
        "scope_sha256": "2" * 64,
        "role": "tesseract_child",
        "profile_sha256": "3" * 64,
        "native_closure_sha256": "4" * 64,
        "probe_executor_authority": child_probe.CHILD_SANDBOX_EXECUTOR_AUTHORITY,
        "probe_executor_source_sha256": executor_sha256,
        "probe_library_path": "/private/tmp/child-probe.dylib",
        "probe_library_sha256": "5" * 64,
        "held_directories": [
            {
                "role": role,
                "descriptor": descriptor,
                "resolved_path": f"/private/tmp/child-probe-{role}",
                "path_sha256": hashlib.sha256(
                    f"/private/tmp/child-probe-{role}".encode()
                ).hexdigest(),
                "device": 1,
                "inode": 10_000 + descriptor,
                "mode": 0o040700,
                "uid": 501,
                "nlink": 2,
                "open_flags": 0,
            }
            for role, descriptor in zip(
                child_probe.CHILD_SANDBOX_HELD_DIRECTORY_ROLES,
                range(10, 19),
            )
        ],
        "operations": operations,
    }
    plan["plan_sha256"] = canonical_sha256(plan)
    return plan


def _descriptor_row(descriptor: int) -> dict[str, Any]:
    return {
        "fd": descriptor,
        "kernel_fd_type": 1,
        "descriptor_flags": 1,
        "status_flags": 0,
        "close_on_exec": True,
        "stat_device": 1,
        "stat_inode": 10_000 + descriptor,
        "stat_mode": 0o040700,
        "stat_mode_type": 0o040000,
        "stat_uid": 501,
        "stat_gid": 20,
        "stat_nlink": 2,
        "stat_size": 0,
    }


def _install_direct_executor_stubs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = iter(range(1_000_000, 1_100_000))

    def now() -> int:
        return next(clock)

    monkeypatch.setattr(child_probe.time, "monotonic_ns", now)
    monkeypatch.setattr(child_probe.resource, "getrlimit", lambda _kind: (0, 0))
    monkeypatch.setattr(child_probe.os, "getpid", lambda: 444)
    monkeypatch.setattr(child_probe.os, "getppid", lambda: 111)
    monkeypatch.setattr(child_probe.os, "getpgid", lambda _pid: 111)
    monkeypatch.setattr(child_probe.os, "getsid", lambda _pid: 111)
    monkeypatch.setattr(
        child_probe,
        "_raw_start_abstime",
        lambda pid: 222 if pid == 111 else 333,
    )

    def thread_inventory() -> dict[str, Any]:
        started = now()
        mapping: dict[str, Any] = {
            "schema_id": "parser-tesseract-child-sandbox-thread-inventory-v1",
            "process": child_probe._process_identity(),
            "identity_basis": (
                "darwin-proc_pidinfo-PROC_PIDLISTTHREADS-uint64-v1"
            ),
            "thread_ids": [777],
            "thread_count": 1,
            "scan_started_monotonic_ns": started,
            "scan_completed_monotonic_ns": now(),
        }
        mapping["inventory_sha256"] = child_probe._canonical_sha256(mapping)
        return mapping

    descriptors = [
        _descriptor_row(fd)
        for fd in (0, 1, 2, 10, 11, 12, 13, 14, 15, 16, 17, 18)
    ]

    def descriptor_inventory() -> dict[str, Any]:
        started = now()
        mapping: dict[str, Any] = {
            "schema_id": "parser-tesseract-child-sandbox-fd-inventory-v1",
            "process": child_probe._process_identity(),
            "identity_basis": (
                "darwin-proc_pidinfo-PROC_PIDLISTFDS-fstat-fcntl-v1"
            ),
            "descriptors": deepcopy(descriptors),
            "descriptor_count": len(descriptors),
            "scan_started_monotonic_ns": started,
            "scan_completed_monotonic_ns": now(),
        }
        mapping["inventory_sha256"] = child_probe._canonical_sha256(mapping)
        return mapping

    def run_operation(
        _library: object, operation: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        blocked = tuple(
            sorted(
                int(value)
                for value in signal.valid_signals()
                if value not in {signal.SIGKILL, signal.SIGSTOP}
            )
        )
        is_path = operation["kind"] == "path"
        invocation: dict[str, Any] = {
            "schema_id": "phase-latency-kernel-sandbox-native-invocation-v1",
            "abi_version": 2,
            "helper_function": (
                "lat_us02_sandbox_probe_path"
                if is_path
                else "lat_us02_sandbox_probe_network"
            ),
            "primary_relative_path_hex": (
                operation["primary_relative_path"].encode().hex()
                if is_path
                else None
            ),
            "secondary_relative_path_hex": None,
            "open_flags": operation["open_flags"] if is_path else None,
            "create_mode": operation["create_mode"] if is_path else None,
            "domain": None if is_path else operation["domain"],
            "socket_type": None if is_path else operation["socket_type"],
            "protocol": None if is_path else operation["protocol"],
            "sockaddr_hex": None if is_path else operation["sockaddr_hex"],
            "operation_code": operation["operation_code"],
            "held_directory_fd": operation["held_directory_fd"],
            "payload_hex": operation["payload_hex"],
            "payload_size_bytes": 0,
            "payload_sha256": hashlib.sha256(b"").hexdigest(),
            "native_thread_identity_basis": (
                "darwin-proc_pidinfo-PROC_PIDLISTTHREADS-uint64-v1"
            ),
            "native_thread_ids_before": [777],
            "native_thread_ids_after": [777],
            "prior_signal_mask": [],
            "blocked_signal_mask": list(blocked),
            "restored_signal_mask": [],
            "signals_blocked_at_monotonic_ns": now(),
            "syscall_returned_at_monotonic_ns": now(),
            "signals_restored_at_monotonic_ns": now(),
        }
        invocation["invocation_sha256"] = child_probe._canonical_sha256(invocation)
        operation_code = operation["operation_code"]
        terminal_stage = 5 if is_path else 10
        raw = struct.pack(
            "<iiiiqqqii",
            2,
            operation_code,
            terminal_stage,
            0,
            0,
            0,
            0,
            0,
            0,
        )
        result: dict[str, Any] = {
            "schema_id": "phase-latency-kernel-sandbox-native-result-v1",
            "abi_version": 2,
            "byte_order": "little-endian-darwin-v1",
            "struct_size_bytes": 48,
            "raw_struct_hex": raw.hex(),
            "raw_struct_sha256": hashlib.sha256(raw).hexdigest(),
            "operation_code": operation_code,
            "terminal_stage_code": terminal_stage,
            "raw_errno": 0,
            "syscall_return": 0,
            "bytes_sent": 0,
            "bytes_received": 0,
            "cwd_restore_return": 0,
            "cwd_restore_errno": 0,
            "top_level_return": 0,
            "top_level_errno": 0,
        }
        result["record_sha256"] = child_probe._canonical_sha256(result)
        return invocation, result

    monkeypatch.setattr(child_probe, "_thread_inventory", thread_inventory)
    monkeypatch.setattr(
        child_probe, "_file_descriptor_inventory", descriptor_inventory
    )
    monkeypatch.setattr(
        child_probe,
        "_load_probe",
        lambda _path, _sha: (SimpleNamespace(_handle=99), 99),
    )

    def held_observations(
        authorities: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], ...]:
        retained: list[dict[str, Any]] = []
        for authority in authorities:
            observation = {
                **authority,
                "scan_started_monotonic_ns": now(),
                "scan_completed_monotonic_ns": now(),
            }
            observation["record_sha256"] = child_probe._canonical_sha256(
                observation
            )
            retained.append(observation)
        return tuple(retained)

    monkeypatch.setattr(
        child_probe, "_held_directory_observations", held_observations
    )
    monkeypatch.setattr(child_probe, "_run_operation", run_operation)
    monkeypatch.setattr(child_probe._ctypes, "dlclose", lambda _handle: None)


def _run_direct(
    monkeypatch: pytest.MonkeyPatch,
    *,
    broker_start_abstime: int = 222,
) -> dict[str, Any]:
    _install_direct_executor_stubs(monkeypatch)
    plan = _plan()
    reservation = child_probe.child_sandbox_probe_report_reservation_bytes(plan)
    return child_probe.run_child_sandbox_probe_plan(
        plan,
        context={
            "request_id": "request-1",
            "request_epoch": 2,
            "request_sequence": 1,
            "spawn_sequence": 1,
            "spawn_nonce_sha256": "6" * 64,
            "native_child_limit_ack_authority": NATIVE_CHILD_LIMIT_ACK_AUTHORITY,
            "native_child_limit_ack_sha256": "7" * 64,
            "broker_pid": 111,
            "broker_start_abstime": broker_start_abstime,
        },
        executor_source_sha256="9" * 64,
        report_reservation_bytes=reservation,
    )


def _rehash_report(report: dict[str, Any]) -> None:
    report["rows_sha256"] = canonical_sha256({"rows": report["rows"]})
    report["record_sha256"] = canonical_sha256(
        {key: value for key, value in report.items() if key != "record_sha256"}
    )


def test_representative_child_probe_executes_raw_plan_and_round_trips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _run_direct(monkeypatch)

    typed = child_sandbox_probe_report_from_mapping(report)
    assert typed.row_count == 10
    assert typed.held_directory_fds == (10, 11, 12, 13, 14, 15, 16, 17, 18)
    assert typed.broker_pid == typed.process["ppid"] == 111
    assert (
        typed.broker_identity_before_probes["start_abstime"]
        == typed.broker_identity_after_probes["start_abstime"]
        == typed.broker_start_abstime
        == 222
    )


@pytest.mark.parametrize("descriptor_count", [8, 10])
def test_child_probe_requires_exact_nine_held_roots(
    descriptor_count: int,
) -> None:
    with pytest.raises(ValueError, match="nine roots|descriptor set"):
        child_probe.child_sandbox_probe_report_reservation_bytes(
            _plan(descriptor_count=descriptor_count)
        )


def test_child_probe_rejects_wrong_broker_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(RuntimeError, match="inherited authority"):
        _run_direct(monkeypatch, broker_start_abstime=223)


def test_child_probe_report_replays_native_result_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _run_direct(monkeypatch)
    result = report["rows"][0]["native_result"]
    raw = bytearray.fromhex(result["raw_struct_hex"])
    raw[12] = 1
    result["raw_struct_hex"] = bytes(raw).hex()
    result["raw_struct_sha256"] = hashlib.sha256(raw).hexdigest()
    result["record_sha256"] = canonical_sha256(
        {key: value for key, value in result.items() if key != "record_sha256"}
    )
    _rehash_report(report)

    with pytest.raises(BrokerProtocolError, match="native result"):
        child_sandbox_probe_report_from_mapping(report)


def test_child_probe_report_rejects_wrong_parent_start_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _run_direct(monkeypatch)
    report["broker_identity_after_probes"]["start_abstime"] += 1
    _rehash_report(report)

    with pytest.raises(BrokerProtocolError, match="broker observation after"):
        child_sandbox_probe_report_from_mapping(report)


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("attempt_id", "different-attempt"),
        ("attempt_nonce_sha256", "a" * 64),
        ("scope_sha256", "b" * 64),
        ("report_reservation_bytes", 256 * 1024),
    ),
)
def test_child_probe_report_rejects_rehashed_plan_authority_rebinding(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    replacement: object,
) -> None:
    plan = _plan()
    report = _run_direct(monkeypatch)
    report[field] = replacement
    _rehash_report(report)
    typed = child_sandbox_probe_report_from_mapping(report)

    with pytest.raises(BrokerProtocolError, match="report/plan .* binding"):
        validate_child_sandbox_probe_report_against_plan(typed, plan)


def test_child_probe_malformed_row_fails_closed_as_protocol_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _run_direct(monkeypatch)
    report["rows"][0] = "not-a-row"
    _rehash_report(report)

    with pytest.raises(BrokerProtocolError, match="raw rows"):
        child_sandbox_probe_report_from_mapping(report)
