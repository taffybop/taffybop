"""Source-faithful chart assets and terminal presentation arbitration.

This module is intentionally independent of chart recognition.  It accepts
only a chart owner that has already passed the Phase 05 admission boundary,
renders that owner's exact bounded region, and exposes a closed inline PNG
contract.  The retained pixels are evidence; they never make extracted chart
values authoritative.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import importlib.metadata
import io
import json
import math
import multiprocessing
import os
import re
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import pypdfium2 as pdfium
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.visual_chart_validation import (
    replay_chart_serialization,
    validate_and_serialize_chart,
)
from app.services.visual_contracts import VisualBoundingBox, VisualStructure


_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
_PNG_PREFIX = "data:image/png;base64,"
_MAX_ASSET_BYTES = 8 * 1024 * 1024
_MAX_ASSET_PIXELS = 16_000_000
_MAX_DATA_URI_LENGTH = len(_PNG_PREFIX) + 4 * ((_MAX_ASSET_BYTES + 2) // 3)
_MAX_TRANSCRIPT_CHARS = 65_536
_MAX_REFERENCES = 64
_PUBLIC_DATA_URI_COPIES = 6
_OWNER_GEOMETRY_DECIMALS = 3
_OWNER_MAX_PAGE_ITEMS = 4_096
_OWNER_MAX_DETECTED_IMAGES = 256
_OWNER_MAX_RAW_PICTURES = 256
_OWNER_MIN_RECIPROCAL_COVERAGE = 0.95
_OWNER_MAX_MAPPING_TOLERANCE_RATIO = 0.015
_OWNER_MIN_MAPPING_TOLERANCE = 1.5
_OWNER_MATERIAL_OVERLAP_OF_SMALLER = 0.50
_NUMERIC_TOKEN_RE = re.compile(
    r"(?:^|\s)[+-]?(?:[$\u00a3\u00a5\u20ac\u20b9]\s*)?\d[\d,.]*(?:%|\b)"
)

FiniteNumber = Annotated[float, Field(allow_inf_nan=False)]
ConfidenceNumber = Annotated[
    float,
    Field(ge=0.0, le=1.0, allow_inf_nan=False),
]


class ChartAssetContract(BaseModel):
    """Closed, non-coercing FFD-015 public data."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    @model_validator(mode="before")
    @classmethod
    def require_exact_object(cls, value: Any) -> Any:
        if type(value) is cls:
            return value
        if type(value) is not dict:
            raise ValueError("chart-asset values must be exact objects")
        return value


class ChartConfidence(ChartAssetContract):
    value: ConfidenceNumber | None = None
    unavailable_reason: Literal[
        "not_calibrated",
        "source_confidence_unavailable",
        "asset_unavailable",
    ] | None = None

    @model_validator(mode="after")
    def validate_state(self) -> "ChartConfidence":
        if (self.value is None) == (self.unavailable_reason is None):
            raise ValueError("chart confidence requires a value or reason")
        return self


class ChartConfidenceDimensions(ChartAssetContract):
    ownership: ChartConfidence
    transcription: ChartConfidence
    family: ChartConfidence
    complexity: ChartConfidence


class ChartOwnerGeometryProof(ChartAssetContract):
    """Independent, source-bound proof for one exact chart crop owner."""

    schema_version: Literal["1.0"]
    policy_id: Literal["ffd-015-chart-owner-geometry-v1"]
    source_document_sha256: str = Field(pattern=_SHA256_PATTERN)
    render_source_sha256: str = Field(pattern=_SHA256_PATTERN)
    owner_item_id: str = Field(min_length=1, max_length=512)
    page_index: int = Field(ge=1, le=1_000_000)
    owner_bbox: VisualBoundingBox
    input_kind: Literal["pdf", "image"]
    proof_kind: Literal[
        "detected_image",
        "docling_picture",
        "detected_image_and_docling_picture",
    ]
    source_evidence_ids: list[str] = Field(min_length=1, max_length=2)
    source_evidence_sha256: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_proof(self) -> "ChartOwnerGeometryProof":
        if self.owner_bbox.width <= 0 or self.owner_bbox.height <= 0:
            raise ValueError("chart owner proof bbox has no area")
        if self.source_evidence_ids != list(dict.fromkeys(self.source_evidence_ids)):
            raise ValueError("chart owner proof evidence repeats")
        expected_count = (
            2
            if self.proof_kind == "detected_image_and_docling_picture"
            else 1
        )
        if len(self.source_evidence_ids) != expected_count:
            raise ValueError("chart owner proof evidence count differs")
        return self


class ChartTranscript(ChartAssetContract):
    status: Literal["available", "unavailable"]
    source: Literal["native", "ocr", "mixed", "source_labels"] | None = None
    text: str | None = Field(default=None, max_length=_MAX_TRANSCRIPT_CHARS)
    text_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    evidence_ids: list[str] = Field(default_factory=list, max_length=_MAX_REFERENCES)
    confidence: ChartConfidence

    @model_validator(mode="after")
    def validate_transcript(self) -> "ChartTranscript":
        if self.evidence_ids != list(dict.fromkeys(self.evidence_ids)):
            raise ValueError("chart transcript evidence order repeats")
        if self.status == "available":
            if self.source is None or self.text is None or not self.text:
                raise ValueError("available chart transcript is incomplete")
            if not self.evidence_ids:
                raise ValueError("available chart transcript lacks source evidence")
            if self.text_sha256 != hashlib.sha256(
                self.text.encode("utf-8", errors="strict")
            ).hexdigest():
                raise ValueError("chart transcript digest differs")
        elif self.evidence_ids or any(
            value is not None for value in (self.source, self.text, self.text_sha256)
        ):
            raise ValueError("unavailable chart transcript carries content")
        return self


class ChartFamilyClassification(ChartAssetContract):
    status: Literal["classified", "undetermined", "not_run"]
    family: Literal[
        "bar",
        "line",
        "pie",
        "area",
        "scatter",
        "bubble",
        "mixed",
        "multi_panel",
        "other",
        "undetermined",
    ]
    classifier_version: Literal["chart-family-source-evidence-v1"]
    reason_codes: list[
        Literal[
            "declared_classifier_family",
            "native_office_family",
            "multiple_family_signals",
            "insufficient_source_features",
            "asset_unavailable",
        ]
    ] = Field(min_length=1, max_length=8)
    evidence_ids: list[str] = Field(default_factory=list, max_length=_MAX_REFERENCES)
    confidence: ChartConfidence

    @model_validator(mode="after")
    def validate_classification(self) -> "ChartFamilyClassification":
        if self.reason_codes != list(dict.fromkeys(self.reason_codes)):
            raise ValueError("chart family reasons repeat")
        if self.evidence_ids != list(dict.fromkeys(self.evidence_ids)):
            raise ValueError("chart family evidence repeats")
        if self.status == "classified" and self.family == "undetermined":
            raise ValueError("chart family state differs")
        if self.status in {"undetermined", "not_run"} and self.family != "undetermined":
            raise ValueError("chart family state differs")
        if self.status == "not_run" and self.reason_codes != ["asset_unavailable"]:
            raise ValueError("not-run chart family reasons differ")
        if self.status == "not_run" and (
            self.evidence_ids
            or self.confidence.value is not None
            or self.confidence.unavailable_reason != "asset_unavailable"
        ):
            raise ValueError("not-run chart family evidence differs")
        if self.status == "undetermined" and self.reason_codes not in (
            ["insufficient_source_features"],
            ["multiple_family_signals"],
        ):
            raise ValueError("undetermined chart family reasons differ")
        return self


class ChartComplexityClassification(ChartAssetContract):
    status: Literal["regular", "complex", "undetermined", "not_run"]
    classifier_version: Literal["chart-complexity-source-evidence-v1"]
    reason_codes: list[
        Literal[
            "single_supported_family",
            "multi_panel_geometry",
            "multiple_axes",
            "multiple_legends",
            "multiple_mark_types",
            "dense_source_labels",
            "multi_encoding_family",
            "insufficient_source_features",
            "asset_unavailable",
        ]
    ] = Field(min_length=1, max_length=8)
    evidence_ids: list[str] = Field(default_factory=list, max_length=_MAX_REFERENCES)
    confidence: ChartConfidence

    @model_validator(mode="after")
    def validate_classification(self) -> "ChartComplexityClassification":
        if self.reason_codes != list(dict.fromkeys(self.reason_codes)):
            raise ValueError("chart complexity reasons repeat")
        if self.evidence_ids != list(dict.fromkeys(self.evidence_ids)):
            raise ValueError("chart complexity evidence repeats")
        complex_reasons = {
            "multi_panel_geometry",
            "multiple_axes",
            "multiple_legends",
            "multiple_mark_types",
            "dense_source_labels",
            "multi_encoding_family",
        }
        if self.status == "complex" and not complex_reasons.intersection(
            self.reason_codes
        ):
            raise ValueError("complex chart lacks source feature evidence")
        if self.status == "regular" and self.reason_codes != [
            "single_supported_family"
        ]:
            raise ValueError("regular chart reasons differ")
        if self.status == "undetermined" and self.reason_codes != [
            "insufficient_source_features"
        ]:
            raise ValueError("undetermined chart reasons differ")
        if self.status == "not_run" and self.reason_codes != ["asset_unavailable"]:
            raise ValueError("not-run chart complexity reasons differ")
        if self.status == "not_run" and (
            self.evidence_ids
            or self.confidence.value is not None
            or self.confidence.unavailable_reason != "asset_unavailable"
        ):
            raise ValueError("not-run chart complexity evidence differs")
        return self


class ChartSourceAsset(ChartAssetContract):
    asset_id: str = Field(pattern=_ID_PATTERN)
    source_document_sha256: str = Field(pattern=_SHA256_PATTERN)
    render_source_sha256: str = Field(pattern=_SHA256_PATTERN)
    owner_item_id: str = Field(min_length=1, max_length=512)
    physical_page: int = Field(ge=1, le=1_000_000)
    source_bbox: VisualBoundingBox
    owner_geometry_proof_kind: Literal[
        "detected_image",
        "docling_picture",
        "detected_image_and_docling_picture",
    ]
    owner_geometry_evidence_ids: list[str] = Field(min_length=1, max_length=2)
    owner_geometry_evidence_sha256: str = Field(pattern=_SHA256_PATTERN)
    rendered_bbox: VisualBoundingBox
    coordinate_system: Literal["page_top_left"]
    pixel_to_page_transform: list[FiniteNumber] = Field(min_length=6, max_length=6)
    page_device_dimensions: list[int] | None = Field(
        default=None,
        min_length=2,
        max_length=2,
    )
    crop_device_margins: list[int] | None = Field(
        default=None,
        min_length=4,
        max_length=4,
    )
    renderer: Literal["pypdfium2", "pillow"]
    renderer_version: str = Field(min_length=1, max_length=64)
    render_policy: Literal["chart-source-inline-png-v1"]
    source_kind: Literal["pdf", "image"]
    render_scale: FiniteNumber = Field(gt=0.0, le=16.0)
    effective_dpi: FiniteNumber | None = Field(default=None, gt=0.0, le=1_152.0)
    width: int = Field(ge=1, le=8_192)
    height: int = Field(ge=1, le=8_192)
    mime_type: Literal["image/png"]
    encoding: Literal["data_uri_base64"]
    byte_length: int = Field(ge=1, le=_MAX_ASSET_BYTES)
    sha256: str = Field(pattern=_SHA256_PATTERN)
    data_uri: str = Field(min_length=len(_PNG_PREFIX) + 4, max_length=_MAX_DATA_URI_LENGTH)
    color_space: Literal["srgb"]
    alpha_policy: Literal["flatten_white"]
    antialiasing_policy: Literal["renderer_default"]
    interpolation_policy: Literal["none"]
    bbox_rounding: Literal["outward_device_pixels", "exact_integer"]
    padding: FiniteNumber = Field(ge=0.0, le=0.0)

    @model_validator(mode="after")
    def validate_asset(self) -> "ChartSourceAsset":
        if self.source_bbox.width <= 0 or self.source_bbox.height <= 0:
            raise ValueError("chart source asset bbox has no area")
        if self.owner_geometry_evidence_ids != list(
            dict.fromkeys(self.owner_geometry_evidence_ids)
        ):
            raise ValueError("chart source asset owner evidence repeats")
        expected_owner_evidence_count = (
            2
            if self.owner_geometry_proof_kind
            == "detected_image_and_docling_picture"
            else 1
        )
        if len(self.owner_geometry_evidence_ids) != expected_owner_evidence_count:
            raise ValueError("chart source asset owner evidence count differs")
        if self.rendered_bbox.unit != self.source_bbox.unit:
            raise ValueError("chart source asset rendered bbox unit differs")
        if self.width * self.height > _MAX_ASSET_PIXELS:
            raise ValueError("chart source asset exceeds its pixel cap")
        if not self.data_uri.startswith(_PNG_PREFIX):
            raise ValueError("chart source asset URI is not an inline PNG")
        try:
            data = base64.b64decode(
                self.data_uri[len(_PNG_PREFIX) :],
                validate=True,
            )
        except (binascii.Error, ValueError) as exc:
            raise ValueError("chart source asset base64 is malformed") from exc
        if len(data) != self.byte_length:
            raise ValueError("chart source asset byte length differs")
        if hashlib.sha256(data).hexdigest() != self.sha256:
            raise ValueError("chart source asset digest differs")
        try:
            with Image.open(io.BytesIO(data)) as opened:
                if opened.format != "PNG" or opened.size != (self.width, self.height):
                    raise ValueError("chart source asset PNG metadata differs")
                opened.verify()
            with Image.open(io.BytesIO(data)) as decoded:
                if decoded.mode != "RGB":
                    raise ValueError("chart source asset color mode differs")
                decoded.load()
        except (OSError, UnidentifiedImageError) as exc:
            raise ValueError("chart source asset PNG cannot be decoded") from exc
        expected_transform = (
            self.rendered_bbox.width / self.width,
            0.0,
            0.0,
            self.rendered_bbox.height / self.height,
            self.rendered_bbox.x,
            self.rendered_bbox.y,
        )
        if any(
            not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-9)
            for actual, expected in zip(
                self.pixel_to_page_transform,
                expected_transform,
                strict=True,
            )
        ):
            raise ValueError("chart source asset transform differs")
        if self.source_kind == "pdf":
            if (
                self.renderer != "pypdfium2"
                or self.bbox_rounding != "outward_device_pixels"
                or self.effective_dpi is None
                or self.page_device_dimensions is None
                or self.crop_device_margins is None
                or not math.isclose(
                    self.effective_dpi,
                    self.render_scale * 72.0,
                    rel_tol=0.0,
                    abs_tol=1e-9,
                )
            ):
                raise ValueError("PDF chart source asset render metadata differs")
            page_device_width, page_device_height = self.page_device_dimensions
            left, bottom, right, top = self.crop_device_margins
            if (
                min(page_device_width, page_device_height) < 1
                or min(left, bottom, right, top) < 0
                or self.width != page_device_width - left - right
                or self.height != page_device_height - bottom - top
            ):
                raise ValueError("PDF chart source asset device crop differs")
            pixel_size = 1.0 / self.render_scale
            if (
                self.rendered_bbox.x > self.source_bbox.x
                or self.rendered_bbox.y > self.source_bbox.y
                or self.rendered_bbox.x + self.rendered_bbox.width
                < self.source_bbox.x + self.source_bbox.width
                or self.rendered_bbox.y + self.rendered_bbox.height
                < self.source_bbox.y + self.source_bbox.height
                or self.source_bbox.x - self.rendered_bbox.x >= pixel_size + 1e-9
                or self.source_bbox.y - self.rendered_bbox.y >= pixel_size + 1e-9
                or (
                    self.rendered_bbox.x
                    + self.rendered_bbox.width
                    - self.source_bbox.x
                    - self.source_bbox.width
                    >= pixel_size + 1e-9
                )
                or (
                    self.rendered_bbox.y
                    + self.rendered_bbox.height
                    - self.source_bbox.y
                    - self.source_bbox.height
                    >= pixel_size + 1e-9
                )
            ):
                raise ValueError("PDF chart source asset rounding coverage differs")
        elif (
            self.renderer != "pillow"
            or self.bbox_rounding != "exact_integer"
            or self.effective_dpi is not None
            or self.page_device_dimensions is not None
            or self.crop_device_margins is not None
            or self.render_scale != 1.0
        ):
            raise ValueError("image chart source asset render metadata differs")
        elif self.rendered_bbox != self.source_bbox:
            raise ValueError("image chart source asset rendered bbox differs")
        expected_id = _stable_id(
            "chart-asset",
            self.source_document_sha256,
            self.render_source_sha256,
            self.owner_item_id,
            self.physical_page,
            self.source_bbox.model_dump(mode="json"),
            self.owner_geometry_proof_kind,
            self.owner_geometry_evidence_ids,
            self.owner_geometry_evidence_sha256,
            self.rendered_bbox.model_dump(mode="json"),
            self.page_device_dimensions,
            self.crop_device_margins,
            self.render_policy,
            self.sha256,
        )
        if self.asset_id != expected_id:
            raise ValueError("chart source asset identity differs")
        return self


ChartSemanticFeature = Literal[
    "region",
    "source_evidence",
    "family",
    "panels",
    "axes",
    "categories",
    "legends",
    "series",
    "points",
    "ownership",
    "ambiguity_closure",
    "serialization",
]


class ChartSemanticAnalysis(ChartAssetContract):
    capability_matrix_version: Literal["chart-semantic-capabilities-v1"]
    attempt_status: Literal[
        "not_run_asset_unavailable",
        "not_run_no_approved_analyzer",
        "completed",
        "failed",
        "timed_out",
        "resource_refused",
    ]
    analyzer_ids: list[str] = Field(default_factory=list, max_length=16)
    configuration_sha256: str = Field(pattern=_SHA256_PATTERN)
    completeness_gate_status: Literal["not_run", "passed", "failed"]
    required_features: list[ChartSemanticFeature] = Field(
        default_factory=list,
        max_length=16,
    )
    observed_features: list[ChartSemanticFeature] = Field(
        default_factory=list,
        max_length=16,
    )
    missing_features: list[ChartSemanticFeature] = Field(
        default_factory=list,
        max_length=16,
    )
    ambiguous_evidence_ids: list[str] = Field(
        default_factory=list,
        max_length=_MAX_REFERENCES,
    )
    failure_reason: Literal[
        "unresolved",
        "unsupported",
        "malformed_input",
        "validation_failed",
        "resource_limit",
        "timeout",
        "low_quality",
        "incomplete",
        "asset_unavailable",
    ] | None = None

    @model_validator(mode="after")
    def validate_analysis(self) -> "ChartSemanticAnalysis":
        for values, label in (
            (self.analyzer_ids, "analyzer"),
            (self.required_features, "required feature"),
            (self.observed_features, "observed feature"),
            (self.missing_features, "missing feature"),
            (self.ambiguous_evidence_ids, "ambiguous evidence"),
        ):
            if values != list(dict.fromkeys(values)):
                raise ValueError(f"chart semantic {label} order repeats")
        if set(self.missing_features) != set(self.required_features) - set(
            self.observed_features
        ):
            raise ValueError("chart semantic completeness ledger differs")
        not_run = self.attempt_status.startswith("not_run_")
        if not_run:
            if (
                self.analyzer_ids
                or self.completeness_gate_status != "not_run"
                or self.required_features
                or self.observed_features
                or self.missing_features
                or self.ambiguous_evidence_ids
                or self.failure_reason
                not in {"unsupported", "asset_unavailable"}
            ):
                raise ValueError("not-run chart semantic state differs")
        elif not self.analyzer_ids or not self.required_features:
            raise ValueError("attempted chart semantics lack capability evidence")
        if self.completeness_gate_status == "passed":
            if (
                self.attempt_status != "completed"
                or self.missing_features
                or self.failure_reason is not None
            ):
                raise ValueError("passed chart semantic state differs")
        elif self.completeness_gate_status == "failed" and (
            not self.missing_features or self.failure_reason is None
        ):
            raise ValueError("failed chart semantic state differs")
        return self


class ChartResolution(ChartAssetContract):
    schema_version: Literal["1.0"]
    policy_id: Literal["ffd-015-chart-source-asset-v1"]
    owner_item_id: str = Field(min_length=1, max_length=512)
    page_index: int = Field(ge=1, le=1_000_000)
    source_order: int = Field(
        ge=0,
        le=1_000_000,
        description=(
            "Immutable item slot at chart-detection handoff; later canonical "
            "relationship ordering may change public presentation order."
        ),
    )
    source_bbox: VisualBoundingBox
    status: Literal[
        "structured_primary",
        "image_primary_unsupported",
        "image_primary_incomplete",
        "asset_unavailable",
    ]
    asset_status: Literal["retained", "unavailable"]
    asset_unavailable_reason: Literal[
        "source_bytes_unavailable",
        "source_kind_unsupported",
        "owner_geometry_invalid",
        "owner_outside_page",
        "page_unavailable",
        "render_failed",
        "render_timeout",
        "crop_dimension_limit",
        "crop_pixel_limit",
        "asset_byte_limit",
        "document_asset_count_limit",
        "document_asset_byte_limit",
        "mime_validation_failed",
        "source_integrity_mismatch",
        "crop_legibility_limit",
        "response_byte_limit",
        "document_render_timeout",
    ] | None = None
    asset: ChartSourceAsset | None = None
    family_classification: ChartFamilyClassification
    complexity_classification: ChartComplexityClassification
    semantic_analysis: ChartSemanticAnalysis
    primary_representation: Literal[
        "structured_chart",
        "source_image",
        "grounded_predecessor",
    ]
    primary_reason: Literal[
        "semantic_completeness_passed",
        "semantic_family_not_supported",
        "semantic_analysis_incomplete",
        "source_asset_unavailable",
    ]
    transcript: ChartTranscript
    confidence_dimensions: ChartConfidenceDimensions
    concern_codes: list[
        Literal[
            "chart_family_undetermined",
            "chart_complexity_undetermined",
            "chart_semantics_unsupported",
            "chart_semantics_incomplete",
            "chart_source_asset_unavailable",
        ]
    ] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_resolution(self) -> "ChartResolution":
        if self.concern_codes != list(dict.fromkeys(self.concern_codes)):
            raise ValueError("chart resolution concerns repeat")
        if self.asset_status == "retained":
            if self.asset is None or self.asset_unavailable_reason is not None:
                raise ValueError("retained chart asset state differs")
            if (
                self.asset.owner_item_id != self.owner_item_id
                or self.asset.physical_page != self.page_index
                or self.asset.source_bbox != self.source_bbox
            ):
                raise ValueError("chart resolution asset ownership differs")
        elif self.asset is not None or self.asset_unavailable_reason is None:
            raise ValueError("unavailable chart asset state differs")
        expected = {
            "structured_primary": (
                "retained",
                "structured_chart",
                "semantic_completeness_passed",
                "completed",
                "passed",
            ),
            "image_primary_unsupported": (
                "retained",
                "source_image",
                "semantic_family_not_supported",
                "not_run_no_approved_analyzer",
                "not_run",
            ),
            "image_primary_incomplete": (
                "retained",
                "source_image",
                "semantic_analysis_incomplete",
                None,
                "failed",
            ),
            "asset_unavailable": (
                "unavailable",
                "grounded_predecessor",
                "source_asset_unavailable",
                "not_run_asset_unavailable",
                "not_run",
            ),
        }[self.status]
        if (
            self.asset_status != expected[0]
            or self.primary_representation != expected[1]
            or self.primary_reason != expected[2]
            or (
                expected[3] is not None
                and self.semantic_analysis.attempt_status != expected[3]
            )
            or self.semantic_analysis.completeness_gate_status != expected[4]
        ):
            raise ValueError("chart terminal resolution state differs")
        if self.status == "image_primary_incomplete" and (
            self.semantic_analysis.attempt_status
            not in {"completed", "failed", "timed_out", "resource_refused"}
        ):
            raise ValueError("incomplete chart attempt state differs")
        classifications_not_run = (
            self.family_classification.status == "not_run"
            or self.complexity_classification.status == "not_run"
        )
        if classifications_not_run != (self.status == "asset_unavailable"):
            raise ValueError("chart classification dispatch state differs")
        expected_concerns: list[str] = []
        if self.family_classification.status == "undetermined":
            expected_concerns.append("chart_family_undetermined")
        if self.complexity_classification.status == "undetermined":
            expected_concerns.append("chart_complexity_undetermined")
        if self.status == "image_primary_unsupported":
            expected_concerns.append("chart_semantics_unsupported")
        elif self.status == "image_primary_incomplete":
            expected_concerns.append("chart_semantics_incomplete")
        elif self.status == "asset_unavailable":
            expected_concerns.append("chart_source_asset_unavailable")
        if self.concern_codes != expected_concerns:
            raise ValueError("chart resolution concerns differ")
        if (
            self.confidence_dimensions.transcription != self.transcript.confidence
            or self.confidence_dimensions.family
            != self.family_classification.confidence
            or self.confidence_dimensions.complexity
            != self.complexity_classification.confidence
        ):
            raise ValueError("chart resolution confidence dimensions differ")
        return self


@dataclass(frozen=True, slots=True)
class ChartAssetLimits:
    min_width: int
    min_height: int
    max_width: int
    max_height: int
    max_pixels: int
    max_bytes: int
    max_assets: int
    max_total_bytes: int
    max_response_bytes: int
    render_timeout_seconds: float
    document_timeout_seconds: float
    pdf_dpi: float


@dataclass(slots=True)
class ChartAssetLedger:
    asset_count: int = 0
    total_bytes: int = 0
    response_bytes: int = 0
    attempt_count: int = 0
    deadline_monotonic: float | None = None


@dataclass(frozen=True, slots=True)
class ChartAssetAttempt:
    asset: ChartSourceAsset | None
    unavailable_reason: str | None


@dataclass(frozen=True, slots=True)
class _OwnerSourceRecord:
    bbox: VisualBoundingBox
    evidence_id: str | None
    evidence_sha256: str | None

    @property
    def valid(self) -> bool:
        return self.evidence_id is not None and self.evidence_sha256 is not None


class _AssetRefusal(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _render_process_entry(
    source_path: str,
    output_path: str,
    status_path: str,
    input_kind: str,
    page_index: int,
    bbox: VisualBoundingBox,
    limits: ChartAssetLimits,
) -> None:
    """Render inside a disposable worker so the deadline is enforceable."""

    status: dict[str, Any]
    try:
        source = Path(source_path).read_bytes()
        if input_kind == "pdf":
            result = _render_pdf(
                source,
                page_index=page_index,
                bbox=bbox,
                limits=limits,
            )
        elif input_kind == "image":
            result = _render_image(
                source,
                page_index=page_index,
                bbox=bbox,
                limits=limits,
            )
        else:
            raise _AssetRefusal("source_kind_unsupported")
        (
            data,
            width,
            height,
            scale,
            renderer,
            renderer_version,
            rendered_bbox,
            page_device_dimensions,
            crop_device_margins,
        ) = result
        Path(output_path).write_bytes(data)
        status = {
            "status": "ok",
            "byte_length": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "width": width,
            "height": height,
            "scale": scale,
            "renderer": renderer,
            "renderer_version": renderer_version,
            "rendered_bbox": rendered_bbox.model_dump(mode="json"),
            "page_device_dimensions": page_device_dimensions,
            "crop_device_margins": crop_device_margins,
        }
    except _AssetRefusal as refusal:
        status = {"status": "refused", "reason": refusal.reason}
    except BaseException:
        status = {"status": "error"}
    temporary_status = f"{status_path}.tmp"
    try:
        Path(temporary_status).write_text(
            json.dumps(status, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary_status, status_path)
    except BaseException:
        pass


def _terminate_render_process(process: multiprocessing.Process) -> None:
    if process.pid is None:
        return
    if process.is_alive():
        process.terminate()
    process.join(timeout=0.25)
    if process.is_alive():
        process.kill()
        process.join(timeout=0.25)


def _render_before_deadline(
    source: bytes,
    *,
    input_kind: str,
    page_index: int,
    bbox: VisualBoundingBox,
    limits: ChartAssetLimits,
    document_deadline: float | None = None,
) -> tuple[
    bytes,
    int,
    int,
    float,
    str,
    str,
    VisualBoundingBox,
    list[int] | None,
    list[int] | None,
]:
    if len(source) > 64 * 1024 * 1024:
        raise _AssetRefusal("source_bytes_unavailable")
    deadline = time.monotonic() + limits.render_timeout_seconds
    if document_deadline is not None:
        deadline = min(deadline, document_deadline)
    with tempfile.TemporaryDirectory(prefix="chart-source-asset-") as directory:
        source_path = str(Path(directory) / "source.bin")
        output_path = str(Path(directory) / "asset.png")
        status_path = str(Path(directory) / "status.json")
        Path(source_path).write_bytes(source)
        if time.monotonic() >= deadline:
            raise _AssetRefusal("render_timeout")
        context = multiprocessing.get_context("spawn")
        process = context.Process(
            target=_render_process_entry,
            args=(
                source_path,
                output_path,
                status_path,
                input_kind,
                page_index,
                bbox,
                limits,
            ),
            daemon=True,
            name="chart-source-asset-render",
        )
        try:
            try:
                process.start()
            except (AssertionError, OSError, RuntimeError, TypeError) as exc:
                raise _AssetRefusal("render_failed") from exc
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _AssetRefusal("render_timeout")
            process.join(timeout=remaining)
            if process.is_alive():
                raise _AssetRefusal("render_timeout")
            if process.exitcode != 0 or not Path(status_path).is_file():
                raise _AssetRefusal("render_failed")
            raw_status = Path(status_path).read_bytes()
            if len(raw_status) > 8_192:
                raise _AssetRefusal("render_failed")
            try:
                status = json.loads(raw_status)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise _AssetRefusal("render_failed") from exc
            if type(status) is not dict:
                raise _AssetRefusal("render_failed")
            if status.get("status") == "refused" and isinstance(
                status.get("reason"),
                str,
            ):
                raise _AssetRefusal(status["reason"])
            if status.get("status") != "ok" or not Path(output_path).is_file():
                raise _AssetRefusal("render_failed")
            with Path(output_path).open("rb") as rendered_file:
                data = rendered_file.read(limits.max_bytes + 1)
            if (
                not data
                or len(data) > limits.max_bytes
                or status.get("byte_length") != len(data)
                or status.get("sha256") != hashlib.sha256(data).hexdigest()
            ):
                raise _AssetRefusal("asset_byte_limit")
            rendered_bbox = VisualBoundingBox.model_validate(
                status.get("rendered_bbox"),
                strict=True,
            )
            page_device_dimensions = status.get("page_device_dimensions")
            crop_device_margins = status.get("crop_device_margins")
            for values, expected_length in (
                (page_device_dimensions, 2),
                (crop_device_margins, 4),
            ):
                if values is not None and (
                    type(values) is not list
                    or len(values) != expected_length
                    or any(type(value) is not int for value in values)
                ):
                    raise _AssetRefusal("render_failed")
            scalar_values = (
                status.get("width"),
                status.get("height"),
                status.get("scale"),
                status.get("renderer"),
                status.get("renderer_version"),
            )
            width, height, scale, renderer, renderer_version = scalar_values
            if (
                type(width) is not int
                or type(height) is not int
                or not isinstance(scale, (int, float))
                or isinstance(scale, bool)
                or type(renderer) is not str
                or type(renderer_version) is not str
            ):
                raise _AssetRefusal("render_failed")
            return (
                data,
                width,
                height,
                float(scale),
                renderer,
                renderer_version,
                rendered_bbox,
                page_device_dimensions,
                crop_device_margins,
            )
        finally:
            _terminate_render_process(process)


def _stable_id(prefix: str, *parts: Any) -> str:
    encoded = json.dumps(
        parts,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _owner_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("chart owner geometry value is not numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("chart owner geometry value is not finite")
    return number


def _owner_coordinate(value: Any) -> float:
    return round(_owner_number(value), _OWNER_GEOMETRY_DECIMALS)


def _owner_public_bbox(
    value: Any,
    *,
    default_unit: str,
) -> VisualBoundingBox:
    if not isinstance(value, Mapping):
        raise ValueError("chart owner bbox is not an object")
    width_value = value.get("width", value.get("w"))
    height_value = value.get("height", value.get("h"))
    width = _owner_coordinate(width_value)
    height = _owner_coordinate(height_value)
    if "width" in value and "w" in value and width != _owner_coordinate(value["w"]):
        raise ValueError("chart owner bbox width aliases differ")
    if "height" in value and "h" in value and height != _owner_coordinate(value["h"]):
        raise ValueError("chart owner bbox height aliases differ")
    unit = value.get("unit", default_unit)
    if type(unit) is not str or unit not in {"pt", "px"}:
        raise ValueError("chart owner bbox unit differs")
    bbox = VisualBoundingBox(
        x=_owner_coordinate(value.get("x")),
        y=_owner_coordinate(value.get("y")),
        width=width,
        height=height,
        unit=unit,
    )
    if min(bbox.x, bbox.y) < 0 or bbox.width <= 0 or bbox.height <= 0:
        raise ValueError("chart owner bbox has invalid area")
    return bbox


def _owner_locatable_public_bboxes(
    value: Any,
    *,
    default_unit: str,
) -> list[VisualBoundingBox]:
    """Return every bounded geometry interpretation of malformed aliases."""

    if not isinstance(value, Mapping):
        return []
    try:
        x = _owner_coordinate(value.get("x"))
        y = _owner_coordinate(value.get("y"))
    except (TypeError, ValueError):
        return []
    unit = value.get("unit", default_unit)
    if type(unit) is not str or unit not in {"pt", "px"}:
        return []
    widths: list[float] = []
    heights: list[float] = []
    for key, values in (("width", widths), ("w", widths)):
        if key not in value:
            continue
        try:
            candidate = _owner_coordinate(value[key])
        except (TypeError, ValueError):
            continue
        if candidate > 0 and candidate not in values:
            values.append(candidate)
    for key, values in (("height", heights), ("h", heights)):
        if key not in value:
            continue
        try:
            candidate = _owner_coordinate(value[key])
        except (TypeError, ValueError):
            continue
        if candidate > 0 and candidate not in values:
            values.append(candidate)
    if x < 0 or y < 0 or not widths or not heights:
        return []
    return [
        VisualBoundingBox(x=x, y=y, width=width, height=height, unit=unit)
        for width in widths
        for height in heights
    ]


def _owner_locatable_docling_bboxes(
    value: Any,
    *,
    page_height: float,
    page_unit: str,
) -> list[VisualBoundingBox]:
    """Return both finite coordinate-origin interpretations when possible."""

    if not isinstance(value, Mapping):
        return []
    try:
        left = _owner_number(value.get("l"))
        top = _owner_number(value.get("t"))
        right = _owner_number(value.get("r"))
        bottom = _owner_number(value.get("b"))
        width = _owner_coordinate(right - left)
    except (TypeError, ValueError):
        return []
    if left < 0 or width <= 0:
        return []
    candidates: list[VisualBoundingBox] = []
    for y, height in (
        (top, bottom - top),
        (page_height - top, top - bottom),
    ):
        normalized_y = _owner_coordinate(y)
        normalized_height = _owner_coordinate(height)
        if normalized_y < 0 or normalized_height <= 0:
            continue
        candidate = VisualBoundingBox(
            x=_owner_coordinate(left),
            y=normalized_y,
            width=width,
            height=normalized_height,
            unit=page_unit,
        )
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _owner_normalized_bbox(value: VisualBoundingBox) -> VisualBoundingBox:
    return VisualBoundingBox(
        x=_owner_coordinate(value.x),
        y=_owner_coordinate(value.y),
        width=_owner_coordinate(value.width),
        height=_owner_coordinate(value.height),
        unit=value.unit,
    )


def _owner_reciprocal_claim(
    layout: VisualBoundingBox,
    owner: VisualBoundingBox,
) -> bool:
    if layout.unit != owner.unit:
        return False
    layout_right = layout.x + layout.width
    layout_bottom = layout.y + layout.height
    owner_right = owner.x + owner.width
    owner_bottom = owner.y + owner.height
    overlap_width = max(
        min(layout_right, owner_right) - max(layout.x, owner.x),
        0.0,
    )
    overlap_height = max(
        min(layout_bottom, owner_bottom) - max(layout.y, owner.y),
        0.0,
    )
    intersection = overlap_width * overlap_height
    layout_coverage = intersection / (layout.width * layout.height)
    owner_coverage = intersection / (owner.width * owner.height)
    tolerance_x = max(
        _OWNER_MIN_MAPPING_TOLERANCE,
        owner.width * _OWNER_MAX_MAPPING_TOLERANCE_RATIO,
    )
    tolerance_y = max(
        _OWNER_MIN_MAPPING_TOLERANCE,
        owner.height * _OWNER_MAX_MAPPING_TOLERANCE_RATIO,
    )
    return bool(
        layout.x >= owner.x - tolerance_x
        and layout.y >= owner.y - tolerance_y
        and layout_right <= owner_right + tolerance_x
        and layout_bottom <= owner_bottom + tolerance_y
        and layout_coverage >= _OWNER_MIN_RECIPROCAL_COVERAGE
        and owner_coverage >= _OWNER_MIN_RECIPROCAL_COVERAGE
    )


def _owner_material_overlap(
    first: VisualBoundingBox,
    second: VisualBoundingBox,
) -> bool:
    if first.unit != second.unit:
        return False
    width = max(
        min(first.x + first.width, second.x + second.width)
        - max(first.x, second.x),
        0.0,
    )
    height = max(
        min(first.y + first.height, second.y + second.height)
        - max(first.y, second.y),
        0.0,
    )
    intersection = width * height
    if intersection <= 0:
        return False
    return (
        intersection / min(first.width * first.height, second.width * second.height)
        >= _OWNER_MATERIAL_OVERLAP_OF_SMALLER
    )


def _owner_overlap_of_smaller(
    first: VisualBoundingBox,
    second: VisualBoundingBox,
) -> float:
    if first.unit != second.unit:
        return 0.0
    width = max(
        min(first.x + first.width, second.x + second.width)
        - max(first.x, second.x),
        0.0,
    )
    height = max(
        min(first.y + first.height, second.y + second.height)
        - max(first.y, second.y),
        0.0,
    )
    smaller = min(first.width * first.height, second.width * second.height)
    return width * height / smaller if smaller > 0 else 0.0


def _owner_canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _owner_table_rows(value: Any) -> list[list[str]] | None:
    if type(value) is not list or not 1 <= len(value) <= 4_096:
        return None
    output: list[list[str]] = []
    column_count: int | None = None
    for row in value:
        if type(row) is not list or not 1 <= len(row) <= 256:
            return None
        if column_count is None:
            column_count = len(row)
        if len(row) != column_count or any(type(cell) is not str for cell in row):
            return None
        normalized_row: list[str] = []
        for cell in row:
            try:
                encoded = cell.encode("utf-8", errors="strict")
            except UnicodeEncodeError:
                return None
            if len(encoded) > 16_384 or any(
                (ord(character) < 0x20 and character not in "\t\n\r")
                or ord(character) == 0x7F
                for character in cell
            ):
                return None
            normalized_row.append(" ".join(cell.casefold().split()))
        output.append(normalized_row)
    if column_count is None or len(output) * column_count > 65_536:
        return None
    return output


def _owner_single_column_raw_cell_bboxes(
    candidate: Mapping[str, Any],
    *,
    candidate_bbox: VisualBoundingBox,
    row_count: int,
    column_count: int,
) -> list[list[dict[str, Any]]] | None:
    """Recover the exact published selected-vector grid when it is unambiguous."""

    raw_row_bboxes = candidate.get("row_bboxes")
    if (
        candidate_bbox.unit != "pt"
        or column_count != 1
        or type(raw_row_bboxes) is not list
        or len(raw_row_bboxes) != row_count
    ):
        return None
    row_bboxes: list[VisualBoundingBox] = []
    try:
        for value in raw_row_bboxes:
            row_bbox = _owner_public_bbox(value, default_unit="pt")
            if row_bbox.unit != "pt":
                return None
            row_bboxes.append(row_bbox)
    except (TypeError, ValueError):
        return None

    tolerance = 0.05

    def close(first: float, second: float) -> bool:
        return abs(first - second) <= tolerance

    table_right = candidate_bbox.x + candidate_bbox.width
    table_bottom = candidate_bbox.y + candidate_bbox.height
    for row_index, row_bbox in enumerate(row_bboxes):
        row_right = row_bbox.x + row_bbox.width
        row_bottom = row_bbox.y + row_bbox.height
        if (
            row_bbox.x < candidate_bbox.x - tolerance
            or row_bbox.y < candidate_bbox.y - tolerance
            or row_right > table_right + tolerance
            or row_bottom > table_bottom + tolerance
            or not close(row_bbox.x, candidate_bbox.x)
            or not close(row_right, table_right)
            or (
                row_index == 0
                and not close(row_bbox.y, candidate_bbox.y)
            )
            or (
                row_index > 0
                and not close(
                    row_bbox.y,
                    row_bboxes[row_index - 1].y
                    + row_bboxes[row_index - 1].height,
                )
            )
            or (
                row_index == len(row_bboxes) - 1
                and not close(row_bottom, table_bottom)
            )
        ):
            return None
    return [[row_bbox.model_dump(mode="json")] for row_bbox in row_bboxes]


def _owner_reconciled_table_candidate_id(
    candidate: Mapping[str, Any],
    *,
    page_index: int,
    candidate_bbox: VisualBoundingBox,
) -> tuple[str, list[str]] | None:
    """Replay the bounded singleton table-candidate authority carried forward."""

    if candidate.get("candidate_table_evidence") is not None:
        return None
    reconciliation = candidate.get("table_reconciliation")
    expected_reconciliation_keys = {
        "cluster_id",
        "candidate_ids",
        "selected_candidate_id",
        "outcome",
        "absolute_threshold",
        "selection_margin",
        "scores",
        "evidence_ids",
        "concern_codes",
    }
    if type(reconciliation) is not dict or set(reconciliation) != (
        expected_reconciliation_keys
    ):
        return None
    candidate_ids = reconciliation.get("candidate_ids")
    selected_candidate_id = reconciliation.get("selected_candidate_id")
    evidence_ids = reconciliation.get("evidence_ids")
    scores = reconciliation.get("scores")
    if (
        type(candidate_ids) is not list
        or len(candidate_ids) != 1
        or type(selected_candidate_id) is not str
        or candidate_ids != [selected_candidate_id]
        or re.fullmatch(_SHA256_PATTERN, selected_candidate_id) is None
        or reconciliation.get("outcome") != "singleton"
        or reconciliation.get("absolute_threshold") != 0.58
        or reconciliation.get("selection_margin") != 1.0
        or reconciliation.get("concern_codes") != []
        or type(evidence_ids) is not list
        or evidence_ids != sorted(set(evidence_ids))
        or len(evidence_ids) > 64
        or any(
            type(value) is not str
            or re.fullmatch(_SHA256_PATTERN, value) is None
            for value in evidence_ids
        )
        or type(scores) is not list
        or len(scores) != 1
        or type(scores[0]) is not dict
    ):
        return None
    if reconciliation.get("cluster_id") != _owner_canonical_sha256(
        ["p04-us02-cluster-v1", candidate_ids]
    ):
        return None

    score = scores[0]
    expected_score_keys = {
        "candidate_id",
        "engine",
        "total",
        "geometry",
        "grid",
        "cell_coverage",
        "text_coverage",
        "spans",
        "provenance",
        "bbox",
        "row_count",
        "column_count",
        "content_sha256",
        "candidate",
    }
    if type(score) is not dict or set(score) != expected_score_keys:
        return None
    summary = score.get("candidate")
    expected_summary_keys = {
        "candidate_id",
        "engine",
        "bbox",
        "rows",
        "cells",
        "row_count",
        "column_count",
        "content_sha256",
    }
    if type(summary) is not dict or not expected_summary_keys.issubset(summary):
        return None
    if any(
        key not in expected_summary_keys
        | {"caption_ids", "source_note_ids", "footnote_ids", "relationships"}
        for key in summary
    ):
        return None
    rows = _owner_table_rows(candidate.get("rows"))
    cells = candidate.get("cells")
    row_count = len(rows) if rows is not None else 0
    column_count = len(rows[0]) if rows else 0
    engine = candidate.get("engine")
    if engine not in {"docling", "pdfplumber"}:
        engine = "unknown"
    bbox_payload = candidate_bbox.model_dump(mode="json")
    if (
        rows is None
        or cells != []
        or candidate.get("row_count") != row_count
        or candidate.get("column_count") != column_count
        or score.get("candidate_id") != selected_candidate_id
        or score.get("engine") != engine
        or score.get("bbox") != bbox_payload
        or score.get("row_count") != row_count
        or score.get("column_count") != column_count
        or type(score.get("content_sha256")) is not str
        or re.fullmatch(_SHA256_PATTERN, score["content_sha256"]) is None
        or summary.get("candidate_id") != selected_candidate_id
        or summary.get("engine") != engine
        or summary.get("bbox") != bbox_payload
        or summary.get("rows") != candidate.get("rows")
        or summary.get("cells") != cells
        or summary.get("row_count") != row_count
        or summary.get("column_count") != column_count
        or summary.get("content_sha256") != score.get("content_sha256")
    ):
        return None
    for optional_key in (
        "caption_ids",
        "source_note_ids",
        "footnote_ids",
        "relationships",
    ):
        if optional_key in summary and summary[optional_key] != candidate.get(
            optional_key
        ):
            return None
    score_numbers: dict[str, float] = {}
    for key in (
        "total",
        "geometry",
        "grid",
        "cell_coverage",
        "text_coverage",
        "spans",
        "provenance",
    ):
        try:
            number = _owner_number(score.get(key))
        except (TypeError, ValueError):
            return None
        if not 0.0 <= number <= 1.0:
            return None
        score_numbers[key] = number
    expected_total = round(
        0.18 * score_numbers["geometry"]
        + 0.18 * score_numbers["grid"]
        + 0.22 * score_numbers["cell_coverage"]
        + 0.22 * score_numbers["text_coverage"]
        + 0.08 * score_numbers["spans"]
        + 0.12 * score_numbers["provenance"],
        6,
    )
    if score_numbers["total"] != expected_total:
        return None
    if (
        score_numbers["grid"] != 1.0
        or score_numbers["cell_coverage"] != 1.0
        or score_numbers["text_coverage"] != 1.0
        or score_numbers["spans"] != 0.75
        or (
            score_numbers["geometry"],
            score_numbers["provenance"],
        )
        not in {(0.65, 0.50), (1.0, 0.85)}
    ):
        return None
    score_geometry = (
        score_numbers["geometry"],
        score_numbers["provenance"],
    )
    if score_geometry == (0.65, 0.50):
        raw_cell_bboxes: list[list[dict[str, Any]]] = []
    else:
        recovered = _owner_single_column_raw_cell_bboxes(
            candidate,
            candidate_bbox=candidate_bbox,
            row_count=row_count,
            column_count=column_count,
        )
        if recovered is None:
            return None
        raw_cell_bboxes = recovered
    expected_content_sha256 = _owner_canonical_sha256(
        [
            "p04-us02-candidate-content-v1",
            rows,
            [],
            raw_cell_bboxes,
        ]
    )
    if score["content_sha256"] != expected_content_sha256:
        return None
    expected_candidate_id = _owner_canonical_sha256(
        [
            "p04-us02-candidate-v1",
            page_index,
            engine,
            bbox_payload,
            row_count,
            column_count,
            expected_content_sha256,
        ]
    )
    if selected_candidate_id != expected_candidate_id:
        return None
    return selected_candidate_id, list(evidence_ids)


def _owner_expected_table_gate_owner_ids(
    owner_item: Mapping[str, Any],
    *,
    owner_item_id: str,
    owner_bbox: VisualBoundingBox,
    page_index: int,
    source_document_sha256: str,
) -> set[str]:
    """Replay both possible P04 owner identities across later ID assignment."""

    synthetic_digest = _owner_canonical_sha256(
        [
            "p04-us04-owner-v1",
            source_document_sha256,
            page_index,
            owner_item.get("type"),
            owner_item.get("content_type"),
            owner_item.get("label"),
            owner_bbox.model_dump(mode="json"),
        ]
    )
    return {owner_item_id, f"p04-owner-{synthetic_digest}"}


def _table_candidate_is_superseded_by_chart(
    candidate: Mapping[str, Any],
    *,
    owner_item_id: str,
    owner_item: Mapping[str, Any],
    owner_bbox: VisualBoundingBox,
    page_unit: str,
    page_index: int,
    source_document_sha256: str,
) -> bool:
    """Recognize only a locally replayable chart-owned table alternative."""

    gate = candidate.get("table_candidate_gate")
    reasons = candidate.get("table_candidate_gate_reasons")
    sources = candidate.get("table_candidate_gate_sources")
    concerns = candidate.get("parse_concerns")
    reconciled = _owner_reconciled_table_candidate_id(
        candidate,
        page_index=page_index,
        candidate_bbox=_owner_public_bbox(
            candidate.get("bbox"),
            default_unit=page_unit,
        ),
    )
    expected_gate_keys = {
        "decision_id",
        "candidate_id",
        "outcome",
        "owner_item_ids",
        "feature_scores",
        "evidence_ids",
        "concern_codes",
    }
    expected_source_keys = {"owner_item_id", "owner_type", "bbox", "overlap"}
    if (
        reconciled is None
        or type(gate) is not dict
        or set(gate) != expected_gate_keys
        or gate.get("outcome") != "chart"
        or gate.get("concern_codes") != ["table_candidate_chart_owned"]
        or reasons != ["typed_chart_owns_region"]
        or type(concerns) is not list
        or "table_candidate_chart_owned" not in concerns
        or type(sources) is not list
        or len(sources) != 1
        or type(sources[0]) is not dict
        or set(sources[0]) != expected_source_keys
        or sources[0].get("owner_type") != "chart"
    ):
        return False
    candidate_id, evidence_ids = reconciled
    owner_ids = _owner_expected_table_gate_owner_ids(
        owner_item,
        owner_item_id=owner_item_id,
        owner_bbox=owner_bbox,
        page_index=page_index,
        source_document_sha256=source_document_sha256,
    )
    source_owner_id = sources[0].get("owner_item_id")
    if (
        type(source_owner_id) is not str
        or source_owner_id not in owner_ids
        or gate.get("owner_item_ids") != [source_owner_id]
        or gate.get("candidate_id") != candidate_id
        or gate.get("evidence_ids") != evidence_ids
    ):
        return False
    try:
        source_bbox = _owner_public_bbox(
            sources[0].get("bbox"),
            default_unit=page_unit,
        )
        overlap = _owner_number(sources[0].get("overlap"))
    except (TypeError, ValueError):
        return False
    candidate_bbox = _owner_public_bbox(
        candidate.get("bbox"),
        default_unit=page_unit,
    )
    expected_overlap = round(
        min(1.0, _owner_overlap_of_smaller(candidate_bbox, owner_bbox)),
        6,
    )
    normalized_rows = _owner_table_rows(candidate.get("rows"))
    if normalized_rows is None:
        return False
    row_count = len(normalized_rows)
    column_count = len(normalized_rows[0])
    nonblank = sum(bool(value) for row in normalized_rows for value in row)
    aligned_rows = sum(
        sum(bool(value) for value in row) >= 2 for row in normalized_rows
    )
    slot_count = row_count * column_count
    structural_failure = row_count < 2 or column_count < 2
    grid = 0.0 if structural_failure else 1.0
    alignment = aligned_rows / row_count if row_count else 0.0
    cell_coverage = nonblank / slot_count if slot_count else 0.0
    geometry = 0.75
    provenance = 0.85
    table_support = min(
        1.0,
        0.24 * grid
        + 0.20 * alignment
        + 0.22 * cell_coverage
        + 0.16 * geometry
        + 0.18 * provenance,
    )
    expected_scores = {
        "alignment": round(min(1.0, alignment), 6),
        "cell_coverage": round(min(1.0, cell_coverage), 6),
        "geometry": geometry,
        "grid": grid,
        "owner_overlap": expected_overlap,
        "provenance": provenance,
        "region_type": 1.0,
        "table_support": round(min(1.0, table_support), 6),
    }
    expected_decision_id = _owner_canonical_sha256(
        [
            "p04-us04-gate-v1",
            candidate_id,
            "chart",
            [source_owner_id],
            expected_scores,
            evidence_ids,
            ["table_candidate_chart_owned"],
        ]
    )
    return bool(
        source_bbox == owner_bbox
        and expected_overlap >= 0.70
        and overlap == expected_overlap
        and gate.get("feature_scores") == expected_scores
        and gate.get("decision_id") == expected_decision_id
    )


def _owner_source_id(value: Any, *, label: str) -> str:
    if type(value) is not str or not value or len(value) > 512:
        raise ValueError(f"chart {label} source identity differs")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError(f"chart {label} source identity differs") from exc
    return value


def _owner_docling_picture_records(
    raw_graph: Mapping[str, Any] | None,
    *,
    page_index: int,
    page_height: float,
    page_unit: str,
) -> list[_OwnerSourceRecord]:
    if raw_graph is None:
        return []
    raw_pictures = raw_graph.get("pictures")
    if raw_pictures is None:
        return []
    if type(raw_pictures) is not list or len(raw_pictures) > _OWNER_MAX_RAW_PICTURES:
        raise ValueError("chart raw picture inventory differs")
    global_source_ids: list[str] = []
    for picture in raw_pictures:
        if not isinstance(picture, Mapping):
            raise ValueError("chart raw picture record differs")
        provenance = picture.get("prov")
        # A multi-record picture cannot be routed by inspecting only one
        # record: a later entry could overlap this owner on another page.
        # Refuse the entire bounded inventory before page filtering.
        if type(provenance) is not list or len(provenance) != 1:
            raise ValueError("chart raw picture provenance count differs")
        provenance_record = provenance[0]
        if (
            not isinstance(provenance_record, Mapping)
            or type(provenance_record.get("page_no")) is not int
            or isinstance(provenance_record.get("page_no"), bool)
            or provenance_record.get("page_no") < 1
        ):
            raise ValueError("chart raw picture page provenance differs")
        try:
            global_source_ids.append(
                _owner_source_id(
                    picture.get("self_ref"),
                    label="Docling picture",
                )
            )
        except (TypeError, ValueError):
            # A missing identity is only poisonous when its parseable geometry
            # overlaps the requested owner; the spatial pass below decides it.
            pass
    if len(global_source_ids) != len(set(global_source_ids)):
        raise ValueError("chart raw picture identity repeats")
    records: list[_OwnerSourceRecord] = []
    for picture in raw_pictures:
        if not isinstance(picture, Mapping):  # pragma: no cover - preflight above
            raise ValueError("chart raw picture record differs")
        provenance = picture.get("prov")
        assert type(provenance) is list and len(provenance) == 1
        record = provenance[0]
        if (
            not isinstance(record, Mapping)
            or type(record.get("page_no")) is not int
            or record.get("page_no") != page_index
        ):
            continue
        raw_bbox = record.get("bbox")
        if not isinstance(raw_bbox, Mapping):
            raise ValueError("chart target-page picture bbox differs")
        try:
            left = _owner_number(raw_bbox.get("l"))
            top = _owner_number(raw_bbox.get("t"))
            right = _owner_number(raw_bbox.get("r"))
            bottom = _owner_number(raw_bbox.get("b"))
            origin = raw_bbox.get("coord_origin")
            if type(origin) is not str or origin.upper() not in {
                "TOPLEFT",
                "BOTTOMLEFT",
            }:
                raise ValueError("chart raw picture coordinate origin differs")
            if origin.upper() == "TOPLEFT":
                y = top
                height = bottom - top
            else:
                y = page_height - top
                height = top - bottom
            bbox = VisualBoundingBox(
                x=_owner_coordinate(left),
                y=_owner_coordinate(y),
                width=_owner_coordinate(right - left),
                height=_owner_coordinate(height),
                unit=page_unit,
            )
            if min(bbox.x, bbox.y) < 0 or bbox.width <= 0 or bbox.height <= 0:
                raise ValueError("chart raw picture bbox has invalid area")
        except (OverflowError, TypeError, ValueError):
            locatable_bboxes = _owner_locatable_docling_bboxes(
                raw_bbox,
                page_height=page_height,
                page_unit=page_unit,
            )
            if not locatable_bboxes:
                raise ValueError("chart target-page picture bbox is unlocatable")
            records.extend(
                _OwnerSourceRecord(
                    bbox=locatable,
                    evidence_id=None,
                    evidence_sha256=None,
                )
                for locatable in locatable_bboxes
            )
            continue

        source_id: str | None = None
        evidence_sha256: str | None = None
        try:
            source_id = _owner_source_id(
                picture.get("self_ref"),
                label="Docling picture",
            )
            projection = {
                "source_id": source_id,
                "page_index": page_index,
                "bbox": bbox.model_dump(mode="json"),
                "raw_bbox": {
                    "l": left,
                    "t": top,
                    "r": right,
                    "b": bottom,
                    "coord_origin": origin.upper(),
                },
            }
            evidence_sha256 = hashlib.sha256(
                json.dumps(
                    projection,
                    allow_nan=False,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
        except (OverflowError, TypeError, ValueError):
            source_id = None
            evidence_sha256 = None
        records.append(
            _OwnerSourceRecord(
                bbox=bbox,
                evidence_id=(
                    f"docling:{source_id}" if source_id is not None else None
                ),
                evidence_sha256=evidence_sha256,
            )
        )
    return records


def _owner_detected_image_records(
    detected_images: Sequence[Any] | None,
    *,
    input_kind: str,
    page_width: float,
    page_height: float,
    page_unit: str,
) -> list[_OwnerSourceRecord]:
    if detected_images is None:
        return []
    if type(detected_images) is not list or len(detected_images) > (
        _OWNER_MAX_DETECTED_IMAGES
    ):
        raise ValueError("chart detected-image inventory differs")
    global_source_ids: list[str] = []
    for detected in detected_images:
        if not isinstance(detected, Mapping):
            raise ValueError("chart detected-image record differs")
        try:
            global_source_ids.append(
                _owner_source_id(
                    detected.get("id"),
                    label="detected image",
                )
            )
        except (TypeError, ValueError):
            # Missing identity is spatially adjudicated below. Syntactically
            # valid identities are reserved inventory-wide before any record
            # provenance or geometry can make the duplicate disappear.
            pass
    if len(global_source_ids) != len(set(global_source_ids)):
        raise ValueError("chart detected-image identity repeats")
    records: list[_OwnerSourceRecord] = []
    page_bbox = VisualBoundingBox(
        x=0.0,
        y=0.0,
        width=_owner_coordinate(page_width),
        height=_owner_coordinate(page_height),
        unit=page_unit,
    )
    for detected in detected_images:
        if not isinstance(detected, Mapping):
            raise ValueError("chart detected-image record differs")
        try:
            bbox = _owner_public_bbox(
                detected.get("bbox"),
                default_unit=page_unit,
            )
        except (OverflowError, TypeError, ValueError):
            locatable_bboxes = _owner_locatable_public_bboxes(
                detected.get("bbox"),
                default_unit=page_unit,
            )
            if not locatable_bboxes:
                raise ValueError("chart detected-image bbox is unlocatable")
            records.extend(
                _OwnerSourceRecord(
                    bbox=locatable,
                    evidence_id=None,
                    evidence_sha256=None,
                )
                for locatable in locatable_bboxes
            )
            continue

        source_id: str | None = None
        evidence_sha256: str | None = None
        try:
            if detected.get("type") != "image":
                raise ValueError("chart detected-image type differs")
            source_id = _owner_source_id(
                detected.get("id"),
                label="detected image",
            )
            pixel_width = detected.get("pixel_width")
            pixel_height = detected.get("pixel_height")
            if (
                type(pixel_width) is not int
                or type(pixel_height) is not int
                or not 1 <= pixel_width <= 100_000
                or not 1 <= pixel_height <= 100_000
                or pixel_width * pixel_height > 1_000_000_000
            ):
                raise ValueError("chart detected-image pixel geometry differs")
            role = detected.get("region_role")
            origin = detected.get("region_origin")
            if input_kind == "pdf":
                if role != "content_region" or origin not in {
                    "pdf_embedded",
                    "pdf_page_render",
                }:
                    raise ValueError("chart PDF detected-image provenance differs")
            elif input_kind == "image":
                if (
                    role != "page_source"
                    or origin != "uploaded_page"
                    or bbox != page_bbox
                ):
                    raise ValueError("chart image source-region provenance differs")
            else:
                raise ValueError("chart owner input kind differs")
            projection = {
                "source_id": source_id,
                "bbox": bbox.model_dump(mode="json"),
                "region_role": role,
                "region_origin": origin,
                "pixel_width": pixel_width,
                "pixel_height": pixel_height,
            }
            evidence_sha256 = hashlib.sha256(
                json.dumps(
                    projection,
                    allow_nan=False,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
        except (OverflowError, TypeError, ValueError):
            source_id = None
            evidence_sha256 = None
        records.append(
            _OwnerSourceRecord(
                bbox=bbox,
                evidence_id=(
                    f"detected:{source_id}" if source_id is not None else None
                ),
                evidence_sha256=evidence_sha256,
            )
        )
    return records


def prove_chart_owner_geometry(
    *,
    item: Mapping[str, Any],
    page_items: Sequence[Any],
    item_index: int,
    detected_images: Sequence[Any] | None,
    raw_graph: Mapping[str, Any] | None,
    page_index: int,
    page_width: float,
    page_height: float,
    page_unit: str,
    input_kind: str,
    source_document_sha256: str,
    render_source_sha256: str,
) -> ChartOwnerGeometryProof | None:
    """Bind one chart bbox to one independently detected source owner.

    The public chart item is only a claim.  A retained crop requires a unique
    exact match in the independently produced detected-image or raw Docling
    picture inventory, plus a reciprocal single claimant on the page.  Nearly
    contained or conflicting regions are deliberately not expanded or chosen.
    """

    try:
        if (
            not isinstance(item, Mapping)
            or type(page_items) is not list
            or len(page_items) > _OWNER_MAX_PAGE_ITEMS
            or type(item_index) is not int
            or isinstance(item_index, bool)
            or not 0 <= item_index < len(page_items)
            or not isinstance(page_index, int)
            or isinstance(page_index, bool)
            or page_index < 1
            or page_unit not in {"pt", "px"}
            or input_kind not in {"pdf", "image"}
            or re.fullmatch(_SHA256_PATTERN, source_document_sha256) is None
            or re.fullmatch(_SHA256_PATTERN, render_source_sha256) is None
        ):
            raise ValueError("chart owner proof context differs")
        owner_item_id = _owner_source_id(item.get("id"), label="public item")
        if (
            str(item.get("type") or item.get("content_type") or "").casefold()
            != "chart"
            or item.get("region_role") != "content_region"
        ):
            raise ValueError("chart owner public claim differs")
        target = _owner_public_bbox(item.get("bbox"), default_unit=page_unit)
        if target.unit != page_unit:
            raise ValueError("chart owner public claim unit differs")
        normalized_page_width = _owner_coordinate(page_width)
        normalized_page_height = _owner_coordinate(page_height)
        if (
            normalized_page_width <= 0
            or normalized_page_height <= 0
            or target.x + target.width > normalized_page_width
            or target.y + target.height > normalized_page_height
        ):
            raise ValueError("chart owner public claim is outside the page")

        visual_claim_types = {"chart", "diagram", "image"}
        structural_claim_types = {
            "table",
            "table_candidate",
            "form",
            "key_value_region",
        }
        current_claim_is_exact = False
        for candidate_index, candidate in enumerate(page_items):
            if not isinstance(candidate, Mapping):
                continue
            candidate_type_values: list[str] = []
            candidate_kind_malformed = False
            for key in ("type", "content_type"):
                raw_candidate_type = candidate.get(key)
                if (
                    key not in candidate
                    or raw_candidate_type is None
                    or raw_candidate_type == ""
                ):
                    continue
                if type(raw_candidate_type) is not str:
                    candidate_kind_malformed = True
                    continue
                candidate_type_values.append(raw_candidate_type.casefold())
            recognized_types = [
                value
                for value in candidate_type_values
                if value in visual_claim_types | structural_claim_types
            ]
            if not recognized_types:
                potentially_malformed_owner = candidate_kind_malformed or (
                    not candidate_type_values
                    and (
                        candidate.get("region_role") == "content_region"
                        or any(
                            candidate.get(key) is not None
                            for key in (
                                "rows",
                                "cells",
                                "fields",
                                "table_evidence",
                            )
                        )
                    )
                )
                if potentially_malformed_owner and any(
                    _owner_material_overlap(value, target)
                    for value in _owner_locatable_public_bboxes(
                        candidate.get("bbox"),
                        default_unit=page_unit,
                    )
                ):
                    raise ValueError("untyped owner overlaps chart")
                continue
            candidate_type = recognized_types[0]
            candidate_kind_malformed = candidate_kind_malformed or (
                len(set(candidate_type_values)) != 1
            )
            try:
                candidate_bbox = _owner_public_bbox(
                    candidate.get("bbox"),
                    default_unit=page_unit,
                )
            except (TypeError, ValueError):
                locatable = _owner_locatable_public_bboxes(
                    candidate.get("bbox"),
                    default_unit=page_unit,
                )
                if candidate_type in visual_claim_types and any(
                    _owner_material_overlap(value, target) for value in locatable
                ):
                    raise ValueError("malformed visual owner overlaps chart")
                if candidate_type in structural_claim_types and any(
                    _owner_material_overlap(value, target) for value in locatable
                ):
                    raise ValueError("malformed structural owner overlaps chart")
                continue
            if candidate_index == item_index:
                current_claim_is_exact = (
                    not candidate_kind_malformed
                    and candidate_type in {"chart", "image"}
                    and candidate_bbox == target
                )
                continue
            if candidate_kind_malformed and (
                (
                    candidate_type in visual_claim_types
                    and _owner_material_overlap(candidate_bbox, target)
                )
                or (
                    candidate_type in structural_claim_types
                    and _owner_material_overlap(candidate_bbox, target)
                )
            ):
                raise ValueError("malformed owner kind overlaps chart")
            if candidate_type in visual_claim_types and _owner_material_overlap(
                candidate_bbox,
                target,
            ):
                raise ValueError("chart owner overlaps another visual claim")
            if candidate_type in structural_claim_types and _owner_material_overlap(
                candidate_bbox,
                target,
            ):
                if candidate_type == "table_candidate" and (
                    _table_candidate_is_superseded_by_chart(
                        candidate,
                        owner_item_id=owner_item_id,
                        owner_item=page_items[item_index],
                        owner_bbox=target,
                        page_unit=page_unit,
                        page_index=page_index,
                        source_document_sha256=source_document_sha256,
                    )
                ):
                    continue
                raise ValueError("chart owner overlaps a structural claim")
        if not current_claim_is_exact:
            raise ValueError("chart owner source claim is ambiguous")

        detected_records = _owner_detected_image_records(
            detected_images,
            input_kind=input_kind,
            page_width=normalized_page_width,
            page_height=normalized_page_height,
            page_unit=page_unit,
        )
        docling_records = _owner_docling_picture_records(
            raw_graph,
            page_index=page_index,
            page_height=normalized_page_height,
            page_unit=page_unit,
        )
        for records in (detected_records, docling_records):
            valid_source_ids = [
                record.evidence_id for record in records if record.valid
            ]
            if len(valid_source_ids) != len(set(valid_source_ids)):
                raise ValueError("chart owner source identity is ambiguous")
        detected_overlapping = [
            record
            for record in detected_records
            if _owner_material_overlap(record.bbox, target)
        ]
        docling_overlapping = [
            record
            for record in docling_records
            if _owner_material_overlap(record.bbox, target)
        ]
        if any(not record.valid for record in detected_overlapping) or any(
            not record.valid for record in docling_overlapping
        ):
            raise ValueError("chart owner has malformed overlapping evidence")
        detected_exact = [
            record for record in detected_overlapping if record.bbox == target
        ]
        docling_exact = [
            record for record in docling_overlapping if record.bbox == target
        ]
        if (
            len(detected_overlapping) != len(detected_exact)
            or len(docling_overlapping) != len(docling_exact)
            or len(detected_exact) > 1
            or len(docling_exact) > 1
            or (not detected_exact and not docling_exact)
            or (input_kind == "pdf" and not docling_exact)
        ):
            raise ValueError("chart owner source geometry differs")

        evidence = [*detected_exact, *docling_exact]
        proof_kind: Literal[
            "detected_image",
            "docling_picture",
            "detected_image_and_docling_picture",
        ]
        if detected_exact and docling_exact:
            proof_kind = "detected_image_and_docling_picture"
        elif detected_exact:
            proof_kind = "detected_image"
        else:
            proof_kind = "docling_picture"
        evidence_ids = [record.evidence_id for record in evidence]
        if any(value is None for value in evidence_ids):
            raise ValueError("chart owner evidence identity differs")
        evidence_sha256 = hashlib.sha256(
            json.dumps(
                [record.evidence_sha256 for record in evidence],
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return ChartOwnerGeometryProof(
            schema_version="1.0",
            policy_id="ffd-015-chart-owner-geometry-v1",
            source_document_sha256=source_document_sha256,
            render_source_sha256=render_source_sha256,
            owner_item_id=owner_item_id,
            page_index=page_index,
            owner_bbox=target,
            input_kind=input_kind,
            proof_kind=proof_kind,
            source_evidence_ids=[str(value) for value in evidence_ids],
            source_evidence_sha256=evidence_sha256,
        )
    except (
        MemoryError,
        OverflowError,
        RecursionError,
        TypeError,
        ValueError,
    ):
        return None
    except Exception:  # noqa: BLE001 - hostile Mapping implementations fail closed
        return None


def _package_version(distribution: str) -> str:
    try:
        value = importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        value = "unknown"
    return value[:64] or "unknown"


def _flatten_white(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    flattened = Image.new("RGB", rgba.size, (255, 255, 255))
    flattened.paste(rgba, mask=rgba.getchannel("A"))
    rgba.close()
    return flattened


def _png_bytes(image: Image.Image, *, maximum: int) -> bytes:
    flattened = _flatten_white(image)
    try:
        output = io.BytesIO()
        flattened.save(
            output,
            format="PNG",
            optimize=False,
            compress_level=9,
        )
        data = output.getvalue()
    finally:
        flattened.close()
    if not data or len(data) > maximum:
        raise _AssetRefusal("asset_byte_limit")
    return data


def _render_pdf(
    source: bytes,
    *,
    page_index: int,
    bbox: VisualBoundingBox,
    limits: ChartAssetLimits,
) -> tuple[
    bytes,
    int,
    int,
    float,
    str,
    str,
    VisualBoundingBox,
    list[int],
    list[int],
]:
    document: Any | None = None
    page: Any | None = None
    bitmap: Any | None = None
    try:
        document = pdfium.PdfDocument(source)
        if page_index > len(document):
            raise _AssetRefusal("page_unavailable")
        page = document[page_index - 1]
        page_width, page_height = (float(value) for value in page.get_size())
        if (
            bbox.unit != "pt"
            or bbox.x < 0
            or bbox.y < 0
            or bbox.width <= 0
            or bbox.height <= 0
        ):
            raise _AssetRefusal("owner_geometry_invalid")
        if (
            bbox.x + bbox.width > page_width + 1e-6
            or bbox.y + bbox.height > page_height + 1e-6
        ):
            raise _AssetRefusal("owner_outside_page")
        scale = limits.pdf_dpi / 72.0
        page_pixel_width = math.ceil(page_width * scale)
        page_pixel_height = math.ceil(page_height * scale)
        # PDFium maps through the integer full-page bitmap dimensions.  On a
        # non-integral page size those effective axis scales differ slightly
        # from the requested scalar DPI.  Select device boundaries with that
        # exact mapping so the crop is outward on every edge.
        device_scale_x = page_pixel_width / page_width
        device_scale_y = page_pixel_height / page_height
        left_pixel = math.floor(bbox.x * device_scale_x)
        top_pixel = math.floor(bbox.y * device_scale_y)
        right_pixel = math.ceil((bbox.x + bbox.width) * device_scale_x)
        bottom_pixel = math.ceil((bbox.y + bbox.height) * device_scale_y)
        width = right_pixel - left_pixel
        height = bottom_pixel - top_pixel
        if width <= 0 or height <= 0:
            raise _AssetRefusal("owner_geometry_invalid")
        if width > limits.max_width or height > limits.max_height:
            raise _AssetRefusal("crop_dimension_limit")
        if width < limits.min_width or height < limits.min_height:
            raise _AssetRefusal("crop_legibility_limit")
        if width * height > limits.max_pixels:
            raise _AssetRefusal("crop_pixel_limit")

        def crop_margin(pixel_count: int) -> float:
            # PDFium rounds every crop margin upward in device pixels. Nudge
            # an aligned positive boundary inward so binary float noise cannot
            # accidentally remove a second pixel.
            if pixel_count <= 0:
                return 0.0
            return (pixel_count - 1e-7) / scale

        right_margin_pixels = page_pixel_width - right_pixel
        bottom_margin_pixels = page_pixel_height - bottom_pixel
        if right_margin_pixels < 0 or bottom_margin_pixels < 0:
            raise _AssetRefusal("owner_outside_page")
        bitmap = page.render(
            scale=scale,
            crop=(
                crop_margin(left_pixel),
                crop_margin(bottom_margin_pixels),
                crop_margin(right_margin_pixels),
                crop_margin(top_pixel),
            ),
            fill_color=(255, 255, 255, 255),
            optimize_mode="print",
        )
        rendered = bitmap.to_pil()
        try:
            if rendered.size != (width, height):
                raise _AssetRefusal("render_failed")
            if rendered.width > limits.max_width or rendered.height > limits.max_height:
                raise _AssetRefusal("crop_dimension_limit")
            if rendered.width < limits.min_width or rendered.height < limits.min_height:
                raise _AssetRefusal("crop_legibility_limit")
            if rendered.width * rendered.height > limits.max_pixels:
                raise _AssetRefusal("crop_pixel_limit")
            data = _png_bytes(rendered, maximum=limits.max_bytes)
            # PDFium's page-to-device conversion uses the integer dimensions
            # of the full rendered page, so ``1 / scale`` is only an
            # approximation for non-integral page sizes.  Record the actual
            # page-space crop boundaries exposed by the renderer.
            position = bitmap.get_posconv(page)
            left_pdf, top_pdf_from_bottom = position.to_page(0, 0)
            right_pdf, bottom_pdf_from_bottom = position.to_page(
                rendered.width,
                rendered.height,
            )
            rendered_bbox = VisualBoundingBox(
                x=float(left_pdf),
                y=page_height - float(top_pdf_from_bottom),
                width=float(right_pdf) - float(left_pdf),
                height=float(top_pdf_from_bottom) - float(bottom_pdf_from_bottom),
                unit="pt",
            )
            return (
                data,
                rendered.width,
                rendered.height,
                scale,
                "pypdfium2",
                _package_version("pypdfium2"),
                rendered_bbox,
                [page_pixel_width, page_pixel_height],
                [
                    left_pixel,
                    bottom_margin_pixels,
                    right_margin_pixels,
                    top_pixel,
                ],
            )
        finally:
            rendered.close()
    except _AssetRefusal:
        raise
    except Exception as exc:
        raise _AssetRefusal("render_failed") from exc
    finally:
        if bitmap is not None:
            bitmap.close()
        if page is not None:
            page.close()
        if document is not None:
            document.close()


def _render_image(
    source: bytes,
    *,
    page_index: int,
    bbox: VisualBoundingBox,
    limits: ChartAssetLimits,
) -> tuple[
    bytes,
    int,
    int,
    float,
    str,
    str,
    VisualBoundingBox,
    None,
    None,
]:
    if bbox.unit != "px" or bbox.width <= 0 or bbox.height <= 0:
        raise _AssetRefusal("owner_geometry_invalid")
    try:
        with Image.open(io.BytesIO(source)) as opened:
            frame_count = int(getattr(opened, "n_frames", 1) or 1)
            frame = page_index - 1 if frame_count > 1 else 0
            if not 0 <= frame < frame_count:
                raise _AssetRefusal("page_unavailable")
            opened.seek(frame)
            coordinates = (
                bbox.x,
                bbox.y,
                bbox.x + bbox.width,
                bbox.y + bbox.height,
            )
            rounded = tuple(round(value) for value in coordinates)
            if any(
                not math.isclose(left, right, rel_tol=0.0, abs_tol=1e-6)
                for left, right in zip(coordinates, rounded, strict=True)
            ):
                raise _AssetRefusal("owner_geometry_invalid")
            left, top, right, bottom = rounded
            if (
                min(left, top) < 0
                or right > opened.width
                or bottom > opened.height
            ):
                raise _AssetRefusal("owner_outside_page")
            width = right - left
            height = bottom - top
            if width <= 0 or height <= 0:
                raise _AssetRefusal("owner_geometry_invalid")
            if width > limits.max_width or height > limits.max_height:
                raise _AssetRefusal("crop_dimension_limit")
            if width < limits.min_width or height < limits.min_height:
                raise _AssetRefusal("crop_legibility_limit")
            if width * height > limits.max_pixels:
                raise _AssetRefusal("crop_pixel_limit")
            crop = opened.crop((left, top, right, bottom))
            try:
                data = _png_bytes(crop, maximum=limits.max_bytes)
            finally:
                crop.close()
            return (
                data,
                width,
                height,
                1.0,
                "pillow",
                _package_version("Pillow"),
                bbox,
                None,
                None,
            )
    except _AssetRefusal:
        raise
    except (MemoryError, OSError, UnidentifiedImageError, ValueError) as exc:
        raise _AssetRefusal("render_failed") from exc


def render_chart_source_asset(
    *,
    source: bytes | None,
    input_kind: str,
    page_index: int,
    bbox: VisualBoundingBox,
    owner_item_id: str,
    source_document_sha256: str,
    owner_geometry_proof: ChartOwnerGeometryProof | None,
    expected_render_source_sha256: str | None = None,
    limits: ChartAssetLimits,
    ledger: ChartAssetLedger,
) -> ChartAssetAttempt:
    """Render and atomically reserve one deterministic inline chart asset."""

    now = time.monotonic()
    if ledger.deadline_monotonic is None:
        ledger.deadline_monotonic = now + limits.document_timeout_seconds
    if now >= ledger.deadline_monotonic:
        return ChartAssetAttempt(None, "document_render_timeout")
    if ledger.attempt_count >= limits.max_assets:
        return ChartAssetAttempt(None, "document_asset_count_limit")
    ledger.attempt_count += 1
    if ledger.asset_count >= limits.max_assets:
        return ChartAssetAttempt(None, "document_asset_count_limit")
    if not source:
        return ChartAssetAttempt(None, "source_bytes_unavailable")
    if re.fullmatch(_SHA256_PATTERN, source_document_sha256) is None:
        return ChartAssetAttempt(None, "source_bytes_unavailable")
    render_source_sha256 = hashlib.sha256(source).hexdigest()
    expected_render_identity = (
        expected_render_source_sha256 or source_document_sha256
    )
    if (
        re.fullmatch(_SHA256_PATTERN, expected_render_identity) is None
        or render_source_sha256 != expected_render_identity
    ):
        return ChartAssetAttempt(None, "source_integrity_mismatch")
    normalized_bbox = _owner_normalized_bbox(bbox)
    if (
        type(owner_geometry_proof) is not ChartOwnerGeometryProof
        or owner_geometry_proof.source_document_sha256 != source_document_sha256
        or owner_geometry_proof.render_source_sha256 != expected_render_identity
        or owner_geometry_proof.owner_item_id != owner_item_id
        or owner_geometry_proof.page_index != page_index
        or owner_geometry_proof.owner_bbox != normalized_bbox
        or owner_geometry_proof.input_kind != input_kind
    ):
        return ChartAssetAttempt(None, "owner_geometry_invalid")
    try:
        if input_kind not in {"pdf", "image"}:
            raise _AssetRefusal("source_kind_unsupported")
        rendered = _render_before_deadline(
            source,
            input_kind=input_kind,
            page_index=page_index,
            bbox=bbox,
            limits=limits,
            document_deadline=ledger.deadline_monotonic,
        )
        if input_kind == "pdf":
            effective_dpi: float | None = limits.pdf_dpi
            bbox_rounding = "outward_device_pixels"
        else:
            effective_dpi = None
            bbox_rounding = "exact_integer"
        (
            data,
            width,
            height,
            scale,
            renderer,
            renderer_version,
            rendered_bbox,
            page_device_dimensions,
            crop_device_margins,
        ) = rendered
        if ledger.total_bytes + len(data) > limits.max_total_bytes:
            raise _AssetRefusal("document_asset_byte_limit")
        digest = hashlib.sha256(data).hexdigest()
        asset_id = _stable_id(
            "chart-asset",
            source_document_sha256,
            render_source_sha256,
            owner_item_id,
            page_index,
            bbox.model_dump(mode="json"),
            owner_geometry_proof.proof_kind,
            owner_geometry_proof.source_evidence_ids,
            owner_geometry_proof.source_evidence_sha256,
            rendered_bbox.model_dump(mode="json"),
            page_device_dimensions,
            crop_device_margins,
            "chart-source-inline-png-v1",
            digest,
        )
        data_uri = _PNG_PREFIX + base64.b64encode(data).decode("ascii")
        projected_response_bytes = len(data_uri.encode("ascii")) * (
            _PUBLIC_DATA_URI_COPIES
        )
        if (
            ledger.response_bytes + projected_response_bytes
            > limits.max_response_bytes
        ):
            raise _AssetRefusal("response_byte_limit")
        asset = ChartSourceAsset(
            asset_id=asset_id,
            source_document_sha256=source_document_sha256,
            render_source_sha256=render_source_sha256,
            owner_item_id=owner_item_id,
            physical_page=page_index,
            source_bbox=bbox,
            owner_geometry_proof_kind=owner_geometry_proof.proof_kind,
            owner_geometry_evidence_ids=owner_geometry_proof.source_evidence_ids,
            owner_geometry_evidence_sha256=(
                owner_geometry_proof.source_evidence_sha256
            ),
            rendered_bbox=rendered_bbox,
            coordinate_system="page_top_left",
            pixel_to_page_transform=[
                rendered_bbox.width / width,
                0.0,
                0.0,
                rendered_bbox.height / height,
                rendered_bbox.x,
                rendered_bbox.y,
            ],
            page_device_dimensions=page_device_dimensions,
            crop_device_margins=crop_device_margins,
            renderer=renderer,
            renderer_version=renderer_version,
            render_policy="chart-source-inline-png-v1",
            source_kind=input_kind,
            render_scale=scale,
            effective_dpi=effective_dpi,
            width=width,
            height=height,
            mime_type="image/png",
            encoding="data_uri_base64",
            byte_length=len(data),
            sha256=digest,
            data_uri=data_uri,
            color_space="srgb",
            alpha_policy="flatten_white",
            antialiasing_policy="renderer_default",
            interpolation_policy="none",
            bbox_rounding=bbox_rounding,
            padding=0.0,
        )
    except _AssetRefusal as refusal:
        reason = (
            "document_render_timeout"
            if refusal.reason == "render_timeout"
            and ledger.deadline_monotonic is not None
            and time.monotonic() >= ledger.deadline_monotonic
            else refusal.reason
        )
        return ChartAssetAttempt(None, reason)
    except (MemoryError, OSError, TypeError, ValueError, OverflowError):
        return ChartAssetAttempt(None, "mime_validation_failed")
    ledger.asset_count += 1
    ledger.total_bytes += asset.byte_length
    ledger.response_bytes += projected_response_bytes
    return ChartAssetAttempt(asset, None)


def chart_asset_limits(settings: Any) -> ChartAssetLimits:
    return ChartAssetLimits(
        min_width=int(getattr(settings, "charts_source_asset_min_width", 64)),
        min_height=int(getattr(settings, "charts_source_asset_min_height", 64)),
        max_width=int(getattr(settings, "charts_source_asset_max_width", 2_048)),
        max_height=int(getattr(settings, "charts_source_asset_max_height", 2_048)),
        max_pixels=int(getattr(settings, "charts_source_asset_max_pixels", 4_000_000)),
        max_bytes=int(getattr(settings, "charts_source_asset_max_bytes", 2_097_152)),
        max_assets=int(getattr(settings, "charts_source_asset_max_assets", 64)),
        max_total_bytes=int(
            getattr(settings, "charts_source_asset_max_total_bytes", 16_777_216)
        ),
        max_response_bytes=int(
            getattr(settings, "charts_source_asset_max_response_bytes", 50_331_648)
        ),
        render_timeout_seconds=float(
            getattr(settings, "charts_source_asset_timeout_seconds", 2.0)
        ),
        document_timeout_seconds=float(
            getattr(settings, "charts_source_asset_document_timeout_seconds", 8.0)
        ),
        pdf_dpi=float(getattr(settings, "charts_source_asset_pdf_dpi", 144.0)),
    )


def _unique_evidence(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))[:_MAX_REFERENCES]


def _unavailable_confidence(reason: str = "not_calibrated") -> ChartConfidence:
    return ChartConfidence(value=None, unavailable_reason=reason)


def _transcript_evidence(
    structure: VisualStructure,
    *,
    extraction_method: str | None = None,
    omit_generated_caption: bool = False,
) -> list[str]:
    """Return only label evidence that actually supports a transcript source."""

    evidence_by_id = {record.id: record for record in structure.evidence}
    output: list[str] = []
    for label in structure.labels:
        if omit_generated_caption and label.role == "caption":
            continue
        for evidence_id in label.evidence_ids:
            record = evidence_by_id.get(evidence_id)
            if (
                record is None
                or record.kind != "label"
                or (
                    extraction_method is not None
                    and record.provenance.extraction_method != extraction_method
                )
            ):
                continue
            output.append(evidence_id)
    unique = list(dict.fromkeys(output))
    return unique if len(unique) <= _MAX_REFERENCES else []


def _native_transcript_evidence(
    item: Mapping[str, Any],
    structure: VisualStructure,
    text: str,
) -> list[str]:
    """Verify the locally attached native aggregate against its occurrences."""

    raw_meta = item.get("meta")
    source_meta = (
        raw_meta.get("phase05_visual_source_text")
        if isinstance(raw_meta, Mapping)
        else None
    )
    occurrences = item.get("visual_source_text_occurrences")
    lines = item.get("visual_source_text_lines")
    if (
        not isinstance(source_meta, Mapping)
        or source_meta.get("method")
        not in {
            "pdf_text_layer_inside_visual_bbox",
            "pdf_source_line_owned_by_visual_child",
        }
        or source_meta.get("text_sha256")
        != hashlib.sha256(text.encode("utf-8", errors="strict")).hexdigest()
        or not isinstance(occurrences, Sequence)
        or isinstance(occurrences, (str, bytes, bytearray))
        or not occurrences
        or len(occurrences) > _MAX_REFERENCES
        or type(source_meta.get("occurrence_count")) is not int
        or source_meta.get("occurrence_count") != len(occurrences)
        or not isinstance(lines, Sequence)
        or isinstance(lines, (str, bytes, bytearray))
        or not lines
        or len(lines) > _MAX_REFERENCES
    ):
        return []
    occurrence_ids: list[str] = []
    for occurrence in occurrences:
        if not isinstance(occurrence, Mapping):
            return []
        occurrence_id = occurrence.get("occurrence_id", occurrence.get("id"))
        if (
            type(occurrence_id) is not str
            or not occurrence_id
            or len(occurrence_id) > 128
        ):
            return []
        occurrence_ids.append(occurrence_id)
    if occurrence_ids != list(dict.fromkeys(occurrence_ids)):
        return []
    line_texts: list[str] = []
    for line in lines:
        if not isinstance(line, Mapping) or type(line.get("text")) is not str:
            return []
        line_text = str(line["text"])
        if not line_text:
            return []
        line_texts.append(line_text)
    if "\n".join(line_texts).strip() != text:
        return []

    evidence_ids = _transcript_evidence(
        structure,
        extraction_method="explicit_text",
    )
    evidence_by_id = {record.id: record for record in structure.evidence}
    evidence_occurrence_ids: list[str] = []
    for evidence_id in evidence_ids:
        source_token_ids = evidence_by_id[evidence_id].provenance.source_token_ids
        if len(source_token_ids) != 1:
            return []
        evidence_occurrence_ids.append(source_token_ids[0])
    if evidence_occurrence_ids != occurrence_ids:
        return []
    return evidence_ids


def replay_chart_transcript(
    item: Mapping[str, Any],
    structure: VisualStructure,
) -> ChartTranscript:
    """Replay the one attributable transcript from its public owner evidence."""

    native_text = item.get("visual_source_text")
    if (
        isinstance(native_text, str)
        and native_text
        and len(native_text) <= _MAX_TRANSCRIPT_CHARS
    ):
        native_evidence_ids = _native_transcript_evidence(
            item,
            structure,
            native_text,
        )
        if native_evidence_ids:
            return ChartTranscript(
                status="available",
                source="native",
                text=native_text,
                text_sha256=hashlib.sha256(native_text.encode("utf-8")).hexdigest(),
                evidence_ids=native_evidence_ids,
                confidence=_unavailable_confidence("source_confidence_unavailable"),
            )

    ocr_text = item.get("ocr_text")
    if (
        isinstance(ocr_text, str)
        and ocr_text
        and len(ocr_text) <= _MAX_TRANSCRIPT_CHARS
    ):
        ocr_evidence_ids = _transcript_evidence(
            structure,
            extraction_method="ocr",
        )
        if ocr_evidence_ids:
            confidence_value = item.get("confidence")
            confidence = (
                ChartConfidence(value=float(confidence_value), unavailable_reason=None)
                if isinstance(confidence_value, (int, float))
                and not isinstance(confidence_value, bool)
                and math.isfinite(float(confidence_value))
                and 0 <= float(confidence_value) <= 1
                else _unavailable_confidence("source_confidence_unavailable")
            )
            return ChartTranscript(
                status="available",
                source="ocr",
                text=ocr_text,
                text_sha256=hashlib.sha256(ocr_text.encode("utf-8")).hexdigest(),
                evidence_ids=ocr_evidence_ids,
                confidence=confidence,
            )

    omit_generated_caption = bool(item.get("caption_generated") is True)
    source_labels = [
        label
        for label in structure.labels
        if label.text
        and not (omit_generated_caption and label.role == "caption")
    ]
    label_text = "\n".join(label.text for label in source_labels)
    if label_text and len(label_text) <= _MAX_TRANSCRIPT_CHARS:
        label_evidence_ids = _transcript_evidence(
            structure,
            omit_generated_caption=omit_generated_caption,
        )
        if not label_evidence_ids:
            label_text = ""
    if label_text:
        return ChartTranscript(
            status="available",
            source="source_labels",
            text=label_text,
            text_sha256=hashlib.sha256(label_text.encode("utf-8")).hexdigest(),
            evidence_ids=label_evidence_ids,
            confidence=_unavailable_confidence("source_confidence_unavailable"),
        )
    return ChartTranscript(
        status="unavailable",
        source=None,
        text=None,
        text_sha256=None,
        evidence_ids=[],
        confidence=_unavailable_confidence("source_confidence_unavailable"),
    )


def classify_chart_family(
    item: Mapping[str, Any],
    structure: VisualStructure,
    *,
    minimum_confidence: float = 0.6,
) -> ChartFamilyClassification:
    evidence_ids = list(structure.region.evidence_ids)
    raw_classification = item.get("classification")
    class_name = (
        str(raw_classification.get("class_name") or "").casefold()
        if isinstance(raw_classification, Mapping)
        else ""
    )
    mapping = {
        "bar_chart": "bar",
        "histogram": "bar",
        "line_chart": "line",
        "pie_chart": "pie",
        "area_chart": "area",
        "scatter_plot": "scatter",
        "bubble_chart": "bubble",
    }
    declared_family = mapping.get(class_name)
    confidence_value = (
        raw_classification.get("confidence")
        if isinstance(raw_classification, Mapping)
        else None
    )
    declared_is_usable = declared_family is not None and (
        isinstance(confidence_value, (int, float))
        and not isinstance(confidence_value, bool)
        and math.isfinite(float(confidence_value))
        and minimum_confidence <= float(confidence_value) <= 1
    )
    raw_office = item.get("office_chart")
    office_type = (
        str(raw_office.get("chart_type") or "")
        if isinstance(raw_office, Mapping)
        else ""
    )
    office_mapping = {
        "barChart": "bar",
        "lineChart": "line",
        "pieChart": "pie",
        "areaChart": "area",
    }
    office_family = office_mapping.get(office_type)
    if (
        declared_is_usable
        and office_family is not None
        and declared_family != office_family
    ):
        return ChartFamilyClassification(
            status="undetermined",
            family="undetermined",
            classifier_version="chart-family-source-evidence-v1",
            reason_codes=["multiple_family_signals"],
            evidence_ids=evidence_ids,
            confidence=_unavailable_confidence(),
        )
    if declared_is_usable:
        assert declared_family is not None
        return ChartFamilyClassification(
            status="classified",
            family=declared_family,
            classifier_version="chart-family-source-evidence-v1",
            reason_codes=["declared_classifier_family"],
            evidence_ids=evidence_ids,
            confidence=ChartConfidence(
                value=float(confidence_value),
                unavailable_reason=None,
            ),
        )
    if office_family is not None:
        return ChartFamilyClassification(
            status="classified",
            family=office_family,
            classifier_version="chart-family-source-evidence-v1",
            reason_codes=["native_office_family"],
            evidence_ids=evidence_ids,
            confidence=_unavailable_confidence(),
        )
    return ChartFamilyClassification(
        status="undetermined",
        family="undetermined",
        classifier_version="chart-family-source-evidence-v1",
        reason_codes=["insufficient_source_features"],
        evidence_ids=evidence_ids,
        confidence=_unavailable_confidence(),
    )


def classify_chart_complexity(
    structure: VisualStructure,
    family: ChartFamilyClassification,
) -> ChartComplexityClassification:
    reasons: list[str] = []
    evidence_ids: list[str] = []
    if len(structure.panels) > 1:
        reasons.append("multi_panel_geometry")
        evidence_ids.extend(
            evidence_id
            for panel in structure.panels
            for evidence_id in panel.evidence_ids
        )
    if len(structure.axes) > 2:
        reasons.append("multiple_axes")
        evidence_ids.extend(
            evidence_id for axis in structure.axes for evidence_id in axis.evidence_ids
        )
    if len(structure.legends) > 1:
        reasons.append("multiple_legends")
        evidence_ids.extend(
            evidence_id
            for legend in structure.legends
            for evidence_id in legend.evidence_ids
        )
    primitive_kind_map = {
        "rectangle": "bar",
        "curve": "line",
        "line": "line",
    }
    primitives = (
        structure.vector_inventory.primitives
        if structure.vector_inventory is not None
        else []
    )
    mark_kinds = {
        primitive_kind_map[primitive.kind]
        for primitive in primitives
        if primitive.supported and primitive.kind in primitive_kind_map
    }
    if len(mark_kinds) > 1:
        reasons.append("multiple_mark_types")
        evidence_ids.extend(
            evidence_id
            for primitive in primitives
            if primitive.supported
            and primitive.kind in primitive_kind_map
            and primitive_kind_map[primitive.kind] in mark_kinds
            for evidence_id in primitive.evidence_ids
        )
    label_text = " ".join(label.text for label in structure.labels)
    if len(structure.labels) >= 48 and len(_NUMERIC_TOKEN_RE.findall(label_text)) >= 8:
        reasons.append("dense_source_labels")
        evidence_ids.extend(
            evidence_id
            for label in structure.labels
            for evidence_id in label.evidence_ids
        )
    if family.family in {"bubble", "mixed", "multi_panel"}:
        reasons.append("multi_encoding_family")
        evidence_ids.extend(family.evidence_ids)
    if reasons:
        return ChartComplexityClassification(
            status="complex",
            classifier_version="chart-complexity-source-evidence-v1",
            reason_codes=list(dict.fromkeys(reasons)),
            evidence_ids=_unique_evidence(evidence_ids),
            confidence=_unavailable_confidence(),
        )
    regular_inventory_complete = False
    if family.family == "bar":
        observed, ambiguous = _bar_completeness(structure, family)
        complexity_inventory = set(_BAR_REQUIRED_FEATURES) - {"serialization"}
        regular_inventory_complete = (
            complexity_inventory <= set(observed)
            and not ambiguous
            and len(structure.labels) <= 24
            and len(structure.legends) <= 1
        )
    if regular_inventory_complete:
        return ChartComplexityClassification(
            status="regular",
            classifier_version="chart-complexity-source-evidence-v1",
            reason_codes=["single_supported_family"],
            evidence_ids=_unique_evidence(family.evidence_ids),
            confidence=_unavailable_confidence(),
        )
    return ChartComplexityClassification(
        status="undetermined",
        classifier_version="chart-complexity-source-evidence-v1",
        reason_codes=["insufficient_source_features"],
        evidence_ids=_unique_evidence(structure.region.evidence_ids),
        confidence=_unavailable_confidence(),
    )


def _analyzer_configuration(settings: Any) -> tuple[list[str], str]:
    flags: dict[str, Any] = {
        "capability_matrix_version": "chart-semantic-capabilities-v1",
        "charts_vector_inventory_enabled": bool(
            getattr(settings, "charts_vector_inventory_enabled", False)
        ),
        "charts_structure_enabled": bool(
            getattr(settings, "charts_structure_enabled", False)
        ),
        "charts_vector_values_enabled": bool(
            getattr(settings, "charts_vector_values_enabled", False)
        ),
        "charts_raster_analysis_enabled": bool(
            getattr(settings, "charts_raster_analysis_enabled", False)
        ),
        "charts_raster_structure_enabled": bool(
            getattr(settings, "charts_raster_structure_enabled", False)
        ),
        "charts_raster_bar_values_enabled": bool(
            getattr(settings, "charts_raster_bar_values_enabled", False)
        ),
        "charts_raster_line_values_enabled": bool(
            getattr(settings, "charts_raster_line_values_enabled", False)
        ),
        "charts_structured_output_enabled": bool(
            getattr(settings, "charts_structured_output_enabled", False)
        ),
    }
    identifiers = [
        identifier
        for field, identifier in (
            ("charts_vector_inventory_enabled", "vector-inventory-v1"),
            ("charts_structure_enabled", "vector-structure-v1"),
            ("charts_vector_values_enabled", "vector-bar-values-v1"),
            ("charts_raster_analysis_enabled", "raster-analysis-gate-v1"),
            ("charts_raster_structure_enabled", "raster-structure-v1"),
            ("charts_raster_bar_values_enabled", "raster-bar-values-v1"),
            ("charts_raster_line_values_enabled", "raster-line-values-v1"),
            ("charts_structured_output_enabled", "chart-completeness-v1"),
        )
        if flags[field]
    ]
    digest = hashlib.sha256(
        json.dumps(flags, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    return identifiers, digest


_BAR_REQUIRED_FEATURES: list[ChartSemanticFeature] = [
    "region",
    "source_evidence",
    "family",
    "panels",
    "axes",
    "categories",
    "series",
    "points",
    "ownership",
    "ambiguity_closure",
    "serialization",
]
# Promotion is allow-listed, not inferred from concern-name substrings.  A new
# producer concern is blocking until the bar-family capability contract has
# explicitly reviewed it.  This is deliberately much stricter than display:
# source images and transcripts remain available when structured promotion is
# withheld.
_BAR_NONBLOCKING_CONCERNS = frozenset(
    {
        ("visual_classifier_unavailable", "info", "schema"),
    }
)


def _bar_analyzer_approved(settings: Any) -> bool:
    vector_values = bool(
        getattr(settings, "charts_vector_values_enabled", False)
    )
    raster_values = bool(
        getattr(settings, "charts_raster_analysis_enabled", False)
    ) and bool(getattr(settings, "charts_raster_bar_values_enabled", False))
    return bool(getattr(settings, "charts_structured_output_enabled", False)) and (
        vector_values or raster_values
    )


def _bar_completeness(
    structure: VisualStructure,
    family: ChartFamilyClassification,
    *,
    item: Mapping[str, Any] | None = None,
    require_serialization: bool = True,
) -> tuple[list[ChartSemanticFeature], list[str]]:
    """Apply the first closed family-specific semantic promotion gate.

    This deliberately prefers false negatives: a sparse or optional-point bar
    chart remains image-primary until a richer family contract can prove which
    combinations are absent in the source.
    """

    observed: list[ChartSemanticFeature] = ["region"]
    evidence_ids = {record.id for record in structure.evidence}
    if evidence_ids and set(structure.region.evidence_ids) <= evidence_ids:
        observed.append("source_evidence")
    if family.status == "classified" and family.family == "bar":
        observed.append("family")

    panel = structure.panels[0] if len(structure.panels) == 1 else None
    if panel is not None:
        observed.append("panels")
    x_axis = None
    y_axis = None
    if panel is not None:
        x_axes = [
            axis
            for axis in structure.axes
            if axis.panel_id == panel.id and axis.orientation == "x"
        ]
        y_axes = [
            axis
            for axis in structure.axes
            if axis.panel_id == panel.id and axis.orientation == "y"
        ]
        if (
            len(structure.axes) == 2
            and len(x_axes) == 1
            and len(y_axes) == 1
            and y_axes[0].scale == "linear"
            and y_axes[0].minimum is not None
            and y_axes[0].maximum is not None
            and y_axes[0].maximum > y_axes[0].minimum
            and y_axes[0].calibration_evidence_ids
        ):
            x_axis = x_axes[0]
            y_axis = y_axes[0]
            observed.append("axes")

    categories = tuple(x_axis.category_label_ids) if x_axis is not None else ()
    if categories and len(categories) == len(set(categories)):
        observed.append("categories")
    series_ids = tuple(value.id for value in structure.series)
    if (
        panel is not None
        and series_ids
        and len(series_ids) == len(set(series_ids))
        and all(panel.id in value.panel_ids for value in structure.series)
    ):
        observed.append("series")

    evidence_by_id = {record.id: record for record in structure.evidence}
    labels_by_id = {label.id: label for label in structure.labels}
    series_by_id = {value.id: value for value in structure.series}
    primitive_by_id = {
        primitive.id: primitive
        for primitive in (
            structure.vector_inventory.primitives
            if structure.vector_inventory is not None
            else ()
        )
    }
    point_pairs: list[tuple[str, str]] = []
    ownership_ambiguities: list[str] = []
    point_ownership = bool(
        panel is not None
        and x_axis is not None
        and y_axis is not None
        and categories
        and series_ids
        and structure.points
    )
    if point_ownership:
        allowed_axis_ids = {x_axis.id, y_axis.id}
        for point in structure.points:
            category = labels_by_id.get(point.category_label_id)
            series = series_by_id.get(point.series_id)
            required_point_evidence = {
                point.point_evidence_id,
                point.baseline_evidence_id,
                *point.source_geometry_evidence_ids,
                *(category.evidence_ids if category is not None else ()),
                *(series.evidence_ids if series is not None else ()),
                *(
                    evidence_id
                    for axis in structure.axes
                    if axis.id in point.axis_ids
                    for evidence_id in (
                        *axis.evidence_ids,
                        *axis.calibration_evidence_ids,
                    )
                ),
            }
            if (
                point.panel_id != panel.id
                or y_axis.id not in point.axis_ids
                or not set(point.axis_ids) <= allowed_axis_ids
                or point.category_label_id not in categories
                or point.series_id not in series_ids
                or not set(point.evidence_ids) <= evidence_ids
                or not required_point_evidence <= set(point.evidence_ids)
                or point.path_id is not None
                or point.mark_id is None
            ):
                point_ownership = False
                ownership_ambiguities.extend(point.evidence_ids)
                break
            point_pairs.append((point.category_label_id, point.series_id))
    expected_pairs = {
        (category_id, series_id)
        for category_id in categories
        for series_id in series_ids
    }
    points_complete = (
        point_ownership
        and len(point_pairs) == len(set(point_pairs))
        and set(point_pairs) == expected_pairs
    )
    if points_complete:
        observed.append("points")

    # Exhaustively account for every analyzer-produced bar mark, baseline, and
    # point record.  Semantic pairs alone are insufficient: an orphan source
    # mark can mean that one visible bar was silently omitted.  Raster marks
    # use evidence IDs directly; vector marks use supported rectangle
    # primitive IDs.  Mixed ownership is not an approved bar capability.
    raster_mark_ids = {
        record.id for record in structure.evidence if record.kind == "mark"
    }
    path_ids = {
        record.id for record in structure.evidence if record.kind == "path"
    }
    point_evidence_ids = {
        record.id for record in structure.evidence if record.kind == "point"
    }
    baseline_evidence_ids = {
        record.id for record in structure.evidence if record.kind == "baseline"
    }
    supported_vector_mark_ids = {
        primitive.id
        for primitive in primitive_by_id.values()
        if primitive.supported and primitive.kind == "rectangle"
    }
    owned_mark_ids = [
        point.mark_id for point in structure.points if point.mark_id is not None
    ]
    owned_point_evidence_ids = [point.point_evidence_id for point in structure.points]
    owned_baseline_evidence_ids = [
        point.baseline_evidence_id for point in structure.points
    ]
    expected_mark_ids = raster_mark_ids or supported_vector_mark_ids
    exclusive_mark_source = not (
        raster_mark_ids and supported_vector_mark_ids
    )
    source_marks_complete = bool(expected_mark_ids) and (
        set(owned_mark_ids) == expected_mark_ids
        and len(owned_mark_ids) == len(set(owned_mark_ids))
        and exclusive_mark_source
        and not path_ids
    )
    point_records_complete = (
        set(owned_point_evidence_ids) == point_evidence_ids
        and len(owned_point_evidence_ids) == len(set(owned_point_evidence_ids))
        and set(owned_baseline_evidence_ids) == baseline_evidence_ids
        and len(owned_baseline_evidence_ids)
        == len(set(owned_baseline_evidence_ids))
    )
    if not source_marks_complete:
        ownership_ambiguities.extend(
            sorted(expected_mark_ids.symmetric_difference(set(owned_mark_ids)))
        )
        ownership_ambiguities.extend(sorted(path_ids))
    if not point_records_complete:
        ownership_ambiguities.extend(
            sorted(
                point_evidence_ids.symmetric_difference(
                    set(owned_point_evidence_ids)
                )
            )
        )
        ownership_ambiguities.extend(
            sorted(
                baseline_evidence_ids.symmetric_difference(
                    set(owned_baseline_evidence_ids)
                )
            )
        )

    primitive_limit_reached = bool(
        structure.vector_inventory is not None
        and structure.vector_inventory.primitive_limit_reached
    )
    if primitive_limit_reached:
        ownership_ambiguities.extend(structure.region.evidence_ids)

    # If a legend exists, every entry must identify exactly one published
    # series and every swatch must be accounted for.  Without a legend, series
    # source identities still have to remain unique (the strict model enforces
    # that invariant before this gate).
    series_relations_complete = True
    if structure.legends:
        legend_entries = [
            entry for legend in structure.legends for entry in legend.entries
        ]
        entry_ids = [entry.id for entry in legend_entries]
        owned_entry_ids = [
            series.legend_entry_id
            for series in structure.series
            if series.legend_entry_id is not None
        ]
        swatch_ids = {
            record.id for record in structure.evidence if record.kind == "swatch"
        }
        series_relations_complete = (
            len(owned_entry_ids) == len(structure.series)
            and len(owned_entry_ids) == len(set(owned_entry_ids))
            and set(owned_entry_ids) == set(entry_ids)
            and {entry.swatch_evidence_id for entry in legend_entries} == swatch_ids
        )
        if not series_relations_complete:
            ownership_ambiguities.extend(entry_ids)
            ownership_ambiguities.extend(sorted(swatch_ids))

    if (
        points_complete
        and source_marks_complete
        and point_records_complete
        and series_relations_complete
    ):
        observed.append("ownership")

    blocking_concerns = [
        concern
        for concern in structure.concerns
        if (concern.code, concern.severity, concern.stage)
        not in _BAR_NONBLOCKING_CONCERNS
    ]
    ambiguous = _unique_evidence(
        [
            *ownership_ambiguities,
            *(
                evidence_id
                for concern in blocking_concerns
                for evidence_id in (
                    concern.evidence_ids or structure.region.evidence_ids
                )
            ),
        ]
    )
    if (
        not blocking_concerns
        and not ownership_ambiguities
        and not primitive_limit_reached
    ):
        observed.append("ambiguity_closure")
    serialization = structure.serialization
    serialization_matches = False
    if require_serialization and item is not None:
        try:
            replayed = replay_chart_serialization(item, structure)
            revalidated = validate_and_serialize_chart(item, structure)
            serialization_matches = bool(
                not revalidated.fallback.active
                and revalidated.points == structure.points
                and revalidated.serialization == replayed
                and serialization == replayed
            )
        except (MemoryError, TypeError, ValueError):
            serialization_matches = False
    if (
        not structure.fallback.active
        and serialization is not None
        and serialization_matches
        and "points" in observed
        and "ownership" in observed
    ):
        observed.append("serialization")
    return observed, ambiguous


def _semantic_analysis(
    item: Mapping[str, Any],
    structure: VisualStructure,
    settings: Any,
    *,
    asset_available: bool,
    family: ChartFamilyClassification,
) -> ChartSemanticAnalysis:
    analyzer_ids, configuration_sha256 = _analyzer_configuration(settings)
    if not asset_available:
        return ChartSemanticAnalysis(
            capability_matrix_version="chart-semantic-capabilities-v1",
            attempt_status="not_run_asset_unavailable",
            analyzer_ids=[],
            configuration_sha256=configuration_sha256,
            completeness_gate_status="not_run",
            required_features=[],
            observed_features=[],
            missing_features=[],
            ambiguous_evidence_ids=[],
            failure_reason="asset_unavailable",
        )
    if family.family != "bar" or not _bar_analyzer_approved(settings):
        return ChartSemanticAnalysis(
            capability_matrix_version="chart-semantic-capabilities-v1",
            attempt_status="not_run_no_approved_analyzer",
            analyzer_ids=[],
            configuration_sha256=configuration_sha256,
            completeness_gate_status="not_run",
            required_features=[],
            observed_features=[],
            missing_features=[],
            ambiguous_evidence_ids=[],
            failure_reason="unsupported",
        )
    required = list(_BAR_REQUIRED_FEATURES)
    observed, ambiguous = _bar_completeness(
        structure,
        family,
        item=item,
    )
    missing = [value for value in required if value not in observed]
    approved_analyzers = [*analyzer_ids, "bar-family-completeness-v1"]
    if not missing:
        return ChartSemanticAnalysis(
            capability_matrix_version="chart-semantic-capabilities-v1",
            attempt_status="completed",
            analyzer_ids=approved_analyzers,
            configuration_sha256=configuration_sha256,
            completeness_gate_status="passed",
            required_features=required,
            observed_features=observed,
            missing_features=[],
            ambiguous_evidence_ids=[],
            failure_reason=None,
        )
    failure = structure.fallback.reason if structure.fallback.active else "incomplete"
    attempt_status = {
        "timeout": "timed_out",
        "resource_limit": "resource_refused",
        "malformed_input": "failed",
        "validation_failed": "failed",
        "unsupported": "failed",
        "low_quality": "failed",
    }.get(failure, "completed")
    return ChartSemanticAnalysis(
        capability_matrix_version="chart-semantic-capabilities-v1",
        attempt_status=attempt_status,
        analyzer_ids=approved_analyzers,
        configuration_sha256=configuration_sha256,
        completeness_gate_status="failed",
        required_features=required,
        observed_features=observed,
        missing_features=missing,
        ambiguous_evidence_ids=ambiguous,
        failure_reason=failure,
    )


def build_chart_resolution(
    *,
    item: Mapping[str, Any],
    structure: VisualStructure,
    page_index: int,
    source_order: int,
    asset_attempt: ChartAssetAttempt,
    settings: Any,
    family_classification: ChartFamilyClassification | None = None,
    complexity_classification: ChartComplexityClassification | None = None,
) -> ChartResolution:
    asset_available = asset_attempt.asset is not None
    if asset_available:
        if (family_classification is None) != (complexity_classification is None):
            raise ValueError("chart classification handoff is partial")
        family = family_classification or classify_chart_family(
            item,
            structure,
            minimum_confidence=float(
                getattr(settings, "image_picture_classification_threshold", 0.6)
            ),
        )
        complexity = complexity_classification or classify_chart_complexity(
            structure,
            family,
        )
        if family.status == "not_run" or complexity.status == "not_run":
            raise ValueError("retained chart asset classification was not run")
    else:
        family = ChartFamilyClassification(
            status="not_run",
            family="undetermined",
            classifier_version="chart-family-source-evidence-v1",
            reason_codes=["asset_unavailable"],
            evidence_ids=[],
            confidence=_unavailable_confidence("asset_unavailable"),
        )
        complexity = ChartComplexityClassification(
            status="not_run",
            classifier_version="chart-complexity-source-evidence-v1",
            reason_codes=["asset_unavailable"],
            evidence_ids=[],
            confidence=_unavailable_confidence("asset_unavailable"),
        )
    semantic = _semantic_analysis(
        item,
        structure,
        settings,
        asset_available=asset_available,
        family=family,
    )
    if not asset_available:
        status = "asset_unavailable"
        primary = "grounded_predecessor"
        primary_reason = "source_asset_unavailable"
    elif semantic.completeness_gate_status == "passed":
        status = "structured_primary"
        primary = "structured_chart"
        primary_reason = "semantic_completeness_passed"
    elif semantic.attempt_status == "not_run_no_approved_analyzer":
        status = "image_primary_unsupported"
        primary = "source_image"
        primary_reason = "semantic_family_not_supported"
    else:
        status = "image_primary_incomplete"
        primary = "source_image"
        primary_reason = "semantic_analysis_incomplete"
    concerns: list[str] = []
    if family.status == "undetermined":
        concerns.append("chart_family_undetermined")
    if complexity.status == "undetermined":
        concerns.append("chart_complexity_undetermined")
    if status == "image_primary_unsupported":
        concerns.append("chart_semantics_unsupported")
    elif status == "image_primary_incomplete":
        concerns.append("chart_semantics_incomplete")
    elif status == "asset_unavailable":
        concerns.append("chart_source_asset_unavailable")
    transcript = replay_chart_transcript(item, structure)
    geometry_confidence = structure.confidence.geometry
    ownership_confidence = (
        ChartConfidence(
            value=float(geometry_confidence),
            unavailable_reason=None,
        )
        if asset_available and geometry_confidence is not None
        else _unavailable_confidence(
            "asset_unavailable" if not asset_available else "not_calibrated"
        )
    )
    return ChartResolution(
        schema_version="1.0",
        policy_id="ffd-015-chart-source-asset-v1",
        owner_item_id=str(item.get("id") or ""),
        page_index=page_index,
        source_order=source_order,
        source_bbox=structure.region.page_bbox,
        status=status,
        asset_status="retained" if asset_available else "unavailable",
        asset_unavailable_reason=asset_attempt.unavailable_reason,
        asset=asset_attempt.asset,
        family_classification=family,
        complexity_classification=complexity,
        semantic_analysis=semantic,
        primary_representation=primary,
        primary_reason=primary_reason,
        transcript=transcript,
        confidence_dimensions=ChartConfidenceDimensions(
            ownership=ownership_confidence,
            transcription=transcript.confidence,
            family=family.confidence,
            complexity=complexity.confidence,
        ),
        concern_codes=concerns,
    )


def chart_resolution_markdown(
    resolution: ChartResolution,
    *,
    caption: str | None,
) -> str | None:
    """Return the one safe image-primary Markdown reference, if selected."""

    if resolution.primary_representation != "source_image" or resolution.asset is None:
        return None
    alt = (caption or "").replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    alt = alt.replace("\r", " ").replace("\n", " ")
    return f"![{alt}]({resolution.asset.data_uri})"


__all__ = [
    "ChartAssetAttempt",
    "ChartAssetLedger",
    "ChartAssetLimits",
    "ChartOwnerGeometryProof",
    "ChartResolution",
    "ChartSourceAsset",
    "build_chart_resolution",
    "chart_asset_limits",
    "chart_resolution_markdown",
    "classify_chart_complexity",
    "classify_chart_family",
    "prove_chart_owner_geometry",
    "replay_chart_transcript",
    "render_chart_source_asset",
]
