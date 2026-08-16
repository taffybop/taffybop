from __future__ import annotations

import hashlib
import os
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.tesseract_broker import TesseractBroker
from app.services.tesseract_broker_client import (
    BrokerClientConfig,
    BrokerPopen,
    BrokerRunResult,
    TesseractBrokerClient,
)
from app.services import tesseract_broker_client as broker_client_module
from app.services.tesseract_broker_protocol import (
    BrokerExecutableIdentity,
    BrokerProtocolError,
)


def _identity(path: Path) -> BrokerExecutableIdentity:
    observed = path.stat()
    return BrokerExecutableIdentity(
        resolved_path=str(path.resolve()),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        device=observed.st_dev,
        inode=observed.st_ino,
        mode=observed.st_mode,
        uid=observed.st_uid,
        nlink=observed.st_nlink,
        size=observed.st_size,
    )


def _command_pair(tmp_path: Path):
    source = tmp_path / "source-tesseract"
    staged = tmp_path / "staged-tesseract"
    source.write_bytes(b"same frozen executable")
    staged.write_bytes(source.read_bytes())
    request_root = tmp_path / "request"
    request_root.mkdir(mode=0o700)
    request_root.chmod(0o700)
    tessdata = tmp_path / "tessdata"
    tessdata.mkdir()
    root_fd = os.open(
        request_root,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    root_stat = os.fstat(root_fd)
    source_identity = _identity(source)
    staged_identity = _identity(staged)
    config = BrokerClientConfig(
        attempt_nonce_sha256="a" * 64,
        scope_sha256="b" * 64,
        broker_pid=100,
        broker_start_abstime=101,
        broker_pgid=100,
        broker_sid=100,
        executable=source_identity.resolved_path,
        executable_sha256=source_identity.sha256,
        staged_executable=staged_identity.resolved_path,
        staged_executable_sha256=staged_identity.sha256,
        native_closure_sha256="c" * 64,
        native_spawn_guard_sha256="d" * 64,
        native_spawn_guard_source_sha256="e" * 64,
        native_runtime_gate_source_sha256="f" * 64,
        native_runtime_gate_library_sha256="1" * 64,
        native_runtime_gate_record_sha256="2" * 64,
        guard_python_sha256="3" * 64,
        guard_python_path_custody_sha256="4" * 64,
        guard_python_native_closure_sha256="5" * 64,
        guard_python_module_tree_sha256="6" * 64,
        guard_wrapper_source_sha256="7" * 64,
        tessdata_root=str(tessdata.resolve()),
        tessdata_sha256="8" * 64,
        languages=("eng", "osd"),
        request_root=str(request_root.resolve()),
        request_root_fd=root_fd,
        request_root_device=root_stat.st_dev,
        request_root_inode=root_stat.st_ino,
        attempt_deadline_monotonic_ns=time.monotonic_ns() + 5_000_000_000,
        external_barriers=True,
    )
    client = object.__new__(TesseractBrokerClient)
    client.config = config
    broker = object.__new__(TesseractBroker)
    broker.config = SimpleNamespace(
        source_executable=source_identity,
        executable=staged_identity,
        tessdata_root=config.tessdata_root,
        languages=config.languages,
    )
    return client, broker, config


@pytest.mark.parametrize(
    ("argv_builder", "input_body", "expected_operation"),
    [
        (lambda c, _p: [c.executable, "--version"], None, "version"),
        (
            lambda c, _p: [c.executable, "--list-langs"],
            None,
            "list_languages",
        ),
        (
            lambda c, p: [
                c.executable,
                "-l",
                "eng",
                "--tessdata-dir",
                c.tessdata_root,
                "--psm",
                "3",
                str(p),
                "stdout",
                "tsv",
            ],
            None,
            "ocr_tsv",
        ),
        (
            lambda c, p: [
                c.executable,
                "--psm",
                "0",
                "-l",
                "osd",
                str(p),
                "stdout",
            ],
            None,
            "osd",
        ),
        (
            lambda c, _p: [
                c.executable,
                "stdin",
                "stdout",
                "-l",
                "eng",
                "--psm",
                "3",
                "--tessdata-dir",
                c.tessdata_root,
                "tsv",
            ],
            b"stdin PNG bytes",
            "ocr_tsv",
        ),
    ],
)
def test_client_and_broker_share_exact_docling_and_local_command_projection(
    tmp_path: Path,
    argv_builder,
    input_body: bytes | None,
    expected_operation: str,
) -> None:
    client, broker, config = _command_pair(tmp_path)
    try:
        image = Path(config.request_root) / "docling-input.png"
        image.write_bytes(b"file PNG bytes")
        command, body, _logical_argv = client._normalize_command(
            argv_builder(config, image), input_body
        )
        command["stderr_mode"] = "merge"
        command["stdout_disposition"] = "captured"
        command["stderr_disposition"] = "captured"

        operation, actual_argv, environment = broker._validate_command(
            command, body
        )

        assert operation == expected_operation
        assert actual_argv[0] == config.staged_executable
        assert environment["TESSDATA_PREFIX"] == config.tessdata_root
        if expected_operation.startswith("ocr") or expected_operation == "osd":
            assert "stdin" in actual_argv
            assert str(image) not in actual_argv
    finally:
        os.close(config.request_root_fd)


def test_command_projection_rejects_unallowlisted_option_before_broker_fork(
    tmp_path: Path,
) -> None:
    client, _broker, config = _command_pair(tmp_path)
    try:
        with pytest.raises(BrokerProtocolError, match="not allowlisted"):
            client._normalize_command(
                [config.executable, "--user-words", "/tmp/injected"], None
            )
    finally:
        os.close(config.request_root_fd)


@pytest.mark.parametrize(
    "terminal_error",
    [
        subprocess.TimeoutExpired(cmd="tesseract", timeout=0.1),
        subprocess.SubprocessError("bounded capture overflow"),
    ],
)
def test_popen_terminal_failure_is_one_shot_and_never_reissues_run(
    monkeypatch: pytest.MonkeyPatch,
    terminal_error: BaseException,
) -> None:
    calls = 0

    class _FailingClient:
        def run(self, *_args, **_kwargs):
            nonlocal calls
            calls += 1
            raise terminal_error

    monkeypatch.setattr(
        broker_client_module,
        "require_tesseract_broker_client",
        lambda: _FailingClient(),
    )
    process = BrokerPopen(
        ["/frozen/tesseract", "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    with pytest.raises(type(terminal_error)):
        process.communicate(timeout=0.1)
    process.kill()
    assert process.wait() == -9
    with pytest.raises(type(terminal_error)):
        process.communicate()
    process.__exit__(None, None, None)
    assert calls == 1


def test_popen_devnull_projects_true_discard_dispositions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[dict[str, object]] = []

    class _DiscardClient:
        def run(self, args, **kwargs):
            observed.append({"args": args, **kwargs})
            return BrokerRunResult(tuple(args), 0, b"", b"")

    monkeypatch.setattr(
        broker_client_module,
        "require_tesseract_broker_client",
        lambda: _DiscardClient(),
    )
    process = BrokerPopen(
        ["/frozen/tesseract", "--version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    assert process.communicate(timeout=0.1) == (None, None)
    assert observed[0]["stdout_disposition"] == "discarded"
    assert observed[0]["stderr_mode"] == "discard"


def test_popen_kill_interrupts_concurrent_run_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    cancelled = threading.Event()
    cancel_count = 0

    class _BlockingClient:
        def run(self, *_args, **_kwargs):
            entered.set()
            assert cancelled.wait(timeout=1)
            raise subprocess.SubprocessError("cancelled broker RUN")

        def force_abort_active(self):
            nonlocal cancel_count
            cancel_count += 1
            cancelled.set()
            return None

    client = _BlockingClient()
    monkeypatch.setattr(
        broker_client_module,
        "require_tesseract_broker_client",
        lambda: client,
    )
    process = BrokerPopen(
        ["/frozen/tesseract", "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    errors: list[BaseException] = []

    def communicate() -> None:
        try:
            process.communicate(timeout=1)
        except BaseException as exc:
            errors.append(exc)

    runner = threading.Thread(target=communicate, daemon=True)
    runner.start()
    assert entered.wait(timeout=1)
    started = time.monotonic()
    process.kill()
    process.kill()
    assert time.monotonic() - started < 0.050
    runner.join(timeout=1)

    assert not runner.is_alive()
    assert len(errors) == 1
    assert cancel_count == 1
