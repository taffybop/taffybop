"""Canonical controller-authored native sandbox role plans."""

from __future__ import annotations

from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Mapping, Sequence

from app.services.parser_sandbox_materialization import SandboxProbeMaterialization
from app.services.tesseract_child_sandbox_probe import (
    CHILD_SANDBOX_EXECUTOR_AUTHORITY,
    CHILD_SANDBOX_HELD_DIRECTORY_ROLES,
    CHILD_SANDBOX_PLAN_SCHEMA,
    child_sandbox_probe_report_reservation_bytes,
)


ROOT_SANDBOX_EXECUTOR_AUTHORITY = (
    "workspace-python-native-ctypes-seatbelt-probe-v1"
)
ROOT_SANDBOX_HELD_DIRECTORY_ROLES = {
    "tesseract_broker": CHILD_SANDBOX_HELD_DIRECTORY_ROLES,
    "parser_worker": (
        *CHILD_SANDBOX_HELD_DIRECTORY_ROLES,
        "worker_scratch_root",
    ),
}


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


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


def _portable_leaf(path: Path, *, label: str) -> str:
    name = path.name
    if (
        not name
        or name in {".", ".."}
        or "/" in name
        or "\0" in name
        or len(name.encode("utf-8")) > 512
    ):
        raise ValueError(f"sandbox {label} leaf differs")
    return name


def _held_directory(
    *, role: str, path: Path, descriptor: int
) -> dict[str, object]:
    resolved = path.resolve(strict=True)
    path_stat = path.lstat()
    fd_stat = os.fstat(descriptor)
    if (
        resolved != path
        or path.is_symlink()
        or not stat.S_ISDIR(path_stat.st_mode)
        or (path_stat.st_dev, path_stat.st_ino, path_stat.st_mode)
        != (fd_stat.st_dev, fd_stat.st_ino, fd_stat.st_mode)
        or path_stat.st_uid != os.geteuid()
        or fd_stat.st_ino <= 0
        or fd_stat.st_nlink <= 0
    ):
        raise RuntimeError(f"sandbox {role} directory identity differs")
    return {
        "role": role,
        "descriptor": descriptor,
        "resolved_path": str(resolved),
        "path_sha256": hashlib.sha256(
            str(resolved).encode("utf-8")
        ).hexdigest(),
        "device": fd_stat.st_dev,
        "inode": fd_stat.st_ino,
        "mode": fd_stat.st_mode,
        "uid": fd_stat.st_uid,
        "nlink": fd_stat.st_nlink,
        "open_flags": int(fcntl.fcntl(descriptor, fcntl.F_GETFL)),
    }


@dataclass(slots=True)
class SandboxRoleDirectoryAuthority:
    materialization: SandboxProbeMaterialization
    artifact_read_path: Path
    tessdata_read_path: Path
    staged_executable_read_path: Path
    held_directories: tuple[dict[str, object], ...]
    owned_descriptors: tuple[int, int, int]
    _closed: bool = False

    @classmethod
    def open(
        cls,
        *,
        materialization: SandboxProbeMaterialization,
        artifact_read_path: Path,
        tessdata_read_path: Path,
        staged_executable_read_path: Path,
    ) -> "SandboxRoleDirectoryAuthority":
        read_paths = tuple(
            path.resolve(strict=True)
            for path in (
                artifact_read_path,
                tessdata_read_path,
                staged_executable_read_path,
            )
        )
        if any(
            path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode)
            for path in read_paths
        ):
            raise RuntimeError("sandbox production read source differs")
        for label, path in zip(
            ("artifact", "tessdata", "staged executable"),
            read_paths,
            strict=True,
        ):
            _portable_leaf(path, label=label)
        opened: list[int] = []
        try:
            for path in read_paths:
                opened.append(os.open(path.parent, _directory_flags()))
            by_role = {
                "artifact_probe_clone_root": materialization.root_fds[
                    "artifact_probe_clone"
                ],
                "artifact_root": opened[0],
                "input_probe_root": materialization.root_fds["input_probe_root"],
                "network_trap_root": materialization.root_fds[
                    "network_trap_root"
                ],
                "outside_probe_root": materialization.root_fds[
                    "outside_probe_root"
                ],
                "staged_executable_probe_clone_root": (
                    materialization.root_fds[
                        "staged_executable_probe_clone"
                    ]
                ),
                "staged_executable_root": opened[2],
                "tessdata_probe_clone_root": materialization.root_fds[
                    "tessdata_probe_clone"
                ],
                "tessdata_root": opened[1],
            }
            held = tuple(
                _held_directory(
                    role=role,
                    path=(
                        read_paths[0].parent
                        if role == "artifact_root"
                        else read_paths[1].parent
                        if role == "tessdata_root"
                        else read_paths[2].parent
                        if role == "staged_executable_root"
                        else materialization.roots[
                            {
                                "artifact_probe_clone_root": "artifact_probe_clone",
                                "input_probe_root": "input_probe_root",
                                "network_trap_root": "network_trap_root",
                                "outside_probe_root": "outside_probe_root",
                                "staged_executable_probe_clone_root": (
                                    "staged_executable_probe_clone"
                                ),
                                "tessdata_probe_clone_root": (
                                    "tessdata_probe_clone"
                                ),
                            }[role]
                        ]
                    ),
                    descriptor=by_role[role],
                )
                for role in CHILD_SANDBOX_HELD_DIRECTORY_ROLES
            )
            return cls(
                materialization=materialization,
                artifact_read_path=read_paths[0],
                tessdata_read_path=read_paths[1],
                staged_executable_read_path=read_paths[2],
                held_directories=held,
                owned_descriptors=(opened[0], opened[1], opened[2]),
            )
        except BaseException:
            for descriptor in opened:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            raise

    @property
    def descriptors_by_role(self) -> dict[str, int]:
        if self._closed:
            raise RuntimeError("sandbox role directory authority is closed")
        return {
            str(item["role"]): int(item["descriptor"])
            for item in self.held_directories
        }

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for descriptor in self.owned_descriptors:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _path_operation(
    *,
    operation: str,
    code: int,
    descriptor: int,
    primary: str,
    secondary: str | None = None,
    flags: int | None = None,
    mode: int | None = None,
    payload: bytes = b"",
) -> dict[str, object]:
    return {
        "operation": operation,
        "kind": "path",
        "operation_code": code,
        "held_directory_fd": descriptor,
        "primary_relative_path": primary,
        "secondary_relative_path": secondary,
        "open_flags": flags,
        "create_mode": mode,
        "payload_hex": payload.hex(),
    }


def _file_operations(
    authority: SandboxRoleDirectoryAuthority,
) -> tuple[dict[str, object], ...]:
    fds = authority.descriptors_by_role
    write_flags = os.O_WRONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    create_flags = write_flags | os.O_CREAT | os.O_EXCL
    truncate_flags = write_flags | os.O_TRUNC
    read_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    return (
        _path_operation(operation="outside_create", code=1, descriptor=fds["outside_probe_root"], primary="outside_create.probe", flags=create_flags, mode=0o600),
        _path_operation(operation="outside_truncate", code=1, descriptor=fds["outside_probe_root"], primary="outside_truncate.probe", flags=truncate_flags, mode=0),
        _path_operation(operation="outside_rename", code=2, descriptor=fds["outside_probe_root"], primary="outside_rename.probe", secondary="outside-rename-destination.probe"),
        _path_operation(operation="outside_unlink", code=3, descriptor=fds["outside_probe_root"], primary="outside_unlink.probe"),
        _path_operation(operation="outside_mkdir", code=4, descriptor=fds["outside_probe_root"], primary="outside_mkdir.probe", mode=0o700),
        _path_operation(operation="artifact_write", code=1, descriptor=fds["artifact_probe_clone_root"], primary="artifact_write.probe", flags=write_flags, mode=0),
        _path_operation(operation="artifact_truncate", code=1, descriptor=fds["artifact_probe_clone_root"], primary="artifact_truncate.probe", flags=truncate_flags, mode=0),
        _path_operation(operation="artifact_unlink", code=3, descriptor=fds["artifact_probe_clone_root"], primary="artifact_unlink.probe"),
        _path_operation(operation="tessdata_write", code=1, descriptor=fds["tessdata_probe_clone_root"], primary="tessdata_write.probe", flags=write_flags, mode=0),
        _path_operation(operation="tessdata_truncate", code=1, descriptor=fds["tessdata_probe_clone_root"], primary="tessdata_truncate.probe", flags=truncate_flags, mode=0),
        _path_operation(operation="tessdata_unlink", code=3, descriptor=fds["tessdata_probe_clone_root"], primary="tessdata_unlink.probe"),
        _path_operation(operation="staged_executable_write", code=1, descriptor=fds["staged_executable_probe_clone_root"], primary="staged_executable_write.probe", flags=write_flags, mode=0),
        _path_operation(operation="staged_executable_truncate", code=1, descriptor=fds["staged_executable_probe_clone_root"], primary="staged_executable_truncate.probe", flags=truncate_flags, mode=0),
        _path_operation(operation="staged_executable_unlink", code=3, descriptor=fds["staged_executable_probe_clone_root"], primary="staged_executable_unlink.probe"),
        _path_operation(operation="staged_executable_read", code=5, descriptor=fds["staged_executable_root"], primary=_portable_leaf(authority.staged_executable_read_path, label="staged executable"), flags=read_flags, mode=0),
        _path_operation(operation="tessdata_read", code=5, descriptor=fds["tessdata_root"], primary=_portable_leaf(authority.tessdata_read_path, label="tessdata"), flags=read_flags, mode=0),
        _path_operation(operation="input_read", code=5, descriptor=fds["input_probe_root"], primary="input.bin", flags=read_flags, mode=0),
        _path_operation(operation="artifact_read", code=5, descriptor=fds["artifact_root"], primary=_portable_leaf(authority.artifact_read_path, label="artifact"), flags=read_flags, mode=0),
    )


def _worker_scratch_operation(descriptor: int) -> dict[str, object]:
    return _path_operation(
        operation="worker_scratch_roundtrip",
        code=6,
        descriptor=descriptor,
        primary="worker-scratch-roundtrip.probe",
        flags=(
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        ),
        mode=0o600,
        payload=b"worker-scratch-roundtrip-v1",
    )


def _build_plan(
    *,
    attempt_id: str,
    attempt_nonce_sha256: str,
    scope_sha256: str,
    role: str,
    profile_sha256: str,
    native_closure_sha256: str,
    executor_authority: str,
    executor_source_sha256: str,
    probe_library_path: Path,
    probe_library_sha256: str,
    held_directories: Sequence[Mapping[str, object]],
    operations: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    fields: dict[str, object] = {
        "schema_id": CHILD_SANDBOX_PLAN_SCHEMA,
        "attempt_id": attempt_id,
        "attempt_nonce_sha256": attempt_nonce_sha256,
        "scope_sha256": scope_sha256,
        "role": role,
        "profile_sha256": profile_sha256,
        "native_closure_sha256": native_closure_sha256,
        "probe_executor_authority": executor_authority,
        "probe_executor_source_sha256": executor_source_sha256,
        "probe_library_path": str(probe_library_path.resolve(strict=True)),
        "probe_library_sha256": probe_library_sha256,
        "held_directories": [dict(item) for item in held_directories],
        "operations": [dict(item) for item in operations],
    }
    return {**fields, "plan_sha256": _canonical_sha256(fields)}


def build_child_sandbox_probe_plan(
    *,
    attempt_id: str,
    attempt_nonce_sha256: str,
    scope_sha256: str,
    profile_sha256: str,
    native_closure_sha256: str,
    executor_source_sha256: str,
    probe_library_path: Path,
    probe_library_sha256: str,
    directories: SandboxRoleDirectoryAuthority,
    network_operations: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], int]:
    operations = tuple(dict(item) for item in network_operations) + _file_operations(
        directories
    )
    plan = _build_plan(
        attempt_id=attempt_id,
        attempt_nonce_sha256=attempt_nonce_sha256,
        scope_sha256=scope_sha256,
        role="tesseract_child",
        profile_sha256=profile_sha256,
        native_closure_sha256=native_closure_sha256,
        executor_authority=CHILD_SANDBOX_EXECUTOR_AUTHORITY,
        executor_source_sha256=executor_source_sha256,
        probe_library_path=probe_library_path,
        probe_library_sha256=probe_library_sha256,
        held_directories=directories.held_directories,
        operations=operations,
    )
    reservation = child_sandbox_probe_report_reservation_bytes(plan)
    return plan, reservation


def build_root_sandbox_probe_plan(
    *,
    attempt_id: str,
    attempt_nonce_sha256: str,
    scope_sha256: str,
    role: str,
    profile_sha256: str,
    native_closure_sha256: str,
    executor_source_sha256: str,
    probe_library_path: Path,
    probe_library_sha256: str,
    directories: SandboxRoleDirectoryAuthority,
    network_operations: Sequence[Mapping[str, object]],
    worker_scratch_root: Path | None = None,
    worker_scratch_fd: int | None = None,
) -> dict[str, object]:
    if role not in ROOT_SANDBOX_HELD_DIRECTORY_ROLES:
        raise ValueError("sandbox root role differs")
    if role == "parser_worker":
        if worker_scratch_root is None or worker_scratch_fd is None:
            raise ValueError("sandbox worker scratch authority is absent")
        scratch = _held_directory(
            role="worker_scratch_root",
            path=worker_scratch_root.resolve(strict=True),
            descriptor=worker_scratch_fd,
        )
        held = (*directories.held_directories, scratch)
        operations = (
            *tuple(dict(item) for item in network_operations),
            *_file_operations(directories),
            _worker_scratch_operation(worker_scratch_fd),
        )
    else:
        if worker_scratch_root is not None or worker_scratch_fd is not None:
            raise ValueError("sandbox broker retained worker scratch")
        held = directories.held_directories
        operations = (
            *tuple(dict(item) for item in network_operations),
            *_file_operations(directories),
        )
    if tuple(str(item["role"]) for item in held) != (
        ROOT_SANDBOX_HELD_DIRECTORY_ROLES[role]
    ):
        raise RuntimeError("sandbox root held directory order differs")
    return _build_plan(
        attempt_id=attempt_id,
        attempt_nonce_sha256=attempt_nonce_sha256,
        scope_sha256=scope_sha256,
        role=role,
        profile_sha256=profile_sha256,
        native_closure_sha256=native_closure_sha256,
        executor_authority=ROOT_SANDBOX_EXECUTOR_AUTHORITY,
        executor_source_sha256=executor_source_sha256,
        probe_library_path=probe_library_path,
        probe_library_sha256=probe_library_sha256,
        held_directories=held,
        operations=operations,
    )


__all__ = [
    "ROOT_SANDBOX_EXECUTOR_AUTHORITY",
    "ROOT_SANDBOX_HELD_DIRECTORY_ROLES",
    "SandboxRoleDirectoryAuthority",
    "build_child_sandbox_probe_plan",
    "build_root_sandbox_probe_plan",
]
