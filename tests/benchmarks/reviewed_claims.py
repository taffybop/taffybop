"""Versioned reviewed-claim contracts for benchmark reporting only.

The contracts in this module classify source-review evidence and scoring
eligibility.  They are deliberately isolated under ``tests`` and must never be
imported by the production parser or public serializers.
"""

from __future__ import annotations

from collections import Counter
from enum import Enum
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from tests.benchmarks.contracts import (
    Annotation,
    CONTRACT_VERSION,
    ContractModel,
    LITERAL_EXACT_PARITY_CLASSES,
    NonEmptyString,
    SchemaVersion,
    Sha256,
    TruthClass,
)
from tests.benchmarks.corpus_registry import (
    PortableCorpusRegistry,
    canonical_registry_json,
)
from tests.benchmarks.source_truth import (
    BBox,
    CatastropheSourceTruth,
    ChartCalibration,
    ChartLabel,
    ChartMeasurement,
    ElementType,
    NegativeAnnotation,
    ReviewStatus as CatastropheReviewStatus,
    SourceElement,
    SourceRelationship,
    TableCell,
    TableDefinition,
)


REVIEWED_CLAIM_CONTRACT_VERSION = CONTRACT_VERSION
CATASTROPHE_TRUTH_PATH = (
    "tracker/phase-00-baseline/evidence/P00-US02-catastrophe-truth.json"
)
CATASTROPHE_TRUTH_SHA256 = (
    "d14d9f4bdbbffee24961d731b7bca75227eaec6bac77cce7508ded4252c9b4ac"
)

_STABLE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[a-z0-9._:-]*[a-z0-9])?$")
StableId = Annotated[str, Field(pattern=_STABLE_ID_PATTERN.pattern)]


class ClaimType(str, Enum):
    """Primary subject assessed by one source-review claim."""

    PAGE_IDENTITY = "page_identity"
    TEXT = "text"
    TEXT_STYLE = "text_style"
    STRUCTURE = "structure"
    RELATIONSHIP = "relationship"
    GEOMETRY = "geometry"
    TABLE = "table"
    CHART = "chart"
    IMAGE = "image"
    DIAGRAM = "diagram"
    FORM = "form"
    LINK = "link"
    METADATA = "metadata"
    ARTIFACT_INVENTORY = "artifact_inventory"
    CONTROL = "control"


class ClaimReviewStatus(str, Enum):
    """Normalized verdicts used by all 15 frozen case reviews."""

    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    NOT_INDEPENDENTLY_VERIFIABLE = "not_independently_verifiable"
    INCORRECT = "incorrect"
    POTENTIALLY_INFERRED = "potentially_inferred"


class RegionScope(str, Enum):
    """What kind of source or control region a locator identifies."""

    PAGE = "page"
    SOURCE_REGION = "source_region"
    SOURCE_OBJECT = "source_object"
    DERIVED_ARTIFACT = "derived_artifact"
    SYNTHETIC_CONTROL = "synthetic_control"


class CoordinateConvention(ContractModel):
    """Displayed-page geometry convention used by every locator."""

    origin: Literal["top_left"]
    unit: Literal["pt"]
    bbox_format: Literal["[x,y,width,height]"]
    page_space: Literal["displayed_after_source_rotation"]


DISPLAY_PAGE_COORDINATES = CoordinateConvention(
    origin="top_left",
    unit="pt",
    bbox_format="[x,y,width,height]",
    page_space="displayed_after_source_rotation",
)


class SourceLocator(ContractModel):
    """One registered physical page and reviewed region on that page."""

    case_id: StableId
    physical_page: int = Field(ge=1)
    printed_page: NonEmptyString | None
    region_id: StableId
    region_scope: RegionScope
    bbox: BBox | None
    coordinates: CoordinateConvention

    @field_validator("printed_page")
    @classmethod
    def require_trimmed_printed_page(cls, value: str | None) -> str | None:
        if value is not None and value != value.strip():
            raise ValueError(
                "printed page labels must not have surrounding whitespace"
            )
        return value


class ReviewerVersion(ContractModel):
    """Explicit reviewer identity and the version of their decision."""

    reviewer_id: NonEmptyString
    review_version: NonEmptyString

    @field_validator("reviewer_id", "review_version")
    @classmethod
    def require_trimmed_nonempty_value(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("reviewer identity and version must be trimmed")
        return value


class ReviewProvenance(ContractModel):
    """Stable row identity in the source review used to create a claim."""

    review_path: NonEmptyString
    review_sha256: Sha256
    review_row_id: StableId

    @field_validator("review_path")
    @classmethod
    def require_portable_review_path(cls, value: str) -> str:
        if value != value.strip() or "\\" in value or "\x00" in value:
            raise ValueError("review paths must be canonical portable paths")
        path = PurePosixPath(value)
        if (
            not value
            or path.is_absolute()
            or path.as_posix() != value
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or value.split("/", 1)[0].startswith("~")
            or ":" in value.split("/", 1)[0]
        ):
            raise ValueError("review paths must be canonical workspace-relative paths")
        return value


class InclusionMask(ContractModel):
    """Independent literal and semantic benchmark denominator decisions."""

    literal_parity: bool
    semantic_parity: bool

    @model_validator(mode="after")
    def require_literal_to_be_semantic(self) -> "InclusionMask":
        if self.literal_parity and not self.semantic_parity:
            raise ValueError("literal parity inclusion requires semantic inclusion")
        return self


class Derivation(ContractModel):
    """Method and uncertainty for a source-reviewed measured claim."""

    method: NonEmptyString
    tolerance: float = Field(ge=0, allow_inf_nan=False)
    tolerance_unit: NonEmptyString

    @field_validator("method", "tolerance_unit")
    @classmethod
    def require_trimmed_nonempty_value(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("derivation method and tolerance unit must be trimmed")
        return value


_UNSUPPORTED_REVIEW_STATUSES = {
    ClaimReviewStatus.INCORRECT,
    ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE,
    ClaimReviewStatus.POTENTIALLY_INFERRED,
}


class ReviewedClaimRecord(ContractModel):
    """One source-review assertion and its explicit scoring policy."""

    schema_version: SchemaVersion
    claim_id: StableId
    case_id: StableId
    claim_type: ClaimType
    claim: NonEmptyString
    evidence_class: TruthClass
    review_status: ClaimReviewStatus
    reviewer: ReviewerVersion
    provenance: ReviewProvenance
    locators: tuple[SourceLocator, ...] = Field(min_length=1)
    inclusion_mask: InclusionMask
    derivation: Derivation | None = None

    @field_validator("claim")
    @classmethod
    def require_trimmed_claim(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("claim text must be trimmed and nonempty")
        return value

    @model_validator(mode="after")
    def validate_evidence_and_scoring(self) -> "ReviewedClaimRecord":
        if any(locator.case_id != self.case_id for locator in self.locators):
            raise ValueError("every locator must use the claim case_id")

        locator_keys = [
            (
                locator.case_id,
                locator.physical_page,
                locator.printed_page,
                locator.region_id,
                locator.region_scope,
                locator.bbox.root if locator.bbox else None,
            )
            for locator in self.locators
        ]
        if len(locator_keys) != len(set(locator_keys)):
            raise ValueError("claim locators must be unique")

        if self.inclusion_mask.literal_parity:
            if self.review_status is not ClaimReviewStatus.VERIFIED:
                raise ValueError(
                    "literal parity requires review_status=verified"
                )
            if self.evidence_class not in LITERAL_EXACT_PARITY_CLASSES:
                raise ValueError(
                    "measured, inferred, or unknowable evidence cannot enter "
                    "literal parity"
                )

        if (
            self.review_status in _UNSUPPORTED_REVIEW_STATUSES
            and (
                self.inclusion_mask.literal_parity
                or self.inclusion_mask.semantic_parity
            )
        ):
            raise ValueError(
                "incorrect, potentially inferred, or not independently "
                "verifiable claims cannot enter parity denominators"
            )

        if self.evidence_class is TruthClass.MEASURED:
            if self.derivation is None:
                raise ValueError(
                    "measured evidence requires derivation method, tolerance, "
                    "and tolerance unit"
                )
        elif self.derivation is not None:
            raise ValueError(
                "derivation is only valid for evidence_class=measured"
            )
        return self

    def annotation_contract(self) -> Annotation:
        """Project to the unchanged P00-US01 annotation contract."""

        return Annotation(
            schema_version=self.schema_version,
            annotation_id=self.claim_id,
            fixture_id=self.case_id,
            truth_class=self.evidence_class,
            claim=self.claim,
            include_in_exact_parity=self.inclusion_mask.literal_parity,
        )


class ReviewBatch(ContractModel):
    """A deterministic, count-reconciled set of reviewed claims."""

    schema_version: SchemaVersion
    batch_id: StableId
    corpus_registry_sha256: Sha256
    claim_count: int = Field(gt=0)
    case_claim_counts: dict[StableId, int] = Field(min_length=1)
    claims: tuple[ReviewedClaimRecord, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_complete_batch(self) -> "ReviewBatch":
        if self.claim_count != len(self.claims):
            raise ValueError("claim_count must match the batch claims")

        claim_ids = [claim.claim_id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("claim IDs must be unique within a review batch")
        if claim_ids != sorted(claim_ids):
            raise ValueError("claims must use canonical claim_id order")

        provenance_keys = [
            (
                claim.provenance.review_path,
                claim.provenance.review_row_id,
            )
            for claim in self.claims
        ]
        if len(provenance_keys) != len(set(provenance_keys)):
            raise ValueError("review path/row identities must be unique")

        if any(claim.schema_version != self.schema_version for claim in self.claims):
            raise ValueError("every claim must use the batch schema version")

        actual_counts = dict(sorted(Counter(
            claim.case_id for claim in self.claims
        ).items()))
        declared_counts = dict(sorted(self.case_claim_counts.items()))
        if any(count <= 0 for count in declared_counts.values()):
            raise ValueError("case claim counts must be positive")
        if declared_counts != actual_counts:
            raise ValueError("case_claim_counts must match the batch claims")
        return self


class ReviewRegistryError(ValueError):
    """A claim batch does not reconcile with the portable corpus registry."""


def canonical_review_batch_json(batch: ReviewBatch) -> str:
    """Serialize one validated review batch deterministically."""

    return json.dumps(
        batch.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def review_batch_sha256(batch: ReviewBatch) -> str:
    """Return the deterministic semantic identity of one claim batch."""

    return hashlib.sha256(
        canonical_review_batch_json(batch).encode("utf-8")
    ).hexdigest()


def corpus_registry_sha256(registry: PortableCorpusRegistry) -> str:
    """Return the canonical semantic identity expected by review batches."""

    return hashlib.sha256(
        canonical_registry_json(registry).encode("utf-8")
    ).hexdigest()


def load_review_batch(path: str | Path) -> ReviewBatch:
    """Load and validate a versioned review batch."""

    return ReviewBatch.model_validate_json(Path(path).read_bytes())


def validate_review_batch_against_registry(
    batch: ReviewBatch,
    registry: PortableCorpusRegistry,
) -> ReviewBatch:
    """Fail closed on unknown cases/pages, label drift, or invalid geometry."""

    current_registry_sha256 = corpus_registry_sha256(registry)
    if batch.corpus_registry_sha256 != current_registry_sha256:
        raise ReviewRegistryError(
            "review batch corpus_registry_sha256 does not match the registry"
        )

    for claim in batch.claims:
        try:
            case = registry.case_by_id(claim.case_id)
        except KeyError as exc:
            raise ReviewRegistryError(
                f"{claim.claim_id} uses unregistered case {claim.case_id}"
            ) from exc
        pages = {
            page.physical_page: page
            for page in case.pages
        }
        for locator in claim.locators:
            page = pages.get(locator.physical_page)
            if page is None:
                raise ReviewRegistryError(
                    f"{claim.claim_id} uses unregistered physical page "
                    f"{locator.physical_page}"
                )
            if locator.printed_page != page.printed_page:
                raise ReviewRegistryError(
                    f"{claim.claim_id} printed page does not match the registry"
                )
            if locator.coordinates != DISPLAY_PAGE_COORDINATES:
                raise ReviewRegistryError(
                    f"{claim.claim_id} uses an unsupported coordinate convention"
                )
            if locator.bbox is not None and (
                locator.bbox.right > page.width_pt
                or locator.bbox.bottom > page.height_pt
            ):
                raise ReviewRegistryError(
                    f"{claim.claim_id} bbox lies outside the registered page"
                )
    return batch


def _catastrophe_claims(
    truth: CatastropheSourceTruth,
) -> tuple[
    SourceElement
    | SourceRelationship
    | TableDefinition
    | TableCell
    | ChartCalibration
    | ChartLabel
    | ChartMeasurement
    | NegativeAnnotation,
    ...,
]:
    return (
        *truth.elements,
        *truth.relationships,
        truth.table,
        *truth.table_cells,
        truth.chart_calibration,
        *truth.chart_labels,
        *truth.chart_measurements,
        *truth.negative_annotations,
    )


def _element_claim_type(element: SourceElement) -> ClaimType:
    if element.type is ElementType.LOGO:
        return ClaimType.IMAGE
    if element.type is ElementType.TABLE:
        return ClaimType.TABLE
    if element.type is ElementType.CHART:
        return ClaimType.CHART
    if element.type is ElementType.PRINTED_PAGE_LABEL:
        return ClaimType.PAGE_IDENTITY
    return ClaimType.TEXT


def _claim_type(
    claim: SourceElement
    | SourceRelationship
    | TableDefinition
    | TableCell
    | ChartCalibration
    | ChartLabel
    | ChartMeasurement
    | NegativeAnnotation,
) -> ClaimType:
    if isinstance(claim, SourceElement):
        return _element_claim_type(claim)
    if isinstance(claim, SourceRelationship):
        return ClaimType.RELATIONSHIP
    if isinstance(claim, (TableDefinition, TableCell)):
        return ClaimType.TABLE
    if isinstance(claim, (ChartCalibration, ChartLabel, ChartMeasurement)):
        return ClaimType.CHART
    return ClaimType.CONTROL


def _bbox_locator(
    truth: CatastropheSourceTruth,
    *,
    region_id: str,
    region_scope: RegionScope,
    bbox: BBox | None,
) -> SourceLocator:
    return SourceLocator(
        case_id=truth.fixture.fixture_id,
        physical_page=truth.page.physical_page,
        printed_page=truth.page.printed_page,
        region_id=region_id,
        region_scope=region_scope,
        bbox=bbox,
        coordinates=DISPLAY_PAGE_COORDINATES,
    )


def _catastrophe_locators(
    claim: SourceElement
    | SourceRelationship
    | TableDefinition
    | TableCell
    | ChartCalibration
    | ChartLabel
    | ChartMeasurement
    | NegativeAnnotation,
    truth: CatastropheSourceTruth,
) -> tuple[SourceLocator, ...]:
    if isinstance(claim, SourceElement):
        return (
            _bbox_locator(
                truth,
                region_id=f"element:{claim.element_id}",
                region_scope=RegionScope.SOURCE_OBJECT,
                bbox=claim.bbox,
            ),
        )
    if isinstance(claim, SourceRelationship):
        elements = {
            element.element_id: element
            for element in truth.elements
        }
        return tuple(
            _bbox_locator(
                truth,
                region_id=f"element:{element_id}",
                region_scope=RegionScope.SOURCE_OBJECT,
                bbox=elements[element_id].bbox,
            )
            for element_id in (claim.source_id, claim.target_id)
        )
    if isinstance(claim, TableDefinition):
        return (
            _bbox_locator(
                truth,
                region_id=f"table:{claim.table_id}",
                region_scope=RegionScope.SOURCE_OBJECT,
                bbox=claim.bbox,
            ),
        )
    if isinstance(claim, TableCell):
        return (
            _bbox_locator(
                truth,
                region_id=(
                    f"table:{claim.table_id}:r{claim.row}:c{claim.column}"
                ),
                region_scope=RegionScope.SOURCE_OBJECT,
                bbox=claim.bbox,
            ),
        )
    if isinstance(claim, ChartCalibration):
        return (
            _bbox_locator(
                truth,
                region_id=f"chart:{claim.chart_id}:calibration",
                region_scope=RegionScope.SOURCE_REGION,
                bbox=claim.source_bbox,
            ),
        )
    if isinstance(claim, ChartLabel):
        return (
            _bbox_locator(
                truth,
                region_id=f"chart:{claim.parent_chart_id}:label:{claim.annotation_id}",
                region_scope=RegionScope.SOURCE_OBJECT,
                bbox=claim.bbox,
            ),
        )
    if isinstance(claim, ChartMeasurement):
        return (
            _bbox_locator(
                truth,
                region_id=f"chart:{claim.chart_id}:mark:{claim.measurement_id}",
                region_scope=RegionScope.SOURCE_OBJECT,
                bbox=claim.raw_mark_bbox,
            ),
        )
    return (
        _bbox_locator(
            truth,
            region_id=f"control:{claim.negative_type.value}",
            region_scope=RegionScope.SYNTHETIC_CONTROL,
            bbox=None,
        ),
    )


def _catastrophe_derivation(
    claim: SourceElement
    | SourceRelationship
    | TableDefinition
    | TableCell
    | ChartCalibration
    | ChartLabel
    | ChartMeasurement
    | NegativeAnnotation,
) -> Derivation | None:
    if isinstance(claim, ChartCalibration):
        return Derivation(
            method=claim.method,
            tolerance=claim.tolerance,
            tolerance_unit=claim.unit.value,
        )
    if isinstance(claim, ChartMeasurement):
        return Derivation(
            method=claim.method,
            tolerance=claim.tolerance,
            tolerance_unit=claim.unit.value,
        )
    return None


def project_catastrophe_truth(
    truth: CatastropheSourceTruth,
    registry: PortableCorpusRegistry,
) -> ReviewBatch:
    """Backward-read all 163 frozen P00-US02 claims without mutating them."""

    if truth.fixture.fixture_id != "catastrophe-recap":
        raise ValueError("catastrophe projection requires catastrophe-recap truth")

    records = []
    for claim in _catastrophe_claims(truth):
        if claim.review_status is not CatastropheReviewStatus.VERIFIED:
            raise ValueError("catastrophe projection requires reviewed claims")
        records.append(
            ReviewedClaimRecord(
                schema_version=claim.schema_version,
                claim_id=claim.annotation_id,
                case_id=claim.fixture_id,
                claim_type=_claim_type(claim),
                claim=claim.claim,
                evidence_class=claim.truth_class,
                review_status=ClaimReviewStatus.VERIFIED,
                reviewer=ReviewerVersion(
                    reviewer_id=claim.reviewer,
                    review_version=claim.review_version,
                ),
                provenance=ReviewProvenance(
                    review_path=CATASTROPHE_TRUTH_PATH,
                    review_sha256=CATASTROPHE_TRUTH_SHA256,
                    review_row_id=claim.annotation_id,
                ),
                locators=_catastrophe_locators(claim, truth),
                inclusion_mask=InclusionMask(
                    literal_parity=claim.include_in_exact_parity,
                    semantic_parity=True,
                ),
                derivation=_catastrophe_derivation(claim),
            )
        )

    ordered = tuple(sorted(records, key=lambda record: record.claim_id))
    batch = ReviewBatch(
        schema_version=REVIEWED_CLAIM_CONTRACT_VERSION,
        batch_id="p00-us02-catastrophe-backward-read",
        corpus_registry_sha256=corpus_registry_sha256(registry),
        claim_count=len(ordered),
        case_claim_counts={"catastrophe-recap": len(ordered)},
        claims=ordered,
    )
    return validate_review_batch_against_registry(batch, registry)
