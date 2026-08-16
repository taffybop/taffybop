from __future__ import annotations

import hashlib
import os
from pathlib import Path
import socket

import pytest

from app.services import parser_sandbox_network_traps as traps
from app.services.parser_sandbox_materialization import (
    materialize_sandbox_probe_roots,
)
from app.services.parser_sandbox_role_plan import (
    SandboxRoleDirectoryAuthority,
    build_child_sandbox_probe_plan,
    build_root_sandbox_probe_plan,
)
from app.services.tesseract_child_sandbox_probe import (
    CHILD_SANDBOX_HELD_DIRECTORY_ROLES,
    child_sandbox_probe_report_reservation_bytes,
)


SHA = hashlib.sha256(b"sandbox-plan-authority").hexdigest()


def _source(root: Path, name: str, content: bytes) -> Path:
    root.mkdir(mode=0o700)
    path = root / name
    path.write_bytes(content)
    return path.resolve(strict=True)


def _network_operations(network_fd: int) -> tuple[dict[str, object], ...]:
    targets = (
        ("ipv4_tcp_connect", 1, socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, -1, traps._sockaddr_in("127.0.0.1", 41001), b""),
        ("ipv6_tcp_connect", 1, socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, -1, traps._sockaddr_in6("::1", 41002), b""),
        ("ipv4_udp_sendto", 2, socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP, -1, traps._sockaddr_in("127.0.0.1", 41003), b"probe123"),
        ("ipv6_udp_sendto", 2, socket.AF_INET6, socket.SOCK_DGRAM, socket.IPPROTO_UDP, -1, traps._sockaddr_in6("::1", 41004), b"probe123"),
        ("unix_connect", 1, socket.AF_UNIX, socket.SOCK_STREAM, 0, network_fd, traps._sockaddr_un("controller.sock"), b""),
        ("ipv4_bind_listen", 3, socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, -1, traps._sockaddr_in("127.0.0.1", 0), b""),
        ("ipv6_bind_listen", 3, socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, -1, traps._sockaddr_in6("::1", 0), b""),
        ("unix_bind", 3, socket.AF_UNIX, socket.SOCK_STREAM, 0, network_fd, traps._sockaddr_un("child-bind.sock"), b""),
    )
    return tuple(
        {
            "operation": name,
            "kind": "network",
            "operation_code": code,
            "held_directory_fd": descriptor,
            "domain": int(family),
            "socket_type": int(socket_type),
            "protocol": int(protocol),
            "sockaddr_hex": sockaddr.hex(),
            "payload_hex": payload.hex(),
        }
        for name, code, family, socket_type, protocol, descriptor, sockaddr, payload in targets
    )


def test_child_sandbox_plan_binds_nine_distinct_directory_authorities(
    tmp_path: Path,
) -> None:
    os.chmod(tmp_path, 0o700)
    artifact = _source(tmp_path / "production-artifact", "model.bin", b"artifact")
    tessdata = _source(tmp_path / "production-tessdata", "eng.traineddata", b"tessdata")
    staged = _source(tmp_path / "production-stage", "tesseract", b"staged")
    input_source = _source(tmp_path / "source", "input.bin", b"input")
    protocol = tmp_path / "protocol"
    protocol.mkdir(mode=0o700)
    materialized = materialize_sandbox_probe_roots(
        base_root=protocol,
        artifact_source=artifact,
        tessdata_source=tessdata,
        staged_executable_source=staged,
        input_source=input_source,
    )
    directories = SandboxRoleDirectoryAuthority.open(
        materialization=materialized,
        artifact_read_path=artifact,
        tessdata_read_path=tessdata,
        staged_executable_read_path=staged,
    )
    try:
        plan, reservation = build_child_sandbox_probe_plan(
            attempt_id="sandbox-plan",
            attempt_nonce_sha256=SHA,
            scope_sha256=SHA,
            profile_sha256=SHA,
            native_closure_sha256=SHA,
            executor_source_sha256=SHA,
            probe_library_path=staged,
            probe_library_sha256=SHA,
            directories=directories,
            network_operations=_network_operations(
                directories.descriptors_by_role["network_trap_root"]
            ),
        )
        assert tuple(item["role"] for item in plan["held_directories"]) == (
            CHILD_SANDBOX_HELD_DIRECTORY_ROLES
        )
        assert len({item["descriptor"] for item in plan["held_directories"]}) == 9
        assert len(plan["operations"]) == 26
        assert reservation == child_sandbox_probe_report_reservation_bytes(plan)

        broker_plan = build_root_sandbox_probe_plan(
            attempt_id="sandbox-plan",
            attempt_nonce_sha256=SHA,
            scope_sha256=SHA,
            role="tesseract_broker",
            profile_sha256=SHA,
            native_closure_sha256=SHA,
            executor_source_sha256=SHA,
            probe_library_path=staged,
            probe_library_sha256=SHA,
            directories=directories,
            network_operations=_network_operations(
                directories.descriptors_by_role["network_trap_root"]
            ),
        )
        assert len(broker_plan["held_directories"]) == 9
        assert len(broker_plan["operations"]) == 26

        scratch = tmp_path / "worker-scratch"
        scratch.mkdir(mode=0o700)
        scratch_fd = os.open(
            scratch,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
        try:
            worker_plan = build_root_sandbox_probe_plan(
                attempt_id="sandbox-plan",
                attempt_nonce_sha256=SHA,
                scope_sha256=SHA,
                role="parser_worker",
                profile_sha256=SHA,
                native_closure_sha256=SHA,
                executor_source_sha256=SHA,
                probe_library_path=staged,
                probe_library_sha256=SHA,
                directories=directories,
                network_operations=_network_operations(
                    directories.descriptors_by_role["network_trap_root"]
                ),
                worker_scratch_root=scratch.resolve(strict=True),
                worker_scratch_fd=scratch_fd,
            )
        finally:
            os.close(scratch_fd)
        assert len(worker_plan["held_directories"]) == 10
        assert len(worker_plan["operations"]) == 27
        assert worker_plan["operations"][-1]["operation"] == (
            "worker_scratch_roundtrip"
        )

        mutated = {**plan, "held_directories": list(plan["held_directories"])}
        mutated["held_directories"][1] = {
            **mutated["held_directories"][1],
            "descriptor": mutated["held_directories"][0]["descriptor"],
        }
        fields = {key: value for key, value in mutated.items() if key != "plan_sha256"}
        mutated["plan_sha256"] = hashlib.sha256(
            __import__("json").dumps(
                fields,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        with pytest.raises(ValueError, match="held directory topology"):
            child_sandbox_probe_report_reservation_bytes(mutated)
    finally:
        directories.close()
        materialized.close()
