"""Credential and egress isolation for disposable latency workers."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import re
import socket
import stat
import sys
import sysconfig
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any


class _DarwinProcFdInfo(ctypes.Structure):
    _fields_ = (
        ("proc_fd", ctypes.c_int32),
        ("proc_fdtype", ctypes.c_uint32),
    )


class _DarwinProcFileInfo(ctypes.Structure):
    _fields_ = (
        ("fi_openflags", ctypes.c_uint32),
        ("fi_status", ctypes.c_uint32),
        ("fi_offset", ctypes.c_int64),
        ("fi_type", ctypes.c_int32),
        ("fi_guardflags", ctypes.c_uint32),
    )


class _DarwinVinfoStat(ctypes.Structure):
    _fields_ = (
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
    )


class _DarwinPipeInfo(ctypes.Structure):
    _fields_ = (
        ("pipe_stat", _DarwinVinfoStat),
        ("pipe_handle", ctypes.c_uint64),
        ("pipe_peerhandle", ctypes.c_uint64),
        ("pipe_status", ctypes.c_int32),
        ("rfu_1", ctypes.c_int32),
    )


class _DarwinPipeFdInfo(ctypes.Structure):
    _fields_ = (
        ("pfi", _DarwinProcFileInfo),
        ("pipeinfo", _DarwinPipeInfo),
    )


APPLICATION_ENV_ALLOWLIST = frozenset(
    {
        "MAX_UPLOAD_BYTES",
        "MAX_DOCUMENT_PAGES",
        "MAX_PDF_PAGES",
        "MAX_IMAGE_PIXELS",
        "MAX_IMAGE_TOTAL_PIXELS",
        "DOCUMENT_TIMEOUT_SECONDS",
        "OCR_LANGUAGES",
        "TESSERACT_CMD",
        "TESSERACT_DATA_PATH",
        "TARGETED_OCR_TIMEOUT_SECONDS",
        "TARGETED_OCR_SCALE",
        "TARGETED_OCR_MAX_PIXELS",
        "DOCLING_ARTIFACTS_PATH",
        "IMAGE_PRIMARY_OCR_MIN_CONFIDENCE",
        "IMAGE_LOW_CONFIDENCE_MIN_ALNUM_CHARS",
        "IMAGE_HEADING_MIN_CONFIDENCE",
        "IMAGE_HEADING_HEIGHT_RATIO",
        "IMAGE_HEADING_MIN_PAGE_HEIGHT_RATIO",
        "IMAGE_PICTURE_CLASSIFICATION_THRESHOLD",
        "IMAGE_CAPTIONING_ENABLED",
        "IMAGE_CAPTIONING_PROMPT",
        "PDF_VISUAL_ANALYSIS_ENABLED",
        "PDF_RENDER_OCR_MIN_NATIVE_ALNUM_CHARS",
        "PDF_RENDER_OCR_MIN_LAYOUT_COVERAGE",
        "PARSER_SHARED_IR_ENABLED",
        "PARSER_SHARED_IR_NORMALIZATION_ENABLED",
        "PARSER_CANONICAL_SERIALIZATION_ENABLED",
        "PARSER_TEXT_INTEGRITY_FONT_AUDIT_ENABLED",
        "PARSER_TEXT_INTEGRITY_FONT_RECOVERY_ENABLED",
        "PARSER_TEXT_INTEGRITY_SELECTIVE_SPAN_OCR_ENABLED",
        "PARSER_TEXT_RECONCILIATION_ENABLED",
        "PARSER_OCR_NUMERIC_CLEANUP_V2_ENABLED",
        "PARSER_OCR_SPATIAL_TOKEN_PRESERVATION_ENABLED",
        "PARSER_TEXT_INTEGRITY_SOURCE_ALIGNMENT_ENABLED",
        "PARSER_LAYOUT_TABLE_CAPTIONS_ENABLED",
        "PARSER_LAYOUT_VISUAL_RELATIONSHIPS_ENABLED",
        "PARSER_LAYOUT_SOURCE_NOTES_ENABLED",
        "PARSER_LAYOUT_RELATIONSHIP_ORDER_ENABLED",
        "PARSER_LAYOUT_TEXT_RUN_SEMANTICS_ENABLED",
        "PARSER_LAYOUT_FORMS_ENABLED",
        "PARSER_LAYOUT_OUTLINE_STRUCTURE_ENABLED",
        "PARSER_LAYOUT_RUNNING_REGIONS_ENABLED",
        "PARSER_TABLES_SPAN_FIDELITY_ENABLED",
        "PARSER_TABLES_EVIDENCE_RECONCILIATION_ENABLED",
        "PARSER_TABLES_CANDIDATE_GATE_ENABLED",
        "PARSER_TABLES_MULTI_PAGE_MERGE_ENABLED",
    }
)

SYSTEM_ENV_ALLOWLIST = frozenset(
    {
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PATH",
        "TMPDIR",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "TOKENIZERS_PARALLELISM",
    }
)

FIXED_OFFLINE_ENVIRONMENT = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "NO_PROXY": "*",
    "no_proxy": "*",
    "PYTHONHASHSEED": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONSAFEPATH": "1",
}

MAXIMUM_ENVIRONMENT_VALUE_BYTES = 16 * 1024
OS_NETWORK_SANDBOX_EXECUTABLE = "/usr/bin/sandbox-exec"
OS_NETWORK_SANDBOX_PROFILE = (
    "(version 1)(allow default)(deny network-outbound)(deny network-inbound)"
)
OS_NETWORK_SANDBOX_PROFILE_SIZE_BYTES = 71
OS_NETWORK_SANDBOX_PROFILE_SHA256 = (
    "e1641a84e8ffc71f77b3c0cf7e0027394ebd099dff618aa94c9ce944fb9850c4"
)
MAXIMUM_OS_NETWORK_SANDBOX_BINARY_BYTES = 1024 * 1024
CHILD_NETWORK_GUARD_RELATIVE_PATH = (
    "tests/benchmarks/latency_child_guard/sitecustomize.py"
)
CHILD_NETWORK_GUARD_SIZE_BYTES = 3_119
CHILD_NETWORK_GUARD_SHA256 = (
    "f6b85e4687fa011bf032dfb50b86031ea420e4f46e521833efe1bf9a214e592b"
)
NETWORK_GUARD_IMPLEMENTATION_RELATIVE_PATH = "tests/benchmarks/latency_isolation.py"
MAXIMUM_NETWORK_GUARD_IMPLEMENTATION_BYTES = 128 * 1024


def trusted_python_runtime_executable_paths() -> tuple[Path, ...]:
    """Return the exact CPython binaries allowed for owned helper processes."""

    base_executable = Path(
        getattr(sys, "_base_executable", None) or sys.executable
    ).resolve(strict=True)
    retained = [base_executable]
    if (
        platform.system() == "Darwin"
        and int(sysconfig.get_config_var("WITH_NEXT_FRAMEWORK") or 0) == 1
    ):
        framework = sysconfig.get_config_var("PYTHONFRAMEWORK")
        prefix = sysconfig.get_config_var("PYTHONFRAMEWORKINSTALLNAMEPREFIX")
        if (
            not isinstance(framework, str)
            or re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", framework) is None
            or not isinstance(prefix, str)
        ):
            raise RuntimeError("Darwin Python framework identity is invalid")
        framework_prefix = Path(prefix).resolve(strict=True)
        if framework_prefix != Path(sys.base_prefix).resolve(strict=True):
            raise RuntimeError("Darwin Python framework prefix differs")
        application_candidate = (
            framework_prefix
            / "Resources"
            / f"{framework}.app"
            / "Contents"
            / "MacOS"
            / framework
        )
        if application_candidate.is_symlink():
            raise RuntimeError("Darwin Python application executable is a symlink")
        application_executable = application_candidate.resolve(strict=True)
        if application_executable != application_candidate:
            raise RuntimeError("Darwin Python application executable path differs")
        application_stat = application_executable.lstat()
        if (
            not stat.S_ISREG(application_stat.st_mode)
            or not 0 < application_stat.st_size <= 16 * 1024 * 1024
        ):
            raise RuntimeError("Darwin Python application executable custody differs")
        retained.append(application_executable)
    return tuple(dict.fromkeys(retained))


def darwin_pipe_file_descriptors(pid: int) -> tuple[int, ...]:
    """List one process's pipe FDs through bounded Darwin libproc evidence."""

    if platform.system() != "Darwin" or isinstance(pid, bool) or pid <= 0:
        raise RuntimeError("Darwin pipe descriptor inventory is unavailable")
    libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    proc_pidinfo = libproc.proc_pidinfo
    proc_pidinfo.argtypes = (
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint64,
        ctypes.c_void_p,
        ctypes.c_int,
    )
    proc_pidinfo.restype = ctypes.c_int
    item_size = ctypes.sizeof(_DarwinProcFdInfo)
    required = proc_pidinfo(pid, 1, 0, None, 0)
    if required <= 0 or required % item_size or required > item_size * 16_384:
        raise RuntimeError("Darwin process FD inventory size differs")
    capacity = required + item_size * 32
    buffer = (ctypes.c_ubyte * capacity)()
    observed = proc_pidinfo(pid, 1, 0, buffer, capacity)
    if observed <= 0 or observed > capacity or observed % item_size:
        raise RuntimeError("Darwin process FD inventory read differs")
    count = observed // item_size
    inventory = ctypes.cast(
        buffer,
        ctypes.POINTER(_DarwinProcFdInfo * count),
    ).contents
    descriptors = tuple(
        int(item.proc_fd) for item in inventory if item.proc_fdtype == 6
    )
    if any(descriptor < 0 for descriptor in descriptors) or len(descriptors) != len(
        set(descriptors)
    ):
        raise RuntimeError("Darwin pipe descriptor inventory is non-canonical")
    return tuple(sorted(descriptors))


def darwin_pipe_endpoint_identity(
    pid: int,
    descriptor: int,
    *,
    expected_access: int | None = None,
) -> tuple[int, int]:
    """Return the kernel handle and peer handle for one exact pipe endpoint."""

    if (
        platform.system() != "Darwin"
        or isinstance(pid, bool)
        or pid <= 0
        or isinstance(descriptor, bool)
        or descriptor < 0
    ):
        raise RuntimeError("Darwin pipe endpoint identity is unavailable")
    libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    proc_pidfdinfo = libproc.proc_pidfdinfo
    proc_pidfdinfo.argtypes = (
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_int,
    )
    proc_pidfdinfo.restype = ctypes.c_int
    retained = _DarwinPipeFdInfo()
    size = ctypes.sizeof(retained)
    observed = proc_pidfdinfo(pid, descriptor, 6, ctypes.byref(retained), size)
    identity = (
        int(retained.pipeinfo.pipe_handle),
        int(retained.pipeinfo.pipe_peerhandle),
    )
    access = int(retained.pfi.fi_openflags) & 3
    if (
        observed != size
        or retained.pfi.fi_type != 6
        or expected_access not in {None, 1, 2}
        or (expected_access is not None and access != expected_access)
        or not all(identity)
        or identity[0] == identity[1]
    ):
        raise RuntimeError("Darwin pipe endpoint kernel identity differs")
    return identity


def attest_darwin_pipe_peers(
    left_pid: int,
    left_descriptor: int,
    right_pid: int,
    right_descriptor: int,
) -> None:
    """Require two cross-process descriptors to be opposite pipe endpoints."""

    left = darwin_pipe_endpoint_identity(
        left_pid,
        left_descriptor,
        expected_access=2,
    )
    right = darwin_pipe_endpoint_identity(
        right_pid,
        right_descriptor,
        expected_access=1,
    )
    if left != (right[1], right[0]):
        raise RuntimeError("Darwin resource-tracker pipe endpoints are not peers")


NETWORK_DIAGNOSTIC_OPERATIONS = frozenset(
    {
        "create_connection",
        "getaddrinfo",
        "gethostbyaddr",
        "gethostbyname",
        "gethostbyname_ex",
        "getnameinfo",
        "socket_connect",
        "socket_connect_ex",
        "socket_create",
        "socket_sendto",
    }
)
NETWORK_DIAGNOSTIC_MODULE_PREFIXES = (
    "PIL",
    "app",
    "docling",
    "docling_core",
    "docling_parse",
    "httpcore",
    "httpx",
    "huggingface_hub",
    "multiprocessing",
    "pypdfium2",
    "requests",
    "socket",
    "tests.benchmarks.latency_isolation",
    "tests.benchmarks.latency_worker",
    "torch",
    "transformers",
    "urllib",
    "urllib3",
)
MAXIMUM_NETWORK_DIAGNOSTIC_FRAMES = 32
_NETWORK_DIAGNOSTIC_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_.<>]{0,127}\Z")


def sanitize_network_diagnostic_event(
    operation: str,
    frames: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Retain only a bounded call operation and code identity.

    The diagnostic deliberately has no channel for socket addresses, call
    arguments, frame locals, source lines, exception text, or document bytes.
    """

    if operation not in NETWORK_DIAGNOSTIC_OPERATIONS:
        raise ValueError("network diagnostic operation is not allowlisted")
    retained: list[dict[str, object]] = []
    for frame in frames:
        module = frame.get("module")
        function = frame.get("function")
        line = frame.get("line")
        if (
            not isinstance(module, str)
            or not isinstance(function, str)
            or isinstance(line, bool)
            or not isinstance(line, int)
            or line <= 0
            or not _NETWORK_DIAGNOSTIC_IDENTIFIER.fullmatch(module)
            or not _NETWORK_DIAGNOSTIC_IDENTIFIER.fullmatch(function)
            or not any(
                module == prefix or module.startswith(f"{prefix}.")
                for prefix in NETWORK_DIAGNOSTIC_MODULE_PREFIXES
            )
        ):
            continue
        retained.append(
            {
                "module": module,
                "function": function,
                "line": line,
            }
        )
        if len(retained) == MAXIMUM_NETWORK_DIAGNOSTIC_FRAMES:
            break
    return {"operation": operation, "frames": tuple(retained)}


def _capture_network_diagnostic_frames() -> tuple[dict[str, object], ...]:
    retained: list[dict[str, object]] = []
    frame = sys._getframe(1)
    try:
        while frame is not None:
            retained.append(
                {
                    "module": frame.f_globals.get("__name__"),
                    "function": frame.f_code.co_name,
                    "line": frame.f_lineno,
                }
            )
            frame = frame.f_back
    finally:
        del frame
    retained.reverse()
    return tuple(retained)


def sanitized_worker_environment(
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return an explicit non-secret, offline worker environment."""

    incoming = os.environ if source is None else source
    retained: dict[str, str] = {}
    for name in sorted(APPLICATION_ENV_ALLOWLIST | SYSTEM_ENV_ALLOWLIST):
        value = incoming.get(name)
        if value is None:
            continue
        if not isinstance(value, str) or "\x00" in value:
            raise ValueError("worker environment contains an invalid value")
        if len(value.encode("utf-8")) > MAXIMUM_ENVIRONMENT_VALUE_BYTES:
            raise ValueError("worker environment value exceeds its byte bound")
        retained[name] = value
    retained.update(FIXED_OFFLINE_ENVIRONMENT)
    return dict(sorted(retained.items()))


def worker_environment_sha256(environment: Mapping[str, str]) -> str:
    payload = json.dumps(
        dict(sorted(environment.items())),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def exact_supplied_worker_environment_sha256(
    environment: Mapping[str, str],
) -> str:
    """Hash supplied keys while rejecting all but Darwin's fixed injected key."""

    retained = dict(environment)
    injected = retained.pop("__CF_USER_TEXT_ENCODING", None)
    if injected is not None and injected != f"0x{os.getuid():X}:0x0:0x0":
        raise RuntimeError("Darwin injected environment identity differs")
    return worker_environment_sha256(retained)


def _child_network_guard_bytes(workspace: Path) -> bytes:
    root = workspace.resolve()
    path = root / CHILD_NETWORK_GUARD_RELATIVE_PATH
    current = root
    for part in Path(CHILD_NETWORK_GUARD_RELATIVE_PATH).parts:
        current = current / part
        if current.is_symlink():
            raise RuntimeError("child network guard path contains a symlink")
    if path.resolve(strict=True).relative_to(root) != Path(
        CHILD_NETWORK_GUARD_RELATIVE_PATH
    ):
        raise RuntimeError("child network guard escaped workspace custody")
    file_stat = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(file_stat.st_mode)
        or file_stat.st_size != CHILD_NETWORK_GUARD_SIZE_BYTES
    ):
        raise RuntimeError("child network guard file custody differs")
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
    )
    opened_stat = os.fstat(descriptor)
    if (
        opened_stat.st_dev != file_stat.st_dev
        or opened_stat.st_ino != file_stat.st_ino
        or opened_stat.st_size != file_stat.st_size
        or opened_stat.st_mtime_ns != file_stat.st_mtime_ns
    ):
        os.close(descriptor)
        raise RuntimeError("child network guard changed before open")
    with os.fdopen(descriptor, "rb") as stream:
        data = stream.read(CHILD_NETWORK_GUARD_SIZE_BYTES + 1)
        final_stat = os.fstat(stream.fileno())
    if (
        len(data) != CHILD_NETWORK_GUARD_SIZE_BYTES
        or final_stat.st_dev != opened_stat.st_dev
        or final_stat.st_ino != opened_stat.st_ino
        or final_stat.st_size != opened_stat.st_size
        or final_stat.st_mtime_ns != opened_stat.st_mtime_ns
        or hashlib.sha256(data).hexdigest() != CHILD_NETWORK_GUARD_SHA256
    ):
        raise RuntimeError("child network guard identity differs")
    return data


def child_network_guard_identity(workspace: Path) -> tuple[int, str]:
    data = _child_network_guard_bytes(workspace)
    return len(data), CHILD_NETWORK_GUARD_SHA256


def network_guard_implementation_identity(workspace: Path) -> tuple[int, str]:
    root = workspace.resolve()
    path = root / NETWORK_GUARD_IMPLEMENTATION_RELATIVE_PATH
    current = root
    for part in Path(NETWORK_GUARD_IMPLEMENTATION_RELATIVE_PATH).parts:
        current = current / part
        if current.is_symlink():
            raise RuntimeError("network guard implementation path contains a symlink")
    if path.resolve(strict=True).relative_to(root) != Path(
        NETWORK_GUARD_IMPLEMENTATION_RELATIVE_PATH
    ):
        raise RuntimeError("network guard implementation escaped workspace custody")
    file_stat = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(file_stat.st_mode)
        or file_stat.st_size <= 0
        or file_stat.st_size > MAXIMUM_NETWORK_GUARD_IMPLEMENTATION_BYTES
    ):
        raise RuntimeError("network guard implementation custody differs")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    opened_stat = os.fstat(descriptor)
    if (
        opened_stat.st_dev != file_stat.st_dev
        or opened_stat.st_ino != file_stat.st_ino
        or opened_stat.st_size != file_stat.st_size
        or opened_stat.st_mtime_ns != file_stat.st_mtime_ns
        or not stat.S_ISREG(opened_stat.st_mode)
    ):
        os.close(descriptor)
        raise RuntimeError("network guard implementation changed before open")
    digest = hashlib.sha256()
    observed = 0
    with os.fdopen(descriptor, "rb") as stream:
        while chunk := stream.read(64 * 1024):
            observed += len(chunk)
            if observed > MAXIMUM_NETWORK_GUARD_IMPLEMENTATION_BYTES:
                raise RuntimeError("network guard implementation exceeded its bound")
            digest.update(chunk)
        final_stat = os.fstat(stream.fileno())
    if (
        observed != file_stat.st_size
        or final_stat.st_dev != opened_stat.st_dev
        or final_stat.st_ino != opened_stat.st_ino
        or final_stat.st_size != opened_stat.st_size
        or final_stat.st_mtime_ns != opened_stat.st_mtime_ns
    ):
        raise RuntimeError("network guard implementation changed while read")
    return observed, digest.hexdigest()


def private_child_network_guard_identity(guard_root: Path) -> tuple[int, str]:
    """Validate the private byte-pinned sitecustomize used by one worker."""

    root = guard_root.resolve(strict=True)
    root_stat = root.lstat()
    if (
        guard_root.is_symlink()
        or not stat.S_ISDIR(root_stat.st_mode)
        or stat.S_IMODE(root_stat.st_mode) != 0o700
        or root_stat.st_uid != os.getuid()
    ):
        raise RuntimeError("private child guard root custody differs")
    path = root / "sitecustomize.py"
    file_stat = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(file_stat.st_mode)
        or stat.S_IMODE(file_stat.st_mode) != 0o600
        or file_stat.st_uid != os.getuid()
        or file_stat.st_nlink != 1
        or file_stat.st_size != CHILD_NETWORK_GUARD_SIZE_BYTES
    ):
        raise RuntimeError("private child network guard custody differs")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    opened_stat = os.fstat(descriptor)
    if (
        opened_stat.st_dev != file_stat.st_dev
        or opened_stat.st_ino != file_stat.st_ino
        or opened_stat.st_size != file_stat.st_size
        or opened_stat.st_mtime_ns != file_stat.st_mtime_ns
        or not stat.S_ISREG(opened_stat.st_mode)
    ):
        os.close(descriptor)
        raise RuntimeError("private child guard changed before open")
    with os.fdopen(descriptor, "rb") as stream:
        data = stream.read(CHILD_NETWORK_GUARD_SIZE_BYTES + 1)
        final_stat = os.fstat(stream.fileno())
    if (
        len(data) != CHILD_NETWORK_GUARD_SIZE_BYTES
        or final_stat.st_dev != opened_stat.st_dev
        or final_stat.st_ino != opened_stat.st_ino
        or final_stat.st_size != opened_stat.st_size
        or final_stat.st_mtime_ns != opened_stat.st_mtime_ns
        or hashlib.sha256(data).hexdigest() != CHILD_NETWORK_GUARD_SHA256
    ):
        raise RuntimeError("private child guard identity differs")
    return len(data), CHILD_NETWORK_GUARD_SHA256


def materialize_private_child_network_guard(
    workspace: Path,
    protocol_root: Path,
) -> Path:
    """Create one exclusive private sitecustomize copy for a worker tree."""

    source = _child_network_guard_bytes(workspace)
    root = protocol_root.resolve(strict=True)
    root_stat = root.lstat()
    if (
        protocol_root.is_symlink()
        or not stat.S_ISDIR(root_stat.st_mode)
        or stat.S_IMODE(root_stat.st_mode) != 0o700
        or root_stat.st_uid != os.getuid()
    ):
        raise RuntimeError("worker protocol root custody differs")
    target = root / "sitecustomize.py"
    descriptor = os.open(
        target,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        written = 0
        while written < len(source):
            count = os.write(descriptor, source[written:])
            if count <= 0:
                raise RuntimeError("private child guard write did not advance")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    private_child_network_guard_identity(root)
    return root


def controlled_worker_environment(
    workspace: Path,
    source: Mapping[str, str] | None = None,
    *,
    child_guard_root: Path | None = None,
) -> dict[str, str]:
    if child_guard_root is None:
        child_network_guard_identity(workspace)
        guard_root = workspace.resolve() / "tests/benchmarks/latency_child_guard"
    else:
        private_child_network_guard_identity(child_guard_root)
        guard_root = child_guard_root.resolve(strict=True)
    retained = sanitized_worker_environment(source)
    retained["PHASE_LATENCY_CHILD_GUARD"] = "all-python-processes-v1"
    implementation_size, implementation_sha256 = network_guard_implementation_identity(
        workspace
    )
    retained["PHASE_LATENCY_GUARD_IMPLEMENTATION_PATH"] = str(
        workspace.resolve() / NETWORK_GUARD_IMPLEMENTATION_RELATIVE_PATH
    )
    retained["PHASE_LATENCY_GUARD_IMPLEMENTATION_SIZE_BYTES"] = str(implementation_size)
    retained["PHASE_LATENCY_GUARD_IMPLEMENTATION_SHA256"] = implementation_sha256
    retained["PYTHONPATH"] = os.pathsep.join(
        (str(guard_root), str(workspace.resolve()))
    )
    return dict(sorted(retained.items()))


def os_network_sandbox_identity() -> tuple[int, str]:
    """Return the exact Darwin sandbox executable identity or fail closed."""

    profile_bytes = OS_NETWORK_SANDBOX_PROFILE.encode("ascii")
    if (
        len(profile_bytes) != OS_NETWORK_SANDBOX_PROFILE_SIZE_BYTES
        or hashlib.sha256(profile_bytes).hexdigest()
        != OS_NETWORK_SANDBOX_PROFILE_SHA256
    ):
        raise RuntimeError("OS network sandbox profile identity differs")
    if platform.system() != "Darwin":
        raise RuntimeError("OS process-tree network sandbox requires Darwin")
    path = Path(OS_NETWORK_SANDBOX_EXECUTABLE)
    file_stat = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(file_stat.st_mode)
        or file_stat.st_uid != 0
        or stat.S_IMODE(file_stat.st_mode) & 0o022
        or file_stat.st_nlink != 1
        or file_stat.st_size <= 0
        or file_stat.st_size > MAXIMUM_OS_NETWORK_SANDBOX_BINARY_BYTES
        or not os.access(path, os.X_OK)
    ):
        raise RuntimeError("OS network sandbox executable custody differs")
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
    )
    opened_stat = os.fstat(descriptor)
    if (
        opened_stat.st_dev != file_stat.st_dev
        or opened_stat.st_ino != file_stat.st_ino
        or opened_stat.st_size != file_stat.st_size
        or opened_stat.st_mtime_ns != file_stat.st_mtime_ns
        or not stat.S_ISREG(opened_stat.st_mode)
    ):
        os.close(descriptor)
        raise RuntimeError("OS network sandbox executable changed before open")
    with os.fdopen(descriptor, "rb") as stream:
        data = stream.read(MAXIMUM_OS_NETWORK_SANDBOX_BINARY_BYTES + 1)
        final_stat = os.fstat(stream.fileno())
    if (
        len(data) != file_stat.st_size
        or final_stat.st_dev != opened_stat.st_dev
        or final_stat.st_ino != opened_stat.st_ino
        or final_stat.st_size != opened_stat.st_size
        or final_stat.st_mtime_ns != opened_stat.st_mtime_ns
    ):
        raise RuntimeError("OS network sandbox executable changed while read")
    return len(data), hashlib.sha256(data).hexdigest()


def sandboxed_worker_command(command: Sequence[str]) -> tuple[str, ...]:
    if not command:
        raise ValueError("sandboxed worker command cannot be empty")
    os_network_sandbox_identity()
    return (
        OS_NETWORK_SANDBOX_EXECUTABLE,
        "-p",
        OS_NETWORK_SANDBOX_PROFILE,
        *command,
    )


def validate_owned_unix_probe(
    path: Path,
    *,
    expected_dev: int,
    expected_ino: int,
) -> None:
    """Validate one exact private AF_UNIX socket pathname generation."""

    observed = path.lstat()
    if (
        stat.S_ISLNK(observed.st_mode)
        or not stat.S_ISSOCK(observed.st_mode)
        or stat.S_IMODE(observed.st_mode) != 0o600
        or observed.st_uid != os.getuid()
        or observed.st_nlink != 1
        or (observed.st_dev, observed.st_ino) != (expected_dev, expected_ino)
    ):
        raise RuntimeError("OS sandbox Unix probe custody differs")
    confirmed = path.lstat()
    if (
        confirmed.st_dev,
        confirmed.st_ino,
        confirmed.st_mode,
        confirmed.st_uid,
        confirmed.st_nlink,
    ) != (
        observed.st_dev,
        observed.st_ino,
        observed.st_mode,
        observed.st_uid,
        observed.st_nlink,
    ):
        raise RuntimeError("OS sandbox Unix probe identity changed during validation")


class NetworkIsolationError(RuntimeError):
    """Raised before a disposable worker can create an Internet socket."""


class NoEgressGuard:
    """Process-local AF_INET/AF_INET6 denial with exact reversible bindings."""

    def __init__(
        self,
        *,
        diagnostic_sink: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        self._installed = False
        self._denied_attempts = 0
        self._lock = threading.Lock()
        self._diagnostic_sink = diagnostic_sink
        self._denial_marker = os.environ.get("PHASE_LATENCY_NETWORK_DENIAL_MARKER")
        self._original_socket = socket.socket
        self._original_socket_type = socket.SocketType
        self._original_getaddrinfo = socket.getaddrinfo
        self._original_gethostbyaddr = socket.gethostbyaddr
        self._original_gethostbyname = socket.gethostbyname
        self._original_gethostbyname_ex = socket.gethostbyname_ex
        self._original_getnameinfo = socket.getnameinfo
        self._original_create_connection = socket.create_connection
        self._original_has_ipv6 = socket.has_ipv6
        self._guarded_socket: type[socket.socket] | None = None
        self._guarded_getaddrinfo: Callable[..., Any] | None = None
        self._guarded_gethostbyaddr: Callable[..., Any] | None = None
        self._guarded_gethostbyname: Callable[..., Any] | None = None
        self._guarded_gethostbyname_ex: Callable[..., Any] | None = None
        self._guarded_getnameinfo: Callable[..., Any] | None = None
        self._guarded_create_connection: Callable[..., Any] | None = None

    @property
    def denied_attempts(self) -> int:
        with self._lock:
            return self._denied_attempts

    @property
    def installed(self) -> bool:
        return self._installed

    @property
    def bindings_exact(self) -> bool:
        return bool(
            self._installed
            and self._guarded_socket is not None
            and socket.socket is self._guarded_socket
            and socket.SocketType is self._guarded_socket
            and socket.getaddrinfo is self._guarded_getaddrinfo
            and socket.gethostbyaddr is self._guarded_gethostbyaddr
            and socket.gethostbyname is self._guarded_gethostbyname
            and socket.gethostbyname_ex is self._guarded_gethostbyname_ex
            and socket.getnameinfo is self._guarded_getnameinfo
            and socket.create_connection is self._guarded_create_connection
            and socket.has_ipv6 is False
        )

    def _deny(self, operation: str) -> None:
        with self._lock:
            self._denied_attempts += 1
        if self._denial_marker is not None:
            marker = Path(self._denial_marker)
            if not marker.is_absolute() or marker.name not in {
                "network-denied",
                "network-probe-denied",
            }:
                raise RuntimeError("network denial marker path differs")
            parent_stat = marker.parent.lstat()
            if (
                marker.parent.is_symlink()
                or not stat.S_ISDIR(parent_stat.st_mode)
                or stat.S_IMODE(parent_stat.st_mode) != 0o700
                or parent_stat.st_uid != os.getuid()
            ):
                raise RuntimeError("network denial marker root custody differs")
            try:
                descriptor = os.open(
                    marker,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
            except FileExistsError:
                marker_stat = marker.lstat()
                if (
                    marker.is_symlink()
                    or not stat.S_ISREG(marker_stat.st_mode)
                    or stat.S_IMODE(marker_stat.st_mode) != 0o600
                    or marker_stat.st_uid != os.getuid()
                    or marker_stat.st_nlink != 1
                    or marker_stat.st_size != 0
                ):
                    raise RuntimeError("network denial marker custody differs")
                descriptor = os.open(
                    marker,
                    os.O_RDONLY
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                )
                try:
                    opened_stat = os.fstat(descriptor)
                    final_stat = marker.lstat()
                finally:
                    os.close(descriptor)
                if (
                    opened_stat.st_dev != marker_stat.st_dev
                    or opened_stat.st_ino != marker_stat.st_ino
                    or final_stat.st_dev != opened_stat.st_dev
                    or final_stat.st_ino != opened_stat.st_ino
                    or not stat.S_ISREG(opened_stat.st_mode)
                    or stat.S_IMODE(opened_stat.st_mode) != 0o600
                    or opened_stat.st_uid != os.getuid()
                    or opened_stat.st_nlink != 1
                    or opened_stat.st_size != 0
                    or not stat.S_ISREG(final_stat.st_mode)
                    or stat.S_IMODE(final_stat.st_mode) != 0o600
                    or final_stat.st_uid != os.getuid()
                    or final_stat.st_nlink != 1
                    or final_stat.st_size != 0
                ):
                    raise RuntimeError("network denial marker identity differs")
            else:
                try:
                    opened_stat = os.fstat(descriptor)
                    final_stat = marker.lstat()
                finally:
                    os.close(descriptor)
                if (
                    final_stat.st_dev != opened_stat.st_dev
                    or final_stat.st_ino != opened_stat.st_ino
                    or not stat.S_ISREG(opened_stat.st_mode)
                    or stat.S_IMODE(opened_stat.st_mode) != 0o600
                    or opened_stat.st_uid != os.getuid()
                    or opened_stat.st_nlink != 1
                    or opened_stat.st_size != 0
                    or not stat.S_ISREG(final_stat.st_mode)
                    or stat.S_IMODE(final_stat.st_mode) != 0o600
                    or final_stat.st_uid != os.getuid()
                    or final_stat.st_nlink != 1
                    or final_stat.st_size != 0
                ):
                    raise RuntimeError("network denial marker identity differs")
        if self._diagnostic_sink is not None:
            event = sanitize_network_diagnostic_event(
                operation,
                _capture_network_diagnostic_frames(),
            )
            try:
                self._diagnostic_sink(event)
            except BaseException:  # noqa: BLE001, S110 - diagnostics cannot weaken denial
                # Optional diagnostics cannot weaken or replace the denial.
                pass
        raise NetworkIsolationError("latency worker network egress is disabled")

    def install(self) -> None:
        if self._installed:
            raise RuntimeError("network isolation guard is single-install")
        guard = self
        original_socket = self._original_socket

        class GuardedSocket(original_socket):
            def __init__(self, family: int = -1, *args: Any, **kwargs: Any) -> None:
                if family in {socket.AF_INET, socket.AF_INET6}:
                    guard._deny("socket_create")
                super().__init__(family, *args, **kwargs)

            def connect(self, address: Any) -> Any:
                if self.family in {socket.AF_INET, socket.AF_INET6}:
                    guard._deny("socket_connect")
                return super().connect(address)

            def connect_ex(self, address: Any) -> int:
                if self.family in {socket.AF_INET, socket.AF_INET6}:
                    guard._deny("socket_connect_ex")
                return super().connect_ex(address)

            def sendto(self, *args: Any, **kwargs: Any) -> int:
                if self.family in {socket.AF_INET, socket.AF_INET6}:
                    guard._deny("socket_sendto")
                return super().sendto(*args, **kwargs)

        def denied_getaddrinfo(*_args: Any, **_kwargs: Any) -> Any:
            guard._deny("getaddrinfo")

        def denied_create_connection(*_args: Any, **_kwargs: Any) -> Any:
            guard._deny("create_connection")

        def denied_gethostbyaddr(*_args: Any, **_kwargs: Any) -> Any:
            guard._deny("gethostbyaddr")

        def denied_gethostbyname(*_args: Any, **_kwargs: Any) -> Any:
            guard._deny("gethostbyname")

        def denied_gethostbyname_ex(*_args: Any, **_kwargs: Any) -> Any:
            guard._deny("gethostbyname_ex")

        def denied_getnameinfo(*_args: Any, **_kwargs: Any) -> Any:
            guard._deny("getnameinfo")

        self._guarded_socket = GuardedSocket
        self._guarded_getaddrinfo = denied_getaddrinfo
        self._guarded_gethostbyaddr = denied_gethostbyaddr
        self._guarded_gethostbyname = denied_gethostbyname
        self._guarded_gethostbyname_ex = denied_gethostbyname_ex
        self._guarded_getnameinfo = denied_getnameinfo
        self._guarded_create_connection = denied_create_connection
        try:
            socket.socket = GuardedSocket
            socket.SocketType = GuardedSocket
            socket.getaddrinfo = denied_getaddrinfo
            socket.gethostbyaddr = denied_gethostbyaddr
            socket.gethostbyname = denied_gethostbyname
            socket.gethostbyname_ex = denied_gethostbyname_ex
            socket.getnameinfo = denied_getnameinfo
            socket.create_connection = denied_create_connection
            socket.has_ipv6 = False
        except BaseException:
            socket.socket = self._original_socket
            socket.SocketType = self._original_socket_type
            socket.getaddrinfo = self._original_getaddrinfo
            socket.gethostbyaddr = self._original_gethostbyaddr
            socket.gethostbyname = self._original_gethostbyname
            socket.gethostbyname_ex = self._original_gethostbyname_ex
            socket.getnameinfo = self._original_getnameinfo
            socket.create_connection = self._original_create_connection
            socket.has_ipv6 = self._original_has_ipv6
            self._guarded_socket = None
            self._guarded_getaddrinfo = None
            self._guarded_gethostbyaddr = None
            self._guarded_gethostbyname = None
            self._guarded_gethostbyname_ex = None
            self._guarded_getnameinfo = None
            self._guarded_create_connection = None
            raise
        self._installed = True

    def close(self) -> None:
        if not self._installed or self._guarded_socket is None:
            raise RuntimeError("network isolation guard is not installed")
        drifted = not self.bindings_exact
        restored_exact = False
        try:
            socket.socket = self._original_socket
            socket.SocketType = self._original_socket_type
            socket.getaddrinfo = self._original_getaddrinfo
            socket.gethostbyaddr = self._original_gethostbyaddr
            socket.gethostbyname = self._original_gethostbyname
            socket.gethostbyname_ex = self._original_gethostbyname_ex
            socket.getnameinfo = self._original_getnameinfo
            socket.create_connection = self._original_create_connection
            socket.has_ipv6 = self._original_has_ipv6
            restored_exact = (
                socket.socket is self._original_socket
                and socket.SocketType is self._original_socket_type
                and socket.getaddrinfo is self._original_getaddrinfo
                and socket.gethostbyaddr is self._original_gethostbyaddr
                and socket.gethostbyname is self._original_gethostbyname
                and socket.gethostbyname_ex is self._original_gethostbyname_ex
                and socket.getnameinfo is self._original_getnameinfo
                and socket.create_connection is self._original_create_connection
                and socket.has_ipv6 is self._original_has_ipv6
            )
        finally:
            self._installed = False
            self._guarded_socket = None
            self._guarded_getaddrinfo = None
            self._guarded_gethostbyaddr = None
            self._guarded_gethostbyname = None
            self._guarded_gethostbyname_ex = None
            self._guarded_getnameinfo = None
            self._guarded_create_connection = None
        if drifted or not restored_exact:
            raise RuntimeError("network isolation socket binding drifted")


def normalized_worker_environment_sha256(
    environment: Mapping[str, str],
    *,
    workspace: Path,
    protocol_root: Path,
) -> str:
    """Bind an exact per-run environment to one stable custody policy hash."""

    root = protocol_root.resolve(strict=True)
    expected_pythonpath = os.pathsep.join((str(root), str(workspace.resolve())))
    expected_pycache = str(root / "pycache")
    expected_denial_marker = str(root / "network-denied")
    if (
        environment.get("PYTHONPATH") != expected_pythonpath
        or environment.get("PYTHONPYCACHEPREFIX") != expected_pycache
        or environment.get("PHASE_LATENCY_NETWORK_DENIAL_MARKER")
        != expected_denial_marker
        or environment.get("PYTHONSAFEPATH") != "1"
    ):
        raise RuntimeError("per-run worker environment path custody differs")
    normalized = controlled_worker_environment(workspace, environment)
    return worker_environment_sha256(normalized)
