"""P00-US05 tests for reviewed-claim and inclusion-mask contracts."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from tests.benchmarks.contracts import CONTRACT_VERSION, TruthClass
from tests.benchmarks.corpus_registry import (
    PortableCorpusRegistry,
    load_corpus_registry,
)
from tests.benchmarks.reviewed_claims import (
    CATASTROPHE_TRUTH_SHA256,
    DISPLAY_PAGE_COORDINATES,
    ClaimReviewStatus,
    ClaimType,
    CoordinateConvention,
    Derivation,
    InclusionMask,
    RegionScope,
    ReviewBatch,
    ReviewProvenance,
    ReviewRegistryError,
    ReviewedClaimRecord,
    ReviewerVersion,
    SourceLocator,
    canonical_review_batch_json,
    corpus_registry_sha256,
    load_review_batch,
    project_catastrophe_truth,
    review_batch_sha256,
    validate_review_batch_against_registry,
)
from tests.benchmarks.source_truth import BBox, load_catastrophe_source_truth


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
SYNTHETIC_REVIEW_HASH = "a" * 64


@pytest.fixture(scope="module")
def registry() -> PortableCorpusRegistry:
    return load_corpus_registry(REGISTRY_PATH)


def _locator(
    *,
    case_id: str = "catastrophe-recap",
    physical_page: int = 1,
    printed_page: str | None = "7",
    region_id: str = "synthetic:region",
    bbox: tuple[float, float, float, float] | None = (10, 20, 30, 40),
    scope: RegionScope = RegionScope.SOURCE_REGION,
    coordinates: CoordinateConvention = DISPLAY_PAGE_COORDINATES,
) -> SourceLocator:
    return SourceLocator(
        case_id=case_id,
        physical_page=physical_page,
        printed_page=printed_page,
        region_id=region_id,
        region_scope=scope,
        bbox=BBox(bbox) if bbox is not None else None,
        coordinates=coordinates,
    )


def _claim(
    claim_id: str,
    *,
    evidence_class: TruthClass = TruthClass.VISIBLE_TEXT,
    review_status: ClaimReviewStatus = ClaimReviewStatus.VERIFIED,
    literal: bool = True,
    semantic: bool = True,
    derivation: Derivation | None = None,
    claim_type: ClaimType = ClaimType.TEXT,
    case_id: str = "catastrophe-recap",
    locators: tuple[SourceLocator, ...] | None = None,
) -> ReviewedClaimRecord:
    return ReviewedClaimRecord(
        schema_version=CONTRACT_VERSION,
        claim_id=claim_id,
        case_id=case_id,
        claim_type=claim_type,
        claim=f"Synthetic reviewed assertion for {claim_id}.",
        evidence_class=evidence_class,
        review_status=review_status,
        reviewer=ReviewerVersion(
            reviewer_id="Synthetic source reviewer",
            review_version="p00-us05-synthetic-v1",
        ),
        provenance=ReviewProvenance(
            review_path="tests/fixtures/benchmarks/p00-us05-synthetic.md",
            review_sha256=SYNTHETIC_REVIEW_HASH,
            review_row_id=f"row:{claim_id}",
        ),
        locators=locators or (_locator(case_id=case_id),),
        inclusion_mask=InclusionMask(
            literal_parity=literal,
            semantic_parity=semantic,
        ),
        derivation=derivation,
    )


def _batch(
    claims: tuple[ReviewedClaimRecord, ...],
    registry: PortableCorpusRegistry,
) -> ReviewBatch:
    ordered = tuple(sorted(claims, key=lambda claim: claim.claim_id))
    counts = dict(sorted(Counter(claim.case_id for claim in ordered).items()))
    return ReviewBatch(
        schema_version=CONTRACT_VERSION,
        batch_id="p00-us05-synthetic-positive",
        corpus_registry_sha256=corpus_registry_sha256(registry),
        claim_count=len(ordered),
        case_claim_counts=counts,
        claims=ordered,
    )


def _payload(claim: ReviewedClaimRecord) -> dict[str, Any]:
    return deepcopy(claim.model_dump(mode="json"))


def test_positive_synthetic_contracts_cover_review_and_evidence_states(
    registry: PortableCorpusRegistry,
) -> None:
    claims = (
        _claim("claim:01:literal"),
        _claim(
            "claim:02:measured",
            evidence_class=TruthClass.MEASURED,
            literal=False,
            semantic=True,
            derivation=Derivation(
                method="PDF vector mark calibrated to printed axis ticks",
                tolerance=0.5,
                tolerance_unit="percent",
            ),
            claim_type=ClaimType.CHART,
        ),
        _claim(
            "claim:03:partial",
            review_status=ClaimReviewStatus.PARTIALLY_VERIFIED,
            literal=False,
            semantic=True,
            claim_type=ClaimType.STRUCTURE,
        ),
        _claim(
            "claim:04:incorrect",
            review_status=ClaimReviewStatus.INCORRECT,
            literal=False,
            semantic=False,
            claim_type=ClaimType.TABLE,
        ),
        _claim(
            "claim:05:inferred",
            evidence_class=TruthClass.INFERRED,
            review_status=ClaimReviewStatus.POTENTIALLY_INFERRED,
            literal=False,
            semantic=False,
            claim_type=ClaimType.RELATIONSHIP,
        ),
        _claim(
            "claim:06:unverifiable",
            evidence_class=TruthClass.UNKNOWABLE,
            review_status=(
                ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE
            ),
            literal=False,
            semantic=False,
            claim_type=ClaimType.METADATA,
        ),
    )
    batch = _batch(claims, registry)

    assert validate_review_batch_against_registry(batch, registry) is batch
    assert batch.claim_count == 6
    assert batch.case_claim_counts == {"catastrophe-recap": 6}
    assert {
        claim.review_status for claim in batch.claims
    } == set(ClaimReviewStatus)
    assert {
        claim.evidence_class for claim in batch.claims
    } == {
        TruthClass.VISIBLE_TEXT,
        TruthClass.MEASURED,
        TruthClass.INFERRED,
        TruthClass.UNKNOWABLE,
    }
    assert sum(claim.inclusion_mask.literal_parity for claim in batch.claims) == 1
    assert sum(claim.inclusion_mask.semantic_parity for claim in batch.claims) == 3


def test_review_batch_round_trips_with_one_stable_canonical_identity(
    registry: PortableCorpusRegistry,
    tmp_path: Path,
) -> None:
    batch = _batch(
        (
            _claim("claim:01:literal"),
            _claim(
                "claim:02:native",
                evidence_class=TruthClass.NATIVE_DATA,
            ),
        ),
        registry,
    )
    canonical = canonical_review_batch_json(batch)
    path = tmp_path / "batch.json"
    path.write_text(canonical + "\n", encoding="utf-8")

    reloaded = load_review_batch(path)
    assert reloaded == batch
    assert canonical_review_batch_json(reloaded) == canonical
    assert review_batch_sha256(reloaded) == hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()
    assert json.loads(canonical)["claims"][0]["claim_id"] == "claim:01:literal"


def test_a_claim_can_locate_multiple_registered_pages(
    registry: PortableCorpusRegistry,
) -> None:
    timetable = registry.case_by_id("ny-timetable")
    locators = tuple(
        _locator(
            case_id=timetable.case_id,
            physical_page=page.physical_page,
            printed_page=page.printed_page,
            region_id=f"page:{page.physical_page}:table",
            bbox=(0, 0, page.width_pt, page.height_pt),
            scope=RegionScope.PAGE,
        )
        for page in timetable.pages
    )
    claim = _claim(
        "claim:multi-page",
        case_id=timetable.case_id,
        locators=locators,
        literal=False,
        semantic=True,
        claim_type=ClaimType.TABLE,
    )
    batch = _batch((claim,), registry)

    assert len(claim.locators) == 3
    assert validate_review_batch_against_registry(batch, registry) is batch


def test_every_registry_page_and_explicit_null_printed_label_are_valid(
    registry: PortableCorpusRegistry,
) -> None:
    claims = []
    sequence = 0
    for case in registry.cases:
        for page in case.pages:
            sequence += 1
            claims.append(
                _claim(
                    f"page-claim:{sequence:02d}",
                    case_id=case.case_id,
                    locators=(
                        _locator(
                            case_id=case.case_id,
                            physical_page=page.physical_page,
                            printed_page=page.printed_page,
                            region_id=f"page:{page.physical_page}",
                            bbox=(0, 0, page.width_pt, page.height_pt),
                            scope=RegionScope.PAGE,
                        ),
                    ),
                    literal=False,
                    semantic=True,
                    claim_type=ClaimType.PAGE_IDENTITY,
                )
            )
    batch = _batch(tuple(claims), registry)

    validate_review_batch_against_registry(batch, registry)
    assert batch.claim_count == 30
    assert sum(
        locator.printed_page is None
        for claim in batch.claims
        for locator in claim.locators
    ) == 2
    esg = next(claim for claim in batch.claims if claim.case_id == "esg-metrics")
    assert esg.locators[0].bbox == BBox((0, 0, 792.0, 612.0))
    assert esg.locators[0].coordinates.page_space == (
        "displayed_after_source_rotation"
    )


@pytest.mark.parametrize(
    "evidence_class",
    [TruthClass.MEASURED, TruthClass.INFERRED, TruthClass.UNKNOWABLE],
)
def test_nonliteral_evidence_cannot_enter_literal_parity(
    evidence_class: TruthClass,
) -> None:
    payload = _payload(_claim("claim:valid"))
    payload["evidence_class"] = evidence_class.value
    if evidence_class is TruthClass.MEASURED:
        payload["derivation"] = {
            "method": "synthetic measurement",
            "tolerance": 1,
            "tolerance_unit": "pt",
        }

    with pytest.raises(ValidationError, match="cannot enter literal parity"):
        ReviewedClaimRecord.model_validate(payload)


@pytest.mark.parametrize(
    "review_status",
    [
        ClaimReviewStatus.PARTIALLY_VERIFIED,
        ClaimReviewStatus.INCORRECT,
        ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE,
        ClaimReviewStatus.POTENTIALLY_INFERRED,
    ],
)
def test_only_fully_verified_claims_can_enter_literal_parity(
    review_status: ClaimReviewStatus,
) -> None:
    payload = _payload(_claim("claim:valid"))
    payload["review_status"] = review_status.value

    with pytest.raises(ValidationError, match="requires review_status=verified"):
        ReviewedClaimRecord.model_validate(payload)


@pytest.mark.parametrize(
    "review_status",
    [
        ClaimReviewStatus.INCORRECT,
        ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE,
        ClaimReviewStatus.POTENTIALLY_INFERRED,
    ],
)
def test_unsupported_review_verdicts_cannot_enter_semantic_parity(
    review_status: ClaimReviewStatus,
) -> None:
    payload = _payload(
        _claim(
            "claim:valid",
            literal=False,
            semantic=True,
        )
    )
    payload["review_status"] = review_status.value

    with pytest.raises(ValidationError, match="cannot enter parity denominators"):
        ReviewedClaimRecord.model_validate(payload)


def test_literal_inclusion_requires_semantic_inclusion() -> None:
    with pytest.raises(
        ValidationError,
        match="literal parity inclusion requires semantic inclusion",
    ):
        InclusionMask(literal_parity=True, semantic_parity=False)


def test_measured_evidence_requires_complete_finite_derivation() -> None:
    payload = _payload(
        _claim(
            "claim:measured",
            evidence_class=TruthClass.MEASURED,
            literal=False,
            semantic=True,
            derivation=Derivation(
                method="synthetic vector calibration",
                tolerance=1,
                tolerance_unit="pt",
            ),
        )
    )
    payload["derivation"] = None
    with pytest.raises(ValidationError, match="requires derivation method"):
        ReviewedClaimRecord.model_validate(payload)

    for tolerance in (-1, float("inf"), float("nan")):
        invalid = deepcopy(payload)
        invalid["derivation"] = {
            "method": "synthetic vector calibration",
            "tolerance": tolerance,
            "tolerance_unit": "pt",
        }
        with pytest.raises(ValidationError):
            ReviewedClaimRecord.model_validate(invalid)

    nonmeasured = _payload(_claim("claim:literal"))
    nonmeasured["derivation"] = {
        "method": "not applicable",
        "tolerance": 0,
        "tolerance_unit": "pt",
    }
    with pytest.raises(ValidationError, match="only valid"):
        ReviewedClaimRecord.model_validate(nonmeasured)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("claim_type", "invented"),
        ("evidence_class", "contradicted"),
        ("review_status", "approved"),
    ],
)
def test_unknown_contract_vocabularies_fail_closed(
    field: str,
    value: str,
) -> None:
    payload = _payload(_claim("claim:valid"))
    payload[field] = value

    with pytest.raises(ValidationError, match="Input should be"):
        ReviewedClaimRecord.model_validate(payload)


def test_missing_or_ambiguous_reviewer_and_provenance_are_rejected() -> None:
    payload = _payload(_claim("claim:valid"))
    payload["reviewer"].pop("reviewer_id")
    with pytest.raises(ValidationError, match="Field required"):
        ReviewedClaimRecord.model_validate(payload)

    for value in ("", " ", " reviewer", "reviewer "):
        invalid = _payload(_claim("claim:valid"))
        invalid["reviewer"]["reviewer_id"] = value
        with pytest.raises(ValidationError):
            ReviewedClaimRecord.model_validate(invalid)

    invalid_path = _payload(_claim("claim:valid"))
    invalid_path["provenance"]["review_path"] = "../private-review.md"
    with pytest.raises(ValidationError, match="canonical workspace-relative"):
        ReviewedClaimRecord.model_validate(invalid_path)


def test_missing_duplicate_and_cross_case_locators_are_rejected() -> None:
    payload = _payload(_claim("claim:valid"))
    payload["locators"] = []
    with pytest.raises(ValidationError, match="at least 1"):
        ReviewedClaimRecord.model_validate(payload)

    duplicate = _payload(_claim("claim:valid"))
    duplicate["locators"].append(deepcopy(duplicate["locators"][0]))
    with pytest.raises(ValidationError, match="locators must be unique"):
        ReviewedClaimRecord.model_validate(duplicate)

    cross_case = _payload(_claim("claim:valid"))
    cross_case["locators"][0]["case_id"] = "clean-energy"
    with pytest.raises(ValidationError, match="claim case_id"):
        ReviewedClaimRecord.model_validate(cross_case)


@pytest.mark.parametrize(
    "bbox",
    [
        (-1, 0, 1, 1),
        (0, -1, 1, 1),
        (0, 0, 0, 1),
        (0, 0, 1, 0),
        (0, 0, float("inf"), 1),
        (0, 0, float("nan"), 1),
    ],
)
def test_impossible_local_region_geometry_is_rejected(
    bbox: tuple[float, float, float, float],
) -> None:
    with pytest.raises(ValidationError):
        _locator(bbox=bbox)


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (
            {"case_id": "missing-case", "locator_case_id": "missing-case"},
            "unregistered case",
        ),
        ({"physical_page": 2}, "unregistered physical page"),
        ({"printed_page": "8"}, "printed page does not match"),
        ({"bbox": (600, 780, 20, 20)}, "bbox lies outside"),
    ],
)
def test_registry_validation_rejects_impossible_cases_pages_and_regions(
    registry: PortableCorpusRegistry,
    mutation: dict[str, object],
    match: str,
) -> None:
    case_id = str(mutation.get("case_id", "catastrophe-recap"))
    locator_case_id = str(mutation.get("locator_case_id", case_id))
    locator = _locator(
        case_id=locator_case_id,
        physical_page=int(mutation.get("physical_page", 1)),
        printed_page=mutation.get("printed_page", "7"),  # type: ignore[arg-type]
        bbox=mutation.get("bbox", (10, 20, 30, 40)),  # type: ignore[arg-type]
    )
    claim = _claim(
        "claim:registry-invalid",
        case_id=case_id,
        locators=(locator,),
        literal=False,
        semantic=True,
    )
    batch = _batch((claim,), registry)

    with pytest.raises(ReviewRegistryError, match=match):
        validate_review_batch_against_registry(batch, registry)


def test_registry_validation_rejects_wrong_coordinate_space_and_hash(
    registry: PortableCorpusRegistry,
) -> None:
    unsupported = CoordinateConvention(
        origin="top_left",
        unit="pt",
        bbox_format="[x,y,width,height]",
        page_space="displayed_after_source_rotation",
    ).model_copy(
        update={"page_space": "raw_source_page"},
    )
    claim = _claim(
        "claim:coordinates",
        locators=(_locator(coordinates=unsupported),),
        literal=False,
        semantic=True,
    )
    batch = _batch((claim,), registry)
    with pytest.raises(ReviewRegistryError, match="coordinate convention"):
        validate_review_batch_against_registry(batch, registry)

    valid_batch = _batch(
        (
            _claim(
                "claim:hash",
                literal=False,
                semantic=True,
            ),
        ),
        registry,
    )
    payload = valid_batch.model_dump(mode="json")
    payload["corpus_registry_sha256"] = "f" * 64
    wrong_hash = ReviewBatch.model_validate(payload)
    with pytest.raises(ReviewRegistryError, match="does not match"):
        validate_review_batch_against_registry(wrong_hash, registry)


def test_batch_rejects_duplicate_ids_rows_counts_and_noncanonical_order(
    registry: PortableCorpusRegistry,
) -> None:
    first = _claim("claim:01")
    second = _claim("claim:02")
    valid = _batch((first, second), registry).model_dump(mode="json")

    duplicate_id = deepcopy(valid)
    duplicate_id["claims"][1]["claim_id"] = duplicate_id["claims"][0]["claim_id"]
    with pytest.raises(ValidationError, match="claim IDs must be unique"):
        ReviewBatch.model_validate(duplicate_id)

    duplicate_row = deepcopy(valid)
    duplicate_row["claims"][1]["provenance"] = deepcopy(
        duplicate_row["claims"][0]["provenance"]
    )
    with pytest.raises(ValidationError, match="row identities must be unique"):
        ReviewBatch.model_validate(duplicate_row)

    wrong_count = deepcopy(valid)
    wrong_count["claim_count"] = 3
    with pytest.raises(ValidationError, match="claim_count must match"):
        ReviewBatch.model_validate(wrong_count)

    wrong_case_count = deepcopy(valid)
    wrong_case_count["case_claim_counts"]["catastrophe-recap"] = 3
    with pytest.raises(ValidationError, match="case_claim_counts must match"):
        ReviewBatch.model_validate(wrong_case_count)

    reversed_claims = deepcopy(valid)
    reversed_claims["claims"].reverse()
    with pytest.raises(ValidationError, match="canonical claim_id order"):
        ReviewBatch.model_validate(reversed_claims)


def test_catastrophe_backward_projection_is_complete_and_lossless(
    registry: PortableCorpusRegistry,
) -> None:
    before = CATASTROPHE_TRUTH_PATH.read_bytes()
    truth = load_catastrophe_source_truth(CATASTROPHE_TRUTH_PATH)
    batch = project_catastrophe_truth(truth, registry)

    assert len(batch.claims) == 163
    assert batch.case_claim_counts == {"catastrophe-recap": 163}
    assert Counter(claim.evidence_class for claim in batch.claims) == {
        TruthClass.VISIBLE_TEXT: 32,
        TruthClass.NATIVE_DATA: 33,
        TruthClass.MEASURED: 89,
        TruthClass.INFERRED: 8,
        TruthClass.UNKNOWABLE: 1,
    }
    assert sum(claim.inclusion_mask.literal_parity for claim in batch.claims) == 62
    assert sum(claim.inclusion_mask.semantic_parity for claim in batch.claims) == 163
    assert sum(claim.derivation is not None for claim in batch.claims) == 89
    assert {
        (claim.reviewer.reviewer_id, claim.reviewer.review_version)
        for claim in batch.claims
    } == {("Codex source review", "P00-US02-1.0")}
    assert all(
        claim.provenance.review_sha256 == CATASTROPHE_TRUTH_SHA256
        for claim in batch.claims
    )
    assert validate_review_batch_against_registry(batch, registry) is batch
    assert hashlib.sha256(CATASTROPHE_TRUTH_PATH.read_bytes()).hexdigest() == (
        CATASTROPHE_TRUTH_SHA256
    )
    assert CATASTROPHE_TRUTH_PATH.read_bytes() == before
