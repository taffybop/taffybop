"""Regression anchors for the P00-US08 reviewed-claim Batch C."""

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
from tests.benchmarks.reviewed_claim_inventory import (
    BATCH_A_EVIDENCE_PATH,
    BATCH_B_EVIDENCE_PATH,
    BATCH_C_EVIDENCE_PATH,
    load_reviewed_claim_batch_a,
    load_reviewed_claim_batch_b,
    load_reviewed_claim_batch_c,
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
BATCH_C_PATH = WORKSPACE / BATCH_C_EVIDENCE_PATH
PINNED_REVIEW_HASHES = {
    "tracker/benchmarks/llamaparse-15/cases/egov-survey.md": (
        "bbdb74c3c05204006c67d5868ad9f7229221c469d6e31a04906a67ac4980bc25"
    ),
    "tracker/benchmarks/llamaparse-15/cases/health-report.md": (
        "13e74b08061571472993123e5bcfa1ac00ca96a5191a4887bcb94589ccc876f5"
    ),
    "tracker/benchmarks/llamaparse-15/cases/postal-10k.md": (
        "e0eb3d81b012018a1b1a2d4d37a17f5c9f62c0014e52bd652845d6ac7fc9cce7"
    ),
    "tracker/benchmarks/llamaparse-15/cases/settlement-agreement.md": (
        "1e1680bd2b28eca6c68c364a32e1381d64ae7d5c8155325ac03c10e4d8addba9"
    ),
    "tracker/benchmarks/llamaparse-15/cases/uber-earnings.md": (
        "344aa02fc3e0315b912e42489331951c39f6bdbb9b7e0e4fdfc17ebb44018567"
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
PINNED_BATCH_C_FILE_SHA256 = (
    "1411d75d2701e51b815f9f3c0e0e5ba5f799f6ec32ca2788cd31ee4f69f05be1"
)
PINNED_BATCH_C_SEMANTIC_SHA256 = (
    "69c58b8ab7a3b9bdd21bc49183fb5334ee88bee1a4850061820b551ae416eb89"
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


def test_all_batch_evidence_and_batch_c_reviews_retain_pinned_hashes() -> None:
    assert sha256_file(BATCH_A_PATH) == PINNED_BATCH_A_FILE_SHA256
    assert sha256_file(BATCH_B_PATH) == PINNED_BATCH_B_FILE_SHA256
    assert sha256_file(BATCH_C_PATH) == PINNED_BATCH_C_FILE_SHA256
    assert {
        path: sha256_file(WORKSPACE / path)
        for path in PINNED_REVIEW_HASHES
    } == PINNED_REVIEW_HASHES


def test_all_15_batch_c_triplet_artifacts_retain_registered_bytes() -> None:
    registry = load_corpus_registry(REGISTRY_PATH)
    case_ids = {
        "egov-survey",
        "health-report",
        "postal-10k",
        "settlement-agreement",
        "uber-earnings",
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


def test_complete_corpus_semantics_retain_pinned_totals_and_identity() -> None:
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
    batch_c = load_reviewed_claim_batch_c(
        BATCH_C_PATH,
        WORKSPACE,
        registry,
    )
    claims = (*batch_a.claims, *batch_b.claims, *batch_c.claims)

    assert review_batch_sha256(batch_a) == PINNED_BATCH_A_SEMANTIC_SHA256
    assert review_batch_sha256(batch_b) == PINNED_BATCH_B_SEMANTIC_SHA256
    assert review_batch_sha256(batch_c) == PINNED_BATCH_C_SEMANTIC_SHA256
    assert len(claims) == 210
    assert len({claim.claim_id for claim in claims}) == 210
    assert len({
        (
            claim.provenance.review_path,
            claim.provenance.review_row_id,
        )
        for claim in claims
    }) == 210
    assert len({claim.case_id for claim in claims}) == 15
    assert Counter(claim.review_status for claim in claims) == {
        ClaimReviewStatus.VERIFIED: 121,
        ClaimReviewStatus.PARTIALLY_VERIFIED: 41,
        ClaimReviewStatus.INCORRECT: 21,
        ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE: 17,
        ClaimReviewStatus.POTENTIALLY_INFERRED: 10,
    }
    assert Counter(claim.evidence_class for claim in claims) == {
        TruthClass.VISIBLE_TEXT: 107,
        TruthClass.NATIVE_DATA: 42,
        TruthClass.INFERRED: 40,
        TruthClass.UNKNOWABLE: 14,
        TruthClass.EMBEDDED_DATA: 3,
        TruthClass.MEASURED: 4,
    }
    assert sum(len(claim.locators) for claim in claims) == 271
    assert sum(claim.derivation is not None for claim in claims) == 4
    assert sum(
        claim.inclusion_mask.literal_parity for claim in claims
    ) == 109
    assert sum(
        claim.inclusion_mask.semantic_parity for claim in claims
    ) == 162


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
        if (
            "reviewed_claim_inventory" in source
            or BATCH_C_EVIDENCE_PATH in source
        ):
            violations.append(
                (path.relative_to(WORKSPACE).as_posix(), "p00-us08")
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
