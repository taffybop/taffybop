"""Regression anchors for the P00-US07 reviewed-claim Batch B."""

from __future__ import annotations

import ast
from collections import Counter
import hashlib
import json
from pathlib import Path

from app.main import create_app
from app.models import ErrorResponse, ParseResult
from tests.benchmarks.corpus_registry import (
    load_corpus_registry,
    sha256_file,
)
from tests.benchmarks.reviewed_claim_inventory import (
    BATCH_A_EVIDENCE_PATH,
    BATCH_B_EVIDENCE_PATH,
    load_reviewed_claim_batch_a,
    load_reviewed_claim_batch_b,
)
from tests.benchmarks.reviewed_claims import (
    ClaimReviewStatus,
    review_batch_sha256,
)


WORKSPACE = Path(__file__).resolve().parents[3]
REGISTRY_PATH = (
    WORKSPACE
    / "tracker"
    / "phase-00-baseline"
    / "evidence"
    / "P00-US04-corpus-registry.json"
)
BATCH_A_PATH = WORKSPACE / BATCH_A_EVIDENCE_PATH
BATCH_B_PATH = WORKSPACE / BATCH_B_EVIDENCE_PATH
PINNED_REVIEW_HASHES = {
    "tracker/benchmarks/llamaparse-15/cases/clean-energy.md": (
        "1345fc03e3f55f415dd7682c827e24b6022d25b46ef0ee68e8437bc145f0ca5a"
    ),
    "tracker/benchmarks/llamaparse-15/cases/clinical-study.md": (
        "fa5c1e863b7cee50ca4eea4b6c2debd042c7d9bbe143663cad64a26a07f5806f"
    ),
    "tracker/benchmarks/llamaparse-15/cases/component-datasheet.md": (
        "6e41940bd8ffd61dbf7fce8ec4882f8935f6a94c481c844d7dc828812c4b53fe"
    ),
    "tracker/benchmarks/llamaparse-15/cases/insurance-acord.md": (
        "327e9ed62a2703075e00434d5b02bead11525692d43178198a9377ca0adeaddb"
    ),
    "tracker/benchmarks/llamaparse-15/cases/ny-timetable.md": (
        "68e1ce268850da1fa09180c0bd0262976ba983dcc5de039c21b1bbde91c7822b"
    ),
}
PINNED_BATCH_A_FILE_SHA256 = (
    "f987d84ca1b0d08dfd304d7ea3164a78366643f4b42ef03bc4975d4d09548de4"
)
PINNED_BATCH_A_SEMANTIC_SHA256 = (
    "f6f0ef58f4cb1379f808e8d5bb7253f260a8f643a83e98e75e4d2e1a3fff01ee"
)
PINNED_BATCH_B_FILE_SHA256 = (
    "7e4728c1c5d76a6453d42c640de8a25c24989ed3a160cac2fe4640b22a55814e"
)
PINNED_BATCH_B_SEMANTIC_SHA256 = (
    "9afe6c098adcd32e3a8370af5ecb2b27ac4730f098e39128e787eef991990d0f"
)
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


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_batch_a_b_evidence_and_batch_b_reviews_retain_pinned_hashes() -> None:
    assert sha256_file(BATCH_A_PATH) == PINNED_BATCH_A_FILE_SHA256
    assert sha256_file(BATCH_B_PATH) == PINNED_BATCH_B_FILE_SHA256
    assert {
        path: sha256_file(WORKSPACE / path)
        for path in PINNED_REVIEW_HASHES
    } == PINNED_REVIEW_HASHES


def test_all_15_batch_b_triplet_artifacts_retain_registered_bytes() -> None:
    registry = load_corpus_registry(REGISTRY_PATH)
    case_ids = {
        "clean-energy",
        "clinical-study",
        "component-datasheet",
        "insurance-acord",
        "ny-timetable",
    }
    artifacts = [
        artifact
        for case in registry.cases
        if case.case_id in case_ids
        for artifact in case.artifacts
    ]

    assert len(artifacts) == 15
    assert all(
        (WORKSPACE / artifact.path).stat().st_size == artifact.size_bytes
        and sha256_file(WORKSPACE / artifact.path) == artifact.sha256
        for artifact in artifacts
    )


def test_batch_a_and_b_semantics_retain_pinned_totals() -> None:
    registry = load_corpus_registry(REGISTRY_PATH)
    batch_a = load_reviewed_claim_batch_a(
        BATCH_A_PATH,
        WORKSPACE,
        registry,
    )
    batch_b = load_reviewed_claim_batch_b(
        BATCH_B_PATH,
        WORKSPACE,
        registry,
    )

    assert review_batch_sha256(batch_a) == PINNED_BATCH_A_SEMANTIC_SHA256
    assert review_batch_sha256(batch_b) == PINNED_BATCH_B_SEMANTIC_SHA256
    assert Counter(claim.review_status for claim in batch_b.claims) == {
        ClaimReviewStatus.VERIFIED: 43,
        ClaimReviewStatus.PARTIALLY_VERIFIED: 15,
        ClaimReviewStatus.INCORRECT: 8,
        ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE: 5,
        ClaimReviewStatus.POTENTIALLY_INFERRED: 5,
    }
    assert sum(
        claim.inclusion_mask.literal_parity for claim in batch_b.claims
    ) == 36
    assert sum(
        claim.inclusion_mask.semantic_parity for claim in batch_b.claims
    ) == 58
    assert len({
        claim.claim_id for claim in (*batch_a.claims, *batch_b.claims)
    }) == 147


def test_production_tree_cannot_import_reviewed_claim_inventory() -> None:
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
        if "reviewed_claim_inventory" in source:
            violations.append(
                (path.relative_to(WORKSPACE).as_posix(), "inventory")
            )

    assert violations == []


def test_public_api_and_serializer_schemas_remain_unchanged() -> None:
    schemas = {
        "openapi": create_app().openapi(),
        "parse_result": ParseResult.model_json_schema(),
        "error_response": ErrorResponse.model_json_schema(),
    }
    assert {
        name: _canonical_sha256(schema)
        for name, schema in schemas.items()
    } == EXPECTED_API_SCHEMA_HASHES
