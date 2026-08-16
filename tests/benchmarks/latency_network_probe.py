"""Content-free descendant probe for the LAT-US01 OS network sandbox."""

from __future__ import annotations

import errno
import json
import socket
import subprocess
import sys
from collections.abc import Callable

from tests.benchmarks.latency_isolation import NetworkIsolationError


def _tcp_result(family: int, address: tuple[object, ...]) -> str:
    channel = socket.socket(family, socket.SOCK_STREAM)
    channel.settimeout(0.25)
    try:
        channel.connect(address)
    except OSError as error:
        return errno.errorcode.get(error.errno or 0, "UNKNOWN")
    finally:
        channel.close()
    return "CONNECTED"


def _udp_result(family: int, address: tuple[object, ...]) -> str:
    channel = socket.socket(family, socket.SOCK_DGRAM)
    try:
        channel.sendto(b"probe", address)
    except OSError as error:
        return errno.errorcode.get(error.errno or 0, "UNKNOWN")
    finally:
        channel.close()
    return "SENT"


def _bind_result(family: int, address: tuple[object, ...]) -> str:
    channel = socket.socket(family, socket.SOCK_STREAM)
    try:
        channel.bind(address)
        channel.listen(1)
    except OSError as error:
        return errno.errorcode.get(error.errno or 0, "UNKNOWN")
    finally:
        channel.close()
    return "LISTENING"


def _filesystem_unix_result(path: str) -> str:
    channel = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        channel.connect(path)
    except OSError as error:
        return errno.errorcode.get(error.errno or 0, "UNKNOWN")
    finally:
        channel.close()
    return "CONNECTED"


def _guarded_call(operation: Callable[[], object]) -> str:
    try:
        operation()
    except NetworkIsolationError:
        return "EPERM"
    except RuntimeError as error:
        if (
            type(error).__name__ == "NetworkIsolationError"
            and type(error).__module__ == "_phase_latency_byte_pinned_network_guard"
        ):
            return "EPERM"
        raise
    except PermissionError as error:
        return errno.errorcode.get(error.errno or 0, "UNKNOWN")
    except OSError as error:
        return errno.errorcode.get(error.errno or 0, "UNKNOWN")
    return "ALLOWED"


def _python_guard_result() -> dict[str, object]:
    import sitecustomize

    guard = sitecustomize.PHASE_LATENCY_NETWORK_GUARD
    left, right = socket.socketpair()
    try:
        left.sendall(b"x")
        unix_roundtrip = right.recv(1) == b"x"
    finally:
        left.close()
        right.close()
    fqdn_before = guard.denied_attempts
    fqdn_result = _guarded_call(lambda: socket.getfqdn("blocked.invalid"))
    fqdn_denied = fqdn_result == "EPERM" and guard.denied_attempts == fqdn_before + 1
    return {
        "bindings_exact": guard.bindings_exact,
        "ipv4_socket_create": _guarded_call(
            lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        ),
        "ipv6_socket_create": _guarded_call(
            lambda: socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        ),
        "getaddrinfo": _guarded_call(
            lambda: socket.getaddrinfo("blocked.invalid", 443)
        ),
        "gethostbyaddr": _guarded_call(lambda: socket.gethostbyaddr("127.0.0.1")),
        "gethostbyname": _guarded_call(lambda: socket.gethostbyname("blocked.invalid")),
        "gethostbyname_ex": _guarded_call(
            lambda: socket.gethostbyname_ex("blocked.invalid")
        ),
        "getnameinfo": _guarded_call(lambda: socket.getnameinfo(("127.0.0.1", 443), 0)),
        "getfqdn_denied_via_guarded_primitive": fqdn_denied,
        "ipv6_capability_suppressed": socket.has_ipv6 is False,
        "unix_socketpair_roundtrip": unix_roundtrip,
        "denied_attempt_count": guard.denied_attempts,
    }


def _leaf_result(filesystem_unix_path: str) -> dict[str, object]:
    left, right = socket.socketpair()
    try:
        left.sendall(b"x")
        unix_roundtrip = right.recv(1) == b"x"
    finally:
        left.close()
        right.close()
    return {
        "ipv4_tcp_connect": _tcp_result(
            socket.AF_INET,
            ("127.0.0.1", 9),
        ),
        "ipv4_udp_send": _udp_result(
            socket.AF_INET,
            ("127.0.0.1", 9),
        ),
        "ipv4_tcp_bind": _bind_result(
            socket.AF_INET,
            ("127.0.0.1", 0),
        ),
        "ipv6_tcp_connect": _tcp_result(
            socket.AF_INET6,
            ("::1", 9, 0, 0),
        ),
        "ipv6_udp_send": _udp_result(
            socket.AF_INET6,
            ("::1", 9, 0, 0),
        ),
        "ipv6_tcp_bind": _bind_result(
            socket.AF_INET6,
            ("::1", 0, 0, 0),
        ),
        "unix_socketpair_roundtrip": unix_roundtrip,
        "filesystem_unix_connect": _filesystem_unix_result(filesystem_unix_path),
    }


def main() -> int:
    if sys.argv[1:] == ["--python-guard"]:
        result = _python_guard_result()
    elif len(sys.argv) == 3 and sys.argv[1] == "--leaf":
        result = _leaf_result(sys.argv[2])
    elif len(sys.argv) == 2:
        completed = subprocess.run(
            (
                sys.executable,
                "-S",
                "-m",
                "tests.benchmarks.latency_network_probe",
                "--leaf",
                sys.argv[1],
            ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5.0,
        )
        if completed.returncode != 0 or len(completed.stdout) > 4_096:
            return 2
        value = json.loads(completed.stdout)
        if not isinstance(value, dict):
            return 3
        result = dict(value)
        result["nested_subprocess_exit_code"] = completed.returncode
    else:
        return 4
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
