"""Narrow Darwin ABI boundary for broker identity, wait4, and inventory."""

from __future__ import annotations

import ctypes
import errno
import os
import socket
import stat
import sys
import time
from dataclasses import asdict, dataclass, fields as dataclass_fields

from app.services.tesseract_broker_protocol import (
    BrokerProtocolError,
    KernelProcessIdentity,
    RawRUsage,
    RawTimeval,
    TrustedLauncherIdentity,
    canonical_sha256,
)


RUSAGE_INFO_V4 = 4
PROC_PGRP_ONLY = 2
PROC_PPID_ONLY = 6
PROC_PIDTBSDINFO = 3
PROC_PIDLISTFDS = 1
PROC_PIDFDVNODEPATHINFO = 2
PROC_PIDFDSOCKETINFO = 3
PROC_PIDFDPIPEINFO = 6
PROC_PIDFDKQUEUEINFO = 7
PROC_PIDLISTTHREADS = 6
PROC_PIDREGIONPATHINFO = 8
MAX_INVENTORY_PIDS = 8_192
MAX_INVENTORY_FILE_DESCRIPTORS = 4_096
MAX_INVENTORY_THREADS = 4_096
MAX_INVENTORY_REGIONS = 8_192
_LIBPROC_PATH = "/usr/lib/libproc.dylib"
_VM_PROT_EXECUTE = 0x04
_PROC_PIDPATHINFO_MAXSIZE = 4096
_PROC_FP_SHARED = 1
_PROC_FP_CLEXEC = 2
_PROC_FP_GUARDED = 4
_PROC_FP_CLFORK = 8
_PROX_FDTYPE_VNODE = 1
_PROX_FDTYPE_SOCKET = 2
_PROX_FDTYPE_KQUEUE = 5
_PROX_FDTYPE_PIPE = 6
_SOCKINFO_IN = 1
_SOCKINFO_TCP = 2
_SOCKINFO_UN = 3
_SOCK_MAXADDRLEN = 255


def _raise_process_observation_error(
    error_number: int,
    operation: str,
    pid: int,
) -> None:
    """Preserve denial/race errno; only ESRCH proves disappearance."""

    if error_number == errno.ESRCH:
        raise ProcessLookupError(error_number, f"{operation} failed for PID {pid}")
    raise OSError(error_number, f"{operation} failed for PID {pid}")


class _RUsageInfoV4(ctypes.Structure):
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


class _Timeval(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_usec", ctypes.c_int)]


class _RUsage(ctypes.Structure):
    _fields_ = [
        ("ru_utime", _Timeval),
        ("ru_stime", _Timeval),
        ("ru_maxrss", ctypes.c_long),
        ("ru_ixrss", ctypes.c_long),
        ("ru_idrss", ctypes.c_long),
        ("ru_isrss", ctypes.c_long),
        ("ru_minflt", ctypes.c_long),
        ("ru_majflt", ctypes.c_long),
        ("ru_nswap", ctypes.c_long),
        ("ru_inblock", ctypes.c_long),
        ("ru_oublock", ctypes.c_long),
        ("ru_msgsnd", ctypes.c_long),
        ("ru_msgrcv", ctypes.c_long),
        ("ru_nsignals", ctypes.c_long),
        ("ru_nvcsw", ctypes.c_long),
        ("ru_nivcsw", ctypes.c_long),
    ]


class _ProcBsdInfo(ctypes.Structure):
    _fields_ = [
        ("pbi_flags", ctypes.c_uint32),
        ("pbi_status", ctypes.c_uint32),
        ("pbi_xstatus", ctypes.c_uint32),
        ("pbi_pid", ctypes.c_uint32),
        ("pbi_ppid", ctypes.c_uint32),
        ("pbi_uid", ctypes.c_uint32),
        ("pbi_gid", ctypes.c_uint32),
        ("pbi_ruid", ctypes.c_uint32),
        ("pbi_rgid", ctypes.c_uint32),
        ("pbi_svuid", ctypes.c_uint32),
        ("pbi_svgid", ctypes.c_uint32),
        ("rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * 16),
        ("pbi_name", ctypes.c_char * 32),
        ("pbi_nfiles", ctypes.c_uint32),
        ("pbi_pgid", ctypes.c_uint32),
        ("pbi_pjobc", ctypes.c_uint32),
        ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32),
        ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64),
        ("pbi_start_tvusec", ctypes.c_uint64),
    ]


class _ProcFdInfo(ctypes.Structure):
    _fields_ = [
        ("proc_fd", ctypes.c_int32),
        ("proc_fdtype", ctypes.c_uint32),
    ]


class _ProcRegionInfo(ctypes.Structure):
    _fields_ = [
        ("pri_protection", ctypes.c_uint32),
        ("pri_max_protection", ctypes.c_uint32),
        ("pri_inheritance", ctypes.c_uint32),
        ("pri_flags", ctypes.c_uint32),
        ("pri_offset", ctypes.c_uint64),
        ("pri_behavior", ctypes.c_uint32),
        ("pri_user_wired_count", ctypes.c_uint32),
        ("pri_user_tag", ctypes.c_uint32),
        ("pri_pages_resident", ctypes.c_uint32),
        ("pri_pages_shared_now_private", ctypes.c_uint32),
        ("pri_pages_swapped_out", ctypes.c_uint32),
        ("pri_pages_dirtied", ctypes.c_uint32),
        ("pri_ref_count", ctypes.c_uint32),
        ("pri_shadow_depth", ctypes.c_uint32),
        ("pri_share_mode", ctypes.c_uint32),
        ("pri_private_pages_resident", ctypes.c_uint32),
        ("pri_shared_pages_resident", ctypes.c_uint32),
        ("pri_obj_id", ctypes.c_uint32),
        ("pri_depth", ctypes.c_uint32),
        ("pri_address", ctypes.c_uint64),
        ("pri_size", ctypes.c_uint64),
    ]


class _VInfoStat(ctypes.Structure):
    _fields_ = [
        ("vst_dev", ctypes.c_uint32),
        ("vst_mode", ctypes.c_uint16),
        ("vst_nlink", ctypes.c_uint16),
        ("vst_ino", ctypes.c_uint64),
        ("vst_uid", ctypes.c_uint32),
        ("vst_gid", ctypes.c_uint32),
        ("vst_atime", ctypes.c_int64),
        ("vst_atimensec", ctypes.c_int64),
        ("vst_mtime", ctypes.c_int64),
        ("vst_mtimensec", ctypes.c_int64),
        ("vst_ctime", ctypes.c_int64),
        ("vst_ctimensec", ctypes.c_int64),
        ("vst_birthtime", ctypes.c_int64),
        ("vst_birthtimensec", ctypes.c_int64),
        ("vst_size", ctypes.c_int64),
        ("vst_blocks", ctypes.c_int64),
        ("vst_blksize", ctypes.c_int32),
        ("vst_flags", ctypes.c_uint32),
        ("vst_gen", ctypes.c_uint32),
        ("vst_rdev", ctypes.c_uint32),
        ("vst_qspare", ctypes.c_int64 * 2),
    ]


class _Fsid(ctypes.Structure):
    _fields_ = [("val", ctypes.c_int32 * 2)]


class _VnodeInfo(ctypes.Structure):
    _fields_ = [
        ("vi_stat", _VInfoStat),
        ("vi_type", ctypes.c_int32),
        ("vi_pad", ctypes.c_int32),
        ("vi_fsid", _Fsid),
    ]


class _VnodeInfoPath(ctypes.Structure):
    _fields_ = [
        ("vip_vi", _VnodeInfo),
        ("vip_path", ctypes.c_char * 1024),
    ]


class _ProcFileInfo(ctypes.Structure):
    _fields_ = [
        ("fi_openflags", ctypes.c_uint32),
        ("fi_status", ctypes.c_uint32),
        ("fi_offset", ctypes.c_int64),
        ("fi_type", ctypes.c_int32),
        ("fi_guardflags", ctypes.c_uint32),
    ]


class _VnodeFdInfoWithPath(ctypes.Structure):
    _fields_ = [("pfi", _ProcFileInfo), ("pvip", _VnodeInfoPath)]


class _PipeInfo(ctypes.Structure):
    _fields_ = [
        ("pipe_stat", _VInfoStat),
        ("pipe_handle", ctypes.c_uint64),
        ("pipe_peerhandle", ctypes.c_uint64),
        ("pipe_status", ctypes.c_int32),
        ("rfu_1", ctypes.c_int32),
    ]


class _PipeFdInfo(ctypes.Structure):
    _fields_ = [("pfi", _ProcFileInfo), ("pipeinfo", _PipeInfo)]


class _KqueueInfo(ctypes.Structure):
    _fields_ = [
        ("kq_stat", _VInfoStat),
        ("kq_state", ctypes.c_uint32),
        ("rfu_1", ctypes.c_uint32),
    ]


class _KqueueFdInfo(ctypes.Structure):
    _fields_ = [("pfi", _ProcFileInfo), ("kqueueinfo", _KqueueInfo)]


class _SockbufInfo(ctypes.Structure):
    _fields_ = [
        ("sbi_cc", ctypes.c_uint32),
        ("sbi_hiwat", ctypes.c_uint32),
        ("sbi_mbcnt", ctypes.c_uint32),
        ("sbi_mbmax", ctypes.c_uint32),
        ("sbi_lowat", ctypes.c_uint32),
        ("sbi_flags", ctypes.c_int16),
        ("sbi_timeo", ctypes.c_int16),
    ]


class _SocketProtocolInfo(ctypes.Union):
    _fields_ = [("raw", ctypes.c_uint8 * 528)]


class _SocketInfo(ctypes.Structure):
    _fields_ = [
        ("soi_stat", _VInfoStat),
        ("soi_so", ctypes.c_uint64),
        ("soi_pcb", ctypes.c_uint64),
        ("soi_type", ctypes.c_int32),
        ("soi_protocol", ctypes.c_int32),
        ("soi_family", ctypes.c_int32),
        ("soi_options", ctypes.c_int16),
        ("soi_linger", ctypes.c_int16),
        ("soi_state", ctypes.c_int16),
        ("soi_qlen", ctypes.c_int16),
        ("soi_incqlen", ctypes.c_int16),
        ("soi_qlimit", ctypes.c_int16),
        ("soi_timeo", ctypes.c_int16),
        ("soi_error", ctypes.c_uint16),
        ("soi_oobmark", ctypes.c_uint32),
        ("soi_rcv", _SockbufInfo),
        ("soi_snd", _SockbufInfo),
        ("soi_kind", ctypes.c_int32),
        ("rfu_1", ctypes.c_uint32),
        ("soi_proto", _SocketProtocolInfo),
    ]


class _SocketFdInfo(ctypes.Structure):
    _fields_ = [("pfi", _ProcFileInfo), ("psi", _SocketInfo)]


class _ProcRegionWithPathInfo(ctypes.Structure):
    _fields_ = [
        ("prp_prinfo", _ProcRegionInfo),
        ("prp_vip", _VnodeInfoPath),
    ]


@dataclass(frozen=True, slots=True)
class NativeExecutableRegionIdentity:
    address: int
    size: int
    file_offset: int
    protection: int
    maximum_protection: int
    user_tag: int
    object_id: int
    resolved_path: str
    device: int
    inode: int
    mode: int
    uid: int
    gid: int
    nlink: int
    file_size: int
    mtime_ns: int
    ctime_ns: int
    vnode_type: int


@dataclass(frozen=True, slots=True)
class NativeExecutableRegionInventory:
    process: KernelProcessIdentity
    scan_started_monotonic_ns: int
    scan_completed_monotonic_ns: int
    total_region_count: int
    regions: tuple[NativeExecutableRegionIdentity, ...]
    inventory_sha256: str


@dataclass(frozen=True, slots=True)
class NativeVnodeFileDescriptorIdentity:
    device: int
    inode: int
    mode: int
    nlink: int
    uid: int
    gid: int
    size: int
    vnode_type: int
    resolved_path_sha256: str


@dataclass(frozen=True, slots=True)
class NativeSocketFileDescriptorIdentity:
    family: int
    socket_type: int
    protocol: int
    socket_kind: int
    socket_state: int
    local_identity_sha256: str
    peer_identity_sha256: str


@dataclass(frozen=True, slots=True)
class NativePipeFileDescriptorIdentity:
    device: int
    inode: int
    mode: int
    nlink: int
    uid: int
    gid: int
    pipe_status: int
    local_handle_sha256: str
    peer_handle_sha256: str


@dataclass(frozen=True, slots=True)
class NativeKqueueFileDescriptorIdentity:
    device: int
    inode: int
    mode: int
    nlink: int
    uid: int
    gid: int
    kqueue_state: int


@dataclass(frozen=True, slots=True)
class NativeFileDescriptorIdentity:
    fd: int
    kernel_type: int
    open_flags: int
    kernel_status_flags: int
    descriptor_offset: int
    descriptor_type: int
    guard_flags: int
    close_on_exec: bool
    close_on_fork: bool
    guarded: bool
    shared: bool
    vnode: NativeVnodeFileDescriptorIdentity | None
    socket: NativeSocketFileDescriptorIdentity | None
    pipe: NativePipeFileDescriptorIdentity | None
    kqueue: NativeKqueueFileDescriptorIdentity | None
    record_sha256: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.fd, bool)
            or not isinstance(self.fd, int)
            or self.fd < 0
            or isinstance(self.kernel_type, bool)
            or not isinstance(self.kernel_type, int)
            or self.kernel_type <= 0
        ):
            raise BrokerProtocolError("file-descriptor identity is invalid")
        for name in (
            "open_flags",
            "kernel_status_flags",
            "guard_flags",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise BrokerProtocolError(
                    f"file-descriptor {name} is invalid"
                )
        if (
            isinstance(self.descriptor_offset, bool)
            or not isinstance(self.descriptor_offset, int)
            or isinstance(self.descriptor_type, bool)
            or not isinstance(self.descriptor_type, int)
            or self.descriptor_type != self.kernel_type
        ):
            raise BrokerProtocolError("file-descriptor kernel type differs")
        for name in ("close_on_exec", "close_on_fork", "guarded", "shared"):
            if type(getattr(self, name)) is not bool:
                raise BrokerProtocolError(
                    f"file-descriptor {name} is not a strict Boolean"
                )
        variants = (self.vnode, self.socket, self.pipe, self.kqueue)
        if sum(value is not None for value in variants) != 1:
            raise BrokerProtocolError(
                "file-descriptor type-specific identity differs"
            )
        expected_variant = {
            _PROX_FDTYPE_VNODE: NativeVnodeFileDescriptorIdentity,
            _PROX_FDTYPE_SOCKET: NativeSocketFileDescriptorIdentity,
            _PROX_FDTYPE_PIPE: NativePipeFileDescriptorIdentity,
            _PROX_FDTYPE_KQUEUE: NativeKqueueFileDescriptorIdentity,
        }.get(self.kernel_type)
        selected = next(value for value in variants if value is not None)
        if expected_variant is None or type(selected) is not expected_variant:
            raise BrokerProtocolError(
                "file-descriptor type-specific identity is unsupported"
            )
        if (
            not isinstance(self.record_sha256, str)
            or len(self.record_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.record_sha256)
        ):
            raise BrokerProtocolError("file-descriptor record digest is invalid")
        expected = canonical_sha256(
            {
                key: value
                for key, value in asdict(self).items()
                if key != "record_sha256"
            }
        )
        if self.record_sha256 != expected:
            raise BrokerProtocolError("file-descriptor record digest differs")


@dataclass(frozen=True, slots=True)
class NativeFileDescriptorInventory:
    schema_id: str
    process: KernelProcessIdentity
    first_scan_started_monotonic_ns: int
    first_scan_completed_monotonic_ns: int
    second_scan_started_monotonic_ns: int
    second_scan_completed_monotonic_ns: int
    descriptors: tuple[NativeFileDescriptorIdentity, ...]
    inventory_sha256: str

    def __post_init__(self) -> None:
        if self.schema_id != "darwin-detailed-file-descriptor-inventory-v1":
            raise BrokerProtocolError("file-descriptor inventory schema differs")
        if type(self.process) is not KernelProcessIdentity:
            raise BrokerProtocolError("file-descriptor process identity differs")
        times = (
            self.first_scan_started_monotonic_ns,
            self.first_scan_completed_monotonic_ns,
            self.second_scan_started_monotonic_ns,
            self.second_scan_completed_monotonic_ns,
        )
        if (
            any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in times)
            or tuple(sorted(times)) != times
        ):
            raise BrokerProtocolError("file-descriptor scan chronology differs")
        if (
            type(self.descriptors) is not tuple
            or not self.descriptors
            or len(self.descriptors) > MAX_INVENTORY_FILE_DESCRIPTORS
            or any(type(value) is not NativeFileDescriptorIdentity for value in self.descriptors)
            or tuple(sorted(value.fd for value in self.descriptors))
            != tuple(value.fd for value in self.descriptors)
            or len({value.fd for value in self.descriptors}) != len(self.descriptors)
        ):
            raise BrokerProtocolError("file-descriptor inventory ordering differs")
        if (
            not isinstance(self.inventory_sha256, str)
            or len(self.inventory_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.inventory_sha256)
        ):
            raise BrokerProtocolError("file-descriptor inventory digest is invalid")
        expected = canonical_sha256(
            {
                "schema_id": self.schema_id,
                "process": asdict(self.process),
                "descriptors": [asdict(value) for value in self.descriptors],
            }
        )
        if self.inventory_sha256 != expected:
            raise BrokerProtocolError("file-descriptor inventory digest differs")


@dataclass(frozen=True, slots=True)
class NativeThreadInventory:
    schema_id: str
    process: KernelProcessIdentity
    identity_basis: str
    first_scan_started_monotonic_ns: int
    first_scan_completed_monotonic_ns: int
    second_scan_started_monotonic_ns: int
    second_scan_completed_monotonic_ns: int
    thread_ids: tuple[int, ...]
    thread_count: int
    inventory_sha256: str

    def __post_init__(self) -> None:
        if (
            self.schema_id != "darwin-detailed-thread-inventory-v1"
            or self.identity_basis
            != "darwin-proc_pidinfo-PROC_PIDLISTTHREADS-uint64-v1"
            or type(self.process) is not KernelProcessIdentity
        ):
            raise BrokerProtocolError("thread inventory identity differs")
        times = (
            self.first_scan_started_monotonic_ns,
            self.first_scan_completed_monotonic_ns,
            self.second_scan_started_monotonic_ns,
            self.second_scan_completed_monotonic_ns,
        )
        if (
            any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
                for value in times
            )
            or tuple(sorted(times)) != times
            or type(self.thread_ids) is not tuple
            or not self.thread_ids
            or len(self.thread_ids) > MAX_INVENTORY_THREADS
            or any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
                for value in self.thread_ids
            )
            or tuple(sorted(self.thread_ids)) != self.thread_ids
            or len(set(self.thread_ids)) != len(self.thread_ids)
            or isinstance(self.thread_count, bool)
            or not isinstance(self.thread_count, int)
            or self.thread_count != len(self.thread_ids)
        ):
            raise BrokerProtocolError("thread inventory fields differ")
        expected = canonical_sha256(
            {
                "schema_id": self.schema_id,
                "process": asdict(self.process),
                "identity_basis": self.identity_basis,
                "thread_ids": list(self.thread_ids),
                "thread_count": self.thread_count,
            }
        )
        if self.inventory_sha256 != expected:
            raise BrokerProtocolError("thread inventory digest differs")


@dataclass(frozen=True, slots=True)
class NativeWait4Result:
    pid: int
    raw_status: int
    rusage: RawRUsage
    maximum_resident_set_size_bytes: int
    minor_faults: int
    major_faults: int
    voluntary_context_switches: int
    involuntary_context_switches: int


def _require_darwin() -> None:
    if sys.platform != "darwin":
        raise RuntimeError("Tesseract broker custody is approved only on Darwin")
    expected_sizes = {
        _Timeval: 16,
        _RUsage: 144,
        _RUsageInfoV4: 296,
        _ProcBsdInfo: 136,
        _ProcFdInfo: 8,
        _ProcFileInfo: 24,
        _VnodeFdInfoWithPath: 1200,
        _PipeFdInfo: 184,
        _KqueueFdInfo: 168,
        _SockbufInfo: 24,
        _SocketInfo: 768,
        _SocketFdInfo: 792,
        _ProcRegionInfo: 96,
        _VInfoStat: 136,
        _VnodeInfo: 152,
        _VnodeInfoPath: 1176,
        _ProcRegionWithPathInfo: 1272,
    }
    if any(ctypes.sizeof(kind) != size for kind, size in expected_sizes.items()):
        raise RuntimeError("Darwin process-accounting ABI layout differs")


def _libproc() -> ctypes.CDLL:
    _require_darwin()
    return ctypes.CDLL(_LIBPROC_PATH, use_errno=True)


def raw_process_start_abstime(pid: int) -> int:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ValueError("process PID must be positive")
    library = _libproc()
    reader = library.proc_pid_rusage
    reader.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_void_p)
    reader.restype = ctypes.c_int
    result = _RUsageInfoV4()
    ctypes.set_errno(0)
    if reader(pid, RUSAGE_INFO_V4, ctypes.byref(result)) != 0:
        error_number = ctypes.get_errno() or errno.EIO
        _raise_process_observation_error(error_number, "proc_pid_rusage", pid)
    value = int(result.ri_proc_start_abstime)
    if value <= 0:
        raise BrokerProtocolError("process start abstime is invalid")
    return value


def native_process_path(pid: int) -> str:
    """Read the kernel process image path with stable PID/start custody."""

    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ValueError("process PID must be positive")
    _require_darwin()
    before = kernel_process_identity(pid)
    library = _libproc()
    reader = library.proc_pidpath
    reader.argtypes = (ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32)
    reader.restype = ctypes.c_int
    buffer = ctypes.create_string_buffer(_PROC_PIDPATHINFO_MAXSIZE)
    ctypes.set_errno(0)
    size = int(reader(pid, buffer, len(buffer)))
    if size <= 0 or size >= len(buffer):
        error_number = ctypes.get_errno() or errno.EIO
        _raise_process_observation_error(error_number, "proc_pidpath", pid)
    raw = bytes(buffer[:size]).split(b"\x00", 1)[0]
    try:
        value = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise BrokerProtocolError("process image path is not UTF-8") from exc
    after = kernel_process_identity(pid)
    if (
        before != after
        or not value
        or not os.path.isabs(value)
        or os.path.realpath(value) != value
        or "\x00" in value
    ):
        raise BrokerProtocolError("process image path identity differs")
    return value


def native_executable_region_inventory(
    pid: int,
) -> NativeExecutableRegionInventory:
    """Return one bounded, kernel-backed executable-region inventory.

    ``PROC_PIDREGIONPATHINFO`` returns vnode identity from the mapped object,
    rather than a later pathname lookup.  A full stable process identity is
    sampled on both sides so PID reuse, reparenting, or group/session drift
    cannot be combined with the region rows.
    """

    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ValueError("process PID must be positive")
    _require_darwin()
    scan_started = time.monotonic_ns()
    process_before = kernel_process_identity(pid)
    library = _libproc()
    reader = library.proc_pidinfo
    reader.argtypes = (
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint64,
        ctypes.c_void_p,
        ctypes.c_int,
    )
    reader.restype = ctypes.c_int
    address = 0
    total_regions = 0
    regions: list[NativeExecutableRegionIdentity] = []
    while True:
        if total_regions >= MAX_INVENTORY_REGIONS:
            raise BrokerProtocolError("native region inventory exceeds its bound")
        result = _ProcRegionWithPathInfo()
        ctypes.set_errno(0)
        size = reader(
            pid,
            PROC_PIDREGIONPATHINFO,
            address,
            ctypes.byref(result),
            ctypes.sizeof(result),
        )
        if size == 0:
            error_number = ctypes.get_errno()
            # Darwin reports EINVAL after the final address-space region for
            # this fixed flavor/record size.  The stable identity sample below
            # distinguishes that natural terminator from process loss.
            if error_number not in {0, errno.EINVAL}:
                _raise_process_observation_error(
                    error_number,
                    "proc_pidinfo executable-region inventory",
                    pid,
                )
            break
        if size != ctypes.sizeof(result):
            error_number = ctypes.get_errno()
            if error_number:
                _raise_process_observation_error(
                    error_number,
                    "proc_pidinfo executable-region inventory",
                    pid,
                )
            raise BrokerProtocolError("native region inventory record is truncated")
        region = result.prp_prinfo
        region_address = int(region.pri_address)
        region_size = int(region.pri_size)
        if (
            region_address < address
            or region_size <= 0
            or region_address + region_size <= region_address
            or region_address + region_size > (1 << 64) - 1
        ):
            raise BrokerProtocolError("native region inventory did not advance")
        total_regions += 1
        address = region_address + region_size
        if not int(region.pri_protection) & _VM_PROT_EXECUTE:
            continue
        raw_path = bytes(result.prp_vip.vip_path).split(b"\x00", 1)[0]
        try:
            path = raw_path.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise BrokerProtocolError(
                "native executable mapping path is not UTF-8"
            ) from exc
        vnode = result.prp_vip.vip_vi
        identity = vnode.vi_stat
        if (
            not path
            or not os.path.isabs(path)
            or os.path.realpath(path) != path
            or "\x00" in path
            or not stat.S_ISREG(int(identity.vst_mode))
            or int(identity.vst_dev) <= 0
            or int(identity.vst_ino) <= 0
            or int(identity.vst_nlink) <= 0
            or int(identity.vst_size) <= 0
            or not 0 <= int(identity.vst_mtimensec) < 1_000_000_000
            or not 0 <= int(identity.vst_ctimensec) < 1_000_000_000
        ):
            raise BrokerProtocolError("native executable mapping identity differs")
        regions.append(
            NativeExecutableRegionIdentity(
                address=region_address,
                size=region_size,
                file_offset=int(region.pri_offset),
                protection=int(region.pri_protection),
                maximum_protection=int(region.pri_max_protection),
                user_tag=int(region.pri_user_tag),
                object_id=int(region.pri_obj_id),
                resolved_path=path,
                device=int(identity.vst_dev),
                inode=int(identity.vst_ino),
                mode=int(identity.vst_mode),
                uid=int(identity.vst_uid),
                gid=int(identity.vst_gid),
                nlink=int(identity.vst_nlink),
                file_size=int(identity.vst_size),
                mtime_ns=(
                    int(identity.vst_mtime) * 1_000_000_000
                    + int(identity.vst_mtimensec)
                ),
                ctime_ns=(
                    int(identity.vst_ctime) * 1_000_000_000
                    + int(identity.vst_ctimensec)
                ),
                vnode_type=int(vnode.vi_type),
            )
        )
    process_after = kernel_process_identity(pid)
    if process_after != process_before:
        raise BrokerProtocolError("process identity changed during native scan")
    if not regions:
        raise BrokerProtocolError("native executable-region inventory is empty")
    ordered = tuple(sorted(regions, key=lambda item: item.address))
    if tuple(regions) != ordered or len({item.address for item in ordered}) != len(ordered):
        raise BrokerProtocolError("native executable-region ordering differs")
    scan_completed = time.monotonic_ns()
    payload = {
        "process": {
            "pid": process_before.pid,
            "start_abstime": process_before.start_abstime,
            "ppid": process_before.ppid,
            "pgid": process_before.pgid,
            "sid": process_before.sid,
        },
        # ``total_region_count`` includes anonymous, non-executable VM regions
        # whose count can legitimately change while the executable image set
        # remains identical.  Retain that diagnostic count above, but bind the
        # custody digest only to the complete executable-region inventory.
        "regions": [
            {
                field: getattr(item, field)
                for field in NativeExecutableRegionIdentity.__dataclass_fields__
            }
            for item in ordered
        ],
    }
    return NativeExecutableRegionInventory(
        process=process_before,
        scan_started_monotonic_ns=scan_started,
        scan_completed_monotonic_ns=scan_completed,
        total_region_count=total_regions,
        regions=ordered,
        inventory_sha256=canonical_sha256(payload),
    )


def _process_bsd_identity(pid: int) -> tuple[int, int, int, int, int, int]:
    library = _libproc()
    reader = library.proc_pidinfo
    reader.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int)
    reader.restype = ctypes.c_int
    result = _ProcBsdInfo()
    ctypes.set_errno(0)
    size = reader(pid, PROC_PIDTBSDINFO, 0, ctypes.byref(result), ctypes.sizeof(result))
    if size != ctypes.sizeof(result):
        error_number = ctypes.get_errno() or errno.ESRCH
        _raise_process_observation_error(error_number, "proc_pidinfo", pid)
    if int(result.pbi_pid) != pid or int(result.pbi_ppid) <= 0:
        raise BrokerProtocolError("BSD process identity differs")
    return (
        int(result.pbi_pid),
        int(result.pbi_ppid),
        int(result.pbi_pgid),
        int(result.pbi_ruid),
        int(result.pbi_uid),
        int(result.pbi_status),
    )


def kernel_process_identity(pid: int) -> KernelProcessIdentity:
    group_before = os.getpgid(pid)
    session_before = os.getsid(pid)
    start_before = raw_process_start_abstime(pid)
    bsd_before = _process_bsd_identity(pid)
    bsd_after = _process_bsd_identity(pid)
    start_after = raw_process_start_abstime(pid)
    group_after = os.getpgid(pid)
    session_after = os.getsid(pid)
    if (
        (start_before, group_before, session_before) != (
        start_after,
        group_after,
        session_after,
        )
        or bsd_before != bsd_after
        or bsd_after[0] != pid
        or bsd_after[2] != group_after
    ):
        raise BrokerProtocolError("process identity changed during observation")
    return KernelProcessIdentity(
        pid=pid,
        start_abstime=start_after,
        ppid=bsd_after[1],
        pgid=group_after,
        sid=session_after,
    )


def trusted_launcher_identity(pid: int) -> TrustedLauncherIdentity:
    """Return one stable full kernel identity for the watchdog launcher."""

    group_before = os.getpgid(pid)
    session_before = os.getsid(pid)
    start_before = raw_process_start_abstime(pid)
    bsd_before = _process_bsd_identity(pid)
    bsd_after = _process_bsd_identity(pid)
    start_after = raw_process_start_abstime(pid)
    group_after = os.getpgid(pid)
    session_after = os.getsid(pid)
    if (
        (start_before, group_before, session_before)
        != (start_after, group_after, session_after)
        or bsd_before != bsd_after
        or bsd_after[0] != pid
        or bsd_after[2] != group_after
    ):
        raise BrokerProtocolError(
            "trusted launcher identity changed during observation"
        )
    return TrustedLauncherIdentity(
        pid=pid,
        start_abstime=start_after,
        ppid=bsd_after[1],
        pgid=group_after,
        sid=session_after,
        uid=bsd_after[3],
        euid=bsd_after[4],
    )


def _list_pids(kind: int, identity: int) -> tuple[int, ...]:
    library = _libproc()
    reader = library.proc_listpids
    reader.argtypes = (ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int)
    reader.restype = ctypes.c_int
    values = (ctypes.c_int * MAX_INVENTORY_PIDS)()
    ctypes.set_errno(0)
    size = reader(kind, identity, ctypes.byref(values), ctypes.sizeof(values))
    if size < 0:
        error_number = ctypes.get_errno() or errno.EIO
        raise OSError(error_number, "proc_listpids failed")
    if size >= ctypes.sizeof(values):
        raise BrokerProtocolError("process inventory exceeds its PID bound")
    if size % ctypes.sizeof(ctypes.c_int):
        raise BrokerProtocolError("process inventory byte count is malformed")
    count = size // ctypes.sizeof(ctypes.c_int)
    return tuple(sorted({int(value) for value in values[:count] if int(value) > 0}))


def group_inventory(pgid: int) -> tuple[KernelProcessIdentity, ...]:
    return tuple(sorted(kernel_process_identity(pid) for pid in _list_pids(PROC_PGRP_ONLY, pgid)))


def recursive_descendants(pid: int) -> tuple[KernelProcessIdentity, ...]:
    pending = [pid]
    seen: set[tuple[int, int]] = set()
    descendants: list[KernelProcessIdentity] = []
    while pending:
        parent = pending.pop()
        for child_pid in _list_pids(PROC_PPID_ONLY, parent):
            child = kernel_process_identity(child_pid)
            key = (child.pid, child.start_abstime)
            if key in seen:
                raise BrokerProtocolError("recursive process inventory repeated an identity")
            seen.add(key)
            descendants.append(child)
            if len(descendants) > MAX_INVENTORY_PIDS:
                raise BrokerProtocolError("recursive process inventory exceeds its bound")
            pending.append(child.pid)
    return tuple(sorted(descendants))


def _thread_ids_once(pid: int) -> tuple[int, ...]:
    library = _libproc()
    reader = library.proc_pidinfo
    reader.argtypes = (
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint64,
        ctypes.c_void_p,
        ctypes.c_int,
    )
    reader.restype = ctypes.c_int
    values = (ctypes.c_uint64 * MAX_INVENTORY_THREADS)()
    ctypes.set_errno(0)
    size = int(
        reader(
            pid,
            PROC_PIDLISTTHREADS,
            0,
            ctypes.byref(values),
            ctypes.sizeof(values),
        )
    )
    if size <= 0:
        _raise_process_observation_error(
            ctypes.get_errno() or errno.ESRCH,
            "proc_pidinfo thread inventory",
            pid,
        )
    if size >= ctypes.sizeof(values):
        raise BrokerProtocolError("thread inventory exceeds its bound")
    item_size = ctypes.sizeof(ctypes.c_uint64)
    if size % item_size:
        raise BrokerProtocolError("thread inventory byte count is malformed")
    count = size // item_size
    result = tuple(sorted(int(value) for value in values[:count]))
    if not result or any(value <= 0 for value in result) or len(set(result)) != len(result):
        raise BrokerProtocolError("thread inventory identities differ")
    return result


def native_thread_inventory(pid: int) -> tuple[int, ...]:
    """Return one race-bounded exact Darwin thread inventory for ``pid``."""

    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ValueError("thread-inventory PID must be positive")
    start_before = raw_process_start_abstime(pid)
    first = _thread_ids_once(pid)
    second = _thread_ids_once(pid)
    start_after = raw_process_start_abstime(pid)
    if start_before != start_after or first != second:
        raise BrokerProtocolError("thread inventory changed during observation")
    return second


def native_detailed_thread_inventory(pid: int) -> NativeThreadInventory:
    """Return a process-bracketed, timed, double-stable Darwin TID set."""

    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ValueError("detailed thread-inventory PID must be positive")
    process_before = kernel_process_identity(pid)
    first_started = time.monotonic_ns()
    first = _thread_ids_once(pid)
    first_completed = time.monotonic_ns()
    second_started = time.monotonic_ns()
    second = _thread_ids_once(pid)
    second_completed = time.monotonic_ns()
    process_after = kernel_process_identity(pid)
    if process_before != process_after or first != second:
        raise BrokerProtocolError("detailed thread inventory changed during observation")
    schema_id = "darwin-detailed-thread-inventory-v1"
    identity_basis = "darwin-proc_pidinfo-PROC_PIDLISTTHREADS-uint64-v1"
    inventory_sha256 = canonical_sha256(
        {
            "schema_id": schema_id,
            "process": asdict(process_after),
            "identity_basis": identity_basis,
            "thread_ids": list(second),
            "thread_count": len(second),
        }
    )
    return NativeThreadInventory(
        schema_id=schema_id,
        process=process_after,
        identity_basis=identity_basis,
        first_scan_started_monotonic_ns=first_started,
        first_scan_completed_monotonic_ns=first_completed,
        second_scan_started_monotonic_ns=second_started,
        second_scan_completed_monotonic_ns=second_completed,
        thread_ids=second,
        thread_count=len(second),
        inventory_sha256=inventory_sha256,
    )


def _pid_fd_info(pid: int, fd: int, flavor: int, result: ctypes.Structure) -> None:
    library = _libproc()
    reader = library.proc_pidfdinfo
    reader.argtypes = (
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_int,
    )
    reader.restype = ctypes.c_int
    ctypes.set_errno(0)
    size = int(
        reader(
            pid,
            fd,
            flavor,
            ctypes.byref(result),
            ctypes.sizeof(result),
        )
    )
    if size <= 0:
        _raise_process_observation_error(
            ctypes.get_errno() or errno.EBADF,
            f"proc_pidfdinfo descriptor {fd}",
            pid,
        )
    if size != ctypes.sizeof(result):
        raise BrokerProtocolError(
            f"file-descriptor {fd} type-specific byte count differs"
        )


def _vnode_stat_mapping(value: _VInfoStat) -> dict[str, int]:
    return {
        "device": int(value.vst_dev),
        "inode": int(value.vst_ino),
        "mode": int(value.vst_mode),
        "nlink": int(value.vst_nlink),
        "uid": int(value.vst_uid),
        "gid": int(value.vst_gid),
        "size": int(value.vst_size),
    }


def _socket_endpoint_hashes(value: _SocketInfo) -> tuple[str, str]:
    protocol = bytes(value.soi_proto.raw)
    family = int(value.soi_family)
    kind = int(value.soi_kind)
    if kind in {_SOCKINFO_IN, _SOCKINFO_TCP} and family in {
        int(socket.AF_INET),
        int(socket.AF_INET6),
    }:
        foreign_port = int.from_bytes(protocol[0:4], sys.byteorder, signed=True)
        local_port = int.from_bytes(protocol[4:8], sys.byteorder, signed=True)
        generation = int.from_bytes(protocol[8:16], sys.byteorder, signed=False)
        address_version_flags = protocol[24]
        foreign_address = protocol[32:48]
        local_address = protocol[48:64]
        local = {
            "family": family,
            "port": local_port,
            "address_version_flags": address_version_flags,
            "address_sha256": canonical_sha256(
                {"raw_address": local_address.hex()}
            ),
            "generation": generation,
            "socket_object_sha256": canonical_sha256(
                {"soi_so": int(value.soi_so), "soi_pcb": int(value.soi_pcb)}
            ),
        }
        peer = {
            "family": family,
            "port": foreign_port,
            "address_version_flags": address_version_flags,
            "address_sha256": canonical_sha256(
                {"raw_address": foreign_address.hex()}
            ),
        }
        return canonical_sha256(local), canonical_sha256(peer)
    if kind == _SOCKINFO_UN and family == int(socket.AF_UNIX):
        connected_socket = int.from_bytes(
            protocol[0:8], sys.byteorder, signed=False
        )
        connected_pcb = int.from_bytes(
            protocol[8:16], sys.byteorder, signed=False
        )
        local_address = protocol[16 : 16 + _SOCK_MAXADDRLEN]
        peer_address = protocol[
            16 + _SOCK_MAXADDRLEN : 16 + (2 * _SOCK_MAXADDRLEN)
        ]
        local = {
            "schema_id": "darwin-unix-socket-endpoint-v1",
            "family": family,
            "address_sha256": canonical_sha256(
                {"raw_sockaddr": local_address.hex()}
            ),
            "kernel_object_sha256": canonical_sha256(
                {
                    "schema_id": "darwin-unix-socket-kernel-object-v1",
                    "socket": int(value.soi_so),
                    "pcb": int(value.soi_pcb),
                }
            ),
        }
        peer = {
            "schema_id": "darwin-unix-socket-endpoint-v1",
            "family": family,
            "address_sha256": canonical_sha256(
                {"raw_sockaddr": peer_address.hex()}
            ),
            "kernel_object_sha256": canonical_sha256(
                {
                    "schema_id": "darwin-unix-socket-kernel-object-v1",
                    "socket": connected_socket,
                    "pcb": connected_pcb,
                }
            ),
        }
        return canonical_sha256(local), canonical_sha256(peer)
    raise BrokerProtocolError(
        f"socket family/kind {family}/{kind} is unsupported for exact inventory"
    )


def _detailed_file_descriptor_identity(
    pid: int,
    fd: int,
    kernel_type: int,
) -> NativeFileDescriptorIdentity:
    vnode: NativeVnodeFileDescriptorIdentity | None = None
    socket_identity: NativeSocketFileDescriptorIdentity | None = None
    pipe: NativePipeFileDescriptorIdentity | None = None
    kqueue: NativeKqueueFileDescriptorIdentity | None = None
    if kernel_type == _PROX_FDTYPE_VNODE:
        result = _VnodeFdInfoWithPath()
        _pid_fd_info(pid, fd, PROC_PIDFDVNODEPATHINFO, result)
        stat_mapping = _vnode_stat_mapping(result.pvip.vip_vi.vi_stat)
        vnode = NativeVnodeFileDescriptorIdentity(
            **stat_mapping,
            vnode_type=int(result.pvip.vip_vi.vi_type),
            resolved_path_sha256=canonical_sha256(
                {"resolved_path_bytes": bytes(result.pvip.vip_path).hex()}
            ),
        )
        file_info = result.pfi
    elif kernel_type == _PROX_FDTYPE_SOCKET:
        result = _SocketFdInfo()
        _pid_fd_info(pid, fd, PROC_PIDFDSOCKETINFO, result)
        local_hash, peer_hash = _socket_endpoint_hashes(result.psi)
        socket_identity = NativeSocketFileDescriptorIdentity(
            family=int(result.psi.soi_family),
            socket_type=int(result.psi.soi_type),
            protocol=int(result.psi.soi_protocol),
            socket_kind=int(result.psi.soi_kind),
            socket_state=int(result.psi.soi_state),
            local_identity_sha256=local_hash,
            peer_identity_sha256=peer_hash,
        )
        file_info = result.pfi
    elif kernel_type == _PROX_FDTYPE_PIPE:
        result = _PipeFdInfo()
        _pid_fd_info(pid, fd, PROC_PIDFDPIPEINFO, result)
        stat_mapping = _vnode_stat_mapping(result.pipeinfo.pipe_stat)
        stat_mapping.pop("size")
        pipe = NativePipeFileDescriptorIdentity(
            **stat_mapping,
            pipe_status=int(result.pipeinfo.pipe_status),
            local_handle_sha256=canonical_sha256(
                {
                    "schema_id": "darwin-pipe-kernel-handle-v1",
                    "handle": int(result.pipeinfo.pipe_handle),
                }
            ),
            peer_handle_sha256=canonical_sha256(
                {
                    "schema_id": "darwin-pipe-kernel-handle-v1",
                    "handle": int(result.pipeinfo.pipe_peerhandle),
                }
            ),
        )
        file_info = result.pfi
    elif kernel_type == _PROX_FDTYPE_KQUEUE:
        result = _KqueueFdInfo()
        _pid_fd_info(pid, fd, PROC_PIDFDKQUEUEINFO, result)
        stat_mapping = _vnode_stat_mapping(result.kqueueinfo.kq_stat)
        stat_mapping.pop("size")
        kqueue = NativeKqueueFileDescriptorIdentity(
            **stat_mapping,
            kqueue_state=int(result.kqueueinfo.kq_state),
        )
        file_info = result.pfi
    else:
        raise BrokerProtocolError(
            f"file-descriptor {fd} kernel type {kernel_type} is unsupported"
        )
    status = int(file_info.fi_status)
    mapping = {
        "fd": fd,
        "kernel_type": kernel_type,
        "open_flags": int(file_info.fi_openflags),
        "kernel_status_flags": status,
        "descriptor_offset": int(file_info.fi_offset),
        "descriptor_type": int(file_info.fi_type),
        "guard_flags": int(file_info.fi_guardflags),
        "close_on_exec": bool(status & _PROC_FP_CLEXEC),
        "close_on_fork": bool(status & _PROC_FP_CLFORK),
        "guarded": bool(status & _PROC_FP_GUARDED),
        "shared": bool(status & _PROC_FP_SHARED),
        "vnode": vnode,
        "socket": socket_identity,
        "pipe": pipe,
        "kqueue": kqueue,
    }
    mapping["record_sha256"] = canonical_sha256(
        {
            key: asdict(value)
            if isinstance(
                value,
                (
                    NativeVnodeFileDescriptorIdentity,
                    NativeSocketFileDescriptorIdentity,
                    NativePipeFileDescriptorIdentity,
                    NativeKqueueFileDescriptorIdentity,
                ),
            )
            else value
            for key, value in mapping.items()
        }
    )
    return NativeFileDescriptorIdentity(**mapping)


def _file_descriptor_inventory_once(pid: int) -> tuple[tuple[int, int], ...]:
    library = _libproc()
    reader = library.proc_pidinfo
    reader.argtypes = (
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint64,
        ctypes.c_void_p,
        ctypes.c_int,
    )
    reader.restype = ctypes.c_int
    values = (_ProcFdInfo * MAX_INVENTORY_FILE_DESCRIPTORS)()
    ctypes.set_errno(0)
    size = int(
        reader(
            pid,
            PROC_PIDLISTFDS,
            0,
            ctypes.byref(values),
            ctypes.sizeof(values),
        )
    )
    if size <= 0:
        _raise_process_observation_error(
            ctypes.get_errno() or errno.ESRCH,
            "proc_pidinfo file-descriptor inventory",
            pid,
        )
    if size >= ctypes.sizeof(values):
        raise BrokerProtocolError(
            "file-descriptor inventory exceeds its bound"
        )
    item_size = ctypes.sizeof(_ProcFdInfo)
    if size % item_size:
        raise BrokerProtocolError(
            "file-descriptor inventory byte count is malformed"
        )
    count = size // item_size
    result = tuple(
        sorted(
            (int(value.proc_fd), int(value.proc_fdtype))
            for value in values[:count]
        )
    )
    if (
        not result
        or any(fd < 0 or fd_type <= 0 for fd, fd_type in result)
        or len({fd for fd, _ in result}) != len(result)
    ):
        raise BrokerProtocolError(
            "file-descriptor inventory identities differ"
        )
    return result


def native_file_descriptor_inventory(pid: int) -> tuple[tuple[int, int], ...]:
    """Return one race-bounded Darwin ``(fd, kernel_type)`` inventory."""

    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ValueError("file-descriptor-inventory PID must be positive")
    start_before = raw_process_start_abstime(pid)
    first = _file_descriptor_inventory_once(pid)
    second = _file_descriptor_inventory_once(pid)
    start_after = raw_process_start_abstime(pid)
    if start_before != start_after or first != second:
        raise BrokerProtocolError(
            "file-descriptor inventory changed during observation"
        )
    return second


def native_detailed_file_descriptor_inventory(
    pid: int,
) -> NativeFileDescriptorInventory:
    """Return a bounded double-stable, type-aware Darwin FD inventory.

    The process identity is observed on both sides of two complete descriptor
    scans.  Every descriptor is resolved through ``proc_pidfdinfo`` and an
    unsupported or unreadable kernel descriptor type fails the observation;
    there is no synthetic or partially-described success path.
    """

    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ValueError("detailed file-descriptor-inventory PID must be positive")
    process_before = kernel_process_identity(pid)
    first_started = time.monotonic_ns()
    first = tuple(
        _detailed_file_descriptor_identity(pid, fd, kernel_type)
        for fd, kernel_type in _file_descriptor_inventory_once(pid)
    )
    first_completed = time.monotonic_ns()
    second_started = time.monotonic_ns()
    second = tuple(
        _detailed_file_descriptor_identity(pid, fd, kernel_type)
        for fd, kernel_type in _file_descriptor_inventory_once(pid)
    )
    second_completed = time.monotonic_ns()
    process_after = kernel_process_identity(pid)
    if process_before != process_after or first != second:
        raise BrokerProtocolError(
            "detailed file-descriptor inventory changed during observation"
        )
    schema_id = "darwin-detailed-file-descriptor-inventory-v1"
    inventory_sha256 = canonical_sha256(
        {
            "schema_id": schema_id,
            "process": asdict(process_after),
            "descriptors": [asdict(value) for value in second],
        }
    )
    return NativeFileDescriptorInventory(
        schema_id=schema_id,
        process=process_after,
        first_scan_started_monotonic_ns=first_started,
        first_scan_completed_monotonic_ns=first_completed,
        second_scan_started_monotonic_ns=second_started,
        second_scan_completed_monotonic_ns=second_completed,
        descriptors=second,
        inventory_sha256=inventory_sha256,
    )


def _exact_dataclass_mapping(
    value: object,
    kind: type[object],
    name: str,
) -> dict[str, object]:
    expected = {item.name for item in dataclass_fields(kind)}
    if type(value) is not dict or set(value) != expected:
        raise BrokerProtocolError(f"{name} fields differ")
    return dict(value)


def _kernel_identity_from_mapping(value: object, name: str) -> KernelProcessIdentity:
    mapping = _exact_dataclass_mapping(value, KernelProcessIdentity, name)
    try:
        return KernelProcessIdentity(**mapping)
    except (TypeError, ValueError) as exc:
        raise BrokerProtocolError(f"{name} is malformed") from exc


def native_thread_inventory_from_mapping(value: object) -> NativeThreadInventory:
    mapping = _exact_dataclass_mapping(value, NativeThreadInventory, "thread inventory")
    mapping["process"] = _kernel_identity_from_mapping(
        mapping["process"], "thread inventory process"
    )
    raw_thread_ids = mapping["thread_ids"]
    if type(raw_thread_ids) not in {list, tuple}:
        raise BrokerProtocolError("thread inventory IDs are malformed")
    mapping["thread_ids"] = tuple(raw_thread_ids)
    try:
        return NativeThreadInventory(**mapping)
    except (TypeError, ValueError) as exc:
        raise BrokerProtocolError("thread inventory is malformed") from exc


def _descriptor_variant_from_mapping(
    value: object,
    kind: type[object],
    name: str,
) -> object | None:
    if value is None:
        return None
    mapping = _exact_dataclass_mapping(value, kind, name)
    try:
        return kind(**mapping)
    except (TypeError, ValueError) as exc:
        raise BrokerProtocolError(f"{name} is malformed") from exc


def native_file_descriptor_inventory_from_mapping(
    value: object,
) -> NativeFileDescriptorInventory:
    mapping = _exact_dataclass_mapping(
        value,
        NativeFileDescriptorInventory,
        "file-descriptor inventory",
    )
    mapping["process"] = _kernel_identity_from_mapping(
        mapping["process"], "file-descriptor inventory process"
    )
    raw_descriptors = mapping["descriptors"]
    if type(raw_descriptors) not in {list, tuple}:
        raise BrokerProtocolError("file-descriptor inventory rows are malformed")
    descriptors: list[NativeFileDescriptorIdentity] = []
    variants: tuple[tuple[str, type[object]], ...] = (
        ("vnode", NativeVnodeFileDescriptorIdentity),
        ("socket", NativeSocketFileDescriptorIdentity),
        ("pipe", NativePipeFileDescriptorIdentity),
        ("kqueue", NativeKqueueFileDescriptorIdentity),
    )
    for index, raw_descriptor in enumerate(raw_descriptors):
        descriptor = _exact_dataclass_mapping(
            raw_descriptor,
            NativeFileDescriptorIdentity,
            f"file-descriptor inventory row {index}",
        )
        for name, kind in variants:
            descriptor[name] = _descriptor_variant_from_mapping(
                descriptor[name], kind, f"file-descriptor {index} {name}"
            )
        try:
            descriptors.append(NativeFileDescriptorIdentity(**descriptor))
        except (TypeError, ValueError) as exc:
            raise BrokerProtocolError(
                f"file-descriptor inventory row {index} is malformed"
            ) from exc
    mapping["descriptors"] = tuple(descriptors)
    try:
        return NativeFileDescriptorInventory(**mapping)
    except (TypeError, ValueError) as exc:
        raise BrokerProtocolError("file-descriptor inventory is malformed") from exc


def _native_wait4_call(
    pid: int,
    options: int,
    *,
    absolute_deadline_ns: int,
) -> NativeWait4Result | None:
    _require_darwin()
    if isinstance(absolute_deadline_ns, bool) or not isinstance(absolute_deadline_ns, int) or absolute_deadline_ns <= 0:
        raise ValueError("wait4 absolute deadline must be positive")
    library = ctypes.CDLL(None, use_errno=True)
    waiter = library.wait4
    waiter.argtypes = (ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.c_int, ctypes.POINTER(_RUsage))
    waiter.restype = ctypes.c_int
    status = ctypes.c_int()
    usage = _RUsage()
    while True:
        if time.monotonic_ns() >= absolute_deadline_ns:
            raise TimeoutError("native wait4 absolute deadline expired")
        ctypes.set_errno(0)
        result = int(waiter(pid, ctypes.byref(status), options, ctypes.byref(usage)))
        if result >= 0 or ctypes.get_errno() != errno.EINTR:
            break
    if result == 0:
        return None
    if result < 0:
        error_number = ctypes.get_errno() or errno.EIO
        if error_number == errno.ECHILD:
            raise ChildProcessError(error_number, "wait4 found no child")
        raise OSError(error_number, "wait4 failed")
    return NativeWait4Result(
        pid=result,
        raw_status=int(status.value),
        rusage=RawRUsage(
            user=RawTimeval.from_raw(int(usage.ru_utime.tv_sec), int(usage.ru_utime.tv_usec)),
            system=RawTimeval.from_raw(int(usage.ru_stime.tv_sec), int(usage.ru_stime.tv_usec)),
        ),
        maximum_resident_set_size_bytes=int(usage.ru_maxrss),
        minor_faults=int(usage.ru_minflt),
        major_faults=int(usage.ru_majflt),
        voluntary_context_switches=int(usage.ru_nvcsw),
        involuntary_context_switches=int(usage.ru_nivcsw),
    )


def native_wait4_exact(
    pid: int,
    *,
    absolute_deadline_ns: int,
) -> NativeWait4Result | None:
    """Perform one non-reaping-until-terminal exact-PID WNOHANG probe.

    Callers own the bounded selector loop and must recheck the immutable
    deadline and process identity between probes.  This primitive can never
    block behind a resistant native child.
    """

    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ValueError("exact wait4 PID must be positive")
    result = _native_wait4_call(
        pid,
        os.WNOHANG,
        absolute_deadline_ns=absolute_deadline_ns,
    )
    if result is not None and result.pid != pid:
        raise BrokerProtocolError("exact wait4 returned a different PID")
    return result


def native_wait4_quiescence(*, absolute_deadline_ns: int) -> NativeWait4Result | None:
    """Return None only for ECHILD; any live/surprise child blocks quiescence."""

    try:
        result = _native_wait4_call(
            -1,
            os.WNOHANG,
            absolute_deadline_ns=absolute_deadline_ns,
        )
    except ChildProcessError:
        return None
    if result is None:
        raise BrokerProtocolError("wait4 quiescence found a live child")
    raise BrokerProtocolError(
        f"wait4 quiescence reaped unregistered child PID {result.pid}"
    )


__all__ = [
    "NativeExecutableRegionIdentity",
    "NativeExecutableRegionInventory",
    "NativeFileDescriptorIdentity",
    "NativeFileDescriptorInventory",
    "NativeKqueueFileDescriptorIdentity",
    "NativePipeFileDescriptorIdentity",
    "NativeSocketFileDescriptorIdentity",
    "NativeThreadInventory",
    "NativeVnodeFileDescriptorIdentity",
    "NativeWait4Result",
    "group_inventory",
    "kernel_process_identity",
    "native_detailed_file_descriptor_inventory",
    "native_detailed_thread_inventory",
    "native_file_descriptor_inventory",
    "native_file_descriptor_inventory_from_mapping",
    "native_executable_region_inventory",
    "native_process_path",
    "native_wait4_exact",
    "native_wait4_quiescence",
    "native_thread_inventory",
    "native_thread_inventory_from_mapping",
    "raw_process_start_abstime",
    "recursive_descendants",
    "trusted_launcher_identity",
]
