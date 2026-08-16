"""Regression anchors for the P00-US05 reviewed-claim contracts."""

from __future__ import annotations

import ast
from collections import Counter
import hashlib
import json
from pathlib import Path

from app.main import create_app
from app.models import ErrorResponse, ParseResult
from tests.benchmarks.contracts import TruthClass
from tests.benchmarks.corpus_registry import (
    load_corpus_registry,
    sha256_file,
)
from tests.benchmarks.reviewed_claims import (
    CATASTROPHE_TRUTH_SHA256,
    ReviewBatch,
    canonical_review_batch_json,
    corpus_registry_sha256,
    project_catastrophe_truth,
    review_batch_sha256,
)
from tests.benchmarks.source_truth import (
    CatastropheSourceTruth,
    ReviewedClaim,
    load_catastrophe_source_truth,
)


WORKSPACE = Path(__file__).resolve().parents[3]
TRUTH_PATH = (
    WORKSPACE
    / "tracker"
    / "phase-00-baseline"
    / "evidence"
    / "P00-US02-catastrophe-truth.json"
)
REGISTRY_PATH = (
    WORKSPACE
    / "tracker"
    / "phase-00-baseline"
    / "evidence"
    / "P00-US04-corpus-registry.json"
)

PINNED_FILE_HASHES = {
    "tracker/phase-00-baseline/evidence/P00-US02-catastrophe-truth.json": (
        "d14d9f4bdbbffee24961d731b7bca75227eaec6bac77cce7508ded4252c9b4ac"
    ),
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
}
PINNED_REGISTRY_SEMANTIC_SHA256 = (
    "f7c3bdf460f64c51a7d7e29765ab1e621dc5f59224ddeba8c8a66959c901e4ca"
)
PINNED_CATASTROPHE_BATCH_SHA256 = (
    "225fc37091849cc4ab7535b7e1dd51c9c1aa390fa2cb50feba051299ae14da71"
)
EXPECTED_EVIDENCE_COUNTS = {
    TruthClass.VISIBLE_TEXT: 32,
    TruthClass.NATIVE_DATA: 33,
    TruthClass.MEASURED: 89,
    TruthClass.INFERRED: 8,
    TruthClass.UNKNOWABLE: 1,
}
EXPECTED_API_SCHEMA_HASHES = {
    "openapi": (
        "3c71271be81fc55e8f85229e1ffdf01ef6a7977c4638a87449617749a1a2983a"
    ),
    "parse_result": (
        "706a1f63bf77eaa6cc3f114b9b5c976d07d764de04a8beffa45cd2b04aafa91f"
    ),
    "error_response": (
        "3fde7027b8452307282b52870914475672aed4b4326018867fdf467922d1a5a6"
    ),
}


def _legacy_claims(truth: CatastropheSourceTruth) -> tuple[ReviewedClaim, ...]:
    return (
        *truth.elements,
        *truth.relationships,
        truth.table,
        *truth.table_cells,
        truth.chart_calibration,
        *truth.chart_labels,
        *truth.chart_measurements,
        *truth.negative_annotations,
    )


def _canonical_sha256(payload: object) -> str:
    data = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def test_frozen_p00_us02_and_p00_us04_evidence_hashes_are_unchanged() -> None:
    assert {
        relative_path: sha256_file(WORKSPACE / relative_path)
        for relative_path in PINNED_FILE_HASHES
    } == PINNED_FILE_HASHES

    registry = load_corpus_registry(REGISTRY_PATH)
    assert CATASTROPHE_TRUTH_SHA256 == PINNED_FILE_HASHES[
        "tracker/phase-00-baseline/evidence/P00-US02-catastrophe-truth.json"
    ]
    assert corpus_registry_sha256(registry) == PINNED_REGISTRY_SEMANTIC_SHA256
    assert registry.inventory_manifest_sha256 == PINNED_FILE_HASHES[
        "tracker/benchmarks/llamaparse-15/manifest.json"
    ]
    assert registry.custody.decision_sha256 == PINNED_FILE_HASHES[
        "tracker/phase-00-baseline/decisions/P00-US04-corpus-custody.md"
    ]
    assert registry.custody.evidence_sha256 == PINNED_FILE_HASHES[
        "tracker/phase-00-baseline/evidence/P00-US04-source-rights.md"
    ]


def test_all_163_catastrophe_claims_project_losslessly_to_annotations() -> None:
    truth = load_catastrophe_source_truth(TRUTH_PATH)
    registry = load_corpus_registry(REGISTRY_PATH)
    batch = project_catastrophe_truth(truth, registry)
    legacy_claims = _legacy_claims(truth)

    assert len(legacy_claims) == batch.claim_count == len(batch.claims) == 163
    assert batch.case_claim_counts == {"catastrophe-recap": 163}
    assert Counter(claim.truth_class for claim in legacy_claims) == (
        EXPECTED_EVIDENCE_COUNTS
    )
    assert Counter(claim.evidence_class for claim in batch.claims) == (
        EXPECTED_EVIDENCE_COUNTS
    )
    assert sum(claim.include_in_exact_parity for claim in legacy_claims) == 62
    assert sum(
        claim.inclusion_mask.literal_parity for claim in batch.claims
    ) == 62
    assert sum(
        claim.inclusion_mask.semantic_parity for claim in batch.claims
    ) == 163

    legacy_by_id = {
        claim.annotation_id: claim.annotation_contract()
        for claim in legacy_claims
    }
    projected_by_id = {
        claim.claim_id: claim.annotation_contract()
        for claim in batch.claims
    }
    assert projected_by_id == legacy_by_id
    assert {
        claim.claim_id: claim.provenance.review_row_id
        for claim in batch.claims
    } == {
        claim.annotation_id: claim.annotation_id
        for claim in legacy_claims
    }


def test_catastrophe_backward_projection_has_a_deterministic_batch_hash() -> None:
    first = project_catastrophe_truth(
        load_catastrophe_source_truth(TRUTH_PATH),
        load_corpus_registry(REGISTRY_PATH),
    )
    second = project_catastrophe_truth(
        load_catastrophe_source_truth(TRUTH_PATH),
        load_corpus_registry(REGISTRY_PATH),
    )
    first_json = canonical_review_batch_json(first)

    assert first == second
    assert first_json == canonical_review_batch_json(second)
    assert ReviewBatch.model_validate_json(first_json) == first
    assert review_batch_sha256(first) == review_batch_sha256(second)
    assert review_batch_sha256(first) == PINNED_CATASTROPHE_BATCH_SHA256


def test_production_tree_cannot_import_reviewed_claim_contracts() -> None:
    violations: list[tuple[str, str]] = []
    for path in sorted((WORKSPACE / "app").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        modules = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        modules.extend(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        for module in modules:
            if module == "tests" or module.startswith("tests."):
                violations.append(
                    (path.relative_to(WORKSPACE).as_posix(), module)
                )
        if "reviewed_claims" in source:
            violations.append(
                (path.relative_to(WORKSPACE).as_posix(), "reviewed_claims")
            )

    assert violations == []


def test_public_api_and_serializer_schemas_retain_the_captured_hashes() -> None:
    schemas = {
        "openapi": create_app().openapi(),
        "parse_result": ParseResult.model_json_schema(),
        "error_response": ErrorResponse.model_json_schema(),
    }

    assert {
        name: _canonical_sha256(schema)
        for name, schema in schemas.items()
    } == EXPECTED_API_SCHEMA_HASHES
