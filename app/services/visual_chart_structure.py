"""Ground supported vector-chart axes, labels, legends, and series."""

from __future__ import annotations

import hashlib
import json
import math
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
    VectorPrimitive,
    VisualBoundingBox,
    VisualConcern,
    VisualEvidence,
    VisualLabel,
    VisualProvenance,
    VisualStructure,
    ensure_finite_mapping,
)


_MAX_LABELS = 512
_MAX_PANELS = 128
_MAX_AXES = 16
_MAX_TICKS = 128
_MAX_LEGENDS = 16
_MAX_LEGEND_ENTRIES = 64
_MAX_SERIES = 128


def _stable_id(prefix: str, *parts: Any) -> str:
    payload = json.dumps(
        parts,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(payload).hexdigest()[:24]}"


def _text(value: Any, *, maximum: int = 1_024) -> str:
    if not isinstance(value, str):
        raise ValueError("chart label text must be a string")
    normalized = " ".join(value.split()).strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError("chart label text is empty or exceeds its limit")
    try:
        if len(normalized.encode("utf-8")) > maximum * 4:
            raise ValueError("chart label text exceeds its byte limit")
    except UnicodeEncodeError as exc:
        raise ValueError("chart label text is not valid UTF-8") from exc
    return normalized


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("chart numeric evidence must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("chart numeric evidence must be finite")
    return result


def _box(value: Any, *, unit: str) -> VisualBoundingBox | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("chart evidence bbox must be an object")
    x = _number(value.get("x"))
    y = _number(value.get("y"))
    width = _number(value.get("width", value.get("w")))
    height = _number(value.get("height", value.get("h")))
    raw_unit = str(value.get("unit") or unit)
    if min(x, y, width, height) < 0 or raw_unit != unit:
        raise ValueError("chart evidence bbox is invalid")
    return VisualBoundingBox(
        x=x,
        y=y,
        width=width,
        height=height,
        unit=unit,
    )


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


def _raw_structure(item: Mapping[str, Any]) -> Mapping[str, Any] | None:
    direct = item.get("chart_structure_evidence")
    if isinstance(direct, Mapping):
        return direct
    meta = item.get("meta")
    if isinstance(meta, Mapping):
        value = meta.get("phase05_chart_structure_evidence")
        if isinstance(value, Mapping):
            return value
    return None


def _append_concern(
    structure: VisualStructure,
    code: str,
) -> VisualStructure:
    payload = structure.model_dump(mode="json", exclude_none=True)
    concerns = payload.setdefault("concerns", [])
    if not any(concern.get("code") == code for concern in concerns):
        concerns.append(
            VisualConcern(
                code=code,
                stage="chart_structure",
                evidence_ids=list(structure.region.evidence_ids),
            ).model_dump(mode="json", exclude_none=True)
        )
    return VisualStructure.model_validate(payload)


def _fit_linear(ticks: Sequence[tuple[float, float]]) -> tuple[float, float, float]:
    if len(ticks) < 2:
        raise ValueError("linear axis needs at least two ticks")
    positions = [position for position, _value in ticks]
    values = [value for _position, value in ticks]
    if len(set(positions)) < 2:
        raise ValueError("linear axis tick positions are not distinct")
    mean_position = sum(positions) / len(positions)
    mean_value = sum(values) / len(values)
    denominator = sum((position - mean_position) ** 2 for position in positions)
    if denominator <= 0:
        raise ValueError("linear axis fit is degenerate")
    slope = sum(
        (position - mean_position) * (value - mean_value)
        for position, value in ticks
    ) / denominator
    intercept = mean_value - slope * mean_position
    residual = max(
        abs(slope * position + intercept - value) for position, value in ticks
    )
    if not all(math.isfinite(value) for value in (slope, intercept, residual)):
        raise ValueError("linear axis fit is non-finite")
    if abs(slope) < 1e-12:
        raise ValueError("linear axis fit has zero slope")
    return slope, intercept, residual


def _panel_source_map(structure: VisualStructure) -> dict[str, ChartPanel]:
    evidence = {record.id: record for record in structure.evidence}
    result: dict[str, ChartPanel] = {}
    for panel in structure.panels:
        for evidence_id in panel.evidence_ids:
            record = evidence[evidence_id]
            for source_id in record.provenance.source_object_ids:
                if source_id in result and result[source_id].id != panel.id:
                    raise ValueError("chart panel source identity is ambiguous")
                result[source_id] = panel
    return result


def _primitive_source_map(structure: VisualStructure) -> dict[str, VectorPrimitive]:
    inventory = structure.vector_inventory
    if inventory is None:
        raise ValueError("chart structure requires vector inventory")
    result: dict[str, VectorPrimitive] = {}
    for primitive in inventory.primitives:
        if primitive.source_object_id in result:
            raise ValueError("vector primitive source identity is ambiguous")
        result[primitive.source_object_id] = primitive
    return result


def _existing_label_token_map(
    labels: Sequence[VisualLabel],
    evidence: Sequence[VisualEvidence],
) -> dict[str, VisualLabel]:
    evidence_by_id = {record.id: record for record in evidence}
    result: dict[str, VisualLabel] = {}
    for label in labels:
        for evidence_id in label.evidence_ids:
            for token_id in evidence_by_id[evidence_id].provenance.source_token_ids:
                if token_id in result and result[token_id].id != label.id:
                    raise ValueError("OCR token identity maps to multiple labels")
                result[token_id] = label
    return result


def _color_matches(primitive: VectorPrimitive, color: str) -> bool:
    normalized = color.strip().casefold()
    return normalized in {
        value.strip().casefold()
        for value in (primitive.fill, primitive.stroke)
        if value is not None
    }


def structure_vector_chart(
    item: Mapping[str, Any],
    structure: VisualStructure,
    *,
    page_index: int,
    input_kind: str,
) -> VisualStructure:
    """Build supported vector chart structure transactionally.

    On ordinary unsupported or malformed evidence, the complete P05-US02
    structure is returned with a targeted concern. No partial axis, legend, or
    series authority is committed.
    """

    if structure.region.kind != "chart":
        raise ValueError("chart structure requires a chart-owned region")
    if structure.vector_inventory is None:
        return _append_concern(structure, "chart_structure_inventory_unavailable")
    raw = _raw_structure(item)
    if raw is None:
        return _append_concern(structure, "chart_structure_evidence_unavailable")
    try:
        ensure_finite_mapping(raw)
        raw_labels = _sequence(
            raw.get("labels"),
            label="chart labels",
            maximum=_MAX_LABELS,
        )
        raw_axes = _sequence(raw.get("axes"), label="chart axes", maximum=_MAX_AXES)
        raw_legends = _sequence(
            raw.get("legends"),
            label="chart legends",
            maximum=_MAX_LEGENDS,
        )
        raw_series = _sequence(
            raw.get("series"),
            label="chart series",
            maximum=_MAX_SERIES,
        )
        if not raw_axes:
            raise ValueError("chart has no grounded axis evidence")

        region_box = structure.region.page_bbox
        public_item_id = structure.evidence[0].provenance.public_item_id
        normalized_input_kind: Literal["pdf", "image", "unknown"] = (
            input_kind if input_kind in {"pdf", "image"} else "unknown"
        )
        panels_by_source = _panel_source_map(structure)
        primitives_by_source = _primitive_source_map(structure)
        labels = [label.model_copy(deep=True) for label in structure.labels]
        evidence = [record.model_copy(deep=True) for record in structure.evidence]
        labels_by_token = _existing_label_token_map(labels, evidence)
        labels_by_source: dict[str, VisualLabel] = {}

        def add_or_resolve_label(
            raw_label: Mapping[str, Any],
            *,
            required_role: Literal[
                "title",
                "caption",
                "axis_title",
                "tick",
                "category",
                "unit",
                "legend",
                "node",
                "other",
            ]
            | None = None,
        ) -> VisualLabel:
            source_token_id = _text(
                raw_label.get("source_token_id"),
                maximum=128,
            )
            text = _text(raw_label.get("text"))
            role_value = str(raw_label.get("role") or required_role or "other")
            allowed_roles = {
                "title",
                "caption",
                "axis_title",
                "tick",
                "category",
                "unit",
                "legend",
                "node",
                "other",
            }
            if role_value not in allowed_roles:
                raise ValueError("chart label role is unsupported")
            role = required_role or role_value
            if required_role is not None and role_value not in {
                required_role,
                "other",
            }:
                raise ValueError("chart label role conflicts with its use")
            page_bbox = _box(raw_label.get("page_bbox"), unit=region_box.unit)
            existing = labels_by_token.get(source_token_id)
            if existing is not None:
                if existing.text != text:
                    raise ValueError("chart label text differs from OCR evidence")
                if page_bbox is not None and existing.page_bbox is not None:
                    if existing.page_bbox.model_dump() != page_bbox.model_dump():
                        raise ValueError("chart label bbox differs from OCR evidence")
                updated = existing.model_copy(
                    update={"role": role},
                    deep=True,
                )
                labels[labels.index(existing)] = updated
                labels_by_token[source_token_id] = updated
                labels_by_source[source_token_id] = updated
                return updated
            if page_bbox is None:
                raise ValueError("new chart label lacks page geometry")
            evidence_id = _stable_id(
                "visual-evidence",
                structure.region.id,
                "chart-label",
                source_token_id,
                text,
                page_bbox.model_dump(mode="json"),
            )
            label_id = _stable_id(
                "visual-label",
                structure.region.id,
                source_token_id,
                text,
                page_bbox.model_dump(mode="json"),
            )
            evidence.append(
                VisualEvidence(
                    id=evidence_id,
                    kind="label",
                    page_bbox=page_bbox,
                    provenance=VisualProvenance(
                        public_item_id=public_item_id,
                        page_index=page_index,
                        input_kind=normalized_input_kind,
                        source_object_ids=[],
                        source_token_ids=[source_token_id],
                        extraction_method="ocr",
                    ),
                )
            )
            label = VisualLabel(
                id=label_id,
                text=text,
                role=role,  # type: ignore[arg-type]
                page_bbox=page_bbox,
                evidence_ids=[evidence_id],
                occurrence_index=len(labels),
            )
            labels.append(label)
            labels_by_token[source_token_id] = label
            labels_by_source[source_token_id] = label
            return label

        raw_label_by_source: dict[str, Mapping[str, Any]] = {}
        for raw_label in raw_labels:
            if not isinstance(raw_label, Mapping):
                raise ValueError("chart label evidence must be an object")
            source_id = _text(raw_label.get("source_token_id"), maximum=128)
            if source_id in raw_label_by_source:
                raise ValueError("chart label source identity repeats")
            raw_label_by_source[source_id] = raw_label
            add_or_resolve_label(raw_label)

        def resolve_label(
            source_id_value: Any,
            *,
            role: Literal[
                "title",
                "caption",
                "axis_title",
                "tick",
                "category",
                "unit",
                "legend",
                "node",
                "other",
            ],
        ) -> VisualLabel:
            source_id = _text(source_id_value, maximum=128)
            raw_label = raw_label_by_source.get(source_id)
            if raw_label is None:
                raise ValueError("chart label source reference is unknown")
            return add_or_resolve_label(raw_label, required_role=role)

        axes: list[ChartAxis] = []
        axis_source_ids: set[str] = set()
        panel_label_ids: dict[str, set[str]] = {
            panel.id: set(panel.label_ids) for panel in structure.panels
        }
        for raw_axis in raw_axes:
            if not isinstance(raw_axis, Mapping):
                raise ValueError("chart axis evidence must be an object")
            scale = str(raw_axis.get("scale") or "unresolved").casefold()
            if scale in {"log", "dual", "unresolved"}:
                return _append_concern(
                    structure,
                    f"chart_axis_{scale}_unsupported",
                )
            if scale != "linear":
                return _append_concern(structure, "chart_axis_unsupported")
            source_object_id = _text(
                raw_axis.get("source_object_id"),
                maximum=256,
            )
            if source_object_id in axis_source_ids:
                raise ValueError("chart axis source identity repeats")
            axis_source_ids.add(source_object_id)
            panel_source_id = _text(
                raw_axis.get("panel_source_object_id"),
                maximum=256,
            )
            panel = panels_by_source.get(panel_source_id)
            if panel is None:
                raise ValueError("chart axis panel reference is unknown")
            orientation = str(raw_axis.get("orientation") or "").casefold()
            if orientation not in {"x", "y"}:
                raise ValueError("chart axis orientation is unsupported")
            raw_ticks = _sequence(
                raw_axis.get("ticks"),
                label="chart ticks",
                maximum=_MAX_TICKS,
            )
            if len(raw_ticks) < 2:
                raise ValueError("linear chart axis has too few ticks")
            ticks: list[ChartTick] = []
            tick_fit: list[tuple[float, float]] = []
            tick_evidence_ids: list[str] = []
            for tick_index, raw_tick in enumerate(raw_ticks):
                if not isinstance(raw_tick, Mapping):
                    raise ValueError("chart tick evidence must be an object")
                label = resolve_label(
                    raw_tick.get("source_token_id"),
                    role=("category" if orientation == "x" else "tick"),
                )
                position = _number(raw_tick.get("position"))
                value = _number(raw_tick.get("value"))
                tick_fit.append((position, value))
                tick_bbox = _box(raw_tick.get("page_bbox"), unit=region_box.unit)
                evidence_id = _stable_id(
                    "visual-evidence",
                    structure.region.id,
                    "tick",
                    source_object_id,
                    tick_index,
                    label.id,
                    position,
                    value,
                )
                evidence.append(
                    VisualEvidence(
                        id=evidence_id,
                        kind="tick",
                        page_bbox=tick_bbox or label.page_bbox,
                        provenance=VisualProvenance(
                            public_item_id=public_item_id,
                            page_index=page_index,
                            input_kind=normalized_input_kind,
                            source_object_ids=[source_object_id],
                            source_token_ids=[
                                _text(
                                    raw_tick.get("source_token_id"),
                                    maximum=128,
                                )
                            ],
                            extraction_method="vector",
                        ),
                    )
                )
                tick_evidence_ids.append(evidence_id)
                ticks.append(
                    ChartTick(
                        id=_stable_id(
                            "chart-tick",
                            structure.region.id,
                            source_object_id,
                            tick_index,
                            label.id,
                            position,
                            value,
                        ),
                        value=value,
                        position=position,
                        label_id=label.id,
                        evidence_ids=[evidence_id],
                    )
                )
                panel_label_ids[panel.id].add(label.id)
            slope, intercept, residual = _fit_linear(tick_fit)
            tolerance = _number(raw_axis.get("calibration_tolerance", 0.5))
            if tolerance < 0 or residual > tolerance + 1e-9:
                return _append_concern(
                    structure,
                    "chart_axis_calibration_residual_exceeded",
                )
            axis_bbox = _box(raw_axis.get("page_bbox"), unit=region_box.unit)
            axis_evidence_id = _stable_id(
                "visual-evidence",
                structure.region.id,
                "axis",
                source_object_id,
                panel.id,
                orientation,
            )
            evidence.append(
                VisualEvidence(
                    id=axis_evidence_id,
                    kind="axis",
                    page_bbox=axis_bbox or panel.page_bbox,
                    provenance=VisualProvenance(
                        public_item_id=public_item_id,
                        page_index=page_index,
                        input_kind=normalized_input_kind,
                        source_object_ids=[source_object_id],
                        source_token_ids=[],
                        extraction_method="vector",
                    ),
                )
            )
            categories: list[str] = []
            for source_id in _sequence(
                raw_axis.get("category_label_source_token_ids"),
                label="axis category references",
                maximum=_MAX_LABELS,
            ):
                label = resolve_label(source_id, role="category")
                categories.append(label.id)
                panel_label_ids[panel.id].add(label.id)
            unit_label: VisualLabel | None = None
            if raw_axis.get("unit_label_source_token_id") is not None:
                unit_label = resolve_label(
                    raw_axis.get("unit_label_source_token_id"),
                    role="unit",
                )
                panel_label_ids[panel.id].add(unit_label.id)
            values = [tick.value for tick in ticks]
            minimum = _number(raw_axis.get("minimum", min(values)))
            maximum = _number(raw_axis.get("maximum", max(values)))
            if maximum <= minimum:
                raise ValueError("linear chart axis range does not increase")
            axes.append(
                ChartAxis(
                    id=_stable_id(
                        "chart-axis",
                        structure.region.id,
                        source_object_id,
                        panel.id,
                        orientation,
                        slope,
                        intercept,
                    ),
                    panel_id=panel.id,
                    orientation=orientation,  # type: ignore[arg-type]
                    scale="linear",
                    minimum=minimum,
                    maximum=maximum,
                    slope=slope,
                    intercept=intercept,
                    residual=residual,
                    calibration_tolerance=tolerance,
                    baseline_position=(
                        _number(raw_axis.get("baseline_position"))
                        if raw_axis.get("baseline_position") is not None
                        else None
                    ),
                    unit_label_id=(unit_label.id if unit_label is not None else None),
                    ticks=ticks,
                    category_label_ids=categories,
                    evidence_ids=[axis_evidence_id],
                    calibration_evidence_ids=[axis_evidence_id, *tick_evidence_ids],
                )
            )

        legends: list[ChartLegend] = []
        legend_entries_by_source: dict[str, ChartLegendEntry] = {}
        for raw_legend in raw_legends:
            if not isinstance(raw_legend, Mapping):
                raise ValueError("chart legend evidence must be an object")
            source_object_id = _text(
                raw_legend.get("source_object_id"),
                maximum=256,
            )
            panel: ChartPanel | None = None
            if raw_legend.get("panel_source_object_id") is not None:
                panel = panels_by_source.get(
                    _text(
                        raw_legend.get("panel_source_object_id"),
                        maximum=256,
                    )
                )
                if panel is None:
                    raise ValueError("chart legend panel reference is unknown")
            raw_entries = _sequence(
                raw_legend.get("entries"),
                label="legend entries",
                maximum=_MAX_LEGEND_ENTRIES,
            )
            if not raw_entries:
                raise ValueError("chart legend has no grounded entries")
            entries: list[ChartLegendEntry] = []
            swatch_evidence_ids: list[str] = []
            for raw_entry in raw_entries:
                if not isinstance(raw_entry, Mapping):
                    raise ValueError("legend entry evidence must be an object")
                entry_source_id = _text(
                    raw_entry.get("source_object_id"),
                    maximum=256,
                )
                if entry_source_id in legend_entries_by_source:
                    raise ValueError("legend entry source identity repeats")
                label = resolve_label(
                    raw_entry.get("label_source_token_id"),
                    role="legend",
                )
                swatch_source_id = _text(
                    raw_entry.get("swatch_source_object_id"),
                    maximum=256,
                )
                primitive = primitives_by_source.get(swatch_source_id)
                color = _text(raw_entry.get("color"), maximum=64).casefold()
                if (
                    primitive is None
                    or not primitive.supported
                    or not _color_matches(primitive, color)
                ):
                    return _append_concern(
                        structure,
                        "chart_legend_swatch_ambiguous",
                    )
                swatch_evidence_id = _stable_id(
                    "visual-evidence",
                    structure.region.id,
                    "swatch",
                    swatch_source_id,
                    color,
                )
                evidence.append(
                    VisualEvidence(
                        id=swatch_evidence_id,
                        kind="swatch",
                        page_bbox=primitive.page_bbox,
                        chart_local_bbox=primitive.chart_local_bbox,
                        transform_ids=list(primitive.transform_ids),
                        provenance=VisualProvenance(
                            public_item_id=public_item_id,
                            page_index=page_index,
                            input_kind=normalized_input_kind,
                            source_object_ids=[swatch_source_id],
                            source_token_ids=[],
                            extraction_method="vector",
                        ),
                    )
                )
                entry = ChartLegendEntry(
                    id=_stable_id(
                        "chart-legend-entry",
                        structure.region.id,
                        entry_source_id,
                        label.id,
                        swatch_source_id,
                        color,
                    ),
                    label_id=label.id,
                    swatch_evidence_id=swatch_evidence_id,
                    color=color,
                    evidence_ids=[*label.evidence_ids, swatch_evidence_id],
                )
                entries.append(entry)
                legend_entries_by_source[entry_source_id] = entry
                swatch_evidence_ids.append(swatch_evidence_id)
                if panel is not None:
                    panel_label_ids[panel.id].add(label.id)
            legend_evidence_id = _stable_id(
                "visual-evidence",
                structure.region.id,
                "legend",
                source_object_id,
            )
            evidence.append(
                VisualEvidence(
                    id=legend_evidence_id,
                    kind="legend",
                    page_bbox=(panel.page_bbox if panel is not None else region_box),
                    provenance=VisualProvenance(
                        public_item_id=public_item_id,
                        page_index=page_index,
                        input_kind=normalized_input_kind,
                        source_object_ids=[source_object_id],
                        source_token_ids=[],
                        extraction_method="vector",
                    ),
                )
            )
            legends.append(
                ChartLegend(
                    id=_stable_id(
                        "chart-legend",
                        structure.region.id,
                        source_object_id,
                        [entry.id for entry in entries],
                    ),
                    panel_id=(panel.id if panel is not None else None),
                    entries=entries,
                    evidence_ids=[legend_evidence_id, *swatch_evidence_ids],
                )
            )

        series: list[ChartSeries] = []
        for raw_value in raw_series:
            if not isinstance(raw_value, Mapping):
                raise ValueError("chart series evidence must be an object")
            source_object_id = _text(
                raw_value.get("source_object_id"),
                maximum=256,
            )
            label = resolve_label(
                raw_value.get("label_source_token_id"),
                role="legend",
            )
            legend_entry_source_id = _text(
                raw_value.get("legend_entry_source_object_id"),
                maximum=256,
            )
            legend_entry = legend_entries_by_source.get(legend_entry_source_id)
            color = _text(raw_value.get("color"), maximum=64).casefold()
            if (
                legend_entry is None
                or legend_entry.label_id != label.id
                or legend_entry.color != color
            ):
                return _append_concern(
                    structure,
                    "chart_series_legend_ambiguous",
                )
            panel_ids: list[str] = []
            for panel_source_id in _sequence(
                raw_value.get("panel_source_object_ids"),
                label="series panel references",
                maximum=_MAX_PANELS,
            ):
                panel = panels_by_source.get(_text(panel_source_id, maximum=256))
                if panel is None or panel.id in panel_ids:
                    raise ValueError("series panel reference is unknown or repeated")
                panel_ids.append(panel.id)
                panel_label_ids[panel.id].add(label.id)
            if not panel_ids:
                raise ValueError("chart series has no panel ownership")
            series_evidence_ids = [legend_entry.swatch_evidence_id]
            for evidence_source_id in _sequence(
                raw_value.get("evidence_source_object_ids"),
                label="series evidence references",
                maximum=64,
            ):
                primitive = primitives_by_source.get(
                    _text(evidence_source_id, maximum=256)
                )
                if (
                    primitive is None
                    or not primitive.supported
                    or not _color_matches(primitive, color)
                ):
                    return _append_concern(
                        structure,
                        "chart_series_geometry_ambiguous",
                    )
                for evidence_id in primitive.evidence_ids:
                    if evidence_id not in series_evidence_ids:
                        series_evidence_ids.append(evidence_id)
            series.append(
                ChartSeries(
                    id=_stable_id(
                        "chart-series",
                        structure.region.id,
                        source_object_id,
                        legend_entry.id,
                        color,
                        panel_ids,
                    ),
                    source_object_id=source_object_id,
                    label_id=label.id,
                    color=color,
                    legend_entry_id=legend_entry.id,
                    panel_ids=panel_ids,
                    evidence_ids=series_evidence_ids,
                )
            )

        if raw_legends and not series:
            return _append_concern(structure, "chart_series_unresolved")
        panels = [
            panel.model_copy(
                update={"label_ids": sorted(panel_label_ids[panel.id])},
                deep=True,
            )
            for panel in structure.panels
        ]
        # Re-sequence occurrences after any existing label was role-updated.
        labels = [
            label.model_copy(update={"occurrence_index": index}, deep=True)
            for index, label in enumerate(labels)
        ]
        # Updated label objects receive the same IDs, so all references remain
        # valid after resequencing.
        payload = structure.model_dump(mode="json", exclude_none=True)
        payload["labels"] = [
            label.model_dump(mode="json", exclude_none=True) for label in labels
        ]
        payload["axes"] = [
            axis.model_dump(mode="json", exclude_none=True) for axis in axes
        ]
        payload["legends"] = [
            legend.model_dump(mode="json", exclude_none=True) for legend in legends
        ]
        payload["panels"] = [
            panel.model_dump(mode="json", exclude_none=True) for panel in panels
        ]
        payload["series"] = [
            value.model_dump(mode="json", exclude_none=True) for value in series
        ]
        payload["points"] = []
        payload["evidence"] = [
            record.model_dump(mode="json", exclude_none=True) for record in evidence
        ]
        return VisualStructure.model_validate(payload)
    except (MemoryError, TypeError, ValueError):
        return _append_concern(structure, "chart_structure_malformed_evidence")


__all__ = ["structure_vector_chart"]
