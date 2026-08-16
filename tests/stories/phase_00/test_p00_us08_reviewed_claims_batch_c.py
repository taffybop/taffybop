"""P00-US08 acceptance tests for the 63-row reviewed-claim Batch C."""

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
    BATCH_A_EVIDENCE_PATH,
    BATCH_B_CASE_CLAIM_COUNTS,
    BATCH_B_EVIDENCE_PATH,
    BATCH_C_CASE_CLAIM_COUNTS,
    BATCH_C_CLAIM_COUNT,
    BATCH_C_EVIDENCE_PATH,
    build_reviewed_claim_batch_c,
    load_reviewed_claim_batch_a,
    load_reviewed_claim_batch_b,
    load_reviewed_claim_batch_c,
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
EVIDENCE_PATH = WORKSPACE / BATCH_C_EVIDENCE_PATH
BATCH_A_PATH = WORKSPACE / BATCH_A_EVIDENCE_PATH
BATCH_B_PATH = WORKSPACE / BATCH_B_EVIDENCE_PATH

EXPECTED_REVIEW_HASHES = {
    "egov-survey": (
        "bbdb74c3c05204006c67d5868ad9f7229221c469d6e31a04906a67ac4980bc25"
    ),
    "health-report": (
        "13e74b08061571472993123e5bcfa1ac00ca96a5191a4887bcb94589ccc876f5"
    ),
    "postal-10k": (
        "e0eb3d81b012018a1b1a2d4d37a17f5c9f62c0014e52bd652845d6ac7fc9cce7"
    ),
    "settlement-agreement": (
        "1e1680bd2b28eca6c68c364a32e1381d64ae7d5c8155325ac03c10e4d8addba9"
    ),
    "uber-earnings": (
        "344aa02fc3e0315b912e42489331951c39f6bdbb9b7e0e4fdfc17ebb44018567"
    ),
}
EXPECTED_STATUS_COUNTS = {
    ClaimReviewStatus.VERIFIED: 34,
    ClaimReviewStatus.PARTIALLY_VERIFIED: 9,
    ClaimReviewStatus.INCORRECT: 9,
    ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE: 6,
    ClaimReviewStatus.POTENTIALLY_INFERRED: 5,
}
EXPECTED_CASE_STATUS_COUNTS = {
    "egov-survey": {
        ClaimReviewStatus.VERIFIED: 9,
        ClaimReviewStatus.PARTIALLY_VERIFIED: 2,
        ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE: 1,
    },
    "health-report": {
        ClaimReviewStatus.VERIFIED: 8,
        ClaimReviewStatus.PARTIALLY_VERIFIED: 1,
        ClaimReviewStatus.INCORRECT: 1,
        ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE: 2,
    },
    "postal-10k": {
        ClaimReviewStatus.VERIFIED: 5,
        ClaimReviewStatus.PARTIALLY_VERIFIED: 1,
        ClaimReviewStatus.INCORRECT: 5,
        ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE: 1,
    },
    "settlement-agreement": {
        ClaimReviewStatus.VERIFIED: 5,
        ClaimReviewStatus.PARTIALLY_VERIFIED: 2,
        ClaimReviewStatus.INCORRECT: 2,
        ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE: 1,
    },
    "uber-earnings": {
        ClaimReviewStatus.VERIFIED: 7,
        ClaimReviewStatus.PARTIALLY_VERIFIED: 3,
        ClaimReviewStatus.INCORRECT: 1,
        ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE: 1,
        ClaimReviewStatus.POTENTIALLY_INFERRED: 5,
    },
}
EXPECTED_EVIDENCE_COUNTS = {
    TruthClass.VISIBLE_TEXT: 29,
    TruthClass.NATIVE_DATA: 12,
    TruthClass.INFERRED: 12,
    TruthClass.UNKNOWABLE: 5,
    TruthClass.EMBEDDED_DATA: 2,
    TruthClass.MEASURED: 3,
}
EXPECTED_CLAIM_TYPE_COUNTS = {
    ClaimType.TEXT: 17,
    ClaimType.TABLE: 8,
    ClaimType.CHART: 8,
    ClaimType.METADATA: 8,
    ClaimType.PAGE_IDENTITY: 5,
    ClaimType.IMAGE: 4,
    ClaimType.ARTIFACT_INVENTORY: 3,
    ClaimType.LINK: 2,
    ClaimType.GEOMETRY: 2,
    ClaimType.STRUCTURE: 2,
    ClaimType.DIAGRAM: 2,
    ClaimType.TEXT_STYLE: 1,
    ClaimType.RELATIONSHIP: 1,
}
EXPECTED_CASE_MASK_COUNTS = {
    "egov-survey": (8, 11),
    "health-report": (8, 9),
    "postal-10k": (5, 6),
    "settlement-agreement": (5, 7),
    "uber-earnings": (6, 10),
}
EXPECTED_LOCATOR_PAGE_COUNTS = {
    ("egov-survey", 1): 12,
    ("health-report", 1): 12,
    ("postal-10k", 1): 5,
    ("postal-10k", 2): 8,
    ("postal-10k", 3): 7,
    ("settlement-agreement", 1): 10,
    ("uber-earnings", 1): 5,
    ("uber-earnings", 2): 11,
    ("uber-earnings", 3): 5,
}
EXPECTED_MEASURED_DERIVATIONS = {
    "p00-us08:uber-earnings:expert-row-06": (
        "Linear interpolation of shared-baseline PDF vector bar heights "
        "against the printed $56B (2022) and $82B (Q1’25 ARR) endpoint labels",
        2,
        "USD_billions",
    ),
    "p00-us08:uber-earnings:expert-row-08": (
        "Linear interpolation of shared-baseline PDF vector bar heights "
        "against the printed $0.6B and $3.1B endpoint labels",
        0.25,
        "USD_billions",
    ),
    "p00-us08:uber-earnings:expert-row-10": (
        "Linear interpolation of PDF vector line-point y positions against "
        "the printed 1.0% and 3.7% endpoint labels",
        0.25,
        "percentage_points",
    ),
}
PINNED_SEMANTIC_SHA256 = (
    "69c58b8ab7a3b9bdd21bc49183fb5334ee88bee1a4850061820b551ae416eb89"
)
PINNED_EVIDENCE_FILE_SHA256 = (
    "1411d75d2701e51b815f9f3c0e0e5ba5f799f6ec32ca2788cd31ee4f69f05be1"
)
PINNED_BATCH_A_SEMANTIC_SHA256 = (
    "f6f0ef58f4cb1379f808e8d5bb7253f260a8f643a83e98e75e4d2e1a3fff01ee"
)
PINNED_BATCH_A_FILE_SHA256 = (
    "f987d84ca1b0d08dfd304d7ea3164a78366643f4b42ef03bc4975d4d09548de4"
)
PINNED_BATCH_B_SEMANTIC_SHA256 = (
    "9afe6c098adcd32e3a8370af5ecb2b27ac4730f098e39128e787eef991990d0f"
)
PINNED_BATCH_B_FILE_SHA256 = (
    "7e4728c1c5d76a6453d42c640de8a25c24989ed3a160cac2fe4640b22a55814e"
)


@pytest.fixture(scope="module")
def registry() -> PortableCorpusRegistry:
    return load_corpus_registry(REGISTRY_PATH)


@pytest.fixture(scope="module")
def batch(registry: PortableCorpusRegistry) -> ReviewBatch:
    return load_reviewed_claim_batch_c(EVIDENCE_PATH, WORKSPACE, registry)


def _split_source_row(line: str) -> tuple[str, ...]:
    """Independently split escaped and inline-code pipes in one table row."""

    cells: list[str] = []
    current: list[str] = []
    code_span = False
    index = 1
    while index < len(line) - 1:
        char = line[index]
        if char == "\\" and index + 1 < len(line) - 1:
            current.extend((char, line[index + 1]))
            index += 2
            continue
        if char == "`":
            code_span = not code_span
            current.append(char)
        elif char == "|" and not code_span:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    cells.append("".join(current).strip())
    assert code_span is False
    return tuple(cells)


def _source_table_rows(
    path: Path,
) -> tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]:
    section = path.read_text(encoding="utf-8").split(
        "## Expert element validation",
        maxsplit=1,
    )[1]
    section = section.split("\n## ", maxsplit=1)[0]
    headers: tuple[str, ...] | None = None
    rows = []
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = _split_source_row(line)
        if set("".join(cells)) <= {"-", ":"}:
            continue
        if "Status" in cells:
            headers = cells
            assert len(headers) in {4, 5}
            continue
        assert headers is not None
        assert len(cells) == len(headers)
        rows.append((headers, cells))
    return tuple(rows)


def _source_status(raw_status: str) -> ClaimReviewStatus:
    normalized = raw_status.replace("**", "").strip()
    prefixes = (
        (
            "Not independently verifiable",
            ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE,
        ),
        ("Partially verified", ClaimReviewStatus.PARTIALLY_VERIFIED),
        ("Potentially inferred", ClaimReviewStatus.POTENTIALLY_INFERRED),
        ("Incorrect", ClaimReviewStatus.INCORRECT),
        ("Verified", ClaimReviewStatus.VERIFIED),
    )
    for prefix, status in prefixes:
        if normalized == prefix or normalized.startswith(f"{prefix} "):
            return status
    raise AssertionError(f"unexpected source status: {raw_status}")


def _expected_claim(
    headers: tuple[str, ...],
    cells: tuple[str, ...],
) -> str:
    status_index = headers.index("Status")
    supplemental = "".join(
        f"{header}: {value}. "
        for header, value in zip(
            headers[2:status_index],
            cells[2:status_index],
            strict=True,
        )
    )
    return (
        f"{cells[0]} — {cells[1]}. {supplemental}"
        f"Review verdict: {cells[status_index]}. Assessment: {cells[-1]}"
    )


def test_all_five_batch_c_triplets_have_approved_custody_and_integrity(
    registry: PortableCorpusRegistry,
) -> None:
    assert registry.custody.decision == "public-redistributable"
    assert registry.custody.no_exceptions is True
    assert registry.custody.derived_annotations_covered is True

    cases = [registry.case_by_id(case_id) for case_id in BATCH_C_CASE_CLAIM_COUNTS]
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
    assert sum(len(case.artifacts) for case in cases) == 15
    for case in cases:
        for artifact in case.artifacts:
            artifact_path = WORKSPACE / artifact.path
            assert artifact_path.stat().st_size == artifact.size_bytes
            assert sha256_file(artifact_path) == artifact.sha256


def test_exactly_63_rows_map_one_to_one_across_four_and_five_column_tables(
    batch: ReviewBatch,
    registry: PortableCorpusRegistry,
) -> None:
    assert batch.claim_count == len(batch.claims) == BATCH_C_CLAIM_COUNT
    assert batch.case_claim_counts == BATCH_C_CASE_CLAIM_COUNTS

    header_widths = set()
    for case_id, expected_count in BATCH_C_CASE_CLAIM_COUNTS.items():
        case = registry.case_by_id(case_id)
        review_path = WORKSPACE / case.review_path
        source_rows = _source_table_rows(review_path)
        header_widths.update(len(headers) for headers, _ in source_rows)
        claims = tuple(
            claim for claim in batch.claims if claim.case_id == case_id
        )

        assert len(source_rows) == len(claims) == expected_count
        assert sha256_file(review_path) == EXPECTED_REVIEW_HASHES[case_id]
        assert [claim.claim for claim in claims] == [
            _expected_claim(headers, cells)
            for headers, cells in source_rows
        ]
        assert [claim.review_status for claim in claims] == [
            _source_status(cells[headers.index("Status")])
            for headers, cells in source_rows
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

    assert header_widths == {4, 5}
    health_rows = _source_table_rows(
        WORKSPACE / registry.case_by_id("health-report").review_path
    )
    assert health_rows[0][1][1] == "Header `| 103`"


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

    for case_id, expected in EXPECTED_CASE_STATUS_COUNTS.items():
        actual = Counter(
            claim.review_status
            for claim in batch.claims
            if claim.case_id == case_id
        )
        assert actual == expected


def test_masks_preserve_supported_semantics_and_exclude_unsupported_truth(
    batch: ReviewBatch,
) -> None:
    assert sum(
        claim.inclusion_mask.literal_parity for claim in batch.claims
    ) == 32
    assert sum(
        claim.inclusion_mask.semantic_parity for claim in batch.claims
    ) == 43

    unsupported = {
        ClaimReviewStatus.INCORRECT,
        ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE,
        ClaimReviewStatus.POTENTIALLY_INFERRED,
    }
    for claim in batch.claims:
        if claim.review_status in unsupported:
            assert claim.inclusion_mask.literal_parity is False
            assert claim.inclusion_mask.semantic_parity is False
        if claim.review_status is ClaimReviewStatus.PARTIALLY_VERIFIED:
            assert claim.inclusion_mask.literal_parity is False
            assert claim.inclusion_mask.semantic_parity is True
        if claim.evidence_class in {
            TruthClass.MEASURED,
            TruthClass.INFERRED,
            TruthClass.UNKNOWABLE,
        }:
            assert claim.inclusion_mask.literal_parity is False

    for case_id, expected in EXPECTED_CASE_MASK_COUNTS.items():
        claims = [claim for claim in batch.claims if claim.case_id == case_id]
        assert (
            sum(claim.inclusion_mask.literal_parity for claim in claims),
            sum(claim.inclusion_mask.semantic_parity for claim in claims),
        ) == expected


def test_measured_claims_have_pinned_derivations_and_uncalibrated_health_does_not(
    batch: ReviewBatch,
) -> None:
    by_id = {claim.claim_id: claim for claim in batch.claims}
    measured = {
        claim.claim_id: claim
        for claim in batch.claims
        if claim.evidence_class is TruthClass.MEASURED
    }
    assert set(measured) == set(EXPECTED_MEASURED_DERIVATIONS)

    for claim_id, (method, tolerance, unit) in (
        EXPECTED_MEASURED_DERIVATIONS.items()
    ):
        claim = measured[claim_id]
        assert claim.review_status is ClaimReviewStatus.POTENTIALLY_INFERRED
        assert claim.inclusion_mask.literal_parity is False
        assert claim.inclusion_mask.semantic_parity is False
        assert claim.derivation is not None
        assert (
            claim.derivation.method,
            claim.derivation.tolerance,
            claim.derivation.tolerance_unit,
        ) == (method, tolerance, unit)

    uncalibrated = by_id["p00-us08:health-report:expert-row-07"]
    assert uncalibrated.claim_type is ClaimType.CHART
    assert uncalibrated.review_status is ClaimReviewStatus.INCORRECT
    assert uncalibrated.evidence_class is TruthClass.INFERRED
    assert uncalibrated.derivation is None
    assert all(
        claim.derivation is None
        for claim in batch.claims
        if claim.claim_id not in EXPECTED_MEASURED_DERIVATIONS
    )


def test_all_75_locators_reconcile_with_registered_page_maps(
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
    assert all(
        locator.region_scope is RegionScope.DERIVED_ARTIFACT
        for claim in batch.claims
        if claim.claim_type in {
            ClaimType.METADATA,
            ClaimType.ARTIFACT_INVENTORY,
        }
        for locator in claim.locators
    )
    assert all(
        locator.printed_page
        == registry.case_by_id(locator.case_id).pages[
            locator.physical_page - 1
        ].printed_page
        for locator in locators
    )


def test_batch_c_reloads_to_one_canonical_identity(
    batch: ReviewBatch,
    registry: PortableCorpusRegistry,
) -> None:
    first = build_reviewed_claim_batch_c(WORKSPACE, registry)
    second = build_reviewed_claim_batch_c(WORKSPACE, registry)
    canonical = canonical_review_batch_json(batch)

    assert batch == first == second
    assert canonical == canonical_review_batch_json(first)
    assert review_batch_sha256(batch) == PINNED_SEMANTIC_SHA256
    assert hashlib.sha256((canonical + "\n").encode("utf-8")).hexdigest() == (
        PINNED_EVIDENCE_FILE_SHA256
    )
    assert EVIDENCE_PATH.read_text(encoding="utf-8") == canonical + "\n"


def test_batches_a_b_and_c_are_stable_and_reconcile_to_the_210_claim_corpus(
    batch: ReviewBatch,
    registry: PortableCorpusRegistry,
) -> None:
    batch_a = load_reviewed_claim_batch_a(BATCH_A_PATH, WORKSPACE, registry)
    batch_b = load_reviewed_claim_batch_b(BATCH_B_PATH, WORKSPACE, registry)
    assert sha256_file(BATCH_A_PATH) == PINNED_BATCH_A_FILE_SHA256
    assert review_batch_sha256(batch_a) == PINNED_BATCH_A_SEMANTIC_SHA256
    assert sha256_file(BATCH_B_PATH) == PINNED_BATCH_B_FILE_SHA256
    assert review_batch_sha256(batch_b) == PINNED_BATCH_B_SEMANTIC_SHA256

    claims = (*batch_a.claims, *batch_b.claims, *batch.claims)
    expected_cases = {
        *BATCH_A_CASE_CLAIM_COUNTS,
        *BATCH_B_CASE_CLAIM_COUNTS,
        *BATCH_C_CASE_CLAIM_COUNTS,
    }
    assert len(claims) == 210
    assert len(expected_cases) == 15
    assert {claim.case_id for claim in claims} == expected_cases
    assert len({claim.claim_id for claim in claims}) == 210
    assert len({
        (claim.provenance.review_path, claim.provenance.review_row_id)
        for claim in claims
    }) == 210
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
    assert sum(claim.inclusion_mask.literal_parity for claim in claims) == 109
    assert sum(claim.inclusion_mask.semantic_parity for claim in claims) == 162
    assert sum(len(claim.locators) for claim in claims) == 271
    assert sum(claim.derivation is not None for claim in claims) == 4


def test_persisted_batch_c_claim_drift_fails_closed(
    batch: ReviewBatch,
    registry: PortableCorpusRegistry,
    tmp_path: Path,
) -> None:
    payload = json.loads(canonical_review_batch_json(batch))
    payload["claims"][0]["claim"] += " Drift."
    drifted_path = tmp_path / "drifted-batch-c.json"
    drifted_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    with pytest.raises(
        ReviewRegistryError,
        match="does not match frozen review rows and policies",
    ):
        load_reviewed_claim_batch_c(
            drifted_path,
            WORKSPACE,
            registry,
        )


def test_frozen_batch_c_review_drift_fails_before_construction(
    registry: PortableCorpusRegistry,
    tmp_path: Path,
) -> None:
    for case_id in BATCH_C_CASE_CLAIM_COUNTS:
        case = registry.case_by_id(case_id)
        source = WORKSPACE / case.review_path
        target = tmp_path / case.review_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())

    egov = tmp_path / registry.case_by_id("egov-survey").review_path
    egov.write_bytes(egov.read_bytes() + b" ")

    with pytest.raises(
        ReviewRegistryError,
        match="egov-survey review SHA-256 changed",
    ):
        build_reviewed_claim_batch_c(tmp_path, registry)
