"""Regression anchors for the P00-US06 reviewed-claim Batch A."""

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
    load_reviewed_claim_batch_a,
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
EVIDENCE_PATH = WORKSPACE / BATCH_A_EVIDENCE_PATH
PINNED_REVIEW_HASHES = {
    "tracker/benchmarks/llamaparse-15/cases/catastrophe-recap.md": (
        "99b2110820d01d6a63e3677c0b49a3b17d3b5958ec186df0df552009ba976770"
    ),
    "tracker/benchmarks/llamaparse-15/cases/esg-metrics.md": (
        "174180aa1cb2b42dd2a7deb8692b2c12e69d3edbb3c3d91b3c9934edb07da563"
    ),
    "tracker/benchmarks/llamaparse-15/cases/finance-10k.md": (
        "3a2a661df038536eb95d72febe43189248df37b243194bfede441e1d38c61aff"
    ),
    "tracker/benchmarks/llamaparse-15/cases/manufacturing-report.md": (
        "4c38cafd256c090fc9d4041a4465d12f34c0855f8568d25c66fe7eb896a11dd1"
    ),
    "tracker/benchmarks/llamaparse-15/cases/purchase-agreement.md": (
        "715e14ee37fd5263939d01dd9090b30d2a3c1f6ea6fc703bbb7ca80e529213a4"
    ),
}
PINNED_EVIDENCE_FILE_SHA256 = (
    "f987d84ca1b0d08dfd304d7ea3164a78366643f4b42ef03bc4975d4d09548de4"
)
PINNED_BATCH_SEMANTIC_SHA256 = (
    "f6f0ef58f4cb1379f808e8d5bb7253f260a8f643a83e98e75e4d2e1a3fff01ee"
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


def test_batch_a_evidence_and_source_reviews_retain_pinned_hashes() -> None:
    assert sha256_file(EVIDENCE_PATH) == PINNED_EVIDENCE_FILE_SHA256
    assert {
        path: sha256_file(WORKSPACE / path)
        for path in PINNED_REVIEW_HASHES
    } == PINNED_REVIEW_HASHES


def test_all_15_batch_a_triplet_artifacts_retain_registered_bytes() -> None:
    registry = load_corpus_registry(REGISTRY_PATH)
    case_ids = {
        "catastrophe-recap",
        "esg-metrics",
        "finance-10k",
        "manufacturing-report",
        "purchase-agreement",
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


def test_batch_a_semantics_and_masks_retain_pinned_totals() -> None:
    registry = load_corpus_registry(REGISTRY_PATH)
    batch = load_reviewed_claim_batch_a(
        EVIDENCE_PATH,
        WORKSPACE,
        registry,
    )

    assert review_batch_sha256(batch) == PINNED_BATCH_SEMANTIC_SHA256
    assert Counter(claim.review_status for claim in batch.claims) == {
        ClaimReviewStatus.VERIFIED: 44,
        ClaimReviewStatus.PARTIALLY_VERIFIED: 17,
        ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE: 6,
        ClaimReviewStatus.INCORRECT: 4,
    }
    assert sum(
        claim.inclusion_mask.literal_parity for claim in batch.claims
    ) == 41
    assert sum(
        claim.inclusion_mask.semantic_parity for claim in batch.claims
    ) == 61


def test_production_tree_cannot_import_batch_a_inventory() -> None:
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
        if "reviewed_claim_inventory" in source or BATCH_A_EVIDENCE_PATH in source:
            violations.append(
                (path.relative_to(WORKSPACE).as_posix(), "p00-us06")
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
