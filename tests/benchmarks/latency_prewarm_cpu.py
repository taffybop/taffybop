"""Exact Darwin process-self CPU counters for LAT-US02 evidence.

The production evidence adapter deliberately does not use ``resource.getrusage``
or psutil floating-point counters.  Darwin's ``proc_pid_rusage`` v4 interface
returns the process start identity and self CPU counters as raw ``uint64_t``
values.  This module keeps that narrow ABI boundary isolated and fail-closed.
"""

from __future__ import annotations

import ctypes
import errno
import os
import sys
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import psutil

RUSAGE_INFO_V4 = 4
PROC_PGRP_ONLY = 2
_LIBPROC_PATH = "/usr/lib/libproc.dylib"
_RUSAGE_INFO_V4_SIZE = 296
_MAXIMUM_GROUP_PROCESSES = 4_096


class _RUsageInfoV4(ctypes.Structure):
    """Exact layout of ``struct rusage_info_v4`` from macOS ``resource.h``."""

    _fields_ = [
        ("ri_uuid", ctypes.c_uint8 * 16),
        ("ri_user_time", ctypes.c_uint64),
        ("ri_system_time", ctypes.c_uint64),
        ("ri_pkg_idle_wkups", ctypes.c_uint64),
        ("ri_interrupt_wkups", ctypes.c_uint64),
        ("ri_pageins", ctypes.c_uint64),
        ("ri_wired_size", ctypes.c_uint64),
        ("ri_resident_size", ctypes.c_uint64),
        ("ri_phys_footprint", ctypes.c_uint64),
        ("ri_proc_start_abstime", ctypes.c_uint64),
        ("ri_proc_exit_abstime", ctypes.c_uint64),
        ("ri_child_user_time", ctypes.c_uint64),
        ("ri_child_system_time", ctypes.c_uint64),
        ("ri_child_pkg_idle_wkups", ctypes.c_uint64),
        ("ri_child_interrupt_wkups", ctypes.c_uint64),
        ("ri_child_pageins", ctypes.c_uint64),
        ("ri_child_elapsed_abstime", ctypes.c_uint64),
        ("ri_diskio_bytesread", ctypes.c_uint64),
        ("ri_diskio_byteswritten", ctypes.c_uint64),
        ("ri_cpu_time_qos_default", ctypes.c_uint64),
        ("ri_cpu_time_qos_maintenance", ctypes.c_uint64),
        ("ri_cpu_time_qos_background", ctypes.c_uint64),
        ("ri_cpu_time_qos_utility", ctypes.c_uint64),
        ("ri_cpu_time_qos_legacy", ctypes.c_uint64),
        ("ri_cpu_time_qos_user_initiated", ctypes.c_uint64),
        ("ri_cpu_time_qos_user_interactive", ctypes.c_uint64),
        ("ri_billed_system_time", ctypes.c_uint64),
        ("ri_serviced_system_time", ctypes.c_uint64),
        ("ri_logical_writes", ctypes.c_uint64),
        ("ri_lifetime_max_phys_footprint", ctypes.c_uint64),
        ("ri_instructions", ctypes.c_uint64),
        ("ri_cycles", ctypes.c_uint64),
        ("ri_billed_energy", ctypes.c_uint64),
        ("ri_serviced_energy", ctypes.c_uint64),
        ("ri_interval_max_phys_footprint", ctypes.c_uint64),
        ("ri_runnable_time", ctypes.c_uint64),
    ]


@dataclass(frozen=True, slots=True)
class DarwinProcessSelfCpuSample:
    """One raw, identity-bound ``proc_pid_rusage`` v4 observation."""

    pid: int
    start_abstime: int
    parent_pid: int
    process_group_id: int
    session_id: int
    observed_monotonic_ns: int
    user_cpu_ns: int
    system_cpu_ns: int


@dataclass(frozen=True, slots=True)
class DarwinProcessMetricSample:
    """One identity-stable resource observation for an owned process."""

    cpu: DarwinProcessSelfCpuSample
    rss_bytes: int
    thread_count: int
    file_descriptor_count: int


@lru_cache(maxsize=1)
def _proc_pid_rusage_reader() -> Any:
    if ctypes.sizeof(_RUsageInfoV4) != _RUSAGE_INFO_V4_SIZE:
        raise RuntimeError("rusage_info_v4 ABI layout differs")
    libproc = ctypes.CDLL(_LIBPROC_PATH, use_errno=True)
    reader = libproc.proc_pid_rusage
    reader.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_void_p)
    reader.restype = ctypes.c_int
    return reader


@lru_cache(maxsize=1)
def _proc_listpids_reader() -> Any:
    libproc = ctypes.CDLL(_LIBPROC_PATH, use_errno=True)
    reader = libproc.proc_listpids
    reader.argtypes = (
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_int,
    )
    reader.restype = ctypes.c_int
    return reader


def darwin_process_group_pids(process_group_id: int) -> tuple[int, ...]:
    """List one owned process group without a system-wide psutil traversal."""

    if sys.platform != "darwin":
        raise RuntimeError("process-group evidence requires Darwin")
    if (
        isinstance(process_group_id, bool)
        or not isinstance(process_group_id, int)
        or process_group_id <= 0
        or process_group_id > (1 << 32) - 1
    ):
        raise ValueError("process-group ID must be a positive uint32")
    capacity = _MAXIMUM_GROUP_PROCESSES + 1
    buffer = (ctypes.c_int * capacity)()
    ctypes.set_errno(0)
    observed_bytes = int(
        _proc_listpids_reader()(
            PROC_PGRP_ONLY,
            process_group_id,
            ctypes.byref(buffer),
            ctypes.sizeof(buffer),
        )
    )
    if observed_bytes < 0:
        error_number = ctypes.get_errno() or errno.EIO
        raise OSError(
            error_number,
            f"proc_listpids failed for process group {process_group_id}",
        )
    if observed_bytes % ctypes.sizeof(ctypes.c_int):
        raise RuntimeError("process-group PID result has a partial record")
    observed_count = observed_bytes // ctypes.sizeof(ctypes.c_int)
    if observed_count >= capacity:
        raise RuntimeError("owned process-group member bound exceeded")
    pids = tuple(sorted(int(pid) for pid in buffer[:observed_count] if pid > 0))
    if len(pids) != len(set(pids)):
        raise RuntimeError("owned process-group returned duplicate PIDs")
    if not pids:
        raise ProcessLookupError(
            errno.ESRCH,
            f"process group {process_group_id} has no observable members",
        )
    return pids


def _proc_pid_rusage_v4(pid: int) -> _RUsageInfoV4:
    if sys.platform != "darwin":
        raise RuntimeError("proc_pid_rusage v4 evidence requires Darwin")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ValueError("process PID must be a positive integer")
    reader = _proc_pid_rusage_reader()
    result = _RUsageInfoV4()
    ctypes.set_errno(0)
    if reader(pid, RUSAGE_INFO_V4, ctypes.byref(result)) != 0:
        error_number = ctypes.get_errno() or errno.EIO
        raise ProcessLookupError(
            error_number,
            f"proc_pid_rusage v4 failed for PID {pid}",
        )
    if result.ri_proc_start_abstime <= 0:
        raise RuntimeError("proc_pid_rusage returned an invalid start identity")
    return result


def sample_darwin_process_self_cpu(
    *,
    pid: int,
    expected_start_abstime: int,
    expected_parent_pid: int,
    expected_process_group_id: int,
    expected_session_id: int,
) -> DarwinProcessSelfCpuSample:
    """Read an exact process-self CPU sample and reject identity drift.

    Group/session observations bracket the libproc read.  The raw start-abstime
    returned in the same kernel structure as the CPU counters prevents a reused
    PID from satisfying the caller's frozen identity.
    """

    expected = (
        expected_start_abstime,
        expected_parent_pid,
        expected_process_group_id,
        expected_session_id,
    )
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in expected
    ):
        raise ValueError("expected process identity values must be positive integers")
    parent_before = psutil.Process(pid).ppid()
    group_before = os.getpgid(pid)
    session_before = os.getsid(pid)
    usage = _proc_pid_rusage_v4(pid)
    parent_after = psutil.Process(pid).ppid()
    group_after = os.getpgid(pid)
    session_after = os.getsid(pid)
    observed_monotonic_ns = time.monotonic_ns()
    observed = (
        int(usage.ri_proc_start_abstime),
        parent_after,
        group_after,
        session_after,
    )
    if (
        parent_before != parent_after
        or group_before != group_after
        or session_before != session_after
    ):
        raise RuntimeError("process lineage changed during CPU sampling")
    if observed != expected:
        raise RuntimeError("process identity changed before CPU sampling")
    return DarwinProcessSelfCpuSample(
        pid=pid,
        start_abstime=observed[0],
        parent_pid=parent_after,
        process_group_id=group_after,
        session_id=session_after,
        observed_monotonic_ns=observed_monotonic_ns,
        user_cpu_ns=int(usage.ri_user_time),
        system_cpu_ns=int(usage.ri_system_time),
    )


def read_darwin_process_identity(pid: int) -> DarwinProcessSelfCpuSample:
    """Read a process identity with the same raw counter source used at edges."""

    parent_before = psutil.Process(pid).ppid()
    group_before = os.getpgid(pid)
    session_before = os.getsid(pid)
    usage = _proc_pid_rusage_v4(pid)
    parent_after = psutil.Process(pid).ppid()
    group_after = os.getpgid(pid)
    session_after = os.getsid(pid)
    observed_monotonic_ns = time.monotonic_ns()
    if (
        parent_before != parent_after
        or group_before != group_after
        or session_before != session_after
    ):
        raise RuntimeError("process lineage changed during identity sampling")
    return DarwinProcessSelfCpuSample(
        pid=pid,
        start_abstime=int(usage.ri_proc_start_abstime),
        parent_pid=parent_after,
        process_group_id=group_after,
        session_id=session_after,
        observed_monotonic_ns=observed_monotonic_ns,
        user_cpu_ns=int(usage.ri_user_time),
        system_cpu_ns=int(usage.ri_system_time),
    )


def sample_darwin_process_group_metrics(
    *,
    process_group_id: int,
) -> tuple[DarwinProcessMetricSample, ...]:
    """Read every current group member or fail the entire observation."""

    retained: list[DarwinProcessMetricSample] = []
    for pid in darwin_process_group_pids(process_group_id):
        identity = read_darwin_process_identity(pid)
        if identity.process_group_id != process_group_id:
            raise RuntimeError("process escaped its enumerated group")
        process = psutil.Process(pid)
        with process.oneshot():
            memory = process.memory_info()
            rss_bytes = int(memory.rss)
            thread_count = int(process.num_threads())
            if not hasattr(process, "num_fds"):
                raise RuntimeError("Darwin process FD count is unavailable")
            file_descriptor_count = int(process.num_fds())
        final = sample_darwin_process_self_cpu(
            pid=pid,
            expected_start_abstime=identity.start_abstime,
            expected_parent_pid=identity.parent_pid,
            expected_process_group_id=identity.process_group_id,
            expected_session_id=identity.session_id,
        )
        if any(value < 0 for value in (rss_bytes, thread_count, file_descriptor_count)):
            raise RuntimeError("owned process resource counter is negative")
        retained.append(
            DarwinProcessMetricSample(
                cpu=final,
                rss_bytes=rss_bytes,
                thread_count=thread_count,
                file_descriptor_count=file_descriptor_count,
            )
        )
    identities = tuple((item.cpu.pid, item.cpu.start_abstime) for item in retained)
    if identities != tuple(sorted(set(identities))):
        raise RuntimeError("owned process identities are not canonical and unique")
    return tuple(retained)


__all__ = [
    "DarwinProcessSelfCpuSample",
    "DarwinProcessMetricSample",
    "darwin_process_group_pids",
    "read_darwin_process_identity",
    "sample_darwin_process_group_metrics",
    "sample_darwin_process_self_cpu",
]
