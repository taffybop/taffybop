"""Measure visible points on supported simple raster line charts."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from app.services.visual_contracts import (
    ChartAxis,
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


_MAX_PATHS = 256
_MAX_POINTS_PER_PATH = 2_048
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
        raise ValueError("raster line identity must be a string")
    result = value.strip()
    if not result or len(result) > maximum:
        raise ValueError("raster line identity is empty or too long")
    return result


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("raster line input must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("raster line input must be finite")
    return result


def _sequence(value: Any, *, maximum: int) -> list[Any]:
    if value is None:
        return []
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or len(value) > maximum
    ):
        raise ValueError("raster line sequence exceeds its entry limit")
    return list(value)


def _box(value: Any) -> VisualBoundingBox:
    if not isinstance(value, Mapping):
        raise ValueError("raster line bbox must be an object")
    box = VisualBoundingBox(
        x=_number(value.get("x")),
        y=_number(value.get("y")),
        width=_number(value.get("width", value.get("w"))),
        height=_number(value.get("height", value.get("h"))),
        unit="px",
    )
    if box.width <= 0 or box.height <= 0:
        raise ValueError("raster line bbox must have positive area")
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


def _raw_lines(item: Mapping[str, Any]) -> Mapping[str, Any] | None:
    direct = item.get("raster_line_evidence")
    if isinstance(direct, Mapping):
        return direct
    meta = item.get("meta")
    if isinstance(meta, Mapping):
        value = meta.get("phase05_raster_line_evidence")
        if isinstance(value, Mapping):
            return value
    return None


def _append_concerns(structure: VisualStructure, codes: Sequence[str]) -> VisualStructure:
    payload = structure.model_dump(mode="json", exclude_none=True)
    concerns = payload.setdefault("concerns", [])
    existing = {str(value.get("code")) for value in concerns}
    for code in codes:
        if code in existing:
            continue
        concerns.append(
            VisualConcern(
                code=code,
                stage="raster_lines",
                evidence_ids=list(structure.region.evidence_ids),
            ).model_dump(mode="json", exclude_none=True)
        )
        existing.add(code)
    return VisualStructure.model_validate(payload)


def _axis_map(structure: VisualStructure) -> dict[str, ChartAxis]:
    evidence = {record.id: record for record in structure.evidence}
    output: dict[str, ChartAxis] = {}
    for axis in structure.axes:
        for evidence_id in axis.evidence_ids:
            record = evidence[evidence_id]
            if record.kind == "axis":
                for source_id in record.provenance.source_object_ids:
                    if source_id in output and output[source_id].id != axis.id:
                        raise ValueError("raster line axis source is ambiguous")
                    output[source_id] = axis
    return output


def _label_map(structure: VisualStructure) -> dict[str, VisualLabel]:
    evidence = {record.id: record for record in structure.evidence}
    output: dict[str, VisualLabel] = {}
    for label in structure.labels:
        for evidence_id in label.evidence_ids:
            for source_id in evidence[evidence_id].provenance.source_token_ids:
                output[source_id] = label
    return output


def _series_map(structure: VisualStructure) -> dict[str, ChartSeries]:
    return {value.source_object_id: value for value in structure.series}


def _explicit_number(text: str) -> tuple[float, float]:
    normalized = text.strip()
    if not _NUMBER_RE.fullmatch(normalized):
        raise ValueError("explicit raster point label is not numeric")
    numeric = normalized[:-1] if normalized.endswith("%") else normalized
    value = float(numeric.replace(",", ""))
    decimals = len(numeric.rsplit(".", 1)[1]) if "." in numeric else 0
    return value, 0.5 * (10.0 ** (-decimals))


@dataclass(frozen=True, slots=True)
class _PathResult:
    points: tuple[ChartPoint, ...]
    evidence: tuple[VisualEvidence, ...]


def measure_raster_lines(
    item: Mapping[str, Any],
    structure: VisualStructure,
    *,
    page_index: int,
    input_kind: str,
) -> VisualStructure:
    """Admit only visible markers on unambiguous simple linear paths."""

    if structure.region.kind != "chart":
        raise ValueError("raster lines require a chart-owned region")
    raw = _raw_lines(item)
    if raw is None:
        return _append_concerns(structure, ["raster_line_evidence_unavailable"])
    try:
        if len(raw) > 16:
            raise ValueError("raster line evidence container is too large")
        raw_paths = _sequence(raw.get("paths"), maximum=_MAX_PATHS)
        axes = _axis_map(structure)
        labels = _label_map(structure)
        series_values = _series_map(structure)
        if len(structure.transforms) != 1:
            raise ValueError("raster line transform is ambiguous")
        transform = structure.transforms[0]
    except (MemoryError, TypeError, ValueError):
        return _append_concerns(structure, ["raster_line_evidence_malformed"])

    public_item_id = structure.evidence[0].provenance.public_item_id
    page_unit: Literal["pt", "px"] = structure.region.page_bbox.unit
    normalized_input: Literal["pdf", "image", "unknown"] = (
        input_kind if input_kind in {"pdf", "image"} else "unknown"
    )
    results: list[_PathResult] = []
    concern_codes: list[str] = []
    existing_evidence = {record.id: record for record in structure.evidence}

    for raw_path in raw_paths:
        try:
            if not isinstance(raw_path, Mapping):
                raise ValueError("raster line path must be an object")
            ensure_finite_mapping(raw_path)
            family = str(raw_path.get("family") or "line").casefold()
            interpolation = str(raw_path.get("interpolation") or "linear").casefold()
            if family != "line" or interpolation != "linear" or any(
                raw_path.get(key) is True for key in ("dense", "area", "scatter_only")
            ):
                concern_codes.append("raster_line_unsupported")
                continue
            if raw_path.get("gap") is True:
                concern_codes.append("raster_line_gap_ambiguous")
                continue
            if raw_path.get("crossing_ambiguous") is True:
                concern_codes.append("raster_line_crossing_ambiguous")
                continue
            if raw_path.get("occluded") is True:
                concern_codes.append("raster_line_occluded")
                continue
            path_source = _text(raw_path.get("source_object_id"))
            axis = axes.get(_text(raw_path.get("axis_source_object_id")))
            if (
                axis is None
                or axis.orientation != "y"
                or axis.scale != "linear"
                or axis.slope is None
                or axis.intercept is None
                or axis.residual is None
                or axis.calibration_tolerance is None
                or axis.baseline_position is None
            ):
                concern_codes.append("raster_line_axis_unavailable")
                continue
            series = series_values.get(_text(raw_path.get("series_source_object_id")))
            if series is None or axis.panel_id not in series.panel_ids:
                concern_codes.append("raster_line_series_unresolved")
                continue
            tolerance_pixels = _number(raw_path.get("pixel_tolerance", 0.75))
            if not 0 < tolerance_pixels <= 10:
                raise ValueError("raster line pixel tolerance is unsupported")
            raw_points = _sequence(
                raw_path.get("points"), maximum=_MAX_POINTS_PER_PATH
            )
            if not raw_points:
                concern_codes.append("raster_line_points_unavailable")
                continue
            boxes: list[VisualBoundingBox] = []
            for raw_point in raw_points:
                if not isinstance(raw_point, Mapping):
                    raise ValueError("raster line point must be an object")
                boxes.append(_box(raw_point.get("raster_pixel_bbox")))
            left = min(box.x for box in boxes)
            top = min(box.y for box in boxes)
            right = max(box.x + box.width for box in boxes)
            bottom = max(box.y + box.height for box in boxes)
            path_pixels = VisualBoundingBox(
                x=left,
                y=top,
                width=max(right - left, 1e-6),
                height=max(bottom - top, 1e-6),
                unit="px",
            )
            path_id = _stable_id("visual-evidence", structure.region.id, "raster-path", path_source)
            path_evidence = VisualEvidence(
                id=path_id,
                kind="path",
                page_bbox=_transform_box(path_pixels, transform.matrix, unit=page_unit),
                raster_pixel_bbox=path_pixels,
                transform_ids=[transform.id],
                provenance=VisualProvenance(
                    public_item_id=public_item_id,
                    page_index=page_index,
                    input_kind=normalized_input,
                    source_object_ids=[path_source],
                    source_token_ids=[],
                    extraction_method="raster",
                ),
            )
            path_records: list[VisualEvidence] = [path_evidence]
            path_points: list[ChartPoint] = []
            for raw_point, box in zip(raw_points, boxes, strict=True):
                assert isinstance(raw_point, Mapping)
                if any(
                    raw_point.get(key) is True
                    for key in ("hidden", "inferred", "occluded", "ambiguous")
                ):
                    concern_codes.append("raster_line_point_withheld")
                    continue
                source_id = _text(raw_point.get("source_object_id"))
                category = labels.get(
                    _text(raw_point.get("category_label_source_token_id"), maximum=128)
                )
                if category is None or category.role != "category" or not any(
                    value.panel_id == axis.panel_id
                    and category.id in value.category_label_ids
                    for value in structure.axes
                ):
                    concern_codes.append("raster_line_category_unresolved")
                    continue
                center_y = box.y + box.height / 2.0
                raw_value = axis.slope * center_y + axis.intercept
                axis_error = max(axis.residual, axis.calibration_tolerance)
                tolerance_value = abs(axis.slope) * (tolerance_pixels + box.height / 2.0) + axis_error
                explicit_source = raw_point.get("explicit_label_source_token_id")
                explicit_label: VisualLabel | None = None
                if explicit_source is not None:
                    explicit_label = labels.get(_text(explicit_source, maximum=128))
                    if explicit_label is None or explicit_label.role != "other":
                        concern_codes.append("raster_line_explicit_label_unresolved")
                        continue
                    raw_value, explicit_tolerance = _explicit_number(explicit_label.text)
                    method: Literal["explicit_text", "raster_measured"] = "explicit_text"
                    display_value = explicit_label.text
                    tolerance = NumericTolerance(
                        absolute=explicit_tolerance,
                        lower=explicit_tolerance,
                        upper=explicit_tolerance,
                        basis="explicit_rounding",
                    )
                else:
                    method = "raster_measured"
                    display_value = f"{raw_value:.2f}".rstrip("0").rstrip(".") or "0"
                    tolerance = NumericTolerance(
                        absolute=tolerance_value,
                        lower=tolerance_value,
                        upper=tolerance_value,
                        basis="combined",
                    )
                point_id = _stable_id("visual-evidence", structure.region.id, "raster-line-point", source_id)
                baseline_id = _stable_id("visual-evidence", structure.region.id, "raster-line-baseline", source_id)
                point_page = _transform_box(box, transform.matrix, unit=page_unit)
                token_ids = sorted(
                    {
                        token
                        for evidence_id in (
                            explicit_label.evidence_ids if explicit_label is not None else ()
                        )
                        for token in existing_evidence[evidence_id].provenance.source_token_ids
                    }
                )
                point_record = VisualEvidence(
                    id=point_id,
                    kind="point",
                    page_bbox=(explicit_label.page_bbox if explicit_label is not None else point_page),
                    raster_pixel_bbox=(explicit_label.raster_pixel_bbox if explicit_label is not None else box),
                    transform_ids=[transform.id],
                    provenance=VisualProvenance(
                        public_item_id=public_item_id,
                        page_index=page_index,
                        input_kind=normalized_input,
                        source_object_ids=[source_id],
                        source_token_ids=token_ids,
                        extraction_method=("explicit_text" if method == "explicit_text" else "raster"),
                    ),
                )
                baseline_pixels = VisualBoundingBox(
                    x=box.x,
                    y=axis.baseline_position,
                    width=box.width,
                    height=0.0,
                    unit="px",
                )
                baseline_record = VisualEvidence(
                    id=baseline_id,
                    kind="baseline",
                    page_bbox=_transform_box(baseline_pixels, transform.matrix, unit=page_unit),
                    raster_pixel_bbox=baseline_pixels,
                    transform_ids=[transform.id],
                    provenance=VisualProvenance(
                        public_item_id=public_item_id,
                        page_index=page_index,
                        input_kind=normalized_input,
                        source_object_ids=[path_source, source_id],
                        source_token_ids=[],
                        extraction_method="raster",
                    ),
                )
                evidence_ids = [point_id, path_id, baseline_id]
                for evidence_id in (
                    *axis.evidence_ids,
                    *axis.calibration_evidence_ids,
                    *category.evidence_ids,
                    *series.evidence_ids,
                    *(explicit_label.evidence_ids if explicit_label is not None else ()),
                ):
                    if evidence_id not in evidence_ids:
                        evidence_ids.append(evidence_id)
                confidence = VisualConfidenceDimensions(
                    geometry=1.0,
                    calibration=max(
                        0.0,
                        min(1.0, 1.0 - axis.residual / max(axis.calibration_tolerance, 1e-9)),
                    ),
                    category=1.0,
                    series=1.0,
                    value=max(0.0, min(1.0, 1.0 - tolerance.absolute / max(abs(raw_value), tolerance.absolute, 1e-9))),
                )
                path_points.append(
                    ChartPoint(
                        id=_stable_id("chart-point", structure.region.id, path_source, source_id, raw_value),
                        panel_id=axis.panel_id,
                        path_id=path_id,
                        point_evidence_id=point_id,
                        baseline_evidence_id=baseline_id,
                        axis_ids=[axis.id],
                        category_label_id=category.id,
                        series_id=series.id,
                        raw_value=raw_value,
                        display_value=display_value,
                        method=method,
                        tolerance=tolerance,
                        confidence=confidence,
                        source_geometry_evidence_ids=[path_id, baseline_id],
                        evidence_ids=evidence_ids,
                    )
                )
                path_records.extend((point_record, baseline_record))
            if path_points:
                results.append(
                    _PathResult(points=tuple(path_points), evidence=tuple(path_records))
                )
        except (MemoryError, TypeError, ValueError):
            concern_codes.append("raster_line_candidate_malformed")

    payload = structure.model_dump(mode="json", exclude_none=True)
    points = [point for result in results for point in result.points]
    payload["points"] = [
        point.model_dump(mode="json", exclude_none=True) for point in points
    ]
    evidence = [record.model_copy(deep=True) for record in structure.evidence]
    for result in results:
        evidence.extend(result.evidence)
    payload["evidence"] = [
        record.model_dump(mode="json", exclude_none=True) for record in evidence
    ]
    if not points:
        concern_codes.append("raster_line_values_withheld")
    try:
        staged = VisualStructure.model_validate(payload)
    except (TypeError, ValueError):
        return _append_concerns(structure, ["raster_lines_failed_closed"])
    return _append_concerns(staged, concern_codes)


__all__ = ["measure_raster_lines"]
