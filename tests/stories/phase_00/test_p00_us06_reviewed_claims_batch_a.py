"""P00-US06 acceptance tests for the 71-row reviewed-claim Batch A."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path

import pytest

from tests.benchmarks.contracts import TruthClass
from tests.benchmarks.corpus_registry import (
    ArtifactRole,
    PortableCorpusRegistry,
    load_corpus_registry,
    sha256_file,
)
from tests.benchmarks.reviewed_claim_inventory import (
    BATCH_A_CASE_CLAIM_COUNTS,
    BATCH_A_CLAIM_COUNT,
    BATCH_A_EVIDENCE_PATH,
    build_reviewed_claim_batch_a,
    load_reviewed_claim_batch_a,
)
from tests.benchmarks.reviewed_claims import (
    DISPLAY_PAGE_COORDINATES,
    ClaimReviewStatus,
    ClaimType,
    RegionScope,
    ReviewBatch,
    ReviewRegistryError,
    canonical_review_batch_json,
    review_batch_sha256,
    validate_review_batch_against_registry,
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

EXPECTED_REVIEW_HASHES = {
    "catastrophe-recap": (
        "99b2110820d01d6a63e3677c0b49a3b17d3b5958ec186df0df552009ba976770"
    ),
    "esg-metrics": (
        "174180aa1cb2b42dd2a7deb8692b2c12e69d3edbb3c3d91b3c9934edb07da563"
    ),
    "finance-10k": (
        "3a2a661df038536eb95d72febe43189248df37b243194bfede441e1d38c61aff"
    ),
    "manufacturing-report": (
        "4c38cafd256c090fc9d4041a4465d12f34c0855f8568d25c66fe7eb896a11dd1"
    ),
    "purchase-agreement": (
        "715e14ee37fd5263939d01dd9090b30d2a3c1f6ea6fc703bbb7ca80e529213a4"
    ),
}
EXPECTED_STATUS_COUNTS = {
    ClaimReviewStatus.VERIFIED: 44,
    ClaimReviewStatus.PARTIALLY_VERIFIED: 17,
    ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE: 6,
    ClaimReviewStatus.INCORRECT: 4,
}
EXPECTED_CASE_STATUS_COUNTS = {
    "catastrophe-recap": {
        ClaimReviewStatus.VERIFIED: 9,
        ClaimReviewStatus.PARTIALLY_VERIFIED: 4,
        ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE: 1,
        ClaimReviewStatus.INCORRECT: 1,
    },
    "esg-metrics": {
        ClaimReviewStatus.VERIFIED: 7,
        ClaimReviewStatus.PARTIALLY_VERIFIED: 5,
        ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE: 1,
    },
    "finance-10k": {
        ClaimReviewStatus.VERIFIED: 7,
        ClaimReviewStatus.PARTIALLY_VERIFIED: 3,
        ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE: 1,
    },
    "manufacturing-report": {
        ClaimReviewStatus.VERIFIED: 15,
        ClaimReviewStatus.PARTIALLY_VERIFIED: 3,
        ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE: 2,
        ClaimReviewStatus.INCORRECT: 1,
    },
    "purchase-agreement": {
        ClaimReviewStatus.VERIFIED: 6,
        ClaimReviewStatus.PARTIALLY_VERIFIED: 2,
        ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE: 1,
        ClaimReviewStatus.INCORRECT: 2,
    },
}
EXPECTED_EVIDENCE_COUNTS = {
    TruthClass.VISIBLE_TEXT: 42,
    TruthClass.NATIVE_DATA: 14,
    TruthClass.INFERRED: 10,
    TruthClass.UNKNOWABLE: 4,
    TruthClass.MEASURED: 1,
}
EXPECTED_CLAIM_TYPE_COUNTS = {
    ClaimType.TEXT: 33,
    ClaimType.TABLE: 10,
    ClaimType.PAGE_IDENTITY: 5,
    ClaimType.METADATA: 5,
    ClaimType.CHART: 4,
    ClaimType.GEOMETRY: 4,
    ClaimType.TEXT_STYLE: 4,
    ClaimType.STRUCTURE: 2,
    ClaimType.IMAGE: 1,
    ClaimType.RELATIONSHIP: 1,
    ClaimType.LINK: 1,
    ClaimType.ARTIFACT_INVENTORY: 1,
}
EXPECTED_CASE_MASK_COUNTS = {
    "catastrophe-recap": (8, 13),
    "esg-metrics": (7, 12),
    "finance-10k": (6, 10),
    "manufacturing-report": (15, 18),
    "purchase-agreement": (5, 8),
}
EXPECTED_LOCATOR_PAGE_COUNTS = {
    ("catastrophe-recap", 1): 15,
    ("esg-metrics", 1): 13,
    ("finance-10k", 1): 5,
    ("finance-10k", 2): 5,
    ("finance-10k", 3): 5,
    ("manufacturing-report", 1): 8,
    ("manufacturing-report", 2): 8,
    ("manufacturing-report", 3): 5,
    ("purchase-agreement", 1): 11,
}
PINNED_SEMANTIC_SHA256 = (
    "f6f0ef58f4cb1379f808e8d5bb7253f260a8f643a83e98e75e4d2e1a3fff01ee"
)
PINNED_EVIDENCE_FILE_SHA256 = (
    "f987d84ca1b0d08dfd304d7ea3164a78366643f4b42ef03bc4975d4d09548de4"
)


@pytest.fixture(scope="module")
def registry() -> PortableCorpusRegistry:
    return load_corpus_registry(REGISTRY_PATH)


@pytest.fixture(scope="module")
def batch(registry: PortableCorpusRegistry) -> ReviewBatch:
    return load_reviewed_claim_batch_a(EVIDENCE_PATH, WORKSPACE, registry)


def _source_table_rows(path: Path) -> tuple[tuple[str, str, str, str], ...]:
    """Independently read the bounded Markdown section used as provenance."""

    section = path.read_text(encoding="utf-8").split(
        "## Expert element validation",
        maxsplit=1,
    )[1]
    section = section.split("\n## ", maxsplit=1)[0]
    rows = []
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = tuple(cell.strip() for cell in line[1:-1].split("|"))
        assert len(cells) == 4
        if cells[2] == "Status" or set("".join(cells)) <= {"-", ":"}:
            continue
        rows.append(cells)
    return tuple(rows)


def _source_status(raw_status: str) -> ClaimReviewStatus:
    normalized = raw_status.replace("**", "").strip()
    prefixes = {
        "Verified": ClaimReviewStatus.VERIFIED,
        "Partially verified": ClaimReviewStatus.PARTIALLY_VERIFIED,
        "Not independently verifiable": (
            ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE
        ),
        "Incorrect": ClaimReviewStatus.INCORRECT,
    }
    for prefix, status in prefixes.items():
        if normalized == prefix or normalized.startswith(f"{prefix} "):
            return status
    raise AssertionError(f"unexpected source status: {raw_status}")


def _expected_claim(cells: tuple[str, str, str, str]) -> str:
    subject, representation, raw_status, assessment = cells
    return (
        f"{subject} — {representation}. "
        f"Review verdict: {raw_status}. Assessment: {assessment}"
    )


def test_all_five_triplets_have_approved_no_exceptions_custody(
    registry: PortableCorpusRegistry,
) -> None:
    assert registry.custody.decision == "public-redistributable"
    assert registry.custody.no_exceptions is True
    assert registry.custody.derived_annotations_covered is True

    cases = [registry.case_by_id(case_id) for case_id in BATCH_A_CASE_CLAIM_COUNTS]
    assert all(case.custody == "public-redistributable" for case in cases)
    assert all(
        tuple(artifact.role for artifact in case.artifacts)
        == (
            ArtifactRole.SOURCE,
            ArtifactRole.EXPERT_MARKDOWN,
            ArtifactRole.EXPERT_JSON,
        )
        for case in cases
    )


def test_exactly_71_rows_map_one_to_one_without_expanding_item_ranges(
    batch: ReviewBatch,
    registry: PortableCorpusRegistry,
) -> None:
    assert batch.claim_count == len(batch.claims) == BATCH_A_CLAIM_COUNT
    assert batch.case_claim_counts == BATCH_A_CASE_CLAIM_COUNTS

    for case_id, expected_count in BATCH_A_CASE_CLAIM_COUNTS.items():
        case = registry.case_by_id(case_id)
        review_path = WORKSPACE / case.review_path
        source_rows = _source_table_rows(review_path)
        claims = tuple(
            claim for claim in batch.claims if claim.case_id == case_id
        )

        assert len(source_rows) == len(claims) == expected_count
        assert sha256_file(review_path) == EXPECTED_REVIEW_HASHES[case_id]
        assert [claim.claim for claim in claims] == [
            _expected_claim(row) for row in source_rows
        ]
        assert [claim.review_status for claim in claims] == [
            _source_status(row[2]) for row in source_rows
        ]
        assert [claim.provenance.review_row_id for claim in claims] == [
            f"{case_id}:expert-row-{ordinal:02d}"
            for ordinal in range(1, expected_count + 1)
        ]
        assert all(
            claim.provenance.review_path == case.review_path
            and claim.provenance.review_sha256 == EXPECTED_REVIEW_HASHES[case_id]
            for claim in claims
        )


def test_status_type_and_evidence_totals_are_fully_classified(
    batch: ReviewBatch,
) -> None:
    assert Counter(claim.review_status for claim in batch.claims) == (
        EXPECTED_STATUS_COUNTS
    )
    assert Counter(claim.evidence_class for claim in batch.claims) == (
        EXPECTED_EVIDENCE_COUNTS
    )
    assert Counter(claim.claim_type for claim in batch.claims) == (
        EXPECTED_CLAIM_TYPE_COUNTS
    )
    assert ClaimReviewStatus.POTENTIALLY_INFERRED not in {
        claim.review_status for claim in batch.claims
    }

    for case_id, expected in EXPECTED_CASE_STATUS_COUNTS.items():
        actual = Counter(
            claim.review_status
            for claim in batch.claims
            if claim.case_id == case_id
        )
        assert actual == expected


def test_masks_preserve_partial_semantics_and_exclude_unsupported_truth(
    batch: ReviewBatch,
) -> None:
    assert sum(
        claim.inclusion_mask.literal_parity for claim in batch.claims
    ) == 41
    assert sum(
        claim.inclusion_mask.semantic_parity for claim in batch.claims
    ) == 61

    unsupported = {
        ClaimReviewStatus.INCORRECT,
        ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE,
        ClaimReviewStatus.POTENTIALLY_INFERRED,
    }
    nonliteral_evidence = {
        TruthClass.MEASURED,
        TruthClass.INFERRED,
        TruthClass.UNKNOWABLE,
    }
    for claim in batch.claims:
        if claim.review_status in unsupported:
            assert claim.inclusion_mask.literal_parity is False
            assert claim.inclusion_mask.semantic_parity is False
        if claim.review_status is ClaimReviewStatus.PARTIALLY_VERIFIED:
            assert claim.inclusion_mask.literal_parity is False
            assert claim.inclusion_mask.semantic_parity is True
        if claim.evidence_class in nonliteral_evidence:
            assert claim.inclusion_mask.literal_parity is False

    for case_id, expected in EXPECTED_CASE_MASK_COUNTS.items():
        claims = [claim for claim in batch.claims if claim.case_id == case_id]
        assert (
            sum(claim.inclusion_mask.literal_parity for claim in claims),
            sum(claim.inclusion_mask.semantic_parity for claim in claims),
        ) == expected


def test_the_only_measured_row_has_a_reviewed_derivation_and_cannot_score(
    batch: ReviewBatch,
) -> None:
    measured = [
        claim for claim in batch.claims
        if claim.evidence_class is TruthClass.MEASURED
    ]
    assert [claim.claim_id for claim in measured] == [
        "p00-us06:catastrophe-recap:expert-row-09"
    ]

    claim = measured[0]
    assert claim.review_status is ClaimReviewStatus.INCORRECT
    assert claim.inclusion_mask.literal_parity is False
    assert claim.inclusion_mask.semantic_parity is False
    assert claim.derivation is not None
    assert claim.derivation.tolerance == 1
    assert claim.derivation.tolerance_unit == "2025_USD_billions"
    assert "linear least-squares" in claim.derivation.method
    assert sum(claim.derivation is not None for claim in batch.claims) == 1


def test_all_75_locators_reconcile_with_registered_physical_and_printed_pages(
    batch: ReviewBatch,
    registry: PortableCorpusRegistry,
) -> None:
    assert validate_review_batch_against_registry(batch, registry) is batch
    locators = [
        locator
        for claim in batch.claims
        for locator in claim.locators
    ]
    assert len(locators) == 75
    assert Counter(
        (locator.case_id, locator.physical_page) for locator in locators
    ) == EXPECTED_LOCATOR_PAGE_COUNTS
    assert all(locator.coordinates == DISPLAY_PAGE_COORDINATES for locator in locators)
    assert all(locator.bbox is None for locator in locators)
    assert all(
        locator.region_scope is RegionScope.PAGE
        for claim in batch.claims
        if claim.claim_type is ClaimType.PAGE_IDENTITY
        for locator in claim.locators
    )
    assert {
        locator.printed_page
        for claim in batch.claims
        if claim.case_id == "purchase-agreement"
        for locator in claim.locators
    } == {None}


def test_persisted_batch_reloads_to_one_canonical_identity(
    batch: ReviewBatch,
    registry: PortableCorpusRegistry,
) -> None:
    built_first = build_reviewed_claim_batch_a(WORKSPACE, registry)
    built_second = build_reviewed_claim_batch_a(WORKSPACE, registry)
    canonical = canonical_review_batch_json(batch)

    assert batch == built_first == built_second
    assert canonical == canonical_review_batch_json(built_first)
    assert review_batch_sha256(batch) == PINNED_SEMANTIC_SHA256
    assert hashlib.sha256((canonical + "\n").encode("utf-8")).hexdigest() == (
        PINNED_EVIDENCE_FILE_SHA256
    )
    assert EVIDENCE_PATH.read_text(encoding="utf-8") == canonical + "\n"


def test_persisted_claim_drift_fails_closed(
    batch: ReviewBatch,
    registry: PortableCorpusRegistry,
    tmp_path: Path,
) -> None:
    payload = json.loads(canonical_review_batch_json(batch))
    payload["claims"][0]["claim"] += " Drift."
    drifted_path = tmp_path / "drifted-batch.json"
    drifted_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    with pytest.raises(
        ReviewRegistryError,
        match="does not match frozen review rows and policies",
    ):
        load_reviewed_claim_batch_a(
            drifted_path,
            WORKSPACE,
            registry,
        )


def test_frozen_review_drift_fails_before_claim_construction(
    registry: PortableCorpusRegistry,
    tmp_path: Path,
) -> None:
    for case_id in BATCH_A_CASE_CLAIM_COUNTS:
        case = registry.case_by_id(case_id)
        source = WORKSPACE / case.review_path
        target = tmp_path / case.review_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())

    catastrophe = (
        tmp_path
        / registry.case_by_id("catastrophe-recap").review_path
    )
    catastrophe.write_bytes(catastrophe.read_bytes() + b" ")

    with pytest.raises(
        ReviewRegistryError,
        match="catastrophe-recap review SHA-256 changed",
    ):
        build_reviewed_claim_batch_a(tmp_path, registry)
