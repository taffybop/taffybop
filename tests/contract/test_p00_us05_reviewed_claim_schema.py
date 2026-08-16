"""Schema and P00-US01 compatibility gates for reviewed-claim contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from pydantic import ValidationError

from tests.benchmarks.contracts import (
    CONTRACT_VERSION,
    Annotation,
    ContractModel,
    TruthClass,
)
from tests.benchmarks.reviewed_claims import (
    DISPLAY_PAGE_COORDINATES,
    ClaimReviewStatus,
    ClaimType,
    CoordinateConvention,
    Derivation,
    InclusionMask,
    RegionScope,
    ReviewBatch,
    ReviewedClaimRecord,
    ReviewerVersion,
    ReviewProvenance,
    SourceLocator,
)


SHA256_PATTERN = "^[0-9a-f]{64}$"
STABLE_ID_PATTERN = "^[a-z0-9]+(?:[a-z0-9._:-]*[a-z0-9])?$"
EXPECTED_SCHEMA_HASHES = {
    "CoordinateConvention": (
        "a6ae91d0d19a9f1620996f3da1d031d4a74e7c9a4e36ff03e333a012a59f8259"
    ),
    "SourceLocator": (
        "a4cf878ad9c80c6b4987aa5d4d154bca29e6773fd407039f90a9f34692aa1f35"
    ),
    "ReviewerVersion": (
        "a99af4e9ed17b8e575d4fbd91025a8e3c6239d12e2fa9aee0d777ef0460a5e4f"
    ),
    "ReviewProvenance": (
        "2757f95e78cd609eb45907ad68f543478dae4aa41ec8aea634474804543c7719"
    ),
    "InclusionMask": (
        "45faf1956e254b07ffac851b8285963b6a069e04c8a191deba5c19f74d05ad17"
    ),
    "Derivation": (
        "33a9576ae0c23f682bac59fe5bdb7784d2de0a83dc084c6f13c859309487682d"
    ),
    "ReviewedClaimRecord": (
        "49c43ce26b4f2cb3b0f602441a1c04f12ecd55ca9731ea9d78f7473ce3f3f8a5"
    ),
    "ReviewBatch": (
        "c3f86ca181cf02fda6c7a395ec3d44d65ac6de8010b1db145588e08b0e5ed346"
    ),
}
P00_US01_ANNOTATION_SCHEMA_HASH = (
    "914e787b8d0475a2ac56278564575cad5b149999f0319b90caf129e283d10268"
)


def _schema_hash(model: type[ContractModel]) -> str:
    canonical = json.dumps(
        model.model_json_schema(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _valid_claim_payload() -> dict[str, Any]:
    return {
        "schema_version": CONTRACT_VERSION,
        "claim_id": "catastrophe-recap:title",
        "case_id": "catastrophe-recap",
        "claim_type": "text",
        "claim": "The source contains the visible title.",
        "evidence_class": "visible_text",
        "review_status": "verified",
        "reviewer": {
            "reviewer_id": "source-review",
            "review_version": "2026-07-29",
        },
        "provenance": {
            "review_path": (
                "tracker/phase-00-baseline/evidence/"
                "P00-US05-reviewed-claim-contracts.md"
            ),
            "review_sha256": "0" * 64,
            "review_row_id": "catastrophe-recap:title",
        },
        "locators": [
            {
                "case_id": "catastrophe-recap",
                "physical_page": 1,
                "printed_page": "1",
                "region_id": "title",
                "region_scope": "source_object",
                "bbox": [20.0, 30.0, 200.0, 24.0],
                "coordinates": DISPLAY_PAGE_COORDINATES.model_dump(mode="json"),
            }
        ],
        "inclusion_mask": {
            "literal_parity": True,
            "semantic_parity": True,
        },
    }


def test_reviewed_claim_schemas_are_strict_versioned_and_hash_pinned() -> None:
    models = (
        CoordinateConvention,
        SourceLocator,
        ReviewerVersion,
        ReviewProvenance,
        InclusionMask,
        Derivation,
        ReviewedClaimRecord,
        ReviewBatch,
    )

    assert {model.__name__: _schema_hash(model) for model in models} == (
        EXPECTED_SCHEMA_HASHES
    )
    for model in models:
        assert model.model_json_schema()["additionalProperties"] is False

    for model in (ReviewedClaimRecord, ReviewBatch):
        schema = model.model_json_schema()
        assert schema["properties"]["schema_version"]["const"] == CONTRACT_VERSION
        assert "schema_version" in schema["required"]


def test_reviewed_claim_schema_closes_all_classification_enums() -> None:
    defs = ReviewedClaimRecord.model_json_schema()["$defs"]

    assert defs["ClaimType"]["enum"] == [member.value for member in ClaimType]
    assert defs["ClaimReviewStatus"]["enum"] == [
        member.value for member in ClaimReviewStatus
    ]
    assert defs["RegionScope"]["enum"] == [
        member.value for member in RegionScope
    ]
    assert defs["TruthClass"]["enum"] == [
        member.value for member in TruthClass
    ]


@pytest.mark.parametrize(
    ("path", "invalid"),
    [
        (("claim_type",), "unknown"),
        (("evidence_class",), "opinion"),
        (("review_status",), "pending"),
        (("locators", 0, "region_scope"), "document"),
    ],
)
def test_unknown_classification_enum_values_are_rejected(
    path: tuple[str | int, ...],
    invalid: str,
) -> None:
    payload = _valid_claim_payload()
    target: Any = payload
    for segment in path[:-1]:
        target = target[segment]
    target[path[-1]] = invalid

    with pytest.raises(ValidationError):
        ReviewedClaimRecord.model_validate(payload)


def test_reviewed_claim_schema_requires_complete_nested_identity_and_masks() -> None:
    schema = ReviewedClaimRecord.model_json_schema()
    defs = schema["$defs"]

    assert schema["required"] == [
        "schema_version",
        "claim_id",
        "case_id",
        "claim_type",
        "claim",
        "evidence_class",
        "review_status",
        "reviewer",
        "provenance",
        "locators",
        "inclusion_mask",
    ]
    assert defs["ReviewerVersion"]["required"] == [
        "reviewer_id",
        "review_version",
    ]
    assert defs["ReviewProvenance"]["required"] == [
        "review_path",
        "review_sha256",
        "review_row_id",
    ]
    assert defs["SourceLocator"]["required"] == [
        "case_id",
        "physical_page",
        "printed_page",
        "region_id",
        "region_scope",
        "bbox",
        "coordinates",
    ]
    assert defs["CoordinateConvention"]["required"] == [
        "origin",
        "unit",
        "bbox_format",
        "page_space",
    ]
    assert defs["InclusionMask"]["required"] == [
        "literal_parity",
        "semantic_parity",
    ]
    assert defs["Derivation"]["required"] == [
        "method",
        "tolerance",
        "tolerance_unit",
    ]
    assert all(
        definition["additionalProperties"] is False
        for definition in (
            defs["ReviewerVersion"],
            defs["ReviewProvenance"],
            defs["SourceLocator"],
            defs["CoordinateConvention"],
            defs["InclusionMask"],
            defs["Derivation"],
        )
    )


def test_schema_exposes_machine_checkable_locator_derivation_and_batch_constraints(
) -> None:
    claim_schema = ReviewedClaimRecord.model_json_schema()
    defs = claim_schema["$defs"]
    locator = defs["SourceLocator"]
    coordinates = defs["CoordinateConvention"]
    derivation = defs["Derivation"]

    assert claim_schema["properties"]["claim_id"]["pattern"] == STABLE_ID_PATTERN
    assert claim_schema["properties"]["case_id"]["pattern"] == STABLE_ID_PATTERN
    assert claim_schema["properties"]["claim"]["minLength"] == 1
    assert claim_schema["properties"]["locators"]["minItems"] == 1
    assert locator["properties"]["physical_page"]["minimum"] == 1
    assert locator["properties"]["region_id"]["pattern"] == STABLE_ID_PATTERN
    assert {"type": "null"} in locator["properties"]["printed_page"]["anyOf"]
    assert defs["BBox"]["minItems"] == 4
    assert defs["BBox"]["maxItems"] == 4
    assert coordinates["properties"]["origin"]["const"] == "top_left"
    assert coordinates["properties"]["unit"]["const"] == "pt"
    assert (
        coordinates["properties"]["bbox_format"]["const"]
        == "[x,y,width,height]"
    )
    assert (
        coordinates["properties"]["page_space"]["const"]
        == "displayed_after_source_rotation"
    )
    assert derivation["properties"]["method"]["minLength"] == 1
    assert derivation["properties"]["tolerance"]["minimum"] == 0
    assert derivation["properties"]["tolerance_unit"]["minLength"] == 1
    assert (
        defs["ReviewProvenance"]["properties"]["review_sha256"]["pattern"]
        == SHA256_PATTERN
    )

    batch = ReviewBatch.model_json_schema()
    assert batch["required"] == [
        "schema_version",
        "batch_id",
        "corpus_registry_sha256",
        "claim_count",
        "case_claim_counts",
        "claims",
    ]
    assert batch["properties"]["batch_id"]["pattern"] == STABLE_ID_PATTERN
    assert (
        batch["properties"]["corpus_registry_sha256"]["pattern"]
        == SHA256_PATTERN
    )
    assert batch["properties"]["claim_count"]["exclusiveMinimum"] == 0
    assert batch["properties"]["case_claim_counts"]["minProperties"] == 1
    assert (
        batch["properties"]["case_claim_counts"]["patternProperties"][
            STABLE_ID_PATTERN
        ]["type"]
        == "integer"
    )
    assert batch["properties"]["claims"]["minItems"] == 1


def test_p00_us01_annotation_schema_and_reviewed_claim_projection_are_unchanged(
) -> None:
    schema = Annotation.model_json_schema()
    assert _schema_hash(Annotation) == P00_US01_ANNOTATION_SCHEMA_HASH
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["const"] == CONTRACT_VERSION
    assert schema["required"] == [
        "schema_version",
        "annotation_id",
        "fixture_id",
        "truth_class",
        "claim",
    ]
    assert set(
        schema["allOf"][0]["then"]["properties"]["truth_class"]["enum"]
    ) == {"visible_text", "native_data", "embedded_data"}

    reviewed = ReviewedClaimRecord.model_validate(_valid_claim_payload())
    projected = reviewed.annotation_contract()

    assert type(projected) is Annotation
    assert projected.model_dump(mode="json") == {
        "schema_version": CONTRACT_VERSION,
        "annotation_id": "catastrophe-recap:title",
        "fixture_id": "catastrophe-recap",
        "truth_class": "visible_text",
        "claim": "The source contains the visible title.",
        "include_in_exact_parity": True,
    }
