"""P00-US07 acceptance tests for the 76-row reviewed-claim Batch B."""

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
    BATCH_A_EVIDENCE_PATH,
    BATCH_B_CASE_CLAIM_COUNTS,
    BATCH_B_CLAIM_COUNT,
    BATCH_B_EVIDENCE_PATH,
    build_reviewed_claim_batch_b,
    load_reviewed_claim_batch_a,
    load_reviewed_claim_batch_b,
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
EVIDENCE_PATH = WORKSPACE / BATCH_B_EVIDENCE_PATH
BATCH_A_PATH = WORKSPACE / BATCH_A_EVIDENCE_PATH

EXPECTED_REVIEW_HASHES = {
    "clean-energy": (
        "1345fc03e3f55f415dd7682c827e24b6022d25b46ef0ee68e8437bc145f0ca5a"
    ),
    "clinical-study": (
        "fa5c1e863b7cee50ca4eea4b6c2debd042c7d9bbe143663cad64a26a07f5806f"
    ),
    "component-datasheet": (
        "6e41940bd8ffd61dbf7fce8ec4882f8935f6a94c481c844d7dc828812c4b53fe"
    ),
    "insurance-acord": (
        "327e9ed62a2703075e00434d5b02bead11525692d43178198a9377ca0adeaddb"
    ),
    "ny-timetable": (
        "68e1ce268850da1fa09180c0bd0262976ba983dcc5de039c21b1bbde91c7822b"
    ),
}
EXPECTED_STATUS_COUNTS = {
    ClaimReviewStatus.VERIFIED: 43,
    ClaimReviewStatus.PARTIALLY_VERIFIED: 15,
    ClaimReviewStatus.INCORRECT: 8,
    ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE: 5,
    ClaimReviewStatus.POTENTIALLY_INFERRED: 5,
}
EXPECTED_CASE_STATUS_COUNTS = {
    "clean-energy": {
        ClaimReviewStatus.VERIFIED: 10,
        ClaimReviewStatus.PARTIALLY_VERIFIED: 2,
        ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE: 1,
        ClaimReviewStatus.POTENTIALLY_INFERRED: 1,
    },
    "clinical-study": {
        ClaimReviewStatus.VERIFIED: 13,
        ClaimReviewStatus.PARTIALLY_VERIFIED: 4,
        ClaimReviewStatus.INCORRECT: 2,
        ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE: 1,
        ClaimReviewStatus.POTENTIALLY_INFERRED: 1,
    },
    "component-datasheet": {
        ClaimReviewStatus.VERIFIED: 10,
        ClaimReviewStatus.PARTIALLY_VERIFIED: 3,
        ClaimReviewStatus.INCORRECT: 2,
        ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE: 1,
        ClaimReviewStatus.POTENTIALLY_INFERRED: 2,
    },
    "insurance-acord": {
        ClaimReviewStatus.VERIFIED: 5,
        ClaimReviewStatus.PARTIALLY_VERIFIED: 4,
        ClaimReviewStatus.INCORRECT: 2,
        ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE: 1,
        ClaimReviewStatus.POTENTIALLY_INFERRED: 1,
    },
    "ny-timetable": {
        ClaimReviewStatus.VERIFIED: 5,
        ClaimReviewStatus.PARTIALLY_VERIFIED: 2,
        ClaimReviewStatus.INCORRECT: 2,
        ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE: 1,
    },
}
EXPECTED_EVIDENCE_COUNTS = {
    TruthClass.VISIBLE_TEXT: 36,
    TruthClass.INFERRED: 18,
    TruthClass.NATIVE_DATA: 16,
    TruthClass.UNKNOWABLE: 5,
    TruthClass.EMBEDDED_DATA: 1,
}
EXPECTED_CLAIM_TYPE_COUNTS = {
    ClaimType.TEXT: 21,
    ClaimType.TABLE: 12,
    ClaimType.PAGE_IDENTITY: 9,
    ClaimType.METADATA: 9,
    ClaimType.STRUCTURE: 5,
    ClaimType.GEOMETRY: 5,
    ClaimType.IMAGE: 4,
    ClaimType.DIAGRAM: 3,
    ClaimType.CHART: 2,
    ClaimType.FORM: 2,
    ClaimType.RELATIONSHIP: 1,
    ClaimType.LINK: 1,
    ClaimType.TEXT_STYLE: 1,
    ClaimType.ARTIFACT_INVENTORY: 1,
}
EXPECTED_CASE_MASK_COUNTS = {
    "clean-energy": (8, 12),
    "clinical-study": (11, 17),
    "component-datasheet": (7, 13),
    "insurance-acord": (5, 9),
    "ny-timetable": (5, 7),
}
EXPECTED_LOCATOR_PAGE_COUNTS = {
    ("clean-energy", 1): 14,
    ("clinical-study", 1): 10,
    ("clinical-study", 2): 10,
    ("clinical-study", 3): 9,
    ("clinical-study", 4): 11,
    ("component-datasheet", 1): 11,
    ("component-datasheet", 2): 11,
    ("component-datasheet", 3): 10,
    ("insurance-acord", 1): 13,
    ("ny-timetable", 1): 7,
    ("ny-timetable", 2): 8,
    ("ny-timetable", 3): 7,
}
PINNED_SEMANTIC_SHA256 = (
    "9afe6c098adcd32e3a8370af5ecb2b27ac4730f098e39128e787eef991990d0f"
)
PINNED_EVIDENCE_FILE_SHA256 = (
    "7e4728c1c5d76a6453d42c640de8a25c24989ed3a160cac2fe4640b22a55814e"
)
PINNED_BATCH_A_SEMANTIC_SHA256 = (
    "f6f0ef58f4cb1379f808e8d5bb7253f260a8f643a83e98e75e4d2e1a3fff01ee"
)
PINNED_BATCH_A_FILE_SHA256 = (
    "f987d84ca1b0d08dfd304d7ea3164a78366643f4b42ef03bc4975d4d09548de4"
)


@pytest.fixture(scope="module")
def registry() -> PortableCorpusRegistry:
    return load_corpus_registry(REGISTRY_PATH)


@pytest.fixture(scope="module")
def batch(registry: PortableCorpusRegistry) -> ReviewBatch:
    return load_reviewed_claim_batch_b(EVIDENCE_PATH, WORKSPACE, registry)


def _split_source_row(line: str) -> tuple[str, ...]:
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


def test_all_five_batch_b_triplets_have_approved_custody(
    registry: PortableCorpusRegistry,
) -> None:
    assert registry.custody.decision == "public-redistributable"
    assert registry.custody.no_exceptions is True
    assert registry.custody.derived_annotations_covered is True

    cases = [registry.case_by_id(case_id) for case_id in BATCH_B_CASE_CLAIM_COUNTS]
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


def test_exactly_76_rows_map_one_to_one_across_four_and_five_column_tables(
    batch: ReviewBatch,
    registry: PortableCorpusRegistry,
) -> None:
    assert batch.claim_count == len(batch.claims) == BATCH_B_CLAIM_COUNT
    assert batch.case_claim_counts == BATCH_B_CASE_CLAIM_COUNTS

    for case_id, expected_count in BATCH_B_CASE_CLAIM_COUNTS.items():
        case = registry.case_by_id(case_id)
        review_path = WORKSPACE / case.review_path
        source_rows = _source_table_rows(review_path)
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
    assert TruthClass.MEASURED not in {
        claim.evidence_class for claim in batch.claims
    }

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
    ) == 36
    assert sum(
        claim.inclusion_mask.semantic_parity for claim in batch.claims
    ) == 58

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


def test_uncalibrated_chart_values_remain_inferred_without_derivations(
    batch: ReviewBatch,
) -> None:
    exact_values = batch.claims[
        [claim.claim_id for claim in batch.claims].index(
            "p00-us07:clean-energy:expert-row-07"
        )
    ]
    assert exact_values.review_status is ClaimReviewStatus.POTENTIALLY_INFERRED
    assert exact_values.evidence_class is TruthClass.INFERRED
    assert exact_values.inclusion_mask.literal_parity is False
    assert exact_values.inclusion_mask.semantic_parity is False
    assert all(claim.derivation is None for claim in batch.claims)


def test_all_121_locators_reconcile_with_registered_page_maps(
    batch: ReviewBatch,
    registry: PortableCorpusRegistry,
) -> None:
    assert validate_review_batch_against_registry(batch, registry) is batch
    locators = [
        locator
        for claim in batch.claims
        for locator in claim.locators
    ]
    assert len(locators) == 121
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
        if claim.case_id == "insurance-acord"
        for locator in claim.locators
    } == {None}


def test_batch_b_reloads_to_one_canonical_identity(
    batch: ReviewBatch,
    registry: PortableCorpusRegistry,
) -> None:
    first = build_reviewed_claim_batch_b(WORKSPACE, registry)
    second = build_reviewed_claim_batch_b(WORKSPACE, registry)
    canonical = canonical_review_batch_json(batch)

    assert batch == first == second
    assert canonical == canonical_review_batch_json(first)
    assert review_batch_sha256(batch) == PINNED_SEMANTIC_SHA256
    assert hashlib.sha256((canonical + "\n").encode("utf-8")).hexdigest() == (
        PINNED_EVIDENCE_FILE_SHA256
    )
    assert EVIDENCE_PATH.read_text(encoding="utf-8") == canonical + "\n"


def test_batch_a_remains_byte_and_semantically_stable(
    batch: ReviewBatch,
    registry: PortableCorpusRegistry,
) -> None:
    batch_a = load_reviewed_claim_batch_a(
        BATCH_A_PATH,
        WORKSPACE,
        registry,
    )
    assert sha256_file(BATCH_A_PATH) == PINNED_BATCH_A_FILE_SHA256
    assert review_batch_sha256(batch_a) == PINNED_BATCH_A_SEMANTIC_SHA256
    assert {
        claim.case_id for claim in batch_a.claims
    }.isdisjoint(BATCH_B_CASE_CLAIM_COUNTS)
    assert len({
        claim.claim_id for claim in (*batch_a.claims, *batch.claims)
    }) == 147


def test_persisted_batch_b_claim_drift_fails_closed(
    batch: ReviewBatch,
    registry: PortableCorpusRegistry,
    tmp_path: Path,
) -> None:
    payload = json.loads(canonical_review_batch_json(batch))
    payload["claims"][0]["claim"] += " Drift."
    drifted_path = tmp_path / "drifted-batch-b.json"
    drifted_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    with pytest.raises(
        ReviewRegistryError,
        match="does not match frozen review rows and policies",
    ):
        load_reviewed_claim_batch_b(
            drifted_path,
            WORKSPACE,
            registry,
        )


def test_frozen_batch_b_review_drift_fails_before_construction(
    registry: PortableCorpusRegistry,
    tmp_path: Path,
) -> None:
    for case_id in BATCH_B_CASE_CLAIM_COUNTS:
        case = registry.case_by_id(case_id)
        source = WORKSPACE / case.review_path
        target = tmp_path / case.review_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())

    clean_energy = tmp_path / registry.case_by_id("clean-energy").review_path
    clean_energy.write_bytes(clean_energy.read_bytes() + b" ")

    with pytest.raises(
        ReviewRegistryError,
        match="clean-energy review SHA-256 changed",
    ):
        build_reviewed_claim_batch_b(tmp_path, registry)
