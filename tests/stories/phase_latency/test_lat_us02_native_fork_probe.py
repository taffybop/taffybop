from __future__ import annotations

import hashlib
import ctypes
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time

import pytest

from app.services.tesseract_broker import TesseractBroker
from app.services.tesseract_broker_protocol import (
    native_child_limit_ack_sha256,
)


SOURCE = (
    Path(__file__).parents[3]
    / "app"
    / "services"
    / "parser_fork_denial_probe.c"
)
SPAWN_SOURCE = SOURCE.with_name("tesseract_broker_spawn.c")


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin RLIMIT custody")
def test_native_probe_denies_fork_vfork_and_posix_spawn_without_python_child(
    tmp_path: Path,
) -> None:
    library = tmp_path / "parser_fork_denial_probe.dylib"
    subprocess.run(
        (
            "/usr/bin/clang",
            "-dynamiclib",
            "-Os",
            "-fvisibility=hidden",
            "-o",
            str(library),
            str(SOURCE),
        ),
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    observed = library.lstat()
    assert stat.S_ISREG(observed.st_mode)
    assert not library.is_symlink()
    assert hashlib.sha256(library.read_bytes()).hexdigest()

    script = """
import ctypes, json, resource, sys
resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
library = ctypes.CDLL(sys.argv[1], use_errno=True)
import_probe = library.parser_probe_import_time_fork_errno
import_probe.argtypes = ()
import_probe.restype = ctypes.c_int
probe = library.parser_probe_process_birth
probe.argtypes = (ctypes.c_int, ctypes.c_char_p)
probe.restype = ctypes.c_int
print(json.dumps({
    'import': int(import_probe()),
    'calls': [int(probe(code, b'/usr/bin/true')) for code in (1, 2, 3)],
}))
"""
    completed = subprocess.run(
        (sys.executable, "-c", script, str(library)),
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10.0,
    )
    errors = json.loads(completed.stdout)
    assert errors["import"] in {1, 35}
    assert errors["calls"] and all(
        value in {1, 35} for value in errors["calls"]
    )


def test_native_probe_source_keeps_vfork_child_inside_native_exit_path() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "__attribute__((constructor))" in source
    assert "parser_probe_import_time_fork" in source
    assert "parser_probe_import_time_fork_errno" in source
    assert "pid = vfork();" in source
    assert "if (pid == 0)" in source
    assert "_exit(127);" in source
    assert "waitpid(pid" in source
    assert "libffi" in source


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin broker fork custody")
def test_native_broker_fork_installs_limit_before_python_and_skips_atfork(
    tmp_path: Path,
) -> None:
    library = tmp_path / "tesseract_broker_spawn.dylib"
    subprocess.run(
        (
            "/usr/bin/clang",
            "-dynamiclib",
            "-Os",
            "-fvisibility=hidden",
            "-o",
            str(library),
            str(SPAWN_SOURCE),
        ),
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    script = r"""
import ctypes, errno, json, os, resource, signal, sys
library = ctypes.CDLL(sys.argv[1], use_errno=True)
fork = library.parser_broker_raw_fork_probe_child_denied
fork.argtypes = (ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_uint64), ctypes.c_int, ctypes.c_int)
fork.restype = ctypes.c_int64
install = library.parser_broker_install_adversarial_atfork_probe
install.argtypes = ()
install.restype = ctypes.c_int
calls = library.parser_broker_adversarial_atfork_child_calls
calls.argtypes = ()
calls.restype = ctypes.c_int
signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGTERM, signal.SIGHUP})
failure = ctypes.c_int()
failure_time = ctypes.c_uint64()
failure_reader, failure_writer = os.pipe()
failure_ack_reader, failure_ack_writer = os.pipe()
ctypes.set_errno(0)
assert int(fork(ctypes.byref(failure), ctypes.byref(failure_time), failure_reader, failure_ack_writer)) == -1
assert ctypes.get_errno() == errno.EPERM
assert failure_time.value == 0
os.close(failure_reader)
os.close(failure_writer)
os.close(failure_ack_reader)
os.close(failure_ack_writer)
assert install() == 0
release_reader, release_writer = os.pipe()
result_reader, result_writer = os.pipe()
ack_reader, ack_writer = os.pipe()
old = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGHUP})
child_errno = ctypes.c_int()
applied = ctypes.c_uint64()
pid = int(fork(ctypes.byref(child_errno), ctypes.byref(applied), release_reader, ack_writer))
if pid == 0:
    os.close(ack_reader)
    os.close(release_reader)
    os.close(release_writer)
    os.close(result_reader)
    body = json.dumps({
        'limits': list(resource.getrlimit(resource.RLIMIT_NPROC)),
        'applied': int(applied.value),
        'atfork_calls': int(calls()),
        'child_errno': int(child_errno.value),
    }).encode('ascii')
    os.write(result_writer, body)
    os._exit(0)
signal.pthread_sigmask(signal.SIG_SETMASK, old)
os.close(ack_writer)
os.close(release_reader)
os.close(result_writer)
ack = b''
while len(ack) < 40:
    chunk = os.read(ack_reader, 40 - len(ack))
    assert chunk
    ack += chunk
assert os.read(ack_reader, 1) == b''
os.close(ack_reader)
os.write(release_writer, b'N')
os.close(release_writer)
body = os.read(result_reader, 4096)
os.close(result_reader)
waited, status = os.waitpid(pid, 0)
print(json.dumps({
    'pid': pid,
    'waited': waited,
    'status': status,
    'parent_applied': int(applied.value),
    'ack_magic': ack[:8].decode('ascii'),
    'ack_pid': int.from_bytes(ack[8:16], 'big'),
    'ack_applied': int.from_bytes(ack[16:24], 'big'),
    'ack_soft': int.from_bytes(ack[24:32], 'big'),
    'ack_hard': int.from_bytes(ack[32:40], 'big'),
    'child': json.loads(body),
}))
"""
    completed = subprocess.run(
        (sys.executable, "-c", script, str(library)),
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10.0,
    )
    record = json.loads(completed.stdout)
    assert record["pid"] == record["waited"] > 0
    assert record["status"] == 0
    assert record["parent_applied"] == 0
    assert record["ack_magic"] == "PN0ACK1!"
    assert record["ack_pid"] == record["pid"]
    assert record["ack_applied"] == record["child"]["applied"] > 0
    assert (record["ack_soft"], record["ack_hard"]) == (0, 0)
    assert record["child"] == {
        "limits": [0, 0],
        "applied": record["child"]["applied"],
        "atfork_calls": 0,
        "child_errno": 0,
    }
    assert record["child"]["applied"] > 0


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin broker fork custody")
def test_broker_waits_for_delayed_native_limit_ack_before_parent_custody(
    tmp_path: Path,
) -> None:
    library_path = tmp_path / "tesseract_broker_spawn-delayed.dylib"
    subprocess.run(
        (
            "/usr/bin/clang",
            "-dynamiclib",
            "-Os",
            "-fvisibility=hidden",
            "-DPARSER_BROKER_TEST_CHILD_ACK_DELAY_NS=150000000",
            "-o",
            str(library_path),
            str(SPAWN_SOURCE),
        ),
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    library = ctypes.CDLL(str(library_path), use_errno=True)
    fork = library.parser_broker_raw_fork_probe_child_denied
    fork.argtypes = (
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.c_int,
        ctypes.c_int,
    )
    fork.restype = ctypes.c_int64
    broker = TesseractBroker.__new__(TesseractBroker)
    broker._native_fork_child_denied = fork
    release_read, release_write = os.pipe()
    prior = signal.pthread_sigmask(
        signal.SIG_BLOCK,
        {signal.SIGTERM, signal.SIGHUP},
    )
    started = time.monotonic_ns()
    try:
        pid, applied_ns, ack_sha256, parent_returned_ns, acknowledged_ns = (
            broker._spawn_child_with_native_denial(
                release_read,
                time.monotonic_ns() + 5_000_000_000,
            )
        )
        if pid == 0:
            os.close(release_read)
            os.close(release_write)
            os._exit(0)
        assert acknowledged_ns - started >= 100_000_000
        assert started <= parent_returned_ns <= acknowledged_ns
        assert applied_ns > 0
        assert ack_sha256 == native_child_limit_ack_sha256(
            pid=pid,
            applied_monotonic_ns=applied_ns,
        )
        assert os.write(release_write, b"N") == 1
        waited, status = os.waitpid(pid, 0)
        assert waited == pid and status == 0
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, prior)
        for descriptor in (release_read, release_write):
            try:
                os.close(descriptor)
            except OSError:
                pass
