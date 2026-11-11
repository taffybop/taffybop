"""Exclusive local provider profiles, with durable handover fences.

This is a single-host development boundary, not production authentication or an
account-wide distributed lock. Every local submitter must use the same private
lock path. Never unlink the lock file: its inode is the locking identity.

Legacy activity survives process death until terminal responses are observed.
Product ownership is deliberately sticky: switching back to legacy requires
manual account/queue reconciliation before an operator removes the journal.
There is no automatic reset that could release unknown upstream work.
"""

from __future__ import annotations

from enum import Enum
import fcntl
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
from uuid import uuid4


class RuntimeProfileError(RuntimeError):
    """Fixed, public-safe admission error; never contains paths or credentials."""

    def __init__(self):
        super().__init__("Local provider admission is unavailable; check the runtime profile and reconcile outstanding provider work.")


class RuntimeProfile(str, Enum):
    LEGACY_LOCAL = "legacy_local"
    PRODUCT_WORKER_LOCAL = "product_worker_local"
    DISABLED = "disabled"

    @classmethod
    def from_env(cls) -> "RuntimeProfile":
        try:
            return cls(os.environ.get("TAFFYBOP_RUNTIME_PROFILE", cls.LEGACY_LOCAL.value))
        except ValueError:
            raise RuntimeProfileError() from None


def _lock_path(path: str | Path | None) -> Path:
    configured = path if path is not None else os.environ.get("TAFFYBOP_PROVIDER_LOCK_PATH")
    value = Path(configured) if configured is not None else Path(__file__).resolve().parents[2] / "tmp/product/provider.lock"
    if not value.is_absolute() or value.name in {"", ".", ".."} or ".." in value.parts:
        raise RuntimeProfileError()
    return value


class LocalProviderLock:
    """Nonblocking exclusive lock held for the full API/worker process lifetime.

    Product acquisition writes a sticky product-owned fence. Preflight checks
    must inspect configuration without acquiring this lock. Instances can be
    used as context managers; close releases only the OS lock, never fences.
    """

    def __init__(self, profile: RuntimeProfile | str, path: str | Path | None = None):
        try:
            self.profile = RuntimeProfile(profile)
        except ValueError:
            raise RuntimeProfileError() from None
        if self.profile is RuntimeProfile.DISABLED:
            raise RuntimeProfileError()
        self.path = _lock_path(path)
        self._fd: int | None = None
        self._pid: int | None = None
        self._mutex = threading.Lock()

    @staticmethod
    def _private(info, *, directory: bool = False):
        expected = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
        if not expected or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise RuntimeProfileError()
        if not directory and info.st_nlink != 1:
            raise RuntimeProfileError()

    def _identity(self):
        if self._fd is None or self._pid != os.getpid():
            raise RuntimeProfileError()
        try:
            current = self.path.lstat()
            opened = os.fstat(self._fd)
        except OSError:
            raise RuntimeProfileError() from None
        self._private(current)
        if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            raise RuntimeProfileError()

    @property
    def journal_path(self) -> Path:
        return self.path.with_name(self.path.name + ".activity.json")

    def _read_journal(self) -> dict:
        self._identity()
        try:
            fd = os.open(self.journal_path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return {"version": 1, "product_owned": False, "legacy": {}}
        try:
            self._private(os.fstat(fd))
            with os.fdopen(fd, "rb", closefd=False) as handle:
                raw = handle.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise RuntimeProfileError()
            value = json.loads(raw)
            if (not isinstance(value, dict) or set(value) != {"version", "product_owned", "legacy"}
                or type(value["version"]) is not int or value["version"] != 1
                or type(value["product_owned"]) is not bool or not isinstance(value["legacy"], dict)
                or any(not isinstance(k, str) or not isinstance(v, dict)
                       or set(v) != {"provider_id"}
                       or (v["provider_id"] is not None and not isinstance(v["provider_id"], str))
                       for k, v in value["legacy"].items())):
                raise RuntimeProfileError()
            return value
        finally:
            os.close(fd)

    def _write_journal(self, value: dict):
        self._identity()
        temporary = None
        try:
            fd, temporary = tempfile.mkstemp(prefix=".provider-activity-", dir=self.path.parent)
            with os.fdopen(fd, "wb") as handle:
                handle.write((json.dumps(value, sort_keys=True) + "\n").encode())
                handle.flush()
                os.fsync(handle.fileno())
            self._identity()
            os.replace(temporary, self.journal_path)
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass

    def acquire(self) -> "LocalProviderLock":
        with self._mutex:
            if self._fd is not None:
                self._identity()
                return self
            try:
                self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                self._private(self.path.parent.lstat(), directory=True)
                fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
                self._fd = fd
                self._pid = os.getpid()
                self._private(os.fstat(fd))
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._identity()
                value = self._read_journal()
                if self.profile is RuntimeProfile.PRODUCT_WORKER_LOCAL:
                    if value["legacy"]:
                        raise RuntimeProfileError()
                    value["product_owned"] = True
                    self._write_journal(value)
                elif value["product_owned"]:
                    raise RuntimeProfileError()
                return self
            except (OSError, ValueError, TypeError, RuntimeProfileError):
                self.close()
                raise RuntimeProfileError() from None

    def close(self):
        fd, self._fd = self._fd, None
        self._pid = None
        if fd is not None:
            os.close(fd)

    def __enter__(self) -> "LocalProviderLock":
        return self.acquire()

    def __exit__(self, *_):
        self.close()

    def begin_legacy_submission(self) -> str:
        with self._mutex:
            if self.profile is not RuntimeProfile.LEGACY_LOCAL:
                raise RuntimeProfileError()
            try:
                value = self._read_journal()
                identity = str(uuid4())
                value["legacy"][identity] = {"provider_id": None}
                self._write_journal(value)
                return identity
            except (OSError, ValueError, TypeError):
                raise RuntimeProfileError() from None

    def acknowledge_legacy_submission(self, identity: str, provider_id: str):
        with self._mutex:
            try:
                value = self._read_journal()
                value["legacy"][identity]["provider_id"] = provider_id
                self._write_journal(value)
            except (OSError, ValueError, TypeError, KeyError):
                raise RuntimeProfileError() from None

    def finish_legacy_submission(self, identity: str, provider_id: str):
        with self._mutex:
            try:
                value = self._read_journal()
                entry = value["legacy"].get(identity)
                if entry is None:
                    return
                if entry["provider_id"] != provider_id:
                    raise RuntimeProfileError()
                del value["legacy"][identity]
                self._write_journal(value)
            except (OSError, ValueError, TypeError):
                raise RuntimeProfileError() from None


_legacy_locks: dict[Path, LocalProviderLock] = {}
_legacy_mutex = threading.Lock()


def legacy_submission_enabled() -> bool:
    try:
        return RuntimeProfile.from_env() is RuntimeProfile.LEGACY_LOCAL
    except RuntimeProfileError:
        return False


def require_legacy_submission() -> LocalProviderLock:
    if not legacy_submission_enabled():
        raise RuntimeProfileError()
    path = _lock_path(None)
    with _legacy_mutex:
        if path not in _legacy_locks:
            _legacy_locks[path] = LocalProviderLock(RuntimeProfile.LEGACY_LOCAL, path).acquire()
        else:
            _legacy_locks[path]._identity()
        return _legacy_locks[path]
