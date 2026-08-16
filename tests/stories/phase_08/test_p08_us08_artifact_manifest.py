"""P08-US08 release-first artifact and license manifest controls."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api as api_module
from app.config import Settings, get_settings
from app.services.artifact_manifest import (
    ArtifactKind,
    ArtifactLocatorKind,
    ArtifactManifest,
    ArtifactManifestError,
    ArtifactRecord,
    ArtifactVerificationError,
    ManifestCatalog,
    LOCAL_REFERENCE_ARTIFACT_PROFILE,
    RELEASE_ARTIFACT_PROFILE,
    ReleaseArtifactProfile,
    ReleaseArtifactRequirement,
    STARTUP_CANDIDATE_ROOT_ENV,
    STARTUP_MANIFEST_PATH_ENV,
    STARTUP_PROFILE_ENV,
    STARTUP_MANIFEST_SHA256_ENV,
    VerificationLimits,
    apply_manifest_capability_rollbacks,
    build_release_manifest,
    disabled_optional_artifact,
    huggingface_model_artifact,
    license_summary,
    load_manifest,
    path_artifact,
    python_distribution_artifact,
    verify_configured_startup_manifest,
    verify_build_manifest,
    verify_manifest,
    verify_release_build_manifest,
    verify_release_manifest,
    verify_startup_manifest,
)


VALID_PDF = b"%PDF-1.7\n% release manifest public-flow fixture\n"
REFERENCE_MANIFEST = Path(
    "tracker/phase-08-production-hardening/evidence/"
    "shipped-artifacts-reference-v1.json"
)


def _required_runtime(
    root: Path,
    *,
    locator: str = "runtime.bin",
    release_text: str = "known-good-runtime",
    artifact_id: str = "runtime.local-core",
) -> ArtifactRecord:
    path = root / locator
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(release_text, encoding="utf-8")
    return path_artifact(
        root=root,
        artifact_id=artifact_id,
        kind=ArtifactKind.RUNTIME,
        capability="local_core",
        version="0.1.0",
        source="https://example.invalid/document-parse-api/releases/0.1.0",
        license_record="MIT",
        locator_kind=ArtifactLocatorKind.FILE,
        locator=locator,
        required=True,
    )


def _optional_renderer(root: Path) -> ArtifactRecord:
    path = root / "renderers" / "renderer.bin"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"renderer-v2")
    return path_artifact(
        root=root,
        artifact_id="renderer.office",
        kind=ArtifactKind.RENDERER,
        capability="office_renderer",
        version="2.0.0",
        source="pkg:renderer/office@2.0.0",
        license_record="Apache-2.0",
        locator_kind=ArtifactLocatorKind.FILE,
        locator="renderers/renderer.bin",
        required=False,
        fallback="native_only",
    )


def _release_profile(
    runtime: ArtifactRecord,
    *optional: ArtifactRecord,
) -> ReleaseArtifactProfile:
    requirements = [
        ReleaseArtifactRequirement(
            artifact_id=runtime.artifact_id,
            kind=runtime.kind,
            capability=runtime.capability,
            required=True,
            version=runtime.version,
            source=runtime.source,
            license_record=runtime.license_record,
            locator_kind=runtime.locator_kind,
            locator=runtime.locator,
        )
    ]
    requirements.extend(
        ReleaseArtifactRequirement(
            artifact_id=item.artifact_id,
            kind=item.kind,
            capability=item.capability,
            required=False,
            fallback=item.fallback,
        )
        for item in optional
    )
    return ReleaseArtifactProfile(
        profile_id="test-release-profile",
        requirements=tuple(requirements),
    )


def test_manifest_generation_is_deterministic_ordered_and_machine_readable(
    tmp_path: Path,
) -> None:
    runtime = _required_runtime(tmp_path)
    disabled_model = disabled_optional_artifact(
        artifact_id="model.visual-captioner",
        kind=ArtifactKind.MODEL,
        capability="visual_model",
        fallback="deterministic_visual",
        unavailable_reason="evidence_unavailable",
    )

    first = ArtifactManifest.create(
        release_id="release-0.1.0",
        artifacts=(runtime, disabled_model),
    )
    second = ArtifactManifest.create(
        release_id="release-0.1.0",
        artifacts=(disabled_model, runtime),
    )

    assert first == second
    assert first.to_json_bytes() == second.to_json_bytes()
    assert [item.artifact_id for item in first.artifacts] == [
        "model.visual-captioner",
        "runtime.local-core",
    ]
    assert ArtifactManifest.from_json_bytes(first.to_json_bytes()) == first
    assert first.computed_sha256() == first.manifest_sha256
    assert len(first.to_json_bytes()) < 4_096


def test_build_and_startup_verify_concrete_required_and_optional_artifacts(
    tmp_path: Path,
) -> None:
    manifest = ArtifactManifest.create(
        release_id="candidate-1",
        artifacts=(_required_runtime(tmp_path), _optional_renderer(tmp_path)),
    )

    build = verify_build_manifest(manifest, root=tmp_path)
    startup = verify_startup_manifest(manifest, root=tmp_path)

    assert build.accepted is True
    assert startup.accepted is True
    assert {check.outcome for check in build.checks} == {"verified"}
    assert build.blocking_reasons == ()
    assert build.disabled_capabilities == ()


@pytest.mark.parametrize("failure", ["missing", "changed"])
def test_required_missing_or_hash_mismatch_fails_closed(
    tmp_path: Path,
    failure: str,
) -> None:
    manifest = ArtifactManifest.create(
        release_id="candidate-1",
        artifacts=(_required_runtime(tmp_path),),
    )
    runtime = tmp_path / "runtime.bin"
    if failure == "missing":
        runtime.unlink()
        expected_reason = "runtime.local-core:artifact_missing"
    else:
        runtime.write_text("substituted-runtime", encoding="utf-8")
        expected_reason = "runtime.local-core:hash_mismatch"

    report = verify_manifest(manifest, root=tmp_path, purpose="startup")

    assert report.accepted is False
    assert report.blocking_reasons == (expected_reason,)
    assert report.checks[0].outcome == "blocked"
    with pytest.raises(ArtifactVerificationError, match=expected_reason):
        verify_startup_manifest(manifest, root=tmp_path)


@pytest.mark.parametrize(
    ("update", "match"),
    [
        ({"source": None}, "require version, source, SHA-256, license"),
        ({"license_record": "unknown"}, "license record is not usable"),
        ({"sha256": "f" * 63}, "64 lowercase hex"),
        ({"source": "file:///Users/private/model.bin"}, "local or user cache path"),
        ({"locator": "../private/model.bin"}, "build-root-relative"),
    ],
)
def test_enabled_artifacts_cannot_claim_missing_or_unsafe_evidence(
    update: dict[str, object],
    match: str,
) -> None:
    values: dict[str, object] = {
        "artifact_id": "model.local",
        "kind": ArtifactKind.MODEL,
        "required": True,
        "enabled": True,
        "capability": "visual_model",
        "version": "1.0.0",
        "source": "https://models.example.invalid/local/1.0.0",
        "sha256": "f" * 64,
        "license_record": "Apache-2.0",
        "locator_kind": ArtifactLocatorKind.FILE,
        "locator": "models/local.bin",
    }
    values.update(update)

    with pytest.raises(ArtifactManifestError, match=match):
        ArtifactRecord(**values)  # type: ignore[arg-type]


def test_duplicate_artifact_and_tampered_manifest_are_rejected(tmp_path: Path) -> None:
    runtime = _required_runtime(tmp_path)
    with pytest.raises(ArtifactManifestError, match="duplicate artifact"):
        ArtifactManifest.create(
            release_id="candidate-1",
            artifacts=(runtime, runtime),
        )

    manifest = ArtifactManifest.create(
        release_id="candidate-1",
        artifacts=(runtime,),
    )
    payload = json.loads(manifest.to_json_bytes())
    payload["artifacts"][0]["version"] = "substituted-version"

    with pytest.raises(ArtifactManifestError, match="digest mismatch"):
        ArtifactManifest.from_json_bytes(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        )


def test_disabled_optional_unknown_artifact_uses_fallback_without_probe(
    tmp_path: Path,
) -> None:
    record = disabled_optional_artifact(
        artifact_id="ocr.language-extra",
        kind=ArtifactKind.OCR_DATA,
        capability="ocr_extra_language",
        fallback="configured_core_language",
        unavailable_reason="source_license_hash_unavailable",
    )
    manifest = ArtifactManifest.create(
        release_id="candidate-1",
        artifacts=(_required_runtime(tmp_path), record),
    )

    report = verify_startup_manifest(manifest, root=tmp_path)

    assert report.accepted is True
    assert report.disabled_capabilities == ("ocr_extra_language",)
    disabled = next(check for check in report.checks if check.artifact_id == record.artifact_id)
    assert disabled.outcome == "disabled"
    assert disabled.reason == "source_license_hash_unavailable"
    assert disabled.fallback == "configured_core_language"


def test_changed_optional_artifact_disables_only_its_capability(tmp_path: Path) -> None:
    optional = _optional_renderer(tmp_path)
    manifest = ArtifactManifest.create(
        release_id="candidate-1",
        artifacts=(_required_runtime(tmp_path), optional),
    )
    (tmp_path / "renderers" / "renderer.bin").write_bytes(b"changed")

    report = verify_startup_manifest(manifest, root=tmp_path)

    assert report.accepted is True
    assert report.disabled_capabilities == ("office_renderer",)
    assert [(check.artifact_id, check.outcome, check.reason) for check in report.checks] == [
        ("renderer.office", "fallback", "hash_mismatch"),
        ("runtime.local-core", "verified", "verified"),
    ]


def test_symlink_substitution_is_rejected_for_required_artifact(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    manifest = ArtifactManifest.create(
        release_id="candidate-1",
        artifacts=(_required_runtime(root),),
    )
    outside = tmp_path / "substitution.bin"
    outside.write_text("known-good-runtime", encoding="utf-8")
    (root / "runtime.bin").unlink()
    (root / "runtime.bin").symlink_to(outside)

    report = verify_manifest(manifest, root=root, purpose="startup")

    assert report.accepted is False
    assert report.blocking_reasons == (
        "runtime.local-core:symlink_not_allowed",
    )


def test_installed_dependency_uses_only_concrete_local_metadata_and_bytes() -> None:
    fastapi = python_distribution_artifact("fastapi")
    manifest = ArtifactManifest.create(
        release_id="installed-runtime",
        artifacts=(fastapi,),
    )

    report = verify_startup_manifest(manifest, root=Path.cwd())

    assert report.accepted is True
    assert fastapi.version
    assert fastapi.source == "https://github.com/fastapi/fastapi"
    assert fastapi.license_record == "MIT"
    assert fastapi.sha256 == report.checks[0].actual_sha256
    assert manifest.binds(
        fastapi.artifact_id,
        version=fastapi.version,
        sha256=fastapi.sha256,
    )


def test_manifest_loading_and_license_summary_are_bounded_and_path_safe(
    tmp_path: Path,
) -> None:
    private_canary = "private-document-filename-and-secret"
    manifest = ArtifactManifest.create(
        release_id="candidate-1",
        artifacts=(
            _required_runtime(tmp_path),
            disabled_optional_artifact(
                artifact_id="prompt.visual",
                kind=ArtifactKind.PROMPT,
                capability="visual_prompt",
                fallback="no_model_prompt",
                unavailable_reason="not_selected_for_release",
            ),
        ),
    )
    manifest_path = tmp_path / "release-manifest.json"
    manifest_path.write_bytes(manifest.to_json_bytes())

    loaded = load_manifest(
        manifest_path,
        limits=VerificationLimits(max_manifest_bytes=4_096),
    )
    encoded = json.dumps(license_summary(loaded), sort_keys=True)

    assert loaded == manifest
    assert private_canary not in encoded
    assert str(tmp_path) not in encoded
    assert "/Users/" not in encoded
    assert "runtime.bin" not in encoded


def test_catalog_selects_candidate_then_restores_verified_known_good(
    tmp_path: Path,
) -> None:
    known_root = tmp_path / "known"
    candidate_root = tmp_path / "candidate"
    known_root.mkdir()
    candidate_root.mkdir()
    known_good = ArtifactManifest.create(
        release_id="known-good",
        artifacts=(_required_runtime(known_root, release_text="known-good"),),
    )
    candidate = ArtifactManifest.create(
        release_id="candidate",
        artifacts=(_required_runtime(candidate_root, release_text="candidate"),),
    )
    catalog = ManifestCatalog(
        (candidate, known_good),
        known_good_sha256=known_good.manifest_sha256,
        profile=_release_profile(known_good.artifacts[0]),
    )

    selected = catalog.select_verified(
        candidate.manifest_sha256,
        candidate_root=candidate_root,
        known_good_root=known_root,
    )
    assert selected.manifest == candidate
    assert selected.rolled_back is False

    (candidate_root / "runtime.bin").write_text("broken-candidate", encoding="utf-8")
    rolled_back = catalog.select_verified(
        candidate.manifest_sha256,
        candidate_root=candidate_root,
        known_good_root=known_root,
    )
    assert rolled_back.manifest == known_good
    assert rolled_back.verification.accepted is True
    assert rolled_back.rolled_back is True
    assert catalog.rollback().manifest_sha256 == known_good.manifest_sha256


def test_catalog_rejects_unrestricted_candidate_and_unrestricted_known_good(
    tmp_path: Path,
) -> None:
    known_root = tmp_path / "known"
    candidate_root = tmp_path / "candidate"
    known_root.mkdir()
    candidate_root.mkdir()
    required = _required_runtime(known_root)
    profile = _release_profile(required)
    known_good = ArtifactManifest.create(
        release_id="known-good-unrestricted",
        artifacts=(
            disabled_optional_artifact(
                artifact_id="model.visual.optional",
                kind=ArtifactKind.MODEL,
                capability="visual_models",
                fallback="deterministic_visual",
                unavailable_reason="not_selected_for_release",
            ),
        ),
    )
    candidate = ArtifactManifest.create(
        release_id="candidate-unrestricted",
        artifacts=(_required_runtime(candidate_root, artifact_id="runtime.other"),),
    )
    catalog = ManifestCatalog(
        (candidate, known_good),
        known_good_sha256=known_good.manifest_sha256,
        profile=profile,
    )

    with pytest.raises(
        ArtifactVerificationError,
        match="runtime.local-core:profile_required_missing",
    ):
        catalog.select_verified(
            candidate.manifest_sha256,
            candidate_root=candidate_root,
            known_good_root=known_root,
        )


def test_default_manifest_support_keeps_representative_public_json_compatible(
    client: TestClient,
    parsed_document: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = ArtifactManifest.create(
        release_id="candidate-1",
        artifacts=(_required_runtime(tmp_path),),
    )
    assert verify_startup_manifest(manifest, root=tmp_path).accepted is True
    monkeypatch.setattr(
        api_module,
        "_parse_document",
        lambda _data, _filename, _settings: parsed_document,
    )

    response = client.post(
        "/v1/parse?output_format=json",
        files={"file": ("sample.pdf", VALID_PDF, "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json() == parsed_document
    assert "artifact" not in response.json()


def test_release_profile_rejects_missing_and_downgraded_required_artifact(
    tmp_path: Path,
) -> None:
    runtime = _required_runtime(tmp_path)
    optional = disabled_optional_artifact(
        artifact_id="model.visual.optional",
        kind=ArtifactKind.MODEL,
        capability="visual_models",
        fallback="deterministic_visual",
        unavailable_reason="not_selected_for_release",
    )
    profile = _release_profile(runtime, optional)
    missing = ArtifactManifest.create(
        release_id="missing-required",
        artifacts=(optional,),
    )
    downgraded = ArtifactManifest.create(
        release_id="downgraded-required",
        artifacts=(
            replace(runtime, required=False, fallback="local_core_fallback"),
            optional,
        ),
    )

    missing_report = verify_release_manifest(
        missing, root=tmp_path, purpose="release_startup", profile=profile
    )
    downgrade_report = verify_release_manifest(
        downgraded, root=tmp_path, purpose="release_startup", profile=profile
    )

    assert missing_report.accepted is False
    assert "runtime.local-core:profile_required_missing" in missing_report.blocking_reasons
    assert downgrade_report.accepted is False
    assert (
        "runtime.local-core:profile_required_downgrade"
        in downgrade_report.blocking_reasons
    )


def test_release_profile_rejects_unknown_artifact_capability(tmp_path: Path) -> None:
    runtime = _required_runtime(tmp_path)
    unknown = disabled_optional_artifact(
        artifact_id="model.unapproved",
        kind=ArtifactKind.MODEL,
        capability="unregistered_model_transport",
        fallback="local_core",
        unavailable_reason="not_selected_for_release",
    )
    manifest = ArtifactManifest.create(
        release_id="unknown-capability",
        artifacts=(runtime, unknown),
    )

    report = verify_release_manifest(
        manifest,
        root=tmp_path,
        purpose="release_startup",
        profile=_release_profile(runtime),
    )

    assert report.accepted is False
    assert "model.unapproved:unknown_capability" in report.blocking_reasons
    assert "model.unapproved:unapproved_artifact" in report.blocking_reasons


def test_distribution_verification_is_bound_to_candidate_root(tmp_path: Path) -> None:
    record = python_distribution_artifact("fastapi", root=Path.cwd())
    manifest = ArtifactManifest.create(
        release_id="candidate-root-binding",
        artifacts=(record,),
    )
    empty_candidate_root = tmp_path / "empty-candidate"
    empty_candidate_root.mkdir()

    report = verify_manifest(
        manifest,
        root=empty_candidate_root,
        purpose="startup",
    )

    assert report.accepted is False
    assert report.blocking_reasons == (
        "python:fastapi:distribution_outside_candidate_root",
    )
    with pytest.raises(ArtifactManifestError, match="outside_candidate_root"):
        python_distribution_artifact("fastapi", root=empty_candidate_root)


def test_directory_enumeration_enforces_bound_while_walking(tmp_path: Path) -> None:
    directory = tmp_path / "bounded"
    directory.mkdir()
    for index in range(3):
        (directory / f"{index}.txt").write_text(str(index), encoding="utf-8")

    with pytest.raises(ArtifactManifestError, match="file_limit_exceeded"):
        path_artifact(
            root=tmp_path,
            artifact_id="runtime.bounded",
            kind=ArtifactKind.RUNTIME,
            capability="local_core",
            version="1",
            source="repository:bounded@1",
            license_record="internal-test-record",
            locator_kind=ArtifactLocatorKind.DIRECTORY,
            locator="bounded",
            required=True,
            limits=VerificationLimits(max_files_per_artifact=2),
        )


def test_debian_inventory_fails_closed_without_candidate_dpkg_metadata(
    tmp_path: Path,
) -> None:
    from app.services.artifact_manifest import debian_package_artifact

    with pytest.raises(
        ArtifactManifestError,
        match="debian_metadata_unavailable|artifact_missing",
    ):
        debian_package_artifact(
            "tesseract-ocr",
            root=tmp_path,
            artifact_id="docker.debian.tesseract-ocr",
        )


def test_production_profile_owns_selected_docker_classes_and_model_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = tmp_path / "models" / "example-org--example-model"
    trees = model / ".cache" / "huggingface" / "trees"
    trees.mkdir(parents=True)
    revision = "a" * 40
    (trees / f"{revision}.json").write_text("{}\n", encoding="utf-8")
    (model / "README.md").write_text(
        "---\nlicense: apache-2.0\n---\nModel card.\n", encoding="utf-8"
    )
    (model / "model.safetensors").write_bytes(b"concrete-model-bytes")

    record = huggingface_model_artifact(
        root=tmp_path,
        artifact_id="model.example",
        capability="visual_models",
        locator="models/example-org--example-model",
    )
    manifest = ArtifactManifest.create(
        release_id="model-evidence",
        artifacts=(record,),
    )

    assert record.version == revision
    assert record.source == "https://huggingface.co/example-org/example-model"
    assert record.license_record == "apache-2.0"
    assert verify_manifest(
        manifest, root=tmp_path, purpose="build"
    ).accepted is True
    (model / "README.md").write_text(
        "---\nlicense: mit\n---\nChanged.\n", encoding="utf-8"
    )
    changed = verify_manifest(manifest, root=tmp_path, purpose="startup")
    assert changed.accepted is False
    assert changed.blocking_reasons == ("model.example:provenance_mismatch",)

    requirements = {
        item.artifact_id: item for item in RELEASE_ARTIFACT_PROFILE.requirements
    }

    assert {
        "docker.debian.libgl1",
        "docker.debian.libglib2.0-0",
        "docker.debian.libgomp1",
        "docker.debian.tesseract-ocr",
        "docker.debian.tesseract-ocr-eng",
        "docker.python.torch",
        "docker.python.torchvision",
        "docker.model.docling-layout-heron",
        "docker.model.docling-models",
        "docker.model.document-figure-classifier",
    } <= set(requirements)
    assert all(
        requirements[artifact_id].required
        for artifact_id in requirements
        if artifact_id.startswith("docker.")
    )
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "app.services.artifact_manifest generate" in dockerfile
    assert "app.services.artifact_manifest verify" in dockerfile
    assert 'CMD ["python", "-m", "app.release_start"]' in dockerfile

    import app.release_start as release_start

    digest_path = tmp_path / "shipped-artifacts.sha256"
    digest_path.write_text("b" * 64 + "\n", encoding="ascii")
    monkeypatch.setenv(
        "PARSER_RELEASE_ARTIFACT_MANIFEST_DIGEST_PATH", str(digest_path)
    )
    monkeypatch.setenv(STARTUP_MANIFEST_PATH_ENV, "/app/release/manifest.json")
    monkeypatch.delenv(STARTUP_MANIFEST_SHA256_ENV, raising=False)
    invocations: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        release_start.uvicorn,
        "run",
        lambda *args, **kwargs: invocations.append((*args, kwargs)),
    )

    release_start.main()

    assert invocations == [
        ("app.main:app", {"host": "0.0.0.0", "port": 8000, "workers": 1})
    ]
    assert os.environ[STARTUP_MANIFEST_SHA256_ENV] == "b" * 64
    os.environ[STARTUP_MANIFEST_SHA256_ENV] = "c" * 64
    try:
        with pytest.raises(RuntimeError, match="differs from the image digest"):
            release_start.main()
    finally:
        os.environ.pop(STARTUP_MANIFEST_SHA256_ENV, None)


def test_optional_artifact_failure_operationally_disables_effective_flags(
    tmp_path: Path,
) -> None:
    runtime = _required_runtime(tmp_path)
    visual = disabled_optional_artifact(
        artifact_id="model.visual.optional",
        kind=ArtifactKind.MODEL,
        capability="visual_models",
        fallback="deterministic_visual",
        unavailable_reason="not_selected_for_release",
    )
    renderer = disabled_optional_artifact(
        artifact_id="renderer.office.optional",
        kind=ArtifactKind.RENDERER,
        capability="adapters_office_fallback",
        fallback="native_only",
        unavailable_reason="not_selected_for_release",
    )
    manifest = ArtifactManifest.create(
        release_id="optional-rollbacks",
        artifacts=(runtime, visual, renderer),
    )
    report = verify_release_manifest(
        manifest,
        root=tmp_path,
        purpose="release_startup",
        profile=_release_profile(runtime, visual, renderer),
    )
    configured = Settings(
        visual_structure_schema_enabled=True,
        visual_models_contract_enabled=True,
        adapters_conformance_enabled=True,
        adapters_image_parity_enabled=True,
        adapters_ooxml_intake_enabled=True,
        adapters_docx_native_enabled=True,
        adapters_pptx_native_enabled=True,
        adapters_xlsx_native_enabled=True,
        adapters_office_charts_enabled=True,
        adapters_office_fallback_enabled=True,
    )

    effective = apply_manifest_capability_rollbacks(configured, report)

    assert report.accepted is True
    assert report.disabled_capabilities == (
        "adapters_office_fallback",
        "visual_models",
    )
    assert effective.visual_models_contract_enabled is False
    assert effective.adapters_conformance_enabled is True
    assert effective.adapters_ooxml_intake_enabled is True
    assert effective.adapters_docx_native_enabled is True
    assert effective.adapters_pptx_native_enabled is True
    assert effective.adapters_xlsx_native_enabled is True
    assert effective.adapters_office_charts_enabled is True
    assert effective.adapters_office_fallback_enabled is False
    assert effective.visual_structure_schema_enabled is True


def test_checked_in_reference_inventory_is_generated_truthfully_and_verifies() -> None:
    checked_in = load_manifest(REFERENCE_MANIFEST)
    generated = build_release_manifest(
        release_id=checked_in.release_id,
        root=Path.cwd(),
        profile=LOCAL_REFERENCE_ARTIFACT_PROFILE,
    )

    assert generated == checked_in
    assert generated.manifest_sha256 == (
        "1f10328783f2963a92a796c56b894a90988f046dd57b52381f14cb54e5ec96e9"
    )
    report = verify_release_build_manifest(
        checked_in, root=Path.cwd(), profile=LOCAL_REFERENCE_ARTIFACT_PROFILE
    )
    assert report.accepted is True
    assert report.disabled_capabilities == (
        "adapters_office_fallback",
        "visual_models",
    )
    encoded = checked_in.to_json_bytes().decode("utf-8")
    assert "/Users/" not in encoded
    assert ".venv" not in encoded
    assert "unknown" not in encoded.casefold()
    assert all(
        item.source and item.license_record and item.sha256
        for item in checked_in.artifacts
        if item.required
    )


def test_release_verifier_cli_checks_pinned_candidate_without_path_output() -> None:
    manifest = load_manifest(REFERENCE_MANIFEST)

    completed = subprocess.run(
        (
            sys.executable,
            "-m",
            "app.services.artifact_manifest",
            "verify",
            "--manifest",
            str(REFERENCE_MANIFEST),
            "--expected-sha256",
            manifest.manifest_sha256,
            "--candidate-root",
            str(Path.cwd()),
            "--profile",
            "local_reference",
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0
    result = json.loads(completed.stdout)
    assert result == {
        "accepted": True,
        "disabled_capabilities": ["adapters_office_fallback", "visual_models"],
        "manifest_sha256": manifest.manifest_sha256,
        "release_id": manifest.release_id,
    }
    assert str(Path.cwd()) not in completed.stdout
    assert completed.stderr == ""


def test_create_app_runs_configured_startup_gate_and_applies_rollbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.main import create_app

    manifest = load_manifest(REFERENCE_MANIFEST)
    monkeypatch.setenv(STARTUP_MANIFEST_PATH_ENV, str(REFERENCE_MANIFEST.resolve()))
    monkeypatch.setenv(STARTUP_MANIFEST_SHA256_ENV, manifest.manifest_sha256)
    monkeypatch.setenv(STARTUP_CANDIDATE_ROOT_ENV, str(Path.cwd()))
    monkeypatch.setenv(STARTUP_PROFILE_ENV, "local_reference")
    monkeypatch.setenv("PARSER_VISUAL_STRUCTURE_SCHEMA_ENABLED", "true")
    monkeypatch.setenv("PARSER_VISUAL_MODELS_CONTRACT_ENABLED", "true")
    monkeypatch.setenv("PARSER_ADAPTERS_CONFORMANCE_ENABLED", "true")

    application = create_app()
    effective = application.dependency_overrides[get_settings]()

    assert application.state.release_artifact_verification.accepted is True
    assert (
        application.state.release_artifact_profile_id
        == LOCAL_REFERENCE_ARTIFACT_PROFILE.profile_id
    )
    assert effective.visual_models_contract_enabled is False
    assert effective.adapters_conformance_enabled is True
    assert effective.adapters_office_fallback_enabled is False


def test_configured_startup_gate_rejects_partial_or_unexpected_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.main import create_app

    monkeypatch.setenv(STARTUP_MANIFEST_PATH_ENV, str(REFERENCE_MANIFEST.resolve()))
    with pytest.raises(ArtifactManifestError, match="path and expected digest"):
        create_app()

    monkeypatch.setenv(STARTUP_MANIFEST_SHA256_ENV, "f" * 64)
    with pytest.raises(ArtifactVerificationError, match="unexpected_digest"):
        create_app()


def test_default_configured_verification_is_noop_and_preserves_settings() -> None:
    configured = Settings()

    assert verify_configured_startup_manifest(configured, environ={}) is None
