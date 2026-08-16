"""Controller-owned native sandbox plans and live trap authority."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat

from app.services.parser_sandbox_materialization import (
    SandboxProbeMaterialization,
)
from app.services.parser_sandbox_network_traps import (
    SandboxNetworkTrapAuthority,
)
from app.services.parser_sandbox_role_plan import (
    SandboxRoleDirectoryAuthority,
    build_child_sandbox_probe_plan,
    build_root_sandbox_probe_plan,
)


def _source_bytes(path: Path, *, maximum_bytes: int) -> bytes:
    resolved = path.resolve(strict=True)
    observed = resolved.lstat()
    if (
        resolved != path
        or path.is_symlink()
        or not stat.S_ISREG(observed.st_mode)
        or observed.st_size <= 0
        or observed.st_size > maximum_bytes
        or observed.st_uid not in {0, os.geteuid()}
        or observed.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        raise RuntimeError("sandbox executor source custody differs")
    descriptor = os.open(
        resolved,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        before = os.fstat(descriptor)
        chunks: list[bytes] = []
        remaining = observed.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise RuntimeError("sandbox executor source read was short")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise RuntimeError("sandbox executor source exceeded custody")
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    stable = (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_uid",
        "st_nlink",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
    )
    if any(getattr(before, name) != getattr(after, name) for name in stable):
        raise RuntimeError("sandbox executor source changed while reading")
    return b"".join(chunks)


@dataclass(slots=True)
class SandboxAttemptProbeAuthority:
    materialization: SandboxProbeMaterialization
    directories: SandboxRoleDirectoryAuthority
    network_traps: SandboxNetworkTrapAuthority
    worker_plan: dict[str, object]
    broker_plan: dict[str, object]
    child_plan: dict[str, object]
    child_report_reservation_bytes: int
    root_executor_source_sha256: str
    child_executor_source_hex: str
    child_executor_source_sha256: str
    _closed: bool = False

    @classmethod
    def open(
        cls,
        *,
        materialization: SandboxProbeMaterialization,
        attempt_id: str,
        attempt_nonce_sha256: str,
        scope_sha256: str,
        worker_profile_sha256: str,
        broker_profile_sha256: str,
        native_closure_sha256: str,
        artifact_read_path: Path,
        tessdata_read_path: Path,
        staged_executable_read_path: Path,
        worker_scratch_root: Path,
        worker_scratch_fd: int,
        probe_library_path: Path,
        probe_library_sha256: str,
        control_nonce: bytes,
    ) -> "SandboxAttemptProbeAuthority":
        from app.services import parser_sandbox_probe
        from app.services import tesseract_child_sandbox_probe

        root_source = _source_bytes(
            Path(parser_sandbox_probe.__file__).resolve(strict=True),
            maximum_bytes=256 * 1024,
        )
        child_source = _source_bytes(
            Path(tesseract_child_sandbox_probe.__file__).resolve(strict=True),
            maximum_bytes=256 * 1024,
        )
        directories: SandboxRoleDirectoryAuthority | None = None
        network: SandboxNetworkTrapAuthority | None = None
        try:
            # The live AF_UNIX trap materializes its private endpoint beneath
            # network_trap_root.  Establish that lifecycle before snapshotting
            # the nine held-directory identities so the retained nlink/path
            # authority describes the exact state inherited by every role.
            network = SandboxNetworkTrapAuthority.open(
                root=materialization.roots["network_trap_root"],
                root_fd=materialization.root_fds["network_trap_root"],
                control_nonce=control_nonce,
            )
            directories = SandboxRoleDirectoryAuthority.open(
                materialization=materialization,
                artifact_read_path=artifact_read_path,
                tessdata_read_path=tessdata_read_path,
                staged_executable_read_path=staged_executable_read_path,
            )
            root_sha = hashlib.sha256(root_source).hexdigest()
            child_sha = hashlib.sha256(child_source).hexdigest()
            child_plan, child_reservation = build_child_sandbox_probe_plan(
                attempt_id=attempt_id,
                attempt_nonce_sha256=attempt_nonce_sha256,
                scope_sha256=scope_sha256,
                profile_sha256=broker_profile_sha256,
                native_closure_sha256=native_closure_sha256,
                executor_source_sha256=child_sha,
                probe_library_path=probe_library_path,
                probe_library_sha256=probe_library_sha256,
                directories=directories,
                network_operations=network.role_network_operations(
                    "tesseract_child"
                ),
            )
            worker_plan = build_root_sandbox_probe_plan(
                attempt_id=attempt_id,
                attempt_nonce_sha256=attempt_nonce_sha256,
                scope_sha256=scope_sha256,
                role="parser_worker",
                profile_sha256=worker_profile_sha256,
                native_closure_sha256=native_closure_sha256,
                executor_source_sha256=root_sha,
                probe_library_path=probe_library_path,
                probe_library_sha256=probe_library_sha256,
                directories=directories,
                network_operations=network.role_network_operations(
                    "parser_worker"
                ),
                worker_scratch_root=worker_scratch_root,
                worker_scratch_fd=worker_scratch_fd,
            )
            broker_plan = build_root_sandbox_probe_plan(
                attempt_id=attempt_id,
                attempt_nonce_sha256=attempt_nonce_sha256,
                scope_sha256=scope_sha256,
                role="tesseract_broker",
                profile_sha256=broker_profile_sha256,
                native_closure_sha256=native_closure_sha256,
                executor_source_sha256=root_sha,
                probe_library_path=probe_library_path,
                probe_library_sha256=probe_library_sha256,
                directories=directories,
                network_operations=network.role_network_operations(
                    "tesseract_broker"
                ),
            )
            return cls(
                materialization=materialization,
                directories=directories,
                network_traps=network,
                worker_plan=worker_plan,
                broker_plan=broker_plan,
                child_plan=child_plan,
                child_report_reservation_bytes=child_reservation,
                root_executor_source_sha256=root_sha,
                child_executor_source_hex=child_source.hex(),
                child_executor_source_sha256=child_sha,
            )
        except BaseException:
            if network is not None:
                network.abort()
            if directories is not None:
                directories.close()
            raise

    @property
    def broker_directory_descriptors(self) -> tuple[int, ...]:
        return tuple(
            int(item["descriptor"])
            for item in self.broker_plan["held_directories"]
        )

    @property
    def worker_directory_descriptors(self) -> tuple[int, ...]:
        return tuple(
            int(item["descriptor"])
            for item in self.worker_plan["held_directories"]
        )

    def close_terminal(self) -> dict[str, object]:
        if self._closed:
            raise RuntimeError("sandbox attempt probe authority already closed")
        terminal = self.network_traps.close()
        self.directories.close()
        self._closed = True
        return terminal

    def abort(self) -> None:
        if self._closed:
            return
        self.network_traps.abort()
        self.directories.close()
        self._closed = True


__all__ = ["SandboxAttemptProbeAuthority"]
