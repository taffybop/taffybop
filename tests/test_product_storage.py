"""Real filesystem checks for write-once product artifacts; no provider calls."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys
from uuid import UUID, uuid4

import pytest

from app.product.storage import (
    ArtifactConflictError, ArtifactIntegrityError, ArtifactNotFoundError,
    ArtifactStorageError, LocalArtifactStore,
)


def read(store, artifact_id, data):
    return store.get(artifact_id, sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))


def test_exact_bytes_survive_new_instance_and_real_process(tmp_path):
    root = tmp_path / "artifacts"
    store = LocalArtifactStore(root)
    artifact_id = uuid4()
    data = b'{ "unknown": [2,1], "unicode": "\\u0ba4" }\n\x00'
    store.put(artifact_id, data)
    assert read(LocalArtifactStore(root), artifact_id, data) == data
    script = """from pathlib import Path
import sys
from uuid import UUID
from app.product.storage import LocalArtifactStore
sys.stdout.buffer.write(LocalArtifactStore(Path(sys.argv[1])).get(UUID(sys.argv[2]), sha256=sys.argv[3], size_bytes=int(sys.argv[4])))
"""
    result = subprocess.run([sys.executable, "-c", script, str(root), str(artifact_id),
                             hashlib.sha256(data).hexdigest(), str(len(data))], check=True,
                            capture_output=True)
    assert result.stdout == data
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / str(artifact_id)).stat().st_mode) == 0o400


def test_write_once_allows_same_bytes_but_refuses_different_bytes(tmp_path):
    store = LocalArtifactStore(tmp_path / "artifacts")
    artifact_id = uuid4()
    store.put(artifact_id, b"original")
    store.put(artifact_id, b"original")
    with pytest.raises(ArtifactConflictError):
        store.put(artifact_id, b"replacement")
    assert read(store, artifact_id, b"original") == b"original"
    assert [path.name for path in store.root.iterdir()] == [str(artifact_id)]


def test_concurrent_identical_writes_publish_one_complete_object(tmp_path):
    store = LocalArtifactStore(tmp_path / "artifacts")
    artifact_id = uuid4()
    data = b"abcdefgh" * 100_000
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda _: store.put(artifact_id, data), range(16)))
    assert read(store, artifact_id, data) == data
    assert len(list(store.root.iterdir())) == 1


def test_concurrent_different_writes_have_exactly_one_winner(tmp_path):
    store = LocalArtifactStore(tmp_path / "artifacts")
    artifact_id = uuid4()
    candidates = [bytes([i]) * 8192 for i in range(8)]

    def attempt(data):
        try:
            store.put(artifact_id, data)
            return data
        except ArtifactConflictError:
            return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        winners = [value for value in executor.map(attempt, candidates) if value is not None]
    assert len(winners) == 1
    assert read(store, artifact_id, winners[0]) == winners[0]


def test_failed_write_never_publishes_partial_object(tmp_path, monkeypatch):
    store = LocalArtifactStore(tmp_path / "artifacts")
    artifact_id = uuid4()
    real_fsync = os.fsync

    def fail_file_sync(descriptor):
        if stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError("simulated disk failure")
        return real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_file_sync)
    with pytest.raises(ArtifactStorageError):
        store.put(artifact_id, b"not published")
    assert list(store.root.iterdir()) == []
    with pytest.raises(ArtifactNotFoundError):
        read(store, artifact_id, b"not published")


@pytest.mark.parametrize("changed", [b"corrupt!", b"short", b"much longer than original"])
def test_corruption_is_detected(tmp_path, changed):
    store = LocalArtifactStore(tmp_path / "artifacts")
    artifact_id = uuid4()
    store.put(artifact_id, b"original")
    path = store.root / str(artifact_id)
    path.chmod(0o600)
    path.write_bytes(changed)
    with pytest.raises(ArtifactIntegrityError):
        read(store, artifact_id, b"original")


def test_missing_object_has_specific_error(tmp_path):
    store = LocalArtifactStore(tmp_path / "artifacts")
    with pytest.raises(ArtifactNotFoundError):
        read(store, uuid4(), b"missing")


@pytest.mark.parametrize("artifact_id", ["../outside", "source.pdf", str(uuid4()), 123, None])
def test_storage_accepts_uuid_objects_only(tmp_path, artifact_id):
    store = LocalArtifactStore(tmp_path / "artifacts")
    with pytest.raises(TypeError):
        store.put(artifact_id, b"payload")
    with pytest.raises(TypeError):
        read(store, artifact_id, b"payload")


@pytest.mark.parametrize("target", ["root", "ancestor", "artifact"])
def test_symlinks_never_redirect_reads_or_writes(tmp_path, target):
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    root = tmp_path / "artifacts"
    artifact_id = uuid4()
    secret = outside / "private.txt"
    secret.write_bytes(b"unrelated local bytes")
    if target == "root":
        root.symlink_to(outside, target_is_directory=True)
        with pytest.raises(ArtifactStorageError):
            LocalArtifactStore(root)
    elif target == "ancestor":
        root.symlink_to(outside, target_is_directory=True)
        with pytest.raises(ArtifactStorageError):
            LocalArtifactStore(root / "nested")
        assert not (outside / "nested").exists()
    else:
        store = LocalArtifactStore(root)
        (root / str(artifact_id)).symlink_to(secret)
        with pytest.raises(ArtifactStorageError):
            read(store, artifact_id, secret.read_bytes())
        with pytest.raises(ArtifactStorageError):
            store.put(artifact_id, b"replacement")
    assert secret.read_bytes() == b"unrelated local bytes"


def test_replacing_root_with_symlink_after_initialization_is_rejected(tmp_path):
    root = tmp_path / "artifacts"
    store = LocalArtifactStore(root)
    moved = tmp_path / "original-artifacts"
    root.rename(moved)
    root.symlink_to(moved, target_is_directory=True)
    with pytest.raises(ArtifactStorageError):
        store.put(uuid4(), b"payload")
    assert list(moved.iterdir()) == []


def test_nonregular_artifact_does_not_block_or_read(tmp_path):
    store = LocalArtifactStore(tmp_path / "artifacts")
    artifact_id = uuid4()
    os.mkfifo(store.root / str(artifact_id))
    with pytest.raises(ArtifactStorageError):
        read(store, artifact_id, b"")


def test_shared_existing_root_is_rejected_without_changing_permissions(tmp_path):
    root = tmp_path / "artifacts"
    root.mkdir(mode=0o755)
    root.chmod(0o755)
    with pytest.raises(ArtifactStorageError):
        LocalArtifactStore(root)
    assert stat.S_IMODE(root.stat().st_mode) == 0o755


@pytest.mark.parametrize("digest,size", [("a" * 63, 1), ("A" * 64, 1), ("a" * 64, True), ("a" * 64, -1)])
def test_invalid_integrity_metadata_is_rejected(tmp_path, digest, size):
    store = LocalArtifactStore(tmp_path / "artifacts")
    with pytest.raises(ValueError):
        store.get(uuid4(), sha256=digest, size_bytes=size)


def test_empty_bytes_are_representable_in_storage(tmp_path):
    store = LocalArtifactStore(tmp_path / "artifacts")
    artifact_id = UUID("8be3f0d9-98c1-4a62-b21a-70f86d3cb3a7")
    store.put(artifact_id, b"")
    assert read(store, artifact_id, b"") == b""
