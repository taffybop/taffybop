"""Native integral counter tests for the LAT-US02 CPU-v2 adapter."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

import pytest

from tests.benchmarks.latency_prewarm_contracts import (
    ExactProcessIdentity,
    ResourcePhase,
)
from tests.benchmarks.latency_prewarm_cpu import (
    darwin_process_group_pids,
    read_darwin_process_identity,
    sample_darwin_process_group_metrics,
    sample_darwin_process_self_cpu,
)
from tests.benchmarks.latency_prewarm_production_worker import (
    _dual_group_resource_sample,
)


pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="LAT-US02 production CPU-v2 authority is Darwin-only",
)


def test_native_self_counter_is_integral_monotone_and_identity_bound() -> None:
    identity = read_darwin_process_identity(os.getpid())
    deadline = time.monotonic_ns() + 50_000_000
    accumulator = 0
    while time.monotonic_ns() < deadline:
        accumulator += 1
    assert accumulator > 0
    after = sample_darwin_process_self_cpu(
        pid=identity.pid,
        expected_start_abstime=identity.start_abstime,
        expected_parent_pid=identity.parent_pid,
        expected_process_group_id=identity.process_group_id,
        expected_session_id=identity.session_id,
    )

    assert isinstance(after.user_cpu_ns, int)
    assert isinstance(after.system_cpu_ns, int)
    assert after.user_cpu_ns >= identity.user_cpu_ns
    assert after.system_cpu_ns >= identity.system_cpu_ns
    assert after.observed_monotonic_ns >= identity.observed_monotonic_ns


@pytest.mark.parametrize(
    "field,delta",
    (("start", 1), ("parent", 1), ("group", 1), ("session", 1)),
)
def test_native_self_counter_rejects_every_identity_drift(
    field: str,
    delta: int,
) -> None:
    identity = read_darwin_process_identity(os.getpid())
    values = {
        "expected_start_abstime": identity.start_abstime,
        "expected_parent_pid": identity.parent_pid,
        "expected_process_group_id": identity.process_group_id,
        "expected_session_id": identity.session_id,
    }
    key = {
        "start": "expected_start_abstime",
        "parent": "expected_parent_pid",
        "group": "expected_process_group_id",
        "session": "expected_session_id",
    }[field]
    values[key] += delta

    with pytest.raises(RuntimeError, match="identity changed"):
        sample_darwin_process_self_cpu(pid=identity.pid, **values)


def test_native_self_counter_rejects_non_integral_identity() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        sample_darwin_process_self_cpu(
            pid=os.getpid(),
            expected_start_abstime=1.5,  # type: ignore[arg-type]
            expected_parent_pid=os.getppid(),
            expected_process_group_id=os.getpgrp(),
            expected_session_id=os.getsid(0),
        )


def test_controller_can_sample_external_fresh_session_with_raw_identity() -> None:
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        identity = read_darwin_process_identity(process.pid)
        assert identity.pid == identity.process_group_id == identity.session_id
        assert darwin_process_group_pids(process.pid) == (process.pid,)
        sample = sample_darwin_process_self_cpu(
            pid=identity.pid,
            expected_start_abstime=identity.start_abstime,
            expected_parent_pid=identity.parent_pid,
            expected_process_group_id=identity.process_group_id,
            expected_session_id=identity.session_id,
        )
        assert sample.start_abstime == identity.start_abstime
        assert sample.user_cpu_ns >= identity.user_cpu_ns
        assert sample.system_cpu_ns >= identity.system_cpu_ns
        group = sample_darwin_process_group_metrics(
            process_group_id=process.pid
        )
        assert len(group) == 1
        assert group[0].cpu.pid == process.pid
        assert group[0].cpu.start_abstime == identity.start_abstime
        assert group[0].rss_bytes > 0
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def test_dual_group_sample_binds_two_separate_roots() -> None:
    processes = tuple(
        subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(2)
    )
    try:
        observed = tuple(
            read_darwin_process_identity(process.pid) for process in processes
        )
        worker = ExactProcessIdentity(
            role="parser_worker",
            pid=observed[0].pid,
            start_abstime=observed[0].start_abstime,
            parent_pid=observed[0].parent_pid,
            process_group_id=observed[0].process_group_id,
            session_id=observed[0].session_id,
        )
        broker = ExactProcessIdentity(
            role="tesseract_broker",
            pid=observed[1].pid,
            start_abstime=observed[1].start_abstime,
            parent_pid=observed[1].parent_pid,
            process_group_id=observed[1].process_group_id,
            session_id=observed[1].session_id,
        )
        sample = _dual_group_resource_sample(
            ResourcePhase.REQUEST_PEAK,
            worker=worker,
            broker=broker,
        )

        assert sample.resource.process_count == 2
        assert tuple(item.role for item in sample.identities) == (
            "parser_worker",
            "tesseract_broker",
        )
        assert {item.pid for item in sample.identities} == {
            worker.pid,
            broker.pid,
        }
    finally:
        for process in processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
        for process in processes:
            process.wait(timeout=5)


def test_group_enumerator_retains_direct_child_raw_identity() -> None:
    code = (
        "import subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']); "
        "print(child.pid,flush=True); time.sleep(30)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        assert process.stdout is not None
        child_pid = int(process.stdout.readline(64).strip())
        deadline = time.monotonic() + 5
        pids: tuple[int, ...] = ()
        while time.monotonic() < deadline:
            pids = darwin_process_group_pids(process.pid)
            if child_pid in pids:
                break
            time.sleep(0.01)
        assert pids == tuple(sorted((process.pid, child_pid)))
        child = read_darwin_process_identity(child_pid)
        assert child.parent_pid == process.pid
        assert child.process_group_id == process.pid
        assert child.session_id == process.pid
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
        if process.stdout is not None:
            process.stdout.close()
