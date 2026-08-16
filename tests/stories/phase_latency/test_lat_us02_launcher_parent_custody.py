from __future__ import annotations

import copy
from dataclasses import asdict

import pytest

from app.services.parser_worker_supervisor import validate_worker_ready_record
from app.services.tesseract_broker import (
    BROKER_READY_SCHEMA,
    validate_broker_ready_record,
)
from app.services.tesseract_broker_native import (
    NativeFileDescriptorIdentity,
    NativeFileDescriptorInventory,
    NativePipeFileDescriptorIdentity,
    NativeThreadInventory,
)
from app.services.tesseract_broker_protocol import (
    BrokerProtocolError,
    KernelProcessIdentity,
    TrustedLauncherIdentity,
    canonical_sha256,
)


SHA = "1" * 64
LAUNCHER = {
    "pid": 100,
    "start_abstime": 101,
    "ppid": 90,
    "pgid": 100,
    "sid": 100,
    "uid": 501,
    "euid": 501,
}


def _broker_kernel_inventories() -> tuple[dict[str, object], dict[str, object]]:
    process = KernelProcessIdentity(200, 201, 100, 200, 200)
    thread_mapping = {
        "schema_id": "darwin-detailed-thread-inventory-v1",
        "process": asdict(process),
        "identity_basis": (
            "darwin-proc_pidinfo-PROC_PIDLISTTHREADS-uint64-v1"
        ),
        "thread_ids": [700],
        "thread_count": 1,
    }
    threads = NativeThreadInventory(
        schema_id=thread_mapping["schema_id"],
        process=process,
        identity_basis=thread_mapping["identity_basis"],
        first_scan_started_monotonic_ns=250,
        first_scan_completed_monotonic_ns=251,
        second_scan_started_monotonic_ns=252,
        second_scan_completed_monotonic_ns=253,
        thread_ids=(700,),
        thread_count=1,
        inventory_sha256=canonical_sha256(thread_mapping),
    )
    pipe = NativePipeFileDescriptorIdentity(
        device=1,
        inode=2,
        mode=0o10600,
        nlink=1,
        uid=501,
        gid=20,
        pipe_status=0,
        local_handle_sha256="2" * 64,
        peer_handle_sha256="3" * 64,
    )
    descriptors: list[NativeFileDescriptorIdentity] = []
    for fd in (0, 7, 8):
        descriptor_mapping = {
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
            NativeFileDescriptorIdentity(
                **{
                    **descriptor_mapping,
                    "pipe": pipe,
                    "record_sha256": canonical_sha256(descriptor_mapping),
                }
            )
        )
    fd_digest_mapping = {
        "schema_id": "darwin-detailed-file-descriptor-inventory-v1",
        "process": asdict(process),
        "descriptors": [asdict(descriptor) for descriptor in descriptors],
    }
    descriptors = NativeFileDescriptorInventory(
        schema_id=fd_digest_mapping["schema_id"],
        process=process,
        first_scan_started_monotonic_ns=254,
        first_scan_completed_monotonic_ns=255,
        second_scan_started_monotonic_ns=256,
        second_scan_completed_monotonic_ns=257,
        descriptors=tuple(descriptors),
        inventory_sha256=canonical_sha256(fd_digest_mapping),
    )
    return asdict(threads), asdict(descriptors)


def _broker_ready() -> dict[str, object]:
    threads, descriptors = _broker_kernel_inventories()
    record: dict[str, object] = {
        "schema_id": BROKER_READY_SCHEMA,
        "attempt_nonce_sha256": SHA,
        "scope_sha256": SHA,
        "config_sha256": SHA,
        "controller": {"pid": 90, "start_abstime": 91},
        "launcher": dict(LAUNCHER),
        "broker": {
            "pid": 200,
            "start_abstime": 201,
            "ppid": 100,
            "pgid": 200,
            "sid": 200,
            "uid": 501,
            "euid": 501,
        },
        "capability": {},
        "profile_sha256": SHA,
        "executable_sha256": SHA,
        "tessdata_sha256": SHA,
        "native_closure_sha256": SHA,
        "native_trust_model": "frozen-native-closure-trusted-v1",
        "native_containment_claim": "none-trusted-pinned-native-computation",
        "native_spawn_guard_sha256": SHA,
        "native_spawn_guard_source_sha256": SHA,
        "native_runtime_gate_source_sha256": SHA,
        "native_runtime_gate_library_sha256": SHA,
        "native_runtime_gate_record_sha256": SHA,
        "watchdog_protocol_sha256": SHA,
        "ledger": {},
        "pre_release_thread_inventory": threads,
        "pre_release_file_descriptor_inventory": descriptors,
        "retired_descriptor_fds": [7, 8],
        "ready_at_monotonic_ns": 300,
    }
    record["ready_sha256"] = canonical_sha256(record)
    return record


def _worker_ready() -> dict[str, object]:
    fork_denial = {
        "launcher": dict(LAUNCHER),
        "launcher_pid": 100,
        "launcher_start_abstime": 101,
        "worker_parent_is_launcher": True,
        "broker_parent_is_launcher": True,
        "controller_pid": 90,
        "real_uid": 501,
        "effective_uid": 501,
        "broker_real_uid": 501,
        "broker_effective_uid": 501,
        "worker": {"pid": 300, "start_abstime": 301, "parent_pid": 100},
        "broker": {"pid": 200, "start_abstime": 201, "parent_pid": 100},
    }
    record: dict[str, object] = {
        "schema_id": "parser-fork-denied-worker-ready-v1",
        "attempt_nonce_sha256": SHA,
        "scope_sha256": SHA,
        "fork_denial": fork_denial,
        "ready_at_monotonic_ns": 400,
    }
    record["ready_sha256"] = canonical_sha256(record)
    return record


def _rehash(record: dict[str, object]) -> None:
    record.pop("ready_sha256", None)
    record["ready_sha256"] = canonical_sha256(record)


def test_trusted_launcher_identity_is_full_non_root_kernel_identity() -> None:
    assert TrustedLauncherIdentity(**LAUNCHER).pid == 100
    with pytest.raises(BrokerProtocolError):
        TrustedLauncherIdentity(**{**LAUNCHER, "euid": 0})
    with pytest.raises(BrokerProtocolError):
        TrustedLauncherIdentity(**{**LAUNCHER, "start_abstime": True})


def test_broker_ready_exactly_binds_launcher_and_physical_parent() -> None:
    record = _broker_ready()
    validated = validate_broker_ready_record(
        record,
        config_sha256=SHA,
        expected_pid=200,
        expected_start_abstime=201,
        expected_launcher=LAUNCHER,
    )
    assert validated["launcher"] == LAUNCHER

    drifted_launcher = copy.deepcopy(record)
    drifted_launcher["launcher"]["pgid"] = 999  # type: ignore[index]
    _rehash(drifted_launcher)
    with pytest.raises(BrokerProtocolError):
        validate_broker_ready_record(
            drifted_launcher,
            config_sha256=SHA,
            expected_pid=200,
            expected_start_abstime=201,
            expected_launcher=LAUNCHER,
        )

    wrong_parent = copy.deepcopy(record)
    wrong_parent["broker"]["ppid"] = 90  # type: ignore[index]
    _rehash(wrong_parent)
    with pytest.raises(BrokerProtocolError):
        validate_broker_ready_record(
            wrong_parent,
            config_sha256=SHA,
            expected_pid=200,
            expected_start_abstime=201,
            expected_launcher=LAUNCHER,
        )


def test_worker_ready_exactly_binds_launcher_and_both_physical_parents() -> None:
    record = _worker_ready()
    validate_worker_ready_record(
        record,
        expected_pid=300,
        expected_start_abstime=301,
        expected_scope_sha256=SHA,
        expected_launcher=LAUNCHER,
    )

    drifted = copy.deepcopy(record)
    drifted["fork_denial"]["launcher"]["sid"] = 999  # type: ignore[index]
    _rehash(drifted)
    with pytest.raises(BrokerProtocolError):
        validate_worker_ready_record(
            drifted,
            expected_pid=300,
            expected_start_abstime=301,
            expected_scope_sha256=SHA,
            expected_launcher=LAUNCHER,
        )

    wrong_parent = copy.deepcopy(record)
    wrong_parent["fork_denial"]["worker"]["parent_pid"] = 90  # type: ignore[index]
    _rehash(wrong_parent)
    with pytest.raises(BrokerProtocolError):
        validate_worker_ready_record(
            wrong_parent,
            expected_pid=300,
            expected_start_abstime=301,
            expected_scope_sha256=SHA,
            expected_launcher=LAUNCHER,
        )
