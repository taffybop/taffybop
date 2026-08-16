"""Measure supported raster vertical bars from grounded pixel geometry."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from app.services.visual_contracts import (
    ChartAxis,
    ChartPanel,
    ChartPoint,
    ChartSeries,
    NumericTolerance,
    VisualBoundingBox,
    VisualConcern,
    VisualConfidenceDimensions,
    VisualEvidence,
    VisualLabel,
    VisualProvenance,
    VisualStructure,
    ensure_finite_mapping,
)


_MAX_BARS = 1_024
_NUMBER_RE = re.compile(r"^[+-]?(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?%?$")


def _stable_id(prefix: str, *parts: Any) -> str:
    data = json.dumps(
        parts,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(data).hexdigest()[:24]}"


def _text(value: Any, *, maximum: int = 256) -> str:
    if not isinstance(value, str):
        raise ValueError("raster bar identity must be a string")
    result = value.strip()
    if not result or len(result) > maximum:
        raise ValueError("raster bar identity is empty or too long")
    return result


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("raster bar input must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("raster bar input must be finite")
    return result


def _sequence(value: Any, *, maximum: int) -> list[Any]:
    if value is None:
        return []
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or len(value) > maximum
    ):
        raise ValueError("raster bars exceed their entry limit")
    return list(value)


def _box(value: Any) -> VisualBoundingBox:
    if not isinstance(value, Mapping):
        raise ValueError("raster bar bbox must be an object")
    box = VisualBoundingBox(
        x=_number(value.get("x")),
        y=_number(value.get("y")),
        width=_number(value.get("width", value.get("w"))),
        height=_number(value.get("height", value.get("h"))),
        unit="px",
    )
    if box.width <= 0 or box.height <= 0:
        raise ValueError("raster bar bbox must have positive area")
    return box


def _transform_box(
    box: VisualBoundingBox,
    matrix: Sequence[float],
    *,
    unit: Literal["pt", "px"],
) -> VisualBoundingBox:
    a, b, c, d, e, f = matrix
    points = [
        (a * x + c * y + e, b * x + d * y + f)
        for x, y in (
            (box.x, box.y),
            (box.x + box.width, box.y),
            (box.x, box.y + box.height),
            (box.x + box.width, box.y + box.height),
        )
    ]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return VisualBoundingBox(
        x=min(xs),
        y=min(ys),
        width=max(xs) - min(xs),
        height=max(ys) - min(ys),
        unit=unit,
    )


def _contains(
    outer: VisualBoundingBox,
    inner: VisualBoundingBox,
    *,
    tolerance: float = 1e-6,
) -> bool:
    return (
        outer.unit == inner.unit
        and inner.x >= outer.x - tolerance
        and inner.y >= outer.y - tolerance
        and inner.x + inner.width <= outer.x + outer.width + tolerance
        and inner.y + inner.height <= outer.y + outer.height + tolerance
    )


def _raw_values(item: Mapping[str, Any]) -> Mapping[str, Any] | None:
    direct = item.get("raster_bar_evidence")
    if isinstance(direct, Mapping):
        return direct
    meta = item.get("meta")
    if isinstance(meta, Mapping):
        value = meta.get("phase05_raster_bar_evidence")
        if isinstance(value, Mapping):
            return value
    return None


def _append_concerns(
    structure: VisualStructure,
    codes: Sequence[str],
) -> VisualStructure:
    payload = structure.model_dump(mode="json", exclude_none=True)
    concerns = payload.setdefault("concerns", [])
    existing = {str(value.get("code")) for value in concerns}
    for code in codes:
        if code in existing:
            continue
        concerns.append(
            VisualConcern(
                code=code,
                stage="raster_bars",
                evidence_ids=list(structure.region.evidence_ids),
            ).model_dump(mode="json", exclude_none=True)
        )
        existing.add(code)
    return VisualStructure.model_validate(payload)


def _source_axis_map(structure: VisualStructure) -> dict[str, ChartAxis]:
    evidence = {record.id: record for record in structure.evidence}
    output: dict[str, ChartAxis] = {}
    for axis in structure.axes:
        for evidence_id in axis.evidence_ids:
            record = evidence[evidence_id]
            if record.kind == "axis":
                for source_id in record.provenance.source_object_ids:
                    if source_id in output and output[source_id].id != axis.id:
                        raise ValueError("raster axis source identity is ambiguous")
                    output[source_id] = axis
    return output


def _source_label_map(structure: VisualStructure) -> dict[str, VisualLabel]:
    evidence = {record.id: record for record in structure.evidence}
    output: dict[str, VisualLabel] = {}
    for label in structure.labels:
        for evidence_id in label.evidence_ids:
            for source_id in evidence[evidence_id].provenance.source_token_ids:
                if source_id in output and output[source_id].id != label.id:
                    raise ValueError("raster label source identity is ambiguous")
                output[source_id] = label
    return output


def _source_series_map(structure: VisualStructure) -> dict[str, ChartSeries]:
    return {value.source_object_id: value for value in structure.series}


def _explicit_number(text: str) -> tuple[float, float]:
    normalized = text.strip()
    if not _NUMBER_RE.fullmatch(normalized):
        raise ValueError("explicit raster bar label is not numeric")
    numeric = normalized[:-1] if normalized.endswith("%") else normalized
    value = float(numeric.replace(",", ""))
    decimals = len(numeric.rsplit(".", 1)[1]) if "." in numeric else 0
    return value, 0.5 * (10.0 ** (-decimals))


def _display(value: float, precision: Any) -> str:
    if isinstance(precision, bool) or not isinstance(precision, int) or not 0 <= precision <= 8:
        raise ValueError("raster bar precision is invalid")
    return f"{value:.{precision}f}".rstrip("0").rstrip(".") or "0"


def _category_matches_mark(
    structure: VisualStructure,
    *,
    panel: ChartPanel,
    value_axis: ChartAxis,
    category: VisualLabel,
    box: VisualBoundingBox,
    tolerance: float,
) -> bool:
    """Prove declared category ownership from grounded label geometry."""

    category_axes = [
        axis
        for axis in structure.axes
        if axis.panel_id == value_axis.panel_id
        and axis.orientation == "x"
        and category.id in axis.category_label_ids
    ]
    if len(category_axes) != 1 or panel.raster_pixel_bbox is None:
        return False
    category_axis = category_axes[0]
    category_ids = category_axis.category_label_ids
    if not category_ids or len(category_ids) != len(set(category_ids)):
        return False
    labels_by_id = {label.id: label for label in structure.labels}
    candidates: list[tuple[float, str]] = []
    mark_center = box.x + box.width / 2.0
    for label_id in category_ids:
        label = labels_by_id.get(label_id)
        if (
            label is None
            or label.role != "category"
            or label.raster_pixel_bbox is None
            or label.id not in panel.label_ids
            or not _contains(panel.raster_pixel_bbox, label.raster_pixel_bbox)
        ):
            return False
        label_center = label.raster_pixel_bbox.x + label.raster_pixel_bbox.width / 2.0
        candidates.append((abs(mark_center - label_center), label.id))
    candidates.sort(key=lambda value: (value[0], value[1]))
    nearest_distance = candidates[0][0]
    nearest = [
        label_id
        for distance, label_id in candidates
        if distance <= nearest_distance + tolerance
    ]
    return nearest == [category.id]


def _explicit_label_matches_mark(
    label: VisualLabel,
    *,
    panel: ChartPanel,
    box: VisualBoundingBox,
    tolerance: float,
) -> bool:
    """Require a value label to be visibly attached to its declared bar."""

    label_box = label.raster_pixel_bbox
    panel_box = panel.raster_pixel_bbox
    if (
        label.role != "other"
        or label_box is None
        or panel_box is None
        or label.id not in panel.label_ids
        or not _contains(panel_box, label_box)
    ):
        return False
    label_center_x = label_box.x + label_box.width / 2.0
    if not box.x - tolerance <= label_center_x <= box.x + box.width + tolerance:
        return False
    vertical_distance_to_tip = max(
        box.y - (label_box.y + label_box.height),
        label_box.y - box.y,
        0.0,
    )
    return vertical_distance_to_tip <= max(label_box.height, 2.0 * tolerance)


def _axis_contains(axis: ChartAxis, value: float, tolerance: float) -> bool:
    return (
        axis.minimum is not None
        and axis.maximum is not None
        and axis.minimum - tolerance <= value <= axis.maximum + tolerance
    )


@dataclass(frozen=True, slots=True)
class _Candidate:
    point: ChartPoint
    mark: VisualEvidence
    baseline: VisualEvidence
    point_evidence: VisualEvidence
    box: VisualBoundingBox
    axis: ChartAxis
    mode: Literal["simple", "grouped", "stacked"]
    stack_source_id: str | None
    pixel_tolerance: float


def measure_raster_bars(
    item: Mapping[str, Any],
    structure: VisualStructure,
    *,
    page_index: int,
    input_kind: str,
) -> VisualStructure:
    """Measure grounded simple/grouped/stacked vertical raster bars."""

    if structure.region.kind != "chart":
        raise ValueError("raster bars require a chart-owned region")
    raw = _raw_values(item)
    if raw is None:
        return _append_concerns(structure, ["raster_bar_evidence_unavailable"])
    try:
        if len(raw) > 16:
            raise ValueError("raster bar evidence container is too large")
        raw_bars = _sequence(raw.get("bars"), maximum=_MAX_BARS)
        axes = _source_axis_map(structure)
        labels = _source_label_map(structure)
        series_values = _source_series_map(structure)
        panels = {panel.id: panel for panel in structure.panels}
        if len(structure.transforms) != 1:
            raise ValueError("raster bar transform is ambiguous")
        transform = structure.transforms[0]
        if transform.source_space != "raster_pixel" or transform.target_space != "page":
            raise ValueError("raster bar transform space differs")
    except (MemoryError, TypeError, ValueError):
        return _append_concerns(structure, ["raster_bar_evidence_malformed"])

    public_item_id = structure.evidence[0].provenance.public_item_id
    normalized_input: Literal["pdf", "image", "unknown"] = (
        input_kind if input_kind in {"pdf", "image"} else "unknown"
    )
    page_unit: Literal["pt", "px"] = structure.region.page_bbox.unit
    built: list[_Candidate] = []
    concern_codes: list[str] = []

    for raw_candidate in raw_bars:
        try:
            if not isinstance(raw_candidate, Mapping):
                raise ValueError("raster bar candidate must be an object")
            ensure_finite_mapping(raw_candidate)
            if str(raw_candidate.get("family") or "bar").casefold() != "bar":
                continue
            if raw_candidate.get("clipped") is True or raw_candidate.get("occluded") is True:
                concern_codes.append("raster_bar_clipped_or_occluded")
                continue
            if raw_candidate.get("ambiguous") is True:
                concern_codes.append("raster_bar_ambiguous")
                continue
            if str(raw_candidate.get("orientation") or "vertical").casefold() != "vertical":
                concern_codes.append("raster_bar_unsupported")
                continue
            if any(
                raw_candidate.get(key) is True
                for key in ("three_dimensional", "pictorial", "waterfall", "floating")
            ):
                concern_codes.append("raster_bar_unsupported")
                continue
            source_id = _text(raw_candidate.get("source_object_id"))
            box = _box(raw_candidate.get("raster_pixel_bbox"))
            axis = axes.get(_text(raw_candidate.get("axis_source_object_id")))
            if (
                axis is None
                or axis.orientation != "y"
                or axis.scale != "linear"
                or axis.slope is None
                or axis.intercept is None
                or axis.baseline_position is None
                or axis.residual is None
                or axis.calibration_tolerance is None
            ):
                concern_codes.append("raster_bar_axis_or_baseline_unavailable")
                continue
            panel = panels.get(axis.panel_id)
            if (
                panel is None
                or panel.raster_pixel_bbox is None
                or not _contains(panel.raster_pixel_bbox, box)
            ):
                concern_codes.append("raster_bar_outside_panel")
                continue
            category = labels.get(
                _text(raw_candidate.get("category_label_source_token_id"), maximum=128)
            )
            if category is None or category.role != "category" or not any(
                other.panel_id == axis.panel_id
                and category.id in other.category_label_ids
                for other in structure.axes
            ):
                concern_codes.append("raster_bar_category_unresolved")
                continue
            series = series_values.get(
                _text(raw_candidate.get("series_source_object_id"))
            )
            if series is None or axis.panel_id not in series.panel_ids:
                concern_codes.append("raster_bar_series_unresolved")
                continue
            mode = str(raw_candidate.get("mode") or "simple").casefold()
            if mode not in {"simple", "grouped", "stacked"}:
                concern_codes.append("raster_bar_unsupported")
                continue
            mode_value: Literal["simple", "grouped", "stacked"] = mode  # type: ignore[assignment]
            stack_source: str | None = None
            stack_index: int | None = None
            if mode_value == "stacked":
                stack_source = _text(raw_candidate.get("stack_id"), maximum=128)
                stack_index_value = raw_candidate.get("stack_index")
                if (
                    isinstance(stack_index_value, bool)
                    or not isinstance(stack_index_value, int)
                    or not 0 <= stack_index_value <= 255
                ):
                    raise ValueError("raster stack index is invalid")
                stack_index = stack_index_value
            elif raw_candidate.get("stack_id") is not None or raw_candidate.get("stack_index") is not None:
                raise ValueError("non-stack raster bar has stack identity")
            tolerance_pixels = _number(raw_candidate.get("pixel_tolerance", 0.75))
            if not 0 < tolerance_pixels <= 10:
                raise ValueError("raster pixel tolerance is unsupported")
            if not _category_matches_mark(
                structure,
                panel=panel,
                value_axis=axis,
                category=category,
                box=box,
                tolerance=tolerance_pixels,
            ):
                concern_codes.append("raster_bar_category_unresolved")
                continue
            if box.height <= 2.0 * tolerance_pixels:
                concern_codes.append("raster_bar_zero_or_low_height")
                continue
            bottom = box.y + box.height
            if mode_value in {"simple", "grouped"} and abs(
                bottom - axis.baseline_position
            ) > tolerance_pixels:
                concern_codes.append("raster_bar_baseline_mismatch")
                continue
            baseline_position = bottom if mode_value == "stacked" else axis.baseline_position
            tip_value = axis.slope * box.y + axis.intercept
            base_value = axis.slope * baseline_position + axis.intercept
            measured_value = (
                abs(tip_value - base_value)
                if mode_value == "stacked"
                else tip_value
            )
            axis_error = max(axis.residual, axis.calibration_tolerance)
            tolerance_value = abs(axis.slope) * tolerance_pixels * 2.0 + axis_error * 2.0
            endpoint_tolerance = abs(axis.slope) * tolerance_pixels + axis_error
            if not _axis_contains(
                axis,
                tip_value,
                endpoint_tolerance,
            ) or not _axis_contains(axis, base_value, endpoint_tolerance):
                concern_codes.append("raster_bar_outside_axis_range")
                continue
            if not math.isfinite(measured_value) or abs(measured_value) <= tolerance_value:
                concern_codes.append("raster_bar_zero_or_low_height")
                continue

            explicit_source = raw_candidate.get("explicit_label_source_token_id")
            explicit_label: VisualLabel | None = None
            if explicit_source is not None:
                explicit_label = labels.get(_text(explicit_source, maximum=128))
                if explicit_label is None or not _explicit_label_matches_mark(
                    explicit_label,
                    panel=panel,
                    box=box,
                    tolerance=tolerance_pixels,
                ):
                    concern_codes.append("raster_bar_explicit_label_unresolved")
                    continue
                explicit_value, explicit_tolerance = _explicit_number(explicit_label.text)
                if not _axis_contains(axis, explicit_value, explicit_tolerance) or abs(
                    explicit_value - measured_value
                ) > explicit_tolerance + tolerance_value:
                    concern_codes.append("raster_bar_explicit_label_mismatch")
                    continue
                raw_value = explicit_value
                method: Literal["explicit_text", "raster_measured"] = "explicit_text"
                display_value = explicit_label.text
                tolerance = NumericTolerance(
                    absolute=explicit_tolerance,
                    lower=explicit_tolerance,
                    upper=explicit_tolerance,
                    basis="explicit_rounding",
                )
            else:
                raw_value = measured_value
                method = "raster_measured"
                display_value = _display(raw_value, raw_candidate.get("display_precision", 2))
                tolerance = NumericTolerance(
                    absolute=tolerance_value,
                    lower=tolerance_value,
                    upper=tolerance_value,
                    basis="combined",
                )
            page_box = _transform_box(box, transform.matrix, unit=page_unit)
            mark_id = _stable_id("visual-evidence", structure.region.id, "raster-mark", source_id)
            baseline_id = _stable_id("visual-evidence", structure.region.id, "raster-baseline", source_id)
            point_evidence_id = _stable_id("visual-evidence", structure.region.id, "raster-point", source_id)
            provenance = VisualProvenance(
                public_item_id=public_item_id,
                page_index=page_index,
                input_kind=normalized_input,
                source_object_ids=[source_id],
                source_token_ids=[],
                extraction_method="raster",
            )
            mark = VisualEvidence(
                id=mark_id,
                kind="mark",
                page_bbox=page_box,
                raster_pixel_bbox=box,
                transform_ids=[transform.id],
                provenance=provenance,
            )
            baseline_pixels = VisualBoundingBox(
                x=box.x,
                y=baseline_position,
                width=box.width,
                height=0.0,
                unit="px",
            )
            baseline = VisualEvidence(
                id=baseline_id,
                kind="baseline",
                page_bbox=_transform_box(baseline_pixels, transform.matrix, unit=page_unit),
                raster_pixel_bbox=baseline_pixels,
                transform_ids=[transform.id],
                provenance=provenance,
            )
            explicit_token_ids: list[str] = []
            if explicit_label is not None:
                existing_evidence = {record.id: record for record in structure.evidence}
                explicit_token_ids = sorted(
                    {
                        token
                        for evidence_id in explicit_label.evidence_ids
                        for token in existing_evidence[evidence_id].provenance.source_token_ids
                    }
                )
            point_record = VisualEvidence(
                id=point_evidence_id,
                kind="point",
                page_bbox=(explicit_label.page_bbox if explicit_label is not None else page_box),
                raster_pixel_bbox=(explicit_label.raster_pixel_bbox if explicit_label is not None else box),
                transform_ids=[transform.id],
                provenance=VisualProvenance(
                    public_item_id=public_item_id,
                    page_index=page_index,
                    input_kind=normalized_input,
                    source_object_ids=[source_id],
                    source_token_ids=explicit_token_ids,
                    extraction_method=("explicit_text" if method == "explicit_text" else "raster"),
                ),
            )
            required = [mark_id, baseline_id]
            point_evidence_ids = [point_evidence_id, mark_id, baseline_id]
            for evidence_id in (
                *axis.evidence_ids,
                *axis.calibration_evidence_ids,
                *category.evidence_ids,
                *series.evidence_ids,
                *(explicit_label.evidence_ids if explicit_label is not None else ()),
            ):
                if evidence_id not in point_evidence_ids:
                    point_evidence_ids.append(evidence_id)
            calibration_confidence = max(
                0.0,
                min(1.0, 1.0 - axis.residual / max(axis.calibration_tolerance, 1e-9)),
            )
            confidence = VisualConfidenceDimensions(
                geometry=1.0,
                calibration=calibration_confidence,
                category=1.0,
                series=1.0,
                value=max(0.0, min(1.0, 1.0 - tolerance.absolute / max(abs(raw_value), tolerance.absolute, 1e-9))),
            )
            point = ChartPoint(
                id=_stable_id("chart-point", structure.region.id, source_id, raw_value, method),
                panel_id=axis.panel_id,
                mark_id=mark_id,
                point_evidence_id=point_evidence_id,
                baseline_evidence_id=baseline_id,
                axis_ids=[axis.id],
                category_label_id=category.id,
                series_id=series.id,
                stack_id=(
                    _stable_id("chart-stack", structure.region.id, axis.panel_id, category.id, stack_source)
                    if stack_source is not None
                    else None
                ),
                stack_index=stack_index,
                raw_value=raw_value,
                display_value=display_value,
                method=method,
                tolerance=tolerance,
                confidence=confidence,
                source_geometry_evidence_ids=required,
                evidence_ids=point_evidence_ids,
            )
            built.append(
                _Candidate(
                    point=point,
                    mark=mark,
                    baseline=baseline,
                    point_evidence=point_record,
                    box=box,
                    axis=axis,
                    mode=mode_value,
                    stack_source_id=stack_source,
                    pixel_tolerance=tolerance_pixels,
                )
            )
        except (MemoryError, TypeError, ValueError):
            concern_codes.append("raster_bar_candidate_malformed")

    invalid: set[str] = set()
    stacks: dict[tuple[str, str, str], list[_Candidate]] = defaultdict(list)
    for value in built:
        if value.mode == "stacked" and value.stack_source_id is not None:
            stacks[(value.point.panel_id, value.point.category_label_id, value.stack_source_id)].append(value)
    for members in stacks.values():
        ordered = sorted(members, key=lambda value: value.point.stack_index or 0)
        aligned = all(
            abs(value.box.x - ordered[0].box.x) <= max(value.pixel_tolerance, ordered[0].pixel_tolerance)
            and abs(value.box.width - ordered[0].box.width) <= max(value.pixel_tolerance, ordered[0].pixel_tolerance)
            for value in ordered[1:]
        )
        valid = (
            [value.point.stack_index for value in ordered] == list(range(len(ordered)))
            and len({value.axis.id for value in ordered}) == 1
            and len({value.point.series_id for value in ordered}) == len(ordered)
            and aligned
        )
        if valid:
            for index, value in enumerate(ordered):
                expected = value.axis.baseline_position if index == 0 else ordered[index - 1].box.y
                if expected is None or abs(value.box.y + value.box.height - expected) > value.pixel_tolerance:
                    valid = False
                    break
        if not valid:
            invalid.update(value.point.id for value in ordered)
            concern_codes.append("raster_bar_stack_ambiguous")

    survivors = [value for value in built if value.point.id not in invalid]
    if not survivors:
        concern_codes.append("raster_bar_values_withheld")
    payload = structure.model_dump(mode="json", exclude_none=True)
    payload["points"] = [
        value.point.model_dump(mode="json", exclude_none=True) for value in survivors
    ]
    evidence = [record.model_copy(deep=True) for record in structure.evidence]
    for value in survivors:
        evidence.extend((value.mark, value.baseline, value.point_evidence))
    payload["evidence"] = [
        record.model_dump(mode="json", exclude_none=True) for record in evidence
    ]
    try:
        staged = VisualStructure.model_validate(payload)
    except (TypeError, ValueError):
        return _append_concerns(structure, ["raster_bars_failed_closed"])
    return _append_concerns(staged, concern_codes)


__all__ = ["measure_raster_bars"]
