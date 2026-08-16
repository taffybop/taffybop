"""Controller-held network targets for the LAT-US02 Seatbelt matrix."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import socket
import stat
import time
from typing import Final, Iterator

from app.services.tesseract_broker_native import (
    native_detailed_file_descriptor_inventory,
    native_thread_inventory,
)


NETWORK_TRAP_SCHEMA: Final = "phase-latency-sandbox-network-traps-v1"
_UNIX_CONNECT_NAME: Final = "controller-connect.sock"
_ROLE_NAMES: Final = ("parser_worker", "tesseract_broker", "tesseract_child")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _sockaddr_in(address: str, port: int) -> bytes:
    return (
        bytes((16, int(socket.AF_INET)))
        + port.to_bytes(2, "big")
        + socket.inet_pton(socket.AF_INET, address)
        + b"\0" * 8
    )


def _sockaddr_in6(address: str, port: int) -> bytes:
    return (
        bytes((28, int(socket.AF_INET6)))
        + port.to_bytes(2, "big")
        + b"\0" * 4
        + socket.inet_pton(socket.AF_INET6, address)
        + b"\0" * 4
    )


def _sockaddr_un(relative_name: str) -> bytes:
    encoded = relative_name.encode("utf-8")
    if (
        not encoded
        or len(encoded) > 103
        or "/" in relative_name
        or relative_name in {".", ".."}
        or "\0" in relative_name
    ):
        raise ValueError("sandbox AF_UNIX relative target differs")
    return bytes((3 + len(encoded), int(socket.AF_UNIX))) + encoded + b"\0"


def _root_identity(path: Path, descriptor: int) -> dict[str, object]:
    resolved = path.resolve(strict=True)
    path_stat = path.lstat()
    fd_stat = os.fstat(descriptor)
    if (
        resolved != path
        or path.is_symlink()
        or not stat.S_ISDIR(path_stat.st_mode)
        or stat.S_IMODE(path_stat.st_mode) != 0o700
        or path_stat.st_uid != os.geteuid()
        or (path_stat.st_dev, path_stat.st_ino, path_stat.st_mode)
        != (fd_stat.st_dev, fd_stat.st_ino, fd_stat.st_mode)
    ):
        raise RuntimeError("sandbox network trap root identity differs")
    return {
        "resolved_path": str(resolved),
        "resolved_path_sha256": hashlib.sha256(
            str(resolved).encode("utf-8")
        ).hexdigest(),
        "device": fd_stat.st_dev,
        "inode": fd_stat.st_ino,
        "mode": fd_stat.st_mode,
        "uid": fd_stat.st_uid,
        "nlink": fd_stat.st_nlink,
        "held_directory_fd": descriptor,
        "held_open_flags": (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
        ),
    }


@contextmanager
def _anchored_directory(descriptor: int) -> Iterator[dict[str, object]]:
    threads = tuple(native_thread_inventory(os.getpid()))
    if len(threads) != 1:
        raise RuntimeError("sandbox network anchor requires one native thread")
    blocked = set(signal.valid_signals()) - {signal.SIGKILL, signal.SIGSTOP}
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
    observed = signal.pthread_sigmask(signal.SIG_BLOCK, set())
    saved_cwd = os.open(
        ".",
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    authority = {
        "thread_ids": list(threads),
        "prior_signal_mask": sorted(int(value) for value in previous),
        "blocked_signal_mask": sorted(int(value) for value in observed),
        "entered_monotonic_ns": time.monotonic_ns(),
        "restored_monotonic_ns": 0,
    }
    try:
        if not blocked.issubset(observed):
            raise RuntimeError("sandbox network anchor signal mask differs")
        os.fchdir(descriptor)
        yield authority
    finally:
        try:
            os.fchdir(saved_cwd)
        finally:
            os.close(saved_cwd)
            signal.pthread_sigmask(signal.SIG_SETMASK, previous)
        restored = signal.pthread_sigmask(signal.SIG_BLOCK, set())
        after = tuple(native_thread_inventory(os.getpid()))
        authority["restored_monotonic_ns"] = time.monotonic_ns()
        if (
            after != threads
            or tuple(sorted(int(value) for value in restored))
            != tuple(authority["prior_signal_mask"])
        ):
            raise RuntimeError("sandbox network anchor restoration differs")


def _inventory() -> dict[str, object]:
    return asdict(native_detailed_file_descriptor_inventory(os.getpid()))


@dataclass(slots=True)
class SandboxNetworkTrapAuthority:
    root: Path
    root_fd: int
    root_identity: dict[str, object]
    tcp4: socket.socket
    tcp6: socket.socket
    udp4: socket.socket
    udp6: socket.socket
    unix_listener: socket.socket
    opened_at_monotonic_ns: int
    positive_controls: tuple[dict[str, object], ...]
    record_sha256: str
    _closed: bool = False

    @classmethod
    def open(
        cls,
        *,
        root: Path,
        root_fd: int,
        control_nonce: bytes,
    ) -> "SandboxNetworkTrapAuthority":
        if not control_nonce or len(control_nonce) > 256:
            raise ValueError("sandbox network control nonce differs")
        identity = _root_identity(root, root_fd)
        if os.listdir(root_fd):
            raise RuntimeError("sandbox network trap root was not empty")
        sockets: list[socket.socket] = []
        opened_at = time.monotonic_ns()
        try:
            tcp4 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sockets.append(tcp4)
            tcp4.bind(("127.0.0.1", 0))
            tcp4.listen(8)
            tcp6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            sockets.append(tcp6)
            tcp6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            tcp6.bind(("::1", 0))
            tcp6.listen(8)
            udp4 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sockets.append(udp4)
            udp4.bind(("127.0.0.1", 0))
            udp6 = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
            sockets.append(udp6)
            udp6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            udp6.bind(("::1", 0))
            unix_listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sockets.append(unix_listener)
            with _anchored_directory(root_fd):
                unix_listener.bind(_UNIX_CONNECT_NAME)
            unix_listener.listen(8)
            provisional = cls(
                root=root,
                root_fd=root_fd,
                root_identity=identity,
                tcp4=tcp4,
                tcp6=tcp6,
                udp4=udp4,
                udp6=udp6,
                unix_listener=unix_listener,
                opened_at_monotonic_ns=opened_at,
                positive_controls=(),
                record_sha256="0" * 64,
            )
            controls = provisional._run_positive_controls(control_nonce)
            provisional.positive_controls = controls
            provisional.record_sha256 = _canonical_sha256(
                provisional.projection(include_controls=True)
            )
            return provisional
        except BaseException:
            for endpoint in reversed(sockets):
                endpoint.close()
            with _anchored_directory(root_fd):
                try:
                    os.unlink(_UNIX_CONNECT_NAME)
                except FileNotFoundError:
                    pass
            raise

    def _stream_control(
        self,
        *,
        role: str,
        operation: str,
        server: socket.socket,
        address: object,
        family: int,
        payload: bytes,
        anchored: bool = False,
    ) -> dict[str, object]:
        started = time.monotonic_ns()
        client = socket.socket(family, socket.SOCK_STREAM)
        accepted: socket.socket | None = None
        try:
            if anchored:
                with _anchored_directory(self.root_fd):
                    client.connect(address)
            else:
                client.connect(address)
            accepted, _peer = server.accept()
            sent = client.send(payload)
            received = accepted.recv(len(payload) + 1)
            if sent != len(payload) or received != payload:
                raise RuntimeError("sandbox stream positive control differs")
            inventory = _inventory()
            return {
                "role": role,
                "operation": operation,
                "syscall_stage": "connect-send-receive",
                "syscall_return": 0,
                "secondary_syscall_return": sent,
                "payload_hex": payload.hex(),
                "payload_sha256": hashlib.sha256(payload).hexdigest(),
                "bytes_sent": sent,
                "bytes_received": len(received),
                "accept_count": 1,
                "datagram_count": 0,
                "fd_inventory": inventory,
                "started_monotonic_ns": started,
                "completed_monotonic_ns": time.monotonic_ns(),
            }
        finally:
            if accepted is not None:
                accepted.close()
            client.close()

    def _datagram_control(
        self,
        *,
        role: str,
        operation: str,
        server: socket.socket,
        address: object,
        family: int,
        payload: bytes,
    ) -> dict[str, object]:
        started = time.monotonic_ns()
        client = socket.socket(family, socket.SOCK_DGRAM)
        try:
            sent = client.sendto(payload, address)
            received, source = server.recvfrom(len(payload) + 1)
            if sent != len(payload) or received != payload:
                raise RuntimeError("sandbox datagram positive control differs")
            return {
                "role": role,
                "operation": operation,
                "syscall_stage": "sendto-recvfrom",
                "syscall_return": sent,
                "secondary_syscall_return": len(received),
                "payload_hex": payload.hex(),
                "payload_sha256": hashlib.sha256(payload).hexdigest(),
                "source": list(source),
                "bytes_sent": sent,
                "bytes_received": len(received),
                "accept_count": 0,
                "datagram_count": 1,
                "fd_inventory": _inventory(),
                "started_monotonic_ns": started,
                "completed_monotonic_ns": time.monotonic_ns(),
            }
        finally:
            client.close()

    def _bind_control(
        self, *, role: str, family: int, address: object
    ) -> dict[str, object]:
        started = time.monotonic_ns()
        endpoint = socket.socket(family, socket.SOCK_STREAM)
        relative: str | None = None
        try:
            if family == socket.AF_UNIX:
                relative = f"{role}-positive-bind.sock"
                with _anchored_directory(self.root_fd):
                    endpoint.bind(relative)
            else:
                endpoint.bind(address)
            endpoint.listen(1)
            inventory = _inventory()
            return {
                "role": role,
                "operation": {
                    socket.AF_INET: "ipv4_bind_listen",
                    socket.AF_INET6: "ipv6_bind_listen",
                    socket.AF_UNIX: "unix_bind",
                }[family],
                "syscall_stage": "bind-listen-getsockname",
                "syscall_return": 0,
                "secondary_syscall_return": 0,
                "getsockname": repr(endpoint.getsockname()),
                "bytes_sent": 0,
                "bytes_received": 0,
                "accept_count": 0,
                "datagram_count": 0,
                "fd_inventory": inventory,
                "started_monotonic_ns": started,
                "completed_monotonic_ns": time.monotonic_ns(),
            }
        finally:
            endpoint.close()
            if relative is not None:
                with _anchored_directory(self.root_fd):
                    os.unlink(relative)

    def _run_positive_controls(
        self, control_nonce: bytes
    ) -> tuple[dict[str, object], ...]:
        controls: list[dict[str, object]] = []
        for role in _ROLE_NAMES:
            for operation, server, address, family, anchored in (
                (
                    "ipv4_tcp_connect",
                    self.tcp4,
                    self.tcp4.getsockname(),
                    socket.AF_INET,
                    False,
                ),
                (
                    "ipv6_tcp_connect",
                    self.tcp6,
                    self.tcp6.getsockname(),
                    socket.AF_INET6,
                    False,
                ),
                (
                    "unix_connect",
                    self.unix_listener,
                    _UNIX_CONNECT_NAME,
                    socket.AF_UNIX,
                    True,
                ),
            ):
                nonce_sha = hashlib.sha256(
                    control_nonce + role.encode() + operation.encode()
                ).hexdigest()
                payload = b"KSNP1" + bytes.fromhex(nonce_sha)
                control = self._stream_control(
                    role=role,
                    operation=operation,
                    server=server,
                    address=address,
                    family=family,
                    payload=payload,
                    anchored=anchored,
                )
                control["control_nonce_sha256"] = nonce_sha
                controls.append(control)
            for operation, server, address, family in (
                (
                    "ipv4_udp_sendto",
                    self.udp4,
                    self.udp4.getsockname(),
                    socket.AF_INET,
                ),
                (
                    "ipv6_udp_sendto",
                    self.udp6,
                    self.udp6.getsockname(),
                    socket.AF_INET6,
                ),
            ):
                nonce_sha = hashlib.sha256(
                    control_nonce + role.encode() + operation.encode()
                ).hexdigest()
                payload = b"KSNP1" + bytes.fromhex(nonce_sha)
                control = self._datagram_control(
                    role=role,
                    operation=operation,
                    server=server,
                    address=address,
                    family=family,
                    payload=payload,
                )
                control["control_nonce_sha256"] = nonce_sha
                controls.append(control)
            controls.extend(
                (
                    self._bind_control(
                        role=role,
                        family=socket.AF_INET,
                        address=("127.0.0.1", 0),
                    ),
                    self._bind_control(
                        role=role,
                        family=socket.AF_INET6,
                        address=("::1", 0),
                    ),
                    self._bind_control(
                        role=role,
                        family=socket.AF_UNIX,
                        address=f"{role}-positive-bind.sock",
                    ),
                )
            )
        return tuple(controls)

    def role_network_operations(self, role: str) -> tuple[dict[str, object], ...]:
        if role not in _ROLE_NAMES or self._closed:
            raise ValueError("sandbox network role differs")
        targets = (
            ("ipv4_tcp_connect", 1, socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, -1, _sockaddr_in(*self.tcp4.getsockname()), b""),
            ("ipv6_tcp_connect", 1, socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, -1, _sockaddr_in6(*self.tcp6.getsockname()[:2]), b""),
            ("ipv4_udp_sendto", 2, socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP, -1, _sockaddr_in(*self.udp4.getsockname()), b"probe123"),
            ("ipv6_udp_sendto", 2, socket.AF_INET6, socket.SOCK_DGRAM, socket.IPPROTO_UDP, -1, _sockaddr_in6(*self.udp6.getsockname()[:2]), b"probe123"),
            ("unix_connect", 1, socket.AF_UNIX, socket.SOCK_STREAM, 0, self.root_fd, _sockaddr_un(_UNIX_CONNECT_NAME), b""),
            ("ipv4_bind_listen", 3, socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, -1, _sockaddr_in("127.0.0.1", 0), b""),
            ("ipv6_bind_listen", 3, socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, -1, _sockaddr_in6("::1", 0), b""),
            ("unix_bind", 3, socket.AF_UNIX, socket.SOCK_STREAM, 0, self.root_fd, _sockaddr_un(f"{role}-bind-denied.sock"), b""),
        )
        return tuple(
            {
                "operation": operation,
                "kind": "network",
                "operation_code": code,
                "held_directory_fd": descriptor,
                "domain": int(family),
                "socket_type": int(socket_type),
                "protocol": int(protocol),
                "sockaddr_hex": sockaddr.hex(),
                "payload_hex": payload.hex(),
            }
            for operation, code, family, socket_type, protocol, descriptor, sockaddr, payload in targets
        )

    def projection(self, *, include_controls: bool) -> dict[str, object]:
        value = {
            "schema_id": NETWORK_TRAP_SCHEMA,
            "root": self.root_identity,
            "opened_at_monotonic_ns": self.opened_at_monotonic_ns,
            "targets": {
                "tcp4": list(self.tcp4.getsockname()),
                "tcp6": list(self.tcp6.getsockname()),
                "udp4": list(self.udp4.getsockname()),
                "udp6": list(self.udp6.getsockname()),
                "unix_connect_relative_path": _UNIX_CONNECT_NAME,
            },
            "positive_controls": (
                list(self.positive_controls) if include_controls else []
            ),
        }
        return value

    def close(self) -> dict[str, object]:
        if self._closed:
            raise RuntimeError("sandbox network traps already closed")
        terminal_started = time.monotonic_ns()
        try:
            readable, _writable, _exceptional = select.select(
                (self.tcp4, self.tcp6, self.udp4, self.udp6, self.unix_listener),
                (),
                (),
                0,
            )
            if readable:
                raise RuntimeError("sandbox denied network probe reached a trap")
            for role in _ROLE_NAMES:
                with _anchored_directory(self.root_fd):
                    if os.path.lexists(f"{role}-bind-denied.sock"):
                        raise RuntimeError(
                            "sandbox denied AF_UNIX bind changed target"
                        )
            for endpoint in (
                self.tcp4,
                self.tcp6,
                self.udp4,
                self.udp6,
                self.unix_listener,
            ):
                endpoint.close()
            with _anchored_directory(self.root_fd):
                os.unlink(_UNIX_CONNECT_NAME)
            if os.listdir(self.root_fd):
                raise RuntimeError("sandbox network trap root retained residue")
            self._closed = True
        except BaseException:
            self.abort()
            raise
        terminal = {
            "schema_id": "phase-latency-sandbox-network-traps-terminal-v1",
            "authority_record_sha256": self.record_sha256,
            "root": _root_identity(self.root, self.root_fd),
            "terminal_started_monotonic_ns": terminal_started,
            "terminal_completed_monotonic_ns": time.monotonic_ns(),
            "all_traps_unchanged": True,
            "root_empty_after_close": True,
        }
        terminal["record_sha256"] = _canonical_sha256(terminal)
        return terminal

    def abort(self) -> None:
        if self._closed:
            return
        self._closed = True
        for endpoint in (
            self.tcp4,
            self.tcp6,
            self.udp4,
            self.udp6,
            self.unix_listener,
        ):
            try:
                endpoint.close()
            except OSError:
                pass
        try:
            with _anchored_directory(self.root_fd):
                for name in (
                    _UNIX_CONNECT_NAME,
                    *(f"{role}-positive-bind.sock" for role in _ROLE_NAMES),
                    *(f"{role}-bind-denied.sock" for role in _ROLE_NAMES),
                ):
                    try:
                        os.unlink(name)
                    except FileNotFoundError:
                        pass
        except OSError:
            pass


__all__ = [
    "NETWORK_TRAP_SCHEMA",
    "SandboxNetworkTrapAuthority",
]
