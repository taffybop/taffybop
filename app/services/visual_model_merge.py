"""Transactional additive merge for independently grounded model evidence.

The service accepts only P06-US05 ``accepted`` envelopes.  It owns no routing
or inference behavior and never mutates its input.  Every refusal returns a
deep copy of the exact predecessor payload, so callers can discard all model
work without manufacturing public warnings or concerns.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping

from pydantic import Field, model_validator

from app.models import ParseResult
from app.services.visual_model_contracts import (
    VisualModelContract,
    VisualModelEvidenceBundle,
    VisualModelObservation,
)
from app.services.visual_model_grounding import VisualModelGroundingEnvelope


MergeReason = Literal[
    "merge_disabled",
    "no_accepted_observations",
    "grounding_rejected",
    "owner_missing",
    "owner_ambiguous",
    "owner_mismatch",
    "region_conflict",
    "observation_collision",
    "observation_limit",
    "output_limit",
    "canonical_projection_failed",
    "source_evidence_changed",
    "candidate_validation_failed",
    "merged",
    "already_merged",
]


class VisualModelMergeEntry(VisualModelContract):
    """One accepted grounding envelope bound to its public visual owner."""

    public_item_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    page_index: int = Field(ge=1, le=1_000_000)
    region_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    grounding: VisualModelGroundingEnvelope

    @model_validator(mode="after")
    def validate_grounding_owner(self) -> "VisualModelMergeEntry":
        if self.grounding.status != "accepted":
            raise ValueError("merge entry requires accepted grounding")
        if any(
            member.observation.region_id != self.region_id
            or member.observation.page_index != self.page_index
            for member in self.grounding.observations
        ):
            raise ValueError("merge entry observation ownership differs")
        return self


@dataclass(frozen=True, slots=True)
class VisualModelMergeResult:
    """Internal transaction outcome; reason/accounting never enter v1 output."""

    status: Literal["accepted", "fallback"]
    reason: MergeReason
    payload: dict[str, Any]
    merged_observations: int = 0
    added_bytes: int = 0


def _strict_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=lambda member: member.model_dump(mode="json", exclude_none=True),
    ).encode("utf-8")


def _source_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    projection = deepcopy(dict(value))
    projection.pop("canonical_presentation", None)
    pages = projection.get("pages")
    if isinstance(pages, list):
        for page in pages:
            if not isinstance(page, dict):
                continue
            items = page.get("items")
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict):
                    item.pop("visual_model_evidence", None)
    return projection


def _owners(
    payload: Mapping[str, Any],
) -> dict[tuple[int, str], list[dict[str, Any]]]:
    result: dict[tuple[int, str], list[dict[str, Any]]] = {}
    pages = payload.get("pages")
    if not isinstance(pages, list):
        return result
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_index = page.get("page_index")
        if not isinstance(page_index, int) or isinstance(page_index, bool):
            continue
        items = page.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                result.setdefault((page_index, item["id"]), []).append(item)
    return result


def _validated_bundle(value: Any) -> VisualModelEvidenceBundle | None:
    if value is None:
        return None
    dump = getattr(value, "model_dump", None)
    raw = dump(mode="json", exclude_none=True) if callable(dump) else value
    return VisualModelEvidenceBundle.model_validate(raw, strict=True)


def _default_candidate_validator(payload: dict[str, Any]) -> None:
    ParseResult.model_validate(payload)


def merge_visual_model_evidence(
    predecessor: Mapping[str, Any],
    entries: list[VisualModelMergeEntry],
    *,
    enabled: bool,
    max_observations: int = 32,
    max_added_bytes: int = 262_144,
    candidate_validator: Callable[[dict[str, Any]], None] | None = None,
) -> VisualModelMergeResult:
    """Atomically merge all accepted entries or restore the predecessor.

    The document is one transaction: a bad owner, collision, size limit,
    canonical error, or validation failure prevents every proposed addition.
    """

    baseline = deepcopy(dict(predecessor))

    def fallback(reason: MergeReason) -> VisualModelMergeResult:
        return VisualModelMergeResult(
            status="fallback",
            reason=reason,
            payload=deepcopy(baseline),
        )

    if not enabled:
        return fallback("merge_disabled")
    if not entries:
        return fallback("no_accepted_observations")
    if (
        isinstance(max_observations, bool)
        or not isinstance(max_observations, int)
        or not 1 <= max_observations <= 256
        or isinstance(max_added_bytes, bool)
        or not isinstance(max_added_bytes, int)
        or not 1 <= max_added_bytes <= 1024 * 1024
    ):
        return fallback("output_limit")

    candidate = deepcopy(baseline)
    owner_index = _owners(candidate)
    projection_pages = deepcopy(candidate.get("pages"))
    projection_owner_index = _owners({"pages": projection_pages})
    total_observations = 0
    changed = False
    delta_count = 0

    try:
        ordered_entries = sorted(
            (
                VisualModelMergeEntry.model_validate(entry, strict=True)
                for entry in entries
            ),
            key=lambda entry: (
                entry.page_index,
                entry.public_item_id,
                entry.region_id,
                entry.grounding.request_id,
            ),
        )
    except (MemoryError, TypeError, ValueError, OverflowError):
        return fallback("grounding_rejected")

    entry_keys = [
        (entry.page_index, entry.public_item_id, entry.region_id)
        for entry in ordered_entries
    ]
    if len(entry_keys) != len(set(entry_keys)):
        return fallback("owner_ambiguous")

    for entry in ordered_entries:
        owners = owner_index.get((entry.page_index, entry.public_item_id), [])
        projection_owners = projection_owner_index.get(
            (entry.page_index, entry.public_item_id),
            [],
        )
        if not owners:
            return fallback("owner_missing")
        if len(owners) != 1 or len(projection_owners) != 1:
            return fallback("owner_ambiguous")
        owner = owners[0]
        projection_owner = projection_owners[0]
        if str(owner.get("type") or "").casefold() not in {
            "image",
            "chart",
            "diagram",
        }:
            return fallback("owner_mismatch")
        raw_structure = owner.get("visual_structure")
        if isinstance(raw_structure, Mapping):
            raw_region = raw_structure.get("region")
            if (
                not isinstance(raw_region, Mapping)
                or raw_region.get("id") != entry.region_id
            ):
                return fallback("region_conflict")

        try:
            existing = _validated_bundle(owner.get("visual_model_evidence"))
        except (MemoryError, TypeError, ValueError, OverflowError):
            return fallback("candidate_validation_failed")
        if existing is not None and (
            existing.public_item_id != entry.public_item_id
            or existing.page_index != entry.page_index
            or existing.region_id != entry.region_id
        ):
            return fallback("region_conflict")

        by_id: dict[str, VisualModelObservation] = {
            observation.id: observation
            for observation in (existing.observations if existing is not None else [])
        }
        delta: list[VisualModelObservation] = []
        for grounded in entry.grounding.observations:
            observation = grounded.observation
            prior = by_id.get(observation.id)
            if prior is not None and prior != observation:
                return fallback("observation_collision")
            if prior is None:
                by_id[observation.id] = observation
                delta.append(observation)
        combined = sorted(by_id.values(), key=lambda observation: observation.id)
        total_observations += len(combined)
        if total_observations > max_observations:
            return fallback("observation_limit")
        if not delta:
            projection_owner.pop("visual_model_evidence", None)
            continue

        bundle = VisualModelEvidenceBundle(
            schema_version="1.0",
            merge_version="p06-additive-merge-v1",
            validation_version="p06-grounding-p05-v1",
            public_item_id=entry.public_item_id,
            region_id=entry.region_id,
            page_index=entry.page_index,
            source_evidence_preserved=True,
            observations=combined,
        )
        owner["visual_model_evidence"] = bundle.model_dump(
            mode="json",
            exclude_none=True,
        )
        projection_owner["visual_model_evidence"] = bundle.model_copy(
            update={"observations": sorted(delta, key=lambda value: value.id)}
        ).model_dump(mode="json", exclude_none=True)
        changed = True
        delta_count += len(delta)

    if not changed:
        return VisualModelMergeResult(
            status="accepted",
            reason="already_merged",
            payload=deepcopy(baseline),
            merged_observations=0,
            added_bytes=0,
        )

    if "canonical_presentation" in candidate:
        try:
            from app.services.presentation import (
                augment_canonical_visual_model_evidence,
            )

            canonical = augment_canonical_visual_model_evidence(
                candidate["canonical_presentation"],
                projection_pages,
            )
            candidate["canonical_presentation"] = canonical.model_dump(
                mode="json",
                exclude_none=True,
            )
        except Exception:
            return fallback("canonical_projection_failed")

    try:
        if _strict_bytes(_source_projection(candidate)) != _strict_bytes(
            _source_projection(baseline)
        ):
            return fallback("source_evidence_changed")
        added_bytes = len(_strict_bytes(candidate)) - len(_strict_bytes(baseline))
    except (MemoryError, TypeError, ValueError, OverflowError):
        return fallback("candidate_validation_failed")
    if added_bytes < 1 or added_bytes > max_added_bytes:
        return fallback("output_limit")

    try:
        (candidate_validator or _default_candidate_validator)(candidate)
    except Exception:
        return fallback("candidate_validation_failed")

    return VisualModelMergeResult(
        status="accepted",
        reason="merged",
        payload=candidate,
        merged_observations=delta_count,
        added_bytes=added_bytes,
    )


__all__ = [
    "VisualModelMergeEntry",
    "VisualModelMergeResult",
    "merge_visual_model_evidence",
]
