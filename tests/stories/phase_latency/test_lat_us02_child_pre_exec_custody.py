from __future__ import annotations

import os
import selectors
import socket
import stat
from types import SimpleNamespace

import pytest

from app.services import tesseract_child_exec as child_exec
from app.services.tesseract_broker_native import (
    NativeFileDescriptorInventory,
    native_detailed_file_descriptor_inventory,
    native_file_descriptor_inventory,
)


def _install_fake_descriptor_observation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        child_exec,
        "native_file_descriptor_inventory",
        lambda _pid: (
            (0, 6),
            (1, 6),
            (2, 6),
            (3, 6),
            (4, 6),
            (5, 1),
        ),
    )

    def fake_fstat(fd: int) -> SimpleNamespace:
        return SimpleNamespace(
            st_dev=7 if fd == 5 else 0,
            st_ino=100 + fd,
            st_mode=(stat.S_IFREG | 0o500) if fd == 5 else (stat.S_IFIFO | 0o600),
        )

    monkeypatch.setattr(child_exec.os, "fstat", fake_fstat)
    monkeypatch.setattr(
        child_exec.fcntl,
        "fcntl",
        lambda fd, _operation: child_exec.fcntl.FD_CLOEXEC if fd >= 3 else 0,
    )


def test_native_fd_inventory_is_stable_and_observes_pipe_birth() -> None:
    before = native_file_descriptor_inventory(os.getpid())
    reader, writer = os.pipe()
    try:
        during = native_file_descriptor_inventory(os.getpid())
    finally:
        os.close(reader)
        os.close(writer)
    assert during == tuple(sorted((*before, (reader, 6), (writer, 6))))
    assert native_file_descriptor_inventory(os.getpid()) == before


def test_detailed_native_fd_inventory_binds_socket_kqueue_and_flags() -> None:
    left, right = socket.socketpair()
    left_fd = left.fileno()
    selector = selectors.KqueueSelector()
    selector.register(left, selectors.EVENT_READ)
    try:
        observed = native_detailed_file_descriptor_inventory(os.getpid())
    finally:
        selector.close()
        left.close()
        right.close()
    assert type(observed) is NativeFileDescriptorInventory
    by_fd = {item.fd: item for item in observed.descriptors}
    assert by_fd[left_fd].socket is not None
    sockets = tuple(item.socket for item in observed.descriptors if item.socket)
    assert len(sockets) >= 2
    assert all(item.family == socket.AF_UNIX for item in sockets)
    assert all(len(item.local_identity_sha256) == 64 for item in sockets)
    assert all(len(item.peer_identity_sha256) == 64 for item in sockets)
    assert any(item.kqueue is not None for item in observed.descriptors)
    assert all(type(item.close_on_exec) is bool for item in observed.descriptors)


def test_detailed_native_fd_inventory_uses_reciprocal_endpoint_identities() -> None:
    left, right = socket.socketpair()
    reader, writer = os.pipe()
    try:
        observed = native_detailed_file_descriptor_inventory(os.getpid())
        by_fd = {item.fd: item for item in observed.descriptors}
        left_identity = by_fd[left.fileno()].socket
        right_identity = by_fd[right.fileno()].socket
        reader_identity = by_fd[reader].pipe
        writer_identity = by_fd[writer].pipe
        assert left_identity is not None
        assert right_identity is not None
        assert reader_identity is not None
        assert writer_identity is not None
        assert (
            left_identity.local_identity_sha256
            == right_identity.peer_identity_sha256
        )
        assert (
            left_identity.peer_identity_sha256
            == right_identity.local_identity_sha256
        )
        assert (
            reader_identity.local_handle_sha256
            == writer_identity.peer_handle_sha256
        )
        assert (
            reader_identity.peer_handle_sha256
            == writer_identity.local_handle_sha256
        )
    finally:
        os.close(reader)
        os.close(writer)
        left.close()
        right.close()


def test_guard_retains_recomputable_fd_roles_not_a_literal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_descriptor_observation(monkeypatch)
    observed = child_exec._guard_descriptor_inventory()
    assert tuple(item["fd"] for item in observed) == (0, 1, 2, 3, 4, 5)
    assert tuple(item["kernel_fd_type"] for item in observed) == (
        6,
        6,
        6,
        6,
        6,
        1,
    )
    assert observed[5]["role"] == "staged_executable"
    assert observed[5]["stat_mode_type"] == stat.S_IFREG


@pytest.mark.parametrize(
    "inventory",
    (
        ((0, 6), (1, 6), (2, 6), (3, 6), (4, 6), (5, 1), (6, 6)),
        ((0, 1), (1, 6), (2, 6), (3, 6), (4, 6), (5, 1)),
    ),
)
def test_guard_rejects_leaked_or_substituted_low_fd(
    monkeypatch: pytest.MonkeyPatch,
    inventory: tuple[tuple[int, int], ...],
) -> None:
    _install_fake_descriptor_observation(monkeypatch)
    monkeypatch.setattr(
        child_exec,
        "native_file_descriptor_inventory",
        lambda _pid: inventory,
    )
    with pytest.raises(RuntimeError, match="file-descriptor inventory differs"):
        child_exec._guard_descriptor_inventory()


def test_guard_rejects_thread_appearing_during_fd_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_descriptor_observation(monkeypatch)
    inventories = iter(((101,), (101, 202)))
    monkeypatch.setattr(
        child_exec,
        "native_thread_inventory",
        lambda _pid: next(inventories),
    )
    with pytest.raises(RuntimeError, match="native thread inventory differs"):
        child_exec._guard_kernel_inventory()
