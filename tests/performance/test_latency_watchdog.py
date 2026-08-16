from __future__ import annotations

import ast
import json
import os
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import psutil
import pytest

from tests.benchmarks import latency_watchdog as watchdog


class FakeRuntime:
    def __init__(self, *, wall_time_ns: int | None = None) -> None:
        self.watchdog_pid = 300
        self.controller_pid = 100
        self.worker_pid = 200
        self.now_ns = 10_000_000_000
        self.wall_ns = time.time_ns() if wall_time_ns is None else wall_time_ns
        self.kills: list[tuple[int, int]] = []
        self.sleep_count = 0
        self.on_sleep: Callable[[FakeRuntime], None] | None = None
        self.kill_error: BaseException | None = None
        self.snapshot_error_pid: int | None = None
        self.snapshots: dict[int, watchdog.ProcessSnapshot | None] = {
            self.watchdog_pid: watchdog.ProcessSnapshot(
                pid=self.watchdog_pid,
                create_time_ns=3_000,
                parent_pid=self.controller_pid,
                process_group_id=self.watchdog_pid,
                session_id=self.watchdog_pid,
                terminal=False,
            ),
            self.controller_pid: watchdog.ProcessSnapshot(
                pid=self.controller_pid,
                create_time_ns=1_000,
                parent_pid=50,
                process_group_id=self.controller_pid,
                session_id=self.controller_pid,
                terminal=False,
            ),
            self.worker_pid: watchdog.ProcessSnapshot(
                pid=self.worker_pid,
                create_time_ns=2_000,
                parent_pid=self.controller_pid,
                process_group_id=self.worker_pid,
                session_id=self.worker_pid,
                terminal=False,
            ),
        }

    def current_pid(self) -> int:
        return self.watchdog_pid

    def current_parent_pid(self) -> int:
        return self.controller_pid

    def monotonic_ns(self) -> int:
        return self.now_ns

    def wall_time_ns(self) -> int:
        return self.wall_ns

    def sleep(self, seconds: float) -> None:
        elapsed_ns = int(seconds * 1_000_000_000)
        self.now_ns += elapsed_ns
        self.wall_ns += elapsed_ns
        self.sleep_count += 1
        if self.on_sleep is not None:
            self.on_sleep(self)

    def process_snapshot(self, pid: int) -> watchdog.ProcessSnapshot | None:
        if pid == self.snapshot_error_pid:
            raise RuntimeError("content-bearing diagnostic that must not escape")
        return self.snapshots.get(pid)

    def kill_process_group(self, process_group_id: int, signum: int) -> None:
        self.kills.append((process_group_id, signum))
        if self.kill_error is not None:
            raise self.kill_error
        worker = self.snapshots[self.worker_pid]
        assert worker is not None
        self.snapshots[self.worker_pid] = watchdog.ProcessSnapshot(
            pid=worker.pid,
            create_time_ns=worker.create_time_ns,
            parent_pid=worker.parent_pid,
            process_group_id=worker.process_group_id,
            session_id=worker.session_id,
            terminal=True,
        )


def _heartbeat(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "watchdog"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    path = root / "heartbeat"
    path.write_bytes(b"")
    path.chmod(0o600)
    return root.resolve(), path.resolve(), (root / "ready").absolute()


def _config(
    root: Path,
    path: Path,
    ready: Path,
    **updates: object,
) -> watchdog.WatchdogConfig:
    values: dict[str, object] = {
        "controller_pid": 100,
        "controller_create_time_ns": 1_000,
        "worker_pid": 200,
        "worker_create_time_ns": 2_000,
        "worker_pgid": 200,
        "heartbeat_root": root,
        "heartbeat_path": path,
        "ready_path": ready,
    }
    values.update(updates)
    return watchdog.WatchdogConfig(**values)  # type: ignore[arg-type]


def _set_mtime(path: Path, value_ns: int) -> None:
    os.utime(path, ns=(value_ns, value_ns), follow_symlinks=False)


def test_normal_worker_exit_never_signals(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    root, path, ready = _heartbeat(tmp_path)
    _set_mtime(path, runtime.wall_ns)

    def finish_worker(fake: FakeRuntime) -> None:
        fake.snapshots[fake.worker_pid] = None

    runtime.on_sleep = finish_worker
    result = watchdog.run_watchdog(_config(root, path, ready), runtime=runtime)

    assert result.exit_code is watchdog.WatchdogExitCode.WORKER_EXITED
    assert runtime.kills == []
    assert result.worker_kill_attempted is False
    assert result.worker_kill_confirmed is False
    assert ready.read_bytes() == b"READY\n"
    assert stat.S_IMODE(ready.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        ("dead", watchdog.WatchdogExitCode.CONTROLLER_DEAD_TERMINATED),
        ("reused", watchdog.WatchdogExitCode.CONTROLLER_REUSED_TERMINATED),
    ],
)
def test_dead_or_reused_controller_kills_only_bound_worker_group(
    tmp_path: Path,
    failure: str,
    expected_code: watchdog.WatchdogExitCode,
) -> None:
    runtime = FakeRuntime()
    root, path, ready = _heartbeat(tmp_path)
    _set_mtime(path, runtime.wall_ns)

    def break_controller(fake: FakeRuntime) -> None:
        if failure == "dead":
            fake.snapshots[fake.controller_pid] = None
        else:
            controller = fake.snapshots[fake.controller_pid]
            assert controller is not None
            fake.snapshots[fake.controller_pid] = watchdog.ProcessSnapshot(
                pid=controller.pid,
                create_time_ns=controller.create_time_ns + 1,
                parent_pid=controller.parent_pid,
                process_group_id=controller.process_group_id,
                session_id=controller.session_id,
                terminal=False,
            )

    runtime.on_sleep = break_controller
    result = watchdog.run_watchdog(_config(root, path, ready), runtime=runtime)

    assert result.exit_code is expected_code
    assert runtime.kills == [(runtime.worker_pid, signal.SIGKILL)]
    assert result.worker_kill_attempted is True
    assert result.worker_kill_confirmed is True


def test_initially_stale_heartbeat_kills_bound_worker(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    root, path, ready = _heartbeat(tmp_path)
    _set_mtime(path, runtime.wall_ns - watchdog.LEASE_NS - 1)

    result = watchdog.run_watchdog(_config(root, path, ready), runtime=runtime)

    assert result.exit_code is watchdog.WatchdogExitCode.HEARTBEAT_STALE_TERMINATED
    assert runtime.kills == [(runtime.worker_pid, signal.SIGKILL)]
    assert not ready.exists()


def test_heartbeat_that_stops_after_ready_kills_bound_worker(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    root, path, ready = _heartbeat(tmp_path)
    _set_mtime(path, runtime.wall_ns)

    def jump_past_lease(fake: FakeRuntime) -> None:
        fake.now_ns += watchdog.LEASE_NS
        fake.wall_ns += watchdog.LEASE_NS

    runtime.on_sleep = jump_past_lease
    result = watchdog.run_watchdog(_config(root, path, ready), runtime=runtime)

    assert result.exit_code is watchdog.WatchdogExitCode.HEARTBEAT_STALE_TERMINATED
    assert runtime.kills == [(runtime.worker_pid, signal.SIGKILL)]
    assert ready.read_bytes() == b"READY\n"


def test_heartbeat_advancement_extends_lease_without_changing_inode(
    tmp_path: Path,
) -> None:
    runtime = FakeRuntime()
    root, path, ready = _heartbeat(tmp_path)
    _set_mtime(path, runtime.wall_ns)

    def advance_then_finish(fake: FakeRuntime) -> None:
        _set_mtime(path, fake.wall_ns)
        if fake.sleep_count == 3:
            fake.snapshots[fake.worker_pid] = None

    runtime.on_sleep = advance_then_finish
    result = watchdog.run_watchdog(_config(root, path, ready), runtime=runtime)

    assert result.exit_code is watchdog.WatchdogExitCode.WORKER_EXITED
    assert runtime.kills == []


def test_replaced_heartbeat_fails_closed_after_binding(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    root, path, ready = _heartbeat(tmp_path)
    _set_mtime(path, runtime.wall_ns)

    def replace(fake: FakeRuntime) -> None:
        path.unlink()
        path.write_bytes(b"")
        path.chmod(0o600)
        _set_mtime(path, fake.wall_ns)

    runtime.on_sleep = replace
    result = watchdog.run_watchdog(_config(root, path, ready), runtime=runtime)

    assert result.exit_code is watchdog.WatchdogExitCode.HEARTBEAT_INVALID_TERMINATED
    assert runtime.kills == [(runtime.worker_pid, signal.SIGKILL)]


def test_worker_pid_reuse_is_never_signalled(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    root, path, ready = _heartbeat(tmp_path)
    _set_mtime(path, runtime.wall_ns)

    def reuse_worker(fake: FakeRuntime) -> None:
        worker = fake.snapshots[fake.worker_pid]
        assert worker is not None
        fake.snapshots[fake.worker_pid] = watchdog.ProcessSnapshot(
            pid=worker.pid,
            create_time_ns=worker.create_time_ns + 1,
            parent_pid=1,
            process_group_id=worker.process_group_id,
            session_id=worker.session_id,
            terminal=False,
        )

    runtime.on_sleep = reuse_worker
    result = watchdog.run_watchdog(_config(root, path, ready), runtime=runtime)

    assert result.exit_code is watchdog.WatchdogExitCode.WORKER_REUSED
    assert runtime.kills == []


@pytest.mark.parametrize("drift_field", ["process_group_id", "session_id"])
def test_worker_group_or_session_drift_is_never_signalled(
    tmp_path: Path,
    drift_field: str,
) -> None:
    runtime = FakeRuntime()
    root, path, ready = _heartbeat(tmp_path)
    _set_mtime(path, runtime.wall_ns)

    def drift_worker(fake: FakeRuntime) -> None:
        worker = fake.snapshots[fake.worker_pid]
        assert worker is not None
        values = {
            "pid": worker.pid,
            "create_time_ns": worker.create_time_ns,
            "parent_pid": worker.parent_pid,
            "process_group_id": worker.process_group_id,
            "session_id": worker.session_id,
            "terminal": False,
        }
        values[drift_field] = worker.pid + 1
        fake.snapshots[fake.worker_pid] = watchdog.ProcessSnapshot(**values)

    runtime.on_sleep = drift_worker
    result = watchdog.run_watchdog(_config(root, path, ready), runtime=runtime)

    assert result.exit_code is watchdog.WatchdogExitCode.WORKER_GROUP_DRIFT
    assert runtime.kills == []


def test_signal_request_fails_closed_on_exact_worker(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    root, path, ready = _heartbeat(tmp_path)
    _set_mtime(path, runtime.wall_ns)

    result = watchdog.run_watchdog(
        _config(root, path, ready),
        runtime=runtime,
        stop_requested=lambda: True,
    )

    assert result.exit_code is watchdog.WatchdogExitCode.SIGNAL_TERMINATED
    assert runtime.kills == [(runtime.worker_pid, signal.SIGKILL)]


def test_kill_error_is_bounded_and_unconfirmed(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    runtime.kill_error = PermissionError("must not escape")
    root, path, ready = _heartbeat(tmp_path)
    _set_mtime(path, runtime.wall_ns - watchdog.LEASE_NS - 1)

    result = watchdog.run_watchdog(_config(root, path, ready), runtime=runtime)

    assert result.exit_code is watchdog.WatchdogExitCode.TERMINATION_UNCONFIRMED
    evidence = json.loads(result.evidence_bytes())
    assert "must not escape" not in json.dumps(evidence)
    assert evidence["worker_kill_attempted"] is True
    assert evidence["worker_kill_confirmed"] is False


def test_unexpected_runtime_error_after_binding_fails_closed_without_leakage(
    tmp_path: Path,
) -> None:
    runtime = FakeRuntime()
    root, path, ready = _heartbeat(tmp_path)
    _set_mtime(path, runtime.wall_ns)

    def fail_controller_probe(fake: FakeRuntime) -> None:
        fake.snapshot_error_pid = fake.controller_pid

    runtime.on_sleep = fail_controller_probe
    result = watchdog.run_watchdog(_config(root, path, ready), runtime=runtime)

    assert result.exit_code is watchdog.WatchdogExitCode.INTERNAL_ERROR_TERMINATED
    assert runtime.kills == [(runtime.worker_pid, signal.SIGKILL)]
    assert b"diagnostic" not in result.evidence_bytes()


def test_fixed_runtime_limit_fails_closed(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    root, path, ready = _heartbeat(tmp_path)
    _set_mtime(path, runtime.wall_ns)

    def cross_runtime_limit(fake: FakeRuntime) -> None:
        fake.now_ns += watchdog.MAXIMUM_RUNTIME_NS
        fake.wall_ns += watchdog.MAXIMUM_RUNTIME_NS
        _set_mtime(path, fake.wall_ns)

    runtime.on_sleep = cross_runtime_limit
    result = watchdog.run_watchdog(_config(root, path, ready), runtime=runtime)

    assert result.exit_code is watchdog.WatchdogExitCode.RUNTIME_LIMIT_TERMINATED
    assert runtime.kills == [(runtime.worker_pid, signal.SIGKILL)]


@pytest.mark.parametrize(
    "updates",
    [
        {"controller_pid": 0},
        {"worker_pid": 100, "worker_pgid": 100},
        {"worker_pgid": 201},
        {"lease_ns": watchdog.LEASE_NS + 1},
        {"poll_interval_seconds": 0.001},
        {"maximum_runtime_ns": watchdog.MAXIMUM_RUNTIME_NS + 1},
    ],
)
def test_invalid_control_values_never_signal(
    tmp_path: Path,
    updates: dict[str, object],
) -> None:
    runtime = FakeRuntime()
    root, path, ready = _heartbeat(tmp_path)
    result = watchdog.run_watchdog(
        _config(root, path, ready, **updates),
        runtime=runtime,
    )

    assert result.exit_code is watchdog.WatchdogExitCode.INVALID_CONTROL_INPUT
    assert runtime.kills == []


def test_heartbeat_must_be_absolute_and_contained(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    root, path, ready = _heartbeat(tmp_path)
    outside = tmp_path / "outside"
    outside.write_bytes(b"")

    relative = watchdog.run_watchdog(
        _config(root, Path("heartbeat"), ready),
        runtime=runtime,
    )
    escaped = watchdog.run_watchdog(
        _config(root, outside.resolve(), ready),
        runtime=runtime,
    )

    assert relative.exit_code is watchdog.WatchdogExitCode.INVALID_CONTROL_INPUT
    assert escaped.exit_code is watchdog.WatchdogExitCode.INVALID_CONTROL_INPUT
    assert runtime.kills == []


def test_symlink_and_unsafe_mode_are_rejected_before_process_binding(
    tmp_path: Path,
) -> None:
    runtime = FakeRuntime()
    root, path, ready = _heartbeat(tmp_path)
    target = root / "target"
    target.write_bytes(b"")
    link = root / "link"
    link.symlink_to(target)

    linked = watchdog.run_watchdog(
        _config(root, link.absolute(), ready), runtime=runtime
    )
    assert linked.exit_code is watchdog.WatchdogExitCode.HEARTBEAT_INVALID_AT_BIND

    path.chmod(0o666)
    unsafe = watchdog.run_watchdog(_config(root, path, ready), runtime=runtime)
    assert unsafe.exit_code is watchdog.WatchdogExitCode.HEARTBEAT_INVALID_AT_BIND
    assert runtime.kills == []


def test_preexisting_or_escaped_ready_marker_is_rejected_without_signal(
    tmp_path: Path,
) -> None:
    runtime = FakeRuntime()
    root, path, ready = _heartbeat(tmp_path)
    ready.write_bytes(b"stale")
    ready.chmod(0o600)

    preexisting = watchdog.run_watchdog(
        _config(root, path, ready),
        runtime=runtime,
    )
    escaped = watchdog.run_watchdog(
        _config(root, path, (tmp_path / "outside-ready").resolve()),
        runtime=runtime,
    )

    assert preexisting.exit_code is watchdog.WatchdogExitCode.HEARTBEAT_INVALID_AT_BIND
    assert escaped.exit_code is watchdog.WatchdogExitCode.INVALID_CONTROL_INPUT
    assert runtime.kills == []


def test_private_session_and_direct_parent_are_required(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    root, path, ready = _heartbeat(tmp_path)
    current = runtime.snapshots[runtime.watchdog_pid]
    assert current is not None
    runtime.snapshots[runtime.watchdog_pid] = watchdog.ProcessSnapshot(
        pid=current.pid,
        create_time_ns=current.create_time_ns,
        parent_pid=current.parent_pid,
        process_group_id=999,
        session_id=999,
        terminal=False,
    )
    result = watchdog.run_watchdog(_config(root, path, ready), runtime=runtime)
    assert result.exit_code is watchdog.WatchdogExitCode.PRIVATE_SESSION_REQUIRED
    assert runtime.kills == []

    runtime = FakeRuntime()
    worker = runtime.snapshots[runtime.worker_pid]
    assert worker is not None
    runtime.snapshots[runtime.worker_pid] = watchdog.ProcessSnapshot(
        pid=worker.pid,
        create_time_ns=worker.create_time_ns,
        parent_pid=999,
        process_group_id=worker.process_group_id,
        session_id=worker.session_id,
        terminal=False,
    )
    result = watchdog.run_watchdog(_config(root, path, ready), runtime=runtime)
    assert result.exit_code is watchdog.WatchdogExitCode.WORKER_IDENTITY_REJECTED
    assert runtime.kills == []


def test_content_free_evidence_and_environment_are_strictly_bounded(
    tmp_path: Path,
) -> None:
    secret = "watchdog-secret-value"
    result = watchdog._result(  # noqa: SLF001 - exact evidence contract
        watchdog.WatchdogOutcome.WORKER_EXITED,
        watchdog.WatchdogExitCode.WORKER_EXITED,
    )
    encoded = result.evidence_bytes()
    payload = json.loads(encoded)

    assert len(encoded) <= watchdog.MAXIMUM_EVIDENCE_BYTES
    assert set(payload) == {
        "exit_code",
        "outcome",
        "schema_id",
        "worker_kill_attempted",
        "worker_kill_confirmed",
    }
    assert secret not in encoded.decode()
    assert str(tmp_path) not in encoded.decode()
    assert watchdog.sanitized_watchdog_environment({"TOKEN": secret}) == {
        "PATH": os.defpath,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }


def test_module_has_no_app_or_network_surface() -> None:
    source_path = Path(watchdog.__file__).resolve()
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    assert "app" not in imported_roots
    assert imported_roots.isdisjoint(
        {"http", "httpx", "requests", "socket", "urllib", "websockets"}
    )
    assert "subprocess" not in imported_roots
    assert "app." not in source


def test_command_uses_isolated_interpreter_and_contains_exact_control_values(
    tmp_path: Path,
) -> None:
    root, path, ready = _heartbeat(tmp_path)
    command = watchdog.build_watchdog_command(
        python_executable=sys.executable,
        controller_pid=101,
        controller_create_time_ns=102,
        worker_pid=201,
        worker_create_time_ns=202,
        worker_pgid=201,
        heartbeat_root=root,
        heartbeat_path=path,
        ready_path=ready,
    )

    assert command[:2] == (sys.executable, "-I")
    assert Path(command[2]).resolve() == Path(watchdog.__file__).resolve()
    assert command[-6:] == (
        "--heartbeat-root",
        str(root),
        "--heartbeat",
        str(path),
        "--ready",
        str(ready),
    )


def test_malformed_cli_is_content_free_and_uses_stable_exit_code() -> None:
    secret = "credential-that-must-not-escape"
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            str(Path(watchdog.__file__).resolve()),
            "--controller-pid",
            secret,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=watchdog.sanitized_watchdog_environment({"SECRET": secret}),
        timeout=5,
        check=False,
    )

    assert completed.returncode == watchdog.WatchdogExitCode.INVALID_CONTROL_INPUT
    assert completed.stderr == b""
    assert secret.encode() not in completed.stdout
    assert json.loads(completed.stdout) == {
        "exit_code": int(watchdog.WatchdogExitCode.INVALID_CONTROL_INPUT),
        "outcome": "invalid_control_input",
        "schema_id": watchdog.SCHEMA_ID,
        "worker_kill_attempted": False,
        "worker_kill_confirmed": False,
    }


def _process_identity(pid: int) -> tuple[int, int, int]:
    process = psutil.Process(pid)
    return (
        int(process.create_time() * 1_000_000_000),
        os.getpgid(pid),
        os.getsid(pid),
    )


def _wait_exact_process_gone(pid: int, create_time_ns: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            observed, _pgid, _sid = _process_identity(pid)
            status = psutil.Process(pid).status()
        except (ProcessLookupError, psutil.NoSuchProcess, psutil.ZombieProcess):
            return True
        if observed != create_time_ns or status in {
            psutil.STATUS_DEAD,
            psutil.STATUS_ZOMBIE,
        }:
            return True
        time.sleep(0.025)
    return False


def test_real_normal_worker_exit_leaves_no_watchdog_or_worker(tmp_path: Path) -> None:
    root, path, ready = _heartbeat(tmp_path)
    controller_pid = os.getpid()
    controller_create_ns, controller_pgid, _controller_sid = _process_identity(
        controller_pid
    )
    worker = subprocess.Popen(
        [sys.executable, "-I", "-c", "import time; time.sleep(0.25)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    worker_create_ns, worker_pgid, worker_sid = _process_identity(worker.pid)
    assert worker_pgid == worker.pid == worker_sid
    assert worker_pgid not in {os.getpgrp(), controller_pgid}
    command = watchdog.build_watchdog_command(
        python_executable=sys.executable,
        controller_pid=controller_pid,
        controller_create_time_ns=controller_create_ns,
        worker_pid=worker.pid,
        worker_create_time_ns=worker_create_ns,
        worker_pgid=worker_pgid,
        heartbeat_root=root,
        heartbeat_path=path,
        ready_path=ready,
    )
    observer = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=watchdog.sanitized_watchdog_environment(),
        start_new_session=True,
        close_fds=True,
    )
    try:
        while observer.poll() is None and worker.poll() is None:
            path.touch()
            time.sleep(0.025)
        stdout, stderr = observer.communicate(timeout=5)
        assert stderr == b""
        assert observer.returncode == watchdog.WatchdogExitCode.WORKER_EXITED
        assert json.loads(stdout)["outcome"] == "worker_exited"
        assert worker.wait(timeout=2) == 0
        assert _wait_exact_process_gone(worker.pid, worker_create_ns, 2)
        assert _wait_exact_process_gone(
            observer.pid,
            _process_identity(observer.pid)[0]
            if psutil.pid_exists(observer.pid)
            else 1,
            2,
        )
    finally:
        if observer.poll() is None:
            observer.terminate()
            observer.wait(timeout=2)
        if worker.poll() is None:
            current_create_ns, current_pgid, current_sid = _process_identity(worker.pid)
            if (
                current_create_ns == worker_create_ns
                and current_pgid == worker.pid == current_sid
                and current_pgid not in {os.getpgrp(), controller_pgid}
            ):
                os.killpg(current_pgid, signal.SIGKILL)
            worker.wait(timeout=2)


def _safe_kill_disposable_group(
    *,
    pid: int,
    create_time_ns: int,
    forbidden_groups: set[int],
) -> None:
    try:
        observed_create_ns, process_group_id, session_id = _process_identity(pid)
    except (ProcessLookupError, psutil.NoSuchProcess, psutil.ZombieProcess):
        return
    if (
        observed_create_ns == create_time_ns
        and pid == process_group_id == session_id
        and process_group_id not in forbidden_groups
    ):
        os.killpg(process_group_id, signal.SIGKILL)


def test_real_abrupt_controller_death_kills_only_disposable_worker_group(
    tmp_path: Path,
) -> None:
    protocol_root = (tmp_path / "abrupt-controller").resolve()
    protocol_root.mkdir(mode=0o700)
    protocol_root.chmod(0o700)
    state_path = protocol_root / "state.json"
    release_path = protocol_root / "release"
    result_path = protocol_root / "result.json"
    controller_code = r'''
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import psutil

root = Path(sys.argv[1]).resolve()
watchdog_script = Path(sys.argv[2]).resolve()
heartbeat = root / "heartbeat"
ready = root / "ready"
go = root / "go"
state = root / "state.json"
release = root / "release"
result = root / "result.json"
heartbeat.write_bytes(b"")
heartbeat.chmod(0o600)
controller = psutil.Process(os.getpid())
controller_create_ns = int(controller.create_time() * 1_000_000_000)
worker_code = (
    "import time,sys; from pathlib import Path; p=Path(sys.argv[1]); "
    "\nwhile not p.exists(): time.sleep(0.01)\ntime.sleep(60)"
)
worker = subprocess.Popen(
    [sys.executable, "-I", "-c", worker_code, str(go)],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    start_new_session=True,
    close_fds=True,
)
worker_process = psutil.Process(worker.pid)
worker_create_ns = int(worker_process.create_time() * 1_000_000_000)
worker_pgid = os.getpgid(worker.pid)
worker_sid = os.getsid(worker.pid)
command = [
    sys.executable,
    "-I",
    str(watchdog_script),
    "--controller-pid",
    str(os.getpid()),
    "--controller-create-time-ns",
    str(controller_create_ns),
    "--worker-pid",
    str(worker.pid),
    "--worker-create-time-ns",
    str(worker_create_ns),
    "--worker-pgid",
    str(worker_pgid),
    "--heartbeat-root",
    str(root),
    "--heartbeat",
    str(heartbeat),
    "--ready",
    str(ready),
]
watchdog_env = {
    "PATH": os.defpath,
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONNOUSERSITE": "1",
}
with result.open("wb") as result_stream:
    observer = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=result_stream,
        stderr=subprocess.DEVNULL,
        env=watchdog_env,
        start_new_session=True,
        close_fds=True,
    )
observer_process = psutil.Process(observer.pid)
observer_create_ns = int(observer_process.create_time() * 1_000_000_000)
deadline = time.monotonic() + 5
while not ready.exists() and time.monotonic() < deadline:
    heartbeat.touch()
    if worker.poll() is not None or observer.poll() is not None:
        raise SystemExit(71)
    time.sleep(0.025)
if not ready.exists():
    raise SystemExit(72)
ready_stat = ready.lstat()
if (
    ready.is_symlink()
    or not stat.S_ISREG(ready_stat.st_mode)
    or stat.S_IMODE(ready_stat.st_mode) != 0o600
    or ready.read_bytes() != b"READY\n"
):
    raise SystemExit(73)
go_fd = os.open(go, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
os.close(go_fd)
payload = {
    "controller": [
        os.getpid(),
        controller_create_ns,
        os.getpgid(os.getpid()),
        os.getsid(os.getpid()),
    ],
    "worker": [worker.pid, worker_create_ns, worker_pgid, worker_sid],
    "observer": [
        observer.pid,
        observer_create_ns,
        os.getpgid(observer.pid),
        os.getsid(observer.pid),
    ],
}
temporary_state = root / "state.tmp"
temporary_state.write_text(json.dumps(payload), encoding="ascii")
os.replace(temporary_state, state)
while not release.exists():
    heartbeat.touch()
    if worker.poll() is not None or observer.poll() is not None:
        raise SystemExit(74)
    time.sleep(0.025)
heartbeat.touch()
os._exit(0)
'''
    controller = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-c",
            controller_code,
            str(protocol_root),
            str(Path(watchdog.__file__).resolve()),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
        close_fds=True,
    )
    identities: dict[str, list[int]] = {}
    own_group = os.getpgrp()
    own_session = os.getsid(0)
    forbidden_groups = {own_group, own_session}
    try:
        deadline = time.monotonic() + 8
        while not state_path.exists() and time.monotonic() < deadline:
            if controller.poll() is not None:
                break
            time.sleep(0.025)
        assert state_path.is_file(), controller.stderr.read().decode(
            "utf-8", errors="replace"
        )
        identities = json.loads(state_path.read_text(encoding="ascii"))
        controller_identity = identities["controller"]
        worker_identity = identities["worker"]
        observer_identity = identities["observer"]

        assert controller_identity[0] == controller.pid
        for pid, create_time_ns, process_group_id, session_id in identities.values():
            assert _process_identity(pid) == (
                create_time_ns,
                process_group_id,
                session_id,
            )
            assert pid == process_group_id == session_id
            assert process_group_id not in forbidden_groups
        assert len({entry[2] for entry in identities.values()}) == 3
        assert psutil.Process(worker_identity[0]).ppid() == controller.pid
        assert psutil.Process(observer_identity[0]).ppid() == controller.pid
        assert (protocol_root / "ready").read_bytes() == b"READY\n"

        release_path.write_bytes(b"")
        assert controller.wait(timeout=5) == 0
        assert _wait_exact_process_gone(
            worker_identity[0], worker_identity[1], timeout=5
        )
        assert _wait_exact_process_gone(
            observer_identity[0], observer_identity[1], timeout=5
        )

        deadline = time.monotonic() + 5
        while (
            (not result_path.exists() or result_path.stat().st_size == 0)
            and time.monotonic() < deadline
        ):
            time.sleep(0.025)
        evidence = json.loads(result_path.read_bytes())
        assert evidence == {
            "exit_code": int(watchdog.WatchdogExitCode.CONTROLLER_DEAD_TERMINATED),
            "outcome": "controller_dead_worker_terminated",
            "schema_id": watchdog.SCHEMA_ID,
            "worker_kill_attempted": True,
            "worker_kill_confirmed": True,
        }
    finally:
        if controller.poll() is None:
            controller_create_ns, controller_pgid, controller_sid = _process_identity(
                controller.pid
            )
            if (
                controller.pid == controller_pgid == controller_sid
                and controller_pgid not in forbidden_groups
            ):
                os.killpg(controller_pgid, signal.SIGKILL)
            controller.wait(timeout=3)
        for key in ("observer", "worker"):
            identity = identities.get(key)
            if identity:
                _safe_kill_disposable_group(
                    pid=identity[0],
                    create_time_ns=identity[1],
                    forbidden_groups=forbidden_groups,
                )
