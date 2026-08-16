"""Fail-closed byte-bound network denial inherited by latency Python trees."""

from __future__ import annotations

import hashlib
import os
import stat

try:
    if os.environ.get("PHASE_LATENCY_CHILD_GUARD") != "all-python-processes-v1":
        raise RuntimeError("latency child network guard policy marker differs")
    if not __import__("sys").flags.safe_path:
        raise RuntimeError("latency child guard requires Python safe-path mode")
    implementation_path = os.environ["PHASE_LATENCY_GUARD_IMPLEMENTATION_PATH"]
    expected_size = int(
        os.environ["PHASE_LATENCY_GUARD_IMPLEMENTATION_SIZE_BYTES"]
    )
    expected_sha256 = os.environ[
        "PHASE_LATENCY_GUARD_IMPLEMENTATION_SHA256"
    ]
    if (
        expected_size <= 0
        or expected_size > 131_072
        or len(expected_sha256) != 64
        or not implementation_path.startswith("/")
    ):
        raise RuntimeError("latency child guard implementation identity differs")
    current = os.sep
    for component in implementation_path.split(os.sep)[1:-1]:
        current = os.path.join(current, component)
        if stat.S_ISLNK(os.lstat(current).st_mode):
            raise RuntimeError("latency child guard implementation path is linked")
    before = os.lstat(implementation_path)
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or before.st_size != expected_size
    ):
        raise RuntimeError("latency child guard implementation custody differs")
    descriptor = os.open(
        implementation_path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
    )
    opened = os.fstat(descriptor)
    if (
        opened.st_dev != before.st_dev
        or opened.st_ino != before.st_ino
        or opened.st_size != before.st_size
        or opened.st_mtime_ns != before.st_mtime_ns
    ):
        os.close(descriptor)
        raise RuntimeError("latency child guard implementation changed before open")
    with os.fdopen(descriptor, "rb") as stream:
        implementation = stream.read(expected_size + 1)
        after = os.fstat(stream.fileno())
    if (
        len(implementation) != expected_size
        or after.st_dev != opened.st_dev
        or after.st_ino != opened.st_ino
        or after.st_size != opened.st_size
        or after.st_mtime_ns != opened.st_mtime_ns
        or hashlib.sha256(implementation).hexdigest() != expected_sha256
    ):
        raise RuntimeError("latency child guard implementation bytes differ")
    namespace = {
        "__file__": implementation_path,
        "__name__": "_phase_latency_byte_pinned_network_guard",
        "__package__": "",
    }
    # The implementation is read, bounded, and SHA-256 verified immediately above.
    exec(  # noqa: S102 - execute only the byte-pinned guard implementation
        compile(implementation, implementation_path, "exec"), namespace
    )
    guard_type = namespace["NoEgressGuard"]
    PHASE_LATENCY_NETWORK_GUARD = guard_type()
    PHASE_LATENCY_NETWORK_GUARD.install()
except BaseException:  # noqa: BLE001 - bootstrap must fail closed for every throwable
    os._exit(86)
