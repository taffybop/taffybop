"""Dedicated P00-US04 tests for the portable 15-case corpus registry."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pdfplumber
import pytest
from pydantic import ValidationError

from tests.benchmarks.contracts import FixtureManifest, canonical_json
from tests.benchmarks.corpus_registry import (
    CORPUS_ROOT,
    CUSTODY_DECISION_ID,
    EXPECTED_ARTIFACT_COUNT,
    EXPECTED_CASE_COUNT,
    EXPECTED_CASE_IDS,
    EXPECTED_PAGE_COUNT,
    INVENTORY_MANIFEST_PATH,
    PERMITTED_USES,
    PortableCorpusRegistry,
    RegistryVerificationError,
    canonical_registry_json,
    load_corpus_registry,
    resolve_portable_path,
    sha256_file,
    verify_current_artifacts,
)
from tests.benchmarks.source_truth import (
    ArtifactIdentity,
    ArtifactRole,
    load_catastrophe_source_truth,
)


WORKSPACE = Path(__file__).resolve().parents[3]
REGISTRY_PATH = (
    WORKSPACE
    / "tracker"
    / "phase-00-baseline"
    / "evidence"
    / "P00-US04-corpus-registry.json"
)
MANIFEST_PATH = WORKSPACE / INVENTORY_MANIFEST_PATH
CATASTROPHE_TRUTH_PATH = (
    WORKSPACE
    / "tracker"
    / "phase-00-baseline"
    / "evidence"
    / "P00-US02-catastrophe-truth.json"
)

EXPECTED_REGISTRY_FILE_SHA256 = (
    "f8024ab7a47df2cedf2d10b996fc8eb140404cdafea0b0a0a9ae2bb059263ceb"
)
EXPECTED_REGISTRY_CANONICAL_SHA256 = (
    "f7c3bdf460f64c51a7d7e29765ab1e621dc5f59224ddeba8c8a66959c901e4ca"
)
EXPECTED_MANIFEST_SHA256 = (
    "16736d189fa38ed10de9755abc181743d87d3199e8cb6275afa32ee39c96a052"
)

# This independent expectation pins the reviewed physical-to-printed mapping;
# it does not derive truth from the registry under test or expert metadata.
EXPECTED_PRINTED_PAGES: dict[str, tuple[str | None, ...]] = {
    "catastrophe-recap": ("7",),
    "clean-energy": ("11",),
    "clinical-study": ("1/21", "7/21", "10/21", "11/21"),
    "component-datasheet": ("3", "7", "11"),
    "egov-survey": ("37",),
    "esg-metrics": ("80",),
    "finance-10k": ("28", "30", "32"),
    "health-report": ("103",),
    "insurance-acord": (None,),
    "manufacturing-report": ("11", "15", "38"),
    "ny-timetable": ("2 of 28", "3 of 28", "4 of 28"),
    "postal-10k": ("2", "46", "49"),
    "purchase-agreement": (None,),
    "settlement-agreement": ("24",),
    "uber-earnings": ("1", "5", "6"),
}


def _payload() -> dict[str, object]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _manifest() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _artifact(case: object, role: ArtifactRole) -> ArtifactIdentity:
    return next(
        artifact
        for artifact in case.artifacts  # type: ignore[attr-defined]
        if artifact.role is role
    )


def test_registry_loads_and_round_trips_deterministically() -> None:
    registry = load_corpus_registry(REGISTRY_PATH)
    canonical = canonical_registry_json(registry)

    assert sha256_file(REGISTRY_PATH) == EXPECTED_REGISTRY_FILE_SHA256
    assert (
        hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        == EXPECTED_REGISTRY_CANONICAL_SHA256
    )
    assert REGISTRY_PATH.read_text(encoding="utf-8") == canonical + "\n"

    reloaded = PortableCorpusRegistry.model_validate_json(canonical)
    assert canonical_registry_json(reloaded) == canonical
    assert canonical_json(reloaded) == canonical
    assert reloaded == registry
    assert registry.schema_version == "1.0"
    assert registry.case_by_id("catastrophe-recap").case_id == "catastrophe-recap"
    with pytest.raises(KeyError, match="unregistered corpus case"):
        registry.case_by_id("not-registered")


def test_registry_has_exact_case_page_and_artifact_denominators() -> None:
    registry = load_corpus_registry(REGISTRY_PATH)

    assert registry.case_count == EXPECTED_CASE_COUNT == 15
    assert registry.page_count == EXPECTED_PAGE_COUNT == 30
    assert registry.artifact_count == EXPECTED_ARTIFACT_COUNT == 45
    assert tuple(case.case_id for case in registry.cases) == EXPECTED_CASE_IDS
    assert sum(case.page_count for case in registry.cases) == 30
    assert len(registry.artifacts) == 45
    assert len({artifact.path for artifact in registry.artifacts}) == 45
    assert len({artifact.sha256 for artifact in registry.artifacts}) == 45

    expected_roles = (
        ArtifactRole.SOURCE,
        ArtifactRole.EXPERT_MARKDOWN,
        ArtifactRole.EXPERT_JSON,
    )
    for case in registry.cases:
        assert tuple(artifact.role for artifact in case.artifacts) == expected_roles
        assert len(case.artifacts) == 3
        assert case.page_count == len(case.pages)


def test_registered_artifacts_and_support_records_match_current_bytes() -> None:
    registry = load_corpus_registry(REGISTRY_PATH)
    verified = verify_current_artifacts(registry, WORKSPACE)

    assert verified == registry.artifacts
    assert len(verified) == 45
    assert registry.inventory_manifest_sha256 == EXPECTED_MANIFEST_SHA256
    assert sha256_file(MANIFEST_PATH) == EXPECTED_MANIFEST_SHA256
    assert (
        sha256_file(WORKSPACE / registry.custody.decision_path)
        == registry.custody.decision_sha256
    )
    assert (
        sha256_file(WORKSPACE / registry.custody.evidence_path)
        == registry.custody.evidence_sha256
    )

    for artifact in verified:
        current = resolve_portable_path(WORKSPACE, artifact.path)
        assert current.is_file()
        assert current.stat().st_size == artifact.size_bytes
        assert sha256_file(current) == artifact.sha256


def test_paths_are_portable_canonical_and_rooted_without_host_state(
    tmp_path: Path,
) -> None:
    registry = load_corpus_registry(REGISTRY_PATH)
    raw = canonical_registry_json(registry)

    assert registry.corpus_root == CORPUS_ROOT
    assert "/Users/" not in raw
    assert "generated_at_utc" not in raw
    for case in registry.cases:
        assert (
            case.review_path
            == f"tracker/benchmarks/llamaparse-15/cases/{case.case_id}.md"
        )
        for artifact in case.artifacts:
            relative = Path(artifact.path)
            assert not relative.is_absolute()
            assert artifact.path.startswith(f"{CORPUS_ROOT}/{case.case_id}.")
            assert "\\" not in artifact.path
            assert ".." not in relative.parts

    root_a = tmp_path / "workspace-a"
    root_b = tmp_path / "workspace-b"
    root_a.mkdir()
    root_b.mkdir()
    portable = registry.cases[0].artifacts[0].path
    assert resolve_portable_path(root_a, portable).relative_to(root_a) == Path(
        portable
    )
    assert resolve_portable_path(root_b, portable).relative_to(root_b) == Path(
        portable
    )


def test_missing_registered_files_and_symlink_escape_fail_closed(
    tmp_path: Path,
) -> None:
    registry = load_corpus_registry(REGISTRY_PATH)
    empty_root = tmp_path / "empty-workspace"
    empty_root.mkdir()

    with pytest.raises(
        RegistryVerificationError,
        match="registered file is missing",
    ):
        verify_current_artifacts(registry, empty_root)

    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"outside")
    symlink_root = tmp_path / "symlink-workspace"
    corpus_dir = symlink_root / CORPUS_ROOT
    corpus_dir.mkdir(parents=True)
    symlink = corpus_dir / "catastrophe-recap.pdf"
    symlink.symlink_to(outside)

    with pytest.raises(ValueError, match="outside the workspace"):
        resolve_portable_path(
            symlink_root,
            f"{CORPUS_ROOT}/catastrophe-recap.pdf",
        )


def test_case_metadata_matches_the_frozen_reviewed_inventory() -> None:
    registry = load_corpus_registry(REGISTRY_PATH)
    manifest_cases = {
        case["case_id"]: case
        for case in _manifest()["cases"]  # type: ignore[index]
    }

    for case in registry.cases:
        frozen = manifest_cases[case.case_id]
        assert case.category == frozen["document_category"]
        assert list(case.layout_characteristics) == frozen[
            "layout_characteristics"
        ]
        assert list(case.complex_elements) == frozen["known_complex_elements"]
        assert case.layout_characteristics
        assert case.complex_elements
        assert len(case.layout_characteristics) == len(
            set(case.layout_characteristics)
        )
        assert len(case.complex_elements) == len(set(case.complex_elements))


def test_page_maps_match_current_pdfs_and_reviewed_printed_labels() -> None:
    registry = load_corpus_registry(REGISTRY_PATH)
    manifest_cases = {
        case["case_id"]: case
        for case in _manifest()["cases"]  # type: ignore[index]
    }

    null_labels = 0
    for case in registry.cases:
        assert tuple(page.physical_page for page in case.pages) == tuple(
            range(1, case.page_count + 1)
        )
        assert (
            tuple(page.printed_page for page in case.pages)
            == EXPECTED_PRINTED_PAGES[case.case_id]
        )
        null_labels += sum(page.printed_page is None for page in case.pages)

        frozen_pages = manifest_cases[case.case_id]["source"]["page_stats"]
        source = resolve_portable_path(
            WORKSPACE,
            _artifact(case, ArtifactRole.SOURCE).path,
        )
        with pdfplumber.open(source) as document:
            assert len(document.pages) == case.page_count == len(frozen_pages)
            for page_record, frozen, actual in zip(
                case.pages,
                frozen_pages,
                document.pages,
                strict=True,
            ):
                assert page_record.physical_page == frozen["page_number"]
                assert page_record.width_pt == round(float(actual.width), 3)
                assert page_record.height_pt == round(float(actual.height), 3)
                assert page_record.source_rotation_deg == int(actual.rotation or 0)
                assert page_record.width_pt == frozen["width_pt"]
                assert page_record.height_pt == frozen["height_pt"]
                assert page_record.source_rotation_deg == frozen["rotation"]

    assert null_labels == 2
    assert registry.case_by_id("insurance-acord").pages[0].printed_page is None
    assert registry.case_by_id("purchase-agreement").pages[0].printed_page is None
    esg_page = registry.case_by_id("esg-metrics").pages[0]
    assert (esg_page.width_pt, esg_page.height_pt) == (792.0, 612.0)
    assert esg_page.source_rotation_deg == 90


def test_expert_page_arrays_match_every_registered_page_map() -> None:
    registry = load_corpus_registry(REGISTRY_PATH)

    for case in registry.cases:
        expert_path = resolve_portable_path(
            WORKSPACE,
            _artifact(case, ArtifactRole.EXPERT_JSON).path,
        )
        expert = json.loads(expert_path.read_text(encoding="utf-8"))
        for view in ("markdown", "text", "items"):
            assert len(expert[view]["pages"]) == case.page_count


def test_custody_is_complete_hash_pinned_and_applies_to_every_case() -> None:
    registry = load_corpus_registry(REGISTRY_PATH)
    custody = registry.custody

    assert custody.decision_id == CUSTODY_DECISION_ID
    assert custody.record_status == "approved"
    assert custody.decision == "public-redistributable"
    assert custody.decision_date == "2026-07-29"
    assert custody.no_exceptions is True
    assert custody.derived_annotations_covered is True
    assert custody.permitted_uses == PERMITTED_USES
    assert {
        case.custody for case in registry.cases
    } == {"public-redistributable"}
    assert {
        case.custody_decision_id for case in registry.cases
    } == {CUSTODY_DECISION_ID}
    assert "private-reference" not in canonical_registry_json(registry)
    assert "synthetic-replacement" not in canonical_registry_json(registry)


def test_each_case_projects_to_the_unchanged_p00_us01_fixture_contract() -> None:
    registry = load_corpus_registry(REGISTRY_PATH)

    for case in registry.cases:
        projected = case.fixture_manifest()
        source = _artifact(case, ArtifactRole.SOURCE)
        assert isinstance(projected, FixtureManifest)
        assert projected.schema_version == "1.0"
        assert projected.fixture_id == case.case_id
        assert projected.source_sha256 == source.sha256
        assert projected.source_format == "PDF"
        assert projected.custody == "public-redistributable"
        assert FixtureManifest.model_validate_json(
            canonical_json(projected)
        ) == projected


def test_catastrophe_projection_matches_p00_us02_truth_exactly() -> None:
    registry = load_corpus_registry(REGISTRY_PATH)
    case = registry.case_by_id("catastrophe-recap")
    truth = load_catastrophe_source_truth(CATASTROPHE_TRUTH_PATH)

    assert case.fixture_manifest() == truth.fixture
    assert case.artifacts == truth.artifacts
    assert case.page_count == 1
    page = case.pages[0]
    assert page.physical_page == truth.page.physical_page
    assert page.printed_page == truth.page.printed_page
    assert page.width_pt == truth.page.width_pt
    assert page.height_pt == truth.page.height_pt
    assert page.source_rotation_deg == truth.page.rotation


@pytest.mark.parametrize(
    "invalid_path",
    (
        "/absolute/file.pdf",
        "../outside.pdf",
        "benchmark-expertmodeldata/../outside.pdf",
        r"benchmark-expertmodeldata\case.pdf",
        "benchmark-expertmodeldata//case.pdf",
        "~/case.pdf",
        "C:/case.pdf",
    ),
)
def test_portable_resolver_rejects_ambiguous_or_escaping_paths(
    invalid_path: str,
) -> None:
    with pytest.raises(ValueError, match="portable path|workspace-relative"):
        resolve_portable_path(WORKSPACE, invalid_path)


def test_missing_duplicate_or_reordered_cases_are_rejected() -> None:
    missing = _payload()
    missing["cases"] = missing["cases"][:-1]  # type: ignore[index]
    with pytest.raises(ValidationError, match="at least 15"):
        PortableCorpusRegistry.model_validate(missing)

    duplicate = _payload()
    duplicate["cases"][-1] = duplicate["cases"][0]  # type: ignore[index]
    with pytest.raises(ValidationError, match="complete LlamaParse-15 inventory"):
        PortableCorpusRegistry.model_validate(duplicate)

    reordered = _payload()
    cases = reordered["cases"]  # type: ignore[assignment]
    cases[0], cases[1] = cases[1], cases[0]
    with pytest.raises(ValidationError, match="canonical order"):
        PortableCorpusRegistry.model_validate(reordered)


def test_missing_role_role_path_mismatch_and_hash_collision_are_rejected() -> None:
    missing_role = _payload()
    missing_role["cases"][0]["artifacts"].pop()  # type: ignore[index]
    with pytest.raises(ValidationError, match="at least 3"):
        PortableCorpusRegistry.model_validate(missing_role)

    role_path_mismatch = _payload()
    role_path_mismatch["cases"][0]["artifacts"][0]["path"] = (  # type: ignore[index]
        "benchmark-expertmodeldata/wrong-case.pdf"
    )
    with pytest.raises(ValidationError, match="case, role, and corpus root"):
        PortableCorpusRegistry.model_validate(role_path_mismatch)

    collision = _payload()
    collision["cases"][1]["artifacts"][0]["sha256"] = (  # type: ignore[index]
        collision["cases"][0]["artifacts"][0]["sha256"]  # type: ignore[index]
    )
    with pytest.raises(ValidationError, match="must not collide across cases"):
        PortableCorpusRegistry.model_validate(collision)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("path", "/tmp/clean-energy.pdf", "portable path"),
        (
            "path",
            "benchmark-expertmodeldata/../clean-energy.pdf",
            "parent segments",
        ),
        (
            "path",
            r"benchmark-expertmodeldata\clean-energy.pdf",
            "POSIX separators",
        ),
        ("size_bytes", 0, "greater than 0"),
        ("sha256", "not-a-hash", "[Ss]tring should match pattern"),
    ),
)
def test_invalid_artifact_identity_fields_are_rejected(
    field: str,
    value: object,
    message: str,
) -> None:
    payload = _payload()
    payload["cases"][1]["artifacts"][0][field] = value  # type: ignore[index]
    with pytest.raises(ValidationError, match=message):
        PortableCorpusRegistry.model_validate(payload)


@pytest.mark.parametrize("field", ("sha256", "size_bytes"))
def test_validly_shaped_but_changed_artifact_identity_fails_current_bytes(
    field: str,
) -> None:
    payload = _payload()
    artifact = payload["cases"][1]["artifacts"][0]  # type: ignore[index]
    artifact[field] = (
        "0" * 64 if field == "sha256" else int(artifact["size_bytes"]) + 1
    )
    registry = PortableCorpusRegistry.model_validate(payload)

    with pytest.raises(
        RegistryVerificationError,
        match="SHA-256 changed|size changed",
    ):
        verify_current_artifacts(registry, WORKSPACE)


def test_changed_support_record_hash_fails_current_bytes() -> None:
    payload = _payload()
    payload["custody"]["decision_sha256"] = "0" * 64  # type: ignore[index]
    registry = PortableCorpusRegistry.model_validate(payload)

    with pytest.raises(RegistryVerificationError, match="SHA-256 changed"):
        verify_current_artifacts(registry, WORKSPACE)


def test_invalid_page_identity_and_reviewed_printed_map_are_rejected() -> None:
    zero_page = _payload()
    zero_page["cases"][2]["pages"][0]["physical_page"] = 0  # type: ignore[index]
    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        PortableCorpusRegistry.model_validate(zero_page)

    page_gap = _payload()
    page_gap["cases"][2]["pages"][1]["physical_page"] = 4  # type: ignore[index]
    with pytest.raises(ValidationError, match="contiguous, one-based"):
        PortableCorpusRegistry.model_validate(page_gap)

    changed_label = _payload()
    changed_label["cases"][2]["pages"][0]["printed_page"] = "1"  # type: ignore[index]
    with pytest.raises(ValidationError, match="printed page map"):
        PortableCorpusRegistry.model_validate(changed_label)

    invalid_rotation = _payload()
    invalid_rotation["cases"][5]["pages"][0][  # type: ignore[index]
        "source_rotation_deg"
    ] = 45
    with pytest.raises(ValidationError, match="Input should be"):
        PortableCorpusRegistry.model_validate(invalid_rotation)

    overprecise_dimension = _payload()
    overprecise_dimension["cases"][0]["pages"][0][  # type: ignore[index]
        "width_pt"
    ] = 612.0001
    with pytest.raises(ValidationError, match="at most three decimals"):
        PortableCorpusRegistry.model_validate(overprecise_dimension)


def test_empty_or_duplicate_case_metadata_is_rejected() -> None:
    empty_category = _payload()
    empty_category["cases"][0]["category"] = ""  # type: ignore[index]
    with pytest.raises(ValidationError, match="at least 1 character"):
        PortableCorpusRegistry.model_validate(empty_category)

    duplicate_layout = _payload()
    layout = duplicate_layout["cases"][0][  # type: ignore[index]
        "layout_characteristics"
    ]
    layout.append(layout[0])
    with pytest.raises(ValidationError, match="metadata values must be unique"):
        PortableCorpusRegistry.model_validate(duplicate_layout)

    empty_complex = _payload()
    empty_complex["cases"][0]["complex_elements"] = []  # type: ignore[index]
    with pytest.raises(ValidationError, match="at least 1"):
        PortableCorpusRegistry.model_validate(empty_complex)


def test_narrowed_or_unapproved_custody_is_rejected() -> None:
    unapproved = _payload()
    unapproved["custody"]["record_status"] = "pending"  # type: ignore[index]
    with pytest.raises(ValidationError, match="Input should be 'approved'"):
        PortableCorpusRegistry.model_validate(unapproved)

    exception = _payload()
    exception["custody"]["no_exceptions"] = False  # type: ignore[index]
    with pytest.raises(ValidationError, match="Input should be True"):
        PortableCorpusRegistry.model_validate(exception)

    narrowed = _payload()
    narrowed["custody"]["permitted_uses"].pop()  # type: ignore[index]
    with pytest.raises(ValidationError, match="at least 6"):
        PortableCorpusRegistry.model_validate(narrowed)

    reordered = _payload()
    uses = reordered["custody"]["permitted_uses"]  # type: ignore[index]
    uses[0], uses[1] = uses[1], uses[0]
    with pytest.raises(ValidationError, match="canonical order"):
        PortableCorpusRegistry.model_validate(reordered)

    private_case = _payload()
    private_case["cases"][0]["custody"] = "private-reference"  # type: ignore[index]
    with pytest.raises(
        ValidationError,
        match="Input should be 'public-redistributable'",
    ):
        PortableCorpusRegistry.model_validate(private_case)


def test_unknown_schema_extra_field_and_wrong_declared_count_are_rejected() -> None:
    unknown_version = _payload()
    unknown_version["schema_version"] = "2.0"
    with pytest.raises(ValidationError, match="Input should be '1.0'"):
        PortableCorpusRegistry.model_validate(unknown_version)

    extra = _payload()
    extra["generated_at_utc"] = "volatile"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PortableCorpusRegistry.model_validate(extra)

    wrong_count = _payload()
    wrong_count["artifact_count"] = 44
    with pytest.raises(ValidationError, match="Input should be 45"):
        PortableCorpusRegistry.model_validate(wrong_count)
