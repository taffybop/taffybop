from __future__ import annotations

import copy
import errno
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.tesseract_broker import TesseractBroker
from app.services.tesseract_broker_native import (
    kernel_process_identity,
    native_executable_region_inventory,
)
from app.services.tesseract_broker_protocol import (
    BrokerProtocolError,
    canonical_sha256,
)
from app.services.tesseract_native_closure import (
    NATIVE_RUNTIME_GATE_ACK_BYTES,
    derive_native_closure,
    native_runtime_non_system_projection,
    observe_runtime_native_scan,
    validate_runtime_native_scan,
)


pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="runtime native-image custody is approved only on Darwin",
)


def test_runtime_scan_esrch_requires_exact_terminal_wnowait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = object.__new__(TesseractBroker)
    child = SimpleNamespace(pid=71_001)
    state = {
        "samples": [
            SimpleNamespace(
                bracket_completed_monotonic_ns=time.monotonic_ns()
            )
        ]
    }
    terminal = SimpleNamespace(
        si_pid=child.pid,
        si_code=os.CLD_EXITED,
        si_status=0,
    )
    observations = iter((None, terminal))
    monkeypatch.setattr(os, "waitid", lambda *_args: next(observations))
    monkeypatch.setattr(
        broker,
        "_append_runtime_scan",
        lambda *_args: (_ for _ in ()).throw(
            ProcessLookupError(errno.ESRCH, "child exited before libproc scan")
        ),
    )

    assert broker._observe_runtime_terminal_or_scan(
        state,
        child,
        scan_if_live=True,
    )
    assert state["terminal_waitid"]["pid"] == child.pid
    assert state["terminal_waitid"]["code"] == os.CLD_EXITED


def test_runtime_scan_esrch_while_child_is_live_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = object.__new__(TesseractBroker)
    child = SimpleNamespace(pid=71_002)
    state = {
        "samples": [
            SimpleNamespace(
                bracket_completed_monotonic_ns=time.monotonic_ns()
            )
        ]
    }
    monkeypatch.setattr(os, "waitid", lambda *_args: None)
    monkeypatch.setattr(
        broker,
        "_append_runtime_scan",
        lambda *_args: (_ for _ in ()).throw(
            ProcessLookupError(errno.ESRCH, "injected libproc failure")
        ),
    )

    with pytest.raises(BrokerProtocolError, match="lost a nonterminal"):
        broker._observe_runtime_terminal_or_scan(
            state,
            child,
            scan_if_live=True,
        )


def _staged_tesseract(tmp_path: Path) -> tuple[str, str, dict[str, object]]:
    discovered = shutil.which("tesseract")
    if discovered is None:
        pytest.skip("Tesseract is unavailable")
    source = os.path.realpath(discovered)
    staged_root = tmp_path / "staged-tesseract"
    staged_root.mkdir(mode=0o700)
    staged = staged_root / "tesseract"
    shutil.copyfile(source, staged)
    staged.chmod(0o500)
    gate_source_input = (
        Path(__file__).parents[3]
        / "app"
        / "services"
        / "tesseract_runtime_gate.c"
    )
    gate_source = tmp_path / "tesseract_runtime_gate.c"
    shutil.copyfile(gate_source_input, gate_source)
    gate_source.chmod(0o500)
    gate_library = tmp_path / "tesseract_runtime_gate.dylib"
    subprocess.run(
        (
            "/usr/bin/clang",
            "-dynamiclib",
            "-Os",
            "-fvisibility=hidden",
            "-o",
            str(gate_library),
            str(gate_source),
        ),
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    gate_library.chmod(0o500)
    return (
        source,
        str(staged),
        derive_native_closure(
            source,
            str(staged),
            runtime_gate_source_path=str(gate_source),
            runtime_gate_library_path=str(gate_library),
        ),
    )


def _waiting_child(
    executable: str,
    closure: dict[str, object],
    arguments: tuple[str, ...] = ("stdin", "stdout"),
) -> tuple[subprocess.Popen[bytes], int, str]:
    runtime_gate = closure["runtime_gate"]
    assert isinstance(runtime_gate, dict)
    library = runtime_gate["library"]
    assert isinstance(library, dict)
    gate_read, gate_write = os.pipe()
    os.set_inheritable(gate_write, True)
    nonce = os.urandom(32)
    environment = {
        "LANG": "C",
        "LC_ALL": "C",
        "OMP_THREAD_LIMIT": "1",
        "TESSDATA_PREFIX": "/opt/homebrew/share/tessdata",
        "DYLD_INSERT_LIBRARIES": str(library["resolved_path"]),
        "PARSER_TESSERACT_RUNTIME_GATE_FD": str(gate_write),
        "PARSER_TESSERACT_RUNTIME_GATE_NONCE": nonce.hex(),
    }
    child = subprocess.Popen(
        [executable, *arguments],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        pass_fds=(gate_write,),
    )
    os.close(gate_write)
    return child, gate_read, __import__("hashlib").sha256(nonce).hexdigest()


def test_runtime_scan_binds_kernel_mappings_to_frozen_closure(
    tmp_path: Path,
) -> None:
    _source, staged, closure = _staged_tesseract(tmp_path)
    child, gate_read, _nonce_sha256 = _waiting_child(staged, closure)
    try:
        assert len(os.read(gate_read, NATIVE_RUNTIME_GATE_ACK_BYTES)) == 56
        assert os.read(gate_read, 1) == b""
        os.waitid(os.P_PID, child.pid, os.WSTOPPED | os.WNOWAIT)
        expected_paths = {
            row["resolved_path"]
            for row in native_runtime_non_system_projection(closure)["images"]
        }
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            observed_paths = {
                region.resolved_path
                for region in native_executable_region_inventory(
                    child.pid
                ).regions
                if not region.resolved_path.startswith(
                    ("/usr/lib/", "/System/Library/")
                )
            }
            if observed_paths == expected_paths:
                break
            time.sleep(0.01)
        assert observed_paths == expected_paths
        identity = kernel_process_identity(child.pid)
        scan = observe_runtime_native_scan(child.pid, identity, closure)
        assert validate_runtime_native_scan(scan, closure, identity) == scan
        assert scan["mapped_image_count"] >= 2
        assert sum(
            image["resolved_path"] == staged
            for image in scan["mapped_images"]
        ) == 1

        forged = copy.deepcopy(scan)
        target = next(
            image
            for image in forged["mapped_images"]
            if image["system_image"] is False
        )
        target["closure_image_sha256"] = "a" * 64
        target["record_sha256"] = canonical_sha256(
            {
                key: value
                for key, value in target.items()
                if key != "record_sha256"
            }
        )
        forged["record_sha256"] = canonical_sha256(
            {
                key: value
                for key, value in forged.items()
                if key != "record_sha256"
            }
        )
        with pytest.raises(BrokerProtocolError):
            validate_runtime_native_scan(forged, closure, identity)

        # A self-consistent retained scan may not omit one frozen dependency,
        # even when every count, inventory digest, projection digest, and outer
        # record digest is recomputed around the smaller image set.
        omitted = copy.deepcopy(scan)
        removable = next(
            image
            for image in omitted["mapped_images"]
            if image["system_image"] is False
            and image["resolved_path"] != staged
        )
        omitted["mapped_images"].remove(removable)
        omitted["mapped_image_count"] = len(omitted["mapped_images"])
        regions = sorted(
            (
                region
                for image in omitted["mapped_images"]
                for region in image["executable_regions"]
            ),
            key=lambda item: item["address"],
        )
        omitted["executable_region_count"] = len(regions)
        omitted["raw_kernel_inventory_sha256"] = canonical_sha256(
            {"process": omitted["process"], "regions": regions}
        )
        projection_rows = [
            {
                "resolved_path": image["resolved_path"],
                "sha256": image["closure_image_sha256"],
                "device": image["device"],
                "inode": image["inode"],
                "mode": image["mode"],
                "uid": image["uid"],
                "gid": image["gid"],
                "nlink": image["nlink"],
                "size": image["size"],
                "mtime_ns": image["mtime_ns"],
                "ctime_ns": image["ctime_ns"],
            }
            for image in omitted["mapped_images"]
            if image["system_image"] is False
        ]
        projection = {
            "schema_id": (
                "parser-tesseract-runtime-non-system-projection-v1"
            ),
            "staged_root": staged,
            "image_count": len(projection_rows),
            "images": projection_rows,
        }
        projection_sha256 = canonical_sha256(projection)
        omitted["expected_non_system_image_count"] = len(projection_rows)
        omitted["observed_non_system_image_count"] = len(projection_rows)
        omitted["expected_non_system_projection_sha256"] = (
            projection_sha256
        )
        omitted["observed_non_system_projection_sha256"] = (
            projection_sha256
        )
        omitted["record_sha256"] = canonical_sha256(
            {
                key: value
                for key, value in omitted.items()
                if key != "record_sha256"
            }
        )
        with pytest.raises(BrokerProtocolError):
            validate_runtime_native_scan(omitted, closure, identity)
    finally:
        os.close(gate_read)
        with __import__("contextlib").suppress(ChildProcessError):
            os.waitid(os.P_PID, child.pid, os.WSTOPPED | os.WNOHANG)
        with __import__("contextlib").suppress(ProcessLookupError):
            os.kill(child.pid, __import__("signal").SIGCONT)
        child.kill()
        child.communicate(timeout=10)


@pytest.mark.parametrize(
    "arguments",
    (("stdin", "stdout"), ("--version",), ("--list-langs",)),
)
def test_actual_tesseract_child_is_stop_gated_and_double_scanned(
    tmp_path: Path,
    arguments: tuple[str, ...],
) -> None:
    _source, staged, closure = _staged_tesseract(tmp_path)
    broker = TesseractBroker.__new__(TesseractBroker)
    runtime_gate = closure["runtime_gate"]
    assert isinstance(runtime_gate, dict)
    gate_source = runtime_gate["source"]
    gate_library = runtime_gate["library"]
    assert isinstance(gate_source, dict) and isinstance(gate_library, dict)
    broker.config = SimpleNamespace(
        executable=SimpleNamespace(resolved_path=staged),
        native_closure=closure,
        native_runtime_gate=runtime_gate,
        native_runtime_gate_source=SimpleNamespace(
            sha256=gate_source["sha256"]
        ),
        native_runtime_gate_library=SimpleNamespace(
            resolved_path=gate_library["resolved_path"],
            sha256=gate_library["sha256"],
        ),
    )
    child, gate_read, nonce_sha256 = _waiting_child(
        staged, closure, arguments
    )
    try:
        identity = kernel_process_identity(child.pid)
        class _Ledger:
            @staticmethod
            def append(_kind: str, record: dict[str, object]) -> str:
                return canonical_sha256(record)

        broker.ledger = _Ledger()

        state = broker._gate_actual_child_for_native_scan(
            identity,
            time.monotonic_ns() + 10_000_000_000,
            runtime_gate_fd=gate_read,
            runtime_gate_nonce_sha256=nonce_sha256,
            exec_release_e_monotonic_ns=time.monotonic_ns(),
        )
        samples = state["samples"]
        assert len(samples) == 2
        assert len(
            {sample.raw_kernel_inventory_sha256 for sample in samples}
        ) == 1
        assert (
            state["stop_observed_monotonic_ns"]
            <= samples[0].bracket_started_monotonic_ns
        )
        assert (
            samples[1].bracket_completed_monotonic_ns
            <= state["continued_signal_sent_monotonic_ns"]
            <= state["continued_observed_monotonic_ns"]
        )
    finally:
        os.close(gate_read)
        child.kill()
        child.communicate(timeout=10)


def test_static_closure_discloses_dlopen_imports(tmp_path: Path) -> None:
    compiler = shutil.which("clang")
    if compiler is None:
        pytest.skip("clang is unavailable")
    source_file = tmp_path / "probe.c"
    source_file.write_text(
        "#include <dlfcn.h>\n"
        "int main(void) { return dlopen(\"/usr/lib/libSystem.B.dylib\", "
        "RTLD_LAZY) == 0; }\n",
        encoding="utf-8",
    )
    source_image = tmp_path / "probe"
    subprocess.run(
        [compiler, "-o", str(source_image), str(source_file)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    source_image.chmod(0o500)
    staged_image = tmp_path / "probe-staged"
    shutil.copyfile(source_image, staged_image)
    staged_image.chmod(0o500)
    closure = derive_native_closure(str(source_image), str(staged_image))
    assert closure["dynamic_loader_importing_image_count"] == 2
    assert all(
        "_dlopen" in image["dynamic_loader_imports"]
        for image in closure["dynamic_loader_importing_images"]
    )


@pytest.mark.parametrize(
    "operation",
    ("version", "list_languages", "ocr_text"),
)
def test_full_native_broker_child_path_uses_constructor_gate_and_wait4(
    tmp_path: Path,
    operation: str,
) -> None:
    source, staged, closure = _staged_tesseract(tmp_path)
    runtime_gate = closure["runtime_gate"]
    assert isinstance(runtime_gate, dict)
    gate_source = runtime_gate["source"]
    gate_library = runtime_gate["library"]
    assert isinstance(gate_source, dict) and isinstance(gate_library, dict)
    spawn_source = (
        Path(__file__).parents[3]
        / "app"
        / "services"
        / "tesseract_broker_spawn.c"
    )
    spawn_library = tmp_path / "tesseract_broker_spawn.dylib"
    subprocess.run(
        (
            "/usr/bin/clang",
            "-dynamiclib",
            "-Os",
            "-fvisibility=hidden",
            "-o",
            str(spawn_library),
            str(spawn_source),
        ),
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    spawn_library.chmod(0o500)
    probe_source = (
        Path(__file__).parents[3]
        / "app"
        / "services"
        / "parser_sandbox_probe.c"
    )
    probe_library = tmp_path / "parser_sandbox_probe.dylib"
    subprocess.run(
        (
            "/usr/bin/clang",
            "-dynamiclib",
            "-Os",
            "-fvisibility=hidden",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-o",
            str(probe_library),
            str(probe_source),
        ),
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    probe_library.chmod(0o500)
    tessdata = "/opt/homebrew/share/tessdata"
    if not Path(tessdata, "eng.traineddata").is_file():
        pytest.skip("Homebrew English tessdata is unavailable")
    script = r'''
import copy, ctypes, hashlib, json, os, socket, sys, threading, time
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from app.services.tesseract_broker import (
    TesseractBroker,
    derive_guard_python_module_tree_custody,
    derive_guard_python_path_custody,
)
import app.services.tesseract_broker as broker_module
from app.services.tesseract_broker_native import kernel_process_identity
from app.services.tesseract_broker_protocol import (
    BROKER_PROTOCOL_SCHEMA,
    BrokerExecutableIdentity,
    BrokerProtocolError,
    BrokerQuiescenceReceipt,
    BrokerRequestReceipt,
    BrokerScratchInventory,
    FramedChannel,
    KernelProcessIdentity,
    broker_audit_record_maximum_bytes,
    build_request_receipt_transport,
    canonical_json_bytes,
    canonical_sha256,
    dataclass_mapping,
    request_receipt_from_blob,
    request_receipt_from_mapping,
    receive_request_receipt_chunks,
    send_request_receipt_chunks,
)
from app.services.tesseract_child_exec import frozen_tesseract_environment, module_sha256
from app.services.tesseract_native_closure import derive_native_closure
from app.services.parser_sandbox_materialization import materialize_sandbox_probe_roots
from app.services.parser_sandbox_role_plan import SandboxRoleDirectoryAuthority, build_child_sandbox_probe_plan
from app.services.parser_sandbox_network_traps import _sockaddr_in, _sockaddr_in6, _sockaddr_un
from app.services.tesseract_child_sandbox_probe import child_sandbox_probe_report_reservation_bytes

source, staged, gate_source, gate_library, spawn_source, spawn_library, probe_library, probe_root, operation, tessdata = sys.argv[1:]
def identity(path):
    observed = os.lstat(path)
    return BrokerExecutableIdentity(
        resolved_path=os.path.realpath(path),
        sha256=hashlib.sha256(open(path, 'rb').read()).hexdigest(),
        device=observed.st_dev,
        inode=observed.st_ino,
        mode=observed.st_mode,
        uid=observed.st_uid,
        nlink=observed.st_nlink,
        size=observed.st_size,
    )
closure = derive_native_closure(
    source,
    staged,
    runtime_gate_source_path=gate_source,
    runtime_gate_library_path=gate_library,
)
guard_python_path = os.path.realpath(
    '/Library/Developer/CommandLineTools/usr/bin/python3'
)
guard_python = identity(guard_python_path)
guard_python_path_custody = derive_guard_python_path_custody(
    guard_python_path
)
guard_python_native_closure = derive_native_closure(
    guard_python_path,
    guard_python_path,
)
guard_python_module_tree_custody = (
    derive_guard_python_module_tree_custody(
        os.path.dirname(os.path.dirname(guard_python_path))
    )
)
guard_wrapper_source = open(
    os.path.join(os.getcwd(), 'app/services/tesseract_child_exec.py'),
    'rb',
).read()
sandbox_base = Path(probe_root, 'native-runtime-sandbox-probes')
sandbox_base.mkdir(mode=0o700)
sandbox_materialization = materialize_sandbox_probe_roots(
    base_root=sandbox_base,
    artifact_source=Path(spawn_source).resolve(strict=True),
    tessdata_source=Path(tessdata, 'eng.traineddata').resolve(strict=True),
    staged_executable_source=Path(staged).resolve(strict=True),
    input_source=Path(spawn_source).resolve(strict=True),
)
for sandbox_root in sandbox_materialization.roots.values():
    for sandbox_leaf in sandbox_root.iterdir():
        if sandbox_leaf.is_file():
            sandbox_leaf.chmod(0o400)
    sandbox_root.chmod(0o500)
sandbox_scratch = Path(probe_root, 'native-runtime-sandbox-scratch')
sandbox_scratch.mkdir(mode=0o700)
sandbox_scratch_fd = os.open(
    sandbox_scratch,
    os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
)
sandbox_directories = SandboxRoleDirectoryAuthority.open(
    materialization=sandbox_materialization,
    artifact_read_path=Path(spawn_source).resolve(strict=True),
    tessdata_read_path=Path(tessdata, 'eng.traineddata').resolve(strict=True),
    staged_executable_read_path=Path(staged).resolve(strict=True),
)
network_fd = sandbox_directories.descriptors_by_role['network_trap_root']
network_targets = (
    ('ipv4_tcp_connect', 1, socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, -1, _sockaddr_in('127.0.0.1', 41001), b''),
    ('ipv6_tcp_connect', 1, socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, -1, _sockaddr_in6('::1', 41002), b''),
    ('ipv4_udp_sendto', 2, socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP, -1, _sockaddr_in('127.0.0.1', 41003), b'probe123'),
    ('ipv6_udp_sendto', 2, socket.AF_INET6, socket.SOCK_DGRAM, socket.IPPROTO_UDP, -1, _sockaddr_in6('::1', 41004), b'probe123'),
    ('unix_connect', 1, socket.AF_UNIX, socket.SOCK_STREAM, 0, network_fd, _sockaddr_un('controller.sock'), b''),
    ('ipv4_bind_listen', 3, socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, -1, _sockaddr_in('127.0.0.1', 0), b''),
    ('ipv6_bind_listen', 3, socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, -1, _sockaddr_in6('::1', 0), b''),
    ('unix_bind', 3, socket.AF_UNIX, socket.SOCK_STREAM, 0, network_fd, _sockaddr_un('child-bind.sock'), b''),
)
network_operations = tuple({
    'operation': name,
    'kind': 'network',
    'operation_code': code,
    'held_directory_fd': descriptor,
    'domain': int(family),
    'socket_type': int(socket_type),
    'protocol': int(protocol),
    'sockaddr_hex': sockaddr.hex(),
    'payload_hex': payload.hex(),
} for name, code, family, socket_type, protocol, descriptor, sockaddr, payload in network_targets)
child_executor_source = open(
    os.path.join(os.getcwd(), 'app/services/tesseract_child_sandbox_probe.py'),
    'rb',
).read()
child_executor_source_sha256 = hashlib.sha256(child_executor_source).hexdigest()
child_sandbox_plan, child_sandbox_reservation = build_child_sandbox_probe_plan(
    attempt_id='native-runtime-integration',
    attempt_nonce_sha256=hashlib.sha256(('f' * 64).encode('ascii')).hexdigest(),
    scope_sha256='e' * 64,
    profile_sha256='b' * 64,
    native_closure_sha256=closure['closure_sha256'],
    executor_source_sha256=child_executor_source_sha256,
    probe_library_path=Path(probe_library).resolve(strict=True),
    probe_library_sha256=hashlib.sha256(open(probe_library, 'rb').read()).hexdigest(),
    directories=sandbox_directories,
    network_operations=network_operations,
)
config = SimpleNamespace(
    executable=identity(staged),
    source_executable=identity(source),
    native_closure=closure,
    native_closure_sha256=closure['closure_sha256'],
    native_runtime_gate=closure['runtime_gate'],
    native_runtime_gate_source=identity(gate_source),
    native_runtime_gate_library=identity(gate_library),
    native_spawn_guard=identity(spawn_library),
    native_spawn_guard_source_sha256=hashlib.sha256(open(spawn_source, 'rb').read()).hexdigest(),
    child_wrapper_sha256=module_sha256(),
    guard_python=guard_python,
    guard_python_path_custody=guard_python_path_custody,
    guard_python_native_closure=guard_python_native_closure,
    guard_python_native_closure_sha256=guard_python_native_closure['closure_sha256'],
    guard_python_module_tree_custody=guard_python_module_tree_custody,
    guard_wrapper_source=guard_wrapper_source,
    broker_profile_sha256='b' * 64,
    tessdata_sha256='d' * 64,
    attempt_nonce='f' * 64,
    scope_sha256='e' * 64,
    attempt_deadline_ns=time.monotonic_ns() + 30_000_000_000,
    child_sandbox_probe_executor_source=child_executor_source,
    child_sandbox_probe_executor_source_sha256=(
        child_executor_source_sha256
    ),
    child_sandbox_probe_plan=child_sandbox_plan,
    child_sandbox_probe_report_reservation_bytes=(
        child_sandbox_reservation
    ),
)
class Ledger:
    def __init__(self): self.sequence = 0; self.maximum_record_bytes = 0
    def append(self, kind, record):
        encoded_bytes = len(canonical_json_bytes(record))
        assert encoded_bytes <= broker_audit_record_maximum_bytes(kind)
        self.maximum_record_bytes = max(self.maximum_record_bytes, encoded_bytes)
        self.sequence += 1
        return canonical_sha256({'sequence': self.sequence, 'kind': kind, 'record': record})
class Broker(TesseractBroker):
    def _watchdog_register_child(self, **kwargs):
        return ('1' * 64, '2' * 64, time.monotonic_ns())
    def _watchdog_bind_birth(self, birth_commitment, *, birth_ledger_row_sha256):
        return ('3' * 64, '4' * 64, time.monotonic_ns())
    def _watchdog_close_child(self, **kwargs):
        return None
worker, worker_peer = socket.socketpair()
watchdog, watchdog_peer = socket.socketpair()
broker = Broker(worker, FramedChannel(watchdog), config, Ledger())
broker.active = {
    'request_id': 'integration-q0001',
    'request_epoch': 2,
    'request_sequence': 1,
}
def scratch_inventory():
    now = time.monotonic_ns()
    mapping = {
        'schema_id': 'parser-broker-scratch-inventory-v1',
        'root_device': 1,
        'root_inode': 1,
        'root_mode': 0o700,
        'root_uid': os.getuid(),
        'entry_count': 0,
        'aggregate_bytes': 0,
        'empty': True,
        'scan_started_monotonic_ns': now,
        'scan_completed_monotonic_ns': now,
        'scan_sha256': canonical_sha256({'entries': []}),
    }
    mapping['record_sha256'] = canonical_sha256(mapping)
    return BrokerScratchInventory(**mapping)
broker_process = KernelProcessIdentity(
    pid=broker.identity.pid,
    start_abstime=broker.identity.start_abstime,
    ppid=broker.identity.ppid,
    pgid=broker.identity.pgid,
    sid=broker.identity.sid,
)
worker_pid = broker.identity.pid + 100000
worker_process = KernelProcessIdentity(
    pid=worker_pid,
    start_abstime=1,
    ppid=1,
    pgid=worker_pid,
    sid=worker_pid,
)
def quiescence(phase, sequences, completed, ledger_head):
    now = time.monotonic_ns()
    mapping = {
        'request_id': 'integration-q0001',
        'request_epoch': 2,
        'request_sequence': 1,
        'phase': phase,
        'worker_identity': dataclass_mapping(worker_process),
        'active_job_count': 0,
        'launched_spawn_sequences': list(sequences),
        'reaped_spawn_sequences': list(sequences),
        'wait4_echild': True,
        'broker_identity': dataclass_mapping(broker_process),
        'broker_group_members': [dataclass_mapping(broker_process)],
        'worker_group_members': [dataclass_mapping(worker_process)],
        'recursive_descendants': [],
        'protocol_pending_bytes': 0,
        'ledger_head_sha256': ledger_head,
        'completed_spawn_count': completed,
        'process_group_scan_complete': True,
        'admission_lock_held': True,
        'broker_armed_and_blocked': True,
        'worker_fork_denial_active': True,
        'broker_thread_count': 1,
        'broker_thread_inventory_sha256': canonical_sha256({'threads': [broker.identity.pid]}),
        'broker_thread_observed_at_monotonic_ns': now,
        'request_root_inventory': dataclass_mapping(scratch_inventory()),
        'observed_at_monotonic_ns': now,
    }
    mapping['observation_sha256'] = canonical_sha256(mapping)
    return BrokerQuiescenceReceipt(
        **{
            **mapping,
            'worker_identity': worker_process,
            'broker_identity': broker_process,
            'broker_group_members': (broker_process,),
            'worker_group_members': (worker_process,),
            'recursive_descendants': (),
            'launched_spawn_sequences': tuple(sequences),
            'reaped_spawn_sequences': tuple(sequences),
            'request_root_inventory': BrokerScratchInventory(
                **mapping['request_root_inventory']
            ),
        }
    )
begin_receipt = quiescence('begin', (), 0, '0' * 64)
if operation == 'version':
    argv = (staged, '--version')
    body = b''
elif operation == 'list_languages':
    argv = (staged, '--list-langs', '--tessdata-dir', tessdata)
    body = b''
else:
    argv = (staged, '-l', 'eng', '--tessdata-dir', tessdata, 'stdin', 'stdout')
    body = b'P1\n16 16\n' + (b'0 ' * 256) + b'\n'
birth, tombstone, stdout, stderr, timed_out, overflowed = broker._run_child(
    operation,
    argv,
    frozen_tesseract_environment(tessdata),
    body,
    time.monotonic_ns() + 20_000_000_000,
    'a' * 64,
    'separate',
)
end_receipt = quiescence(
    'end',
    (1,),
    1,
    tombstone.record_sha256,
)
issued = max(1, begin_receipt.observed_at_monotonic_ns - 1)
receipt_mapping = {
    'schema_id': BROKER_PROTOCOL_SCHEMA,
    'attempt_nonce_sha256': hashlib.sha256(config.attempt_nonce.encode('ascii')).hexdigest(),
    'scope_sha256': config.scope_sha256,
    'request_id': 'integration-q0001',
    'request_epoch': 2,
    'request_sequence': 1,
    'worker_thread_id': 1,
    'arm_capability_sha256': '9' * 64,
    'arm_issued_at_monotonic_ns': issued,
    'arm_consumed_at_monotonic_ns': issued,
    'arm_terminal_disposition': 'ended',
    'thread_transfer_required': False,
    'logical_phase': 'startup',
    'terminal_kind': 'end',
    'phase_deadline_monotonic_ns': config.attempt_deadline_ns,
    'binding_sha256': '8' * 64,
    'request_binding': None,
    'thread_claim_count': 0,
    'failure_reason_sha256': hashlib.sha256(b'').hexdigest(),
    'native_closure_sha256': closure['closure_sha256'],
    'native_closure': closure,
    'guard_python': dataclass_mapping(guard_python),
    'guard_python_path_custody': guard_python_path_custody,
    'guard_python_native_closure': guard_python_native_closure,
    'guard_python_module_tree_custody': guard_python_module_tree_custody,
    'guard_wrapper_source_hex': guard_wrapper_source.hex(),
    'guard_wrapper_source_sha256': hashlib.sha256(guard_wrapper_source).hexdigest(),
    'guard_wrapper_delivery_basis': 'execve-python-c-embedded-source-v1',
    'child_sandbox_probe_executor_authority': (
        'embedded-clt-python39-native-ctypes-seatbelt-probe-v1'
    ),
    'child_sandbox_probe_executor_source_hex': (
        child_executor_source.hex()
    ),
    'child_sandbox_probe_executor_source_sha256': (
        child_executor_source_sha256
    ),
    'child_sandbox_probe_plan': child_sandbox_plan,
    'child_sandbox_probe_report': dataclass_mapping(
        broker.child_sandbox_probe_report
    ),
    'child_sandbox_probe_representative_report_sha256': (
        broker.child_sandbox_probe_report.record_sha256
    ),
    'child_sandbox_probe_report_ledger_row_sha256': (
        broker.child_sandbox_probe_report_ledger_row_sha256
    ),
    'child_sandbox_probe_inheritance_count': 1,
    'child_sandbox_probe_inheritance_head_sha256': (
        __import__('app.services.tesseract_broker_protocol', fromlist=['child_sandbox_probe_phase_inheritance_head'])
        .child_sandbox_probe_phase_inheritance_head((birth,))[1]
    ),
    'begin': dataclass_mapping(begin_receipt),
    'thread_transfers': [],
    'births': [dataclass_mapping(birth)],
    'tombstones': [dataclass_mapping(tombstone)],
    'end': dataclass_mapping(end_receipt),
    'previous_receipt_sha256': '0' * 64,
}
receipt_mapping['receipt_sha256'] = canonical_sha256(receipt_mapping)
wire_receipt_mapping = json.loads(json.dumps(receipt_mapping))
receipt_wire_bytes = json.dumps(
    wire_receipt_mapping,
    sort_keys=True,
    separators=(',', ':'),
).encode('utf-8')
assert len(receipt_wire_bytes) <= 4 * 1024 * 1024
receipt = request_receipt_from_mapping(wire_receipt_mapping)
assert json.loads(json.dumps(dataclass_mapping(receipt))) == wire_receipt_mapping
receipt_manifest, receipt_blob, receipt_chunks = build_request_receipt_transport(
    receipt
)
assert request_receipt_from_blob(receipt_manifest, receipt_blob) == receipt
assert receipt_manifest.receipt_sha256 == receipt.receipt_sha256
assert receipt_manifest.chunk_count == len(receipt_chunks)
assert receipt_chunks[-1].commitment_sha256 == (
    receipt_manifest.terminal_chunk_commitment_sha256
)
transport_sender, transport_receiver = socket.socketpair()
sender_channel = FramedChannel(transport_sender)
receiver_channel = FramedChannel(transport_receiver)
sender_error = []
def send_receipt_chunks():
    try:
        send_request_receipt_chunks(
            sender_channel,
            receipt_manifest,
            receipt_blob,
            receipt_chunks,
        )
    except BaseException as exc:
        sender_error.append(exc)
sender_thread = threading.Thread(target=send_receipt_chunks)
sender_thread.start()
assert receive_request_receipt_chunks(
    receiver_channel,
    receipt_manifest,
) == receipt
sender_thread.join(5)
assert not sender_thread.is_alive()
assert not sender_error
sender_channel.close(); receiver_channel.close()
def rehash_child_chain(mutated):
    changed_birth = mutated['births'][0]
    changed_birth['record_sha256'] = canonical_sha256({
        key: value for key, value in changed_birth.items()
        if key != 'record_sha256'
    })
    changed_tombstone = mutated['tombstones'][0]
    changed_tombstone['previous_record_sha256'] = changed_birth['record_sha256']
    changed_tombstone['birth_record_sha256'] = changed_birth['record_sha256']
    changed_tombstone['record_sha256'] = canonical_sha256({
        key: value for key, value in changed_tombstone.items()
        if key != 'record_sha256'
    })
    mutated['end']['ledger_head_sha256'] = changed_tombstone['record_sha256']
    mutated['end']['observation_sha256'] = canonical_sha256({
        key: value for key, value in mutated['end'].items()
        if key != 'observation_sha256'
    })
    mutated['receipt_sha256'] = canonical_sha256({
        key: value for key, value in mutated.items()
        if key != 'receipt_sha256'
    })
    return mutated
def rejected(mutated):
    try:
        request_receipt_from_mapping(mutated)
    except BrokerProtocolError:
        return True
    return False

# Both child-clock and parent-clock gate orderings remain independently
# evaluable after a fully rehashed receipt mutation.
bad_child_clock = copy.deepcopy(wire_receipt_mapping)
bad_birth = bad_child_clock['births'][0]
bad_child_a = max(
    1,
    bad_birth['fork_denial']['applied_at_monotonic_ns'] - 1,
)
bad_release_record = {
    'schema_id': 'parser-tesseract-child-release-v1',
    'pid': bad_birth['pid'],
    'released_monotonic_ns': bad_child_a,
    'ready_record_sha256': bad_birth['child_ready_sha256'],
}
bad_release_sha = canonical_sha256(bad_release_record)
bad_birth['child_reported_guard_release_a_monotonic_ns'] = bad_child_a
bad_birth['child_guard_release_a_record_sha256'] = bad_release_sha
bad_birth['fork_denial']['child_reported_guard_release_a_monotonic_ns'] = bad_child_a
bad_birth['fork_denial']['child_guard_release_a_record_sha256'] = bad_release_sha
assert rejected(rehash_child_chain(bad_child_clock))

bad_parent_clock = copy.deepcopy(wire_receipt_mapping)
bad_birth = bad_parent_clock['births'][0]
bad_birth['guard_release_a_monotonic_ns'] = (
    bad_birth['registration_acknowledged_monotonic_ns'] - 1
)
assert rejected(rehash_child_chain(bad_parent_clock))

# Receipt validation reconstructs the exact root-owned ``-c`` argv from the
# retained source and capability descriptor numbers.
bad_guard_fd = copy.deepcopy(wire_receipt_mapping)
bad_guard_fd['births'][0]['guard_config_fd'] += 1000
bad_guard_fd['births'][0]['native_child_config_projection']['config_fd'] += 1000
bad_guard_fd['births'][0]['native_child_config_projection_sha256'] = canonical_sha256(
    bad_guard_fd['births'][0]['native_child_config_projection']
)
assert rejected(rehash_child_chain(bad_guard_fd))
bad_guard_source = copy.deepcopy(wire_receipt_mapping)
source_bytes = bytearray.fromhex(bad_guard_source['guard_wrapper_source_hex'])
source_bytes[0] ^= 1
bad_guard_source['guard_wrapper_source_hex'] = bytes(source_bytes).hex()
bad_guard_source['guard_wrapper_source_sha256'] = hashlib.sha256(
    source_bytes
).hexdigest()
bad_guard_source['receipt_sha256'] = canonical_sha256({
    key: value for key, value in bad_guard_source.items()
    if key != 'receipt_sha256'
})
assert rejected(bad_guard_source)

# A self-consistent structural scan mutation is still rejected by the outer
# receipt's exact frozen-closure replay.
bad_runtime = copy.deepcopy(wire_receipt_mapping)
bad_tombstone = bad_runtime['tombstones'][0]
bad_attestation = bad_tombstone['native_runtime_attestation']
bad_initial = bad_attestation['initial_scan']
changed_image = next(
    image for image in bad_initial['mapped_images']
    if image['system_image'] is False
)
changed_image['closure_image_sha256'] = 'a' * 64
changed_image['record_sha256'] = canonical_sha256({
    key: value for key, value in changed_image.items()
    if key != 'record_sha256'
})
bad_initial['record_sha256'] = canonical_sha256({
    key: value for key, value in bad_initial.items()
    if key != 'record_sha256'
})
for sample in bad_attestation['scan_samples']:
    full_scan = {
        key: value for key, value in bad_initial.items()
        if key != 'record_sha256'
    }
    full_scan.update({
        'bracket_started_monotonic_ns': sample['bracket_started_monotonic_ns'],
        'kernel_scan_started_monotonic_ns': sample['kernel_scan_started_monotonic_ns'],
        'kernel_scan_completed_monotonic_ns': sample['kernel_scan_completed_monotonic_ns'],
        'bracket_completed_monotonic_ns': sample['bracket_completed_monotonic_ns'],
        'total_region_count': sample['total_region_count'],
        'raw_kernel_inventory_sha256': sample['raw_kernel_inventory_sha256'],
    })
    sample['full_scan_record_sha256'] = canonical_sha256(full_scan)
    sample['record_sha256'] = canonical_sha256({
        key: value for key, value in sample.items()
        if key != 'record_sha256'
    })
bad_attestation['scan_log_sha256'] = canonical_sha256({
    'scan_samples': bad_attestation['scan_samples']
})
bad_attestation['record_sha256'] = canonical_sha256({
    key: value for key, value in bad_attestation.items()
    if key != 'record_sha256'
})
assert rejected(rehash_child_chain(bad_runtime))
post_wait_pid_safety = True
if operation == 'version':
    real_wait4 = broker_module.native_wait4_exact
    real_validate_closure = broker_module.validate_native_closure
    real_kill = os.kill
    reaped = False
    post_reap_wait_calls = []
    post_reap_kill_calls = []
    def spy_wait4(pid, *, absolute_deadline_ns):
        global reaped
        if reaped:
            post_reap_wait_calls.append(pid)
        result = real_wait4(
            pid,
            absolute_deadline_ns=absolute_deadline_ns,
        )
        if result is not None:
            reaped = True
        return result
    def spy_kill(pid, signal_number):
        if reaped:
            post_reap_kill_calls.append((pid, signal_number))
        return real_kill(pid, signal_number)
    def fail_after_wait4(_closure):
        raise RuntimeError('injected post-wait closure failure')
    broker_module.native_wait4_exact = spy_wait4
    broker_module.validate_native_closure = fail_after_wait4
    os.kill = spy_kill
    try:
        try:
            broker._run_child(
                'version',
                (staged, '--version'),
                frozen_tesseract_environment(tessdata),
                b'',
                time.monotonic_ns() + 20_000_000_000,
                'a' * 64,
                'separate',
            )
        except RuntimeError as exc:
            assert str(exc) == 'injected post-wait closure failure'
        else:
            raise AssertionError('post-wait failure injection did not fire')
    finally:
        broker_module.native_wait4_exact = real_wait4
        broker_module.validate_native_closure = real_validate_closure
        os.kill = real_kill
    assert reaped is True
    assert post_reap_kill_calls == []
    assert post_reap_wait_calls == []
print(json.dumps({
    'operation': operation,
    'birth_pid': birth.pid,
    'tombstone_pid': tombstone.pid,
    'exit_code': tombstone.exit_code,
    'timed_out': timed_out,
    'overflowed': overflowed,
    'terminal_wait4_reap_count': tombstone.terminal_wait4_reap_count,
    'scan_count': tombstone.native_runtime_attestation.scan_count,
    'post_continue_scan_count': tombstone.native_runtime_attestation.post_continue_scan_count,
    'stdout_sha256': hashlib.sha256(stdout).hexdigest(),
    'stderr_bytes': len(stderr),
    'receipt_roundtrip': True,
    'receipt_mutations_rejected': True,
    'post_wait_pid_safety': post_wait_pid_safety,
    'receipt_wire_bytes': len(receipt_wire_bytes),
    'receipt_sha256': receipt.receipt_sha256,
    'maximum_audit_record_bytes': broker.ledger.maximum_record_bytes,
}))
sandbox_directories.close()
sandbox_materialization.close()
os.close(sandbox_scratch_fd)
worker_peer.close(); watchdog_peer.close()
'''
    completed = subprocess.run(
        (
            sys.executable,
            "-c",
            script,
            source,
            staged,
            str(gate_source["resolved_path"]),
            str(gate_library["resolved_path"]),
            str(spawn_source),
            str(spawn_library),
            str(probe_library),
            str(tmp_path),
            operation,
            tessdata,
        ),
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=40.0,
        start_new_session=True,
    )
    assert completed.returncode == 0, completed.stderr
    result = __import__("json").loads(completed.stdout)
    assert result["operation"] == operation
    assert result["birth_pid"] == result["tombstone_pid"] > 0
    assert result["exit_code"] == 0
    assert result["timed_out"] is False
    assert result["overflowed"] is False
    assert result["terminal_wait4_reap_count"] == 1
    assert result["scan_count"] >= 2
    assert result["receipt_roundtrip"] is True
    assert result["receipt_mutations_rejected"] is True
    assert result["post_wait_pid_safety"] is True
    assert 0 < result["receipt_wire_bytes"] <= 4 * 1024 * 1024
    assert len(result["receipt_sha256"]) == 64
    assert 0 < result["maximum_audit_record_bytes"] <= 256 * 1024
