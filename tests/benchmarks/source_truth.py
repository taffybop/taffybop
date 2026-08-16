"""Test/reporting-only source-truth validation for the P00-US02 fixture.

The models layer page geometry, relationships, cells, and chart evidence on
top of the P00-US01 contracts.  They are deliberately not a production parser
IR and must never be imported from ``app``.
"""

from __future__ import annotations

from enum import Enum
from itertools import pairwise
import math
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import ConfigDict, Field, RootModel, model_validator

from tests.benchmarks.contracts import (
    Annotation,
    ContractModel,
    FixtureManifest,
    MetricRecord,
    MetricUnit,
    NonEmptyString,
    SchemaVersion,
    Sha256,
    TruthClass,
)


class ArtifactRole(str, Enum):
    SOURCE = "source"
    EXPERT_MARKDOWN = "expert_markdown"
    EXPERT_JSON = "expert_json"


class ReviewStatus(str, Enum):
    VERIFIED = "verified"


class ElementType(str, Enum):
    LOGO = "logo"
    PARAGRAPH = "paragraph"
    TEXT_SPAN = "text_span"
    CAPTION = "caption"
    TABLE = "table"
    CHART = "chart"
    SOURCE_NOTE = "source_note"
    FOOTER = "footer"
    PRINTED_PAGE_LABEL = "printed_page_label"


class RelationshipType(str, Enum):
    CAPTION_OF = "caption_for"
    SOURCE_NOTE_OF = "source_for"
    CONTAINS = "contains"
    FOOTER_PAIR = "footer_pair"


class ChartSeries(str, Enum):
    FIRST_HALF = "1H"
    ANNUAL_TOTAL = "annual_total"


class NegativeType(str, Enum):
    DUPLICATE_TITLE = "duplicate_title"
    FALSE_ROW_SPAN = "false_row_span"
    ANNUAL_BELOW_FIRST_HALF = "annual_below_1h"
    UNSUPPORTED_EXACT_VALUE = "unsupported_exact_value"


class BBox(RootModel[tuple[float, float, float, float]]):
    """A compact ``[x, y, width, height]`` box in top-left PDF points."""

    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    @model_validator(mode="after")
    def require_valid_geometry(self) -> "BBox":
        if not all(math.isfinite(value) for value in self.root):
            raise ValueError("bbox coordinates must be finite")
        if self.x < 0 or self.y < 0:
            raise ValueError("bbox origin must be non-negative")
        if self.w <= 0 or self.h <= 0:
            raise ValueError("bbox width and height must be positive")
        return self

    @property
    def x(self) -> float:
        return self.root[0]

    @property
    def y(self) -> float:
        return self.root[1]

    @property
    def w(self) -> float:
        return self.root[2]

    @property
    def h(self) -> float:
        return self.root[3]

    @property
    def unit(self) -> str:
        return "pt"

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h


class ArtifactIdentity(ContractModel):
    role: ArtifactRole
    path: NonEmptyString
    sha256: Sha256
    size_bytes: int = Field(gt=0)


class CoordinateSpace(ContractModel):
    origin: Literal["top_left"]
    unit: Literal["pt"]
    bbox_format: Literal["[x,y,width,height]"]


class PageIdentity(ContractModel):
    physical_page: int = Field(ge=1)
    printed_page: NonEmptyString
    width_pt: float = Field(gt=0)
    height_pt: float = Field(gt=0)
    rotation: Literal[0, 90, 180, 270]
    coordinate_space: CoordinateSpace

    @property
    def printed_page_label(self) -> str:
        return self.printed_page

    @property
    def coordinate_origin(self) -> str:
        return "top-left"

    @property
    def coordinate_unit(self) -> str:
        return self.coordinate_space.unit


class ReviewedClaim(Annotation):
    review_status: ReviewStatus
    reviewer: NonEmptyString
    review_version: NonEmptyString
    physical_page: int = Field(ge=1)

    def annotation_contract(self) -> Annotation:
        """Return the strict P00-US01 projection for this reviewed claim."""

        return Annotation(
            schema_version=self.schema_version,
            annotation_id=self.annotation_id,
            fixture_id=self.fixture_id,
            truth_class=self.truth_class,
            claim=self.claim,
            include_in_exact_parity=self.include_in_exact_parity,
        )


class SourceUseDecision(ContractModel):
    """Governance record for fixture custody, not a PDF-derived annotation."""

    schema_version: SchemaVersion
    decision_id: NonEmptyString
    fixture_id: NonEmptyString
    record_status: Literal["approved"]
    recorder: NonEmptyString
    record_version: NonEmptyString
    decision: Literal["public-redistributable"]
    decision_date: NonEmptyString
    approver: NonEmptyString
    evidence_path: NonEmptyString
    applies_to_artifact_roles: tuple[ArtifactRole, ...] = Field(
        min_length=3,
        max_length=3,
    )
    permitted_uses: tuple[NonEmptyString, ...] = Field(min_length=1)
    limitation: NonEmptyString

    @model_validator(mode="after")
    def require_approval(self) -> "SourceUseDecision":
        required_uses = {
            "workspace_retention",
            "repository_commit",
            "benchmark_redistribution",
            "local_validation",
            "private_ci_validation",
            "committed_ci_validation",
        }
        if set(self.applies_to_artifact_roles) != set(ArtifactRole):
            raise ValueError("source-use decision must cover the complete triplet")
        if set(self.permitted_uses) != required_uses:
            raise ValueError("source-use decision must retain every approved use")
        if (
            self.evidence_path
            != "tracker/phase-00-baseline/evidence/P00-US02-source-rights.md"
        ):
            raise ValueError("source-use decision must use the portable evidence path")
        return self


class SourceElement(ReviewedClaim):
    element_id: NonEmptyString
    type: ElementType
    text: NonEmptyString | None
    bbox: BBox
    bbox_segments: tuple[BBox, ...] = ()
    reading_order: int = Field(ge=0)

    @property
    def element_type(self) -> ElementType:
        return self.type


class SourceRelationship(ReviewedClaim):
    relationship_type: RelationshipType
    source_id: NonEmptyString
    target_id: NonEmptyString


class TableDefinition(ReviewedClaim):
    table_id: NonEmptyString
    bbox: BBox
    row_count: int = Field(gt=0)
    column_count: int = Field(gt=0)
    cell_count: int = Field(gt=0)
    header_row_count: int = Field(ge=0)
    all_row_spans: int = Field(gt=0)
    all_col_spans: int = Field(gt=0)
    grid_x_pt: tuple[float, ...] = Field(min_length=2)
    grid_y_pt: tuple[float, ...] = Field(min_length=2)

    @property
    def element_id(self) -> str:
        return self.table_id

    @property
    def rows(self) -> int:
        return self.row_count

    @property
    def columns(self) -> int:
        return self.column_count


class TableCell(ReviewedClaim):
    table_id: NonEmptyString
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    row_span: int = Field(gt=0)
    col_span: int = Field(gt=0)
    text: NonEmptyString
    bbox: BBox

    @property
    def column_span(self) -> int:
        return self.col_span


class AxisTick(ContractModel):
    value: float = Field(ge=0)
    y_pt: float = Field(ge=0)

    @property
    def value_2025_usd_billions(self) -> float:
        return self.value

    @property
    def page_y_pt(self) -> float:
        return self.y_pt


class IntermediateYearAssignments(ContractModel):
    truth_class: Literal[TruthClass.INFERRED]
    count: int = Field(ge=0)
    rule: NonEmptyString


class ChartCalibration(ReviewedClaim):
    calibration_id: NonEmptyString
    chart_id: NonEmptyString
    method: NonEmptyString
    baseline_y_pt: float = Field(ge=0)
    baseline_value: float = Field(ge=0)
    baseline_value_is_inferred: bool
    tick_positions: tuple[AxisTick, ...] = Field(min_length=2)
    points_per_usd_billion: float = Field(gt=0)
    quantization_pt: float = Field(gt=0)
    tolerance: float = Field(gt=0)
    unit: MetricUnit
    source_bbox: BBox
    intermediate_year_assignments: IntermediateYearAssignments
    overpaint_note: NonEmptyString

    @property
    def measurement_method(self) -> str:
        return self.method

    @property
    def ticks(self) -> tuple[AxisTick, ...]:
        return self.tick_positions

    @property
    def coordinate_quantization_pt(self) -> float:
        return self.quantization_pt


class ChartLabel(ReviewedClaim):
    parent_chart_id: NonEmptyString
    label_type: Literal["panel", "axis_tick", "year_anchor", "legend"]
    text: NonEmptyString
    bbox: BBox
    panel: Literal["Americas", "APAC", "EMEA", "USA"] | None = None

    @model_validator(mode="after")
    def require_literal_chart_label(self) -> "ChartLabel":
        if self.truth_class is not TruthClass.VISIBLE_TEXT:
            raise ValueError("printed chart labels must be visible_text")
        if not self.include_in_exact_parity:
            raise ValueError("printed chart labels must be eligible for exact parity")
        return self


class ChartMeasurement(ReviewedClaim):
    measurement_id: NonEmptyString
    chart_id: NonEmptyString
    calibration_id: NonEmptyString
    panel: Literal["Americas", "APAC", "EMEA", "USA"]
    year: int = Field(ge=2015, le=2025)
    series: ChartSeries
    value: float = Field(ge=0)
    unit: MetricUnit
    tolerance: float = Field(gt=0)
    method: NonEmptyString
    raw_mark_bbox: BBox

    @model_validator(mode="after")
    def require_measured_semantics(self) -> "ChartMeasurement":
        if self.truth_class is not TruthClass.MEASURED:
            raise ValueError("chart measurements must use truth_class=measured")
        if self.review_status is not ReviewStatus.VERIFIED:
            raise ValueError("chart measurements must be source-reviewed")
        if self.include_in_exact_parity:
            raise ValueError("chart measurements cannot enter exact parity")
        if self.unit is not MetricUnit.BILLIONS_2025_USD:
            raise ValueError("catastrophe chart measurements use 2025_USD_billions")
        self.metric_contract()
        return self

    @property
    def measurement_method(self) -> str:
        return self.method

    @property
    def source_bbox(self) -> BBox:
        return self.raw_mark_bbox

    def metric_contract(self) -> MetricRecord:
        """Return the strict P00-US01 measured-metric projection."""

        return MetricRecord(
            schema_version=self.schema_version,
            metric_name=(
                f"{self.chart_id}.{self.panel}.{self.year}.{self.series.value}"
            ),
            measurement_method=self.method,
            fixture_id=self.fixture_id,
            annotation_id=self.annotation_id,
            value=self.value,
            unit=self.unit,
            tolerance=self.tolerance,
            evidence_class=self.truth_class,
        )


class NegativeAnnotation(ReviewedClaim):
    negative_type: NegativeType
    control_kind: Literal["synthetic_validator_control"]
    observed_in_registered_artifact: bool
    expected_validation: Literal["reject"]
    mutation: dict[NonEmptyString, object] = Field(min_length=1)

    @model_validator(mode="after")
    def require_rejected_nonliteral_semantics(self) -> "NegativeAnnotation":
        if self.review_status is not ReviewStatus.VERIFIED:
            raise ValueError("negative annotations must be source-reviewed")
        if self.include_in_exact_parity:
            raise ValueError("negative annotations cannot enter exact parity")
        if self.observed_in_registered_artifact:
            raise ValueError("registered negatives are synthetic controls")
        return self


def _bbox_contains(parent: BBox, child: BBox) -> bool:
    return (
        parent.x <= child.x
        and parent.y <= child.y
        and child.right <= parent.right
        and child.bottom <= parent.bottom
    )


class CatastropheSourceTruth(ContractModel):
    """Complete, cross-referenced source truth for the catastrophe fixture."""

    schema_version: SchemaVersion
    fixture: FixtureManifest
    artifacts: tuple[ArtifactIdentity, ...] = Field(min_length=3, max_length=3)
    source_use_decision: SourceUseDecision
    page: PageIdentity
    elements: tuple[SourceElement, ...] = Field(min_length=1)
    relationships: tuple[SourceRelationship, ...] = Field(min_length=1)
    table: TableDefinition
    table_cells: tuple[TableCell, ...] = Field(min_length=30, max_length=30)
    chart_calibration: ChartCalibration
    chart_labels: tuple[ChartLabel, ...] = Field(min_length=23, max_length=23)
    chart_measurements: tuple[ChartMeasurement, ...] = Field(
        min_length=88,
        max_length=88,
    )
    negative_annotations: tuple[NegativeAnnotation, ...] = Field(
        min_length=4,
        max_length=4,
    )

    @model_validator(mode="after")
    def validate_cross_references(self) -> "CatastropheSourceTruth":
        self._validate_fixture_and_artifacts()
        self._validate_claims_and_geometry()
        self._validate_elements_and_relationships()
        self._validate_table()
        self._validate_chart()
        self._validate_negatives()
        return self

    def _validate_fixture_and_artifacts(self) -> None:
        if self.fixture.schema_version != self.schema_version:
            raise ValueError("fixture and bundle schema versions must match")
        if self.fixture.custody != "public-redistributable":
            raise ValueError("P00-US02 requires public-redistributable custody")
        if self.fixture.source_format != "PDF":
            raise ValueError("catastrophe source format must remain PDF")
        if self.source_use_decision.schema_version != self.schema_version:
            raise ValueError(
                "source-use decision and bundle schema versions must match"
            )
        if self.source_use_decision.fixture_id != self.fixture.fixture_id:
            raise ValueError(
                "source-use decision must reference the registered fixture"
            )
        if (
            self.source_use_decision.decision_id
            != "source-use-decision-catastrophe-recap"
        ):
            raise ValueError("source-use decision must use its stable decision ID")
        if self.source_use_decision.decision != self.fixture.custody:
            raise ValueError("source-use decision must match fixture custody")
        if not self.source_use_decision.evidence_path.endswith(
            "P00-US02-source-rights.md"
        ):
            raise ValueError("source-use decision must link its approval evidence")

        expected_roles = set(ArtifactRole)
        roles = {artifact.role for artifact in self.artifacts}
        if roles != expected_roles:
            raise ValueError("source, expert_markdown, and expert_json are required")
        paths = [artifact.path for artifact in self.artifacts]
        hashes = [artifact.sha256 for artifact in self.artifacts]
        if len(paths) != len(set(paths)):
            raise ValueError("artifact paths must be unique")
        if len(hashes) != len(set(hashes)):
            raise ValueError("artifact hashes must not collide")
        for path in paths:
            pure_path = PurePosixPath(path)
            if pure_path.is_absolute() or ".." in pure_path.parts:
                raise ValueError("artifact paths must be portable workspace paths")
            if not pure_path.parts or pure_path.parts[0] != "benchmark-expertmodeldata":
                raise ValueError("artifact paths must stay in benchmark-expertmodeldata")
        source = next(
            artifact
            for artifact in self.artifacts
            if artifact.role is ArtifactRole.SOURCE
        )
        if source.sha256 != self.fixture.source_sha256:
            raise ValueError("source artifact hash must match FixtureManifest")
        if (
            self.page.physical_page != 1
            or self.page.printed_page != "7"
            or self.page.width_pt != 612.0
            or self.page.height_pt != 792.0
            or self.page.rotation != 0
            or self.page.coordinate_space.origin != "top_left"
            or self.page.coordinate_space.unit != "pt"
            or self.page.coordinate_space.bbox_format
            != "[x,y,width,height]"
        ):
            raise ValueError(
                "page identity and coordinate space must match the reviewed PDF"
            )

    def _all_claims(self) -> tuple[ReviewedClaim, ...]:
        return (
            *self.elements,
            *self.relationships,
            self.table,
            *self.table_cells,
            self.chart_calibration,
            *self.chart_labels,
            *self.chart_measurements,
            *self.negative_annotations,
        )

    def _validate_claims_and_geometry(self) -> None:
        claims = self._all_claims()
        annotation_ids = [claim.annotation_id for claim in claims]
        if len(annotation_ids) != len(set(annotation_ids)):
            raise ValueError("annotation IDs must be unique")
        for claim in claims:
            if claim.review_status is not ReviewStatus.VERIFIED:
                raise ValueError("every PDF-derived claim must be source-verified")
            if claim.fixture_id != self.fixture.fixture_id:
                raise ValueError("every claim must reference the registered fixture")
            if claim.schema_version != self.schema_version:
                raise ValueError("every claim must use the bundle schema version")
            if claim.physical_page != self.page.physical_page:
                raise ValueError("every claim must reference the registered page")
            claim.annotation_contract()

        geometry_records = (
            *self.elements,
            *self.table_cells,
            *self.chart_labels,
            *self.chart_measurements,
        )
        page_bbox = BBox((0, 0, self.page.width_pt, self.page.height_pt))
        for record in geometry_records:
            bbox = record.source_bbox if isinstance(record, ChartMeasurement) else record.bbox
            if not _bbox_contains(page_bbox, bbox):
                raise ValueError(f"{record.annotation_id} bbox lies outside the page")
        if not _bbox_contains(page_bbox, self.table.bbox):
            raise ValueError("Exhibit 7 bbox lies outside the page")
        if not _bbox_contains(page_bbox, self.chart_calibration.source_bbox):
            raise ValueError("Exhibit 8 bbox lies outside the page")
        for element in self.elements:
            if any(
                not _bbox_contains(element.bbox, segment)
                for segment in element.bbox_segments
            ):
                raise ValueError("element bbox segment lies outside its parent bbox")

    def _validate_elements_and_relationships(self) -> None:
        caption_texts = [
            element.text
            for element in self.elements
            if element.element_type is ElementType.CAPTION
        ]
        if len(caption_texts) != len(set(caption_texts)):
            raise ValueError("canonical exhibit titles must not be duplicated")
        reading_orders = sorted(element.reading_order for element in self.elements)
        if reading_orders != list(range(len(self.elements))):
            raise ValueError("element reading order must be contiguous and unique")
        expected_reading_order = [
            "logo-aon",
            "intro-paragraph",
            "damaged-sentence",
            "exhibit-7-title",
            "exhibit-7-table",
            "transition-paragraph",
            "exhibit-8-title",
            "exhibit-8-chart",
            "chart-source-note",
            "footer-title",
            "printed-page-label",
        ]
        actual_reading_order = [
            element.element_id
            for element in sorted(self.elements, key=lambda item: item.reading_order)
        ]
        if actual_reading_order != expected_reading_order:
            raise ValueError("element reading order must match the reviewed source")
        element_ids = {element.element_id for element in self.elements}
        if len(element_ids) != len(self.elements):
            raise ValueError("element IDs must be unique")
        expected_elements = {
            "logo-aon": (
                ElementType.LOGO,
                "AON",
            ),
            "intro-paragraph": (
                ElementType.PARAGRAPH,
                "Insured losses were driven by the destructive California "
                "wildfires in January, with total insured losses to be "
                "estimated at more than $40 billion. At least 19 events, 18 "
                "of which occurred in the United States, surpassed $1 billion "
                "in insured losses. Outside the U.S. region, European SCS "
                "outbreak in late June was the only event that exceeded this "
                "threshold. Cyclone Alfred in Australia resulted in the "
                "insured losses of approximately $900 million (AUD1.4 "
                "billion). Windstorm Éowyn in Ireland and the UK followed "
                "with $690 million (€620 million).",
            ),
            "damaged-sentence": (
                ElementType.TEXT_SPAN,
                "Windstorm Éowyn in Ireland and the UK followed with $690 "
                "million (€620 million).",
            ),
            "exhibit-7-title": (
                ElementType.CAPTION,
                "EXHIBIT 7: Top 5 Costliest Insured Loss Events in 1H 2025",
            ),
            "exhibit-7-table": (
                ElementType.TABLE,
                None,
            ),
            "transition-paragraph": (
                ElementType.PARAGRAPH,
                "Natural catastrophes in the United States accounted for "
                "more than 90 percent of global insured losses in the first "
                "half of 2025, reaching approximately $92 billion. Meanwhile, "
                "1H insured losses in all other regions were significantly "
                "lower compared to their long-term averages.",
            ),
            "exhibit-8-title": (
                ElementType.CAPTION,
                "EXHIBIT 8: 1H Insured Losses by Region (2025 $B)",
            ),
            "exhibit-8-chart": (
                ElementType.CHART,
                None,
            ),
            "chart-source-note": (
                ElementType.SOURCE_NOTE,
                "Data: Aon Catastrophe Insight",
            ),
            "footer-title": (
                ElementType.FOOTER,
                "1H 2025 Global Catastrophe Recap",
            ),
            "printed-page-label": (
                ElementType.PRINTED_PAGE_LABEL,
                "7",
            ),
        }
        actual_elements = {
            element.element_id: (element.element_type, element.text)
            for element in self.elements
        }
        if actual_elements != expected_elements:
            raise ValueError(
                "all source element IDs, types, and text must match the source"
            )
        expected_element_semantics = {
            "logo-aon": (TruthClass.VISIBLE_TEXT, True),
            "intro-paragraph": (TruthClass.VISIBLE_TEXT, False),
            "damaged-sentence": (TruthClass.VISIBLE_TEXT, True),
            "exhibit-7-title": (TruthClass.VISIBLE_TEXT, True),
            "exhibit-7-table": (TruthClass.NATIVE_DATA, True),
            "transition-paragraph": (TruthClass.VISIBLE_TEXT, False),
            "exhibit-8-title": (TruthClass.VISIBLE_TEXT, True),
            "exhibit-8-chart": (TruthClass.NATIVE_DATA, False),
            "chart-source-note": (TruthClass.VISIBLE_TEXT, True),
            "footer-title": (TruthClass.VISIBLE_TEXT, True),
            "printed-page-label": (TruthClass.VISIBLE_TEXT, True),
        }
        actual_element_semantics = {
            element.element_id: (
                element.truth_class,
                element.include_in_exact_parity,
            )
            for element in self.elements
        }
        if actual_element_semantics != expected_element_semantics:
            raise ValueError(
                "source elements must retain reviewed truth and parity classes"
            )
        elements_by_id = {
            element.element_id: element for element in self.elements
        }
        top_level_order = [
            "logo-aon",
            "intro-paragraph",
            "exhibit-7-title",
            "exhibit-7-table",
            "transition-paragraph",
            "exhibit-8-title",
            "exhibit-8-chart",
            "chart-source-note",
            "footer-title",
            "printed-page-label",
        ]
        if any(
            elements_by_id[later].bbox.y < elements_by_id[earlier].bbox.y
            for earlier, later in pairwise(top_level_order)
        ):
            raise ValueError(
                "source element bboxes must follow reviewed top-to-bottom order"
            )
        damaged = elements_by_id["damaged-sentence"].bbox
        intro = elements_by_id["intro-paragraph"].bbox
        geometry_slack = self.chart_calibration.coordinate_quantization_pt
        if (
            damaged.x < intro.x - geometry_slack
            or damaged.y < intro.y - geometry_slack
            or damaged.right > intro.right + geometry_slack
            or damaged.bottom > intro.bottom + geometry_slack
        ):
            raise ValueError(
                "damaged sentence bbox must remain within the intro paragraph"
            )
        if elements_by_id["exhibit-7-table"].bbox != self.table.bbox:
            raise ValueError(
                "Exhibit 7 element bbox must match its table definition"
            )
        if (
            elements_by_id["exhibit-8-chart"].bbox
            != self.chart_calibration.source_bbox
        ):
            raise ValueError(
                "Exhibit 8 element bbox must match its chart calibration"
            )
        for relationship in self.relationships:
            if (
                relationship.truth_class is not TruthClass.INFERRED
                or relationship.include_in_exact_parity
            ):
                raise ValueError(
                    "source relationships must remain inferred and non-exact"
                )
            if relationship.source_id not in element_ids:
                raise ValueError("relationship source_id must reference an element")
            if relationship.target_id not in element_ids:
                raise ValueError("relationship target_id must reference an element")
            if relationship.source_id == relationship.target_id:
                raise ValueError("relationships cannot be self-referential")
        expected_relationships = {
            (
                RelationshipType.CONTAINS,
                "intro-paragraph",
                "damaged-sentence",
            ),
            (
                RelationshipType.CAPTION_OF,
                "exhibit-7-title",
                "exhibit-7-table",
            ),
            (
                RelationshipType.CAPTION_OF,
                "exhibit-8-title",
                "exhibit-8-chart",
            ),
            (
                RelationshipType.SOURCE_NOTE_OF,
                "chart-source-note",
                "exhibit-8-chart",
            ),
            (
                RelationshipType.FOOTER_PAIR,
                "footer-title",
                "printed-page-label",
            ),
        }
        actual_relationships = {
            (
                relationship.relationship_type,
                relationship.source_id,
                relationship.target_id,
            )
            for relationship in self.relationships
        }
        if (
            actual_relationships != expected_relationships
            or len(self.relationships) != len(expected_relationships)
        ):
            raise ValueError(
                "all five source-reviewed relationships must match the source"
            )

    def _validate_table(self) -> None:
        element_ids = {element.element_id for element in self.elements}
        if self.table.element_id not in element_ids:
            raise ValueError("table definition must reference a registered element")
        if (
            self.table.truth_class is not TruthClass.NATIVE_DATA
            or not self.table.include_in_exact_parity
        ):
            raise ValueError(
                "Exhibit 7 definition must remain native-data exact truth"
            )
        if self.table.rows != 6 or self.table.columns != 5:
            raise ValueError("Exhibit 7 must be a 6x5 table")
        if self.table.cell_count != 30:
            raise ValueError("Exhibit 7 must declare 30 cells")
        if self.table.header_row_count != 1:
            raise ValueError("Exhibit 7 must declare one header row")
        if self.table.all_row_spans != 1 or self.table.all_col_spans != 1:
            raise ValueError("Exhibit 7 must declare unspanned cells")
        if len(self.table.grid_x_pt) != 6 or len(self.table.grid_y_pt) != 7:
            raise ValueError("Exhibit 7 grid boundaries are incomplete")
        if any(
            later <= earlier for earlier, later in pairwise(self.table.grid_x_pt)
        ) or any(
            later <= earlier for earlier, later in pairwise(self.table.grid_y_pt)
        ):
            raise ValueError("Exhibit 7 grid boundaries must strictly increase")

        occupied: set[tuple[int, int]] = set()
        for cell in self.table_cells:
            if cell.table_id != self.table.element_id:
                raise ValueError("table cell references the wrong table")
            if cell.truth_class is not TruthClass.NATIVE_DATA:
                raise ValueError("Exhibit 7 cells must use native-data truth")
            if not cell.include_in_exact_parity:
                raise ValueError("Exhibit 7 cells must be eligible for exact parity")
            if not _bbox_contains(self.table.bbox, cell.bbox):
                raise ValueError("table cell bbox lies outside Exhibit 7")
            for row in range(cell.row, cell.row + cell.row_span):
                for column in range(cell.column, cell.column + cell.col_span):
                    if row >= self.table.rows or column >= self.table.columns:
                        raise ValueError("table span lies outside Exhibit 7")
                    position = (row, column)
                    if position in occupied:
                        raise ValueError("table cells overlap through a false span")
                    occupied.add(position)
        expected = {
            (row, column)
            for row in range(self.table.rows)
            for column in range(self.table.columns)
        }
        if occupied != expected:
            raise ValueError("Exhibit 7 must contain 30 explicit cell positions")
        if any(
            cell.row_span != 1 or cell.col_span != 1
            for cell in self.table_cells
        ):
            raise ValueError("Exhibit 7 must not contain fabricated spans")
        expected_text = (
            (
                "Date(s)",
                "Event",
                "Location",
                "Fatalities",
                "Insured Loss ($B)",
            ),
            (
                "01/07-01/28",
                "Palisades Fire",
                "United States",
                "12",
                "23.0",
            ),
            (
                "01/07-01/28",
                "Eaton Fire",
                "United States",
                "18",
                "17.5",
            ),
            (
                "03/14-03/16",
                "Severe Convective Storm",
                "United States",
                "43",
                "8.0",
            ),
            (
                "05/14-05/16",
                "Severe Convective Storm",
                "United States",
                "30",
                "8.0",
            ),
            (
                "05/17-05/20",
                "Severe Convective Storm",
                "United States",
                "0",
                "4.0",
            ),
        )
        grid_tolerance_pt = 0.01
        for cell in self.table_cells:
            if cell.annotation_id != (
                f"cell-exhibit-7-r{cell.row}-c{cell.column}"
            ):
                raise ValueError(
                    "table cell annotation IDs must match their grid positions"
                )
            if cell.text != expected_text[cell.row][cell.column]:
                raise ValueError(
                    "Exhibit 7 cell text must match its reviewed grid position"
                )
            expected_bbox = (
                self.table.grid_x_pt[cell.column],
                self.table.grid_y_pt[cell.row],
                (
                    self.table.grid_x_pt[cell.column + cell.col_span]
                    - self.table.grid_x_pt[cell.column]
                ),
                (
                    self.table.grid_y_pt[cell.row + cell.row_span]
                    - self.table.grid_y_pt[cell.row]
                ),
            )
            if any(
                abs(actual - expected) > grid_tolerance_pt
                for actual, expected in zip(
                    cell.bbox.root,
                    expected_bbox,
                    strict=True,
                )
            ):
                raise ValueError(
                    "table cell bbox must match its declared grid slot"
                )

    def _validate_chart(self) -> None:
        calibration = self.chart_calibration
        if (
            calibration.calibration_id
            != "exhibit-8-vector-axis-calibration"
            or calibration.chart_id != "exhibit-8-chart"
            or calibration.annotation_id != "chart-calibration-exhibit-8"
        ):
            raise ValueError(
                "chart calibration must retain its stable source identity"
            )
        if (
            calibration.truth_class is not TruthClass.MEASURED
            or calibration.include_in_exact_parity
        ):
            raise ValueError(
                "chart calibration must remain measured and non-exact"
            )
        if calibration.unit is not MetricUnit.BILLIONS_2025_USD:
            raise ValueError("chart calibration must use 2025_USD_billions")
        if len(calibration.ticks) != 5:
            raise ValueError("chart calibration must record all five printed ticks")
        if {tick.value_2025_usd_billions for tick in calibration.ticks} != {
            25.0,
            50.0,
            75.0,
            100.0,
            125.0,
        }:
            raise ValueError("chart calibration tick values are incomplete")
        tick_values = [tick.value for tick in calibration.ticks]
        tick_positions = [tick.y_pt for tick in calibration.ticks]
        if tick_values != sorted(tick_values):
            raise ValueError("chart calibration tick values must increase")
        if tick_positions != sorted(tick_positions, reverse=True):
            raise ValueError("chart calibration y positions must decrease")
        if calibration.baseline_value != 0 or not calibration.baseline_value_is_inferred:
            raise ValueError("chart calibration must declare its inferred zero baseline")
        if calibration.intermediate_year_assignments.count != 32:
            raise ValueError(
                "chart calibration must record all 32 inferred intermediate years"
            )
        for tick in calibration.ticks:
            expected_y = (
                calibration.baseline_y_pt
                - tick.value * calibration.points_per_usd_billion
            )
            if (
                abs(tick.y_pt - expected_y)
                > calibration.coordinate_quantization_pt
            ):
                raise ValueError("chart calibration tick does not fit the linear axis")

        element_ids = {element.element_id for element in self.elements}
        if calibration.chart_id not in element_ids:
            raise ValueError("chart calibration must reference a chart element")
        for label in self.chart_labels:
            if label.parent_chart_id != calibration.chart_id:
                raise ValueError("chart label references the wrong chart")
            if not _bbox_contains(calibration.source_bbox, label.bbox):
                raise ValueError("chart label bbox lies outside Exhibit 8")
        expected_labels = {
            ("panel", panel, panel)
            for panel in ("Americas", "APAC", "EMEA", "USA")
        }
        expected_labels |= {
            ("axis_tick", None, value)
            for value in ("125", "100", "75", "50", "25")
        }
        expected_labels |= {
            ("year_anchor", panel, year)
            for panel in ("Americas", "APAC", "EMEA", "USA")
            for year in ("2015", "2020", "2025")
        }
        expected_labels |= {
            ("legend", None, value)
            for value in ("Annual total", "1H")
        }
        actual_labels = {
            (label.label_type, label.panel, label.text)
            for label in self.chart_labels
        }
        if actual_labels != expected_labels:
            raise ValueError("all 23 printed chart labels must match the source")
        labels_by_key = {
            (label.label_type, label.panel, label.text): label
            for label in self.chart_labels
        }
        panel_labels = [
            labels_by_key[("panel", panel, panel)]
            for panel in ("Americas", "APAC", "EMEA", "USA")
        ]
        if any(
            later.bbox.x <= earlier.bbox.x
            for earlier, later in pairwise(panel_labels)
        ):
            raise ValueError("printed panel labels must remain in source x order")
        for panel in ("Americas", "APAC", "EMEA", "USA"):
            anchors = [
                labels_by_key[("year_anchor", panel, year)]
                for year in ("2015", "2020", "2025")
            ]
            if any(
                later.bbox.x <= earlier.bbox.x
                for earlier, later in pairwise(anchors)
            ):
                raise ValueError(
                    "printed year anchors must remain in source x order"
                )
        axis_labels = [
            labels_by_key[("axis_tick", None, value)]
            for value in ("125", "100", "75", "50", "25")
        ]
        if any(
            later.bbox.y <= earlier.bbox.y
            for earlier, later in pairwise(axis_labels)
        ):
            raise ValueError(
                "printed axis labels must remain in source y order"
            )
        ticks_by_value = {
            tick.value_2025_usd_billions: tick for tick in calibration.ticks
        }
        for label in axis_labels:
            label_center_y = label.bbox.y + label.bbox.h / 2
            tick_y = ticks_by_value[float(label.text)].page_y_pt
            if (
                abs(label_center_y - tick_y)
                > 2 * calibration.coordinate_quantization_pt
            ):
                raise ValueError(
                    "printed axis label must align with its calibration tick"
                )
        annual_legend = labels_by_key[("legend", None, "Annual total")]
        first_half_legend = labels_by_key[("legend", None, "1H")]
        if annual_legend.bbox.x >= first_half_legend.bbox.x:
            raise ValueError("printed legend labels must remain in source x order")

        for label in self.chart_labels:
            if label.label_type == "panel":
                expected_annotation_id = (
                    f"chart-label-panel-{label.text.lower()}"
                )
            elif label.label_type == "axis_tick":
                expected_annotation_id = f"chart-label-axis-{label.text}"
            elif label.label_type == "year_anchor":
                expected_annotation_id = (
                    f"chart-label-{label.panel.lower()}-{label.text}"
                )
            else:
                slug = (
                    "annual-total" if label.text == "Annual total" else "1h"
                )
                expected_annotation_id = f"chart-label-legend-{slug}"
            if label.annotation_id != expected_annotation_id:
                raise ValueError(
                    "chart label annotation IDs must match their source labels"
                )

        expected_keys = {
            (panel, year, series)
            for panel in ("Americas", "APAC", "EMEA", "USA")
            for year in range(2015, 2026)
            for series in ChartSeries
        }
        measurements = {
            (point.panel, point.year, point.series): point
            for point in self.chart_measurements
        }
        if set(measurements) != expected_keys:
            raise ValueError("chart must contain 88 unique panel/year/series points")
        for point in self.chart_measurements:
            series_slug = (
                "1h"
                if point.series is ChartSeries.FIRST_HALF
                else "annual-total"
            )
            identity_suffix = (
                f"{point.panel.lower()}-{point.year}-{series_slug}"
            )
            if point.measurement_id != f"measurement-{identity_suffix}":
                raise ValueError(
                    "measurement IDs must match panel/year/series identity"
                )
            if point.annotation_id != f"chart-measurement-{identity_suffix}":
                raise ValueError(
                    "measurement annotation IDs must match measurement identity"
                )
            if point.chart_id != calibration.chart_id:
                raise ValueError("chart measurement references the wrong chart")
            if point.calibration_id != calibration.calibration_id:
                raise ValueError("chart measurement references the wrong calibration")
            if point.measurement_method != calibration.measurement_method:
                raise ValueError("chart measurement method must match calibration")
            if point.tolerance != calibration.tolerance:
                raise ValueError("chart measurement tolerance must match calibration")
            if point.unit is not calibration.unit:
                raise ValueError("chart measurement unit must match calibration")
            if not _bbox_contains(calibration.source_bbox, point.source_bbox):
                raise ValueError("chart measurement bbox lies outside Exhibit 8")
            if (
                abs(point.source_bbox.bottom - calibration.baseline_y_pt)
                > calibration.coordinate_quantization_pt
            ):
                raise ValueError("chart measurement must terminate at the baseline")
            geometry_value = (
                calibration.baseline_y_pt - point.source_bbox.y
            ) / calibration.points_per_usd_billion
            geometry_rounding_band = (
                calibration.coordinate_quantization_pt
                / calibration.points_per_usd_billion
                + 0.02
            )
            if abs(point.value - geometry_value) > geometry_rounding_band:
                raise ValueError(
                    "chart measurement value does not match raw vector geometry"
                )
            point.metric_contract()
        panel_x_ranges: list[tuple[float, float]] = []
        for panel in ("Americas", "APAC", "EMEA", "USA"):
            year_x_positions: list[float] = []
            for year in range(2015, 2026):
                first_half_point = measurements[
                    (panel, year, ChartSeries.FIRST_HALF)
                ]
                annual_point = measurements[
                    (panel, year, ChartSeries.ANNUAL_TOTAL)
                ]
                if (
                    abs(first_half_point.source_bbox.x - annual_point.source_bbox.x)
                    > calibration.coordinate_quantization_pt
                    or abs(first_half_point.source_bbox.w - annual_point.source_bbox.w)
                    > calibration.coordinate_quantization_pt
                ):
                    raise ValueError(
                        "each annual/1H pair must share its source x position"
                    )
                year_x_positions.append(
                    (
                        first_half_point.source_bbox.x
                        + annual_point.source_bbox.x
                    )
                    / 2
                )
                if annual_point.value < first_half_point.value:
                    raise ValueError("annual total cannot be below 1H")
            if any(
                later - earlier <= calibration.coordinate_quantization_pt
                for earlier, later in pairwise(year_x_positions)
            ):
                raise ValueError(
                    "chart years must map left-to-right within each panel"
                )
            panel_x_ranges.append(
                (
                    year_x_positions[0],
                    max(
                        measurements[
                            (panel, 2025, series)
                        ].source_bbox.right
                        for series in ChartSeries
                    ),
                )
            )
        if any(
            earlier_right >= later_left
            for (_, earlier_right), (later_left, _) in pairwise(panel_x_ranges)
        ):
            raise ValueError(
                "chart panels must remain in Americas/APAC/EMEA/USA x order"
            )

    def _validate_negatives(self) -> None:
        negative_types = {
            annotation.negative_type for annotation in self.negative_annotations
        }
        if negative_types != set(NegativeType):
            raise ValueError("all four required negative controls must be recorded")
        expected_truth_classes = {
            NegativeType.DUPLICATE_TITLE: TruthClass.INFERRED,
            NegativeType.FALSE_ROW_SPAN: TruthClass.INFERRED,
            NegativeType.ANNUAL_BELOW_FIRST_HALF: TruthClass.INFERRED,
            NegativeType.UNSUPPORTED_EXACT_VALUE: TruthClass.UNKNOWABLE,
        }
        if any(
            annotation.truth_class
            is not expected_truth_classes[annotation.negative_type]
            for annotation in self.negative_annotations
        ):
            raise ValueError(
                "negative controls must retain their nonliteral truth classes"
            )
        expected_controls = {
            NegativeType.DUPLICATE_TITLE: (
                "negative-duplicate-title",
                {
                    "action": "duplicate_element",
                    "element_id": "exhibit-8-title",
                },
            ),
            NegativeType.FALSE_ROW_SPAN: (
                "negative-false-row-span",
                {
                    "action": "set_row_span",
                    "cell_annotation_id": "cell-exhibit-7-r1-c2",
                    "row_span": 5,
                },
            ),
            NegativeType.ANNUAL_BELOW_FIRST_HALF: (
                "negative-annual-below-1h",
                {
                    "panel": "Americas",
                    "year": 2023,
                    "annual_total": 2,
                    "1H": 3,
                },
            ),
            NegativeType.UNSUPPORTED_EXACT_VALUE: (
                "negative-unsupported-exact-value",
                {
                    "measurement_id": (
                        "measurement-americas-2015-annual-total"
                    ),
                    "truth_class": "visible_text",
                    "include_in_exact_parity": True,
                },
            ),
        }
        for annotation in self.negative_annotations:
            expected_id, expected_mutation = expected_controls[
                annotation.negative_type
            ]
            if (
                annotation.annotation_id != expected_id
                or annotation.mutation != expected_mutation
            ):
                raise ValueError(
                    "negative controls must retain executable mutation evidence"
                )


def load_catastrophe_source_truth(path: str | Path) -> CatastropheSourceTruth:
    """Load and validate a P00-US02 source-truth JSON artifact."""

    return CatastropheSourceTruth.model_validate_json(Path(path).read_bytes())
