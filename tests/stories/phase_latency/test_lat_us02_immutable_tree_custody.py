from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys

import pytest

from app.services import immutable_tree_custody as custody_module
from app.services.immutable_tree_custody import (
    DarwinImmutableTreeCustody,
    ImmutableTreeCustodyViolation,
)
from app.services.tesseract_broker_protocol import canonical_sha256
from tests.benchmarks.latency_prewarm_contracts import (
    ImmutableRuntimeInputCustodyEvidence,
)


pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="Darwin EVFILT_VNODE custody is required"
)


def _tree(root: Path) -> Path:
    root.mkdir(mode=0o700)
    nested = root / "nested"
    nested.mkdir(mode=0o700)
    leaf = nested / "weights.bin"
    leaf.write_bytes(b"approved-model-bytes")
    return leaf


def test_immutable_tree_custody_accepts_stable_held_tree(
    tmp_path: Path,
) -> None:
    root = tmp_path / "models"
    leaf = _tree(root)
    custody = DarwinImmutableTreeCustody((("docling_artifacts", root),))

    assert leaf.read_bytes() == b"approved-model-bytes"
    evidence = custody.finish()

    assert evidence["event_count"] == 0
    assert evidence["root_paths_stable"] is True
    assert evidence["held_vnodes_unchanged"] is True
    assert evidence["no_relevant_vnode_events"] is True
    assert evidence["initial_projection_sha256"] == evidence[
        "final_projection_sha256"
    ]


def test_immutable_tree_custody_rejects_write_then_restore(
    tmp_path: Path,
) -> None:
    root = tmp_path / "models"
    leaf = _tree(root)
    original = leaf.read_bytes()
    custody = DarwinImmutableTreeCustody((("docling_artifacts", root),))

    descriptor = os.open(leaf, os.O_WRONLY)
    try:
        assert os.pwrite(descriptor, b"malicious-model-byte", 0) > 0
        os.fsync(descriptor)
        os.ftruncate(descriptor, 0)
        assert os.write(descriptor, original) == len(original)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

    with pytest.raises(ImmutableTreeCustodyViolation) as caught:
        custody.finish()
    assert caught.value.evidence is not None
    assert caught.value.evidence["event_count"] > 0
    assert caught.value.evidence["no_relevant_vnode_events"] is False


def test_immutable_tree_custody_holds_an_individual_native_image(
    tmp_path: Path,
) -> None:
    image = tmp_path / "libdependency.dylib"
    image.write_bytes(b"frozen-native-image")
    custody = DarwinImmutableTreeCustody((("native_image_0001", image),))

    evidence = custody.finish()

    assert evidence["event_count"] == 0
    assert evidence["root_authorities"] == [
        {
            "role": "native_image_0001",
            "resolved_path": str(image),
            "device": image.stat().st_dev,
            "inode": image.stat().st_ino,
            "kind": "file",
            "content_manifest_sha256": evidence["root_authorities"][0][
                "content_manifest_sha256"
            ],
            "file_count": 1,
            "aggregate_bytes": len(b"frozen-native-image"),
        }
    ]


def test_immutable_tree_custody_rejects_root_rename_rebind_restore(
    tmp_path: Path,
) -> None:
    root = tmp_path / "tessdata"
    _tree(root)
    displaced = tmp_path / "tessdata-held"
    custody = DarwinImmutableTreeCustody((("tessdata", root),))

    root.rename(displaced)
    replacement_leaf = _tree(root)
    replacement_leaf.write_bytes(b"replacement-traineddata")
    shutil.rmtree(root)
    displaced.rename(root)

    with pytest.raises(ImmutableTreeCustodyViolation) as caught:
        custody.finish()
    assert caught.value.evidence is not None
    assert caught.value.evidence["event_count"] > 0


def test_immutable_tree_custody_rejects_symlink_member(
    tmp_path: Path,
) -> None:
    root = tmp_path / "models"
    _tree(root)
    (root / "alias").symlink_to(root / "nested" / "weights.bin")

    with pytest.raises(RuntimeError, match="symbolic links"):
        DarwinImmutableTreeCustody((("docling_artifacts", root),))


def test_immutable_tree_custody_rejects_overlapping_roots(
    tmp_path: Path,
) -> None:
    root = tmp_path / "models"
    _tree(root)

    with pytest.raises(ValueError, match="overlap"):
        DarwinImmutableTreeCustody(
            (("docling_artifacts", root), ("nested", root / "nested"))
        )


def test_immutable_tree_custody_rejects_member_added_during_enumeration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "models"
    _tree(root)
    original_listdir = custody_module.os.listdir
    injected = False

    def inject_after_list(directory_fd: int) -> list[str]:
        nonlocal injected
        names = original_listdir(directory_fd)
        if not injected:
            injected = True
            (root / "late-added.bin").write_bytes(b"unadmitted")
        return names

    monkeypatch.setattr(custody_module.os, "listdir", inject_after_list)
    with pytest.raises(
        ImmutableTreeCustodyViolation,
        match="directory membership|emitted an event",
    ):
        DarwinImmutableTreeCustody((("docling_artifacts", root),))


def test_immutable_tree_custody_arms_file_before_initial_content_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "models"
    leaf = _tree(root)
    original = leaf.read_bytes()
    original_sha256_fd = custody_module._sha256_fd
    injected = False

    def mutate_and_restore_after_hash(fd: int, size: int) -> str:
        nonlocal injected
        digest = original_sha256_fd(fd, size)
        if not injected and size == len(original):
            injected = True
            writer = os.open(leaf, os.O_WRONLY)
            try:
                os.ftruncate(writer, 0)
                assert os.write(writer, b"transient-unapproved-bytes") > 0
                os.fsync(writer)
                os.ftruncate(writer, 0)
                assert os.write(writer, original) == len(original)
                os.fsync(writer)
            finally:
                os.close(writer)
        return digest

    monkeypatch.setattr(
        custody_module, "_sha256_fd", mutate_and_restore_after_hash
    )
    with pytest.raises(
        ImmutableTreeCustodyViolation,
        match="emitted an event|changed while custody",
    ):
        DarwinImmutableTreeCustody((("docling_artifacts", root),))


def test_immutable_tree_custody_record_validates_shared_evidence(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    tessdata = tmp_path / "tessdata"
    staged = tmp_path / "staged"
    _tree(artifacts)
    _tree(tessdata)
    _tree(staged)
    custody = DarwinImmutableTreeCustody(
        (
            ("docling_artifacts", artifacts),
            ("staged_execution_inputs", staged),
            ("tessdata", tessdata),
        )
    )

    raw = custody.finish()
    raw["attempt_id"] = "lat-us02-fixture-enabled-r01"
    raw.pop("record_sha256")
    raw["record_sha256"] = canonical_sha256(raw)
    evidence = ImmutableRuntimeInputCustodyEvidence.model_validate(raw)

    assert evidence.attempt_id == "lat-us02-fixture-enabled-r01"
    assert tuple(item.role for item in evidence.root_authorities) == (
        "docling_artifacts",
        "staged_execution_inputs",
        "tessdata",
    )
