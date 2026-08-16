"""Focused fatal-envelope controls for the LAT-US01 external worker.

These tests are synthetic harness controls only.  They never invoke the real
parser, a hosted provider, or the all-15 phase-exit campaign.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from tests.benchmarks import latency_runner, latency_worker
from tests.benchmarks.latency_campaign import build_interleaved_plan
from tests.benchmarks.latency_contracts import (
    AttemptStatus,
    FailureType,
    WorkerFatalEnvelope,
    canonical_model_bytes,
)

REPOSITORY = Path(__file__).resolve().parents[2]

CHECKPOINTS = (
    "bootstrap",
    "argument_validation",
    "os_network_attestation",
    "source_and_identity_validation",
    "application_startup",
    "testclient_startup",
    "prewarm_request",
    "pre_request_validation",
    "measured_request",
    "post_request_resource_snapshot",
    "post_request_resource_tracker_inspection",
    "response_boundary_handshake",
    "response_validation",
    "testclient_shutdown",
    "post_shutdown_network_check",
    "disposable_parser_state_release",
    "disposable_tqdm_lock_release",
    "disposable_environment_restore",
    "resource_tracker_cleanup",
    "resource_tracker_cleanup_identity",
    "resource_tracker_private_stop",
    "resource_tracker_cleanup_proof",
    "resource_tracker_cleanup_private_state",
    "resource_tracker_cleanup_exit_code",
    "resource_tracker_cleanup_process_absence",
    "resource_tracker_cleanup_no_relaunch",
    "resource_tracker_relaunch_register",
    "resource_tracker_relaunch_unregister",
    "resource_tracker_relaunch_other",
    "resource_closure_handshake",
    "resource_closure_signal",
    "resource_closure_ack_wait",
    "resource_closure_post_tracker",
    "resource_closure_environment",
    "resource_closure_network",
    "evidence_construction",
    "evidence_identity_derivation",
    "evidence_configuration",
    "evidence_cache_state",
    "evidence_stage_trace",
    "evidence_instrumentation_manifest",
    "evidence_instrumentation_harness_files",
    "evidence_instrumentation_overhead",
    "evidence_instrumentation_bindings",
    "evidence_environment_manifest",
    "evidence_contract_validation",
    "evidence_post_validation",
    "evidence_post_tracker",
    "evidence_post_network",
    "evidence_serialization",
    "evidence_done_marker",
    "final_ack",
    "guard_close",
)

EXCEPTION_FAMILIES = (
    "network_isolation",
    "memory",
    "timeout",
    "permission",
    "os",
    "validation",
    "assertion",
    "runtime",
    "cancellation",
    "system_exit",
    "unexpected_exception",
    "unexpected_base_exception",
)


def _envelope(**updates: Any) -> WorkerFatalEnvelope:
    payload: dict[str, Any] = {
        "schema_id": "phase-latency-worker-fatal-envelope-v1",
        "checkpoint": "measured_request",
        "exception_family": "runtime",
        "exit_code": 88,
    }
    payload.update(updates)
    return WorkerFatalEnvelope.model_validate(payload)


def _write_private(path: Path, payload: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)


def test_fatal_envelope_contract_is_closed_bounded_and_content_free() -> None:
    envelope = _envelope()
    encoded = canonical_model_bytes(envelope)

    assert latency_worker.MAXIMUM_FATAL_ENVELOPE_BYTES == 512
    assert latency_runner.MAXIMUM_FATAL_ENVELOPE_BYTES == 512
    assert latency_worker.WORKER_FATAL_EXIT_CODE == 88
    assert latency_runner.WORKER_FATAL_EXIT_CODE == 88
    assert latency_worker.WORKER_FATAL_ENVELOPE_WRITE_FAILED_EXIT_CODE == 89
    assert latency_runner.WORKER_FATAL_ENVELOPE_WRITE_FAILED_EXIT_CODE == 89
    assert encoded == (
        b'{"checkpoint":"measured_request","exception_family":"runtime",'
        b'"exit_code":88,"schema_id":'
        b'"phase-latency-worker-fatal-envelope-v1"}'
    )
    assert len(encoded) <= 512
    assert set(envelope.model_dump()) == {
        "schema_id",
        "checkpoint",
        "exception_family",
        "exit_code",
    }
    for forbidden in (
        b'"message":',
        b'"path":',
        b'"request":',
        b'"source":',
        b'"document":',
        b'"traceback":',
    ):
        assert forbidden not in encoded


def test_fatal_envelope_retains_the_complete_fixed_vocabulary() -> None:
    schema = WorkerFatalEnvelope.model_json_schema()

    assert tuple(schema["properties"]["checkpoint"]["enum"]) == CHECKPOINTS
    assert tuple(schema["properties"]["exception_family"]["enum"]) == EXCEPTION_FAMILIES
    assert schema["properties"]["schema_id"]["const"] == (
        "phase-latency-worker-fatal-envelope-v1"
    )
    assert schema["properties"]["exit_code"]["const"] == 88
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize(
    "mutation",
    (
        {"schema_id": "phase-latency-worker-fatal-envelope-v2"},
        {"checkpoint": "unknown_checkpoint"},
        {"exception_family": "RuntimeError"},
        {"exit_code": 89},
        {"message": "request material must never be accepted"},
        {"source_path": "/private/source.pdf"},
    ),
)
def test_fatal_envelope_rejects_unknown_or_content_bearing_fields(
    mutation: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        _envelope(**mutation)


def test_fatal_envelope_writer_and_reader_preserve_private_canonical_custody(
    tmp_path: Path,
) -> None:
    protocol = tmp_path / "protocol"
    protocol.mkdir(mode=0o700)
    protocol.chmod(0o700)
    path = protocol / "fatal.json"
    envelope = _envelope()

    latency_worker._write_fatal_envelope(path, envelope)

    retained = path.lstat()
    assert not path.is_symlink()
    assert stat.S_ISREG(retained.st_mode)
    assert stat.S_IMODE(retained.st_mode) == 0o600
    assert retained.st_uid == os.getuid()
    assert retained.st_nlink == 1
    assert retained.st_size == len(canonical_model_bytes(envelope))
    assert latency_runner._read_worker_fatal_envelope(path) == envelope
    assert path.read_bytes() == canonical_model_bytes(envelope)
    with pytest.raises(FileExistsError):
        latency_worker._write_fatal_envelope(path, envelope)


def test_fatal_envelope_writer_rejects_oversized_canonical_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol = tmp_path / "protocol"
    protocol.mkdir(mode=0o700)
    protocol.chmod(0o700)
    path = protocol / "fatal.json"
    monkeypatch.setattr(
        latency_worker,
        "canonical_model_bytes",
        lambda _model: b"x" * 513,
    )

    with pytest.raises(RuntimeError, match="bound"):
        latency_worker._write_fatal_envelope(path, _envelope())
    assert not path.exists()


@pytest.mark.parametrize(
    "payload",
    (
        b"{",
        b"{}",
        b'{"checkpoint":"unknown_checkpoint"}',
        canonical_model_bytes(_envelope()) + b"\n",
        b"x" * 513,
    ),
)
def test_fatal_envelope_reader_rejects_malformed_noncanonical_or_oversized_input(
    tmp_path: Path,
    payload: bytes,
) -> None:
    protocol = tmp_path / "protocol"
    protocol.mkdir(mode=0o700)
    protocol.chmod(0o700)
    path = protocol / "fatal.json"
    _write_private(path, payload)

    with pytest.raises((RuntimeError, ValueError)):
        latency_runner._read_worker_fatal_envelope(path)


def test_fatal_envelope_reader_rejects_symlink(tmp_path: Path) -> None:
    protocol = tmp_path / "protocol"
    protocol.mkdir(mode=0o700)
    protocol.chmod(0o700)
    target = protocol / "retained.json"
    path = protocol / "fatal.json"
    _write_private(target, canonical_model_bytes(_envelope()))
    path.symlink_to(target)

    with pytest.raises((RuntimeError, ValueError), match="custody|symlink|regular"):
        latency_runner._read_worker_fatal_envelope(path)


def test_fatal_envelope_writer_rejects_preexisting_symlink(tmp_path: Path) -> None:
    protocol = tmp_path / "protocol"
    protocol.mkdir(mode=0o700)
    protocol.chmod(0o700)
    target = protocol / "target.json"
    path = protocol / "fatal.json"
    _write_private(target, canonical_model_bytes(_envelope()))
    path.symlink_to(target)

    with pytest.raises((FileExistsError, RuntimeError, OSError)):
        latency_worker._write_fatal_envelope(path, _envelope())
    assert path.is_symlink()


def test_fatal_envelope_helpers_reject_noncanonical_leaf_name(
    tmp_path: Path,
) -> None:
    protocol = tmp_path / "protocol"
    protocol.mkdir(mode=0o700)
    protocol.chmod(0o700)
    wrong = protocol / "fatal-envelope.json"

    with pytest.raises(RuntimeError, match="custody"):
        latency_worker._write_fatal_envelope(wrong, _envelope())
    _write_private(wrong, canonical_model_bytes(_envelope()))
    with pytest.raises(RuntimeError, match="custody"):
        latency_runner._read_worker_fatal_envelope(wrong)


def test_worker_fatal_envelope_write_failure_uses_distinct_exit_code(
    tmp_path: Path,
) -> None:
    protocol = tmp_path / "protocol"
    protocol.mkdir(mode=0o700)
    protocol.chmod(0o700)
    fatal = protocol / "fatal.json"
    ready = protocol / "ready"
    _write_private(fatal, b"preexisting")

    completed = subprocess.run(
        (
            sys.executable,
            "-m",
            "tests.benchmarks.latency_worker",
            "--fatal-envelope",
            str(fatal),
            "--ready",
            str(ready),
        ),
        cwd=REPOSITORY,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=10.0,
    )

    assert completed.returncode == (
        latency_worker.WORKER_FATAL_ENVELOPE_WRITE_FAILED_EXIT_CODE
    )
    assert completed.returncode != latency_worker.WORKER_FATAL_EXIT_CODE
    assert fatal.read_bytes() == b"preexisting"


def test_disposable_tqdm_lock_release_unregisters_the_owned_semaphore() -> None:
    probe = textwrap.dedent(
        """\
        import gc
        from multiprocessing import resource_tracker
        from tqdm.auto import tqdm
        from tests.benchmarks.latency_worker import _release_disposable_tqdm_lock

        lock = tqdm.get_lock()
        assert resource_tracker._resource_tracker._pid is not None
        _release_disposable_tqdm_lock()
        del lock
        gc.collect()
        resource_tracker._resource_tracker._stop()
        for _ in range(3):
            bytearray(1_000_000)
            gc.collect()
        assert resource_tracker._resource_tracker._pid is None
        assert resource_tracker._resource_tracker._fd is None
        print(resource_tracker._resource_tracker._exitcode)
        """
    )
    completed = subprocess.run(
        (sys.executable, "-c", probe),
        cwd=REPOSITORY,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=10.0,
        start_new_session=True,
    )

    assert completed.returncode == 0
    assert completed.stdout == b"0\n"


def test_owned_resource_tracker_audit_cleans_a_stale_owned_registration() -> None:
    probe = textwrap.dedent(
        """\
        from multiprocessing import resource_tracker
        from tests.benchmarks.latency_worker import _OwnedResourceTrackerAudit

        audit = _OwnedResourceTrackerAudit()
        resource_tracker.register('/lat-us01-owned-audit-probe', 'shared_memory')
        print(audit.cleanup_owned_and_seal())
        resource_tracker._resource_tracker._stop()
        print(resource_tracker._resource_tracker._exitcode)
        try:
            resource_tracker.register('/lat-us01-late-registration', 'shared_memory')
        except RuntimeError:
            print('late-registration-rejected')
        else:
            raise AssertionError('late registration was accepted')
        try:
            resource_tracker.getfd()
        except RuntimeError:
            print('late-getfd-rejected')
        else:
            raise AssertionError('late tracker getfd was accepted')
        try:
            resource_tracker.ensure_running()
        except RuntimeError:
            print('late-ensure-running-rejected')
        else:
            raise AssertionError('late tracker ensure-running was accepted')
        print(resource_tracker._resource_tracker._pid)
        """
    )
    completed = subprocess.run(
        (sys.executable, "-c", probe),
        cwd=REPOSITORY,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=10.0,
        start_new_session=True,
    )

    assert completed.returncode == 0
    assert completed.stdout == (
        b"1\n0\nlate-registration-rejected\nlate-getfd-rejected\n"
        b"late-ensure-running-rejected\nNone\n"
    )


def test_disposable_environment_restore_is_exact_and_narrow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in latency_worker.DISPOSABLE_DEPENDENCY_ENVIRONMENT_KEYS:
        monkeypatch.delenv(name, raising=False)
    baseline = dict(os.environ)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/dependency-added")
    monkeypatch.setenv("TORCHINDUCTOR_CACHE_DIR", "/dependency-cache")
    monkeypatch.setenv("LAT_US01_UNRELATED_CONTROL", "unchanged")

    latency_worker._restore_disposable_worker_environment(baseline)

    assert "LD_LIBRARY_PATH" not in os.environ
    assert "TORCHINDUCTOR_CACHE_DIR" not in os.environ
    assert os.environ["LAT_US01_UNRELATED_CONTROL"] == "unchanged"


@pytest.mark.parametrize("operation", ("write", "read"))
def test_fatal_envelope_rejects_inode_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    protocol = tmp_path / "protocol"
    protocol.mkdir(mode=0o700)
    protocol.chmod(0o700)
    path = protocol / "fatal.json"
    displaced = protocol / "displaced.json"
    replacement = protocol / "replacement.json"
    payload = canonical_model_bytes(_envelope())
    _write_private(replacement, payload)
    if operation == "read":
        _write_private(path, payload)
    real_open = os.open
    attacked = False

    def hostile_open(
        candidate: os.PathLike[str] | str,
        *args: Any,
        **kwargs: Any,
    ) -> int:
        nonlocal attacked
        descriptor = real_open(candidate, *args, **kwargs)
        if Path(candidate) == path and not attacked:
            path.replace(displaced)
            replacement.replace(path)
            attacked = True
        return descriptor

    monkeypatch.setattr(os, "open", hostile_open)

    with pytest.raises((RuntimeError, ValueError), match="custody|identity|changed"):
        if operation == "write":
            latency_worker._write_fatal_envelope(path, _envelope())
        else:
            latency_runner._read_worker_fatal_envelope(path)
    assert attacked is True
    assert path.lstat().st_ino != displaced.lstat().st_ino


def test_synthetic_mock_fatal_is_retained_by_controller_without_content() -> None:
    slot = build_interleaved_plan(("synthetic-external",), sample_count=5)[0]
    retained_runs: list[Any] = []

    attempt = latency_runner.run_external_candidate_attempt(
        slot=slot,
        source_path=(REPOSITORY / "benchmark-expertmodeldata" / "insurance-acord.pdf"),
        attempt_id="synthetic-mock-fatal",
        output_format="markdown",
        timeout_seconds=10.0,
        workspace=REPOSITORY,
        synthetic_fixture_mode="mock-fatal",
        _role_observer=lambda _slot, _attempt_id, run: retained_runs.append(run),
    )

    assert len(retained_runs) == 2
    assert all(run.evidence is None for run in retained_runs)
    assert all(run.worker_fatal_envelope is not None for run in retained_runs)
    assert all(run.worker_fatal_envelope.exit_code == 88 for run in retained_runs)
    retained_fatal_summaries = tuple(
        (
            run.failure_code,
            run.worker_fatal_envelope.checkpoint,
            run.worker_fatal_envelope.exception_family,
        )
        for run in retained_runs
    )
    assert all(
        checkpoint == "measured_request"
        for _, checkpoint, _ in retained_fatal_summaries
    ), retained_fatal_summaries
    assert all(
        run.worker_fatal_envelope.exception_family == "runtime" for run in retained_runs
    )
    assert attempt.status is AttemptStatus.ERROR
    assert attempt.failure is not None
    assert attempt.failure.exception_type is FailureType.WORKER_CRASH
    assert attempt.worker_fatal_envelope == retained_runs[0].worker_fatal_envelope
    encoded = canonical_model_bytes(attempt.worker_fatal_envelope)
    assert len(encoded) <= 512
    assert b"insurance-acord" not in encoded
    assert b"synthetic-mock-fatal" not in encoded


def test_synthetic_success_retains_no_fatal_envelope() -> None:
    slot = build_interleaved_plan(("synthetic-external",), sample_count=5)[0]
    retained_runs: list[Any] = []

    attempt = latency_runner.run_external_candidate_attempt(
        slot=slot,
        source_path=(REPOSITORY / "benchmark-expertmodeldata" / "insurance-acord.pdf"),
        attempt_id="synthetic-fatal-envelope-success-control",
        output_format="markdown",
        timeout_seconds=10.0,
        workspace=REPOSITORY,
        synthetic_fixture_mode="mock-testclient",
        _role_observer=lambda _slot, _attempt_id, run: retained_runs.append(run),
    )

    assert attempt.status is AttemptStatus.SUCCESS, (
        attempt.failure,
        attempt.worker_fatal_envelope,
        tuple(
            (
                run.failure_code,
                run.worker_fatal_envelope,
            )
            for run in retained_runs
        ),
    )
    assert attempt.worker_fatal_envelope is None
    assert len(retained_runs) == 2
    assert all(run.worker_fatal_envelope is None for run in retained_runs)
