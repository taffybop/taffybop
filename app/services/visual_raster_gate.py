"""Deterministic pre/post admission boundary for raster chart analysis."""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from app.services.visual_contracts import (
    VisualConcern,
    VisualFallback,
    VisualSerialization,
    VisualStructure,
    ensure_finite_mapping,
)


@dataclass(frozen=True, slots=True)
class RasterGateContext:
    started_at: float
    deadline: float
    input_variant: Literal["direct_image", "pdf_render"]
    coordinate_tolerance: float
    predecessor: VisualStructure


class RasterGateRejected(ValueError):
    def __init__(
        self,
        code: str,
        reason: Literal["resource_limit", "timeout", "low_quality", "incomplete"],
    ) -> None:
        super().__init__(code)
        self.code = code
        self.reason = reason


def _raw_gate(item: Mapping[str, Any]) -> Mapping[str, Any] | None:
    direct = item.get("raster_gate_evidence")
    if isinstance(direct, Mapping):
        return direct
    meta = item.get("meta")
    if isinstance(meta, Mapping):
        value = meta.get("phase05_raster_gate_evidence")
        if isinstance(value, Mapping):
            return value
    return None


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RasterGateRejected("raster_gate_incomplete", "incomplete")
    return value


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RasterGateRejected("raster_gate_incomplete", "incomplete")
    result = float(value)
    if not math.isfinite(result):
        raise RasterGateRejected("raster_gate_incomplete", "incomplete")
    return result


def preflight_raster_analysis(
    item: Mapping[str, Any],
    settings: Any,
    predecessor: VisualStructure,
    *,
    input_kind: Literal["pdf", "image", "unknown"],
) -> RasterGateContext:
    raw = _raw_gate(item)
    if raw is None:
        raise RasterGateRejected("raster_gate_incomplete", "incomplete")
    try:
        ensure_finite_mapping(raw)
    except ValueError as exc:
        raise RasterGateRejected("raster_gate_incomplete", "incomplete") from exc
    crop_width = _integer(raw.get("crop_width"), "crop_width")
    crop_height = _integer(raw.get("crop_height"), "crop_height")
    total_pixels = _integer(raw.get("total_pixels"), "total_pixels")
    work_units = _integer(raw.get("work_units"), "work_units")
    if (
        crop_width <= 0
        or crop_height <= 0
        or total_pixels <= 0
        or crop_width > settings.charts_raster_max_crop_width
        or crop_height > settings.charts_raster_max_crop_height
        or total_pixels > settings.charts_raster_max_total_pixels
        or crop_width * crop_height > settings.charts_raster_max_total_pixels
        or work_units > settings.charts_raster_max_work_units
    ):
        raise RasterGateRejected("raster_gate_resource_limit", "resource_limit")
    quality = _number(raw.get("quality"), "quality")
    if (
        not 0.0 <= quality <= 1.0
        or quality < settings.charts_raster_minimum_quality
        or any(raw.get(key) is True for key in ("blurred", "occluded"))
    ):
        raise RasterGateRejected("raster_gate_low_quality", "low_quality")
    if raw.get("incomplete") is True or raw.get("unsupported") is True:
        raise RasterGateRejected("raster_gate_incomplete", "incomplete")
    variant = str(raw.get("input_variant") or "")
    if variant not in {"direct_image", "pdf_render"}:
        raise RasterGateRejected("raster_gate_incomplete", "incomplete")
    expected_variant = {
        "image": "direct_image",
        "pdf": "pdf_render",
    }.get(input_kind)
    if expected_variant is None or variant != expected_variant:
        # A rendered-PDF transform must never be admitted against direct-image
        # coordinates (or vice versa).  The variant is provenance, not a hint.
        raise RasterGateRejected("raster_gate_coordinate_mismatch", "incomplete")
    declared_tolerance = _number(
        raw.get("coordinate_tolerance", settings.charts_raster_coordinate_tolerance),
        "coordinate_tolerance",
    )
    if not 0 <= declared_tolerance <= settings.charts_raster_coordinate_tolerance:
        raise RasterGateRejected("raster_gate_coordinate_mismatch", "incomplete")
    simulated = _number(raw.get("simulated_elapsed_seconds", 0.0), "elapsed")
    if simulated > settings.charts_raster_timeout_seconds:
        raise RasterGateRejected("raster_gate_timeout", "timeout")
    started = time.monotonic()
    return RasterGateContext(
        started_at=started,
        deadline=started + settings.charts_raster_timeout_seconds,
        input_variant=variant,  # type: ignore[arg-type]
        coordinate_tolerance=declared_tolerance,
        predecessor=predecessor.model_copy(deep=True),
    )


def postflight_raster_analysis(
    candidate: VisualStructure,
    context: RasterGateContext,
) -> VisualStructure:
    if time.monotonic() > context.deadline:
        raise RasterGateRejected("raster_gate_timeout", "timeout")
    if (
        candidate.region.kind != "chart"
        or not candidate.axes
        or not candidate.labels
        or any(
            record.provenance.extraction_method not in {
                "layout",
                "ocr",
                "raster",
                "explicit_text",
            }
            for record in candidate.evidence
        )
    ):
        raise RasterGateRejected("raster_gate_incomplete", "incomplete")
    # Every raster value must have survived the shared P05-US05 validator.
    if candidate.points and (
        candidate.fallback.active
        or candidate.serialization is None
        or candidate.serialization.status != "structured_chart"
    ):
        raise RasterGateRejected("raster_gate_incomplete", "incomplete")
    return candidate


def raster_gate_fallback(
    predecessor: VisualStructure,
    rejection: RasterGateRejected,
    candidate: VisualStructure | None = None,
) -> VisualStructure:
    payload = predecessor.model_dump(mode="json", exclude_none=True)
    payload["fallback"] = VisualFallback(
        active=True,
        reason=rejection.reason,
        predecessor_concern="chart_values_not_structured",
    ).model_dump(mode="json", exclude_none=True)
    predecessor_markdown = (
        predecessor.serialization.markdown
        if predecessor.serialization is not None
        else ""
    )
    payload["serialization"] = VisualSerialization(
        status="fallback",
        markdown=predecessor_markdown,
        caption_occurrences=(
            predecessor.serialization.caption_occurrences
            if predecessor.serialization is not None
            else 0
        ),
        row_count=0,
    ).model_dump(mode="json", exclude_none=True)
    payload["points"] = []
    concerns = payload.setdefault("concerns", [])
    existing_codes = {str(value.get("code")) for value in concerns}
    allowed_evidence = {record.id for record in predecessor.evidence}
    if candidate is not None:
        for concern in candidate.concerns:
            if concern.code in existing_codes:
                continue
            evidence_ids = [
                evidence_id
                for evidence_id in concern.evidence_ids
                if evidence_id in allowed_evidence
            ]
            concerns.append(
                VisualConcern(
                    code=concern.code,
                    severity=concern.severity,
                    stage=concern.stage,
                    evidence_ids=(
                        evidence_ids
                        if evidence_ids
                        else list(predecessor.region.evidence_ids)
                    ),
                ).model_dump(mode="json", exclude_none=True)
            )
            existing_codes.add(concern.code)
    if rejection.code not in existing_codes:
        concerns.append(
            VisualConcern(
                code=rejection.code,
                stage="raster_gate",
                evidence_ids=list(predecessor.region.evidence_ids),
            ).model_dump(mode="json", exclude_none=True)
        )
    return VisualStructure.model_validate(payload)


__all__ = [
    "RasterGateContext",
    "RasterGateRejected",
    "postflight_raster_analysis",
    "preflight_raster_analysis",
    "raster_gate_fallback",
]
