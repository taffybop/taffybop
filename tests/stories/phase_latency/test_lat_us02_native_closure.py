from __future__ import annotations

import copy
import os
import platform
import shutil
import struct
from pathlib import Path

import pytest

from app.services.tesseract_broker_protocol import (
    BrokerProtocolError,
    canonical_sha256,
)
from app.services.tesseract_native_closure import (
    NATIVE_CLOSURE_TRUST_MODEL,
    NON_SYSTEM_IMAGE_MUTABILITY_POLICY,
    NON_SYSTEM_IMAGE_OWNER_POLICY,
    RUNPATH_RESOLUTION_POLICY,
    derive_native_closure,
    validate_native_closure,
)


def _host_tesseract() -> str:
    executable = shutil.which("tesseract")
    if platform.system() != "Darwin" or executable is None:
        pytest.skip("native closure is approved on a Darwin Tesseract host")
    return os.path.realpath(executable)


def _staged_tesseract(tmp_path: Path) -> tuple[str, str]:
    source = _host_tesseract()
    staged = tmp_path / "tesseract-staged"
    shutil.copy2(source, staged)
    staged.chmod(0o500)
    return source, str(staged.resolve())


def _minimal_macho(load_command: int, install_name: str) -> bytes:
    raw_name = install_name.encode("utf-8") + b"\x00"
    command_size = (24 + len(raw_name) + 7) & ~7
    command = struct.pack("<IIIIII", load_command, command_size, 24, 0, 0, 0)
    command += raw_name + b"\x00" * (command_size - 24 - len(raw_name))
    header = struct.pack(
        "<IIIIIIII",
        0xFEEDFACF,
        0x0100000C,
        0,
        2,
        1,
        command_size,
        0,
        0,
    )
    return header + command


def test_native_closure_recursively_binds_staged_image_and_dyld_authority(
    tmp_path: Path,
) -> None:
    source, staged = _staged_tesseract(tmp_path)

    closure = derive_native_closure(source, staged)

    assert closure["trust_model"] == NATIVE_CLOSURE_TRUST_MODEL
    assert closure["containment_claim"] == "none-trusted-pinned-native-computation"
    assert closure["non_system_image_owner_policy"] == (
        NON_SYSTEM_IMAGE_OWNER_POLICY
    )
    assert closure["non_system_image_mutability_policy"] == (
        NON_SYSTEM_IMAGE_MUTABILITY_POLICY
    )
    assert closure["runpath_resolution_policy"] == RUNPATH_RESOLUTION_POLICY
    assert closure["ancestor_only_runpath_edge_count"] == 0
    assert closure["roots"]["source_executable"] == source
    assert closure["roots"]["staged_executable"] == staged
    assert closure["roots"]["source_sha256"] == closure["roots"]["staged_sha256"]
    assert closure["image_count"] == len(closure["images"])
    assert closure["edge_count"] == len(closure["edges"])
    assert closure["image_count"] > 1
    source_edges = [
        edge
        for edge in closure["edges"]
        if edge["root_executable"] == source
    ]
    staged_edges = [
        edge
        for edge in closure["edges"]
        if edge["root_executable"] == staged
    ]
    assert len(source_edges) == len(staged_edges) > 1
    assert closure["roots"]["source_dependency_projection_sha256"] == (
        closure["roots"]["staged_dependency_projection_sha256"]
    )
    assert closure["system_cache"]["authority"] == (
        "apple-sealed-system-volume-dyld-shared-cache-v1"
    )
    assert closure["system_cache"]["content_scope"] == (
        "main-cache-fully-hashed-subcache-metadata-and-sealed-os-trusted-v1"
    )
    assert closure["system_cache"]["system_references"]
    assert any(edge["symlink_chain"] for edge in closure["edges"])
    assert all(
        edge["runpath_resolution_scope"]
        in {"not-rpath", "loader-rpath", "main-executable-rpath"}
        for edge in closure["edges"]
    )
    assert all(
        edge["runpath_resolution_scope"] == "loader-rpath"
        for edge in closure["edges"]
        if edge["install_name"].startswith("@rpath/")
    )
    assert validate_native_closure(closure) == closure


def test_native_closure_rejects_a_self_hashed_forged_image_identity(
    tmp_path: Path,
) -> None:
    source, staged = _staged_tesseract(tmp_path)
    closure = derive_native_closure(source, staged)
    forged = copy.deepcopy(closure)
    forged["images"][0]["sha256"] = "f" * 64
    forged["closure_sha256"] = canonical_sha256(
        {key: value for key, value in forged.items() if key != "closure_sha256"}
    )

    with pytest.raises(BrokerProtocolError, match="reobservation"):
        validate_native_closure(forged)


def test_native_closure_rejects_staged_bytes_changed_after_preflight(
    tmp_path: Path,
) -> None:
    source, staged = _staged_tesseract(tmp_path)
    closure = derive_native_closure(source, staged)
    staged_path = Path(staged)
    body = staged_path.read_bytes()
    staged_path.chmod(0o700)
    staged_path.write_bytes(body[:-1] + bytes((body[-1] ^ 1,)))
    staged_path.chmod(0o500)

    with pytest.raises(BrokerProtocolError):
        validate_native_closure(closure)


@pytest.mark.parametrize("mutation", ["group_writable", "hard_link"])
def test_native_closure_rejects_mutable_staged_image_custody(
    tmp_path: Path,
    mutation: str,
) -> None:
    source, staged = _staged_tesseract(tmp_path)
    staged_path = Path(staged)
    if mutation == "group_writable":
        staged_path.chmod(0o520)
    else:
        os.link(staged_path, tmp_path / "second-link")

    with pytest.raises(BrokerProtocolError, match="ownership/mutability"):
        derive_native_closure(source, staged)


def test_native_closure_rejects_self_hashed_ancestor_runpath_claim(
    tmp_path: Path,
) -> None:
    source, staged = _staged_tesseract(tmp_path)
    closure = derive_native_closure(source, staged)
    forged = copy.deepcopy(closure)
    forged["ancestor_only_runpath_edge_count"] = 1
    forged["closure_sha256"] = canonical_sha256(
        {key: value for key, value in forged.items() if key != "closure_sha256"}
    )

    with pytest.raises(BrokerProtocolError, match="trust boundary"):
        validate_native_closure(forged, reobserve=False)


def test_native_closure_traverses_transitive_executable_path_for_both_roots(
    tmp_path: Path,
) -> None:
    if platform.system() != "Darwin":
        pytest.skip("native closure is approved only on Darwin")
    source_root = tmp_path / "source"
    staged_root = tmp_path / "staged"
    for root in (source_root, staged_root):
        (root / "lib").mkdir(parents=True)
        (root / "tesseract").write_bytes(
            _minimal_macho(0xC, "@executable_path/lib/dep.dylib")
        )
        (root / "lib" / "dep.dylib").write_bytes(
            _minimal_macho(0xC, "@executable_path/lib/leaf.dylib")
        )
    (source_root / "lib" / "leaf.dylib").write_bytes(
        _minimal_macho(0xD, "source-leaf")
    )
    (staged_root / "lib" / "leaf.dylib").write_bytes(
        _minimal_macho(0xD, "staged-leaf")
    )

    with pytest.raises(
        BrokerProtocolError,
        match="source/staged native dependency projections differ",
    ):
        derive_native_closure(
            str((source_root / "tesseract").resolve()),
            str((staged_root / "tesseract").resolve()),
        )
