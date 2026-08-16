"""Adversarial protocol-custody controls for the LAT-US01 harness.

The tests in this module are harness-only.  They do not invoke the real parser,
an all-15 campaign, or a hosted provider.
"""

from __future__ import annotations

import os
import socket
import stat
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.benchmarks import latency_runner, latency_worker
from tests.benchmarks.latency_isolation import (
    NetworkIsolationError,
    NoEgressGuard,
    validate_owned_unix_probe,
)

REPOSITORY = Path(__file__).resolve().parents[2]
MarkerValidator = Callable[[Path], object]


def _write_private(path: Path, data: bytes = b"") -> None:
    path.write_bytes(data)
    path.chmod(0o600)


def _runner_marker(path: Path) -> None:
    assert latency_runner._private_empty_marker_exists(path) is True


def _worker_marker(path: Path) -> None:
    latency_worker._wait_for(path, timeout_seconds=0.01)


def _denial_marker(path: Path) -> None:
    assert latency_worker._network_denial_marker_observed(path) is True


MARKER_VALIDATORS: tuple[tuple[str, MarkerValidator], ...] = (
    ("runner", _runner_marker),
    ("worker", _worker_marker),
    ("network-denial", _denial_marker),
)


@pytest.mark.parametrize(
    ("owner", "create", "validate"),
    (
        (
            "runner",
            latency_runner._touch_exclusive,
            _runner_marker,
        ),
        (
            "worker",
            latency_worker._touch_exclusive,
            _worker_marker,
        ),
    ),
)
def test_exclusive_marker_is_private_regular_single_link_empty_and_stable(
    tmp_path: Path,
    owner: str,
    create: Callable[[Path], None],
    validate: MarkerValidator,
) -> None:
    marker = tmp_path / f"{owner}-marker"

    create(marker)

    retained = marker.lstat()
    assert not marker.is_symlink()
    assert stat.S_ISREG(retained.st_mode)
    assert stat.S_IMODE(retained.st_mode) == 0o600
    assert retained.st_uid == os.getuid()
    assert retained.st_nlink == 1
    assert retained.st_size == 0
    validate(marker)
    with pytest.raises(FileExistsError):
        create(marker)


@pytest.mark.parametrize(
    ("validator_name", "validate"),
    MARKER_VALIDATORS,
)
@pytest.mark.parametrize(
    "attack",
    ("symlink", "non-regular", "wrong-mode", "hard-link", "non-empty"),
)
def test_marker_validators_reject_nonprivate_or_nonempty_evidence(
    tmp_path: Path,
    validator_name: str,
    validate: MarkerValidator,
    attack: str,
) -> None:
    root = tmp_path / f"{validator_name}-{attack}"
    root.mkdir(mode=0o700)
    marker = root / "marker"
    if attack == "symlink":
        target = root / "target"
        _write_private(target)
        marker.symlink_to(target)
    elif attack == "non-regular":
        os.mkfifo(marker, 0o600)
    else:
        _write_private(marker, b"x" if attack == "non-empty" else b"")
        if attack == "wrong-mode":
            marker.chmod(0o640)
        elif attack == "hard-link":
            os.link(marker, root / "second-link")

    with pytest.raises(RuntimeError, match="custody|identity"):
        validate(marker)


@pytest.mark.parametrize(
    ("validator_name", "validate"),
    MARKER_VALIDATORS,
)
def test_broken_symlink_is_rejected_instead_of_treated_as_absent(
    tmp_path: Path,
    validator_name: str,
    validate: MarkerValidator,
) -> None:
    marker = tmp_path / f"{validator_name}-marker"
    marker.symlink_to(tmp_path / "missing-target")

    with pytest.raises(RuntimeError, match="custody"):
        validate(marker)


@pytest.mark.parametrize(
    ("owner", "create"),
    (
        ("runner", latency_runner._touch_exclusive),
        ("worker", latency_worker._touch_exclusive),
    ),
)
def test_marker_creator_rejects_post_open_path_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    owner: str,
    create: Callable[[Path], None],
) -> None:
    marker = tmp_path / f"{owner}-marker"
    displaced = tmp_path / f"{owner}-displaced"
    replacement = tmp_path / f"{owner}-replacement"
    _write_private(replacement)
    real_open = os.open
    attacked = False

    def hostile_open(path: os.PathLike[str] | str, *args: object, **kwargs: object):
        nonlocal attacked
        descriptor = real_open(path, *args, **kwargs)
        if Path(path) == marker and not attacked:
            marker.replace(displaced)
            replacement.replace(marker)
            attacked = True
        return descriptor

    monkeypatch.setattr(os, "open", hostile_open)

    with pytest.raises(RuntimeError, match="custody"):
        create(marker)
    assert attacked is True
    assert marker.lstat().st_ino != displaced.lstat().st_ino


@pytest.mark.parametrize(
    ("validator_name", "validate"),
    MARKER_VALIDATORS,
)
def test_marker_validator_rejects_inode_swap_during_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    validator_name: str,
    validate: MarkerValidator,
) -> None:
    marker = tmp_path / f"{validator_name}-marker"
    displaced = tmp_path / f"{validator_name}-displaced"
    replacement = tmp_path / f"{validator_name}-replacement"
    _write_private(marker)
    _write_private(replacement)
    real_lstat = Path.lstat
    attacked = False

    def hostile_lstat(path: Path):
        nonlocal attacked
        retained = real_lstat(path)
        if path == marker and not attacked:
            marker.replace(displaced)
            replacement.replace(marker)
            attacked = True
        return retained

    monkeypatch.setattr(Path, "lstat", hostile_lstat)

    with pytest.raises(RuntimeError, match="custody|identity"):
        validate(marker)
    assert attacked is True


def test_worker_result_is_bounded_private_and_read_from_one_stable_inode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = tmp_path / "result.json"
    payload = b'{"schema_id":"synthetic"}'

    latency_worker._write_exclusive(result, payload)

    retained = result.lstat()
    assert not result.is_symlink()
    assert stat.S_ISREG(retained.st_mode)
    assert stat.S_IMODE(retained.st_mode) == 0o600
    assert retained.st_uid == os.getuid()
    assert retained.st_nlink == 1
    assert retained.st_size == len(payload)
    assert (
        latency_runner.bounded_read_bytes(
            result,
            maximum_bytes=len(payload),
        )
        == payload
    )

    oversized = tmp_path / "oversized-result.json"
    monkeypatch.setattr(latency_worker, "MAXIMUM_EVIDENCE_BYTES", 4)
    with pytest.raises(RuntimeError, match="bound"):
        latency_worker._write_exclusive(oversized, b"12345")
    assert not oversized.exists()


def test_worker_result_writer_rejects_post_open_inode_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = tmp_path / "result.json"
    displaced = tmp_path / "displaced-result.json"
    replacement = tmp_path / "replacement-result.json"
    payload = b'{"schema_id":"synthetic"}'
    _write_private(replacement, payload)
    real_open = os.open
    attacked = False

    def hostile_open(path: os.PathLike[str] | str, *args: object, **kwargs: object):
        nonlocal attacked
        descriptor = real_open(path, *args, **kwargs)
        if Path(path) == result and not attacked:
            result.replace(displaced)
            replacement.replace(result)
            attacked = True
        return descriptor

    monkeypatch.setattr(os, "open", hostile_open)

    with pytest.raises(RuntimeError, match="custody"):
        latency_worker._write_exclusive(result, payload)
    assert attacked is True
    assert result.read_bytes() == displaced.read_bytes() == payload
    assert result.lstat().st_ino != displaced.lstat().st_ino


@pytest.mark.parametrize("attack_timing", ("before-open", "after-open"))
def test_bounded_result_reader_rejects_path_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attack_timing: str,
) -> None:
    result = tmp_path / "result.json"
    displaced = tmp_path / "displaced-result.json"
    replacement = tmp_path / "replacement-result.json"
    payload = b'{"schema_id":"synthetic"}'
    _write_private(result, payload)
    _write_private(replacement, payload)
    real_open = os.open
    attacked = False

    def hostile_open(path: os.PathLike[str] | str, *args: object, **kwargs: object):
        nonlocal attacked
        if Path(path) == result and not attacked and attack_timing == "before-open":
            result.replace(displaced)
            replacement.replace(result)
            attacked = True
        descriptor = real_open(path, *args, **kwargs)
        if Path(path) == result and not attacked and attack_timing == "after-open":
            result.replace(displaced)
            replacement.replace(result)
            attacked = True
        return descriptor

    monkeypatch.setattr(os, "open", hostile_open)

    with pytest.raises(ValueError, match="identity|changed"):
        latency_runner.bounded_read_bytes(
            result,
            maximum_bytes=len(payload),
        )
    assert attacked is True


def test_network_denial_marker_remains_valid_after_guard_shutdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol = tmp_path / "protocol"
    protocol.mkdir(mode=0o700)
    protocol.chmod(0o700)
    marker = protocol / "network-denied"
    monkeypatch.setenv("PHASE_LATENCY_NETWORK_DENIAL_MARKER", str(marker))
    guard = NoEgressGuard()
    guard.install()
    try:
        with pytest.raises(NetworkIsolationError):
            socket.getaddrinfo("blocked.invalid", 443)
        assert guard.denied_attempts == 1
        before_shutdown = marker.lstat()
    finally:
        guard.close()

    assert guard.installed is False
    assert latency_worker._network_denial_marker_observed(marker) is True
    after_shutdown = marker.lstat()
    assert (after_shutdown.st_dev, after_shutdown.st_ino) == (
        before_shutdown.st_dev,
        before_shutdown.st_ino,
    )
    assert stat.S_IMODE(after_shutdown.st_mode) == 0o600
    assert after_shutdown.st_nlink == 1
    assert after_shutdown.st_size == 0


def test_network_guard_creates_exact_private_empty_denial_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol = tmp_path / "protocol"
    protocol.mkdir(mode=0o700)
    protocol.chmod(0o700)
    marker = protocol / "network-denied"
    monkeypatch.setenv("PHASE_LATENCY_NETWORK_DENIAL_MARKER", str(marker))
    guard = NoEgressGuard()

    with pytest.raises(NetworkIsolationError):
        guard._deny("socket_create")

    retained = marker.lstat()
    assert not marker.is_symlink()
    assert stat.S_ISREG(retained.st_mode)
    assert stat.S_IMODE(retained.st_mode) == 0o600
    assert retained.st_uid == os.getuid()
    assert retained.st_nlink == 1
    assert retained.st_size == 0


@pytest.mark.parametrize("attack", ("wrong-mode", "hard-link", "non-empty"))
def test_network_guard_rejects_invalid_preexisting_denial_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
) -> None:
    protocol = tmp_path / "protocol"
    protocol.mkdir(mode=0o700)
    protocol.chmod(0o700)
    marker = protocol / "network-denied"
    _write_private(marker, b"x" if attack == "non-empty" else b"")
    if attack == "wrong-mode":
        marker.chmod(0o640)
    elif attack == "hard-link":
        os.link(marker, protocol / "second-link")
    monkeypatch.setenv("PHASE_LATENCY_NETWORK_DENIAL_MARKER", str(marker))
    guard = NoEgressGuard()

    with pytest.raises(RuntimeError, match="custody"):
        guard._deny("socket_create")


def test_network_guard_rejects_preexisting_broken_denial_marker_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol = tmp_path / "protocol"
    protocol.mkdir(mode=0o700)
    protocol.chmod(0o700)
    marker = protocol / "network-denied"
    marker.symlink_to(protocol / "missing-target")
    monkeypatch.setenv("PHASE_LATENCY_NETWORK_DENIAL_MARKER", str(marker))
    guard = NoEgressGuard()

    with pytest.raises(RuntimeError, match="custody"):
        guard._deny("socket_create")


def test_network_guard_rejects_denial_marker_creator_inode_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol = tmp_path / "protocol"
    protocol.mkdir(mode=0o700)
    protocol.chmod(0o700)
    marker = protocol / "network-denied"
    displaced = protocol / "displaced"
    replacement = protocol / "replacement"
    _write_private(replacement)
    monkeypatch.setenv("PHASE_LATENCY_NETWORK_DENIAL_MARKER", str(marker))
    guard = NoEgressGuard()
    real_open = os.open
    attacked = False

    def hostile_open(path: os.PathLike[str] | str, *args: object, **kwargs: object):
        nonlocal attacked
        descriptor = real_open(path, *args, **kwargs)
        if Path(path) == marker and not attacked:
            marker.replace(displaced)
            replacement.replace(marker)
            attacked = True
        return descriptor

    monkeypatch.setattr(os, "open", hostile_open)

    with pytest.raises(RuntimeError, match="custody|identity"):
        guard._deny("socket_create")
    assert attacked is True


@pytest.mark.parametrize("mutation", ("wrong-mode", "hard-link", "non-empty"))
def test_network_guard_rechecks_new_marker_after_descriptor_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    protocol = tmp_path / "protocol"
    protocol.mkdir(mode=0o700)
    protocol.chmod(0o700)
    marker = protocol / "network-denied"
    monkeypatch.setenv("PHASE_LATENCY_NETWORK_DENIAL_MARKER", str(marker))
    guard = NoEgressGuard()
    real_fstat = os.fstat
    attacked = False

    def hostile_fstat(descriptor: int):
        nonlocal attacked
        retained = real_fstat(descriptor)
        if not attacked:
            if mutation == "wrong-mode":
                marker.chmod(0o640)
            elif mutation == "hard-link":
                os.link(marker, protocol / "second-link")
            else:
                marker.write_bytes(b"x")
            attacked = True
        return retained

    monkeypatch.setattr(os, "fstat", hostile_fstat)

    with pytest.raises(RuntimeError, match="custody|identity"):
        guard._deny("socket_create")
    assert attacked is True


def test_network_guard_rejects_preexisting_denial_marker_inode_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol = tmp_path / "protocol"
    protocol.mkdir(mode=0o700)
    protocol.chmod(0o700)
    marker = protocol / "network-denied"
    displaced = protocol / "displaced"
    replacement = protocol / "replacement"
    _write_private(marker)
    _write_private(replacement)
    monkeypatch.setenv("PHASE_LATENCY_NETWORK_DENIAL_MARKER", str(marker))
    guard = NoEgressGuard()
    real_lstat = Path.lstat
    attacked = False

    def hostile_lstat(path: Path):
        nonlocal attacked
        retained = real_lstat(path)
        if path == marker and not attacked:
            marker.replace(displaced)
            replacement.replace(marker)
            attacked = True
        return retained

    monkeypatch.setattr(Path, "lstat", hostile_lstat)

    with pytest.raises(RuntimeError, match="custody|identity"):
        guard._deny("socket_create")
    assert attacked is True


def test_controller_and_worker_use_one_unix_probe_identity_validator() -> None:
    assert latency_runner.validate_owned_unix_probe is validate_owned_unix_probe
    assert latency_worker.validate_owned_unix_probe is validate_owned_unix_probe


def test_unix_probe_validator_rejects_replaced_socket_inode() -> None:
    with latency_runner.tempfile.TemporaryDirectory(
        prefix="up-",
        dir=REPOSITORY / "tmp",
    ) as directory:
        path = Path(directory) / "probe.sock"
        original = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        replacement: socket.socket | None = None
        try:
            original.bind(str(path))
            path.chmod(0o600)
            retained = path.lstat()
            validate_owned_unix_probe(
                path,
                expected_dev=retained.st_dev,
                expected_ino=retained.st_ino,
            )

            path.unlink()
            replacement = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            replacement.bind(str(path))
            path.chmod(0o600)
            replaced = path.lstat()
            assert (replaced.st_dev, replaced.st_ino) != (
                retained.st_dev,
                retained.st_ino,
            )
            with pytest.raises(RuntimeError, match="custody|identity"):
                validate_owned_unix_probe(
                    path,
                    expected_dev=retained.st_dev,
                    expected_ino=retained.st_ino,
                )
        finally:
            original.close()
            if replacement is not None:
                replacement.close()
            path.unlink(missing_ok=True)


def test_unix_probe_validator_rejects_inode_swap_during_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with latency_runner.tempfile.TemporaryDirectory(
        prefix="up-r-",
        dir="/private/tmp",
    ) as directory:
        root = Path(directory)
        path = root / "probe.sock"
        displaced = root / "displaced.sock"
        replacement_path = root / "replacement.sock"
        original = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        replacement = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        original.bind(str(path))
        replacement.bind(str(replacement_path))
        path.chmod(0o600)
        replacement_path.chmod(0o600)
        expected = path.lstat()
        real_lstat = Path.lstat
        attacked = False

        def hostile_lstat(candidate: Path):
            nonlocal attacked
            retained = real_lstat(candidate)
            if candidate == path and not attacked:
                path.replace(displaced)
                replacement_path.replace(path)
                attacked = True
            return retained

        monkeypatch.setattr(Path, "lstat", hostile_lstat)
        try:
            with pytest.raises(RuntimeError, match="custody|identity"):
                validate_owned_unix_probe(
                    path,
                    expected_dev=expected.st_dev,
                    expected_ino=expected.st_ino,
                )
            assert attacked is True
        finally:
            original.close()
            replacement.close()


def test_external_worker_socket_replacement_fails_closed_and_reaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = REPOSITORY / "benchmark-expertmodeldata" / "insurance-acord.pdf"
    source = latency_runner.derive_source_identity(
        source_path,
        case_id="synthetic-protocol-custody",
        workspace=REPOSITORY,
    )
    expected_execution_identity = (
        latency_runner.derive_candidate_code_sha256(REPOSITORY),
        latency_runner.derive_dependency_lock_sha256(REPOSITORY),
        latency_runner.derive_environment_sha256(),
        latency_runner.derive_model_artifacts_sha256(REPOSITORY),
    )
    real_lstat = Path.lstat
    real_cleanup = latency_runner._terminate_and_reap_owned_worker
    attacker_socket: socket.socket | None = None
    cleanup_calls = 0
    unix_probe_lstats = 0

    def hostile_lstat(path: Path):
        nonlocal attacker_socket, unix_probe_lstats
        retained = real_lstat(path)
        if path.name != "network-proxy-probe.sock":
            return retained
        unix_probe_lstats += 1
        if unix_probe_lstats == 4:
            path.unlink()
            attacker_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            attacker_socket.bind(str(path))
            path.chmod(0o600)
        return retained

    def tracked_cleanup(*args: object, **kwargs: object) -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1
        real_cleanup(*args, **kwargs)

    monkeypatch.setattr(Path, "lstat", hostile_lstat)
    monkeypatch.setattr(
        latency_runner,
        "_terminate_and_reap_owned_worker",
        tracked_cleanup,
    )
    try:
        run = latency_runner._run_one_external_worker(
            role="authoritative_uninstrumented",
            source=source,
            source_path=source_path,
            output_format="markdown",
            request_profile="request_cold_after_app_startup",
            timeout_seconds=10.0,
            root=REPOSITORY,
            synthetic_fixture_mode="mock-testclient",
            bounded_concurrency=1,
            expected_execution_identity=expected_execution_identity,
        )
    finally:
        if attacker_socket is not None:
            attacker_socket.close()

    assert unix_probe_lstats >= 4
    assert cleanup_calls >= 1
    assert run.evidence is None
    assert run.status is not latency_runner.AttemptStatus.SUCCESS
    assert run.completed_at >= run.started_at
    assert run.ended_ns > run.started_ns
