"""Contract gates for the persisted P00-US07 Batch B evidence."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from tests.benchmarks.contracts import CONTRACT_VERSION
from tests.benchmarks.corpus_registry import load_corpus_registry
from tests.benchmarks.reviewed_claim_inventory import (
    BATCH_B_EVIDENCE_PATH,
    load_reviewed_claim_batch_b,
)
from tests.benchmarks.reviewed_claims import (
    ReviewBatch,
    canonical_review_batch_json,
)


WORKSPACE = Path(__file__).resolve().parents[2]
REGISTRY_PATH = (
    WORKSPACE
    / "tracker"
    / "phase-00-baseline"
    / "evidence"
    / "P00-US04-corpus-registry.json"
)
EVIDENCE_PATH = WORKSPACE / BATCH_B_EVIDENCE_PATH


def _payload() -> dict[str, Any]:
    return json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))


def test_batch_b_is_a_strict_versioned_review_batch() -> None:
    payload = _payload()
    batch = ReviewBatch.model_validate(payload)

    assert batch.schema_version == CONTRACT_VERSION
    assert batch.claim_count == len(batch.claims) == 76
    assert all(claim.schema_version == CONTRACT_VERSION for claim in batch.claims)
    assert set(payload) == {
        "batch_id",
        "case_claim_counts",
        "claim_count",
        "claims",
        "corpus_registry_sha256",
        "schema_version",
    }
    assert set(payload["claims"][0]) == {
        "case_id",
        "claim",
        "claim_id",
        "claim_type",
        "derivation",
        "evidence_class",
        "inclusion_mask",
        "locators",
        "provenance",
        "review_status",
        "reviewer",
        "schema_version",
    }


@pytest.mark.parametrize(
    ("path", "invalid"),
    [
        (("claim_count",), 77),
        (("claims", 0, "review_status"), "approved"),
        (("claims", 0, "evidence_class"), "expert_output"),
        (("claims", 0, "locators", 0, "physical_page"), 0),
        (("claims", 6, "inclusion_mask", "literal_parity"), True),
    ],
)
def test_batch_b_rejects_count_classification_locator_and_mask_drift(
    path: tuple[str | int, ...],
    invalid: object,
) -> None:
    payload = deepcopy(_payload())
    target: Any = payload
    for segment in path[:-1]:
        target = target[segment]
    target[path[-1]] = invalid

    with pytest.raises(ValidationError):
        ReviewBatch.model_validate(payload)


def test_batch_b_rejects_unknown_fields() -> None:
    payload = _payload()
    payload["claims"][0]["expert_confidence"] = 1.0

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ReviewBatch.model_validate(payload)


def test_batch_b_load_is_registry_and_source_policy_valid() -> None:
    registry = load_corpus_registry(REGISTRY_PATH)
    batch = load_reviewed_claim_batch_b(
        EVIDENCE_PATH,
        WORKSPACE,
        registry,
    )
    assert ReviewBatch.model_validate_json(
        canonical_review_batch_json(batch)
    ) == batch
