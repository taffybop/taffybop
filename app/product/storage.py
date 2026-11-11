"""Private, immutable local artifact bytes for the product persistence layer.

This is a trusted storage adapter, not an authorization boundary. Callers must
check an artifact's owner and document availability before retrieving its bytes.
Only server-generated UUIDs are accepted; filenames never come from uploads.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import stat
from typing import Iterator
from uuid import UUID, uuid4


class ArtifactStorageError(RuntimeError):
    """Local storage failed without exposing file contents or paths."""


class ArtifactConflictError(ArtifactStorageError):
    """An immutable artifact ID already contains different bytes."""


class ArtifactIntegrityError(ArtifactStorageError):
    """Stored bytes do not match the database's integrity metadata."""


class ArtifactNotFoundError(ArtifactStorageError):
    """The requested local object is absent."""


_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


class LocalArtifactStore:
    """Write-once objects in a dedicated owner-private directory.

    Paths containing symlinks are rejected, including the configured root and
    its ancestors. On macOS, use /private/tmp rather than its /tmp alias. New
    directories use mode 0700; an existing root must already be owner-private.
    Writes publish a fully fsynced read-only file by atomic, no-replace hard
    link. A crash may leave an unreferenced temporary file, never partial bytes
    under an artifact ID. Repeating an identical write is safe.
    """

    def __init__(self, root: Path):
        self.root = Path(root).absolute()
        with self._directory(create=True):
            pass

    @staticmethod
    def _name(artifact_id: UUID) -> str:
        if not isinstance(artifact_id, UUID):
            raise TypeError("artifact_id must be a UUID")
        return str(artifact_id)

    @contextmanager
    def _directory(self, *, create: bool = False) -> Iterator[int]:
        """Walk with pinned directory descriptors; never follow a symlink."""
        descriptor = None
        try:
            descriptor = os.open(self.root.anchor, _DIRECTORY_FLAGS)
            parts = self.root.parts[1:]
            if not parts or any(part in {".", ".."} for part in parts):
                raise ArtifactStorageError("storage requires a dedicated directory")
            for part in parts:
                if create:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=descriptor)
                        os.fsync(descriptor)
                    except FileExistsError:
                        pass
                next_descriptor = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = next_descriptor
            info = os.fstat(descriptor)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
                raise ArtifactStorageError("storage directory must be owner-private")
            yield descriptor
        except OSError as exc:
            raise ArtifactStorageError("local artifact storage unavailable") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)

    @staticmethod
    def _read(directory: int, name: str, *, sha256: str, size_bytes: int) -> bytes:
        descriptor = None
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise ArtifactStorageError("artifact must be a regular file")
            if info.st_size != size_bytes:
                raise ArtifactIntegrityError("artifact integrity check failed")
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = None
                data = stream.read(size_bytes + 1)
            if len(data) != size_bytes or hashlib.sha256(data).hexdigest() != sha256:
                raise ArtifactIntegrityError("artifact integrity check failed")
            return data
        except FileNotFoundError as exc:
            raise ArtifactNotFoundError("artifact unavailable") from exc
        except OSError as exc:
            raise ArtifactStorageError("local artifact storage unavailable") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def put(self, artifact_id: UUID, data: bytes) -> None:
        """Durably publish bytes once; refuse any replacement of an ID."""
        name = self._name(artifact_id)
        if not isinstance(data, bytes):
            raise TypeError("artifact data must be bytes")
        digest = hashlib.sha256(data).hexdigest()
        with self._directory() as directory:
            temporary = f".{name}.{uuid4()}.tmp"
            descriptor = None
            try:
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                     mode=0o600, dir_fd=directory)
                with os.fdopen(descriptor, "wb") as stream:
                    descriptor = None
                    stream.write(data)
                    stream.flush()
                    os.fchmod(stream.fileno(), 0o400)
                    os.fsync(stream.fileno())
                try:
                    os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory,
                            follow_symlinks=False)
                except FileExistsError:
                    try:
                        self._read(directory, name, sha256=digest, size_bytes=len(data))
                    except ArtifactIntegrityError as exc:
                        raise ArtifactConflictError("artifact ID already contains different bytes") from exc
                os.fsync(directory)
            finally:
                if descriptor is not None:
                    os.close(descriptor)
                try:
                    os.unlink(temporary, dir_fd=directory)
                except FileNotFoundError:
                    pass
                os.fsync(directory)

    def get(self, artifact_id: UUID, *, sha256: str, size_bytes: int) -> bytes:
        """Read exact bytes, rejecting missing/corrupt/nonregular objects."""
        name = self._name(artifact_id)
        if not isinstance(sha256, str) or re.fullmatch(r"[0-9a-f]{64}", sha256) is None:
            raise ValueError("sha256 must be a lowercase SHA-256 digest")
        if type(size_bytes) is not int or size_bytes < 0:
            raise ValueError("size_bytes must be a nonnegative integer")
        with self._directory() as directory:
            return self._read(directory, name, sha256=sha256, size_bytes=size_bytes)
