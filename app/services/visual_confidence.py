"""Conservative Phase 08 confidence decisions for visual observations.

This module deliberately does not fit, infer, or expose probabilities.  It
translates the existing Phase 05 validators and Phase 06 grounding result into
bounded qualitative dimensions.  Model-reported confidence values are never
read, so a model cannot promote its own unsupported claim.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.visual_contracts import VisualStructure
from app.services.visual_model_grounding import (
    GroundedObservation,
    VisualModelGroundingEnvelope,
)


_POLICY_VERSION = "p08-visual-confidence-deterministic-v1"
_POLICY_BASIS = "deterministic_validator_outcomes_not_statistical_probability"
_MAX_PUBLIC_ASSESSMENT_BYTES = 131_072

DimensionOutcome = Literal["supported", "withheld", "not_applicable"]
DimensionReason = Literal[
    "phase05_structure_validated",
    "phase05_structure_unavailable",
    "phase05_chart_value_validated",
    "phase05_chart_value_rejected",
    "phase05_relationship_validated",
    "phase05_relationship_rejected",
    "phase06_observation_grounded",
    "phase06_observation_rejected",
    "dimension_not_claimed",
]
EvidenceIdentifier = Annotated[
    str,
    Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"),
]

_SUPPORTED_REASONS = frozenset(
    {
        "phase05_structure_validated",
        "phase05_chart_value_validated",
        "phase05_relationship_validated",
        "phase06_observation_grounded",
    }
)
_WITHHELD_REASONS = frozenset(
    {
        "phase05_structure_unavailable",
        "phase05_chart_value_rejected",
        "phase05_relationship_rejected",
        "phase06_observation_rejected",
    }
)


class _ConfidenceContract(BaseModel):
    """Closed, immutable, non-coercing confidence contract."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    @model_validator(mode="before")
    @classmethod
    def require_exact_object(cls, value: Any) -> Any:
        if type(value) is cls:
            return value
        if type(value) is not dict:
            raise ValueError("visual confidence values must be exact objects")
        return value


class VisualConfidenceDimension(_ConfidenceContract):
    """One qualitative validator result, never a probability estimate."""

    outcome: DimensionOutcome
    reason: DimensionReason
    evidence_ids: list[EvidenceIdentifier] = Field(
        default_factory=list,
        max_length=64,
    )

    @model_validator(mode="after")
    def validate_dimension(self) -> "VisualConfidenceDimension":
        if self.evidence_ids != sorted(self.evidence_ids) or len(
            self.evidence_ids
        ) != len(set(self.evidence_ids)):
            raise ValueError("visual confidence evidence must be sorted and unique")
        if self.outcome == "not_applicable":
            if self.reason != "dimension_not_claimed" or self.evidence_ids:
                raise ValueError("non-applicable dimension carries a claim")
        elif self.outcome == "supported" and self.reason not in _SUPPORTED_REASONS:
            raise ValueError("supported dimension lacks a support reason")
        elif self.outcome == "withheld" and self.reason not in _WITHHELD_REASONS:
            raise ValueError("withheld dimension lacks a refusal reason")
        return self


class VisualConfidenceDimensions(_ConfidenceContract):
    """Independent release-first visual confidence dimensions."""

    structure: VisualConfidenceDimension
    value: VisualConfidenceDimension
    relationship: VisualConfidenceDimension
    model_observation: VisualConfidenceDimension


class VisualClaimConfidence(_ConfidenceContract):
    observation_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    observation_type: Literal[
        "generated_description",
        "visual_identification",
        "derived_measurement",
        "inferred_relationship",
    ]
    decision: Literal["accept", "withhold"]
    dimensions: VisualConfidenceDimensions

    @model_validator(mode="after")
    def validate_decision(self) -> "VisualClaimConfidence":
        model_supported = (
            self.dimensions.model_observation.outcome == "supported"
        )
        if (self.decision == "accept") != model_supported:
            raise ValueError("claim decision differs from grounding dimension")
        if self.decision == "accept" and any(
            dimension.outcome == "withheld"
            for dimension in (
                self.dimensions.structure,
                self.dimensions.value,
                self.dimensions.relationship,
            )
        ):
            raise ValueError("accepted claim contains a withheld dimension")
        return self


class VisualConfidenceAssessment(_ConfidenceContract):
    """Bounded assessment used before any Phase 06 observation can merge."""

    schema_version: Literal["1.0"]
    policy_version: Literal["p08-visual-confidence-deterministic-v1"]
    policy_basis: Literal[
        "deterministic_validator_outcomes_not_statistical_probability"
    ]
    public_item_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
    )
    decision: Literal["accept", "withhold", "fallback"]
    reason: Literal[
        "all_claims_grounded",
        "grounding_rejected",
        "no_observations",
    ]
    claims: list[VisualClaimConfidence] = Field(default_factory=list, max_length=256)

    @model_validator(mode="after")
    def validate_assessment(self) -> "VisualConfidenceAssessment":
        identifiers = [claim.observation_id for claim in self.claims]
        if identifiers != sorted(identifiers) or len(identifiers) != len(
            set(identifiers)
        ):
            raise ValueError("visual confidence claims must be sorted and unique")
        accepted = bool(self.claims) and all(
            claim.decision == "accept" for claim in self.claims
        )
        withheld = bool(self.claims) and any(
            claim.decision == "withhold" for claim in self.claims
        )
        expected = "accept" if accepted else "withhold" if withheld else "fallback"
        if self.decision != expected:
            raise ValueError("visual confidence assessment decision differs")
        expected_reason = {
            "accept": "all_claims_grounded",
            "withhold": "grounding_rejected",
            "fallback": "no_observations",
        }[self.decision]
        if self.reason != expected_reason:
            raise ValueError("visual confidence assessment reason differs")
        return self


def _structure(item: Mapping[str, Any]) -> VisualStructure | None:
    raw = item.get("visual_structure")
    dump = getattr(raw, "model_dump", None)
    if callable(dump):
        raw = dump(mode="json", exclude_none=True)
    if not isinstance(raw, Mapping):
        return None
    try:
        structure = VisualStructure.model_validate(dict(raw), strict=True)
    except (MemoryError, TypeError, ValueError, OverflowError):
        return None
    if (
        structure.region.kind != str(item.get("type") or "").casefold()
        or not structure.region.evidence_ids
    ):
        return None
    return structure


def _dimension(
    outcome: DimensionOutcome,
    reason: DimensionReason,
    evidence_ids: list[str] | tuple[str, ...] = (),
) -> VisualConfidenceDimension:
    return VisualConfidenceDimension(
        outcome=outcome,
        reason=reason,
        evidence_ids=sorted(set(evidence_ids)),
    )


def _claim(
    grounded: GroundedObservation,
    *,
    structure: VisualStructure | None,
    transaction_accepted: bool,
) -> VisualClaimConfidence:
    observation = grounded.observation
    accepted = transaction_accepted and grounded.status == "accepted"
    evidence_ids = list(observation.evidence_ids)
    structure_applicable = observation.observation_type != "generated_description"
    if structure_applicable and structure is not None:
        structure_dimension = _dimension(
            "supported",
            "phase05_structure_validated",
            structure.region.evidence_ids,
        )
    elif structure_applicable:
        structure_dimension = _dimension(
            "withheld",
            "phase05_structure_unavailable",
            evidence_ids,
        )
    else:
        structure_dimension = _dimension(
            "not_applicable",
            "dimension_not_claimed",
        )

    if observation.observation_type == "derived_measurement":
        value_dimension = _dimension(
            "supported" if accepted else "withheld",
            (
                "phase05_chart_value_validated"
                if accepted
                else "phase05_chart_value_rejected"
            ),
            evidence_ids,
        )
    else:
        value_dimension = _dimension(
            "not_applicable",
            "dimension_not_claimed",
        )

    if observation.observation_type == "inferred_relationship":
        relationship_dimension = _dimension(
            "supported" if accepted else "withheld",
            (
                "phase05_relationship_validated"
                if accepted
                else "phase05_relationship_rejected"
            ),
            evidence_ids,
        )
    else:
        relationship_dimension = _dimension(
            "not_applicable",
            "dimension_not_claimed",
        )

    model_dimension = _dimension(
        "supported" if accepted else "withheld",
        (
            "phase06_observation_grounded"
            if accepted
            else "phase06_observation_rejected"
        ),
        evidence_ids,
    )
    return VisualClaimConfidence(
        observation_id=observation.id,
        observation_type=observation.observation_type,
        decision="accept" if accepted else "withhold",
        dimensions=VisualConfidenceDimensions(
            structure=structure_dimension,
            value=value_dimension,
            relationship=relationship_dimension,
            model_observation=model_dimension,
        ),
    )


def assess_visual_confidence(
    item: Mapping[str, Any],
    grounding: VisualModelGroundingEnvelope,
    *,
    enabled: bool,
) -> VisualConfidenceAssessment | None:
    """Return deterministic dimensions or remain entirely inert when off.

    The function intentionally never reads ``observation.confidence``.  Its
    only authority is the typed Phase 05 structure and Phase 06 grounding
    outcome.  Mixed grounding results are atomic: one rejected member causes
    every member to be withheld from the document transaction.
    """

    if not enabled:
        return None
    public_item_id = str(item.get("id") or "").strip()
    if not public_item_id:
        raise ValueError("visual confidence item has no public identity")
    structure = _structure(item)
    transaction_accepted = grounding.status == "accepted"
    claims = sorted(
        (
            _claim(
                member,
                structure=structure,
                transaction_accepted=transaction_accepted,
            )
            for member in grounding.observations
        ),
        key=lambda claim: claim.observation_id,
    )
    decision = (
        "accept"
        if claims and all(claim.decision == "accept" for claim in claims)
        else "withhold"
        if claims
        else "fallback"
    )
    return VisualConfidenceAssessment(
        schema_version="1.0",
        policy_version=_POLICY_VERSION,
        policy_basis=_POLICY_BASIS,
        public_item_id=public_item_id,
        decision=decision,
        reason={
            "accept": "all_claims_grounded",
            "withhold": "grounding_rejected",
            "fallback": "no_observations",
        }[decision],
        claims=claims,
    )


def attach_visual_confidence_assessments(
    payload: Mapping[str, Any],
    assessments: list[tuple[int, VisualConfidenceAssessment]],
    *,
    max_added_bytes: int,
) -> dict[str, Any] | None:
    """Attach accepted qualitative dimensions as one bounded transaction.

    The Phase 06 merge remains authoritative for source/model evidence.  This
    helper only exposes the already-validated Phase 08 assessment on the
    owning public item.  Any collision, ambiguous owner, invalid assessment,
    or size breach rejects the entire sidecar projection.
    """

    if (
        isinstance(max_added_bytes, bool)
        or not isinstance(max_added_bytes, int)
        or not 1 <= max_added_bytes <= 1024 * 1024
        or not assessments
    ):
        return None
    baseline = deepcopy(dict(payload))
    candidate = deepcopy(baseline)
    pages = candidate.get("pages")
    if not isinstance(pages, list):
        return None

    owners: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for page in pages:
        if not isinstance(page, dict):
            return None
        page_index = page.get("page_index")
        items = page.get("items")
        if (
            isinstance(page_index, bool)
            or not isinstance(page_index, int)
            or not isinstance(items, list)
        ):
            return None
        for item in items:
            if not isinstance(item, dict):
                return None
            item_id = item.get("id")
            if isinstance(item_id, str):
                owners.setdefault((page_index, item_id), []).append(item)

    try:
        ordered = sorted(
            (
                (
                    page_index,
                    VisualConfidenceAssessment.model_validate(
                        assessment,
                        strict=True,
                    ),
                )
                for page_index, assessment in assessments
            ),
            key=lambda value: (value[0], value[1].public_item_id),
        )
    except (MemoryError, TypeError, ValueError, OverflowError):
        return None
    keys = [
        (page_index, assessment.public_item_id)
        for page_index, assessment in ordered
    ]
    if len(keys) != len(set(keys)):
        return None

    for page_index, assessment in ordered:
        if assessment.decision != "accept":
            return None
        matches = owners.get((page_index, assessment.public_item_id), [])
        if len(matches) != 1:
            return None
        owner = matches[0]
        if "visual_confidence" in owner:
            return None
        owner["visual_confidence"] = assessment.model_dump(
            mode="json",
            exclude_none=True,
        )

    try:
        baseline_bytes = len(
            json.dumps(
                baseline,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        )
        candidate_bytes = len(
            json.dumps(
                candidate,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        )
        added_bytes = candidate_bytes - baseline_bytes
    except (MemoryError, TypeError, ValueError, OverflowError):
        return None
    if not 1 <= added_bytes <= min(
        max_added_bytes,
        _MAX_PUBLIC_ASSESSMENT_BYTES,
    ):
        return None

    # Import lazily to keep this release-first sidecar independent from the
    # public schema and to prove existing permissive extension handling still
    # round-trips the bounded payload.
    try:
        from app.models import ParseResult

        validated = ParseResult.model_validate(candidate)
        result = validated.model_dump(mode="json", exclude_unset=True)
    except (MemoryError, TypeError, ValueError, OverflowError):
        return None
    for page_index, assessment in ordered:
        result_pages = result.get("pages")
        if not isinstance(result_pages, list):
            return None
        matches = [
            item
            for page in result_pages
            if isinstance(page, dict) and page.get("page_index") == page_index
            for item in page.get("items", [])
            if isinstance(item, dict)
            and item.get("id") == assessment.public_item_id
        ]
        if len(matches) != 1 or matches[0].get("visual_confidence") != (
            assessment.model_dump(mode="json", exclude_none=True)
        ):
            return None
    return result


__all__ = [
    "VisualClaimConfidence",
    "VisualConfidenceAssessment",
    "VisualConfidenceDimension",
    "VisualConfidenceDimensions",
    "attach_visual_confidence_assessments",
    "assess_visual_confidence",
]
