"""Controller-owned private fixtures for LAT-US02 Seatbelt probes.

The destructive positive controls never target production artifacts.  They run
against five attempt-private roots, restore the exact initial projection, and
then hand those roots to the continuous vnode-custody authority before any
sandboxed role is released.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Final, Mapping


MAXIMUM_FIXTURE_SOURCE_BYTES: Final = 64 * 1024 * 1024
_CLONE_OPERATIONS: Final[dict[str, tuple[str, ...]]] = {
    "artifact_probe_clone": (
        "artifact_write.probe",
        "artifact_truncate.probe",
        "artifact_unlink.probe",
    ),
    "tessdata_probe_clone": (
        "tessdata_write.probe",
        "tessdata_truncate.probe",
        "tessdata_unlink.probe",
    ),
    "staged_executable_probe_clone": (
        "staged_executable_write.probe",
        "staged_executable_truncate.probe",
        "staged_executable_unlink.probe",
    ),
}
_ROOT_NAMES: Final[dict[str, str]] = {
    "artifact_probe_clone": "sandbox-probe-artifact",
    "tessdata_probe_clone": "sandbox-probe-tessdata",
    "staged_executable_probe_clone": "sandbox-probe-staged-executable",
    "input_probe_root": "sandbox-probe-input-read",
    "outside_probe_root": "sandbox-probe-outside",
    "network_trap_root": "sandbox-probe-network-traps",
}
_OUTSIDE_EXISTING: Final = (
    "outside_truncate.probe",
    "outside_rename.probe",
    "outside_unlink.probe",
)


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
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def _file_read_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def _require_private_directory(path: Path, *, label: str) -> os.stat_result:
    resolved = path.resolve(strict=True)
    observed = path.lstat()
    if (
        resolved != path
        or path.is_symlink()
        or not stat.S_ISDIR(observed.st_mode)
        or stat.S_IMODE(observed.st_mode) != 0o700
        or observed.st_uid != os.geteuid()
        or observed.st_nlink < 2
    ):
        raise RuntimeError(f"sandbox {label} private directory differs")
    return observed


def _read_source(path: Path) -> tuple[bytes, dict[str, object]]:
    resolved = path.resolve(strict=True)
    if resolved != path or path.is_symlink():
        raise RuntimeError("sandbox fixture source path custody differs")
    descriptor = os.open(path, _file_read_flags())
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size <= 0
            or before.st_size > MAXIMUM_FIXTURE_SOURCE_BYTES
            or before.st_mode & (stat.S_ISUID | stat.S_ISGID)
        ):
            raise RuntimeError("sandbox fixture source identity differs")
        chunks: list[bytes] = []
        offset = 0
        while offset < before.st_size:
            chunk = os.pread(
                descriptor,
                min(1024 * 1024, before.st_size - offset),
                offset,
            )
            if not chunk:
                raise RuntimeError("sandbox fixture source read was short")
            chunks.append(chunk)
            offset += len(chunk)
        if os.pread(descriptor, 1, before.st_size):
            raise RuntimeError("sandbox fixture source grew while reading")
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    fields = (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_uid",
        "st_gid",
        "st_nlink",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
    )
    if any(getattr(before, name) != getattr(after, name) for name in fields):
        raise RuntimeError("sandbox fixture source changed while reading")
    content = b"".join(chunks)
    return content, {
        "resolved_path": str(resolved),
        "device": before.st_dev,
        "inode": before.st_ino,
        "mode": before.st_mode,
        "uid": before.st_uid,
        "gid": before.st_gid,
        "nlink": before.st_nlink,
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def select_bounded_probe_source(root: Path) -> Path:
    """Select one canonical regular production leaf for the read/control fixture."""

    resolved_root = root.resolve(strict=True)
    if resolved_root != root or root.is_symlink() or not root.is_dir():
        raise RuntimeError("sandbox fixture source root custody differs")
    candidates: list[Path] = []
    for supplied in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if supplied.is_symlink():
            raise RuntimeError("sandbox fixture source tree contains a symlink")
        observed = supplied.lstat()
        if stat.S_ISDIR(observed.st_mode):
            continue
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_size <= 0
            or observed.st_size > MAXIMUM_FIXTURE_SOURCE_BYTES
            or observed.st_mode & (stat.S_ISUID | stat.S_ISGID)
        ):
            continue
        resolved = supplied.resolve(strict=True)
        if resolved_root not in resolved.parents:
            raise RuntimeError("sandbox fixture source escaped its root")
        candidates.append(resolved)
    if not candidates:
        raise RuntimeError("sandbox fixture source root has no bounded leaf")
    return candidates[0]


def _write_exclusive(root_fd: int, name: str, content: bytes) -> int:
    descriptor = os.open(
        name,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
        dir_fd=root_fd,
    )
    try:
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, content[offset:])
            if written <= 0:
                raise RuntimeError("sandbox fixture write was short")
            offset += written
        os.fsync(descriptor)
        observed = os.fstat(descriptor)
        if (
            not stat.S_ISREG(observed.st_mode)
            or stat.S_IMODE(observed.st_mode) != 0o600
            or observed.st_uid != os.geteuid()
            or observed.st_nlink != 1
            or observed.st_size != len(content)
        ):
            raise RuntimeError("sandbox fixture target identity differs")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _inventory(root_fd: int) -> tuple[dict[str, object], ...]:
    retained: list[dict[str, object]] = []
    for name in sorted(os.listdir(root_fd)):
        if not name or name in {".", ".."} or "/" in name or "\x00" in name:
            raise RuntimeError("sandbox fixture member name differs")
        descriptor = os.open(name, _file_read_flags(), dir_fd=root_fd)
        try:
            observed = os.fstat(descriptor)
            if not stat.S_ISREG(observed.st_mode):
                raise RuntimeError("sandbox fixture member type differs")
            content = bytearray()
            offset = 0
            while offset < observed.st_size:
                chunk = os.pread(
                    descriptor,
                    min(1024 * 1024, observed.st_size - offset),
                    offset,
                )
                if not chunk:
                    raise RuntimeError("sandbox fixture inventory read was short")
                content.extend(chunk)
                offset += len(chunk)
            retained.append(
                {
                    "name": name,
                    "device": observed.st_dev,
                    "inode": observed.st_ino,
                    "mode": observed.st_mode,
                    "uid": observed.st_uid,
                    "gid": observed.st_gid,
                    "nlink": observed.st_nlink,
                    "size_bytes": observed.st_size,
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
        finally:
            os.close(descriptor)
    return tuple(retained)


@dataclass(slots=True)
class SandboxProbeMaterialization:
    base_root: Path
    roots: dict[str, Path]
    root_fds: dict[str, int]
    source_identities: dict[str, dict[str, object]]
    fixture_contents: dict[str, bytes]
    initial_inventories: dict[str, tuple[dict[str, object], ...]]
    record_sha256: str
    positive_control_records: tuple[dict[str, object], ...] = ()
    _closed: bool = False

    def custody_roots(self) -> tuple[tuple[str, Path], ...]:
        if self._closed:
            raise RuntimeError("sandbox probe materialization is closed")
        retained = {
            role: self.roots[role]
            for role in (
                "artifact_probe_clone",
                "tessdata_probe_clone",
                "staged_executable_probe_clone",
                "outside_probe_root",
            )
        } | {
            "request_input_probe": (
                self.roots["input_probe_root"] / "input.bin"
            ).resolve(strict=True),
        }
        return tuple(sorted(retained.items()))

    def verify_restored(self) -> None:
        if self._closed:
            raise RuntimeError("sandbox probe materialization is closed")
        if any(
            _inventory(self.root_fds[role]) != expected
            for role, expected in self.initial_inventories.items()
        ):
            raise RuntimeError("sandbox probe materialization was not restored")

    @staticmethod
    def _rewrite(root_fd: int, name: str, content: bytes) -> tuple[int, int]:
        descriptor = os.open(
            name,
            os.O_WRONLY
            | os.O_TRUNC
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=root_fd,
        )
        try:
            offset = 0
            while offset < len(content):
                written = os.write(descriptor, content[offset:])
                if written <= 0:
                    raise RuntimeError("sandbox control restore write was short")
                offset += written
            os.fsync(descriptor)
            return descriptor, offset
        finally:
            os.close(descriptor)

    def run_dac_positive_controls(
        self, *, control_nonce: bytes
    ) -> tuple[dict[str, object], ...]:
        """Prove same-EUID operations work, restore, then freeze the baseline."""

        if self._closed or self.positive_control_records:
            raise RuntimeError("sandbox probe controls are not one-shot")
        if not control_nonce or len(control_nonce) > 256:
            raise ValueError("sandbox probe control nonce differs")
        records: list[dict[str, object]] = []

        def retain(
            *,
            role: str,
            operation: str,
            syscall_stage: str,
            syscall_return: int,
            opened_fd: int | None = None,
            write_return: int | None = None,
        ) -> None:
            record = {
                "schema_id": "phase-latency-sandbox-dac-positive-control-v1",
                "role": role,
                "operation": operation,
                "effective_uid": os.geteuid(),
                "control_nonce_sha256": hashlib.sha256(control_nonce).hexdigest(),
                "syscall_stage": syscall_stage,
                "syscall_return": syscall_return,
                "opened_fd": opened_fd,
                "write_return": write_return,
            }
            record["record_sha256"] = _canonical_sha256(record)
            records.append(record)

        for role, names in _CLONE_OPERATIONS.items():
            root_fd = self.root_fds[role]
            content = self.fixture_contents[role]
            for name in names:
                operation = name.removesuffix(".probe")
                if operation.endswith("_write"):
                    descriptor = os.open(
                        name,
                        os.O_WRONLY
                        | getattr(os, "O_CLOEXEC", 0)
                        | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=root_fd,
                    )
                    try:
                        written = os.pwrite(descriptor, control_nonce, 0)
                        os.fsync(descriptor)
                        retain(
                            role=role,
                            operation=operation,
                            syscall_stage="open-write-fsync",
                            syscall_return=descriptor,
                            opened_fd=descriptor,
                            write_return=written,
                        )
                    finally:
                        os.close(descriptor)
                    self._rewrite(root_fd, name, content)
                elif operation.endswith("_truncate"):
                    descriptor = os.open(
                        name,
                        os.O_WRONLY
                        | os.O_TRUNC
                        | getattr(os, "O_CLOEXEC", 0)
                        | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=root_fd,
                    )
                    retain(
                        role=role,
                        operation=operation,
                        syscall_stage="open-truncate",
                        syscall_return=descriptor,
                        opened_fd=descriptor,
                    )
                    os.close(descriptor)
                    self._rewrite(root_fd, name, content)
                else:
                    os.unlink(name, dir_fd=root_fd)
                    retain(
                        role=role,
                        operation=operation,
                        syscall_stage="unlink",
                        syscall_return=0,
                    )
                    descriptor = _write_exclusive(root_fd, name, content)
                    os.close(descriptor)
            os.fsync(root_fd)

        outside_fd = self.root_fds["outside_probe_root"]
        outside_seed = self.fixture_contents["outside_probe_root"]
        created = _write_exclusive(
            outside_fd, "outside_create.probe", control_nonce
        )
        retain(
            role="outside_probe_root",
            operation="outside_create",
            syscall_stage="open-create-exclusive",
            syscall_return=created,
            opened_fd=created,
            write_return=len(control_nonce),
        )
        os.close(created)
        os.unlink("outside_create.probe", dir_fd=outside_fd)

        truncated = os.open(
            "outside_truncate.probe",
            os.O_WRONLY
            | os.O_TRUNC
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=outside_fd,
        )
        retain(
            role="outside_probe_root",
            operation="outside_truncate",
            syscall_stage="open-truncate",
            syscall_return=truncated,
            opened_fd=truncated,
        )
        os.close(truncated)
        self._rewrite(outside_fd, "outside_truncate.probe", outside_seed)

        os.rename(
            "outside_rename.probe",
            "outside-rename-destination.probe",
            src_dir_fd=outside_fd,
            dst_dir_fd=outside_fd,
        )
        retain(
            role="outside_probe_root",
            operation="outside_rename",
            syscall_stage="rename",
            syscall_return=0,
        )
        os.rename(
            "outside-rename-destination.probe",
            "outside_rename.probe",
            src_dir_fd=outside_fd,
            dst_dir_fd=outside_fd,
        )

        os.unlink("outside_unlink.probe", dir_fd=outside_fd)
        retain(
            role="outside_probe_root",
            operation="outside_unlink",
            syscall_stage="unlink",
            syscall_return=0,
        )
        restored_unlink = _write_exclusive(
            outside_fd, "outside_unlink.probe", outside_seed
        )
        os.close(restored_unlink)

        os.mkdir("outside_mkdir.probe", 0o700, dir_fd=outside_fd)
        retain(
            role="outside_probe_root",
            operation="outside_mkdir",
            syscall_stage="mkdir",
            syscall_return=0,
        )
        os.rmdir("outside_mkdir.probe", dir_fd=outside_fd)
        os.fsync(outside_fd)

        self.initial_inventories = {
            role: _inventory(descriptor)
            for role, descriptor in self.root_fds.items()
        }
        self.positive_control_records = tuple(records)
        self.verify_restored()
        self.record_sha256 = _canonical_sha256(
            {
                "schema_id": "phase-latency-sandbox-probe-materialization-v1",
                "roots": {
                    role: str(path) for role, path in sorted(self.roots.items())
                },
                "sources": self.source_identities,
                "inventories": self.initial_inventories,
                "positive_controls": self.positive_control_records,
            }
        )
        return self.positive_control_records

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for descriptor in self.root_fds.values():
            try:
                os.close(descriptor)
            except OSError:
                pass


def materialize_sandbox_probe_roots(
    *,
    base_root: Path,
    artifact_source: Path,
    tessdata_source: Path,
    staged_executable_source: Path,
    input_source: Path,
) -> SandboxProbeMaterialization:
    """Create all private roots with O_EXCL files and keep their dirfds open."""

    _require_private_directory(base_root, label="probe parent")
    supplied_sources = {
        "artifact_probe_clone": artifact_source,
        "tessdata_probe_clone": tessdata_source,
        "staged_executable_probe_clone": staged_executable_source,
        "input_probe_root": input_source,
    }
    contents: dict[str, bytes] = {}
    source_identities: dict[str, dict[str, object]] = {}
    for role, source in supplied_sources.items():
        content, identity = _read_source(source)
        contents[role] = content
        source_identities[role] = identity
    roots: dict[str, Path] = {}
    root_fds: dict[str, int] = {}
    try:
        for role, name in _ROOT_NAMES.items():
            path = base_root / name
            os.mkdir(path, 0o700)
            _require_private_directory(path, label=role)
            descriptor = os.open(path, _directory_flags())
            root_fds[role] = descriptor
            roots[role] = path.resolve(strict=True)
        for role, names in _CLONE_OPERATIONS.items():
            for name in names:
                descriptor = _write_exclusive(
                    root_fds[role], name, contents[role]
                )
                os.close(descriptor)
            os.fsync(root_fds[role])
        input_fd = _write_exclusive(
            root_fds["input_probe_root"],
            "input.bin",
            contents["input_probe_root"],
        )
        os.close(input_fd)
        outside_seed = hashlib.sha256(
            b"lat-us02-outside-probe-fixture-v1"
        ).digest()
        for name in _OUTSIDE_EXISTING:
            descriptor = _write_exclusive(
                root_fds["outside_probe_root"], name, outside_seed
            )
            os.close(descriptor)
        os.fsync(root_fds["input_probe_root"])
        os.fsync(root_fds["outside_probe_root"])
        inventories = {
            role: _inventory(descriptor)
            for role, descriptor in root_fds.items()
        }
        projection = {
            "schema_id": "phase-latency-sandbox-probe-materialization-v1",
            "roots": {role: str(path) for role, path in sorted(roots.items())},
            "sources": source_identities,
            "inventories": inventories,
        }
        return SandboxProbeMaterialization(
            base_root=base_root.resolve(strict=True),
            roots=roots,
            root_fds=root_fds,
            source_identities=source_identities,
            fixture_contents={
                **contents,
                "outside_probe_root": outside_seed,
            },
            initial_inventories=inventories,
            record_sha256=_canonical_sha256(projection),
        )
    except BaseException:
        for descriptor in root_fds.values():
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise
