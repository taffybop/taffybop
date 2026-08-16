from __future__ import annotations

import hashlib
import os
import stat
import threading
import time
from types import SimpleNamespace

import psutil
import pytest

from app.services import tesseract_broker as broker_module
from app.services.tesseract_broker_protocol import (
    BrokerProtocolError,
    KernelProcessIdentity,
)


def _broker() -> broker_module.TesseractBroker:
    broker = object.__new__(broker_module.TesseractBroker)
    broker.identity = KernelProcessIdentity(
        pid=os.getpid(),
        start_abstime=123,
        ppid=max(1, os.getppid()),
        pgid=os.getpid(),
        sid=os.getpid(),
    )
    broker.active = {
        "request_id": "thread-authority",
        "request_epoch": 1,
        "request_sequence": 1,
    }
    broker.births = []
    broker.tombstones = []
    broker.ledger = SimpleNamespace(reserve_child=lambda _sequence: None)
    return broker


def test_broker_single_thread_observation_is_hash_bound(monkeypatch) -> None:
    broker = _broker()
    monkeypatch.setattr(
        broker_module,
        "native_thread_inventory",
        lambda pid: (987654,) if pid == os.getpid() else (),
    )

    count, digest, observed_at = broker._sole_thread_observation()

    assert count == 1
    assert len(digest) == 64
    assert observed_at <= time.monotonic_ns()


def test_persistent_extra_broker_thread_blocks_authority(monkeypatch) -> None:
    broker = _broker()
    monkeypatch.setattr(
        broker_module,
        "native_thread_inventory",
        lambda _pid: (111, 222),
    )

    with pytest.raises(BrokerProtocolError, match="not single-threaded"):
        broker._sole_thread_observation()


def test_thread_race_at_spawn_boundary_blocks_before_fork_without_fd_leak(
    monkeypatch,
) -> None:
    broker = _broker()
    monkeypatch.setattr(
        broker,
        "_sole_thread_observation",
        lambda: (_ for _ in ()).throw(
            BrokerProtocolError("spawn-authorized broker is not single-threaded")
        ),
    )
    fork_called = False

    def forbidden_fork() -> int:
        nonlocal fork_called
        fork_called = True
        raise AssertionError("fork ran after the thread authority failed")

    monkeypatch.setattr(broker_module.os, "fork", forbidden_fork)
    before_fds = psutil.Process().num_fds()

    with pytest.raises(BrokerProtocolError, match="not single-threaded"):
        broker._run_child(
            "version",
            ("/frozen/tesseract", "--version"),
            {"LANG": "C"},
            b"",
            time.monotonic_ns() + 1_000_000_000,
            "a" * 64,
            "separate",
        )

    assert fork_called is False
    assert psutil.Process().num_fds() == before_fds


def test_thread_started_after_durable_spawn_intent_blocks_adjacent_fork(
    monkeypatch,
) -> None:
    broker = _broker()
    guard_source = b"raise SystemExit(125)\n"
    broker.config = SimpleNamespace(
        executable=SimpleNamespace(
            resolved_path="/frozen/tesseract",
            sha256="1" * 64,
            device=1,
            inode=2,
            mode=stat.S_IFREG | 0o500,
        ),
        native_runtime_gate_library=SimpleNamespace(
            resolved_path="/frozen/runtime-gate.dylib",
            sha256="2" * 64,
            device=3,
            inode=4,
        ),
        native_runtime_gate={"record_sha256": "3" * 64},
        native_spawn_guard=SimpleNamespace(sha256="4" * 64),
        guard_python=SimpleNamespace(
            resolved_path="/frozen/python3",
            sha256="5" * 64,
            device=5,
            inode=6,
        ),
        guard_python_path_custody={"record_sha256": "6" * 64},
        guard_python_native_closure_sha256="7" * 64,
        guard_python_module_tree_custody={
            "resolved_root": "/frozen",
            "record_sha256": "8" * 64,
        },
        guard_wrapper_source=guard_source,
        child_wrapper_sha256=hashlib.sha256(guard_source).hexdigest(),
        attempt_nonce="9" * 64,
        scope_sha256="a" * 64,
    )
    stop = threading.Event()
    started = threading.Event()
    raced_thread = threading.Thread(
        target=lambda: (started.set(), stop.wait()),
        name="post-intent-broker-race",
    )

    class Ledger:
        def append(self, kind, _record):
            assert kind == "spawn_intent"
            raced_thread.start()
            assert started.wait(1.0)
            return "b" * 64

    broker.ledger = Ledger()
    observations = 0

    def observe_threads():
        nonlocal observations
        observations += 1
        if observations == 1:
            return 1, "a" * 64, time.monotonic_ns()
        assert raced_thread.is_alive()
        raise BrokerProtocolError(
            "spawn-authorized broker is not single-threaded"
        )

    monkeypatch.setattr(broker, "_sole_thread_observation", observe_threads)
    monkeypatch.setattr(
        broker_module,
        "_read_exact_file",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("child admission reread the workspace guard")
        ),
    )
    monkeypatch.setattr(
        broker_module,
        "_observed_file_identity",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("child admission re-resolved guard Python")
        ),
    )
    fork_called = False

    def forbidden_fork() -> int:
        nonlocal fork_called
        fork_called = True
        raise AssertionError("fork ran after adjacent thread scan failed")

    monkeypatch.setattr(broker_module.os, "fork", forbidden_fork)
    before_fds = psutil.Process().num_fds()
    try:
        with pytest.raises(BrokerProtocolError, match="not single-threaded"):
            broker._run_child(
                "version",
                ("/frozen/tesseract", "--version"),
                {"LANG": "C"},
                b"",
                time.monotonic_ns() + 1_000_000_000,
                "a" * 64,
                "separate",
            )
    finally:
        stop.set()
        raced_thread.join(timeout=1.0)

    assert observations == 2
    assert fork_called is False
    assert psutil.Process().num_fds() == before_fds
