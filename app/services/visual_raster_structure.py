"""Recover bounded, value-free structure for supported raster charts."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any, Literal

from app.services.visual_contracts import (
    ChartAxis,
    ChartLegend,
    ChartLegendEntry,
    ChartPanel,
    ChartSeries,
    ChartTick,
    VisualBoundingBox,
    VisualConcern,
    VisualEvidence,
    VisualLabel,
    VisualProvenance,
    VisualStructure,
    VisualTransform,
    ensure_finite_mapping,
)


_MAX_LABELS = 512
_MAX_AXES = 8
_MAX_LEGENDS = 8
_NUMERIC_TICK_RE = re.compile(
    r"^[+-]?(?:(?:\d{1,3}(?:,\d{3})+)|\d+)(?:\.\d+)?%?$"
)


def _stable_id(prefix: str, *parts: Any) -> str:
    encoded = json.dumps(
        parts,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _text(value: Any, *, maximum: int = 1_024) -> str:
    if not isinstance(value, str):
        raise ValueError("raster structure text must be a string")
    result = value.strip()
    if not result or len(result) > maximum:
        raise ValueError("raster structure text is empty or too long")
    return result


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("raster structure coordinate must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("raster structure coordinate must be finite")
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


def _box(value: Any, *, unit: Literal["pt", "px"]) -> VisualBoundingBox:
    if not isinstance(value, Mapping):
        raise ValueError("raster structure bbox must be an object")
    raw_unit = str(value.get("unit") or unit)
    if raw_unit != unit:
        raise ValueError("raster structure bbox unit differs")
    box = VisualBoundingBox(
        x=_number(value.get("x")),
        y=_number(value.get("y")),
        width=_number(value.get("width", value.get("w"))),
        height=_number(value.get("height", value.get("h"))),
        unit=unit,
    )
    if box.width <= 0 or box.height <= 0:
        raise ValueError("raster structure bbox must have positive area")
    return box


def _contains(outer: VisualBoundingBox, inner: VisualBoundingBox) -> bool:
    epsilon = 1e-6
    return (
        outer.unit == inner.unit
        and inner.x + epsilon >= outer.x
        and inner.y + epsilon >= outer.y
        and inner.x + inner.width <= outer.x + outer.width + epsilon
        and inner.y + inner.height <= outer.y + outer.height + epsilon
    )


def _transform_box(
    box: VisualBoundingBox,
    matrix: Sequence[float],
    *,
    unit: Literal["pt", "px"],
) -> VisualBoundingBox:
    a, b, c, d, e, f = matrix
    corners = (
        (box.x, box.y),
        (box.x + box.width, box.y),
        (box.x, box.y + box.height),
        (box.x + box.width, box.y + box.height),
    )
    points = [(a * x + c * y + e, b * x + d * y + f) for x, y in corners]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return VisualBoundingBox(
        x=min(xs),
        y=min(ys),
        width=max(xs) - min(xs),
        height=max(ys) - min(ys),
        unit=unit,
    )


def _same_box(first: VisualBoundingBox, second: VisualBoundingBox) -> bool:
    return first.unit == second.unit and all(
        abs(left - right) <= 1e-4
        for left, right in (
            (first.x, second.x),
            (first.y, second.y),
            (first.width, second.width),
            (first.height, second.height),
        )
    )


def _tick_number(text: str) -> float:
    """Derive a numeric calibration value from one complete OCR label."""

    normalized = text.strip().replace("\N{MINUS SIGN}", "-")
    negative = normalized.startswith("(") and normalized.endswith(")")
    if negative:
        normalized = normalized[1:-1].strip()
    if normalized[:1] in {"$", "€", "£", "¥", "₹"}:
        normalized = normalized[1:].strip()
    if not _NUMERIC_TICK_RE.fullmatch(normalized):
        raise ValueError("raster tick OCR label is not wholly numeric")
    numeric = normalized[:-1] if normalized.endswith("%") else normalized
    result = float(numeric.replace(",", ""))
    return -result if negative else result


def _axis_label_position(label: VisualLabel, orientation: str) -> float:
    box = label.raster_pixel_bbox
    if box is None or box.unit != "px":
        raise ValueError("raster tick has no pixel-grounded OCR geometry")
    if orientation == "x":
        return box.x + box.width / 2.0
    return box.y + box.height / 2.0


def _assert_close(actual: float, asserted: Any, tolerance: float, label: str) -> None:
    expected = _number(asserted)
    if abs(actual - expected) > tolerance + 1e-6:
        raise ValueError(f"raster {label} assertion differs from grounded geometry")


def _derived_baseline(
    orientation: str,
    axis: VisualBoundingBox,
    slope: float,
    intercept: float,
) -> float:
    if orientation == "x":
        return axis.y
    start = axis.y
    end = axis.y + axis.height
    zero = -intercept / slope
    if start - 1e-6 <= zero <= end + 1e-6:
        return min(end, max(start, zero))
    return min((start, end), key=lambda position: abs(slope * position + intercept))


def _vertical_overlap(first: VisualBoundingBox, second: VisualBoundingBox) -> bool:
    return min(first.y + first.height, second.y + second.height) - max(
        first.y, second.y
    ) > 0


def _interval_gap(
    first_start: float,
    first_size: float,
    second_start: float,
    second_size: float,
) -> float:
    return max(
        first_start - (second_start + second_size),
        second_start - (first_start + first_size),
        0.0,
    )


def _raw_structure(item: Mapping[str, Any]) -> Mapping[str, Any] | None:
    direct = item.get("raster_structure_evidence")
    if isinstance(direct, Mapping):
        return direct
    meta = item.get("meta")
    if isinstance(meta, Mapping):
        value = meta.get("phase05_raster_structure_evidence")
        if isinstance(value, Mapping):
            return value
    return None


def _append_concern(structure: VisualStructure, code: str) -> VisualStructure:
    payload = structure.model_dump(mode="json", exclude_none=True)
    concerns = payload.setdefault("concerns", [])
    if code not in {str(value.get("code")) for value in concerns}:
        concerns.append(
            VisualConcern(
                code=code,
                stage="raster_structure",
                evidence_ids=list(structure.region.evidence_ids),
            ).model_dump(mode="json", exclude_none=True)
        )
    return VisualStructure.model_validate(payload)


def _fit_axis(
    ticks: Sequence[tuple[float, float]],
    tolerance: float,
) -> tuple[float, float, float]:
    if len(ticks) < 2 or len({position for position, _value in ticks}) < 2:
        raise ValueError("raster axis needs two distinct grounded ticks")
    count = float(len(ticks))
    mean_x = sum(position for position, _value in ticks) / count
    mean_y = sum(value for _position, value in ticks) / count
    denominator = sum((position - mean_x) ** 2 for position, _value in ticks)
    if denominator <= 0:
        raise ValueError("raster axis calibration is singular")
    slope = sum(
        (position - mean_x) * (value - mean_y) for position, value in ticks
    ) / denominator
    intercept = mean_y - slope * mean_x
    residual = max(
        abs(slope * position + intercept - value) for position, value in ticks
    )
    if slope == 0 or residual > tolerance + 1e-6:
        raise ValueError("raster axis calibration exceeds tolerance")
    return slope, intercept, residual


def structure_raster_chart(
    item: Mapping[str, Any],
    structure: VisualStructure,
    *,
    page_index: int,
    input_kind: str,
) -> VisualStructure:
    """Return supported raster axes/labels/legends without any data marks."""

    if structure.region.kind != "chart":
        raise ValueError("raster structure requires a chart-owned region")
    raw = _raw_structure(item)
    if raw is None:
        return _append_concern(structure, "raster_structure_evidence_unavailable")
    try:
        ensure_finite_mapping(raw)
        if raw.get("ambiguous_axis") is True or raw.get("ambiguous_legend") is True:
            return _append_concern(structure, "raster_structure_ambiguous")
        occurrences_raw = _sequence(
            item.get("ocr_token_occurrences"),
            label="spatial OCR occurrences",
            maximum=_MAX_LABELS,
        )
        occurrences: dict[str, Mapping[str, Any]] = {}
        for value in occurrences_raw:
            if not isinstance(value, Mapping) or value.get("selected") is False:
                continue
            identifier = _text(
                value.get("occurrence_id", value.get("id")),
                maximum=128,
            )
            if identifier in occurrences:
                raise ValueError("spatial OCR occurrence identity repeats")
            occurrences[identifier] = value
        if not occurrences:
            raise ValueError("raster structure has no selected spatial OCR")

        raw_transform = raw.get("transform")
        if not isinstance(raw_transform, Mapping):
            raise ValueError("raster structure transform is unavailable")
        raw_matrix = _sequence(
            raw_transform.get("matrix"),
            label="raster transform matrix",
            maximum=6,
        )
        if len(raw_matrix) != 6:
            raise ValueError("raster transform matrix must have six values")
        matrix = [_number(value) for value in raw_matrix]
        transform = VisualTransform(
            id=_stable_id("visual-transform", structure.region.id, "raster", matrix),
            source_space="raster_pixel",
            target_space="page",
            matrix=matrix,
            source_transform_ids=[
                _text(raw_transform.get("source_id", "raster-to-page"), maximum=128)
            ],
        )
        page_unit: Literal["pt", "px"] = structure.region.page_bbox.unit
        normalized_input: Literal["pdf", "image", "unknown"] = (
            input_kind if input_kind in {"pdf", "image"} else "unknown"
        )
        public_item_id = structure.evidence[0].provenance.public_item_id

        raw_panel = raw.get("panel")
        if not isinstance(raw_panel, Mapping):
            raise ValueError("raster chart panel is unavailable")
        panel_pixels = _box(raw_panel.get("raster_pixel_bbox"), unit="px")
        panel_page = _transform_box(panel_pixels, matrix, unit=page_unit)
        if raw_panel.get("page_bbox") is not None and not _same_box(
            panel_page,
            _box(raw_panel.get("page_bbox"), unit=page_unit),
        ):
            raise ValueError("raster panel transform differs from page geometry")
        if not _contains(structure.region.page_bbox, panel_page):
            raise ValueError("raster panel leaves its chart region")
        panel_source = _text(
            raw_panel.get("source_object_id", "raster-panel"),
            maximum=256,
        )
        panel_id = _stable_id(
            "chart-panel",
            structure.region.id,
            panel_source,
            panel_pixels.model_dump(mode="json"),
        )
        panel_evidence_id = _stable_id("visual-evidence", panel_id, "panel")
        evidence = [record.model_copy(deep=True) for record in structure.evidence]
        evidence.append(
            VisualEvidence(
                id=panel_evidence_id,
                kind="panel",
                page_bbox=panel_page,
                raster_pixel_bbox=panel_pixels,
                transform_ids=[transform.id],
                provenance=VisualProvenance(
                    public_item_id=public_item_id,
                    page_index=page_index,
                    input_kind=normalized_input,
                    source_object_ids=[panel_source],
                    source_token_ids=[],
                    extraction_method="raster",
                ),
            )
        )

        labels: list[VisualLabel] = []
        labels_by_source: dict[str, VisualLabel] = {}
        raw_labels = _sequence(
            raw.get("labels"), label="raster labels", maximum=_MAX_LABELS
        )
        allowed_roles = {
            "title",
            "axis_title",
            "tick",
            "category",
            "unit",
            "legend",
            "other",
        }
        for raw_label in raw_labels:
            if not isinstance(raw_label, Mapping):
                raise ValueError("raster label must be an object")
            source_token = _text(raw_label.get("source_token_id"), maximum=128)
            if source_token in labels_by_source or source_token not in occurrences:
                raise ValueError("raster label source occurrence is unknown or repeated")
            occurrence = occurrences[source_token]
            text = _text(raw_label.get("text"))
            if text != _text(occurrence.get("text")):
                raise ValueError("raster label text differs from spatial OCR")
            role = str(raw_label.get("role") or "other")
            if role not in allowed_roles:
                raise ValueError("raster label role is unsupported")
            page_box = _box(occurrence.get("bbox"), unit=page_unit)
            pixel_box = _box(
                occurrence.get("crop_pixel_bbox", raw_label.get("raster_pixel_bbox")),
                unit="px",
            )
            if not _same_box(
                page_box,
                _transform_box(pixel_box, matrix, unit=page_unit),
            ):
                raise ValueError("raster label page/pixel transform differs")
            if not _contains(panel_page, page_box) or not _contains(
                panel_pixels, pixel_box
            ):
                raise ValueError("raster label is outside the chart panel")
            evidence_id = _stable_id(
                "visual-evidence", structure.region.id, "raster-label", source_token
            )
            label_id = _stable_id(
                "visual-label", structure.region.id, source_token, text, role
            )
            evidence.append(
                VisualEvidence(
                    id=evidence_id,
                    kind="label",
                    page_bbox=page_box,
                    raster_pixel_bbox=pixel_box,
                    transform_ids=[transform.id],
                    provenance=VisualProvenance(
                        public_item_id=public_item_id,
                        page_index=page_index,
                        input_kind=normalized_input,
                        source_object_ids=[],
                        source_token_ids=[source_token],
                        extraction_method="ocr",
                    ),
                )
            )
            label = VisualLabel(
                id=label_id,
                text=text,
                role=role,  # type: ignore[arg-type]
                page_bbox=page_box,
                raster_pixel_bbox=pixel_box,
                evidence_ids=[evidence_id],
                occurrence_index=len(labels),
            )
            labels.append(label)
            labels_by_source[source_token] = label

        axes: list[ChartAxis] = []
        axis_sources: set[str] = set()
        for raw_axis in _sequence(
            raw.get("axes"), label="raster axes", maximum=_MAX_AXES
        ):
            if not isinstance(raw_axis, Mapping):
                raise ValueError("raster axis must be an object")
            scale = str(raw_axis.get("scale") or "linear").casefold()
            if scale != "linear" or raw_axis.get("ambiguous") is True:
                return _append_concern(structure, "raster_axis_unsupported")
            orientation = str(raw_axis.get("orientation") or "")
            if orientation not in {"x", "y"}:
                raise ValueError("raster axis orientation is unsupported")
            source_object = _text(raw_axis.get("source_object_id"), maximum=256)
            if source_object in axis_sources:
                raise ValueError("raster axis source identity repeats")
            axis_sources.add(source_object)
            axis_pixels = _box(raw_axis.get("raster_pixel_bbox"), unit="px")
            if not _contains(panel_pixels, axis_pixels):
                raise ValueError("raster axis leaves its chart panel")
            if (orientation == "x" and axis_pixels.width <= axis_pixels.height) or (
                orientation == "y" and axis_pixels.height <= axis_pixels.width
            ):
                raise ValueError("raster axis geometry differs from its orientation")
            axis_page = _transform_box(axis_pixels, matrix, unit=page_unit)
            if raw_axis.get("page_bbox") is not None and not _same_box(
                axis_page,
                _box(raw_axis.get("page_bbox"), unit=page_unit),
            ):
                raise ValueError("raster axis transform differs from page geometry")
            if not _contains(panel_page, axis_page):
                raise ValueError("raster axis page geometry leaves its chart panel")
            axis_evidence_id = _stable_id(
                "visual-evidence", structure.region.id, "raster-axis", source_object
            )
            evidence.append(
                VisualEvidence(
                    id=axis_evidence_id,
                    kind="axis",
                    page_bbox=axis_page,
                    raster_pixel_bbox=axis_pixels,
                    transform_ids=[transform.id],
                    provenance=VisualProvenance(
                        public_item_id=public_item_id,
                        page_index=page_index,
                        input_kind=normalized_input,
                        source_object_ids=[source_object],
                        source_token_ids=[],
                        extraction_method="raster",
                    ),
                )
            )
            tolerance = _number(raw_axis.get("calibration_tolerance", 0.5))
            if tolerance < 0 or tolerance > 10:
                raise ValueError("raster axis tolerance is unsupported")
            category_sources = [
                _text(value, maximum=128)
                for value in _sequence(
                    raw_axis.get("category_label_source_token_ids"),
                    label="raster axis categories",
                    maximum=_MAX_LABELS,
                )
            ]
            if len(category_sources) != len(set(category_sources)):
                raise ValueError("raster axis category occurrence repeats")
            category_labels: list[VisualLabel] = []
            for token in category_sources:
                label = labels_by_source.get(token)
                if label is None:
                    raise ValueError("raster axis category occurrence is unknown")
                if label.role != "category":
                    raise ValueError("raster axis category label role differs")
                category_labels.append(label)

            raw_ticks = _sequence(
                raw_axis.get("ticks"), label="raster ticks", maximum=128
            )
            grounded_ticks: list[tuple[Mapping[str, Any], str, VisualLabel, float]] = []
            tick_tokens: set[str] = set()
            tick_roles: set[str] = set()
            for raw_tick in raw_ticks:
                if not isinstance(raw_tick, Mapping):
                    raise ValueError("raster tick must be an object")
                token = _text(raw_tick.get("source_token_id"), maximum=128)
                label = labels_by_source.get(token)
                if label is None or label.role not in {"tick", "category"}:
                    raise ValueError("raster tick has no role-compatible OCR label")
                if token in tick_tokens:
                    raise ValueError("raster tick source occurrence repeats")
                tick_tokens.add(token)
                tick_roles.add(label.role)
                position = _axis_label_position(label, orientation)
                label_pixels = label.raster_pixel_bbox
                assert label_pixels is not None
                axis_start = axis_pixels.x if orientation == "x" else axis_pixels.y
                axis_size = axis_pixels.width if orientation == "x" else axis_pixels.height
                if not axis_start - 1.0 <= position <= axis_start + axis_size + 1.0:
                    raise ValueError("raster tick position leaves its axis extent")
                cross_gap = (
                    _interval_gap(
                        label_pixels.y,
                        label_pixels.height,
                        axis_pixels.y,
                        axis_pixels.height,
                    )
                    if orientation == "x"
                    else _interval_gap(
                        label_pixels.x,
                        label_pixels.width,
                        axis_pixels.x,
                        axis_pixels.width,
                    )
                )
                label_minor = (
                    label_pixels.height if orientation == "x" else label_pixels.width
                )
                if cross_gap > max(4.0, label_minor) + 1e-6:
                    raise ValueError("raster tick label is not adjacent to its axis")
                _assert_close(
                    position,
                    raw_tick.get("position"),
                    max(1.0, axis_pixels.height if orientation == "x" else axis_pixels.width),
                    "tick position",
                )
                grounded_ticks.append((raw_tick, token, label, position))
            if len(tick_roles) != 1:
                raise ValueError("raster axis mixes numeric and category ticks")
            category_tick_tokens = {
                token for _raw_tick, token, label, _position in grounded_ticks
                if label.role == "category"
            }
            if category_tick_tokens != set(category_sources):
                raise ValueError("raster axis category refs differ from grounded ticks")
            ordered_categories = {
                token: float(index)
                for index, (_raw_tick, token, _label, _position) in enumerate(
                    sorted(grounded_ticks, key=lambda value: value[3])
                )
            } if tick_roles == {"category"} else {}

            ticks: list[ChartTick] = []
            fit_values: list[tuple[float, float]] = []
            calibration_ids = [axis_evidence_id]
            evidence_by_id = {record.id: record for record in evidence}
            for raw_tick, token, label, position in grounded_ticks:
                value = (
                    ordered_categories[token]
                    if label.role == "category"
                    else _tick_number(label.text)
                )
                _assert_close(
                    value,
                    raw_tick.get("value"),
                    max(tolerance, 1e-6),
                    "tick value",
                )
                fit_values.append((position, value))
                label_evidence = evidence_by_id[label.evidence_ids[0]]
                tick_evidence_id = _stable_id(
                    "visual-evidence", structure.region.id, "raster-tick", token
                )
                evidence.append(
                    VisualEvidence(
                        id=tick_evidence_id,
                        kind="tick",
                        page_bbox=label_evidence.page_bbox,
                        raster_pixel_bbox=label_evidence.raster_pixel_bbox,
                        transform_ids=[transform.id],
                        provenance=VisualProvenance(
                            public_item_id=public_item_id,
                            page_index=page_index,
                            input_kind=normalized_input,
                            source_object_ids=[source_object],
                            source_token_ids=[token],
                            extraction_method="raster",
                        ),
                    )
                )
                calibration_ids.append(tick_evidence_id)
                ticks.append(
                    ChartTick(
                        id=_stable_id("chart-tick", structure.region.id, source_object, token),
                        value=value,
                        position=position,
                        label_id=label.id,
                        evidence_ids=[tick_evidence_id],
                    )
                )
            slope, intercept, residual = _fit_axis(fit_values, tolerance)
            baseline = _derived_baseline(
                orientation,
                axis_pixels,
                slope,
                intercept,
            )
            _assert_close(
                baseline,
                raw_axis.get("baseline_position"),
                max(1.0, axis_pixels.height if orientation == "x" else axis_pixels.width),
                "axis baseline",
            )
            unit_source = raw_axis.get("unit_label_source_token_id")
            unit_label_id = None
            if unit_source is not None:
                unit = labels_by_source.get(_text(unit_source, maximum=128))
                if unit is None or unit.role != "unit":
                    raise ValueError("raster axis unit label is unresolved")
                unit_label_id = unit.id
            axes.append(
                ChartAxis(
                    id=_stable_id("chart-axis", structure.region.id, source_object),
                    panel_id=panel_id,
                    orientation=orientation,  # type: ignore[arg-type]
                    scale="linear",
                    minimum=min(value for _position, value in fit_values),
                    maximum=max(value for _position, value in fit_values),
                    slope=slope,
                    intercept=intercept,
                    residual=residual,
                    calibration_tolerance=tolerance,
                    baseline_position=baseline,
                    unit_label_id=unit_label_id,
                    ticks=ticks,
                    category_label_ids=[label.id for label in category_labels],
                    evidence_ids=[axis_evidence_id],
                    calibration_evidence_ids=calibration_ids,
                )
            )
        if not axes:
            raise ValueError("raster chart has no supported axis")

        legends: list[ChartLegend] = []
        series: list[ChartSeries] = []
        legend_sources: set[str] = set()
        entry_sources: set[str] = set()
        entry_label_ids: set[str] = set()
        entry_colors: set[str] = set()
        swatch_sources: set[str] = set()
        swatch_geometries: set[tuple[float, float, float, float]] = set()
        for raw_legend in _sequence(
            raw.get("legends"), label="raster legends", maximum=_MAX_LEGENDS
        ):
            if not isinstance(raw_legend, Mapping) or raw_legend.get("ambiguous") is True:
                return _append_concern(structure, "raster_legend_ambiguous")
            legend_source = _text(raw_legend.get("source_object_id"), maximum=256)
            if legend_source in legend_sources:
                raise ValueError("raster legend source identity repeats")
            legend_sources.add(legend_source)
            legend_evidence_id = _stable_id(
                "visual-evidence", structure.region.id, "raster-legend", legend_source
            )
            evidence.append(
                VisualEvidence(
                    id=legend_evidence_id,
                    kind="legend",
                    page_bbox=panel_page,
                    raster_pixel_bbox=panel_pixels,
                    transform_ids=[transform.id],
                    provenance=VisualProvenance(
                        public_item_id=public_item_id,
                        page_index=page_index,
                        input_kind=normalized_input,
                        source_object_ids=[legend_source],
                        source_token_ids=[],
                        extraction_method="raster",
                    ),
                )
            )
            entries: list[ChartLegendEntry] = []
            for raw_entry in _sequence(
                raw_legend.get("entries"), label="raster legend entries", maximum=64
            ):
                if not isinstance(raw_entry, Mapping):
                    raise ValueError("raster legend entry must be an object")
                entry_source = _text(raw_entry.get("source_object_id"), maximum=256)
                if entry_source in entry_sources:
                    raise ValueError("raster legend entry source identity repeats")
                entry_sources.add(entry_source)
                token = _text(raw_entry.get("label_source_token_id"), maximum=128)
                label = labels_by_source.get(token)
                if label is None or label.role != "legend":
                    raise ValueError("raster legend entry label is unresolved")
                if label.id in entry_label_ids:
                    raise ValueError("raster legend label association repeats")
                entry_label_ids.add(label.id)
                color = _text(raw_entry.get("color"), maximum=64).casefold()
                sampled_color = raw_entry.get("sampled_color")
                if sampled_color is not None and (
                    _text(sampled_color, maximum=64).casefold() != color
                ):
                    raise ValueError("raster legend sampled color differs")
                if color in entry_colors:
                    raise ValueError("raster legend color association repeats")
                entry_colors.add(color)
                swatch_source = _text(
                    raw_entry.get("swatch_source_object_id"), maximum=256
                )
                if swatch_source in swatch_sources:
                    raise ValueError("raster legend swatch source identity repeats")
                swatch_sources.add(swatch_source)
                swatch_pixels = _box(raw_entry.get("swatch_raster_pixel_bbox"), unit="px")
                swatch_geometry = (
                    swatch_pixels.x,
                    swatch_pixels.y,
                    swatch_pixels.width,
                    swatch_pixels.height,
                )
                if swatch_geometry in swatch_geometries:
                    raise ValueError("raster legend swatch geometry repeats")
                swatch_geometries.add(swatch_geometry)
                swatch_page = _transform_box(swatch_pixels, matrix, unit=page_unit)
                if not _contains(panel_pixels, swatch_pixels) or not _contains(
                    panel_page, swatch_page
                ):
                    raise ValueError("raster legend swatch leaves its panel")
                if label.raster_pixel_bbox is None or not _vertical_overlap(
                    label.raster_pixel_bbox,
                    swatch_pixels,
                ):
                    raise ValueError("raster legend label/swatch association is not spatial")
                swatch_evidence_id = _stable_id(
                    "visual-evidence", structure.region.id, "raster-swatch", swatch_source
                )
                evidence.append(
                    VisualEvidence(
                        id=swatch_evidence_id,
                        kind="swatch",
                        page_bbox=swatch_page,
                        raster_pixel_bbox=swatch_pixels,
                        transform_ids=[transform.id],
                        provenance=VisualProvenance(
                            public_item_id=public_item_id,
                            page_index=page_index,
                            input_kind=normalized_input,
                            source_object_ids=[swatch_source],
                            source_token_ids=[],
                            extraction_method="raster",
                        ),
                    )
                )
                entry_id = _stable_id(
                    "chart-legend-entry", structure.region.id, entry_source
                )
                entries.append(
                    ChartLegendEntry(
                        id=entry_id,
                        label_id=label.id,
                        swatch_evidence_id=swatch_evidence_id,
                        color=color,
                        evidence_ids=[label.evidence_ids[0], swatch_evidence_id],
                    )
                )
                series.append(
                    ChartSeries(
                        id=_stable_id("chart-series", structure.region.id, entry_source),
                        source_object_id=entry_source,
                        label_id=label.id,
                        color=color,
                        legend_entry_id=entry_id,
                        panel_ids=[panel_id],
                        evidence_ids=[label.evidence_ids[0], swatch_evidence_id],
                    )
                )
            if entries:
                legends.append(
                    ChartLegend(
                        id=_stable_id("chart-legend", structure.region.id, legend_source),
                        panel_id=panel_id,
                        entries=entries,
                        evidence_ids=[legend_evidence_id],
                    )
                )

        payload = structure.model_dump(mode="json", exclude_none=True)
        payload["transforms"] = [transform.model_dump(mode="json", exclude_none=True)]
        payload["labels"] = [
            value.model_dump(mode="json", exclude_none=True) for value in labels
        ]
        payload["panels"] = [
            ChartPanel(
                id=panel_id,
                page_bbox=panel_page,
                raster_pixel_bbox=panel_pixels,
                label_ids=[value.id for value in labels],
                evidence_ids=[panel_evidence_id],
            ).model_dump(mode="json", exclude_none=True)
        ]
        payload["axes"] = [
            value.model_dump(mode="json", exclude_none=True) for value in axes
        ]
        payload["legends"] = [
            value.model_dump(mode="json", exclude_none=True) for value in legends
        ]
        payload["series"] = [
            value.model_dump(mode="json", exclude_none=True) for value in series
        ]
        payload["points"] = []
        payload["vector_inventory"] = None
        payload["evidence"] = [
            value.model_dump(mode="json", exclude_none=True) for value in evidence
        ]
        payload["concerns"] = [
            value
            for value in payload.get("concerns", [])
            if value.get("code") != "chart_structure_unresolved"
        ]
        return VisualStructure.model_validate(payload)
    except (MemoryError, TypeError, ValueError):
        return _append_concern(structure, "raster_structure_malformed")


__all__ = ["structure_raster_chart"]
