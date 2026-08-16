from __future__ import annotations

import os
from pathlib import Path
import stat

import pytest

from app.services.parser_sandbox_materialization import (
    materialize_sandbox_probe_roots,
    select_bounded_probe_source,
)


def _source(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    return path.resolve(strict=True)


def test_private_sandbox_probe_roots_are_distinct_and_restorable(
    tmp_path: Path,
) -> None:
    os.chmod(tmp_path, 0o700)
    artifact = _source(tmp_path / "artifact.bin", b"artifact-fixture")
    tessdata = _source(tmp_path / "eng.traineddata", b"traineddata-fixture")
    staged = _source(tmp_path / "tesseract", b"staged-executable-fixture")
    input_source = _source(tmp_path / "input.pdf", b"request-input-fixture")

    materialized = materialize_sandbox_probe_roots(
        base_root=tmp_path,
        artifact_source=artifact,
        tessdata_source=tessdata,
        staged_executable_source=staged,
        input_source=input_source,
    )
    try:
        assert len(materialized.roots) == 6
        assert len(set(materialized.roots.values())) == 6
        assert materialized.initial_inventories["network_trap_root"] == ()
        assert "network_trap_root" not in dict(materialized.custody_roots())
        assert materialized.record_sha256 != "0" * 64
        for role, root in materialized.roots.items():
            observed = root.stat()
            assert stat.S_ISDIR(observed.st_mode)
            assert stat.S_IMODE(observed.st_mode) == 0o700
            assert observed.st_uid == os.geteuid()
            assert materialized.root_fds[role] >= 0
        assert (
            materialized.initial_inventories["input_probe_root"][0]["name"]
            == "input.bin"
        )
        controls = materialized.run_dac_positive_controls(
            control_nonce=b"controller-positive-control"
        )
        assert len(controls) == 14
        assert {item["operation"] for item in controls} == {
            "artifact_write",
            "artifact_truncate",
            "artifact_unlink",
            "tessdata_write",
            "tessdata_truncate",
            "tessdata_unlink",
            "staged_executable_write",
            "staged_executable_truncate",
            "staged_executable_unlink",
            "outside_create",
            "outside_truncate",
            "outside_rename",
            "outside_unlink",
            "outside_mkdir",
        }
        materialized.verify_restored()
    finally:
        materialized.close()


def test_private_sandbox_probe_materialization_rejects_reuse(
    tmp_path: Path,
) -> None:
    os.chmod(tmp_path, 0o700)
    sources = {
        "artifact_source": _source(tmp_path / "artifact.bin", b"artifact"),
        "tessdata_source": _source(tmp_path / "traineddata", b"tessdata"),
        "staged_executable_source": _source(tmp_path / "tesseract", b"binary"),
        "input_source": _source(tmp_path / "input.pdf", b"input"),
    }
    first = materialize_sandbox_probe_roots(base_root=tmp_path, **sources)
    first.close()

    with pytest.raises(FileExistsError):
        materialize_sandbox_probe_roots(base_root=tmp_path, **sources)


def test_probe_source_selection_is_canonical_and_bounded(tmp_path: Path) -> None:
    os.chmod(tmp_path, 0o700)
    nested = tmp_path / "nested"
    nested.mkdir(mode=0o700)
    selected = _source(nested / "a.bin", b"bounded-source")
    _source(nested / "z.bin", b"other-source")

    assert select_bounded_probe_source(tmp_path) == selected
