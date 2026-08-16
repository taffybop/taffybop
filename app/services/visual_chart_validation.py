"""Validate chart candidates and build the authoritative chart projection.

P05-US04 and the later raster stages produce evidence-grounded candidates.
This module is the shared admission boundary for those candidates: it never
measures, corrects, or guesses a value.  A point is either supported by its
own evidence and uncertainty or is withheld before public projection.
"""

from __future__ import annotations

import math
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from app.services.visual_contracts import (
    ChartAxis,
    ChartPoint,
    ChartSeries,
    VisualConcern,
    VisualFallback,
    VisualLabel,
    VisualSerialization,
    VisualStructure,
)


_MAX_MARKDOWN_BYTES = 262_144
_OBSOLETE_SUCCESS_CONCERNS = frozenset(
    {
        "chart_structure_unresolved",
        "vector_bar_values_withheld",
    }
)


def validate_and_serialize_office_chart(structure: Any) -> Any:
    """Apply the P05 native-evidence admission rules to an Office chart.

    Office XML has exact values and source locators but no honest rendered
    mark/baseline geometry, so it cannot be forced into the measured-chart
    ``VisualStructure`` shape.  This sibling admission path enforces the same
    closed, finite, source-grounded, rectangular and serializer-owned rules
    without fabricating visual evidence.
    """

    from app.services.office_charts import OfficeChartStructure

    primitive = (
        structure.model_dump(mode="json")
        if isinstance(structure, OfficeChartStructure)
        else structure
    )
    validated = OfficeChartStructure.model_validate(primitive, strict=True)
    provenance = dict(validated.provenance)
    if (
        provenance.get("method") != "native_xml"
        or provenance.get("chart_part") is None
        or provenance.get("formulas_executed") is not False
        or provenance.get("external_content_fetched") is not False
        or provenance.get("source_precedence")
        != ["cell_data", "embedded_data", "cached_data"]
    ):
        raise ValueError("Office chart provenance differs")
    chart_part = str(provenance["chart_part"])
    if any(
        point.chart_part != chart_part
        or not point.source_locator.strip()
        or point.method not in {"cell_data", "embedded_data", "cached_data"}
        for point in validated.points
    ):
        raise ValueError("Office chart point grounding differs")

    lines: list[str] = []
    if validated.title:
        lines.extend((_markdown_text(validated.title), ""))
    lines.extend(
        (
            "| Category | Series | Value | Method |",
            "| --- | --- | ---: | --- |",
        )
    )
    for point in validated.points:
        lines.append(
            "| "
            + " | ".join(
                (
                    _markdown_text(point.category),
                    _markdown_text(point.series),
                    _markdown_text(point.display_value),
                    point.method,
                )
            )
            + " |"
        )
    markdown = "\n".join(lines) + "\n"
    if len(markdown.encode("utf-8")) > _MAX_MARKDOWN_BYTES:
        raise ValueError("structured Office chart Markdown exceeds its public limit")
    provenance["validation_contract"] = "p05-chart-validation-v1"
    return validated.model_copy(
        update={"markdown": markdown, "provenance": provenance}
    )


def _markdown_text(value: str) -> str:
    """Escape one bounded public value for a Markdown table cell."""

    return (
        value.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r\n", "<br>")
        .replace("\r", "<br>")
        .replace("\n", "<br>")
        .strip()
    )


def _number_text(value: float) -> str:
    if value == 0:
        return "0"
    return format(value, ".15g")


def _caption(item: Mapping[str, Any], structure: VisualStructure) -> str | None:
    raw_caption = item.get("caption")
    if isinstance(raw_caption, str):
        value = raw_caption.strip()
        if value:
            return value[:16_384]
    for label in structure.labels:
        if label.role == "caption" and label.text.strip():
            return label.text.strip()
    return None


def _point_order(
    structure: VisualStructure,
    points: Sequence[ChartPoint],
) -> list[ChartPoint]:
    panel_order = {panel.id: index for index, panel in enumerate(structure.panels)}
    label_order = {
        label.id: (label.occurrence_index, label.id) for label in structure.labels
    }
    series_order = {series.id: index for index, series in enumerate(structure.series)}
    return sorted(
        points,
        key=lambda point: (
            panel_order.get(point.panel_id, len(panel_order)),
            label_order.get(point.category_label_id, (1_000_000, point.category_label_id)),
            series_order.get(point.series_id, len(series_order)),
            point.stack_index if point.stack_index is not None else -1,
            point.id,
        ),
    )


def _build_markdown(
    item: Mapping[str, Any],
    structure: VisualStructure,
    points: Sequence[ChartPoint],
) -> tuple[str, int]:
    labels = {label.id: label for label in structure.labels}
    series = {value.id: value for value in structure.series}
    caption = _caption(item, structure)
    lines: list[str] = []
    if caption is not None:
        lines.extend((_markdown_text(caption), ""))
    lines.extend(
        (
            "| Category | Series | Value | Method | Tolerance |",
            "| --- | --- | ---: | --- | ---: |",
        )
    )
    for point in _point_order(structure, points):
        category = labels[point.category_label_id].text
        chart_series = series[point.series_id]
        series_label = (
            labels[chart_series.label_id].text
            if chart_series.label_id is not None
            else chart_series.source_object_id
        )
        lines.append(
            "| "
            + " | ".join(
                (
                    _markdown_text(category),
                    _markdown_text(series_label),
                    _markdown_text(point.display_value),
                    point.method,
                    f"±{_number_text(point.tolerance.absolute)}",
                )
            )
            + " |"
        )
    markdown = "\n".join(lines) + "\n"
    if len(markdown.encode("utf-8")) > _MAX_MARKDOWN_BYTES:
        raise ValueError("structured chart Markdown exceeds its public limit")
    return markdown, 1 if caption is not None else 0


def _normalized_semantic(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return " ".join(normalized.split())


def _point_issues(
    point: ChartPoint,
    *,
    axes: Mapping[str, ChartAxis],
    labels: Mapping[str, VisualLabel],
    series: Mapping[str, ChartSeries],
    evidence_kinds: Mapping[str, str],
    evidence_methods: Mapping[str, str],
    evidence_source_tokens: Mapping[str, tuple[str, ...]],
    primitive_evidence: Mapping[str, frozenset[str]],
) -> set[str]:
    issues: set[str] = set()
    point_axes = [axes[axis_id] for axis_id in point.axis_ids]
    value_axes = [axis for axis in point_axes if axis.orientation == "y"]
    if len(value_axes) != 1:
        issues.add("chart_point_axis_range_invalid")
    else:
        axis = value_axes[0]
        if (
            axis.scale != "linear"
            or axis.minimum is None
            or axis.maximum is None
            or point.raw_value < axis.minimum - point.tolerance.lower
            or point.raw_value > axis.maximum + point.tolerance.upper
        ):
            issues.add("chart_point_axis_range_invalid")

    if not point.confidence.complete_for_value():
        issues.add("chart_point_confidence_incomplete")
    confidence_values = (
        point.confidence.geometry,
        point.confidence.calibration,
        point.confidence.category,
        point.confidence.series,
        point.confidence.value,
    )
    if any(
        value is None or not math.isfinite(value) or not 0.0 <= value <= 1.0
        for value in confidence_values
    ):
        issues.add("chart_point_confidence_incomplete")

    if (
        not math.isfinite(point.tolerance.absolute)
        or not math.isfinite(point.tolerance.lower)
        or not math.isfinite(point.tolerance.upper)
        or point.tolerance.absolute + 1e-12
        < max(point.tolerance.lower, point.tolerance.upper)
    ):
        issues.add("chart_point_tolerance_invalid")

    point_evidence = set(point.evidence_ids)
    required_evidence = {
        point.point_evidence_id,
        point.baseline_evidence_id,
        *point.source_geometry_evidence_ids,
        *labels[point.category_label_id].evidence_ids,
        *series[point.series_id].evidence_ids,
    }
    for axis in point_axes:
        required_evidence.update(axis.evidence_ids)
        required_evidence.update(axis.calibration_evidence_ids)
    if not required_evidence <= point_evidence:
        issues.add("chart_point_evidence_incomplete")
    if (
        evidence_kinds.get(point.point_evidence_id) != "point"
        or evidence_kinds.get(point.baseline_evidence_id) != "baseline"
        or point.baseline_evidence_id not in point.source_geometry_evidence_ids
    ):
        issues.add("chart_point_evidence_incomplete")

    geometry_evidence = set(point.source_geometry_evidence_ids)
    if point.mark_id is not None:
        if point.mark_id in primitive_evidence:
            if not primitive_evidence[point.mark_id] <= geometry_evidence:
                issues.add("chart_point_evidence_incomplete")
        elif (
            evidence_kinds.get(point.mark_id) != "mark"
            or point.mark_id not in geometry_evidence
        ):
            issues.add("chart_point_evidence_incomplete")
    if point.path_id is not None and (
        evidence_kinds.get(point.path_id) != "path"
        or point.path_id not in geometry_evidence
    ):
        issues.add("chart_point_evidence_incomplete")

    point_method = evidence_methods.get(point.point_evidence_id)
    if point.method == "explicit_text":
        if (
            point_method != "explicit_text"
            or not evidence_source_tokens.get(point.point_evidence_id)
            or point.tolerance.basis not in {"explicit_rounding", "combined"}
        ):
            issues.add("chart_point_method_invalid")
    elif point.method == "vector_measured":
        if (
            point_method != "vector"
            or point.mark_id not in primitive_evidence
            or point.tolerance.basis
            not in {"vector_geometry", "axis_residual", "combined"}
        ):
            issues.add("chart_point_method_invalid")
    elif point.method == "raster_measured":
        if (
            point_method != "raster"
            or point.tolerance.basis not in {"raster_pixels", "combined"}
        ):
            issues.add("chart_point_method_invalid")
    else:  # pragma: no cover - the closed contract rejects this first.
        issues.add("chart_point_method_invalid")
    return issues


def _invalid_stacks(
    points: Sequence[ChartPoint],
    *,
    axes: Mapping[str, ChartAxis],
    already_invalid: set[str],
) -> set[str]:
    groups: dict[tuple[str, str, str], list[ChartPoint]] = defaultdict(list)
    for point in points:
        if point.stack_id is not None:
            groups[(point.panel_id, point.category_label_id, point.stack_id)].append(
                point
            )
    invalid: set[str] = set()
    for members in groups.values():
        ordered = sorted(members, key=lambda point: point.stack_index or 0)
        shared_axes = {tuple(point.axis_ids) for point in ordered}
        value_axes = [
            axes[axis_id]
            for axis_id in ordered[0].axis_ids
            if axes[axis_id].orientation == "y"
        ]
        tolerances = sum(point.tolerance.absolute for point in ordered)
        stack_total = sum(point.raw_value for point in ordered)
        range_valid = False
        if len(value_axes) == 1:
            axis = value_axes[0]
            if axis.minimum is not None and axis.maximum is not None:
                range_valid = (
                    stack_total >= -tolerances
                    and stack_total
                    <= (axis.maximum - axis.minimum) + tolerances
                )
        valid = (
            len(ordered) >= 2
            and not any(point.id in already_invalid for point in ordered)
            and len(shared_axes) == 1
            and len({point.series_id for point in ordered}) == len(ordered)
            and [point.stack_index for point in ordered] == list(range(len(ordered)))
            and range_valid
        )
        if not valid:
            invalid.update(point.id for point in ordered)
    return invalid


def _invalid_series_relations(
    points: Sequence[ChartPoint],
    *,
    labels: Mapping[str, VisualLabel],
    series: Mapping[str, ChartSeries],
    already_invalid: set[str],
) -> set[str]:
    semantic_by_series: dict[str, str] = {}
    for series_id, value in series.items():
        if value.label_id is not None:
            semantic_by_series[series_id] = _normalized_semantic(
                labels[value.label_id].text
            )

    grouped: dict[tuple[str, str], list[ChartPoint]] = defaultdict(list)
    for point in points:
        if point.id not in already_invalid:
            grouped[(point.panel_id, point.category_label_id)].append(point)

    invalid: set[str] = set()
    for members in grouped.values():
        first_half = [
            point
            for point in members
            if semantic_by_series.get(point.series_id) == "1h"
        ]
        annual = [
            point
            for point in members
            if semantic_by_series.get(point.series_id) == "annual total"
        ]
        if not first_half or not annual:
            continue
        if len(first_half) != 1 or len(annual) != 1:
            invalid.update(point.id for point in (*first_half, *annual))
            continue
        first_half_point = first_half[0]
        annual_point = annual[0]
        if (
            annual_point.raw_value + annual_point.tolerance.upper
            < first_half_point.raw_value - first_half_point.tolerance.lower
        ):
            # Do not rewrite an impossible annual total.  The grounded 1H
            # point remains useful; only the contradicted annual point is
            # withheld.
            invalid.add(annual_point.id)
    return invalid


def _append_concerns(
    payload: dict[str, Any],
    structure: VisualStructure,
    concerns: Sequence[tuple[str, Sequence[str]]],
) -> None:
    target = payload.setdefault("concerns", [])
    existing = {str(value.get("code")) for value in target}
    allowed_evidence = {record.id for record in structure.evidence}
    for code, raw_evidence_ids in concerns:
        if code in existing or len(target) >= 256:
            continue
        evidence_ids = [
            evidence_id
            for evidence_id in dict.fromkeys(raw_evidence_ids)
            if evidence_id in allowed_evidence
        ][:64]
        target.append(
            VisualConcern(
                code=code,
                stage="validation",
                evidence_ids=(
                    evidence_ids
                    if evidence_ids
                    else list(structure.region.evidence_ids)
                ),
            ).model_dump(mode="json", exclude_none=True)
        )
        existing.add(code)


def _fallback_result(
    item: Mapping[str, Any],
    structure: VisualStructure,
    *,
    points: Sequence[ChartPoint],
    concerns: Sequence[tuple[str, Sequence[str]]],
) -> VisualStructure:
    payload = structure.model_dump(mode="json", exclude_none=True)
    payload["points"] = [
        point.model_dump(mode="json", exclude_none=True) for point in points
    ]
    payload["fallback"] = VisualFallback(
        active=True,
        reason="validation_failed",
        predecessor_concern="chart_values_not_structured",
    ).model_dump(mode="json", exclude_none=True)
    predecessor_markdown = ""
    if structure.serialization is not None and structure.serialization.status == "fallback":
        predecessor_markdown = structure.serialization.markdown
    elif isinstance(item.get("md"), str):
        predecessor_markdown = item["md"]
    elif isinstance(item.get("value"), str):
        predecessor_markdown = item["value"]
    caption = _caption(item, structure)
    payload["serialization"] = VisualSerialization(
        status="fallback",
        markdown=predecessor_markdown,
        caption_occurrences=(
            1
            if caption is not None and caption in predecessor_markdown
            else 0
        ),
        row_count=0,
    ).model_dump(mode="json", exclude_none=True)
    _append_concerns(payload, structure, concerns)
    return VisualStructure.model_validate(payload)


def validate_and_serialize_chart(
    item: Mapping[str, Any],
    structure: VisualStructure,
) -> VisualStructure:
    """Withhold unsupported points and serialize the surviving chart once."""

    if structure.region.kind != "chart":
        raise ValueError("structured chart projection requires a chart")

    axes = {axis.id: axis for axis in structure.axes}
    labels = {label.id: label for label in structure.labels}
    series = {value.id: value for value in structure.series}
    evidence_kinds = {record.id: record.kind for record in structure.evidence}
    evidence_methods = {
        record.id: record.provenance.extraction_method
        for record in structure.evidence
    }
    evidence_source_tokens = {
        record.id: tuple(record.provenance.source_token_ids)
        for record in structure.evidence
    }
    primitive_evidence = {
        primitive.id: frozenset(primitive.evidence_ids)
        for primitive in (
            structure.vector_inventory.primitives
            if structure.vector_inventory is not None
            else ()
        )
    }

    invalid: set[str] = set()
    concern_evidence: dict[str, list[str]] = defaultdict(list)
    for point in structure.points:
        for issue in _point_issues(
            point,
            axes=axes,
            labels=labels,
            series=series,
            evidence_kinds=evidence_kinds,
            evidence_methods=evidence_methods,
            evidence_source_tokens=evidence_source_tokens,
            primitive_evidence=primitive_evidence,
        ):
            invalid.add(point.id)
            concern_evidence[issue].append(point.point_evidence_id)

    invalid_relations = _invalid_series_relations(
        structure.points,
        labels=labels,
        series=series,
        already_invalid=invalid,
    )
    invalid.update(invalid_relations)
    concern_evidence["chart_series_relation_invalid"].extend(
        point.point_evidence_id
        for point in structure.points
        if point.id in invalid_relations
    )

    # Run stack admission after every point/series check.  Removing one
    # contradicted segment must not leave a partial stack carrying authority.
    invalid_stacks = _invalid_stacks(
        structure.points,
        axes=axes,
        already_invalid=invalid,
    )
    invalid.update(invalid_stacks)
    concern_evidence["chart_stack_constraint_failed"].extend(
        point.point_evidence_id
        for point in structure.points
        if point.id in invalid_stacks
    )

    valid_points = [point for point in structure.points if point.id not in invalid]
    concerns = [
        (code, evidence_ids)
        for code, evidence_ids in sorted(concern_evidence.items())
        if evidence_ids
    ]
    if not valid_points:
        concerns.append(
            (
                "chart_values_validation_withheld",
                [
                    point.point_evidence_id for point in structure.points
                ] or list(structure.region.evidence_ids),
            )
        )
        return _fallback_result(
            item,
            structure,
            points=(),
            concerns=concerns,
        )

    try:
        markdown, caption_occurrences = _build_markdown(
            item,
            structure,
            valid_points,
        )
        payload = structure.model_dump(mode="json", exclude_none=True)
        payload["points"] = [
            point.model_dump(mode="json", exclude_none=True)
            for point in valid_points
        ]
        payload["concerns"] = [
            concern
            for concern in payload.get("concerns", [])
            if concern.get("code") not in _OBSOLETE_SUCCESS_CONCERNS
        ]
        _append_concerns(payload, structure, concerns)
        payload["fallback"] = VisualFallback(
            active=False,
            reason="none",
            predecessor_concern="chart_values_not_structured",
        ).model_dump(mode="json", exclude_none=True)
        payload["serialization"] = VisualSerialization(
            status="structured_chart",
            markdown=markdown,
            caption_occurrences=caption_occurrences,
            row_count=len(valid_points),
        ).model_dump(mode="json", exclude_none=True)
        return VisualStructure.model_validate(payload)
    except (MemoryError, TypeError, ValueError):
        # Preserve the validated predecessor atomically; never leak a partly
        # built projection or a guessed replacement value.
        return _fallback_result(
            item,
            structure,
            points=structure.points,
            concerns=[
                (
                    "chart_serialization_failed_closed",
                    list(structure.region.evidence_ids),
                )
            ],
        )


__all__ = ["validate_and_serialize_chart"]
