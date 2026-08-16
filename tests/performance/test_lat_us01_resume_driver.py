from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.benchmarks import latency_runner
from tests.benchmarks.latency_contracts import (
    AttemptSlot,
    ProcessIdentity,
    ProcessMetric,
    ProcessRole,
    SystemName,
)


REPOSITORY = Path(__file__).resolve().parents[2]
DRIVER_PATH = REPOSITORY / "tracker/phase-latency/run_lat_us01_resume.py"


def _load_driver():
    module_name = "lat_us01_resume_driver_for_test"
    spec = importlib.util.spec_from_file_location(module_name, DRIVER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _slot(*, slot_id: str, order_index: int, case_id: str) -> AttemptSlot:
    return AttemptSlot(
        slot_id=slot_id,
        order_index=order_index,
        case_id=case_id,
        pair_index=1,
        system=SystemName.CANDIDATE,
    )


def test_concurrent_role_checkpoint_waits_for_both_workers_and_orders_slots() -> None:
    driver = _load_driver()
    retained = []
    ny = _slot(
        slot_id="ny-timetable-bound2-cold-json",
        order_index=46,
        case_id="ny-timetable",
    )
    uber = _slot(
        slot_id="uber-earnings-bound2-cold-json",
        order_index=47,
        case_id="uber-earnings",
    )
    buffer = driver._ConcurrentRoleCheckpointBuffer(
        lambda slot, execution_id, run: retained.append(
            (slot.slot_id, execution_id, run.role)
        ),
        slot_order={ny.slot_id: 46, uber.slot_id: 47},
    )

    authoritative = SimpleNamespace(role="authoritative_uninstrumented")
    diagnostic = SimpleNamespace(role="diagnostic_instrumented")
    buffer(uber, "uber-auth", authoritative)
    assert retained == []
    buffer(ny, "ny-auth", authoritative)
    assert retained == []
    buffer.flush_role(authoritative.role)
    assert retained == [
        (ny.slot_id, "ny-auth", authoritative.role),
        (uber.slot_id, "uber-auth", authoritative.role),
    ]
    with pytest.raises(RuntimeError, match="incomplete"):
        buffer.assert_complete()

    buffer(uber, "uber-diag", diagnostic)
    assert len(retained) == 2
    buffer(ny, "ny-diag", diagnostic)
    assert len(retained) == 2
    buffer.flush_role(diagnostic.role)
    buffer.assert_complete()
    assert retained[-2:] == [
        (ny.slot_id, "ny-diag", diagnostic.role),
        (uber.slot_id, "uber-diag", diagnostic.role),
    ]


def test_concurrent_role_checkpoint_flushes_partial_terminal_round() -> None:
    driver = _load_driver()
    retained = []
    ny = _slot(
        slot_id="ny-timetable-bound2-cold-json",
        order_index=46,
        case_id="ny-timetable",
    )
    buffer = driver._ConcurrentRoleCheckpointBuffer(
        lambda slot, execution_id, run: retained.append(
            (slot.slot_id, execution_id, run.role)
        ),
        slot_order={
            "ny-timetable-bound2-cold-json": 46,
            "uber-earnings-bound2-cold-json": 47,
        },
    )
    run = SimpleNamespace(role="authoritative_uninstrumented")
    buffer(ny, "ny-auth", run)
    buffer.flush_pending()
    assert retained == [(ny.slot_id, "ny-auth", run.role)]
    with pytest.raises(RuntimeError, match="lifecycle differs"):
        buffer(ny, "ny-auth-duplicate", run)


def test_parallel_member_snapshot_preserves_exact_member_aggregation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = _load_driver()

    class FakeProcess:
        def __init__(self, pid: int, created: float) -> None:
            self.pid = pid
            self._created = created

        def create_time(self) -> float:
            return self._created

    root = FakeProcess(100, 1.0)
    child = FakeProcess(101, 2.0)
    processes = {100: root, 101: child}
    monkeypatch.setattr(
        latency_runner.psutil,
        "Process",
        lambda pid: processes[pid],
    )
    monkeypatch.setattr(
        latency_runner,
        "_direct_child_processes",
        lambda process: [child] if process.pid == root.pid else [],
    )
    monkeypatch.setattr(
        latency_runner,
        "_process_role",
        lambda process, *, root_pid: ProcessRole.TESSERACT,
    )

    def metric(process, *, role, worker):
        value = process.pid
        return ProcessMetric(
            identity=ProcessIdentity(
                pid=process.pid,
                create_time_ns=int(process.create_time() * 1_000_000_000),
                role=role,
            ),
            rss_bytes=value,
            user_cpu_ns=value * 2,
            system_cpu_ns=value * 3,
            thread_count=1,
            fd_count=2,
            self_hwm_bytes=value if worker else None,
        )

    monkeypatch.setattr(latency_runner, "_process_metric", metric)
    snapshot = driver._parallel_member_process_tree_snapshot(
        root.pid,
        observed_monotonic_ns=123,
    )
    assert tuple(item.identity.pid for item in snapshot.members) == (100, 101)
    assert tuple(item.identity.role for item in snapshot.members) == (
        ProcessRole.CANDIDATE_WORKER,
        ProcessRole.TESSERACT,
    )
    assert snapshot.total_rss_bytes == 201
    assert snapshot.total_user_cpu_ns == 402
    assert snapshot.total_system_cpu_ns == 603
    assert snapshot.total_thread_count == 2
    assert snapshot.total_fd_count == 4


def test_continuation_rejects_an_existing_diagnostic_hwm_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = _load_driver()
    monkeypatch.setattr(
        driver.profile_set,
        "_tree_is_complete_and_sane",
        lambda tree, *, logical_cpu_count: logical_cpu_count == 8,
    )
    monkeypatch.setitem(driver.profile_set.M0_CASE_HWM_BYTES, "case", 1_000)
    monkeypatch.setattr(driver.profile_set, "PER_WORKER_DELTA_BYTES", 64)
    identity = SimpleNamespace(
        environment_manifest=SimpleNamespace(logical_cpu_count=8)
    )
    authoritative = SimpleNamespace(peak_worker_hwm_bytes=900)
    attempt = SimpleNamespace(
        case_id="case",
        process_tree=authoritative,
        diagnostic_process_tree=SimpleNamespace(peak_worker_hwm_bytes=964),
    )
    assert driver._attempt_passes_resource_continuation_gate(
        attempt,
        identity=identity,
    )

    attempt.diagnostic_process_tree = SimpleNamespace(peak_worker_hwm_bytes=965)
    assert not driver._attempt_passes_resource_continuation_gate(
        attempt,
        identity=identity,
    )
