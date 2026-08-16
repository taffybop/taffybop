"""Closed public contracts for default-off Phase 05 visual semantics.

The rest of the public response remains intentionally additive.  Once the
``visual_structure`` sidecar is present, however, this module makes its shape
closed, bounded, finite, and reference checked so a malformed analyzer result
cannot leak partial authority into a parse response.
"""

from __future__ import annotations

import math
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_MAX_REFERENCES = 64
_MAX_EVIDENCE = 2_048
_MAX_LABELS = 512
_MAX_PRIMITIVES = 2_048
_MAX_POINTS = 1_024
_MAX_NODES = 512
_MAX_CONNECTORS = 1_024

FiniteNumber = Annotated[float, Field(allow_inf_nan=False)]
ConfidenceNumber = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]


class VisualContract(BaseModel):
    """Strict, non-coercing base for Phase 05 public data."""

    model_config = ConfigDict(extra="forbid", strict=True)

    @model_validator(mode="before")
    @classmethod
    def require_plain_object(cls, value: Any) -> Any:
        if type(value) is cls:
            return value
        if type(value) is not dict:
            raise ValueError("visual structure values must be exact objects")
        return value


class VisualBoundingBox(VisualContract):
    x: FiniteNumber = Field(ge=0.0)
    y: FiniteNumber = Field(ge=0.0)
    width: FiniteNumber = Field(ge=0.0)
    height: FiniteNumber = Field(ge=0.0)
    unit: Literal["pt", "px"]


class VisualTransform(VisualContract):
    """Affine source-to-target transform in PDF/Pillow order."""

    id: str = Field(pattern=_ID_RE.pattern)
    source_space: Literal["page", "chart_local", "raster_pixel"]
    target_space: Literal["page", "chart_local", "raster_pixel"]
    matrix: list[FiniteNumber] = Field(min_length=6, max_length=6)
    source_transform_ids: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_transform(self) -> VisualTransform:
        a, b, c, d, _e, _f = self.matrix
        if self.source_space == self.target_space and tuple(self.matrix) != (
            1.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
        ):
            raise ValueError("same-space visual transform must be identity")
        if self.source_space != self.target_space and abs(a * d - b * c) < 1e-12:
            raise ValueError("visual transform must be invertible")
        return self


class VisualConfidenceDimensions(VisualContract):
    geometry: ConfidenceNumber | None = None
    calibration: ConfidenceNumber | None = None
    category: ConfidenceNumber | None = None
    series: ConfidenceNumber | None = None
    value: ConfidenceNumber | None = None
    direction: ConfidenceNumber | None = None

    def complete_for_value(self) -> bool:
        return all(
            value is not None
            for value in (
                self.geometry,
                self.calibration,
                self.category,
                self.series,
                self.value,
            )
        )


class NumericTolerance(VisualContract):
    absolute: FiniteNumber = Field(ge=0.0)
    lower: FiniteNumber = Field(ge=0.0)
    upper: FiniteNumber = Field(ge=0.0)
    basis: Literal[
        "explicit_rounding",
        "vector_geometry",
        "raster_pixels",
        "axis_residual",
        "combined",
    ]

    @model_validator(mode="after")
    def validate_bounds(self) -> NumericTolerance:
        if self.absolute + 1e-12 < max(self.lower, self.upper):
            raise ValueError("absolute tolerance must cover both bounds")
        return self


class VisualProvenance(VisualContract):
    public_item_id: str = Field(min_length=1, max_length=128)
    page_index: int = Field(ge=1, le=1_000_000)
    input_kind: Literal["pdf", "image", "unknown"]
    source_object_ids: list[str] = Field(
        default_factory=list,
        max_length=_MAX_REFERENCES,
    )
    source_token_ids: list[str] = Field(
        default_factory=list,
        max_length=_MAX_REFERENCES,
    )
    extraction_method: Literal[
        "layout",
        "ocr",
        "vector",
        "raster",
        "explicit_text",
    ]

    @model_validator(mode="after")
    def validate_identifiers(self) -> VisualProvenance:
        for values, label in (
            (self.source_object_ids, "source object"),
            (self.source_token_ids, "source token"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {label} identifiers")
            if values != sorted(values):
                raise ValueError(f"{label} identifiers must be sorted")
        return self


class VisualEvidence(VisualContract):
    id: str = Field(pattern=_ID_RE.pattern)
    kind: Literal[
        "region",
        "label",
        "axis",
        "tick",
        "legend",
        "swatch",
        "panel",
        "mark",
        "path",
        "point",
        "baseline",
        "node",
        "connector",
        "source_object",
        "ocr_token",
    ]
    page_bbox: VisualBoundingBox | None = None
    chart_local_bbox: VisualBoundingBox | None = None
    raster_pixel_bbox: VisualBoundingBox | None = None
    transform_ids: list[str] = Field(default_factory=list, max_length=8)
    provenance: VisualProvenance

    @model_validator(mode="after")
    def require_grounding(self) -> VisualEvidence:
        if not any(
            (
                self.page_bbox,
                self.chart_local_bbox,
                self.raster_pixel_bbox,
                self.provenance.source_object_ids,
                self.provenance.source_token_ids,
            )
        ):
            raise ValueError("visual evidence has no source grounding")
        return self


class VisualConcern(VisualContract):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{2,95}$")
    severity: Literal["info", "warning", "error"] = "warning"
    stage: Literal[
        "schema",
        "vector_inventory",
        "chart_structure",
        "vector_values",
        "validation",
        "raster_structure",
        "raster_bars",
        "raster_lines",
        "raster_gate",
        "diagram_topology",
    ]
    evidence_ids: list[str] = Field(default_factory=list, max_length=_MAX_REFERENCES)


class VisualRegion(VisualContract):
    id: str = Field(pattern=_ID_RE.pattern)
    kind: Literal["chart", "diagram"]
    page_bbox: VisualBoundingBox
    evidence_ids: list[str] = Field(min_length=1, max_length=_MAX_REFERENCES)


class VisualLabel(VisualContract):
    id: str = Field(pattern=_ID_RE.pattern)
    text: str = Field(min_length=1, max_length=1_024)
    role: Literal[
        "title",
        "caption",
        "axis_title",
        "tick",
        "category",
        "unit",
        "legend",
        "node",
        "node_detail",
        "connector",
        "other",
    ]
    page_bbox: VisualBoundingBox | None = None
    raster_pixel_bbox: VisualBoundingBox | None = None
    evidence_ids: list[str] = Field(min_length=1, max_length=_MAX_REFERENCES)
    occurrence_index: int = Field(ge=0, le=_MAX_LABELS)

    @field_validator("text", mode="before")
    @classmethod
    def validate_safe_text(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        value = value.replace("\r\n", "\n").replace("\r", "\n")
        if (
            len(value) > 1_024
            or any(ord(character) < 0x20 and character != "\n" for character in value)
            or any(
                character in value
                for character in (
                    "\u202a",
                    "\u202b",
                    "\u202c",
                    "\u202d",
                    "\u202e",
                    "\u2028",
                    "\u2029",
                    "\u2066",
                    "\u2067",
                    "\u2068",
                    "\u2069",
                )
            )
        ):
            raise ValueError("visual label text is unsafe")
        try:
            encoded = value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ValueError("visual label text is not valid UTF-8") from exc
        if len(encoded) > 4_096:
            raise ValueError("visual label text exceeds its UTF-8 byte limit")
        return value


class ChartTick(VisualContract):
    id: str = Field(pattern=_ID_RE.pattern)
    value: FiniteNumber
    position: FiniteNumber
    label_id: str = Field(pattern=_ID_RE.pattern)
    evidence_ids: list[str] = Field(min_length=1, max_length=_MAX_REFERENCES)


class ChartAxis(VisualContract):
    id: str = Field(pattern=_ID_RE.pattern)
    panel_id: str = Field(pattern=_ID_RE.pattern)
    orientation: Literal["x", "y"]
    scale: Literal["linear", "log", "dual", "unresolved"]
    minimum: FiniteNumber | None = None
    maximum: FiniteNumber | None = None
    slope: FiniteNumber | None = None
    intercept: FiniteNumber | None = None
    residual: FiniteNumber | None = Field(default=None, ge=0.0)
    calibration_tolerance: FiniteNumber | None = Field(default=None, ge=0.0)
    baseline_position: FiniteNumber | None = None
    unit_label_id: str | None = Field(default=None, pattern=_ID_RE.pattern)
    ticks: list[ChartTick] = Field(default_factory=list, max_length=128)
    category_label_ids: list[str] = Field(
        default_factory=list,
        max_length=_MAX_LABELS,
    )
    evidence_ids: list[str] = Field(min_length=1, max_length=_MAX_REFERENCES)
    calibration_evidence_ids: list[str] = Field(
        default_factory=list,
        max_length=_MAX_REFERENCES,
    )

    @model_validator(mode="after")
    def validate_calibration(self) -> ChartAxis:
        calibration = (
            self.minimum,
            self.maximum,
            self.slope,
            self.intercept,
            self.residual,
            self.calibration_tolerance,
        )
        if self.scale == "linear":
            if (
                any(value is None for value in calibration)
                or len(self.ticks) < 2
                or not self.calibration_evidence_ids
            ):
                raise ValueError("linear axis requires a complete calibration")
            if self.minimum is not None and self.maximum is not None:
                if self.maximum <= self.minimum:
                    raise ValueError("linear axis range must increase")
            if self.slope == 0:
                raise ValueError("linear axis slope must be non-zero")
            positions = [tick.position for tick in self.ticks]
            if len(set(positions)) < 2:
                raise ValueError("linear axis ticks need distinct positions")
            assert self.slope is not None
            assert self.intercept is not None
            assert self.residual is not None
            assert self.calibration_tolerance is not None
            assert self.minimum is not None
            assert self.maximum is not None
            errors = [
                abs(self.slope * tick.position + self.intercept - tick.value)
                for tick in self.ticks
            ]
            if (
                max(errors) > self.residual + 1e-6
                or self.residual > self.calibration_tolerance + 1e-6
                or any(
                    tick.value < self.minimum - self.calibration_tolerance
                    or tick.value > self.maximum + self.calibration_tolerance
                    for tick in self.ticks
                )
            ):
                raise ValueError("linear axis calibration is incoherent")
        elif any(value is not None for value in calibration) or self.calibration_evidence_ids:
            raise ValueError("unsupported axis cannot carry linear calibration")
        return self


class ChartLegendEntry(VisualContract):
    id: str = Field(pattern=_ID_RE.pattern)
    label_id: str = Field(pattern=_ID_RE.pattern)
    swatch_evidence_id: str = Field(pattern=_ID_RE.pattern)
    color: str = Field(min_length=1, max_length=64)
    evidence_ids: list[str] = Field(min_length=1, max_length=_MAX_REFERENCES)


class ChartLegend(VisualContract):
    id: str = Field(pattern=_ID_RE.pattern)
    panel_id: str | None = Field(default=None, pattern=_ID_RE.pattern)
    entries: list[ChartLegendEntry] = Field(min_length=1, max_length=64)
    evidence_ids: list[str] = Field(min_length=1, max_length=_MAX_REFERENCES)


class ChartPanel(VisualContract):
    id: str = Field(pattern=_ID_RE.pattern)
    page_bbox: VisualBoundingBox
    chart_local_bbox: VisualBoundingBox | None = None
    raster_pixel_bbox: VisualBoundingBox | None = None
    label_ids: list[str] = Field(default_factory=list, max_length=_MAX_REFERENCES)
    evidence_ids: list[str] = Field(min_length=1, max_length=_MAX_REFERENCES)

    @model_validator(mode="after")
    def validate_coordinate_space(self) -> ChartPanel:
        if (self.chart_local_bbox is None) == (self.raster_pixel_bbox is None):
            raise ValueError("chart panel requires exactly one local coordinate space")
        return self


class ChartSeries(VisualContract):
    id: str = Field(pattern=_ID_RE.pattern)
    source_object_id: str = Field(min_length=1, max_length=256)
    label_id: str | None = Field(default=None, pattern=_ID_RE.pattern)
    color: str | None = Field(default=None, max_length=64)
    legend_entry_id: str | None = Field(default=None, pattern=_ID_RE.pattern)
    panel_ids: list[str] = Field(min_length=1, max_length=128)
    evidence_ids: list[str] = Field(min_length=1, max_length=_MAX_REFERENCES)


class VectorPrimitive(VisualContract):
    id: str = Field(pattern=_ID_RE.pattern)
    kind: Literal["curve", "rectangle", "line", "text_anchor"]
    panel_id: str = Field(pattern=_ID_RE.pattern)
    page_bbox: VisualBoundingBox
    chart_local_bbox: VisualBoundingBox
    transform_ids: list[str] = Field(min_length=1, max_length=8)
    fill: str | None = Field(default=None, max_length=64)
    stroke: str | None = Field(default=None, max_length=64)
    clipping_known: bool
    clipped: bool
    supported: bool
    source_object_id: str = Field(min_length=1, max_length=256)
    evidence_ids: list[str] = Field(min_length=1, max_length=_MAX_REFERENCES)


class VectorInventory(VisualContract):
    primitives: list[VectorPrimitive] = Field(
        default_factory=list,
        max_length=_MAX_PRIMITIVES,
    )
    panel_candidate_ids: list[str] = Field(
        default_factory=list,
        max_length=128,
    )
    primitive_limit_reached: bool = False


class ChartPoint(VisualContract):
    id: str = Field(pattern=_ID_RE.pattern)
    panel_id: str = Field(pattern=_ID_RE.pattern)
    mark_id: str | None = Field(default=None, pattern=_ID_RE.pattern)
    path_id: str | None = Field(default=None, pattern=_ID_RE.pattern)
    point_evidence_id: str = Field(pattern=_ID_RE.pattern)
    baseline_evidence_id: str = Field(pattern=_ID_RE.pattern)
    axis_ids: list[str] = Field(min_length=1, max_length=2)
    category_label_id: str = Field(pattern=_ID_RE.pattern)
    series_id: str = Field(pattern=_ID_RE.pattern)
    stack_id: str | None = Field(default=None, pattern=_ID_RE.pattern)
    stack_index: int | None = Field(default=None, ge=0, le=255)
    raw_value: FiniteNumber
    display_value: str = Field(min_length=1, max_length=128)
    method: Literal["explicit_text", "vector_measured", "raster_measured"]
    tolerance: NumericTolerance
    confidence: VisualConfidenceDimensions
    source_geometry_evidence_ids: list[str] = Field(
        min_length=1,
        max_length=_MAX_REFERENCES,
    )
    evidence_ids: list[str] = Field(min_length=1, max_length=_MAX_REFERENCES)

    @model_validator(mode="after")
    def validate_value_grounding(self) -> ChartPoint:
        if self.mark_id is None and self.path_id is None:
            raise ValueError("chart point requires mark or path identity")
        if self.method != "explicit_text" and not self.confidence.complete_for_value():
            raise ValueError("measured chart point confidence is incomplete")
        if (self.stack_id is None) != (self.stack_index is None):
            raise ValueError("chart point stack identity is partial")
        return self


class DiagramNode(VisualContract):
    id: str = Field(pattern=_ID_RE.pattern)
    shape: Literal["rectangle", "rounded_rectangle", "ellipse", "diamond"]
    label_id: str | None = Field(default=None, pattern=_ID_RE.pattern)
    detail_label_ids: list[str] = Field(
        default_factory=list,
        max_length=_MAX_REFERENCES,
        exclude_if=lambda value: not value,
    )
    page_bbox: VisualBoundingBox
    evidence_ids: list[str] = Field(min_length=1, max_length=_MAX_REFERENCES)
    confidence: VisualConfidenceDimensions

    @model_validator(mode="after")
    def require_geometry_confidence(self) -> DiagramNode:
        if self.page_bbox.width <= 0 or self.page_bbox.height <= 0:
            raise ValueError("diagram node requires positive-area geometry")
        if self.confidence.geometry is None:
            raise ValueError("diagram node geometry confidence is unavailable")
        return self


class DiagramConnector(VisualContract):
    id: str = Field(pattern=_ID_RE.pattern)
    source_node_id: str = Field(pattern=_ID_RE.pattern)
    target_node_id: str = Field(pattern=_ID_RE.pattern)
    label_id: str | None = Field(
        default=None,
        pattern=_ID_RE.pattern,
        exclude_if=lambda value: value is None,
    )
    directed: Literal[True]
    path_evidence_id: str = Field(pattern=_ID_RE.pattern)
    endpoint_evidence_ids: list[str] = Field(min_length=2, max_length=2)
    direction_evidence_id: str = Field(pattern=_ID_RE.pattern)
    evidence_ids: list[str] = Field(min_length=1, max_length=_MAX_REFERENCES)
    confidence: VisualConfidenceDimensions

    @model_validator(mode="after")
    def require_connector_confidence(self) -> DiagramConnector:
        if self.confidence.geometry is None or self.confidence.direction is None:
            raise ValueError("diagram connector confidence is incomplete")
        return self


class VisualFallback(VisualContract):
    active: bool
    reason: Literal[
        "unresolved",
        "unsupported",
        "malformed_input",
        "validation_failed",
        "resource_limit",
        "timeout",
        "low_quality",
        "incomplete",
        "none",
    ]
    predecessor_concern: Literal[
        "chart_values_not_structured",
        "diagram_relationships_not_structured",
    ]

    @model_validator(mode="after")
    def validate_state(self) -> VisualFallback:
        if self.active == (self.reason == "none"):
            raise ValueError("visual fallback active/reason state differs")
        return self


class VisualSerialization(VisualContract):
    status: Literal["fallback", "structured_chart", "diagram_topology"]
    markdown: str = Field(max_length=262_144)
    caption_occurrences: int = Field(ge=0, le=1)
    row_count: int = Field(ge=0, le=_MAX_POINTS)


class VisualStructure(VisualContract):
    schema_version: Literal["1.0"]
    region: VisualRegion
    transforms: list[VisualTransform] = Field(default_factory=list, max_length=16)
    labels: list[VisualLabel] = Field(default_factory=list, max_length=_MAX_LABELS)
    axes: list[ChartAxis] = Field(default_factory=list, max_length=16)
    legends: list[ChartLegend] = Field(default_factory=list, max_length=16)
    panels: list[ChartPanel] = Field(default_factory=list, max_length=128)
    series: list[ChartSeries] = Field(default_factory=list, max_length=128)
    points: list[ChartPoint] = Field(default_factory=list, max_length=_MAX_POINTS)
    nodes: list[DiagramNode] = Field(default_factory=list, max_length=_MAX_NODES)
    connectors: list[DiagramConnector] = Field(
        default_factory=list,
        max_length=_MAX_CONNECTORS,
    )
    evidence: list[VisualEvidence] = Field(
        min_length=1,
        max_length=_MAX_EVIDENCE,
    )
    vector_inventory: VectorInventory | None = None
    confidence: VisualConfidenceDimensions
    concerns: list[VisualConcern] = Field(default_factory=list, max_length=256)
    fallback: VisualFallback
    serialization: VisualSerialization | None = None

    @model_validator(mode="after")
    def validate_graph(self) -> VisualStructure:
        def unique_ids(values: list[Any], label: str) -> set[str]:
            identifiers = [value.id for value in values]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"duplicate visual {label} identifiers")
            return set(identifiers)

        evidence_ids = unique_ids(self.evidence, "evidence")
        label_ids = unique_ids(self.labels, "label")
        axis_ids = unique_ids(self.axes, "axis")
        legend_ids = unique_ids(self.legends, "legend")
        panel_ids = unique_ids(self.panels, "panel")
        series_ids = unique_ids(self.series, "series")
        point_ids = unique_ids(self.points, "point")
        node_ids = unique_ids(self.nodes, "node")
        connector_ids = unique_ids(self.connectors, "connector")
        tick_ids = unique_ids(
            [tick for axis in self.axes for tick in axis.ticks],
            "tick",
        )
        legend_entry_values = [
            entry for legend in self.legends for entry in legend.entries
        ]
        legend_entry_ids = unique_ids(legend_entry_values, "legend entry")
        legend_entries_by_id = {entry.id: entry for entry in legend_entry_values}
        if len(
            label_ids
            | axis_ids
            | legend_ids
            | panel_ids
            | series_ids
            | point_ids
            | node_ids
            | connector_ids
            | tick_ids
            | legend_entry_ids
            | {self.region.id}
        ) != (
            len(label_ids)
            + len(axis_ids)
            + len(legend_ids)
            + len(panel_ids)
            + len(series_ids)
            + len(point_ids)
            + len(node_ids)
            + len(connector_ids)
            + len(tick_ids)
            + len(legend_entry_ids)
            + 1
        ):
            raise ValueError("visual semantic identifiers overlap")

        if [label.occurrence_index for label in self.labels] != list(
            range(len(self.labels))
        ):
            raise ValueError("visual label occurrence order differs")
        labels_by_id = {label.id: label for label in self.labels}
        evidence_by_id = {record.id: record for record in self.evidence}
        if len({series.source_object_id for series in self.series}) != len(
            self.series
        ):
            raise ValueError("chart series source identity repeats")

        transform_ids = unique_ids(self.transforms, "transform")

        def require_refs(values: list[str], allowed: set[str], label: str) -> None:
            if not set(values) <= allowed:
                raise ValueError(f"unknown {label} reference")
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {label} references")

        require_refs(self.region.evidence_ids, evidence_ids, "region evidence")
        for evidence in self.evidence:
            require_refs(evidence.transform_ids, transform_ids, "evidence transform")
        for label in self.labels:
            require_refs(label.evidence_ids, evidence_ids, "label evidence")
        for axis in self.axes:
            if axis.panel_id not in panel_ids:
                raise ValueError("unknown axis panel")
            require_refs(axis.evidence_ids, evidence_ids, "axis evidence")
            require_refs(
                axis.calibration_evidence_ids,
                evidence_ids,
                "axis calibration evidence",
            )
            if not any(
                evidence_by_id[evidence_id].kind == "axis"
                for evidence_id in axis.evidence_ids
            ):
                raise ValueError("axis lacks axis evidence")
            if any(
                evidence_by_id[evidence_id].kind not in {"axis", "tick"}
                for evidence_id in axis.calibration_evidence_ids
            ):
                raise ValueError("axis calibration evidence kind differs")
            require_refs(axis.category_label_ids, label_ids, "axis category")
            if any(
                labels_by_id[label_id].role != "category"
                for label_id in axis.category_label_ids
            ):
                raise ValueError("axis category label role differs")
            if axis.unit_label_id is not None and axis.unit_label_id not in label_ids:
                raise ValueError("unknown axis unit label")
            if (
                axis.unit_label_id is not None
                and labels_by_id[axis.unit_label_id].role != "unit"
            ):
                raise ValueError("axis unit label role differs")
            for tick in axis.ticks:
                if tick.label_id not in label_ids:
                    raise ValueError("unknown tick label")
                require_refs(tick.evidence_ids, evidence_ids, "tick evidence")
                if labels_by_id[tick.label_id].role not in {"tick", "category"}:
                    raise ValueError("tick label role differs")
                if not any(
                    evidence_by_id[evidence_id].kind == "tick"
                    for evidence_id in tick.evidence_ids
                ):
                    raise ValueError("tick lacks tick evidence")
        for legend in self.legends:
            if legend.panel_id is not None and legend.panel_id not in panel_ids:
                raise ValueError("unknown legend panel")
            require_refs(legend.evidence_ids, evidence_ids, "legend evidence")
            for entry in legend.entries:
                if entry.label_id not in label_ids:
                    raise ValueError("unknown legend label")
                if labels_by_id[entry.label_id].role != "legend":
                    raise ValueError("legend label role differs")
                if entry.swatch_evidence_id not in evidence_ids:
                    raise ValueError("unknown legend swatch evidence")
                if evidence_by_id[entry.swatch_evidence_id].kind != "swatch":
                    raise ValueError("legend swatch evidence kind differs")
                require_refs(entry.evidence_ids, evidence_ids, "legend entry evidence")
        for panel in self.panels:
            require_refs(panel.label_ids, label_ids, "panel label")
            require_refs(panel.evidence_ids, evidence_ids, "panel evidence")
        for series in self.series:
            if series.label_id is not None and series.label_id not in label_ids:
                raise ValueError("unknown series label")
            if (
                series.legend_entry_id is not None
                and series.legend_entry_id not in legend_entry_ids
            ):
                raise ValueError("unknown series legend entry")
            require_refs(series.panel_ids, panel_ids, "series panel")
            require_refs(series.evidence_ids, evidence_ids, "series evidence")
            if series.legend_entry_id is not None:
                legend_entry = legend_entries_by_id[series.legend_entry_id]
                if (
                    series.label_id != legend_entry.label_id
                    or series.color != legend_entry.color
                ):
                    raise ValueError("series and legend semantics differ")
            if not any(
                evidence_by_id[evidence_id].kind in {"swatch", "mark", "source_object"}
                for evidence_id in series.evidence_ids
            ):
                raise ValueError("series lacks geometry or swatch evidence")
        primitive_ids: set[str] = set()
        primitives_by_id: dict[str, VectorPrimitive] = {}
        if self.vector_inventory is not None:
            primitive_ids = unique_ids(self.vector_inventory.primitives, "primitive")
            primitives_by_id = {
                primitive.id: primitive
                for primitive in self.vector_inventory.primitives
            }
            require_refs(
                self.vector_inventory.panel_candidate_ids,
                panel_ids,
                "panel candidate",
            )
            for primitive in self.vector_inventory.primitives:
                if primitive.panel_id not in panel_ids:
                    raise ValueError("unknown primitive panel")
                require_refs(
                    primitive.transform_ids,
                    transform_ids,
                    "primitive transform",
                )
                require_refs(
                    primitive.evidence_ids,
                    evidence_ids,
                    "primitive evidence",
                )
        for point in self.points:
            if point.panel_id not in panel_ids:
                raise ValueError("unknown point panel")
            require_refs(point.axis_ids, axis_ids, "point axis")
            point_axes = [axis for axis in self.axes if axis.id in point.axis_ids]
            if any(
                axis.scale != "linear" or axis.panel_id != point.panel_id
                for axis in point_axes
            ):
                raise ValueError("point axis is unsupported or belongs to another panel")
            if point.category_label_id not in label_ids:
                raise ValueError("unknown point category")
            if labels_by_id[point.category_label_id].role != "category":
                raise ValueError("point category label role differs")
            if not any(
                axis.panel_id == point.panel_id
                and point.category_label_id in axis.category_label_ids
                for axis in self.axes
            ):
                raise ValueError("point category is not grounded to its panel")
            if point.series_id not in series_ids:
                raise ValueError("unknown point series")
            point_series = next(
                series for series in self.series if series.id == point.series_id
            )
            if point.panel_id not in point_series.panel_ids:
                raise ValueError("point series does not own its panel")
            if point.mark_id is not None and point.mark_id not in primitive_ids:
                # Raster marks are evidence identities rather than vector
                # primitive identities and therefore use the mark evidence set.
                mark_evidence_ids = {
                    evidence.id for evidence in self.evidence if evidence.kind == "mark"
                }
                if point.mark_id not in mark_evidence_ids:
                    raise ValueError("unknown point mark")
            if point.mark_id in primitives_by_id:
                primitive = primitives_by_id[point.mark_id]
                if primitive.panel_id != point.panel_id:
                    raise ValueError("point mark belongs to another panel")
                if not set(primitive.evidence_ids) <= set(
                    point.source_geometry_evidence_ids
                ):
                    raise ValueError("point geometry omits mark evidence")
            if point.path_id is not None:
                path_evidence_ids = {
                    evidence.id for evidence in self.evidence if evidence.kind == "path"
                }
                if point.path_id not in path_evidence_ids:
                    raise ValueError("unknown point path")
            if point.point_evidence_id not in evidence_ids:
                raise ValueError("unknown point evidence")
            if evidence_by_id[point.point_evidence_id].kind != "point":
                raise ValueError("point evidence kind differs")
            if point.baseline_evidence_id not in evidence_ids:
                raise ValueError("unknown point baseline evidence")
            if evidence_by_id[point.baseline_evidence_id].kind != "baseline":
                raise ValueError("point baseline evidence kind differs")
            require_refs(
                point.source_geometry_evidence_ids,
                evidence_ids,
                "point geometry evidence",
            )
            require_refs(point.evidence_ids, evidence_ids, "point evidence")
            if point.method == "vector_measured":
                if point.mark_id not in primitive_ids or point.tolerance.basis not in {
                    "vector_geometry",
                    "axis_residual",
                    "combined",
                }:
                    raise ValueError("vector point method/evidence differs")
            elif point.method == "raster_measured":
                if point.tolerance.basis not in {"raster_pixels", "combined"}:
                    raise ValueError("raster point tolerance basis differs")
            elif point.tolerance.basis not in {"explicit_rounding", "combined"}:
                raise ValueError("explicit point tolerance basis differs")
        mark_point_ids = [
            point.mark_id for point in self.points if point.mark_id is not None
        ]
        if len(mark_point_ids) != len(set(mark_point_ids)):
            raise ValueError("chart mark contributes more than one point")
        point_semantic_keys = [
            (point.panel_id, point.category_label_id, point.series_id)
            for point in self.points
        ]
        if len(point_semantic_keys) != len(set(point_semantic_keys)):
            raise ValueError("chart point semantic ownership repeats")
        for node in self.nodes:
            if node.label_id is not None and node.label_id not in label_ids:
                raise ValueError("unknown node label")
            require_refs(node.detail_label_ids, label_ids, "node detail label")
            require_refs(node.evidence_ids, evidence_ids, "node evidence")
            node_geometry = [
                evidence_by_id[evidence_id]
                for evidence_id in node.evidence_ids
                if evidence_by_id[evidence_id].kind == "node"
            ]
            if not node_geometry:
                raise ValueError("diagram node lacks node geometry evidence")
            if not any(
                record.page_bbox is not None
                and record.page_bbox == node.page_bbox
                for record in node_geometry
            ):
                raise ValueError("diagram node geometry evidence differs")
            if (
                node.page_bbox.unit != self.region.page_bbox.unit
                or node.page_bbox.x < self.region.page_bbox.x - 1e-6
                or node.page_bbox.y < self.region.page_bbox.y - 1e-6
                or node.page_bbox.x + node.page_bbox.width
                > self.region.page_bbox.x + self.region.page_bbox.width + 1e-6
                or node.page_bbox.y + node.page_bbox.height
                > self.region.page_bbox.y + self.region.page_bbox.height + 1e-6
            ):
                raise ValueError("diagram node leaves its owner region")
            if node.label_id is not None:
                node_label = labels_by_id[node.label_id]
                if node_label.role != "node" or node_label.page_bbox is None:
                    raise ValueError("diagram node label is not spatial node text")
                label_box = node_label.page_bbox
                if (
                    label_box.unit != node.page_bbox.unit
                    or label_box.x < node.page_bbox.x - 1e-6
                    or label_box.y < node.page_bbox.y - 1e-6
                    or label_box.x + label_box.width
                    > node.page_bbox.x + node.page_bbox.width + 1e-6
                    or label_box.y + label_box.height
                    > node.page_bbox.y + node.page_bbox.height + 1e-6
                ):
                    raise ValueError("diagram node label leaves node geometry")
                if not set(node_label.evidence_ids) <= set(node.evidence_ids):
                    raise ValueError("diagram node omits label evidence")
            for detail_label_id in node.detail_label_ids:
                detail_label = labels_by_id[detail_label_id]
                if detail_label.role != "node_detail" or detail_label.page_bbox is None:
                    raise ValueError("diagram node detail is not spatial detail text")
                detail_box = detail_label.page_bbox
                if (
                    detail_box.unit != node.page_bbox.unit
                    or detail_box.x < node.page_bbox.x - 1e-6
                    or detail_box.y < node.page_bbox.y - 1e-6
                    or detail_box.x + detail_box.width
                    > node.page_bbox.x + node.page_bbox.width + 1e-6
                    or detail_box.y + detail_box.height
                    > node.page_bbox.y + node.page_bbox.height + 1e-6
                ):
                    raise ValueError("diagram node detail leaves node geometry")
                if not set(detail_label.evidence_ids) <= set(node.evidence_ids):
                    raise ValueError("diagram node omits detail evidence")
        directed_edges: list[tuple[str, str]] = []
        for connector in self.connectors:
            if (
                connector.source_node_id not in node_ids
                or connector.target_node_id not in node_ids
                or connector.source_node_id == connector.target_node_id
            ):
                raise ValueError("unknown or self-referential connector node")
            if connector.path_evidence_id not in evidence_ids:
                raise ValueError("unknown connector path evidence")
            if evidence_by_id[connector.path_evidence_id].kind != "path":
                raise ValueError("connector path evidence kind differs")
            require_refs(
                connector.endpoint_evidence_ids,
                evidence_ids,
                "connector endpoint evidence",
            )
            if any(
                evidence_by_id[evidence_id].kind != "point"
                for evidence_id in connector.endpoint_evidence_ids
            ):
                raise ValueError("connector endpoint evidence kind differs")
            if connector.direction_evidence_id not in evidence_ids:
                raise ValueError("unknown connector direction evidence")
            if evidence_by_id[connector.direction_evidence_id].kind != "connector":
                raise ValueError("connector direction evidence kind differs")
            if connector.label_id is not None:
                if connector.label_id not in label_ids:
                    raise ValueError("unknown connector label")
                connector_label = labels_by_id[connector.label_id]
                if connector_label.role != "connector":
                    raise ValueError("diagram connector label role differs")
                if not set(connector_label.evidence_ids) <= set(
                    connector.evidence_ids
                ):
                    raise ValueError("diagram connector omits label evidence")
            require_refs(connector.evidence_ids, evidence_ids, "connector evidence")
            required_connector_evidence = {
                connector.path_evidence_id,
                connector.direction_evidence_id,
                *connector.endpoint_evidence_ids,
            }
            if not required_connector_evidence <= set(connector.evidence_ids):
                raise ValueError("connector omits path, endpoint, or direction evidence")
            directed_edges.append(
                (connector.source_node_id, connector.target_node_id)
            )
        if len(directed_edges) != len(set(directed_edges)):
            raise ValueError("diagram directed edge ownership repeats")
        for concern in self.concerns:
            require_refs(concern.evidence_ids, evidence_ids, "concern evidence")

        if self.region.kind == "chart" and (self.nodes or self.connectors):
            raise ValueError("chart structure cannot carry diagram topology")
        if self.region.kind == "diagram" and (
            self.axes
            or self.legends
            or self.panels
            or self.series
            or self.points
            or self.vector_inventory is not None
        ):
            raise ValueError("diagram structure cannot carry chart semantics")
        if self.fallback.active and self.serialization is not None:
            if self.serialization.status != "fallback":
                raise ValueError("fallback visual cannot claim structured serialization")
        # Chart value candidates intentionally exist between US04/US07/US08
        # measurement and the shared US05 validator.  Diagram connectors have
        # no analogous candidate state: until endpoint/direction validation and
        # serialization succeed they must remain absent.
        if self.fallback.active and self.connectors:
            raise ValueError("fallback diagram cannot carry authoritative topology")
        if not self.fallback.active and self.serialization is None:
            raise ValueError("authoritative visual structure requires serialization")
        if self.fallback.predecessor_concern != (
            "chart_values_not_structured"
            if self.region.kind == "chart"
            else "diagram_relationships_not_structured"
        ):
            raise ValueError("visual fallback concern differs from region kind")
        if not self.fallback.active and self.serialization is not None:
            expected_status = (
                "structured_chart"
                if self.region.kind == "chart"
                else "diagram_topology"
            )
            if self.serialization.status != expected_status:
                raise ValueError("visual serialization status differs from region kind")
            expected_rows = (
                len(self.points)
                if self.region.kind == "chart"
                else len(self.connectors)
            )
            if self.serialization.row_count != expected_rows:
                raise ValueError("visual serialization row count differs from authority")
            if self.region.kind == "diagram" and not self.connectors:
                raise ValueError("diagram topology requires a grounded connector")
        return self


def ensure_finite_mapping(value: Any, *, depth: int = 0, budget: list[int] | None = None) -> None:
    """Bound and reject non-finite/malformed analyzer input before staging it."""

    if budget is None:
        budget = [16_384]
    if depth > 12 or budget[0] <= 0:
        raise ValueError("visual analyzer input exceeds its structural limit")
    budget[0] -= 1
    if isinstance(value, bool) or value is None or isinstance(value, (str, bytes)):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise ValueError("visual analyzer input contains a non-finite number")
        return
    if isinstance(value, dict):
        if len(value) > 2_048:
            raise ValueError("visual analyzer mapping exceeds its entry limit")
        for key, member in value.items():
            if not isinstance(key, str) or len(key) > 256:
                raise ValueError("visual analyzer mapping key is invalid")
            ensure_finite_mapping(member, depth=depth + 1, budget=budget)
        return
    if isinstance(value, (list, tuple)):
        if len(value) > 4_096:
            raise ValueError("visual analyzer sequence exceeds its entry limit")
        for member in value:
            ensure_finite_mapping(member, depth=depth + 1, budget=budget)
        return
    raise ValueError("visual analyzer input contains an unsupported value")
