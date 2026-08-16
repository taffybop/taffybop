"""Regression anchors for the immutable P00-US04 portable corpus registry."""

from __future__ import annotations

import ast
from pathlib import Path

from tests.benchmarks.corpus_registry import (
    canonical_registry_json,
    load_corpus_registry,
    sha256_file,
    verify_current_artifacts,
)
from tests.benchmarks.source_truth import (
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
CATASTROPHE_TRUTH_PATH = (
    WORKSPACE
    / "tracker"
    / "phase-00-baseline"
    / "evidence"
    / "P00-US02-catastrophe-truth.json"
)

PINNED_FILE_HASHES = {
    "tracker/phase-00-baseline/evidence/P00-US04-corpus-registry.json": (
        "f8024ab7a47df2cedf2d10b996fc8eb140404cdafea0b0a0a9ae2bb059263ceb"
    ),
    "tracker/benchmarks/llamaparse-15/manifest.json": (
        "16736d189fa38ed10de9755abc181743d87d3199e8cb6275afa32ee39c96a052"
    ),
    "tracker/phase-00-baseline/decisions/P00-US04-corpus-custody.md": (
        "d6ae0e9dd15aeab2ef9d585ac3242d3941ef2988c3ebc6343e74166e30292d1f"
    ),
    "tracker/phase-00-baseline/evidence/P00-US04-source-rights.md": (
        "f4b2bff08889186572c477ecba19b8b2d6244d046288b79f0786be116f872c3e"
    ),
    "tracker/phase-00-baseline/evidence/P00-US02-catastrophe-truth.json": (
        "d14d9f4bdbbffee24961d731b7bca75227eaec6bac77cce7508ded4252c9b4ac"
    ),
}

EXPECTED_PRINTED_PAGE_LABELS: dict[str, tuple[str | None, ...]] = {
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

ROLE_SUFFIXES = (
    (ArtifactRole.SOURCE, ".pdf"),
    (ArtifactRole.EXPERT_MARKDOWN, ".md"),
    (ArtifactRole.EXPERT_JSON, ".json"),
)


def test_registry_manifest_and_custody_evidence_remain_hash_pinned() -> None:
    assert {
        relative_path: sha256_file(WORKSPACE / relative_path)
        for relative_path in PINNED_FILE_HASHES
    } == PINNED_FILE_HASHES

    registry = load_corpus_registry(REGISTRY_PATH)
    assert (
        registry.inventory_manifest_path,
        registry.inventory_manifest_sha256,
        registry.custody.decision_path,
        registry.custody.decision_sha256,
        registry.custody.evidence_path,
        registry.custody.evidence_sha256,
    ) == (
        "tracker/benchmarks/llamaparse-15/manifest.json",
        PINNED_FILE_HASHES["tracker/benchmarks/llamaparse-15/manifest.json"],
        "tracker/phase-00-baseline/decisions/P00-US04-corpus-custody.md",
        PINNED_FILE_HASHES[
            "tracker/phase-00-baseline/decisions/P00-US04-corpus-custody.md"
        ],
        "tracker/phase-00-baseline/evidence/P00-US04-source-rights.md",
        PINNED_FILE_HASHES[
            "tracker/phase-00-baseline/evidence/P00-US04-source-rights.md"
        ],
    )
    assert REGISTRY_PATH.read_text(encoding="utf-8") == (
        canonical_registry_json(registry) + "\n"
    )


def test_all_physical_pages_retain_the_reviewed_printed_page_map() -> None:
    registry = load_corpus_registry(REGISTRY_PATH)
    actual_labels = {
        case.case_id: tuple(page.printed_page for page in case.pages)
        for case in registry.cases
    }

    assert actual_labels == EXPECTED_PRINTED_PAGE_LABELS
    assert sum(
        label is None
        for labels in actual_labels.values()
        for label in labels
    ) == 2
    assert [
        (
            case.case_id,
            page.physical_page,
            page.width_pt,
            page.height_pt,
            page.source_rotation_deg,
        )
        for case in registry.cases
        for page in case.pages
        if page.source_rotation_deg
    ] == [("esg-metrics", 1, 792.0, 612.0, 90)]


def test_catastrophe_case_projects_to_the_existing_p00_us02_contract() -> None:
    registry = load_corpus_registry(REGISTRY_PATH)
    catastrophe = registry.case_by_id("catastrophe-recap")
    truth = load_catastrophe_source_truth(CATASTROPHE_TRUTH_PATH)

    assert catastrophe.fixture_manifest() == truth.fixture
    assert catastrophe.artifacts == truth.artifacts
    assert (
        catastrophe.pages[0].physical_page,
        catastrophe.pages[0].printed_page_label,
        catastrophe.pages[0].width_pt,
        catastrophe.pages[0].height_pt,
        catastrophe.pages[0].source_rotation_deg,
    ) == (
        truth.page.physical_page,
        truth.page.printed_page_label,
        truth.page.width_pt,
        truth.page.height_pt,
        truth.page.rotation,
    )


def test_current_artifact_verification_is_complete_and_deterministic() -> None:
    first_registry = load_corpus_registry(REGISTRY_PATH)
    second_registry = load_corpus_registry(REGISTRY_PATH)

    first = verify_current_artifacts(first_registry, WORKSPACE)
    second = verify_current_artifacts(second_registry, WORKSPACE)

    assert first == first_registry.artifacts
    assert second == first
    assert len(first) == 45
    assert canonical_registry_json(first_registry) == canonical_registry_json(
        second_registry
    )
    assert tuple((artifact.role, artifact.path) for artifact in first) == tuple(
        (
            role,
            f"benchmark-expertmodeldata/{case_id}{suffix}",
        )
        for case_id in EXPECTED_PRINTED_PAGE_LABELS
        for role, suffix in ROLE_SUFFIXES
    )


def test_production_tree_cannot_import_the_test_only_registry() -> None:
    violations: list[tuple[str, str]] = []
    for path in sorted((WORKSPACE / "app").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        imported_modules = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        imported_modules.extend(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )

        for module in imported_modules:
            if module == "tests" or module.startswith("tests."):
                violations.append((path.relative_to(WORKSPACE).as_posix(), module))
        if "corpus_registry" in source:
            violations.append(
                (path.relative_to(WORKSPACE).as_posix(), "corpus_registry")
            )

    assert violations == []
