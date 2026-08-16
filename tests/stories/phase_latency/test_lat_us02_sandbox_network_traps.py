from __future__ import annotations

import errno
import os
from pathlib import Path
import socket
import sys

import pytest

from app.services import parser_sandbox_network_traps as traps
from app.services.parser_sandbox_attempt import SandboxAttemptProbeAuthority
from app.services.parser_sandbox_materialization import (
    materialize_sandbox_probe_roots,
)


def _source(path: Path, content: bytes) -> Path:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(content)
    return path.resolve(strict=True)


def test_network_plan_uses_exact_darwin_sockaddr_shapes() -> None:
    ipv4 = traps._sockaddr_in("127.0.0.1", 1234)
    ipv6 = traps._sockaddr_in6("::1", 5678)
    unix = traps._sockaddr_un("controller.sock")
    assert len(ipv4) == 16 and ipv4[:2] == bytes((16, socket.AF_INET))
    assert len(ipv6) == 28 and ipv6[:2] == bytes((28, socket.AF_INET6))
    assert unix[:2] == bytes((len(unix), socket.AF_UNIX))
    with pytest.raises(ValueError):
        traps._sockaddr_un("../escaped.sock")


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason="native network trap authority is Darwin-specific",
)
def test_network_traps_run_controls_and_close_without_residue(
    tmp_path: Path,
) -> None:
    os.chmod(tmp_path, 0o700)
    materialized = materialize_sandbox_probe_roots(
        base_root=tmp_path,
        artifact_source=_source(tmp_path / "artifact.bin", b"artifact"),
        tessdata_source=_source(tmp_path / "eng.traineddata", b"tessdata"),
        staged_executable_source=_source(tmp_path / "tesseract", b"staged"),
        input_source=_source(tmp_path / "input.bin", b"input"),
    )
    authority = None
    try:
        try:
            authority = traps.SandboxNetworkTrapAuthority.open(
                root=materialized.roots["network_trap_root"],
                root_fd=materialized.root_fds["network_trap_root"],
                control_nonce=b"network-positive-control",
            )
        except PermissionError as error:
            if error.errno == errno.EPERM:
                pytest.skip("host sandbox forbids controller loopback bind")
            raise
        assert len(authority.positive_controls) == 24
        for role in (
            "parser_worker",
            "tesseract_broker",
            "tesseract_child",
        ):
            operations = authority.role_network_operations(role)
            assert len(operations) == 8
            assert tuple(row["operation"] for row in operations) == (
                "ipv4_tcp_connect",
                "ipv6_tcp_connect",
                "ipv4_udp_sendto",
                "ipv6_udp_sendto",
                "unix_connect",
                "ipv4_bind_listen",
                "ipv6_bind_listen",
                "unix_bind",
            )
            assert {
                row["held_directory_fd"]
                for row in operations
                if row["held_directory_fd"] >= 0
            } == {materialized.root_fds["network_trap_root"]}
        terminal = authority.close()
        authority = None
        assert terminal["all_traps_unchanged"] is True
        assert terminal["root_empty_after_close"] is True
    finally:
        if authority is not None:
            for endpoint in (
                authority.tcp4,
                authority.tcp6,
                authority.udp4,
                authority.udp6,
                authority.unix_listener,
            ):
                endpoint.close()
        materialized.close()


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason="native sandbox attempt authority is Darwin-specific",
)
def test_attempt_authority_builds_exact_worker_broker_child_plans(
    tmp_path: Path,
) -> None:
    os.chmod(tmp_path, 0o700)
    artifact = _source(
        tmp_path / "production-artifact" / "artifact.bin", b"artifact"
    )
    tessdata = _source(
        tmp_path / "production-tessdata" / "eng.traineddata", b"tessdata"
    )
    staged = _source(
        tmp_path / "production-stage" / "tesseract", b"staged"
    )
    materialized = materialize_sandbox_probe_roots(
        base_root=tmp_path,
        artifact_source=artifact,
        tessdata_source=tessdata,
        staged_executable_source=staged,
        input_source=_source(tmp_path / "input.bin", b"input"),
    )
    scratch = tmp_path / "worker-scratch"
    scratch.mkdir(mode=0o700)
    scratch_fd = os.open(
        scratch,
        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
    )
    authority = None
    try:
        try:
            authority = SandboxAttemptProbeAuthority.open(
                materialization=materialized,
                attempt_id="sandbox-attempt",
                attempt_nonce_sha256="1" * 64,
                scope_sha256="2" * 64,
                worker_profile_sha256="3" * 64,
                broker_profile_sha256="4" * 64,
                native_closure_sha256="5" * 64,
                artifact_read_path=artifact,
                tessdata_read_path=tessdata,
                staged_executable_read_path=staged,
                worker_scratch_root=scratch.resolve(strict=True),
                worker_scratch_fd=scratch_fd,
                probe_library_path=staged,
                probe_library_sha256="6" * 64,
                control_nonce=b"attempt-network-positive-control",
            )
        except PermissionError as error:
            if error.errno == errno.EPERM:
                pytest.skip("host sandbox forbids controller loopback bind")
            raise
        assert len(authority.worker_directory_descriptors) == 10
        assert len(authority.broker_directory_descriptors) == 9
        assert len(authority.worker_plan["operations"]) == 27
        assert len(authority.broker_plan["operations"]) == 26
        assert len(authority.child_plan["operations"]) == 26
        assert authority.child_report_reservation_bytes <= 256 * 1024
        terminal = authority.close_terminal()
        authority = None
        assert terminal["all_traps_unchanged"] is True
    finally:
        if authority is not None:
            authority.abort()
        os.close(scratch_fd)
        materialized.close()
