"""Pre-import subprocess facade for one capability-bound Tesseract broker."""

from __future__ import annotations

import contextlib
import array
import errno
import fcntl
import hashlib
import hmac
import math
import os
import signal
import socket
import stat
import subprocess
import threading
import time
import termios
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from app.services.tesseract_broker_protocol import (
    BrokerBarrierSnapshot,
    BrokerPostReleaseBaseline,
    BrokerProtocolError,
    BrokerQuiescenceReceipt,
    BrokerRequestBindingEvidence,
    BrokerRequestReceipt,
    BrokerRunOutputManifest,
    BrokerThreadTransfer,
    FramedChannel,
    KernelProcessIdentity,
    MAX_RUN_INPUT_BYTES,
    WorkerForkDenialEvidence,
    build_run_input_transport,
    canonical_sha256,
    canonical_tesseract_logical_argv_sha256,
    broker_post_release_baseline_from_mapping,
    immutable_input_observation_from_mapping,
    quiescence_from_mapping,
    receive_request_receipt_chunks,
    receive_run_blob_chunks,
    request_binding_from_mapping,
    request_receipt_manifest_from_mapping,
    run_output_manifest_from_mapping,
    send_run_blob_chunks,
    thread_transfer_from_mapping,
)


BROKER_CLIENT_FATAL_EXIT_CODE = 80
BROKER_FD_ENV = "PARSER_TESSERACT_BROKER_FD"
BROKER_NONCE_SHA_ENV = "PARSER_TESSERACT_BROKER_NONCE_SHA256"
BROKER_SCOPE_ENV = "PARSER_TESSERACT_BROKER_SCOPE_SHA256"
BROKER_PID_ENV = "PARSER_TESSERACT_BROKER_PID"
BROKER_START_ABSTIME_ENV = "PARSER_TESSERACT_BROKER_START_ABSTIME"
BROKER_PGID_ENV = "PARSER_TESSERACT_BROKER_PGID"
BROKER_SID_ENV = "PARSER_TESSERACT_BROKER_SID"
BROKER_EXECUTABLE_ENV = "PARSER_TESSERACT_EXECUTABLE"
BROKER_EXECUTABLE_SHA_ENV = "PARSER_TESSERACT_EXECUTABLE_SHA256"
BROKER_STAGED_EXECUTABLE_ENV = "PARSER_TESSERACT_STAGED_EXECUTABLE"
BROKER_STAGED_EXECUTABLE_SHA_ENV = "PARSER_TESSERACT_STAGED_EXECUTABLE_SHA256"
BROKER_NATIVE_CLOSURE_SHA_ENV = "PARSER_TESSERACT_NATIVE_CLOSURE_SHA256"
BROKER_NATIVE_SPAWN_GUARD_SHA_ENV = (
    "PARSER_TESSERACT_NATIVE_SPAWN_GUARD_SHA256"
)
BROKER_NATIVE_SPAWN_GUARD_SOURCE_SHA_ENV = (
    "PARSER_TESSERACT_NATIVE_SPAWN_GUARD_SOURCE_SHA256"
)
BROKER_NATIVE_RUNTIME_GATE_SOURCE_SHA_ENV = (
    "PARSER_TESSERACT_NATIVE_RUNTIME_GATE_SOURCE_SHA256"
)
BROKER_NATIVE_RUNTIME_GATE_LIBRARY_SHA_ENV = (
    "PARSER_TESSERACT_NATIVE_RUNTIME_GATE_LIBRARY_SHA256"
)
BROKER_NATIVE_RUNTIME_GATE_RECORD_SHA_ENV = (
    "PARSER_TESSERACT_NATIVE_RUNTIME_GATE_RECORD_SHA256"
)
BROKER_GUARD_PYTHON_SHA_ENV = "PARSER_TESSERACT_GUARD_PYTHON_SHA256"
BROKER_GUARD_PYTHON_PATH_CUSTODY_SHA_ENV = (
    "PARSER_TESSERACT_GUARD_PYTHON_PATH_CUSTODY_SHA256"
)
BROKER_GUARD_PYTHON_NATIVE_CLOSURE_SHA_ENV = (
    "PARSER_TESSERACT_GUARD_PYTHON_NATIVE_CLOSURE_SHA256"
)
BROKER_GUARD_PYTHON_MODULE_TREE_SHA_ENV = (
    "PARSER_TESSERACT_GUARD_PYTHON_MODULE_TREE_SHA256"
)
BROKER_GUARD_WRAPPER_SOURCE_SHA_ENV = (
    "PARSER_TESSERACT_GUARD_WRAPPER_SOURCE_SHA256"
)
BROKER_TESSDATA_ENV = "PARSER_TESSERACT_TESSDATA_ROOT"
BROKER_TESSDATA_SHA_ENV = "PARSER_TESSERACT_TESSDATA_SHA256"
BROKER_LANGUAGES_ENV = "PARSER_TESSERACT_LANGUAGES"
BROKER_REQUEST_ROOT_ENV = "PARSER_TESSERACT_REQUEST_ROOT"
BROKER_REQUEST_ROOT_FD_ENV = "PARSER_TESSERACT_REQUEST_ROOT_FD"
BROKER_ATTEMPT_DEADLINE_ENV = "PARSER_TESSERACT_ATTEMPT_DEADLINE_MONOTONIC_NS"
BROKER_EXTERNAL_BARRIERS_ENV = "PARSER_TESSERACT_EXTERNAL_BARRIERS"
MAX_INPUT_BYTES = MAX_RUN_INPUT_BYTES
MAX_REQUEST_ID_CHARS = 256
_ORIGINAL_POPEN = subprocess.Popen
_INSTALL_LOCK = threading.Lock()
_ACTIVE_CLIENT: TesseractBrokerClient | None = None
_WORKER_FORK_DENIAL_EVIDENCE: WorkerForkDenialEvidence | None = None


def _sha256(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise BrokerProtocolError(f"{name} must be a lowercase SHA-256")
    return value


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BrokerProtocolError(f"{name} must be positive")
    return value


def _environment_int(name: str) -> int:
    raw = os.environ.get(name)
    if raw is None:
        raise BrokerProtocolError("broker capability environment is incomplete")
    try:
        value = int(raw)
    except ValueError as exc:
        raise BrokerProtocolError(f"{name} is malformed") from exc
    return _positive_int(value, name)


def _environment_bool(name: str) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return False
    value = raw.strip().casefold()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise BrokerProtocolError(f"{name} is malformed")


@dataclass(frozen=True, slots=True)
class BrokerClientConfig:
    attempt_nonce_sha256: str
    scope_sha256: str
    broker_pid: int
    broker_start_abstime: int
    broker_pgid: int
    broker_sid: int
    executable: str
    executable_sha256: str
    staged_executable: str
    staged_executable_sha256: str
    native_closure_sha256: str
    native_spawn_guard_sha256: str
    native_spawn_guard_source_sha256: str
    native_runtime_gate_source_sha256: str
    native_runtime_gate_library_sha256: str
    native_runtime_gate_record_sha256: str
    guard_python_sha256: str
    guard_python_path_custody_sha256: str
    guard_python_native_closure_sha256: str
    guard_python_module_tree_sha256: str
    guard_wrapper_source_sha256: str
    tessdata_root: str
    tessdata_sha256: str
    languages: tuple[str, ...]
    request_root: str
    request_root_fd: int
    request_root_device: int
    request_root_inode: int
    attempt_deadline_monotonic_ns: int
    external_barriers: bool

    def __post_init__(self) -> None:
        for name in (
            "attempt_nonce_sha256",
            "scope_sha256",
            "executable_sha256",
            "staged_executable_sha256",
            "native_closure_sha256",
            "native_spawn_guard_sha256",
            "native_spawn_guard_source_sha256",
            "native_runtime_gate_source_sha256",
            "native_runtime_gate_library_sha256",
            "native_runtime_gate_record_sha256",
            "guard_python_sha256",
            "guard_python_path_custody_sha256",
            "guard_python_native_closure_sha256",
            "guard_python_module_tree_sha256",
            "guard_wrapper_source_sha256",
            "tessdata_sha256",
        ):
            _sha256(getattr(self, name), name)
        if self.executable_sha256 != self.staged_executable_sha256:
            raise BrokerProtocolError("logical/staged Tesseract bytes differ")
        for name in (
            "broker_pid",
            "broker_start_abstime",
            "broker_pgid",
            "broker_sid",
            "request_root_fd",
            "request_root_device",
            "request_root_inode",
            "attempt_deadline_monotonic_ns",
        ):
            _positive_int(getattr(self, name), name)
        if self.broker_pid != self.broker_pgid or self.broker_pid != self.broker_sid:
            raise BrokerProtocolError("broker is not a fresh group/session leader")
        if type(self.external_barriers) is not bool:
            raise BrokerProtocolError("external barrier flag must be Boolean")
        for name in ("executable", "staged_executable", "tessdata_root", "request_root"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not os.path.isabs(value)
                or os.path.realpath(value) != value
                or "\x00" in value
            ):
                raise BrokerProtocolError(f"{name} must be absolute and resolved")
        if not self.languages or tuple(sorted(set(self.languages))) != self.languages:
            raise BrokerProtocolError("broker language identity differs")
        opened = os.fstat(self.request_root_fd)
        observed = os.lstat(self.request_root)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) != 0o700
            or opened.st_uid != os.geteuid()
            or (opened.st_dev, opened.st_ino)
            != (self.request_root_device, self.request_root_inode)
            or (observed.st_dev, observed.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            raise BrokerProtocolError("request-root descriptor identity differs")
        if os.get_inheritable(self.request_root_fd):
            raise BrokerProtocolError("request-root descriptor must be close-on-exec")
        if self.attempt_deadline_monotonic_ns <= time.monotonic_ns():
            raise BrokerProtocolError("attempt deadline already expired")

    @classmethod
    def from_environment(cls) -> BrokerClientConfig:
        string_names = (
            BROKER_NONCE_SHA_ENV,
            BROKER_SCOPE_ENV,
            BROKER_EXECUTABLE_ENV,
            BROKER_EXECUTABLE_SHA_ENV,
            BROKER_STAGED_EXECUTABLE_ENV,
            BROKER_STAGED_EXECUTABLE_SHA_ENV,
            BROKER_NATIVE_CLOSURE_SHA_ENV,
            BROKER_NATIVE_SPAWN_GUARD_SHA_ENV,
            BROKER_NATIVE_SPAWN_GUARD_SOURCE_SHA_ENV,
            BROKER_NATIVE_RUNTIME_GATE_SOURCE_SHA_ENV,
            BROKER_NATIVE_RUNTIME_GATE_LIBRARY_SHA_ENV,
            BROKER_NATIVE_RUNTIME_GATE_RECORD_SHA_ENV,
            BROKER_GUARD_PYTHON_SHA_ENV,
            BROKER_GUARD_PYTHON_PATH_CUSTODY_SHA_ENV,
            BROKER_GUARD_PYTHON_NATIVE_CLOSURE_SHA_ENV,
            BROKER_GUARD_PYTHON_MODULE_TREE_SHA_ENV,
            BROKER_GUARD_WRAPPER_SOURCE_SHA_ENV,
            BROKER_TESSDATA_ENV,
            BROKER_TESSDATA_SHA_ENV,
            BROKER_LANGUAGES_ENV,
            BROKER_REQUEST_ROOT_ENV,
        )
        values = {name: os.environ.get(name) for name in string_names}
        if any(value is None or value == "" for value in values.values()):
            raise BrokerProtocolError("broker capability environment is incomplete")
        root_fd = _environment_int(BROKER_REQUEST_ROOT_FD_ENV)
        root_stat = os.fstat(root_fd)
        languages = tuple(str(values[BROKER_LANGUAGES_ENV]).split(","))
        return cls(
            attempt_nonce_sha256=str(values[BROKER_NONCE_SHA_ENV]),
            scope_sha256=str(values[BROKER_SCOPE_ENV]),
            broker_pid=_environment_int(BROKER_PID_ENV),
            broker_start_abstime=_environment_int(BROKER_START_ABSTIME_ENV),
            broker_pgid=_environment_int(BROKER_PGID_ENV),
            broker_sid=_environment_int(BROKER_SID_ENV),
            executable=str(values[BROKER_EXECUTABLE_ENV]),
            executable_sha256=str(values[BROKER_EXECUTABLE_SHA_ENV]),
            staged_executable=str(values[BROKER_STAGED_EXECUTABLE_ENV]),
            staged_executable_sha256=str(values[BROKER_STAGED_EXECUTABLE_SHA_ENV]),
            native_closure_sha256=str(values[BROKER_NATIVE_CLOSURE_SHA_ENV]),
            native_spawn_guard_sha256=str(
                values[BROKER_NATIVE_SPAWN_GUARD_SHA_ENV]
            ),
            native_spawn_guard_source_sha256=str(
                values[BROKER_NATIVE_SPAWN_GUARD_SOURCE_SHA_ENV]
            ),
            native_runtime_gate_source_sha256=str(
                values[BROKER_NATIVE_RUNTIME_GATE_SOURCE_SHA_ENV]
            ),
            native_runtime_gate_library_sha256=str(
                values[BROKER_NATIVE_RUNTIME_GATE_LIBRARY_SHA_ENV]
            ),
            native_runtime_gate_record_sha256=str(
                values[BROKER_NATIVE_RUNTIME_GATE_RECORD_SHA_ENV]
            ),
            guard_python_sha256=str(values[BROKER_GUARD_PYTHON_SHA_ENV]),
            guard_python_path_custody_sha256=str(
                values[BROKER_GUARD_PYTHON_PATH_CUSTODY_SHA_ENV]
            ),
            guard_python_native_closure_sha256=str(
                values[BROKER_GUARD_PYTHON_NATIVE_CLOSURE_SHA_ENV]
            ),
            guard_python_module_tree_sha256=str(
                values[BROKER_GUARD_PYTHON_MODULE_TREE_SHA_ENV]
            ),
            guard_wrapper_source_sha256=str(
                values[BROKER_GUARD_WRAPPER_SOURCE_SHA_ENV]
            ),
            tessdata_root=str(values[BROKER_TESSDATA_ENV]),
            tessdata_sha256=str(values[BROKER_TESSDATA_SHA_ENV]),
            languages=tuple(sorted(languages)),
            request_root=str(values[BROKER_REQUEST_ROOT_ENV]),
            request_root_fd=root_fd,
            request_root_device=root_stat.st_dev,
            request_root_inode=root_stat.st_ino,
            attempt_deadline_monotonic_ns=_environment_int(BROKER_ATTEMPT_DEADLINE_ENV),
            external_barriers=_environment_bool(BROKER_EXTERNAL_BARRIERS_ENV),
        )


@dataclass(frozen=True, slots=True)
class BrokerPhaseLease:
    phase: str
    request_id: str
    request_epoch: int
    request_sequence: int
    worker_python_thread_id: int
    worker_thread_id: int
    capability_sha256: str
    arm_capability_sha256: str
    arm_issued_at_monotonic_ns: int
    arm_consumed_at_monotonic_ns: int
    binding_sha256: str
    phase_deadline_monotonic_ns: int
    thread_transfer_required: bool


@dataclass(frozen=True, slots=True)
class BrokerRunResult:
    args: tuple[str, ...]
    returncode: int
    stdout: bytes
    stderr: bytes


def _timeout_duration_ns(timeout: float | None) -> int:
    if timeout is None:
        return 300 * 1_000_000_000
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise TypeError("timeout must be a number")
    if not math.isfinite(timeout) or timeout <= 0 or timeout > 900:
        raise ValueError("timeout must be between 0 and 900 seconds")
    return math.ceil(timeout * 1_000_000_000)


def _same_stat(first: os.stat_result, second: os.stat_result) -> bool:
    return (
        first.st_dev,
        first.st_ino,
        first.st_mode,
        first.st_uid,
        first.st_nlink,
        first.st_size,
        first.st_mtime_ns,
        first.st_ctime_ns,
    ) == (
        second.st_dev,
        second.st_ino,
        second.st_mode,
        second.st_uid,
        second.st_nlink,
        second.st_size,
        second.st_mtime_ns,
        second.st_ctime_ns,
    )


def _assert_request_root_empty(config: BrokerClientConfig) -> None:
    """Prove the held 0700 worker scratch has no cross-phase residue."""

    before = os.fstat(config.request_root_fd)
    if (
        (before.st_dev, before.st_ino)
        != (config.request_root_device, config.request_root_inode)
        or not stat.S_ISDIR(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o700
        or before.st_uid != os.geteuid()
    ):
        raise BrokerProtocolError("request-root identity changed")
    try:
        entries = os.listdir(config.request_root_fd)
    except OSError as exc:
        raise BrokerProtocolError("request-root enumeration failed") from exc
    after = os.fstat(config.request_root_fd)
    if entries or not _same_stat(before, after):
        raise BrokerProtocolError("request-root is not empty/quiescent")


def _read_custodied_input(
    path: str,
    config: BrokerClientConfig,
) -> tuple[bytearray, str]:
    if not os.path.isabs(path) or "\x00" in path:
        raise BrokerProtocolError("Tesseract input path is not absolute")
    normalized = os.path.normpath(path)
    if os.path.commonpath((config.request_root, normalized)) != config.request_root:
        raise BrokerProtocolError("Tesseract input escapes the request root")
    relative = os.path.relpath(normalized, config.request_root)
    components = Path(relative).parts
    if not components or any(value in {"", ".", ".."} for value in components):
        raise BrokerProtocolError("Tesseract input relative path differs")
    directory_fd = os.dup(config.request_root_fd)
    os.set_inheritable(directory_fd, False)
    try:
        for component in components[:-1]:
            next_fd = os.open(
                component,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=directory_fd,
            )
            child = os.fstat(next_fd)
            if (
                not stat.S_ISDIR(child.st_mode)
                or child.st_uid != os.geteuid()
                or stat.S_IMODE(child.st_mode) & 0o022
            ):
                os.close(next_fd)
                raise BrokerProtocolError("Tesseract input parent custody differs")
            os.close(directory_fd)
            directory_fd = next_fd
        descriptor = os.open(
            components[-1],
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            dir_fd=directory_fd,
        )
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_uid != os.geteuid()
                or opened.st_nlink != 1
                or opened.st_size <= 0
                or opened.st_size > MAX_INPUT_BYTES
            ):
                raise BrokerProtocolError("Tesseract input custody differs")
            retained = bytearray(opened.st_size)
            total = 0
            while chunk := os.read(
                descriptor,
                min(1024 * 1024, MAX_INPUT_BYTES + 1 - total),
            ):
                retained[total : total + len(chunk)] = chunk
                total += len(chunk)
                if total > MAX_INPUT_BYTES:
                    raise BrokerProtocolError("Tesseract input exceeds its bound")
            if total != opened.st_size or not _same_stat(opened, os.fstat(descriptor)):
                raise BrokerProtocolError("Tesseract input changed during read")
        finally:
            os.close(descriptor)
    finally:
        os.close(directory_fd)
    suffix = Path(components[-1]).suffix.casefold()
    if suffix not in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".pnm", ".pbm", ".pgm", ".ppm"}:
        raise BrokerProtocolError("Tesseract input suffix is not admitted")
    return retained, suffix


class TesseractBrokerClient:
    """One process-owned, strict-alternation broker capability."""

    def __init__(
        self,
        sock: socket.socket,
        config: BrokerClientConfig,
        *,
        lease_seed: bytes,
        fatal_exit: Callable[[int], Any] = os._exit,
    ) -> None:
        if not isinstance(lease_seed, bytes) or len(lease_seed) != 32:
            raise BrokerProtocolError("supervisor lease seed must be 256 bits")
        self.config = config
        self._channel = FramedChannel(sock)
        self._channel.set_absolute_deadline_ns(config.attempt_deadline_monotonic_ns)
        self._lease_seed = lease_seed
        self._fatal_exit = fatal_exit
        self._lock = threading.RLock()
        self._abort_lock = threading.Lock()
        self._run_active = threading.Event()
        self._abort_sent = False
        self._local = threading.local()
        self._owner_pid = os.getpid()
        self._epoch = 0
        self._request_sequence = 0
        self._active: BrokerPhaseLease | None = None
        self._begin_receipt: BrokerQuiescenceReceipt | None = None
        self._begin_released = False
        self._pending_receipt: BrokerRequestReceipt | None = None
        self._last_receipt: BrokerRequestReceipt | None = None
        self._previous_receipt_sha256 = "0" * 64
        self._child_sandbox_probe_representative_report_sha256 = "0" * 64
        self._child_sandbox_probe_report_ledger_row_sha256 = "0" * 64
        self._run_ack_ledger: list[dict[str, Any]] = []
        self._thread_transfer_ledger: list[BrokerThreadTransfer] = []
        self._origin_lease: BrokerPhaseLease | None = None
        self._issued_arm: tuple[str, str, str, int, int] | None = None
        self._active_binding: dict[str, Any] | None = None
        self._request_binding_evidence: BrokerRequestBindingEvidence | None = None
        self._closed = False
        self._poisoned = False
        self._post_release_baseline: BrokerPostReleaseBaseline | None = None
        self._hello()

    def _poison(self, exc: BaseException) -> None:
        self._poisoned = True
        with contextlib.suppress(BaseException):
            self._channel.close()
        self._fatal_exit(BROKER_CLIENT_FATAL_EXIT_CODE)
        raise BrokerProtocolError("broker capability became terminal") from exc

    def _exchange(
        self,
        send_kind: str,
        payload: Mapping[str, Any],
        *,
        body: bytes = b"",
        receive_kind: str,
    ) -> tuple[dict[str, Any], bytes]:
        try:
            self._channel.send(send_kind, payload, body)
            _, response, response_body = self._channel.receive(expected_kind=receive_kind)
            return response, response_body
        except BaseException as exc:
            self._poison(exc)

    def _hello(self) -> None:
        worker_pid = os.getpid()
        from app.services.tesseract_broker_native import raw_process_start_abstime

        payload, body = self._exchange(
            "hello",
            {
                "attempt_nonce_sha256": self.config.attempt_nonce_sha256,
                "scope_sha256": self.config.scope_sha256,
                "worker_pid": worker_pid,
                "worker_start_abstime": raw_process_start_abstime(worker_pid),
                "worker_ppid": os.getppid(),
                "worker_pgid": os.getpgid(0),
                "worker_sid": os.getsid(0),
            },
            receive_kind="hello_ack",
        )
        expected = {
            "attempt_nonce_sha256": self.config.attempt_nonce_sha256,
            "scope_sha256": self.config.scope_sha256,
            "broker_pid": self.config.broker_pid,
            "broker_start_abstime": self.config.broker_start_abstime,
            "broker_pgid": self.config.broker_pgid,
            "broker_sid": self.config.broker_sid,
        }
        if body or set(payload) != {*expected, "post_release_baseline"}:
            self._poison(BrokerProtocolError("broker hello identity differs"))
        try:
            baseline = broker_post_release_baseline_from_mapping(
                payload.pop("post_release_baseline")
            )
            if (
                payload != expected
                or baseline.broker.pid != self.config.broker_pid
                or baseline.broker.start_abstime
                != self.config.broker_start_abstime
                or baseline.broker.pgid != self.config.broker_pgid
                or baseline.broker.sid != self.config.broker_sid
            ):
                raise BrokerProtocolError("broker hello baseline differs")
        except BaseException as exc:
            self._poison(exc)
        self._post_release_baseline = baseline

    def post_release_baseline(self) -> BrokerPostReleaseBaseline:
        baseline = self._post_release_baseline
        if baseline is None or self._poisoned:
            raise BrokerProtocolError("broker post-release baseline is unavailable")
        return baseline

    def _require_owner(self) -> None:
        if self._closed or self._poisoned or os.getpid() != self._owner_pid:
            raise BrokerProtocolError("broker capability owner differs")

    @staticmethod
    def _phase_payload(lease: BrokerPhaseLease) -> dict[str, Any]:
        return {
            "request_id": lease.request_id,
            "request_epoch": lease.request_epoch,
            "request_sequence": lease.request_sequence,
            "worker_python_thread_id": lease.worker_python_thread_id,
            "worker_thread_id": lease.worker_thread_id,
            "capability_sha256": lease.capability_sha256,
            "arm_capability_sha256": lease.arm_capability_sha256,
            "binding_sha256": lease.binding_sha256,
        }

    def issue_arm_capability(
        self,
        request_id: str,
        binding: Mapping[str, Any],
        *,
        phase_deadline_monotonic_ns: int,
        arm_issued_at_monotonic_ns: int | None = None,
    ) -> str:
        """Mint one supervisor-seed-bound request arm; never persist it raw."""

        self._require_owner()
        binding_sha256 = canonical_sha256(dict(binding))
        deadline = _positive_int(
            phase_deadline_monotonic_ns, "phase deadline"
        )
        if (
            not isinstance(request_id, str)
            or not 0 < len(request_id) <= MAX_REQUEST_ID_CHARS
            or deadline <= time.monotonic_ns()
            or deadline > self.config.attempt_deadline_monotonic_ns
        ):
            raise BrokerProtocolError("request arm binding differs")
        with self._lock:
            if (
                self._issued_arm is not None
                or self._active is not None
                or self._pending_receipt is not None
            ):
                raise BrokerProtocolError("request arm overlap")
            observed_now = time.monotonic_ns()
            issued_at = (
                observed_now
                if arm_issued_at_monotonic_ns is None
                else _positive_int(
                    arm_issued_at_monotonic_ns,
                    "arm_issued_at_monotonic_ns",
                )
            )
            if issued_at > observed_now or issued_at >= deadline:
                raise BrokerProtocolError("request arm issuance time differs")
            raw = hmac.new(
                self._lease_seed,
                canonical_sha256(
                    {
                        "schema_id": "parser-broker-asgi-arm-v1",
                        "attempt_nonce_sha256": self.config.attempt_nonce_sha256,
                        "scope_sha256": self.config.scope_sha256,
                        "request_id": request_id,
                        "binding_sha256": binding_sha256,
                        "phase_deadline_monotonic_ns": deadline,
                        "issued_at_monotonic_ns": issued_at,
                    }
                ).encode("ascii"),
                hashlib.sha256,
            ).hexdigest()
            self._issued_arm = (
                raw,
                request_id,
                binding_sha256,
                deadline,
                issued_at,
            )
            return raw

    def issued_arm_snapshot(self) -> tuple[str, str, str, int, int]:
        """Return the one in-process ARM tuple before it is consumed."""

        with self._lock:
            if self._issued_arm is None:
                raise BrokerProtocolError("request arm is unavailable")
            return self._issued_arm

    def begin_phase(
        self,
        phase: str,
        request_id: str,
        binding: Mapping[str, Any] | None = None,
        *,
        phase_deadline_monotonic_ns: int,
        arm_capability: str | None = None,
        require_thread_transfer: bool = False,
    ) -> BrokerPhaseLease:
        self._require_owner()
        if phase not in {"startup", "request", "shutdown"}:
            raise BrokerProtocolError("invalid broker phase")
        if type(require_thread_transfer) is not bool or (
            require_thread_transfer and phase != "request"
        ):
            raise BrokerProtocolError("thread-transfer requirement differs")
        if not isinstance(request_id, str) or not 0 < len(request_id) <= MAX_REQUEST_ID_CHARS:
            raise BrokerProtocolError("invalid broker request id")
        deadline = _positive_int(phase_deadline_monotonic_ns, "phase deadline")
        if deadline > self.config.attempt_deadline_monotonic_ns or deadline <= time.monotonic_ns():
            raise BrokerProtocolError("phase deadline differs")
        thread_id = threading.get_native_id()
        python_thread_id = threading.get_ident()
        with self._lock:
            if self._active is not None or self._pending_receipt is not None:
                raise BrokerProtocolError("broker request overlap")
            _assert_request_root_empty(self.config)
            self._epoch += 1
            if phase == "request":
                self._request_sequence += 1
            request_sequence = max(1, self._request_sequence)
            binding_payload = dict(binding or {})
            binding_sha256 = canonical_sha256(binding_payload)
            if arm_capability is None:
                arm_issued_at = time.monotonic_ns()
                arm_capability = hmac.new(
                    self._lease_seed,
                    f"internal:{phase}:{request_id}:{self._epoch}".encode("utf-8"),
                    hashlib.sha256,
                ).hexdigest()
            elif (
                phase != "request"
                or self._issued_arm is None
                or self._issued_arm[:4]
                != (arm_capability, request_id, binding_sha256, deadline)
            ):
                raise BrokerProtocolError("request arm capability differs")
            else:
                arm_issued_at = self._issued_arm[4]
            if (
                not isinstance(arm_capability, str)
                or len(arm_capability) != 64
                or any(value not in "0123456789abcdef" for value in arm_capability)
            ):
                raise BrokerProtocolError("request arm capability is malformed")
            arm_capability_sha256 = hashlib.sha256(
                arm_capability.encode("ascii")
            ).hexdigest()
            capability = hmac.new(
                self._lease_seed,
                canonical_sha256(
                    {
                        "attempt_nonce_sha256": self.config.attempt_nonce_sha256,
                        "scope_sha256": self.config.scope_sha256,
                        "phase": phase,
                        "request_id": request_id,
                        "request_epoch": self._epoch,
                        "request_sequence": request_sequence,
                        "worker_thread_id": thread_id,
                        "binding_sha256": binding_sha256,
                    }
                ).encode("ascii"),
                hashlib.sha256,
            ).hexdigest()
            lease = BrokerPhaseLease(
                phase=phase,
                request_id=request_id,
                request_epoch=self._epoch,
                request_sequence=request_sequence,
                worker_python_thread_id=python_thread_id,
                worker_thread_id=thread_id,
                capability_sha256=hashlib.sha256(capability.encode("ascii")).hexdigest(),
                arm_capability_sha256=arm_capability_sha256,
                arm_issued_at_monotonic_ns=arm_issued_at,
                arm_consumed_at_monotonic_ns=1,
                binding_sha256=binding_sha256,
                phase_deadline_monotonic_ns=deadline,
                thread_transfer_required=require_thread_transfer,
            )
            try:
                payload, body = self._exchange(
                    "begin",
                    {
                        "attempt_nonce_sha256": self.config.attempt_nonce_sha256,
                        "scope_sha256": self.config.scope_sha256,
                        "phase": phase,
                        "request_id": request_id,
                        "request_epoch": self._epoch,
                        "request_sequence": request_sequence,
                        "worker_python_thread_id": python_thread_id,
                        "worker_thread_id": thread_id,
                        "capability": capability,
                        "arm_capability": arm_capability,
                        "arm_issued_at_monotonic_ns": arm_issued_at,
                        "binding": binding_payload,
                        "binding_sha256": binding_sha256,
                        "phase_deadline_monotonic_ns": deadline,
                        "thread_transfer_required": require_thread_transfer,
                    },
                    receive_kind="begin_ack",
                )
                if body or set(payload) != {
                    "quiescence",
                    "arm_consumed_at_monotonic_ns",
                }:
                    raise BrokerProtocolError("malformed broker begin acknowledgement")
                consumed_at = _positive_int(
                    payload["arm_consumed_at_monotonic_ns"],
                    "arm_consumed_at_monotonic_ns",
                )
                if not arm_issued_at <= consumed_at <= deadline:
                    raise BrokerProtocolError("broker arm consumption time differs")
                lease = replace(
                    lease,
                    arm_consumed_at_monotonic_ns=consumed_at,
                )
                begin = quiescence_from_mapping(payload["quiescence"])
                begin.assert_complete(self.config.broker_pid)
                if (
                    begin.request_id != request_id
                    or begin.request_epoch != self._epoch
                    or begin.request_sequence != request_sequence
                    or begin.phase != "begin"
                ):
                    raise BrokerProtocolError("broker begin binding differs")
            except BaseException as exc:
                if not self._poisoned:
                    self._poison(exc)
                raise
            self._active = lease
            self._begin_receipt = begin
            self._begin_released = False
            self._local.lease = lease
            self._run_ack_ledger = []
            self._thread_transfer_ledger = []
            self._origin_lease = None
            self._active_binding = binding_payload
            self._request_binding_evidence = None
            if self._issued_arm is not None:
                self._issued_arm = None
            if not self.config.external_barriers or phase != "request":
                self.release_begin(lease)
            return lease

    def bind_actual_request(
        self,
        lease: BrokerPhaseLease,
        actual_request: Mapping[str, Any],
    ) -> BrokerRequestBindingEvidence:
        """Bind validator-observed request identity before thread claim."""

        self._require_owner()
        actual = dict(actual_request)
        with self._lock:
            if (
                lease is not self._current_lease()
                or lease.phase != "request"
                or not lease.thread_transfer_required
                or self._request_binding_evidence is not None
                or self._thread_transfer_ledger
                or self._active_binding is None
                or actual != self._active_binding
                or canonical_sha256(actual) != lease.binding_sha256
            ):
                raise BrokerProtocolError("actual request differs from its arm")
            payload, body = self._exchange(
                "request_match",
                {
                    **self._phase_payload(lease),
                    "actual_request": actual,
                },
                receive_kind="request_match_ack",
            )
            if body or set(payload) != {"request_binding"}:
                self._poison(BrokerProtocolError("request match ACK differs"))
            try:
                evidence = request_binding_from_mapping(
                    payload["request_binding"]
                )
                if (
                    evidence.binding_record_sha256 != lease.binding_sha256
                    or {
                        key: getattr(evidence, key)
                        for key in actual
                    }
                    != actual
                ):
                    raise BrokerProtocolError("request match evidence differs")
            except BaseException as exc:
                self._poison(exc)
            self._request_binding_evidence = evidence
            return evidence

    def claim_phase_on_current_thread(
        self,
        origin: BrokerPhaseLease,
    ) -> BrokerPhaseLease:
        """Transfer one active request from ASGI ownership to its AnyIO thread."""

        self._require_owner()
        python_thread_id = threading.get_ident()
        native_thread_id = threading.get_native_id()
        with self._lock:
            if (
                origin is not self._active
                or origin.phase != "request"
                or self._origin_lease is not None
                or self._thread_transfer_ledger
                or self._request_binding_evidence is None
                or python_thread_id == origin.worker_python_thread_id
                or native_thread_id == origin.worker_thread_id
                or getattr(self._local, "lease", None) is not None
            ):
                raise BrokerProtocolError("broker thread claim state differs")
            payload, body = self._exchange(
                "thread_claim",
                {
                    **self._phase_payload(origin),
                    "to_python_thread_id": python_thread_id,
                    "to_native_thread_id": native_thread_id,
                },
                receive_kind="thread_claim_ack",
            )
            if body or set(payload) != {"transfer"}:
                self._poison(BrokerProtocolError("thread claim ACK differs"))
            try:
                transfer = thread_transfer_from_mapping(payload["transfer"])
                if (
                    transfer.kind != "claim"
                    or transfer.from_python_thread_id
                    != origin.worker_python_thread_id
                    or transfer.from_native_thread_id != origin.worker_thread_id
                    or transfer.to_python_thread_id != python_thread_id
                    or transfer.to_native_thread_id != native_thread_id
                    or transfer.arm_capability_sha256
                    != origin.arm_capability_sha256
                ):
                    raise BrokerProtocolError("thread claim record differs")
            except BaseException as exc:
                self._poison(exc)
            claimed = replace(
                origin,
                worker_python_thread_id=python_thread_id,
                worker_thread_id=native_thread_id,
            )
            self._origin_lease = origin
            self._active = claimed
            self._thread_transfer_ledger.append(transfer)
            self._local.lease = claimed
            return claimed

    def release_phase_claim(self, claimed: BrokerPhaseLease) -> BrokerPhaseLease:
        """Return ordinary END authority to the exact ASGI owner thread."""

        self._require_owner()
        with self._lock:
            origin = self._origin_lease
            if (
                claimed is not self._current_lease()
                or origin is None
                or self._active is not claimed
                or len(self._thread_transfer_ledger) != 1
            ):
                raise BrokerProtocolError("broker thread release state differs")
            payload, body = self._exchange(
                "thread_release",
                {
                    **self._phase_payload(claimed),
                    "to_python_thread_id": origin.worker_python_thread_id,
                    "to_native_thread_id": origin.worker_thread_id,
                },
                receive_kind="thread_release_ack",
            )
            if body or set(payload) != {"transfer"}:
                self._poison(BrokerProtocolError("thread release ACK differs"))
            try:
                transfer = thread_transfer_from_mapping(payload["transfer"])
                if (
                    transfer.kind != "release"
                    or transfer.from_python_thread_id
                    != claimed.worker_python_thread_id
                    or transfer.from_native_thread_id != claimed.worker_thread_id
                    or transfer.to_python_thread_id
                    != origin.worker_python_thread_id
                    or transfer.to_native_thread_id != origin.worker_thread_id
                    or transfer.previous_transfer_sha256
                    != self._thread_transfer_ledger[0].record_sha256
                ):
                    raise BrokerProtocolError("thread release record differs")
            except BaseException as exc:
                self._poison(exc)
            self._thread_transfer_ledger.append(transfer)
            self._active = origin
            self._origin_lease = None
            del self._local.lease
            return origin

    def _current_lease(self) -> BrokerPhaseLease:
        lease = getattr(self._local, "lease", None)
        if (
            type(lease) is not BrokerPhaseLease
            or lease is not self._active
            or lease.worker_python_thread_id != threading.get_ident()
            or lease.worker_thread_id != threading.get_native_id()
        ):
            raise BrokerProtocolError("Tesseract call lacks its thread-bound lease")
        return lease

    def begin_barrier(self) -> BrokerBarrierSnapshot | None:
        with self._lock:
            lease = self._active
            begin = self._begin_receipt
            if lease is None or begin is None or self._begin_released:
                return None
            return BrokerBarrierSnapshot(
                kind="BEGIN",
                request_id=lease.request_id,
                request_epoch=lease.request_epoch,
                request_sequence=lease.request_sequence,
                broker_identity=begin.broker_identity,
                quiescence=begin,
                client_protocol_pending_bytes=self._pending_channel_bytes(),
                transcript_next_sequence=self._channel.next_sequence,
                transcript_head_sha256=self._channel.previous_sha256,
            )

    def _pending_channel_bytes(self) -> int:
        pending = array.array("i", [0])
        fcntl.ioctl(self._channel.fileno, termios.FIONREAD, pending, True)
        value = int(pending[0])
        if value != 0:
            raise BrokerProtocolError("broker client channel has pending bytes")
        return value

    def release_begin(self, lease: BrokerPhaseLease | None = None) -> None:
        with self._lock:
            active = self._active
            if active is None or self._begin_released or (lease is not None and lease is not active):
                raise BrokerProtocolError("broker BEGIN release differs")
            payload, body = self._exchange(
                "begin_release",
                self._phase_payload(active),
                receive_kind="begin_release_ack",
            )
            if body or payload != {
                "request_id": active.request_id,
                "request_epoch": active.request_epoch,
            }:
                self._poison(BrokerProtocolError("BEGIN release acknowledgement differs"))
            self._begin_released = True

    def _normalize_command(
        self,
        args: Sequence[str | os.PathLike[str]],
        input_bytes: bytes | None,
    ) -> tuple[dict[str, Any], bytes | bytearray, tuple[str, ...]]:
        if isinstance(args, (str, bytes, os.PathLike)):
            raise BrokerProtocolError("Tesseract argv must be a sequence")
        try:
            argv = tuple(os.fspath(value) for value in args)
        except TypeError as exc:
            raise BrokerProtocolError("Tesseract argv is malformed") from exc
        if not argv or any(type(value) is not str or not value or "\x00" in value for value in argv):
            raise BrokerProtocolError("Tesseract argv is malformed")
        if argv[0] != self.config.executable:
            raise PermissionError(errno.EPERM, "worker process creation is denied")
        if argv[1:] == ("--version",):
            if input_bytes not in {None, b""}:
                raise BrokerProtocolError("version command rejects input")
            return {
                "operation": "version", "language": None, "tessdata": None,
                "psm": None, "input_suffix": "", "input_bytes": 0,
                "input_sha256": hashlib.sha256(b"").hexdigest(),
                "input_transport": "none",
                "logical_argv_sha256": canonical_tesseract_logical_argv_sha256(
                    source_executable=self.config.executable,
                    operation="version", language=None, tessdata=None,
                    psm=None, input_transport="none", input_suffix="",
                    input_sha256=hashlib.sha256(b"").hexdigest(), input_bytes=0,
                ),
            }, b"", argv
        if argv[1:] == ("--list-langs",):
            if input_bytes not in {None, b""}:
                raise BrokerProtocolError("list-langs command rejects input")
            return {
                "operation": "list_languages", "language": None, "tessdata": None,
                "psm": None, "input_suffix": "", "input_bytes": 0,
                "input_sha256": hashlib.sha256(b"").hexdigest(),
                "input_transport": "none",
                "logical_argv_sha256": canonical_tesseract_logical_argv_sha256(
                    source_executable=self.config.executable,
                    operation="list_languages", language=None, tessdata=None,
                    psm=None, input_transport="none", input_suffix="",
                    input_sha256=hashlib.sha256(b"").hexdigest(), input_bytes=0,
                ),
            }, b"", argv
        language: str | None = None
        tessdata: str | None = None
        psm: int | None = None
        positionals: list[str] = []
        index = 1
        while index < len(argv):
            token = argv[index]
            if token in {"-l", "--tessdata-dir", "--psm"}:
                if index + 1 >= len(argv):
                    raise BrokerProtocolError("Tesseract option lacks a value")
                value = argv[index + 1]
                if token == "-l":
                    if language is not None:
                        raise BrokerProtocolError("duplicate Tesseract language")
                    language = value
                elif token == "--tessdata-dir":
                    if tessdata is not None or value != self.config.tessdata_root:
                        raise BrokerProtocolError("Tesseract tessdata differs")
                    tessdata = value
                else:
                    if psm is not None:
                        raise BrokerProtocolError("duplicate Tesseract psm")
                    try:
                        psm = int(value)
                    except ValueError as exc:
                        raise BrokerProtocolError("Tesseract psm is malformed") from exc
                    if not 0 <= psm <= 13 or str(psm) != value:
                        raise BrokerProtocolError("Tesseract psm differs")
                index += 2
                continue
            if token.startswith("-"):
                raise BrokerProtocolError("Tesseract option is not allowlisted")
            positionals.append(token)
            index += 1
        if len(positionals) == 3 and positionals[-2:] == ["stdout", "tsv"]:
            operation = "ocr_tsv"
            input_token = positionals[0]
        elif len(positionals) == 2 and positionals[-1] == "stdout":
            operation = "osd" if psm == 0 else "ocr_text"
            input_token = positionals[0]
        else:
            raise BrokerProtocolError("Tesseract positional grammar differs")
        if language is not None and any(
            value not in self.config.languages for value in language.split("+")
        ):
            raise BrokerProtocolError("Tesseract language is not frozen")
        if input_token == "stdin":
            body = input_bytes or b""
            suffix = ".bin"
            input_transport = "stdin"
        else:
            if input_bytes not in {None, b""}:
                raise BrokerProtocolError("file-backed Tesseract rejects stdin input")
            body, suffix = _read_custodied_input(input_token, self.config)
            input_transport = "custodied-request-file"
        if not body or len(body) > MAX_INPUT_BYTES:
            raise BrokerProtocolError("Tesseract input body differs")
        input_sha256 = hashlib.sha256(body).hexdigest()
        logical_sha = canonical_tesseract_logical_argv_sha256(
            source_executable=self.config.executable,
            operation=operation,
            language=language,
            tessdata=tessdata,
            psm=psm,
            input_transport=input_transport,
            input_suffix=suffix,
            input_sha256=input_sha256,
            input_bytes=len(body),
        )
        return {
            "operation": operation,
            "language": language,
            "tessdata": tessdata,
            "psm": psm,
            "input_suffix": suffix,
            "input_bytes": len(body),
            "input_sha256": input_sha256,
            "input_transport": input_transport,
            "logical_argv_sha256": logical_sha,
        }, body, argv

    def run(
        self,
        args: Sequence[str | os.PathLike[str]],
        *,
        input_bytes: bytes | None,
        timeout: float | None,
        stderr_mode: str = "separate",
        stdout_disposition: str = "captured",
    ) -> BrokerRunResult:
        lease = self._current_lease()
        if not self._begin_released:
            raise BrokerProtocolError("broker request is still at BEGIN barrier")
        command, body, argv = self._normalize_command(args, input_bytes)
        if stderr_mode not in {"separate", "merge", "discard"}:
            raise BrokerProtocolError("broker stderr mode differs")
        if stdout_disposition not in {"captured", "discarded"}:
            raise BrokerProtocolError("broker stdout disposition differs")
        command["stderr_mode"] = stderr_mode
        command["stdout_disposition"] = stdout_disposition
        command["stderr_disposition"] = (
            "discarded" if stderr_mode == "discard" else "captured"
        )
        deadline = min(
            lease.phase_deadline_monotonic_ns,
            time.monotonic_ns() + _timeout_duration_ns(timeout),
        )
        input_manifest, input_commitments = build_run_input_transport(
            request_id=lease.request_id,
            request_epoch=lease.request_epoch,
            request_sequence=lease.request_sequence,
            body=body,
        )
        self._run_active.set()
        with self._lock:
            try:
                self._channel.set_absolute_deadline_ns(deadline)
                self._channel.send(
                    "run",
                    {
                        **self._phase_payload(lease),
                        "absolute_deadline_monotonic_ns": deadline,
                        "command": command,
                        "input_manifest": asdict(input_manifest),
                    },
                )
                send_run_blob_chunks(
                    self._channel,
                    input_manifest,
                    body,
                    input_commitments,
                )
                del input_commitments
                del input_manifest
                del body
                input_bytes = None
                _, payload, response_body = self._channel.receive(
                    expected_kind="run_ack"
                )
                if response_body:
                    raise BrokerProtocolError("broker RUN ACK body is forbidden")
                if type(payload) is not dict or set(payload) != {
                    "request_id",
                    "request_epoch",
                    "request_sequence",
                    "outcome",
                    "returncode",
                    "birth_record_sha256",
                    "tombstone_record_sha256",
                    "output_manifest",
                }:
                    raise BrokerProtocolError(
                        "broker run response fields differ"
                    )
                output_manifest = run_output_manifest_from_mapping(
                    payload["output_manifest"]
                )
                output_blob = receive_run_blob_chunks(
                    self._channel, output_manifest
                )
                if time.monotonic_ns() >= deadline:
                    raise TimeoutError(
                        "broker RUN output crossed its absolute deadline"
                    )
                self._channel.set_absolute_deadline_ns(
                    lease.phase_deadline_monotonic_ns
                )
            except BaseException as exc:
                self._poison(exc)
            finally:
                self._run_active.clear()
        required = {
            "request_id", "request_epoch", "request_sequence", "outcome", "returncode",
            "birth_record_sha256", "tombstone_record_sha256", "output_manifest",
        }
        if set(payload) != required or any(
            payload[name] != getattr(lease, name)
            for name in ("request_id", "request_epoch", "request_sequence")
        ):
            self._poison(BrokerProtocolError("broker run response binding differs"))
        returncode = payload["returncode"]
        if (
            isinstance(returncode, bool)
            or not isinstance(returncode, int)
            or type(output_manifest) is not BrokerRunOutputManifest
            or output_manifest.request_id != lease.request_id
            or output_manifest.request_epoch != lease.request_epoch
            or output_manifest.request_sequence != lease.request_sequence
            or output_manifest.outcome != payload["outcome"]
            or output_manifest.returncode != returncode
            or output_manifest.stdout_disposition
            != command["stdout_disposition"]
            or output_manifest.stderr_disposition
            != command["stderr_disposition"]
            or output_manifest.output_blob_bytes != len(output_blob)
        ):
            self._poison(BrokerProtocolError("broker run result fields differ"))
        try:
            for name in ("birth_record_sha256", "tombstone_record_sha256"):
                _sha256(payload[name], name)
            output_view = memoryview(output_blob)
            stdout = bytes(output_view[: output_manifest.stdout_bytes])
            stderr = bytes(output_view[output_manifest.stdout_bytes :])
            del output_view
            del output_blob
            if payload["outcome"] not in {"completed", "timeout", "overflow"}:
                raise BrokerProtocolError("broker run outcome differs")
            if (
                hashlib.sha256(stdout).hexdigest()
                != output_manifest.stdout_sha256
                or hashlib.sha256(stderr).hexdigest()
                != output_manifest.stderr_sha256
            ):
                raise BrokerProtocolError("broker RUN output stream differs")
            self._run_ack_ledger.append(
                {
                    **{
                        key: item
                        for key, item in payload.items()
                        if key != "output_manifest"
                    },
                    "stdout_bytes": output_manifest.stdout_bytes,
                    "stderr_bytes": output_manifest.stderr_bytes,
                    "stdout_sha256": output_manifest.stdout_sha256,
                    "stdout_disposition": (
                        output_manifest.stdout_disposition
                    ),
                    "stderr_sha256": output_manifest.stderr_sha256,
                    "stderr_disposition": (
                        output_manifest.stderr_disposition
                    ),
                    "output_manifest_sha256": output_manifest.record_sha256,
                }
            )
        except BaseException as exc:
            self._poison(exc)
        if payload["outcome"] == "timeout":
            error = subprocess.TimeoutExpired(
                argv, timeout, output=stdout, stderr=stderr
            )
            error.broker_returncode = returncode  # type: ignore[attr-defined]
            raise error
        if payload["outcome"] == "overflow":
            error = subprocess.SubprocessError(
                "Tesseract output exceeded its custody bound"
            )
            error.broker_returncode = returncode  # type: ignore[attr-defined]
            raise error
        return BrokerRunResult(argv, returncode, stdout, stderr)

    def _terminal_receipt(
        self,
        kind: str,
        lease: BrokerPhaseLease,
        *,
        failure_reason_sha256: str,
    ) -> BrokerRequestReceipt:
        payload, body = self._exchange(
            kind,
            {
                **self._phase_payload(lease),
                "failure_reason_sha256": failure_reason_sha256,
            },
            receive_kind=f"{kind}_ack",
        )
        if body or set(payload) != {"receipt_manifest"}:
            self._poison(BrokerProtocolError("malformed broker terminal acknowledgement"))
        try:
            manifest = request_receipt_manifest_from_mapping(
                payload["receipt_manifest"]
            )
            receipt = receive_request_receipt_chunks(
                self._channel,
                manifest,
            )
            receipt.begin.assert_complete(self.config.broker_pid)
            receipt.end.assert_complete(self.config.broker_pid)
            known_sandbox_report = (
                self._child_sandbox_probe_representative_report_sha256
            )
            known_sandbox_row = (
                self._child_sandbox_probe_report_ledger_row_sha256
            )
            incoming_sandbox_report = (
                receipt.child_sandbox_probe_representative_report_sha256
            )
            incoming_sandbox_row = (
                receipt.child_sandbox_probe_report_ledger_row_sha256
            )
            first_sandbox_receipt = (
                known_sandbox_report == "0" * 64
                and incoming_sandbox_report != "0" * 64
            )
            if (
                receipt.attempt_nonce_sha256 != self.config.attempt_nonce_sha256
                or receipt.scope_sha256 != self.config.scope_sha256
                or receipt.previous_receipt_sha256 != self._previous_receipt_sha256
                or receipt.request_id != lease.request_id
                or receipt.request_epoch != lease.request_epoch
                or receipt.request_sequence != lease.request_sequence
                or receipt.worker_thread_id != lease.worker_thread_id
                or receipt.arm_capability_sha256
                != lease.arm_capability_sha256
                or receipt.arm_issued_at_monotonic_ns
                != lease.arm_issued_at_monotonic_ns
                or receipt.arm_consumed_at_monotonic_ns
                != lease.arm_consumed_at_monotonic_ns
                or receipt.thread_transfer_required
                != lease.thread_transfer_required
                or receipt.request_binding != self._request_binding_evidence
                or receipt.thread_claim_count
                != (1 if self._thread_transfer_ledger else 0)
                or receipt.logical_phase != lease.phase
                or receipt.terminal_kind != kind
                or receipt.phase_deadline_monotonic_ns
                != lease.phase_deadline_monotonic_ns
                or receipt.binding_sha256 != lease.binding_sha256
                or receipt.begin is not None
                and receipt.begin != self._begin_receipt
                or receipt.thread_transfers
                != tuple(self._thread_transfer_ledger)
                or len(receipt.births) != len(self._run_ack_ledger)
                or len(receipt.tombstones) != len(self._run_ack_ledger)
                or (known_sandbox_report == "0" * 64)
                != (known_sandbox_row == "0" * 64)
                or (incoming_sandbox_report == "0" * 64)
                != (incoming_sandbox_row == "0" * 64)
                or (
                    known_sandbox_report != "0" * 64
                    and (
                        incoming_sandbox_report != known_sandbox_report
                        or incoming_sandbox_row != known_sandbox_row
                    )
                )
                or (
                    first_sandbox_receipt
                    and not any(
                        birth.child_sandbox_probe_mode
                        == "representative-full-matrix"
                        for birth in receipt.births
                    )
                )
            ):
                raise BrokerProtocolError("broker receipt binding differs")
            for ack, birth, tombstone in zip(
                self._run_ack_ledger,
                receipt.births,
                receipt.tombstones,
                strict=True,
            ):
                if (
                    ack["birth_record_sha256"] != birth.record_sha256
                    or ack["tombstone_record_sha256"] != tombstone.record_sha256
                    or ack["stdout_bytes"] != tombstone.stdout_retained_bytes
                    or ack["stderr_bytes"] != tombstone.stderr_retained_bytes
                    or ack["stdout_disposition"]
                    != tombstone.stdout_disposition
                    or ack["stderr_disposition"]
                    != tombstone.stderr_disposition
                    or (
                        not tombstone.overflowed
                        and tombstone.stdout_disposition == "captured"
                        and ack["stdout_sha256"] != tombstone.stdout_sha256
                    )
                    or (
                        not tombstone.overflowed
                        and tombstone.stderr_disposition == "captured"
                        and ack["stderr_sha256"] != tombstone.stderr_sha256
                    )
                    or (
                        tombstone.stdout_disposition == "discarded"
                        and ack["stdout_sha256"]
                        != hashlib.sha256(b"").hexdigest()
                    )
                    or (
                        tombstone.stderr_disposition == "discarded"
                        and ack["stderr_sha256"]
                        != hashlib.sha256(b"").hexdigest()
                    )
                ):
                    raise BrokerProtocolError("broker run/receipt ledger differs")
        except BaseException as exc:
            if not self._poisoned:
                self._poison(exc)
            raise
        self._active = None
        self._begin_receipt = None
        self._begin_released = False
        self._thread_transfer_ledger = []
        self._origin_lease = None
        self._active_binding = None
        self._request_binding_evidence = None
        self._pending_receipt = receipt
        self._last_receipt = receipt
        if first_sandbox_receipt:
            self._child_sandbox_probe_representative_report_sha256 = (
                incoming_sandbox_report
            )
            self._child_sandbox_probe_report_ledger_row_sha256 = (
                incoming_sandbox_row
            )
        if getattr(self._local, "lease", None) is lease:
            del self._local.lease
        if not self.config.external_barriers or lease.phase != "request":
            self.release_receipt(receipt)
        return receipt

    def end_phase(self, lease: BrokerPhaseLease) -> BrokerRequestReceipt:
        if lease is not self._current_lease() or not self._begin_released:
            raise BrokerProtocolError("broker end lease differs")
        with self._lock:
            _assert_request_root_empty(self.config)
            return self._terminal_receipt(
                "end",
                lease,
                failure_reason_sha256=hashlib.sha256(b"").hexdigest(),
            )

    def abort_phase(
        self,
        lease: BrokerPhaseLease,
        failure: BaseException | None = None,
    ) -> BrokerRequestReceipt:
        if lease is not self._current_lease():
            raise BrokerProtocolError("broker abort lease differs")
        with self._lock:
            reason = type(failure).__name__ if failure is not None else "forced_abort"
            return self._terminal_receipt(
                "abort",
                lease,
                failure_reason_sha256=hashlib.sha256(reason.encode("utf-8")).hexdigest(),
            )

    def force_abort_active(self) -> BrokerRequestReceipt | None:
        """Process-owner shutdown authority; safe from a different thread."""

        self._require_owner()
        if self._run_active.is_set():
            with self._abort_lock:
                if not self._abort_sent:
                    self._abort_sent = True
                    self._channel.abort_io()
            return None
        with self._lock:
            lease = self._active
            if lease is None:
                return None
            return self._terminal_receipt(
                "abort",
                lease,
                failure_reason_sha256=hashlib.sha256(b"forced_abort").hexdigest(),
            )

    def release_receipt(self, receipt: BrokerRequestReceipt | None = None) -> BrokerRequestReceipt:
        with self._lock:
            pending = self._pending_receipt
            if pending is None or (receipt is not None and receipt is not pending):
                raise BrokerProtocolError("broker release receipt differs")
            payload, body = self._exchange(
                "release",
                {
                    "request_id": pending.request_id,
                    "request_epoch": pending.request_epoch,
                    "receipt_sha256": pending.receipt_sha256,
                },
                receive_kind="release_ack",
            )
            if body or payload != {
                "request_id": pending.request_id,
                "request_epoch": pending.request_epoch,
            }:
                self._poison(BrokerProtocolError("broker release acknowledgement differs"))
            self._pending_receipt = None
            self._previous_receipt_sha256 = pending.receipt_sha256
            return pending

    def barrier_snapshot(self) -> BrokerBarrierSnapshot | None:
        begin = self.begin_barrier()
        if begin is not None:
            return begin
        with self._lock:
            receipt = self._pending_receipt
            if receipt is None:
                return None
            return BrokerBarrierSnapshot(
                kind="END",
                request_id=receipt.request_id,
                request_epoch=receipt.request_epoch,
                request_sequence=receipt.request_sequence,
                broker_identity=receipt.end.broker_identity,
                quiescence=receipt.end,
                receipt_sha256=receipt.receipt_sha256,
                client_protocol_pending_bytes=self._pending_channel_bytes(),
                transcript_next_sequence=self._channel.next_sequence,
                transcript_head_sha256=self._channel.previous_sha256,
            )

    def pending_receipt(self) -> BrokerRequestReceipt | None:
        with self._lock:
            return self._pending_receipt

    def last_receipt(self) -> BrokerRequestReceipt | None:
        with self._lock:
            return self._last_receipt

    @contextlib.contextmanager
    def phase(
        self,
        phase: str,
        request_id: str,
        binding: Mapping[str, Any] | None = None,
        *,
        phase_deadline_monotonic_ns: int,
    ) -> Iterator[BrokerPhaseLease]:
        lease = self.begin_phase(
            phase,
            request_id,
            binding,
            phase_deadline_monotonic_ns=phase_deadline_monotonic_ns,
        )
        try:
            yield lease
        except BaseException as exc:
            self.abort_phase(lease, exc)
            raise
        else:
            self.end_phase(lease)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self._active is not None:
                self.force_abort_active()
            if self._pending_receipt is not None:
                self.release_receipt(self._pending_receipt)
            _assert_request_root_empty(self.config)
            payload, body = self._exchange(
                "shutdown",
                {"attempt_nonce_sha256": self.config.attempt_nonce_sha256},
                receive_kind="shutdown_ack",
            )
            if body or set(payload) != {"ledger", "immutable_inputs"}:
                self._poison(BrokerProtocolError("broker shutdown acknowledgement differs"))
            try:
                immutable = immutable_input_observation_from_mapping(
                    payload["immutable_inputs"]
                )
            except BaseException as exc:
                self._poison(exc)
            if (
                immutable["native_closure_sha256"]
                != self.config.native_closure_sha256
                or immutable["source_executable_sha256"]
                != self.config.executable_sha256
                or immutable["staged_executable_sha256"]
                != self.config.staged_executable_sha256
                or immutable["native_spawn_guard_sha256"]
                != self.config.native_spawn_guard_sha256
                or immutable["native_spawn_guard_source_sha256"]
                != self.config.native_spawn_guard_source_sha256
                or immutable["native_runtime_gate_source_sha256"]
                != self.config.native_runtime_gate_source_sha256
                or immutable["native_runtime_gate_library_sha256"]
                != self.config.native_runtime_gate_library_sha256
                or immutable["native_runtime_gate_record_sha256"]
                != self.config.native_runtime_gate_record_sha256
                or immutable["guard_python_sha256"]
                != self.config.guard_python_sha256
                or immutable["guard_python_path_custody_sha256"]
                != self.config.guard_python_path_custody_sha256
                or immutable["guard_python_native_closure_sha256"]
                != self.config.guard_python_native_closure_sha256
                or immutable["guard_python_module_tree_sha256"]
                != self.config.guard_python_module_tree_sha256
                or immutable["guard_wrapper_source_sha256"]
                != self.config.guard_wrapper_source_sha256
                or immutable["tessdata_sha256"]
                != self.config.tessdata_sha256
            ):
                self._poison(
                    BrokerProtocolError(
                        "broker shutdown immutable-input identity differs"
                    )
                )
            self._closed = True
            self._channel.close()


class BrokerPopen:
    """Exact observed ``Popen`` subset; unsupported process options fail closed."""

    def __init__(
        self,
        args: Sequence[str | os.PathLike[str]],
        bufsize: int = -1,
        executable: str | None = None,
        stdin: Any = None,
        stdout: Any = None,
        stderr: Any = None,
        preexec_fn: Any = None,
        close_fds: bool = True,
        shell: bool = False,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        universal_newlines: bool | None = None,
        startupinfo: Any = None,
        creationflags: int = 0,
        restore_signals: bool = True,
        start_new_session: bool = False,
        pass_fds: tuple[int, ...] = (),
        *,
        user: Any = None,
        group: Any = None,
        extra_groups: Any = None,
        encoding: str | None = None,
        errors: str | None = None,
        text: bool | None = None,
        umask: int = -1,
        pipesize: int = -1,
        process_group: int | None = None,
    ) -> None:
        if (
            bufsize != -1
            or executable is not None
            or preexec_fn is not None
            or close_fds is not True
            or shell is not False
            or cwd is not None
            or env is not None
            or startupinfo is not None
            or creationflags != 0
            or restore_signals is not True
            or start_new_session is not False
            or pass_fds
            or user is not None
            or group is not None
            or extra_groups is not None
            or umask != -1
            or pipesize != -1
            or process_group not in {None, -1}
        ):
            raise PermissionError(errno.EPERM, "unfrozen process options are denied")
        if stdin not in {None, subprocess.PIPE, subprocess.DEVNULL}:
            raise PermissionError(errno.EPERM, "unfrozen stdin transport is denied")
        if stdout not in {subprocess.PIPE, subprocess.DEVNULL} and not hasattr(stdout, "write"):
            raise PermissionError(errno.EPERM, "unfrozen stdout transport is denied")
        if stderr not in {subprocess.PIPE, subprocess.DEVNULL, subprocess.STDOUT} and not hasattr(stderr, "write"):
            raise PermissionError(errno.EPERM, "unfrozen stderr transport is denied")
        if text is not None and universal_newlines is not None and text != universal_newlines:
            raise subprocess.SubprocessError("Cannot disambiguate text and universal_newlines")
        self.args = args
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self.encoding = encoding or ("UTF-8" if text or universal_newlines else None)
        self.errors = errors
        self.text_mode = bool(text or universal_newlines or encoding or errors)
        self.returncode: int | None = None
        self.pid = None
        self._result: BrokerRunResult | None = None
        self._timeout: float | None = None
        self._state = "NEW"
        self._terminal_error: BaseException | None = None
        self._kill_requested = False

    @staticmethod
    def _write_redirect(target: Any, value: bytes) -> None:
        if target in {subprocess.PIPE, subprocess.DEVNULL, subprocess.STDOUT}:
            return
        try:
            target.write(value)
        except TypeError:
            target.write(value.decode("utf-8", errors="replace"))

    def _execute(self, input_value: bytes | str | None, timeout: float | None) -> BrokerRunResult:
        if self._state == "TERMINAL_SUCCESS" and self._result is not None:
            if input_value is not None:
                raise ValueError("Cannot send input after starting communication")
            return self._result
        if self._state == "TERMINAL_ERROR" and self._terminal_error is not None:
            raise self._terminal_error
        if self._state != "NEW":
            raise subprocess.SubprocessError("broker Popen state differs")
        if isinstance(input_value, str):
            if not self.text_mode:
                raise TypeError("a bytes-like object is required")
            input_bytes = input_value.encode(self.encoding or "utf-8", self.errors or "strict")
        elif input_value is None or isinstance(input_value, bytes):
            input_bytes = input_value
        else:
            raise TypeError("stdin input must be bytes or text")
        self._timeout = timeout
        self._state = "RUNNING"
        try:
            result = require_tesseract_broker_client().run(
                self.args,
                input_bytes=input_bytes,
                timeout=timeout,
                stderr_mode=(
                    "merge"
                    if self.stderr is subprocess.STDOUT
                    else "discard"
                    if self.stderr is subprocess.DEVNULL
                    else "separate"
                ),
                stdout_disposition=(
                    "discarded"
                    if self.stdout is subprocess.DEVNULL
                    else "captured"
                ),
            )
        except BaseException as exc:
            self._terminal_error = exc
            self.returncode = int(getattr(exc, "broker_returncode", -signal.SIGKILL))
            self._state = "TERMINAL_ERROR"
            raise
        self._result = result
        self.returncode = result.returncode
        self._state = "TERMINAL_SUCCESS"
        self._write_redirect(self.stdout, result.stdout)
        if self.stderr is not subprocess.STDOUT:
            self._write_redirect(self.stderr, result.stderr)
        return result

    def communicate(
        self,
        input: bytes | str | None = None,
        timeout: float | None = None,
    ) -> tuple[bytes | str | None, bytes | str | None]:
        result = self._execute(input, timeout)
        stdout: bytes | str | None = result.stdout if self.stdout is subprocess.PIPE else None
        stderr: bytes | str | None = result.stderr if self.stderr is subprocess.PIPE else None
        if self.text_mode:
            if isinstance(stdout, bytes):
                stdout = stdout.decode(self.encoding or "utf-8", self.errors or "strict")
            if isinstance(stderr, bytes):
                stderr = stderr.decode(self.encoding or "utf-8", self.errors or "strict")
        return stdout, stderr

    def wait(self, timeout: float | None = None) -> int:
        if self._state == "TERMINAL_ERROR" and self.returncode is not None:
            return self.returncode
        return self._execute(None, timeout).returncode

    def poll(self) -> int | None:
        return self.returncode

    def kill(self) -> None:
        if self._state == "NEW":
            raise subprocess.SubprocessError("broker process has not entered a waitable job")
        if self._state == "RUNNING":
            if not self._kill_requested:
                self._kill_requested = True
                require_tesseract_broker_client().force_abort_active()
            return None
        # Terminal RUN RPCs return only after the broker has exact-wait4'd the
        # child.  There is no local or remote child left to signal here.
        return None

    terminate = kill

    def send_signal(self, signal_number: int) -> None:
        if signal_number not in {signal.SIGTERM, signal.SIGKILL}:
            raise ValueError("unsupported broker child signal")
        self.kill()

    def __enter__(self) -> BrokerPopen:
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        if self._state == "NEW":
            self._execute(None, None)


def install_tesseract_broker_client_from_fd(
    fd: int | None = None,
    config: BrokerClientConfig | None = None,
    *,
    lease_seed: bytes,
    fatal_exit: Callable[[int], Any] = os._exit,
) -> TesseractBrokerClient:
    global _ACTIVE_CLIENT
    with _INSTALL_LOCK:
        if _ACTIVE_CLIENT is not None:
            raise BrokerProtocolError("broker client installation is not repeatable")
        if fd is None:
            fd = _environment_int(BROKER_FD_ENV)
        if fd < 3:
            raise BrokerProtocolError("broker capability fd is unsafe")
        os.set_inheritable(fd, False)
        sock = socket.socket(fileno=fd)
        client = TesseractBrokerClient(
            sock,
            config or BrokerClientConfig.from_environment(),
            lease_seed=lease_seed,
            fatal_exit=fatal_exit,
        )
        subprocess.Popen = BrokerPopen  # type: ignore[assignment]
        _ACTIVE_CLIENT = client
        return client


def active_tesseract_broker_client() -> TesseractBrokerClient | None:
    return _ACTIVE_CLIENT


def set_worker_fork_denial_evidence(evidence: WorkerForkDenialEvidence) -> None:
    global _WORKER_FORK_DENIAL_EVIDENCE
    if type(evidence) is not WorkerForkDenialEvidence:
        raise BrokerProtocolError("worker fork-denial evidence type differs")
    if _WORKER_FORK_DENIAL_EVIDENCE is not None:
        raise BrokerProtocolError("worker fork-denial evidence is not repeatable")
    _WORKER_FORK_DENIAL_EVIDENCE = evidence


def worker_fork_denial_evidence() -> WorkerForkDenialEvidence:
    evidence = _WORKER_FORK_DENIAL_EVIDENCE
    if evidence is None:
        raise BrokerProtocolError("worker fork-denial evidence is unavailable")
    return evidence


def require_tesseract_broker_client() -> TesseractBrokerClient:
    client = _ACTIVE_CLIENT
    if client is None:
        raise BrokerProtocolError("Tesseract broker capability is unavailable")
    return client


def restore_subprocess_for_tests() -> None:
    global _ACTIVE_CLIENT, _WORKER_FORK_DENIAL_EVIDENCE
    with _INSTALL_LOCK:
        client = _ACTIVE_CLIENT
        _ACTIVE_CLIENT = None
        _WORKER_FORK_DENIAL_EVIDENCE = None
        subprocess.Popen = _ORIGINAL_POPEN  # type: ignore[assignment]
        if client is not None:
            with contextlib.suppress(BaseException):
                client.close()


__all__ = [
    "BROKER_CLIENT_FATAL_EXIT_CODE",
    "BrokerClientConfig",
    "BrokerPhaseLease",
    "BrokerPopen",
    "BrokerRunResult",
    "TesseractBrokerClient",
    "active_tesseract_broker_client",
    "install_tesseract_broker_client_from_fd",
    "require_tesseract_broker_client",
    "set_worker_fork_denial_evidence",
    "worker_fork_denial_evidence",
]
