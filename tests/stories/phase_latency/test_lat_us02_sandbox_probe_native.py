from __future__ import annotations

import ctypes
import errno
import fcntl
import hashlib
import json
import os
import signal
import socket
import stat
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest


class ProbeResult(ctypes.Structure):
    _fields_ = (
        ("abi_version", ctypes.c_int32),
        ("operation", ctypes.c_int32),
        ("terminal_stage", ctypes.c_int32),
        ("raw_errno", ctypes.c_int32),
        ("syscall_return", ctypes.c_int64),
        ("bytes_sent", ctypes.c_int64),
        ("bytes_received", ctypes.c_int64),
        ("cwd_restore_return", ctypes.c_int32),
        ("cwd_restore_errno", ctypes.c_int32),
    )


@pytest.fixture(scope="module")
def sandbox_probe_library(tmp_path_factory: pytest.TempPathFactory):
    workspace = Path(__file__).resolve().parents[3]
    source = workspace / "app/services/parser_sandbox_probe.c"
    build = tmp_path_factory.mktemp("lat-us02-sandbox-probe")
    library_path = build / "parser-sandbox-probe.dylib"
    subprocess.run(
        (
            "/usr/bin/clang",
            "-dynamiclib",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-o",
            str(library_path),
            str(source),
        ),
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    library = ctypes.CDLL(str(library_path), use_errno=True)
    library.lat_us02_sandbox_probe_path.argtypes = (
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_uint16,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ProbeResult),
    )
    library.lat_us02_sandbox_probe_path.restype = ctypes.c_int
    library.lat_us02_sandbox_probe_network.argtypes = (
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ProbeResult),
    )
    library.lat_us02_sandbox_probe_network.restype = ctypes.c_int
    return library


def _path_probe(
    library,
    *,
    operation: int,
    directory_fd: int,
    primary: bytes,
    secondary: bytes | None = None,
    flags: int = 0,
    mode: int = 0,
    payload: bytes = b"",
) -> ProbeResult:
    result = ProbeResult()
    payload_buffer = ctypes.create_string_buffer(payload) if payload else None
    returned = library.lat_us02_sandbox_probe_path(
        operation,
        directory_fd,
        primary,
        secondary,
        flags,
        mode,
        ctypes.cast(payload_buffer, ctypes.c_void_p) if payload_buffer else None,
        len(payload),
        ctypes.byref(result),
    )
    assert returned == 0
    assert result.abi_version == 2
    assert result.cwd_restore_return == 0
    assert result.cwd_restore_errno == 0
    return result


def _network_probe(
    library,
    *,
    operation: int,
    family: int,
    socket_type: int,
    protocol: int,
    directory_fd: int = -1,
    sockaddr: bytes,
    payload: bytes = b"",
) -> ProbeResult:
    result = ProbeResult()
    address_buffer = ctypes.create_string_buffer(sockaddr)
    payload_buffer = ctypes.create_string_buffer(payload) if payload else None
    returned = library.lat_us02_sandbox_probe_network(
        operation,
        family,
        socket_type,
        protocol,
        directory_fd,
        ctypes.cast(address_buffer, ctypes.c_void_p),
        len(sockaddr),
        ctypes.cast(payload_buffer, ctypes.c_void_p) if payload_buffer else None,
        len(payload),
        ctypes.byref(result),
    )
    assert returned == 0
    assert result.abi_version == 2
    return result


def _sockaddr_in(host: str, port: int) -> bytes:
    # Darwin sockaddr_in: length, family, network-order port, IPv4, zero pad.
    return bytes((16, socket.AF_INET)) + port.to_bytes(2, "big") + socket.inet_aton(
        host
    ) + b"\0" * 8


def _sockaddr_un(relative_path: str) -> bytes:
    encoded = relative_path.encode("utf-8")
    return bytes((len(encoded) + 3, socket.AF_UNIX)) + encoded + b"\0"


def test_runner_exact_hidden_visibility_build_exports_both_probe_abis(
    tmp_path: Path,
) -> None:
    from tests.benchmarks import latency_prewarm_production_runner as runner

    workspace = Path(__file__).resolve().parents[3]
    staged = tmp_path / "staged"
    staged.mkdir(mode=0o700)
    library_path, identity, source_path, source_sha256 = (
        runner._build_and_stage_native_sandbox_probe(
            workspace=workspace,
            target_root=staged,
        )
    )
    assert identity["sha256"] == hashlib.sha256(
        library_path.read_bytes()
    ).hexdigest()
    assert source_sha256 == hashlib.sha256(source_path.read_bytes()).hexdigest()
    library = ctypes.CDLL(str(library_path), use_errno=True)
    library.lat_us02_sandbox_probe_path.argtypes = (
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_uint16,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ProbeResult),
    )
    library.lat_us02_sandbox_probe_path.restype = ctypes.c_int
    library.lat_us02_sandbox_probe_network.argtypes = (
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ProbeResult),
    )
    library.lat_us02_sandbox_probe_network.restype = ctypes.c_int
    held = tmp_path / "held"
    held.mkdir(mode=0o700)
    (held / "read.bin").write_bytes(b"probe-read")
    held_fd = os.open(
        held, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    try:
        path_result = _path_probe(
            library,
            operation=5,
            directory_fd=held_fd,
            primary=b"read.bin",
        )
        missing_socket_path = b"absent.sock"
        sockaddr_un = bytes(
            (len(missing_socket_path) + 3, socket.AF_UNIX)
        ) + (missing_socket_path + b"\0")
        network_result = _network_probe(
            library,
            operation=1,
            family=socket.AF_UNIX,
            socket_type=socket.SOCK_STREAM,
            protocol=0,
            directory_fd=held_fd,
            sockaddr=sockaddr_un,
        )
    finally:
        os.close(held_fd)
    assert path_result.operation == 5
    assert network_result.operation == 1


def test_pinned_native_probe_bridge_retains_exact_raw_result(
    tmp_path: Path,
) -> None:
    from app.services.parser_sandbox_probe import NativeSandboxProbe
    from tests.benchmarks import latency_prewarm_production_runner as runner
    from tests.benchmarks.latency_prewarm_contracts import (
        KernelSandboxNativeProbeInvocation,
        KernelSandboxNativeProbeResult,
    )

    workspace = Path(__file__).resolve().parents[3]
    staged = tmp_path / "staged-bridge"
    staged.mkdir(mode=0o700)
    library_path, identity, _source_path, _source_sha256 = (
        runner._build_and_stage_native_sandbox_probe(
            workspace=workspace,
            target_root=staged,
        )
    )
    target_root = tmp_path / "probe-root"
    target_root.mkdir(mode=0o700)
    (target_root / "fixture.bin").write_bytes(b"known-readable-bytes")
    root_fd = os.open(
        target_root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
    )
    try:
        probe = NativeSandboxProbe(
            library_path,
            expected_sha256=str(identity["sha256"]),
        )
        invocation, result, blocked = probe.probe_path(
            operation_code=5,
            held_directory_fd=root_fd,
            primary_relative_path="fixture.bin",
            secondary_relative_path=None,
            open_flags=os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
            create_mode=None,
        )
    finally:
        os.close(root_fd)
    typed_invocation = KernelSandboxNativeProbeInvocation.model_validate(
        invocation
    )
    typed_result = KernelSandboxNativeProbeResult.model_validate(result)
    assert typed_result.syscall_return == len(b"known-readable-bytes")
    assert typed_result.bytes_received == len(b"known-readable-bytes")
    assert typed_result.top_level_return == 0
    assert typed_result.top_level_errno == typed_result.raw_errno == 0
    assert typed_invocation.held_directory_fd == root_fd
    assert (
        typed_invocation.native_thread_ids_before
        == typed_invocation.native_thread_ids_after
    )
    assert len(typed_invocation.native_thread_ids_before) == 1
    assert typed_invocation.prior_signal_mask == typed_invocation.restored_signal_mask
    assert (
        typed_invocation.signals_blocked_at_monotonic_ns
        < typed_invocation.syscall_returned_at_monotonic_ns
        < typed_invocation.signals_restored_at_monotonic_ns
    )
    assert signal.SIGTERM in blocked


def test_native_role_probe_plan_retains_process_fd_and_raw_call_custody(
    tmp_path: Path,
) -> None:
    from app.services.parser_sandbox_probe import (
        run_native_sandbox_probe_plan,
    )
    from app.services.parser_sandbox_role_plan import (
        ROOT_SANDBOX_EXECUTOR_AUTHORITY,
        ROOT_SANDBOX_HELD_DIRECTORY_ROLES,
    )
    from app.services.tesseract_broker_protocol import canonical_sha256
    from tests.benchmarks import latency_prewarm_production_runner as runner
    from tests.benchmarks.latency_prewarm_contracts import (
        KernelSandboxNativeProbeInvocation,
        KernelSandboxNativeProbeResult,
        KernelSandboxFileIdentity,
        NativeFileDescriptorInventory,
    )

    workspace = Path(__file__).resolve().parents[3]
    staged = tmp_path / "staged-role-plan"
    staged.mkdir(mode=0o700)
    library_path, identity, _source_path, _source_sha256 = (
        runner._build_and_stage_native_sandbox_probe(
            workspace=workspace,
            target_root=staged,
        )
    )
    held_directories: list[dict[str, object]] = []
    held_fds: list[int] = []
    try:
        import app.services.parser_sandbox_probe as bridge

        operations: list[dict[str, object]] = []
        for sequence, role in enumerate(
            ROOT_SANDBOX_HELD_DIRECTORY_ROLES["parser_worker"], start=1
        ):
            target_root = tmp_path / f"role-plan-root-{sequence:02d}"
            target_root.mkdir(mode=0o700)
            (target_root / "fixture.bin").write_bytes(b"role-plan-readable")
            descriptor = os.open(
                target_root,
                os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
            )
            held_fds.append(descriptor)
            observed = os.fstat(descriptor)
            held_directories.append(
                {
                    "role": role,
                    "descriptor": descriptor,
                    "resolved_path": str(target_root.resolve(strict=True)),
                    "path_sha256": hashlib.sha256(
                        str(target_root.resolve(strict=True)).encode("utf-8")
                    ).hexdigest(),
                    "device": observed.st_dev,
                    "inode": observed.st_ino,
                    "mode": observed.st_mode,
                    "uid": observed.st_uid,
                    "nlink": observed.st_nlink,
                    "open_flags": int(fcntl.fcntl(descriptor, fcntl.F_GETFL)),
                }
            )
            operations.append(
                {
                    "operation": f"read_held_root_{sequence:02d}",
                    "kind": "path",
                    "operation_code": 5,
                    "held_directory_fd": descriptor,
                    "primary_relative_path": "fixture.bin",
                    "secondary_relative_path": None,
                    "open_flags": os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
                    "create_mode": None,
                    "payload_hex": "",
                }
            )
        plan = {
            "schema_id": "phase-latency-kernel-sandbox-role-plan-v1",
            "attempt_id": "role-plan-attempt",
            "attempt_nonce_sha256": "1" * 64,
            "scope_sha256": "2" * 64,
            "role": "parser_worker",
            "profile_sha256": "3" * 64,
            "native_closure_sha256": "4" * 64,
            "probe_executor_authority": ROOT_SANDBOX_EXECUTOR_AUTHORITY,
            "probe_executor_source_sha256": hashlib.sha256(
                Path(bridge.__file__).read_bytes()
            ).hexdigest(),
            "probe_library_path": str(library_path),
            "probe_library_sha256": str(identity["sha256"]),
            "held_directories": held_directories,
            "operations": operations,
        }
        plan["plan_sha256"] = canonical_sha256(plan)
        applied = time.monotonic_ns()
        report = run_native_sandbox_probe_plan(
            plan,
            sandbox_applied_at_monotonic_ns=applied,
        )
    finally:
        for descriptor in held_fds:
            os.close(descriptor)

    assert report["record_sha256"] == canonical_sha256(
        {key: value for key, value in report.items() if key != "record_sha256"}
    )
    assert report["sandbox_applied_at_monotonic_ns"] == applied
    assert report["rows"][0]["started_monotonic_ns"] > applied
    KernelSandboxNativeProbeInvocation.model_validate(
        report["rows"][0]["native_invocation"]
    )
    result = KernelSandboxNativeProbeResult.model_validate(
        report["rows"][0]["native_result"]
    )
    assert result.bytes_received == len(b"role-plan-readable")
    before = NativeFileDescriptorInventory.model_validate(
        report["file_descriptor_inventory_before_probes"]
    )
    after = NativeFileDescriptorInventory.model_validate(
        report["file_descriptor_inventory_after_probes"]
    )
    assert before.descriptors == after.descriptors
    assert before.inventory_sha256 == after.inventory_sha256
    assert runner._validate_root_sandbox_probe_report(
        report,
        plan=plan,
        expected_pid=before.process.pid,
        expected_start_abstime=before.process.start_abstime,
        expected_ppid=before.process.ppid,
        expected_pgid=before.process.pgid,
        expected_sid=before.process.sid,
    ) == report
    crossed = json.loads(json.dumps(report))
    crossed_invocation = crossed["rows"][0]["native_invocation"]
    crossed_invocation["held_directory_fd"] = int(
        plan["held_directories"][1]["descriptor"]
    )
    crossed_invocation["invocation_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in crossed_invocation.items()
            if key != "invocation_sha256"
        }
    )
    crossed["record_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in crossed.items()
            if key != "record_sha256"
        }
    )
    with pytest.raises(ValueError, match="crossed its plan"):
        runner._validate_root_sandbox_probe_report(
            crossed,
            plan=plan,
            expected_pid=before.process.pid,
            expected_start_abstime=before.process.start_abstime,
            expected_ppid=before.process.ppid,
            expected_pgid=before.process.pgid,
            expected_sid=before.process.sid,
        )
    bridge_before = report["probe_executor_source_observation_before"]
    bridge_after = report["probe_executor_source_observation_after"]
    bridge_fields = {
        "resolved_path": bridge_before["resolved_path"],
        "resolved_path_sha256": bridge_before["resolved_path_sha256"],
        "content_sha256": bridge_before["content_sha256"],
        "device": bridge_before["device"],
        "inode": bridge_before["inode"],
        "mode": bridge_before["mode"],
        "uid": bridge_before["uid"],
        "effective_uid": bridge_before["effective_uid"],
        "nlink": bridge_before["nlink"],
        "size_bytes": bridge_before["size_bytes"],
        "mtime_ns": bridge_before["mtime_ns"],
        "ctime_ns": bridge_before["ctime_ns"],
        "first_descriptor": bridge_before["descriptor"],
        "first_open_flags": bridge_before["open_flags"],
        "first_observed_at_monotonic_ns": bridge_before[
            "observed_at_monotonic_ns"
        ],
        "second_descriptor": bridge_after["descriptor"],
        "second_open_flags": bridge_after["open_flags"],
        "second_observed_at_monotonic_ns": bridge_after[
            "observed_at_monotonic_ns"
        ],
        "observations_used_nofollow": True,
        "observations_hashed_open_descriptor": True,
    }
    KernelSandboxFileIdentity.model_validate(
        {
            **bridge_fields,
            "record_sha256": canonical_sha256(bridge_fields),
        }
    )


def test_native_probe_bridge_rejects_dot_path_before_native_call(
    tmp_path: Path,
) -> None:
    from app.services.parser_sandbox_probe import NativeSandboxProbe
    from tests.benchmarks import latency_prewarm_production_runner as runner

    workspace = Path(__file__).resolve().parents[3]
    staged = tmp_path / "staged-dot-path"
    staged.mkdir(mode=0o700)
    library_path, identity, _source_path, _source_sha256 = (
        runner._build_and_stage_native_sandbox_probe(
            workspace=workspace,
            target_root=staged,
        )
    )
    held = tmp_path / "held-dot-path"
    held.mkdir(mode=0o700)
    held_fd = os.open(
        held, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    )
    try:
        probe = NativeSandboxProbe(
            library_path, expected_sha256=str(identity["sha256"])
        )
        with pytest.raises(ValueError, match="relative path"):
            probe.probe_path(
                operation_code=5,
                held_directory_fd=held_fd,
                primary_relative_path="..",
                secondary_relative_path=None,
                open_flags=os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
                create_mode=None,
            )
    finally:
        os.close(held_fd)


def test_native_sandbox_probe_anchors_path_operations_to_held_dirfd(
    sandbox_probe_library,
    tmp_path: Path,
) -> None:
    original = tmp_path / "held"
    original.mkdir(mode=0o700)
    (original / "identity.bin").write_bytes(b"held-vnode")
    held_fd = os.open(
        original,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    original_cwd = os.getcwd()
    moved = tmp_path / "moved-held"
    replacement = tmp_path / "held"
    try:
        original.rename(moved)
        replacement.mkdir(mode=0o700)
        (replacement / "identity.bin").write_bytes(b"replacement-vnode")
        read = _path_probe(
            sandbox_probe_library,
            operation=5,
            directory_fd=held_fd,
            primary=b"identity.bin",
            flags=os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        assert read.terminal_stage == 5
        assert read.raw_errno == 0
        assert read.bytes_received == len(b"held-vnode")
        assert os.getcwd() == original_cwd

        payload = b"sandbox-roundtrip"
        scratch = _path_probe(
            sandbox_probe_library,
            operation=6,
            directory_fd=held_fd,
            primary=b"scratch.bin",
            flags=(
                os.O_RDWR
                | os.O_CREAT
                | os.O_EXCL
                | os.O_NOFOLLOW
                | os.O_CLOEXEC
            ),
            mode=0o600,
            payload=payload,
        )
        assert scratch.terminal_stage == 7
        assert scratch.syscall_return == 0
        assert scratch.raw_errno == 0
        assert scratch.bytes_sent == scratch.bytes_received == len(payload)
        assert not (moved / "scratch.bin").exists()
        assert not (replacement / "scratch.bin").exists()
        assert os.getcwd() == original_cwd
    finally:
        os.close(held_fd)


def test_native_sandbox_probe_anchors_unix_connect_to_held_dirfd(
    sandbox_probe_library,
    tmp_path: Path,
) -> None:
    original = tmp_path / "held-unix-connect"
    moved = tmp_path / "moved-unix-connect"
    replacement = tmp_path / "held-unix-connect"
    original.mkdir(mode=0o700)
    held_fd = os.open(
        original, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    intended = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    decoy = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    setup_cwd = os.getcwd()
    try:
        os.chdir(original)
        try:
            intended.bind("trap.sock")
        except PermissionError as error:
            if error.errno == errno.EPERM:
                pytest.skip("host sandbox forbids AF_UNIX bind")
            raise
        os.chdir(setup_cwd)
        intended.listen(1)
        intended.settimeout(1)
        original.rename(moved)
        replacement.mkdir(mode=0o700)
        os.chdir(replacement)
        decoy.bind("trap.sock")
        os.chdir(setup_cwd)
        decoy.listen(1)
        decoy.settimeout(0.05)
        observed_cwd = os.getcwd()
        result = _network_probe(
            sandbox_probe_library,
            operation=1,
            family=socket.AF_UNIX,
            socket_type=socket.SOCK_STREAM,
            protocol=0,
            directory_fd=held_fd,
            sockaddr=_sockaddr_un("trap.sock"),
        )
        assert result.terminal_stage == 10
        assert result.syscall_return == 0
        assert result.raw_errno == 0
        assert result.cwd_restore_return == 0
        assert result.cwd_restore_errno == 0
        accepted, _ = intended.accept()
        accepted.close()
        with pytest.raises(TimeoutError):
            decoy.accept()
        assert os.getcwd() == observed_cwd
    finally:
        os.chdir(setup_cwd)
        intended.close()
        decoy.close()
        os.close(held_fd)


def test_native_sandbox_probe_anchors_unix_bind_to_held_dirfd(
    sandbox_probe_library,
    tmp_path: Path,
) -> None:
    original = tmp_path / "held-unix-bind"
    moved = tmp_path / "moved-unix-bind"
    replacement = tmp_path / "held-unix-bind"
    original.mkdir(mode=0o700)
    held_fd = os.open(
        original, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    try:
        original.rename(moved)
        replacement.mkdir(mode=0o700)
        observed_cwd = os.getcwd()
        result = _network_probe(
            sandbox_probe_library,
            operation=3,
            family=socket.AF_UNIX,
            socket_type=socket.SOCK_STREAM,
            protocol=0,
            directory_fd=held_fd,
            sockaddr=_sockaddr_un("bound.sock"),
        )
        if result.syscall_return == -1 and result.raw_errno == errno.EPERM:
            pytest.skip("host sandbox forbids AF_UNIX bind")
        assert result.terminal_stage == 13
        assert result.syscall_return == 0
        assert result.raw_errno == 0
        assert result.cwd_restore_return == 0
        assert result.cwd_restore_errno == 0
        assert stat.S_ISSOCK((moved / "bound.sock").lstat().st_mode)
        assert not (replacement / "bound.sock").exists()
        assert os.getcwd() == observed_cwd
    finally:
        os.close(held_fd)


def test_native_sandbox_probe_exposes_raw_udp_connect_and_bind_results(
    sandbox_probe_library,
) -> None:
    payload = b"KSNP1-controller-nonce"
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        udp.bind(("127.0.0.1", 0))
    except PermissionError as error:
        udp.close()
        if error.errno == errno.EPERM:
            pytest.skip("host sandbox forbids controller loopback bind")
        raise
    udp.settimeout(1)
    try:
        send = _network_probe(
            sandbox_probe_library,
            operation=2,
            family=socket.AF_INET,
            socket_type=socket.SOCK_DGRAM,
            protocol=socket.IPPROTO_UDP,
            sockaddr=_sockaddr_in(*udp.getsockname()),
            payload=payload,
        )
        assert send.terminal_stage == 11
        assert send.syscall_return == len(payload)
        assert send.raw_errno == 0
        assert send.bytes_sent == len(payload)
        assert udp.recvfrom(4096)[0] == payload
    finally:
        udp.close()

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(1)
    try:
        connect = _network_probe(
            sandbox_probe_library,
            operation=1,
            family=socket.AF_INET,
            socket_type=socket.SOCK_STREAM,
            protocol=socket.IPPROTO_TCP,
            sockaddr=_sockaddr_in(*listener.getsockname()),
        )
        assert connect.terminal_stage == 10
        assert connect.syscall_return == 0
        assert connect.raw_errno == 0
        accepted, _ = listener.accept()
        accepted.close()
    finally:
        listener.close()

    bind = _network_probe(
        sandbox_probe_library,
        operation=3,
        family=socket.AF_INET,
        socket_type=socket.SOCK_STREAM,
        protocol=socket.IPPROTO_TCP,
        sockaddr=_sockaddr_in("127.0.0.1", 0),
    )
    assert bind.terminal_stage == 13
    assert bind.syscall_return == 0
    assert bind.raw_errno == 0


@pytest.mark.skipif(
    sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file(),
    reason="real Seatbelt helper probe requires Darwin",
)
def test_native_sandbox_probe_observes_real_seatbelt_denials_and_scratch_control(
    sandbox_probe_library,
    tmp_path: Path,
) -> None:
    from tests.benchmarks import latency_prewarm_production_runner as runner

    root = tmp_path / "actual-seatbelt-probe"
    root.mkdir(mode=0o700)
    artifact = root / "artifact"
    tessdata = root / "tessdata"
    scratch = root / "scratch"
    staged = root / "staged"
    input_probe = root / "input-probe"
    network_traps = root / "network-traps"
    artifact_clone = root / "artifact-clone"
    tessdata_clone = root / "tessdata-clone"
    staged_clone = root / "staged-clone"
    for directory in (
        artifact,
        tessdata,
        scratch,
        staged,
        input_probe,
        network_traps,
        artifact_clone,
        tessdata_clone,
        staged_clone,
    ):
        directory.mkdir(mode=0o700)
    executable = staged / "tesseract"
    executable.write_bytes(b"private-staged-executable")
    executable.chmod(0o500)
    profile = runner._production_seatbelt_profile(
        artifact_root=artifact,
        tessdata_root=tessdata,
        request_root=scratch,
        input_probe_root=input_probe,
        network_trap_root=network_traps,
        artifact_probe_clone_root=artifact_clone,
        tessdata_probe_clone_root=tessdata_clone,
        staged_executable_probe_clone_root=staged_clone,
        worker_scratch_root=scratch,
        immutable_executable=executable,
        deny_process_fork=True,
    )
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 0))
    except PermissionError as error:
        listener.close()
        if error.errno == errno.EPERM:
            pytest.skip("host sandbox forbids controller loopback bind")
        raise
    listener.listen(1)
    listener.settimeout(0.25)
    sockaddr = _sockaddr_in(*listener.getsockname())
    script = textwrap.dedent(
        """
        import ctypes, json, os, sys

        class R(ctypes.Structure):
            _fields_ = (
                ("abi_version", ctypes.c_int32),
                ("operation", ctypes.c_int32),
                ("terminal_stage", ctypes.c_int32),
                ("raw_errno", ctypes.c_int32),
                ("syscall_return", ctypes.c_int64),
                ("bytes_sent", ctypes.c_int64),
                ("bytes_received", ctypes.c_int64),
                ("cwd_restore_return", ctypes.c_int32),
                ("cwd_restore_errno", ctypes.c_int32),
            )

        library = ctypes.CDLL(sys.argv[1], use_errno=True)
        library.lat_us02_sandbox_probe_path.argtypes = (
            ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p,
            ctypes.c_int, ctypes.c_uint16, ctypes.c_void_p, ctypes.c_size_t,
            ctypes.POINTER(R),
        )
        library.lat_us02_sandbox_probe_network.argtypes = (
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
            ctypes.c_size_t, ctypes.POINTER(R),
        )
        protected_fd = os.open(
            sys.argv[2], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
        scratch_fd = os.open(
            sys.argv[3], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
        denied = R()
        library.lat_us02_sandbox_probe_path(
            1, protected_fd, b"denied.bin", None,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600, None, 0, ctypes.byref(denied),
        )
        payload = ctypes.create_string_buffer(b"scratch-control")
        allowed = R()
        library.lat_us02_sandbox_probe_path(
            6, scratch_fd, b"allowed.bin", None,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600, ctypes.cast(payload, ctypes.c_void_p), len(b"scratch-control"),
            ctypes.byref(allowed),
        )
        raw = bytes.fromhex(sys.argv[4])
        raw_buffer = ctypes.create_string_buffer(raw)
        network = R()
        library.lat_us02_sandbox_probe_network(
            1, 2, 1, 6, -1,
            ctypes.cast(raw_buffer, ctypes.c_void_p), len(raw),
            None, 0, ctypes.byref(network),
        )
        os.close(protected_fd)
        os.close(scratch_fd)
        print(json.dumps({
            "denied": [denied.terminal_stage, denied.syscall_return, denied.raw_errno,
                       denied.cwd_restore_return, denied.cwd_restore_errno],
            "allowed": [allowed.terminal_stage, allowed.syscall_return,
                        allowed.raw_errno, allowed.bytes_sent, allowed.bytes_received,
                        allowed.cwd_restore_return, allowed.cwd_restore_errno],
            "network": [network.terminal_stage, network.syscall_return,
                        network.raw_errno, network.bytes_sent],
        }, sort_keys=True, separators=(",", ":")))
        """
    )
    try:
        completed = subprocess.run(
            (
                "/usr/bin/sandbox-exec",
                "-p",
                profile,
                sys.executable,
                "-I",
                "-S",
                "-B",
                "-c",
                script,
                str(Path(sandbox_probe_library._name).resolve(strict=True)),
                str(artifact),
                str(scratch),
                sockaddr.hex(),
            ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": "/usr/bin:/bin"},
            check=False,
            timeout=5,
        )
        if completed.returncode == 71 and b"sandbox_apply: Operation not permitted" in (
            completed.stderr
        ):
            pytest.skip("host sandbox forbids nested Seatbelt application")
        assert completed.returncode == 0, completed.stderr[:4096]
        result = json.loads(completed.stdout)
        assert result["denied"] in ([2, -1, 1, 0, 0], [2, -1, 13, 0, 0])
        assert result["allowed"] == [7, 0, 0, 15, 15, 0, 0]
        assert result["network"] in ([10, -1, 1, 0], [10, -1, 13, 0])
        assert not (artifact / "denied.bin").exists()
        assert list(scratch.iterdir()) == []
        with pytest.raises(TimeoutError):
            listener.accept()
    finally:
        listener.close()
