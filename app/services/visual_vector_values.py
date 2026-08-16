"""Measure supported vector vertical bars with explicit uncertainty."""

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
    ChartPoint,
    ChartSeries,
    NumericTolerance,
    VectorPrimitive,
    VisualBoundingBox,
    VisualConcern,
    VisualConfidenceDimensions,
    VisualEvidence,
    VisualLabel,
    VisualProvenance,
    VisualStructure,
    ensure_finite_mapping,
)


_MAX_CANDIDATES = 1_024
_NUMBER_RE = re.compile(r"^[+-]?(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?%?$")


def _stable_id(prefix: str, *parts: Any) -> str:
    payload = json.dumps(
        parts,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(payload).hexdigest()[:24]}"


def _text(value: Any, *, maximum: int = 256) -> str:
    if not isinstance(value, str):
        raise ValueError("vector value reference must be a string")
    result = value.strip()
    if not result or len(result) > maximum:
        raise ValueError("vector value reference is empty or too long")
    return result


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("vector value input must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("vector value input must be finite")
    return result


def _sequence(value: Any, *, label: str, maximum: int) -> list[Any]:
    if value is None:
        return []
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or len(value) > maximum
    ):
        raise ValueError(f"{label} exceeds its entry limit")
    return list(value)


def _raw_values(item: Mapping[str, Any]) -> Mapping[str, Any] | None:
    direct = item.get("vector_value_evidence")
    if isinstance(direct, Mapping):
        return direct
    meta = item.get("meta")
    if isinstance(meta, Mapping):
        value = meta.get("phase05_vector_value_evidence")
        if isinstance(value, Mapping):
            return value
    return None


def _append_concerns(
    structure: VisualStructure,
    codes: Sequence[str],
) -> VisualStructure:
    payload = structure.model_dump(mode="json", exclude_none=True)
    concerns = payload.setdefault("concerns", [])
    existing = {str(concern.get("code")) for concern in concerns}
    for code in codes:
        if code in existing:
            continue
        concerns.append(
            VisualConcern(
                code=code,
                stage="vector_values",
                evidence_ids=list(structure.region.evidence_ids),
            ).model_dump(mode="json", exclude_none=True)
        )
        existing.add(code)
    return VisualStructure.model_validate(payload)


def _axis_source_map(structure: VisualStructure) -> dict[str, ChartAxis]:
    evidence = {record.id: record for record in structure.evidence}
    result: dict[str, ChartAxis] = {}
    for axis in structure.axes:
        for evidence_id in axis.evidence_ids:
            record = evidence[evidence_id]
            if record.kind != "axis":
                continue
            for source_id in record.provenance.source_object_ids:
                if source_id in result and result[source_id].id != axis.id:
                    raise ValueError("axis source identity is ambiguous")
                result[source_id] = axis
    return result


def _label_token_map(structure: VisualStructure) -> dict[str, VisualLabel]:
    evidence = {record.id: record for record in structure.evidence}
    result: dict[str, VisualLabel] = {}
    for label in structure.labels:
        for evidence_id in label.evidence_ids:
            for token_id in evidence[evidence_id].provenance.source_token_ids:
                if token_id in result and result[token_id].id != label.id:
                    raise ValueError("label source identity is ambiguous")
                result[token_id] = label
    return result


def _primitive_map(structure: VisualStructure) -> dict[str, VectorPrimitive]:
    if structure.vector_inventory is None:
        raise ValueError("vector inventory is unavailable")
    result: dict[str, VectorPrimitive] = {}
    for primitive in structure.vector_inventory.primitives:
        if primitive.source_object_id in result:
            raise ValueError("mark source identity is ambiguous")
        result[primitive.source_object_id] = primitive
    return result


def _series_map(structure: VisualStructure) -> dict[str, ChartSeries]:
    result: dict[str, ChartSeries] = {}
    for series in structure.series:
        if series.source_object_id in result:
            raise ValueError("series source identity is ambiguous")
        result[series.source_object_id] = series
    return result


def _explicit_number(text: str) -> tuple[float, float]:
    normalized = text.strip()
    if not _NUMBER_RE.fullmatch(normalized):
        raise ValueError("explicit chart label is not an unambiguous number")
    percent = normalized.endswith("%")
    numeric = normalized[:-1] if percent else normalized
    raw_value = float(numeric.replace(",", ""))
    decimals = len(numeric.rsplit(".", 1)[1]) if "." in numeric else 0
    tolerance = 0.5 * (10.0 ** (-decimals))
    if percent:
        # Keep the source-visible percent number rather than silently changing
        # units; the chart unit label carries the interpretation.
        tolerance = max(tolerance, 0.5 * (10.0 ** (-decimals)))
    if not math.isfinite(raw_value):
        raise ValueError("explicit chart label is non-finite")
    return raw_value, tolerance


def _derived_display(value: float, precision: int) -> str:
    if not 0 <= precision <= 8:
        raise ValueError("vector display precision is unsupported")
    return f"{value:.{precision}f}".rstrip("0").rstrip(".") or "0"


def _confidence(axis: ChartAxis, tolerance: float, value: float) -> VisualConfidenceDimensions:
    calibration_tolerance = axis.calibration_tolerance or 0.0
    residual = axis.residual or 0.0
    calibration = max(
        0.0,
        min(1.0, 1.0 - residual / max(calibration_tolerance, 1e-9)),
    )
    relative = tolerance / max(abs(value), tolerance, 1e-9)
    value_confidence = max(0.0, min(1.0, 1.0 - relative))
    return VisualConfidenceDimensions(
        geometry=1.0,
        calibration=calibration,
        category=1.0,
        series=1.0,
        value=value_confidence,
    )


@dataclass(frozen=True, slots=True)
class _Candidate:
    point: ChartPoint
    mark: VectorPrimitive
    axis: ChartAxis
    mode: Literal["simple", "grouped", "stacked"]
    stack_id: str | None
    stack_index: int | None
    geometry_tolerance: float
    staged_evidence: tuple[VisualEvidence, ...]


def _axis_value(axis: ChartAxis, position: float) -> float:
    if axis.slope is None or axis.intercept is None:
        raise ValueError("vector value axis is not calibrated")
    value = axis.slope * position + axis.intercept
    if not math.isfinite(value):
        raise ValueError("vector value axis produced a non-finite ordinate")
    return value


def _axis_contains(axis: ChartAxis, value: float, tolerance: float) -> bool:
    if axis.minimum is None or axis.maximum is None:
        return False
    return axis.minimum - tolerance <= value <= axis.maximum + tolerance


def _series_matches_mark(series: ChartSeries, mark: VectorPrimitive) -> bool:
    if series.color is None:
        return False
    expected = series.color.strip().casefold()
    return expected in {
        value.strip().casefold()
        for value in (mark.fill, mark.stroke)
        if value is not None
    }


def _category_matches_mark(
    structure: VisualStructure,
    *,
    mark: VectorPrimitive,
    category: VisualLabel,
    tolerance: float,
) -> bool:
    axes = [
        axis
        for axis in structure.axes
        if axis.panel_id == mark.panel_id
        and category.id in axis.category_label_ids
    ]
    if not axes:
        return False
    category_ids = {
        label_id for axis in axes for label_id in axis.category_label_ids
    }
    if len(category_ids) == 1:
        return True
    horizontal = [axis for axis in axes if axis.orientation == "x"]
    if not horizontal:
        return False
    center = mark.chart_local_bbox.x + mark.chart_local_bbox.width / 2.0
    candidates = [
        (abs(center - tick.position), tick.label_id)
        for axis in horizontal
        for tick in axis.ticks
        if tick.label_id in axis.category_label_ids
    ]
    if not candidates:
        return False
    candidates.sort(key=lambda value: (value[0], value[1]))
    if len(candidates) > 1 and abs(candidates[0][0] - candidates[1][0]) <= tolerance:
        return False
    return candidates[0][1] == category.id


def _explicit_label_matches_mark(
    label: VisualLabel,
    mark: VectorPrimitive,
) -> bool:
    if label.role != "other" or label.page_bbox is None:
        return False
    label_box = label.page_bbox
    mark_box = mark.page_bbox
    horizontal_overlap = min(
        label_box.x + label_box.width,
        mark_box.x + mark_box.width,
    ) - max(label_box.x, mark_box.x)
    vertical_gap = max(
        mark_box.y - (label_box.y + label_box.height),
        label_box.y - (mark_box.y + mark_box.height),
        0.0,
    )
    return horizontal_overlap > 0 and vertical_gap <= max(12.0, label_box.height)


def measure_vector_bars(
    item: Mapping[str, Any],
    structure: VisualStructure,
    *,
    page_index: int,
    input_kind: str,
) -> VisualStructure:
    """Measure supported simple/grouped/stacked vertical vector bars."""

    if structure.region.kind != "chart":
        raise ValueError("vector bar measurement requires a chart")
    raw = _raw_values(item)
    if raw is None:
        return _append_concerns(structure, ["vector_value_evidence_unavailable"])
    try:
        if len(raw) > 16 or any(
            not isinstance(key, str) or len(key) > 128 for key in raw
        ):
            raise ValueError("vector value evidence container is malformed")
        raw_candidates = _sequence(
            raw.get("bars"),
            label="vector bar candidates",
            maximum=_MAX_CANDIDATES,
        )
        axes = _axis_source_map(structure)
        labels = _label_token_map(structure)
        primitives = _primitive_map(structure)
        series_values = _series_map(structure)
    except (MemoryError, TypeError, ValueError):
        return _append_concerns(structure, ["vector_value_evidence_malformed"])
    evidence = [record.model_copy(deep=True) for record in structure.evidence]
    evidence_by_id = {record.id: record for record in evidence}
    public_item_id = structure.evidence[0].provenance.public_item_id
    normalized_input_kind: Literal["pdf", "image", "unknown"] = (
        input_kind if input_kind in {"pdf", "image"} else "unknown"
    )
    built: list[_Candidate] = []
    concern_codes: list[str] = []

    for candidate_index, raw_candidate in enumerate(raw_candidates):
        try:
            if not isinstance(raw_candidate, Mapping):
                raise ValueError("vector bar candidate must be an object")
            ensure_finite_mapping(raw_candidate)
            source_object_id = _text(
                raw_candidate.get("source_object_id"),
                maximum=256,
            )
            mark = primitives.get(source_object_id)
            if (
                mark is None
                or mark.kind != "rectangle"
                or not mark.supported
                or mark.clipped
            ):
                concern_codes.append("vector_bar_mark_unsupported")
                continue
            axis = axes.get(
                _text(raw_candidate.get("axis_source_object_id"), maximum=256)
            )
            if (
                axis is None
                or axis.orientation != "y"
                or axis.scale != "linear"
                or axis.baseline_position is None
                or axis.slope is None
                or axis.residual is None
                or axis.calibration_tolerance is None
                or mark.panel_id != axis.panel_id
            ):
                concern_codes.append("vector_bar_axis_or_baseline_unavailable")
                continue
            category = labels.get(
                _text(
                    raw_candidate.get("category_label_source_token_id"),
                    maximum=128,
                )
            )
            if category is None or category.role != "category":
                concern_codes.append("vector_bar_category_unresolved")
                continue
            series = series_values.get(
                _text(raw_candidate.get("series_source_object_id"), maximum=256)
            )
            if (
                series is None
                or mark.panel_id not in series.panel_ids
                or not _series_matches_mark(series, mark)
            ):
                concern_codes.append("vector_bar_series_unresolved")
                continue
            mode = str(raw_candidate.get("mode") or "simple").casefold()
            if mode not in {"simple", "grouped", "stacked"}:
                concern_codes.append("vector_bar_family_unsupported")
                continue
            mode_value: Literal["simple", "grouped", "stacked"] = mode  # type: ignore[assignment]
            stack_id: str | None = None
            stack_index: int | None = None
            if mode_value == "stacked":
                stack_id = _text(raw_candidate.get("stack_id"), maximum=128)
                raw_stack_index = raw_candidate.get("stack_index")
                if (
                    isinstance(raw_stack_index, bool)
                    or not isinstance(raw_stack_index, int)
                    or not 0 <= raw_stack_index <= 255
                ):
                    raise ValueError("stack index is invalid")
                stack_index = raw_stack_index
            elif any(
                raw_candidate.get(key) is not None
                for key in ("stack_id", "stack_index")
            ):
                raise ValueError("non-stacked bar carries stack identity")
            if raw_candidate.get("ambiguous") is True:
                concern_codes.append("vector_bar_ownership_ambiguous")
                continue
            geometry_tolerance = _number(
                raw_candidate.get("coordinate_tolerance", 0.25)
            )
            if geometry_tolerance <= 0 or geometry_tolerance > 10:
                raise ValueError("vector coordinate tolerance is unsupported")
            mark_height = mark.chart_local_bbox.height
            minimum_height = _number(raw_candidate.get("minimum_mark_height", 1.0))
            if mark_height < minimum_height:
                concern_codes.append("vector_bar_too_low_to_measure")
                continue
            if raw_candidate.get("rounded") is True or mark_height < 4.0:
                geometry_tolerance *= 2.0
            if not _category_matches_mark(
                structure,
                mark=mark,
                category=category,
                tolerance=geometry_tolerance,
            ):
                concern_codes.append("vector_bar_category_unresolved")
                continue
            top_position = mark.chart_local_bbox.y
            bottom_position = mark.chart_local_bbox.y + mark.chart_local_bbox.height
            if mode_value in {"simple", "grouped"} and abs(
                bottom_position - axis.baseline_position
            ) > geometry_tolerance:
                concern_codes.append("vector_bar_baseline_mismatch")
                continue
            baseline_position = (
                bottom_position
                if mode_value == "stacked"
                else axis.baseline_position
            )
            tip_value = _axis_value(axis, top_position)
            baseline_value = _axis_value(axis, baseline_position)
            axis_error = max(axis.residual, axis.calibration_tolerance)
            endpoint_tolerance = (
                abs(axis.slope) * geometry_tolerance + axis_error
            )
            if not _axis_contains(axis, tip_value, endpoint_tolerance) or not _axis_contains(
                axis,
                baseline_value,
                endpoint_tolerance,
            ):
                concern_codes.append("vector_bar_outside_axis_range")
                continue
            baseline_box = VisualBoundingBox(
                x=mark.chart_local_bbox.x,
                y=baseline_position,
                width=mark.chart_local_bbox.width,
                height=0.0,
                unit=mark.chart_local_bbox.unit,
            )
            baseline_evidence_id = _stable_id(
                "visual-evidence",
                structure.region.id,
                "baseline",
                source_object_id,
                baseline_position,
            )
            candidate_evidence: list[VisualEvidence] = [
                VisualEvidence(
                    id=baseline_evidence_id,
                    kind="baseline",
                    chart_local_bbox=baseline_box,
                    transform_ids=list(mark.transform_ids),
                    provenance=VisualProvenance(
                        public_item_id=public_item_id,
                        page_index=page_index,
                        input_kind=normalized_input_kind,
                        source_object_ids=[source_object_id],
                        source_token_ids=[],
                        extraction_method="vector",
                    ),
                )
            ]
            explicit_token = raw_candidate.get("explicit_label_source_token_id")
            explicit_label: VisualLabel | None = None
            if explicit_token is not None:
                explicit_label = labels.get(_text(explicit_token, maximum=128))
                if explicit_label is None or not _explicit_label_matches_mark(
                    explicit_label,
                    mark,
                ):
                    concern_codes.append("vector_bar_explicit_label_unresolved")
                    continue
                raw_value, tolerance_value = _explicit_number(explicit_label.text)
                if not _axis_contains(axis, raw_value, tolerance_value):
                    concern_codes.append("vector_bar_explicit_value_outside_axis")
                    continue
                method: Literal["explicit_text", "vector_measured"] = "explicit_text"
                display_value = explicit_label.text
                tolerance = NumericTolerance(
                    absolute=tolerance_value,
                    lower=tolerance_value,
                    upper=tolerance_value,
                    basis="explicit_rounding",
                )
            else:
                raw_value = (
                    abs(tip_value - baseline_value)
                    if mode_value == "stacked"
                    else tip_value
                )
                tolerance_value = (
                    abs(axis.slope) * geometry_tolerance * 2.0
                    + axis_error * 2.0
                )
                if not math.isfinite(raw_value) or not math.isfinite(tolerance_value):
                    raise ValueError("measured vector value is non-finite")
                if abs(raw_value) <= tolerance_value:
                    concern_codes.append("vector_bar_too_low_to_measure")
                    continue
                method = "vector_measured"
                precision_raw = raw_candidate.get("display_precision", 2)
                if (
                    isinstance(precision_raw, bool)
                    or not isinstance(precision_raw, int)
                ):
                    raise ValueError("display precision must be an integer")
                display_value = _derived_display(raw_value, precision_raw)
                tolerance = NumericTolerance(
                    absolute=tolerance_value,
                    lower=tolerance_value,
                    upper=tolerance_value,
                    basis="combined",
                )
            point_evidence_id = _stable_id(
                "visual-evidence",
                structure.region.id,
                "point",
                source_object_id,
                category.id,
                series.id,
                method,
                raw_value,
            )
            explicit_token_ids = (
                [
                    token_id
                    for evidence_id in explicit_label.evidence_ids
                    for token_id in evidence_by_id[evidence_id].provenance.source_token_ids
                ]
                if explicit_label is not None
                else []
            )
            candidate_evidence.append(
                VisualEvidence(
                    id=point_evidence_id,
                    kind="point",
                    page_bbox=(
                        explicit_label.page_bbox
                        if explicit_label is not None
                        else mark.page_bbox
                    ),
                    chart_local_bbox=(
                        None if explicit_label is not None else mark.chart_local_bbox
                    ),
                    transform_ids=list(mark.transform_ids),
                    provenance=VisualProvenance(
                        public_item_id=public_item_id,
                        page_index=page_index,
                        input_kind=normalized_input_kind,
                        source_object_ids=[source_object_id],
                        source_token_ids=sorted(set(explicit_token_ids)),
                        extraction_method=(
                            "explicit_text" if method == "explicit_text" else "vector"
                        ),
                    ),
                )
            )
            source_geometry_ids = [*mark.evidence_ids, baseline_evidence_id]
            if explicit_label is not None:
                source_geometry_ids.extend(explicit_label.evidence_ids)
            point_evidence_ids: list[str] = []
            for evidence_id in (
                point_evidence_id,
                baseline_evidence_id,
                *mark.evidence_ids,
                *axis.evidence_ids,
                *axis.calibration_evidence_ids,
                *category.evidence_ids,
                *series.evidence_ids,
                *(explicit_label.evidence_ids if explicit_label is not None else ()),
            ):
                if evidence_id not in point_evidence_ids:
                    point_evidence_ids.append(evidence_id)
            point = ChartPoint(
                id=_stable_id(
                    "chart-point",
                    structure.region.id,
                    source_object_id,
                    category.id,
                    series.id,
                    method,
                    raw_value,
                ),
                panel_id=mark.panel_id,
                mark_id=mark.id,
                point_evidence_id=point_evidence_id,
                baseline_evidence_id=baseline_evidence_id,
                axis_ids=[axis.id],
                category_label_id=category.id,
                series_id=series.id,
                stack_id=(
                    _stable_id(
                        "chart-stack",
                        structure.region.id,
                        mark.panel_id,
                        category.id,
                        stack_id,
                    )
                    if stack_id is not None
                    else None
                ),
                stack_index=stack_index,
                raw_value=raw_value,
                display_value=display_value,
                method=method,
                tolerance=tolerance,
                confidence=_confidence(axis, tolerance.absolute, raw_value),
                source_geometry_evidence_ids=list(dict.fromkeys(source_geometry_ids)),
                evidence_ids=point_evidence_ids,
            )
            built.append(
                _Candidate(
                    point=point,
                    mark=mark,
                    axis=axis,
                    mode=mode_value,
                    stack_id=stack_id,
                    stack_index=stack_index,
                    geometry_tolerance=geometry_tolerance,
                    staged_evidence=tuple(candidate_evidence),
                )
            )
        except (MemoryError, TypeError, ValueError):
            concern_codes.append("vector_bar_candidate_malformed")
            continue

    invalid_point_ids: set[str] = set()
    stacks: dict[tuple[str, str, str], list[_Candidate]] = defaultdict(list)
    for candidate in built:
        if candidate.mode == "stacked" and candidate.stack_id is not None:
            stacks[
                (
                    candidate.point.panel_id,
                    candidate.point.category_label_id,
                    candidate.stack_id,
                )
            ].append(candidate)
    for members in stacks.values():
        ordered = sorted(members, key=lambda member: member.stack_index or 0)
        first = ordered[0]
        same_axis = len({member.axis.id for member in ordered}) == 1
        distinct_series = len({member.point.series_id for member in ordered}) == len(
            ordered
        )
        aligned_band = all(
            abs(member.mark.chart_local_bbox.x - first.mark.chart_local_bbox.x)
            <= max(member.geometry_tolerance, first.geometry_tolerance)
            and abs(
                member.mark.chart_local_bbox.width
                - first.mark.chart_local_bbox.width
            )
            <= max(member.geometry_tolerance, first.geometry_tolerance)
            for member in ordered[1:]
        )
        if (
            [member.stack_index for member in ordered] != list(range(len(ordered)))
            or not same_axis
            or not distinct_series
            or not aligned_band
        ):
            invalid_point_ids.update(member.point.id for member in ordered)
            concern_codes.append("vector_bar_stack_ambiguous")
            continue
        for position, member in enumerate(ordered):
            bottom = member.mark.chart_local_bbox.y + member.mark.chart_local_bbox.height
            expected = (
                member.axis.baseline_position
                if position == 0
                else ordered[position - 1].mark.chart_local_bbox.y
            )
            if expected is None or abs(bottom - expected) > member.geometry_tolerance:
                invalid_point_ids.update(value.point.id for value in ordered)
                concern_codes.append("vector_bar_stack_ambiguous")
                break

    points = [
        candidate.point for candidate in built if candidate.point.id not in invalid_point_ids
    ]
    for candidate in built:
        if candidate.point.id not in invalid_point_ids:
            evidence.extend(candidate.staged_evidence)
    if not points:
        concern_codes.append("vector_bar_values_withheld")
    payload = structure.model_dump(mode="json", exclude_none=True)
    payload["points"] = [
        point.model_dump(mode="json", exclude_none=True) for point in points
    ]
    payload["evidence"] = [
        record.model_dump(mode="json", exclude_none=True) for record in evidence
    ]
    try:
        staged = VisualStructure.model_validate(payload)
    except (TypeError, ValueError):
        return _append_concerns(structure, ["vector_values_failed_closed"])
    return _append_concerns(staged, concern_codes)


__all__ = ["measure_vector_bars"]
