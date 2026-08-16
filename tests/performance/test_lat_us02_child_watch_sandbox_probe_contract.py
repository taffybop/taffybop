"""Focused watchdog custody for the representative child sandbox probe."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, is_dataclass
import time
from types import SimpleNamespace
from typing import Any

import psutil
import pytest

from app.services import tesseract_child_sandbox_probe as child_probe
from app.services.tesseract_broker_protocol import (
    CHILD_SANDBOX_BIRTH_BINDING_FIELDS,
    BrokerChildWait4Tombstone,
    BrokerProtocolError,
    NativeRuntimeImageAttestation,
    NativeRuntimeScanSample,
    canonical_sha256,
    child_sandbox_probe_inheritance_sha256,
    child_watch_birth_from_commitment,
    replay_broker_audit_blob_bundle,
)
from tests.performance import test_lat_us02_production_adapter_contract as fixtures
from tests.stories.phase_latency.test_lat_us02_child_sandbox_probe import (
    _install_direct_executor_stubs,
    _plan as base_sandbox_plan,
)


def _wire(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _wire(asdict(value))
    if isinstance(value, dict):
        return {key: _wire(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_wire(item) for item in value]
    return value


def _representative_plan() -> dict[str, Any]:
    plan = base_sandbox_plan()
    plan.update(
        {
            "attempt_nonce_sha256": "3" * 64,
            "scope_sha256": "4" * 64,
            "native_closure_sha256": "6" * 64,
        }
    )
    plan["plan_sha256"] = canonical_sha256(
        {key: value for key, value in plan.items() if key != "plan_sha256"}
    )
    return plan


def _representative_report(plan: dict[str, Any]) -> dict[str, Any]:
    local_patch = pytest.MonkeyPatch()
    try:
        _install_direct_executor_stubs(local_patch)
        local_patch.setattr(child_probe.os, "getpid", lambda: 43_001)
        local_patch.setattr(child_probe.os, "getppid", lambda: 42_001)
        local_patch.setattr(child_probe.os, "getpgid", lambda _pid: 42_001)
        local_patch.setattr(child_probe.os, "getsid", lambda _pid: 42_001)
        local_patch.setattr(
            child_probe,
            "_raw_start_abstime",
            lambda pid: 52_001 if pid == 42_001 else 53_001,
        )
        reservation = child_probe.child_sandbox_probe_report_reservation_bytes(
            plan
        )
        return child_probe.run_child_sandbox_probe_plan(
            plan,
            context={
                "request_id": "request-1",
                "request_epoch": 2,
                "request_sequence": 1,
                "spawn_sequence": 1,
                "spawn_nonce_sha256": "7" * 64,
                "native_child_limit_ack_authority": (
                    "native-fixed-binary-pipe-PN0ACK1-big-endian-v1"
                ),
                "native_child_limit_ack_sha256": fixtures.native_child_limit_ack_sha256(
                    pid=43_001,
                    applied_monotonic_ns=123_456_789,
                ),
                "broker_pid": 42_001,
                "broker_start_abstime": 52_001,
            },
            executor_source_sha256=plan["probe_executor_source_sha256"],
            report_reservation_bytes=reservation,
        )
    finally:
        local_patch.undo()


def _child_intent(
    *,
    registry: fixtures._ChildWatchRegistry,
    registration: dict[str, Any],
    register_ack: dict[str, Any],
) -> dict[str, Any]:
    join = registry.audit_joins[registration["registration_sha256"]]
    return {
        "request_id": registration["request_id"],
        "request_epoch": registration["request_epoch"],
        "request_sequence": registration["request_sequence"],
        "spawn_sequence": registration["spawn_sequence"],
        "spawn_nonce_sha256": registration["spawn_nonce_sha256"],
        "pid": registration["pid"],
        "start_abstime": registration["start_abstime"],
        "child_ready_sha256": "9" * 64,
        "spawn_intent_sha256": registration["spawn_intent_sha256"],
        "spawn_intent_ledger_row_sha256": registration[
            "spawn_intent_ledger_row_sha256"
        ],
        "provisional_child_ledger_row_sha256": registration[
            "provisional_child_ledger_row_sha256"
        ],
        "provisional_record_sha256": join["provisional_record_sha256"],
        "watchdog_registration_sha256": registration["registration_sha256"],
        "watchdog_registration_ack_sha256": register_ack[
            "watchdog_record_sha256"
        ],
    }


def _bind_sandbox_birth(
    commitment: dict[str, Any],
    *,
    plan: dict[str, Any],
    report: dict[str, Any],
    report_row_sha256: str,
) -> dict[str, Any]:
    commitment.update(
        {
            "child_sandbox_probe_mode": "representative-full-matrix",
            "child_sandbox_probe_plan_sha256": plan["plan_sha256"],
            "child_sandbox_probe_executor_authority": report[
                "executor_authority"
            ],
            "child_sandbox_probe_executor_source_sha256": report[
                "executor_source_sha256"
            ],
            "child_sandbox_probe_library_sha256": report[
                "probe_library_sha256"
            ],
            "child_sandbox_probe_representative_report_sha256": report[
                "record_sha256"
            ],
            "child_sandbox_probe_report_ledger_row_sha256": report_row_sha256,
            "child_sandbox_probe_report_reservation_bytes": report[
                "report_reservation_bytes"
            ],
            "child_guard_applied_at_monotonic_ns": report[
                "completed_at_monotonic_ns"
            ]
            + 1,
            "child_reported_guard_release_a_monotonic_ns": report[
                "completed_at_monotonic_ns"
            ]
            + 2,
        }
    )
    commitment["child_guard_release_a_record_sha256"] = canonical_sha256(
        {
            "schema_id": "parser-tesseract-child-release-v1",
            "pid": commitment["pid"],
            "released_monotonic_ns": commitment[
                "child_reported_guard_release_a_monotonic_ns"
            ],
            "ready_record_sha256": commitment["child_ready_sha256"],
        }
    )
    commitment["birth_commitment_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in commitment.items()
            if key != "birth_commitment_sha256"
        }
    )
    return commitment


def _install_runtime_fixture_adapters(
    monkeypatch: pytest.MonkeyPatch,
    commitment: dict[str, Any],
) -> None:
    def attestation_factory(**raw: Any) -> NativeRuntimeImageAttestation:
        fields = dict(raw)
        fields.update(
            {
                name: commitment[name]
                for name in CHILD_SANDBOX_BIRTH_BINDING_FIELDS
            }
        )
        fields.pop("record_sha256", None)
        fields["record_sha256"] = canonical_sha256(_wire(fields))
        return NativeRuntimeImageAttestation(**fields)

    def tombstone_factory(**raw: Any) -> BrokerChildWait4Tombstone:
        fields = dict(raw)
        attestation = fields["native_runtime_attestation"]
        fields["child_sandbox_probe_inheritance_sha256"] = (
            child_sandbox_probe_inheritance_sha256(
                request_id=fields["request_id"],
                request_epoch=fields["request_epoch"],
                request_sequence=fields["request_sequence"],
                spawn_sequence=fields["spawn_sequence"],
                spawn_nonce_sha256=fields["spawn_nonce_sha256"],
                pid=fields["pid"],
                start_abstime=fields["start_abstime"],
                attestation=attestation,
            )
        )
        fields.pop("record_sha256", None)
        fields["record_sha256"] = canonical_sha256(_wire(fields))
        return BrokerChildWait4Tombstone(**fields)

    monkeypatch.setattr(
        fixtures, "AppNativeRuntimeImageAttestation", attestation_factory
    )
    monkeypatch.setattr(fixtures, "AppBrokerChildWait4Tombstone", tombstone_factory)


def test_watchdog_orders_and_joins_representative_probe_through_wait4(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _representative_plan()
    report = _representative_report(plan)
    reservation = child_probe.child_sandbox_probe_report_reservation_bytes(plan)
    original_projection = fixtures._native_child_config_projection_fixture

    def sandbox_projection(*, broker_pid: int) -> dict[str, Any]:
        projection = original_projection(broker_pid=broker_pid)
        projection.update(
            {
                "child_sandbox_probe_mode": "representative-full-matrix",
                "child_sandbox_probe_executor_authority": report[
                    "executor_authority"
                ],
                "child_sandbox_probe_executor_source_sha256": report[
                    "executor_source_sha256"
                ],
                "child_sandbox_probe_plan": deepcopy(plan),
                "child_sandbox_probe_report_reservation_bytes": reservation,
                "child_sandbox_probe_representative_report_sha256": "0" * 64,
            }
        )
        return projection

    monkeypatch.setattr(
        fixtures, "_native_child_config_projection_fixture", sandbox_projection
    )
    registry, peer, registration = (
        fixtures._child_watch_native_ack_registration_fixture(
            tmp_path / "representative-probe-watch"
        )
    )
    try:
        peer.send("child_watch_register", registration)
        registry.service_available()
        _, register_ack, body = peer.receive(
            expected_kind="child_watch_register_ack"
        )
        assert body == b""
        assert isinstance(register_ack, dict)
        fixtures._append_child_watch_audit_row(
            registry,
            peer,
            kind="watchdog_register_ack",
            record=register_ack,
        )

        intent = _child_intent(
            registry=registry,
            registration=registration,
            register_ack=register_ack,
        )
        with pytest.raises(BrokerProtocolError, match="kind/order"):
            fixtures._append_child_watch_audit_row(
                registry,
                peer,
                kind="child_intent",
                record=intent,
            )

        report_row_sha256 = fixtures._append_child_watch_audit_row(
            registry,
            peer,
            kind="child_sandbox_probe",
            record=report,
        )
        intent_row_sha256 = fixtures._append_child_watch_audit_row(
            registry,
            peer,
            kind="child_intent",
            record=intent,
        )
        commitment = _bind_sandbox_birth(
            fixtures._child_birth_commitment_fixture(
                registry=registry,
                registration=registration,
            ),
            plan=plan,
            report=report,
            report_row_sha256=report_row_sha256,
        )

        wrong_report_row = deepcopy(commitment)
        wrong_report_row[
            "child_sandbox_probe_report_ledger_row_sha256"
        ] = "f" * 64
        wrong_report_row["birth_commitment_sha256"] = canonical_sha256(
            {
                key: value
                for key, value in wrong_report_row.items()
                if key != "birth_commitment_sha256"
            }
        )
        with pytest.raises(BrokerProtocolError, match="commitment join"):
            registry._validate_child_birth_row(wrong_report_row, "e" * 64)

        birth_row_sha256 = fixtures._append_child_watch_audit_row(
            registry,
            peer,
            kind="child_birth",
            record=commitment,
        )
        replay = replay_broker_audit_blob_bundle(
            compact_ledger=registry.ledger.path.read_bytes(),
            record_blobs={
                path.name: path.read_bytes()
                for path in registry.ledger.record_blob_root_path.iterdir()
            },
            event_blobs={
                path.name: path.read_bytes()
                for path in registry.ledger.event_blob_root_path.iterdir()
            },
        )
        assert [row["kind"] for row in replay["rows"][-4:]] == [
            "watchdog_register_ack",
            "child_sandbox_probe",
            "child_intent",
            "child_birth",
        ]
        assert registry.pending_intent is None
        assert registry.pending_birth is not None
        assert registry.audit_joins[registration["registration_sha256"]][
            "child_ready_intent_row_sha256"
        ] == intent_row_sha256
        assert {
            name: registry.pending_birth[name]
            for name in CHILD_SANDBOX_BIRTH_BINDING_FIELDS
        } == {name: commitment[name] for name in CHILD_SANDBOX_BIRTH_BINDING_FIELDS}

        reported_fds = tuple(
            (item["fd"], item["kernel_fd_type"])
            for item in commitment["open_file_descriptors"]
        )
        reported_threads = tuple(commitment["native_thread_ids"])
        from app.services import tesseract_broker_native as native_module
        from tests.benchmarks import latency_prewarm_cpu as cpu_module

        monkeypatch.setattr(
            native_module,
            "native_file_descriptor_inventory",
            lambda _pid: reported_fds,
        )
        monkeypatch.setattr(
            native_module,
            "native_thread_inventory",
            lambda _pid: reported_threads,
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

        class FakeChildProcess:
            def __init__(self, pid: int) -> None:
                assert pid == registration["pid"]

            def __enter__(self) -> "FakeChildProcess":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def oneshot(self) -> "FakeChildProcess":
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

        monkeypatch.setattr(psutil, "Process", FakeChildProcess)
        birth = child_watch_birth_from_commitment(
            commitment,
            birth_ledger_row_sha256=birth_row_sha256,
        )
        fixtures._send_child_watch_frame_while_servicing(
            registry,
            peer,
            kind="child_watch_birth",
            payload={**birth, "watch_birth_sha256": canonical_sha256(birth)},
        )
        _, birth_ack, body = peer.receive(expected_kind="child_watch_birth_ack")
        assert body == b""
        fixtures._append_child_watch_audit_row(
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
            "birth_commitment_sha256": commitment["birth_commitment_sha256"],
            "watchdog_birth_ack_sha256": birth_ack["watchdog_record_sha256"],
            "exec_release_e_monotonic_ns": exec_release_e,
        }
        fixtures._append_child_watch_audit_row(
            registry,
            peer,
            kind="child_exec_release",
            record=exec_release,
        )

        _install_runtime_fixture_adapters(monkeypatch, commitment)
        transition, _ = fixtures._runtime_gate_tombstone_fixture(
            commitment=commitment,
            exec_release_e_monotonic_ns=exec_release_e,
            runtime_gate_row_sha256="5" * 64,
        )
        runtime_gate_row_sha256 = fixtures._append_child_watch_audit_row(
            registry,
            peer,
            kind="child_runtime_gate",
            record=transition,
        )
        replayed_transition, tombstone = fixtures._runtime_gate_tombstone_fixture(
            commitment=commitment,
            exec_release_e_monotonic_ns=exec_release_e,
            runtime_gate_row_sha256=runtime_gate_row_sha256,
        )
        assert replayed_transition == transition

        bad_attestation_fields = asdict(tombstone.native_runtime_attestation)
        bad_attestation_fields["scan_samples"] = tuple(
            NativeRuntimeScanSample(**sample)
            for sample in bad_attestation_fields["scan_samples"]
        )
        bad_attestation_fields[
            "child_sandbox_probe_report_ledger_row_sha256"
        ] = "f" * 64
        bad_attestation_fields["record_sha256"] = canonical_sha256(
            {
                key: _wire(value)
                for key, value in bad_attestation_fields.items()
                if key != "record_sha256"
            }
        )
        bad_attestation = NativeRuntimeImageAttestation(
            **bad_attestation_fields
        )
        bad_tombstone_fields = asdict(tombstone)
        bad_tombstone_fields["rusage"] = tombstone.rusage
        bad_tombstone_fields["native_runtime_attestation"] = bad_attestation
        bad_tombstone_fields["child_sandbox_probe_inheritance_sha256"] = (
            child_sandbox_probe_inheritance_sha256(
                request_id=tombstone.request_id,
                request_epoch=tombstone.request_epoch,
                request_sequence=tombstone.request_sequence,
                spawn_sequence=tombstone.spawn_sequence,
                spawn_nonce_sha256=tombstone.spawn_nonce_sha256,
                pid=tombstone.pid,
                start_abstime=tombstone.start_abstime,
                attestation=bad_attestation,
            )
        )
        bad_tombstone_fields["record_sha256"] = canonical_sha256(
            {
                key: _wire(value)
                for key, value in bad_tombstone_fields.items()
                if key != "record_sha256"
            }
        )
        bad_tombstone = BrokerChildWait4Tombstone(**bad_tombstone_fields)
        with pytest.raises(BrokerProtocolError, match="child wait4 row join"):
            registry._validate_child_wait4_row(_wire(bad_tombstone), "d" * 64)

        tombstone_row_sha256 = fixtures._append_child_watch_audit_row(
            registry,
            peer,
            kind="child_wait4",
            record=asdict(tombstone),
        )
        attestation = tombstone.native_runtime_attestation
        assert {
            name: getattr(attestation, name)
            for name in CHILD_SANDBOX_BIRTH_BINDING_FIELDS
        } == {name: commitment[name] for name in CHILD_SANDBOX_BIRTH_BINDING_FIELDS}
        join = registry.audit_joins[registration["registration_sha256"]]
        assert join["runtime_gate_row_sha256"] == runtime_gate_row_sha256
        assert join["wait4_row_sha256"] == tombstone_row_sha256

        registry.runtime.kernel_process_identity = (
            lambda pid: (_ for _ in ()).throw(ProcessLookupError(pid))
        )
        attestation = tombstone.native_runtime_attestation
        reaped = {
            "request_id": registration["request_id"],
            "request_epoch": registration["request_epoch"],
            "request_sequence": registration["request_sequence"],
            "spawn_sequence": registration["spawn_sequence"],
            "spawn_nonce_sha256": registration["spawn_nonce_sha256"],
            "pid": registration["pid"],
            "start_abstime": registration["start_abstime"],
            "registration_sha256": registration["registration_sha256"],
            "birth_record_sha256": commitment["birth_commitment_sha256"],
            "tombstone_record_sha256": tombstone.record_sha256,
            "raw_wait_status": tombstone.raw_wait_status,
            "wait4_observed_monotonic_ns": tombstone.observed_monotonic_ns,
            "tombstone_ledger_row_sha256": tombstone_row_sha256,
            "native_runtime_attestation_sha256": attestation.record_sha256,
            "native_runtime_scan_log_sha256": attestation.scan_log_sha256,
            "guard_to_exec_transition_sha256": (
                attestation.guard_to_exec_transition_sha256
            ),
            "native_closure_post_wait4_sha256": (
                attestation.static_closure_post_wait4_sha256
            ),
        }
        reaped["reaped_record_sha256"] = canonical_sha256(reaped)
        fixtures._send_child_watch_frame_while_servicing(
            registry,
            peer,
            kind="child_watch_reaped",
            payload=reaped,
        )
        _, reaped_ack, body = peer.receive(
            expected_kind="child_watch_reaped_ack"
        )
        assert body == b""
        fixtures._append_child_watch_audit_row(
            registry,
            peer,
            kind="watchdog_reaped_ack",
            record=reaped_ack,
        )
        assert registry.open == {}
        assert registry.registered_count == registry.reaped_count == 1
        snapshot = registry.terminal_snapshot()
        assert snapshot[
            "child_watch_sandbox_representative_report_sha256"
        ] == report["record_sha256"]
        assert snapshot[
            "child_watch_sandbox_report_ledger_row_sha256"
        ] == report_row_sha256
        assert snapshot[
            "child_watch_sandbox_representative_registration_sha256"
        ] == registration["registration_sha256"]
        assert snapshot["child_watch_sandbox_inheritance_count"] == 1
        assert snapshot[
            "child_watch_sandbox_inheritance_head_sha256"
        ] != "0" * 64
    finally:
        peer.close()
        registry.close()
