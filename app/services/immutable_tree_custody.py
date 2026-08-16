"""Darwin vnode-event custody for immutable runtime input trees.

The production latency harness must distinguish an unchanged final tree from a
tree that was modified, consumed, and restored while a worker was alive.  This
module keeps every admitted directory/file vnode open, registers EVFILT_VNODE
before protected work is released, and revalidates the same held objects at
closure.  It intentionally fails closed on unsupported leaves, capacity
overflow, any relevant vnode event, or any content/metadata drift.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import select
import stat
import sys
import time
from typing import Final, Iterable


MAXIMUM_CUSTODY_ENTRIES: Final = 4_096
MAXIMUM_CUSTODY_BYTES: Final = 16 * 1024 * 1024 * 1024
_ZERO_SHA256: Final = "0" * 64


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


def _sha256_fd(fd: int, size: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while offset < size:
        chunk = os.pread(fd, min(1024 * 1024, size - offset), offset)
        if not chunk:
            raise RuntimeError("immutable input file ended before retained size")
        digest.update(chunk)
        offset += len(chunk)
    if os.pread(fd, 1, size):
        raise RuntimeError("immutable input file exceeds retained size")
    return digest.hexdigest()


def _metadata(fd: int, *, relative_path: str, kind: str) -> dict[str, object]:
    observed = os.fstat(fd)
    if kind == "directory":
        if not stat.S_ISDIR(observed.st_mode):
            raise RuntimeError("immutable input directory identity changed")
        content_sha256 = None
    elif kind == "file":
        if not stat.S_ISREG(observed.st_mode):
            raise RuntimeError("immutable input file identity changed")
        content_sha256 = _sha256_fd(fd, observed.st_size)
    else:  # pragma: no cover - private caller invariant
        raise RuntimeError("immutable input kind differs")
    return {
        "relative_path": relative_path,
        "kind": kind,
        "device": observed.st_dev,
        "inode": observed.st_ino,
        "mode": observed.st_mode,
        "uid": observed.st_uid,
        "gid": observed.st_gid,
        "nlink": observed.st_nlink,
        "size_bytes": observed.st_size,
        "content_sha256": content_sha256,
    }


@dataclass(slots=True)
class _HeldVnode:
    label: str
    root: str
    relative_path: str
    kind: str
    fd: int
    before: dict[str, object]
    event_mask: int
    vnode_filter_registered_at_monotonic_ns: int


class ImmutableTreeCustodyViolation(RuntimeError):
    """Raised when immutable runtime inputs cannot be proven unchanged."""

    def __init__(self, message: str, *, evidence: dict[str, object] | None = None):
        super().__init__(message)
        self.evidence = evidence


class DarwinImmutableTreeCustody:
    """Hold and monitor complete, bounded immutable directory trees.

    ``roots`` is an ordered iterable of ``(role, path)`` pairs.  Roots must be
    distinct and non-overlapping.  Construction completes two identical scans
    with all vnode filters armed between them.  ``finish`` must run only after
    protected workers and their children have reached terminal custody.
    """

    def __init__(
        self,
        roots: Iterable[tuple[str, Path]],
        *,
        maximum_entries: int = MAXIMUM_CUSTODY_ENTRIES,
        maximum_bytes: int = MAXIMUM_CUSTODY_BYTES,
    ) -> None:
        if sys.platform != "darwin" or not hasattr(select, "kqueue"):
            raise RuntimeError("immutable vnode custody requires Darwin kqueue")
        if (
            type(maximum_entries) is not int
            or maximum_entries <= 0
            or maximum_entries > MAXIMUM_CUSTODY_ENTRIES
            or type(maximum_bytes) is not int
            or maximum_bytes <= 0
            or maximum_bytes > MAXIMUM_CUSTODY_BYTES
        ):
            raise ValueError("immutable vnode custody bound differs")
        normalized: list[tuple[str, Path]] = []
        labels: set[str] = set()
        for label, supplied in roots:
            if (
                type(label) is not str
                or not label
                or len(label) > 128
                or label in labels
            ):
                raise ValueError("immutable vnode custody role differs")
            path = supplied.resolve(strict=True)
            opened = path.lstat()
            if (
                supplied.is_symlink()
                or path == Path(path.anchor)
                or not (
                    stat.S_ISDIR(opened.st_mode)
                    or stat.S_ISREG(opened.st_mode)
                )
            ):
                raise ValueError("immutable vnode custody root is unsafe")
            labels.add(label)
            normalized.append((label, path))
        if not normalized:
            raise ValueError("immutable vnode custody requires a root")
        for index, (_label, path) in enumerate(normalized):
            for _other_label, other in normalized[index + 1 :]:
                if path == other or path in other.parents or other in path.parents:
                    raise ValueError("immutable vnode custody roots overlap")

        self._maximum_entries = maximum_entries
        self._maximum_bytes = maximum_bytes
        self._roots = tuple(normalized)
        self._held: list[_HeldVnode] = []
        self._by_fd: dict[int, _HeldVnode] = {}
        self._kqueue = select.kqueue()
        self._closed = False
        self._armed_at_monotonic_ns = 0
        self._aggregate_bytes = 0
        self._root_path_identities: list[dict[str, object]] = []
        try:
            for label, root in self._roots:
                self._open_target(label, root)
            self._armed_at_monotonic_ns = max(
                max(1, time.monotonic_ns()),
                max(
                    held.vnode_filter_registered_at_monotonic_ns
                    for held in self._held
                ),
            )
            first = self._snapshot()
            first_membership = self._directory_membership_snapshot()
            if self._drain_events():
                raise ImmutableTreeCustodyViolation(
                    "immutable input emitted an event while custody was armed"
                )
            second = self._snapshot()
            second_membership = self._directory_membership_snapshot()
            if first != second or first_membership != second_membership:
                raise ImmutableTreeCustodyViolation(
                    "immutable input changed while custody was armed"
                )
            if self._drain_events():
                raise ImmutableTreeCustodyViolation(
                    "immutable input emitted an event while custody was armed"
                )
            self._initial_projection = first
            self._initial_projection_sha256 = _canonical_sha256(first)
            self._initial_directory_membership = first_membership
            self._root_authorities = self._derive_root_authorities()
        except BaseException:
            self._close_descriptors()
            raise

    @property
    def armed_at_monotonic_ns(self) -> int:
        return self._armed_at_monotonic_ns

    @property
    def initial_projection_sha256(self) -> str:
        return self._initial_projection_sha256

    def _open_flags(self, *, directory: bool) -> int:
        return (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | (getattr(os, "O_DIRECTORY", 0) if directory else 0)
        )

    def _append_held(
        self,
        *,
        label: str,
        root: Path,
        relative_path: str,
        kind: str,
        fd: int,
        event_mask: int,
    ) -> None:
        if len(self._held) >= self._maximum_entries:
            raise RuntimeError("immutable vnode custody entry bound exceeded")
        retained = _HeldVnode(
            label=label,
            root=str(root),
            relative_path=relative_path,
            kind=kind,
            fd=fd,
            before={},
            event_mask=event_mask,
            vnode_filter_registered_at_monotonic_ns=0,
        )
        self._held.append(retained)
        self._by_fd[fd] = retained
        self._register_held(retained)
        retained.vnode_filter_registered_at_monotonic_ns = max(
            1, time.monotonic_ns()
        )
        before = _metadata(fd, relative_path=relative_path, kind=kind)
        retained.before = before
        if kind == "file":
            self._aggregate_bytes += int(before["size_bytes"])
            if self._aggregate_bytes > self._maximum_bytes:
                raise RuntimeError("immutable vnode custody byte bound exceeded")

    def _open_target(self, label: str, root: Path) -> None:
        path_stat = root.lstat()
        is_directory = stat.S_ISDIR(path_stat.st_mode)
        root_fd = os.open(root, self._open_flags(directory=is_directory))
        try:
            root_stat = os.fstat(root_fd)
            if (
                not (
                    stat.S_ISDIR(root_stat.st_mode)
                    if is_directory
                    else stat.S_ISREG(root_stat.st_mode)
                )
                or (root_stat.st_dev, root_stat.st_ino)
                != (path_stat.st_dev, path_stat.st_ino)
            ):
                raise RuntimeError("immutable vnode custody root identity differs")
            self._root_path_identities.append(
                {
                    "role": label,
                    "resolved_path": str(root),
                    "device": root_stat.st_dev,
                    "inode": root_stat.st_ino,
                    "kind": "directory" if is_directory else "file",
                }
            )
            self._append_held(
                label=label,
                root=root,
                relative_path=".",
                kind="directory" if is_directory else "file",
                fd=root_fd,
                event_mask=self._content_event_mask(),
            )
            root_fd = -1
            if is_directory:
                self._open_descendants(self._held[-1])
            self._open_ancestor_chain(label, root)
        finally:
            if root_fd >= 0:
                os.close(root_fd)

    def _open_descendants(self, directory: _HeldVnode) -> None:
        names = sorted(os.listdir(directory.fd))
        for name in names:
            if (
                type(name) is not str
                or not name
                or name in {".", ".."}
                or "/" in name
                or "\x00" in name
            ):
                raise RuntimeError("immutable vnode custody member name differs")
            observed = os.stat(name, dir_fd=directory.fd, follow_symlinks=False)
            if stat.S_ISLNK(observed.st_mode):
                raise RuntimeError("immutable vnode custody rejects symbolic links")
            relative = (
                name
                if directory.relative_path == "."
                else f"{directory.relative_path}/{name}"
            )
            is_directory = stat.S_ISDIR(observed.st_mode)
            if not is_directory and not stat.S_ISREG(observed.st_mode):
                raise RuntimeError("immutable vnode custody rejects special leaves")
            fd = os.open(
                name,
                self._open_flags(directory=is_directory),
                dir_fd=directory.fd,
            )
            try:
                opened = os.fstat(fd)
                if (opened.st_dev, opened.st_ino, opened.st_mode) != (
                    observed.st_dev,
                    observed.st_ino,
                    observed.st_mode,
                ):
                    raise RuntimeError("immutable vnode custody member raced open")
                self._append_held(
                    label=directory.label,
                    root=Path(directory.root),
                    relative_path=relative,
                    kind="directory" if is_directory else "file",
                    fd=fd,
                    event_mask=self._content_event_mask(),
                )
                fd = -1
                if is_directory:
                    self._open_descendants(self._held[-1])
            finally:
                if fd >= 0:
                    os.close(fd)

    def _open_ancestor_chain(self, label: str, root: Path) -> None:
        for index, ancestor in enumerate(root.parents):
            fd = os.open(ancestor, self._open_flags(directory=True))
            try:
                self._append_held(
                    label=f"{label}:ancestor",
                    root=root,
                    relative_path=f"@ancestor/{index}",
                    kind="directory",
                    fd=fd,
                    event_mask=self._ancestor_event_mask(),
                )
                fd = -1
            finally:
                if fd >= 0:
                    os.close(fd)

    @staticmethod
    def _content_event_mask() -> int:
        return (
            select.KQ_NOTE_WRITE
            | select.KQ_NOTE_EXTEND
            | select.KQ_NOTE_ATTRIB
            | select.KQ_NOTE_LINK
            | select.KQ_NOTE_RENAME
            | select.KQ_NOTE_DELETE
            | select.KQ_NOTE_REVOKE
        )

    @staticmethod
    def _ancestor_event_mask() -> int:
        return (
            select.KQ_NOTE_RENAME
            | select.KQ_NOTE_DELETE
            | select.KQ_NOTE_REVOKE
        )

    def _register_held(self, held: _HeldVnode) -> None:
        self._kqueue.control(
            [
                select.kevent(
                    held.fd,
                    filter=select.KQ_FILTER_VNODE,
                    flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
                    fflags=held.event_mask,
                )
            ],
            0,
            0,
        )

    def _snapshot(self) -> list[dict[str, object]]:
        return [
            {
                "role": held.label,
                "root": held.root,
                "vnode_filter_registered_at_monotonic_ns": (
                    held.vnode_filter_registered_at_monotonic_ns
                ),
                **_metadata(
                    held.fd,
                    relative_path=held.relative_path,
                    kind=held.kind,
                ),
            }
            for held in self._held
        ]

    @staticmethod
    def _parent_relative_path(relative_path: str) -> str | None:
        if relative_path == "." or relative_path.startswith("@ancestor/"):
            return None
        if "/" not in relative_path:
            return "."
        return relative_path.rsplit("/", 1)[0]

    def _directory_membership_snapshot(self) -> list[dict[str, object]]:
        expected_by_directory: dict[
            tuple[str, str, str], list[dict[str, object]]
        ] = {}
        for held in self._held:
            parent = self._parent_relative_path(held.relative_path)
            if parent is None:
                continue
            expected_by_directory.setdefault(
                (held.label, held.root, parent), []
            ).append(
                {
                    "name": held.relative_path.rsplit("/", 1)[-1],
                    "kind": held.kind,
                    "device": held.before["device"],
                    "inode": held.before["inode"],
                }
            )
        retained: list[dict[str, object]] = []
        for held in self._held:
            if held.kind != "directory" or held.relative_path.startswith(
                "@ancestor/"
            ):
                continue
            actual_members: list[dict[str, object]] = []
            for name in sorted(os.listdir(held.fd)):
                observed = os.stat(
                    name, dir_fd=held.fd, follow_symlinks=False
                )
                kind = (
                    "directory"
                    if stat.S_ISDIR(observed.st_mode)
                    else "file"
                    if stat.S_ISREG(observed.st_mode)
                    else "unsupported"
                )
                actual_members.append(
                    {
                        "name": name,
                        "kind": kind,
                        "device": observed.st_dev,
                        "inode": observed.st_ino,
                    }
                )
            expected_members = sorted(
                expected_by_directory.get(
                    (held.label, held.root, held.relative_path), []
                ),
                key=lambda item: str(item["name"]),
            )
            if actual_members != expected_members:
                raise ImmutableTreeCustodyViolation(
                    "immutable input directory membership differs"
                )
            retained.append(
                {
                    "role": held.label,
                    "root": held.root,
                    "relative_path": held.relative_path,
                    "device": held.before["device"],
                    "inode": held.before["inode"],
                    "members": actual_members,
                }
            )
        return sorted(
            retained,
            key=lambda item: (
                str(item["role"]),
                str(item["root"]),
                str(item["relative_path"]),
            ),
        )

    def _derive_root_authorities(self) -> list[dict[str, object]]:
        authorities: list[dict[str, object]] = []
        for label, root in self._roots:
            files = sorted(
                (
                    held
                    for held in self._held
                    if held.label == label and held.kind == "file"
                ),
                key=lambda held: held.relative_path,
            )
            records = [
                {
                    "path": held.relative_path,
                    "sha256": held.before["content_sha256"],
                    "size_bytes": held.before["size_bytes"],
                }
                for held in files
            ]
            root_identity = next(
                value
                for value in self._root_path_identities
                if value["role"] == label
            )
            authorities.append(
                {
                    **root_identity,
                    "content_manifest_sha256": _canonical_sha256(records),
                    "file_count": len(records),
                    "aggregate_bytes": sum(
                        int(record["size_bytes"]) for record in records
                    ),
                }
            )
        return authorities

    def _drain_events(self) -> list[dict[str, object]]:
        retained: list[dict[str, object]] = []
        maximum = max(1, len(self._held) * 2)
        while True:
            events = self._kqueue.control(None, maximum, 0)
            if not events:
                return retained
            for event in events:
                held = self._by_fd.get(int(event.ident))
                retained.append(
                    {
                        "role": held.label if held is not None else "unknown",
                        "root": held.root if held is not None else "unknown",
                        "relative_path": (
                            held.relative_path if held is not None else "unknown"
                        ),
                        "fflags": int(event.fflags),
                    }
                )

    def finish(self) -> dict[str, object]:
        if self._closed:
            raise RuntimeError("immutable vnode custody already closed")
        completed_at = max(1, time.monotonic_ns())
        events_before = self._drain_events()
        after = self._snapshot()
        directory_membership_after = self._directory_membership_snapshot()
        events_after = self._drain_events()
        events = [*events_before, *events_after]
        roots_after: list[dict[str, object]] = []
        root_path_stable = True
        for retained, (_label, path) in zip(
            self._root_path_identities, self._roots, strict=True
        ):
            try:
                observed = path.lstat()
                current = {
                    "role": retained["role"],
                    "resolved_path": str(path),
                    "device": observed.st_dev,
                    "inode": observed.st_ino,
                    "kind": retained["kind"],
                }
            except OSError:
                current = {
                    "role": retained["role"],
                    "resolved_path": str(path),
                    "device": -1,
                    "inode": -1,
                    "kind": retained["kind"],
                }
            roots_after.append(current)
            root_path_stable = root_path_stable and current == retained
        after_sha256 = _canonical_sha256(after)
        fields: dict[str, object] = {
            "schema_id": "parser-darwin-immutable-tree-custody-v1",
            "event_authority": "darwin-kqueue-EVFILT_VNODE-held-fd-v1",
            "monitored_note_flags": [
                "WRITE",
                "EXTEND",
                "ATTRIB",
                "LINK",
                "RENAME",
                "DELETE",
                "REVOKE",
            ],
            "armed_at_monotonic_ns": self._armed_at_monotonic_ns,
            "completed_at_monotonic_ns": completed_at,
            "maximum_entries": self._maximum_entries,
            "maximum_bytes": self._maximum_bytes,
            "entry_count": len(self._held),
            "aggregate_file_bytes": self._aggregate_bytes,
            "root_authorities": self._root_authorities,
            "root_path_identities_before": self._root_path_identities,
            "root_path_identities_after": roots_after,
            "entry_projection": self._initial_projection,
            "directory_membership_projection": (
                self._initial_directory_membership
            ),
            "initial_projection_sha256": self._initial_projection_sha256,
            "final_projection_sha256": after_sha256,
            "event_count": len(events),
            "events": events,
            "root_paths_stable": root_path_stable,
            "held_vnodes_unchanged": after == self._initial_projection,
            "no_relevant_vnode_events": not events,
        }
        fields["record_sha256"] = _canonical_sha256(fields)
        self._close_descriptors()
        if (
            not root_path_stable
            or after != self._initial_projection
            or directory_membership_after
            != self._initial_directory_membership
            or events
        ):
            raise ImmutableTreeCustodyViolation(
                "immutable runtime input custody failed", evidence=fields
            )
        return fields

    def _close_descriptors(self) -> None:
        if self._closed:
            return
        self._closed = True
        for held in reversed(self._held):
            try:
                os.close(held.fd)
            except OSError:
                pass
        self._held.clear()
        self._by_fd.clear()
        try:
            self._kqueue.close()
        except OSError:
            pass

    def abort(self) -> None:
        """Close custody descriptors without claiming an immutable interval."""

        self._close_descriptors()


__all__ = [
    "DarwinImmutableTreeCustody",
    "ImmutableTreeCustodyViolation",
    "MAXIMUM_CUSTODY_BYTES",
    "MAXIMUM_CUSTODY_ENTRIES",
]
