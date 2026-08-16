"""Provider-neutral, additive-only contracts for optional visual models.

The contracts in this module are intentionally independent of any model
runtime or transport.  They describe one bounded crop and the exact Phase 05
evidence submitted with it.  Model output is still only an observation: it
does not become document content until the later grounding and merge stages.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.visual_contracts import NumericTolerance, VisualBoundingBox


_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_CONCERN_PATTERN = r"^[a-z][a-z0-9_]{2,95}$"
_MAX_CROP_BYTES = 25 * 1024 * 1024
_MAX_RESPONSE_BYTES = 1024 * 1024
_MAX_EVIDENCE = 256
_MAX_OBSERVATIONS = 256
_MAX_REFERENCES = 64

FiniteNumber = Annotated[float, Field(allow_inf_nan=False)]
ConfidenceNumber = Annotated[
    float,
    Field(ge=0.0, le=1.0, allow_inf_nan=False),
]


class VisualModelContract(BaseModel):
    """Closed, non-coercing base for the Phase 06 trust boundary."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        ser_json_bytes="base64",
        val_json_bytes="base64",
    )

    @model_validator(mode="before")
    @classmethod
    def require_exact_object(cls, value: Any) -> Any:
        if type(value) is cls:
            return value
        if type(value) is not dict:
            raise ValueError("visual-model contract values must be exact objects")
        return value


def _require_sorted_unique(values: list[str], label: str) -> None:
    if values != sorted(values) or len(values) != len(set(values)):
        raise ValueError(f"{label} references must be sorted and unique")


def _contains(
    outer: VisualBoundingBox,
    inner: VisualBoundingBox,
    *,
    tolerance: float = 1e-6,
) -> bool:
    return bool(
        outer.unit == inner.unit
        and inner.x >= outer.x - tolerance
        and inner.y >= outer.y - tolerance
        and inner.x + inner.width
        <= outer.x + outer.width + tolerance
        and inner.y + inner.height
        <= outer.y + outer.height + tolerance
    )


class VisualModelCrop(VisualModelContract):
    """The only source pixels an adapter is authorized to inspect."""

    mime_type: Literal["image/png", "image/jpeg", "image/webp"]
    width: int = Field(ge=1, le=8_192)
    height: int = Field(ge=1, le=8_192)
    byte_length: int = Field(ge=1, le=_MAX_CROP_BYTES)
    content_sha256: str = Field(pattern=_SHA256_PATTERN)
    data: bytes = Field(min_length=1, max_length=_MAX_CROP_BYTES, repr=False)

    @model_validator(mode="after")
    def validate_crop(self) -> "VisualModelCrop":
        if self.width * self.height > 16_000_000:
            raise ValueError("visual-model crop exceeds its pixel cap")
        if len(self.data) != self.byte_length:
            raise ValueError("visual-model crop byte length differs")
        if hashlib.sha256(self.data).hexdigest() != self.content_sha256:
            raise ValueError("visual-model crop digest differs")
        return self


class VisualModelEvidenceReference(VisualModelContract):
    """A bounded source-evidence record submitted with the crop."""

    id: str = Field(pattern=_ID_PATTERN)
    page_index: int = Field(ge=1, le=1_000_000)
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
    source_origin: Literal[
        "native",
        "ocr",
        "vector",
        "raster",
        "explicit_text",
        "layout",
    ]
    text: str | None = Field(default=None, min_length=1, max_length=1_024)
    source_object_ids: list[str] = Field(
        default_factory=list,
        max_length=_MAX_REFERENCES,
    )
    source_token_ids: list[str] = Field(
        default_factory=list,
        max_length=_MAX_REFERENCES,
    )

    @model_validator(mode="after")
    def validate_grounding(self) -> "VisualModelEvidenceReference":
        _require_sorted_unique(self.source_object_ids, "source-object")
        _require_sorted_unique(self.source_token_ids, "source-token")
        if (
            self.page_bbox is None
            and not self.source_object_ids
            and not self.source_token_ids
        ):
            raise ValueError("visual-model evidence has no source grounding")
        return self


class VisualModelRegion(VisualModelContract):
    id: str = Field(pattern=_ID_PATTERN)
    public_item_id: str = Field(pattern=_ID_PATTERN)
    page_index: int = Field(ge=1, le=1_000_000)
    kind: Literal["image", "chart", "diagram"]
    page_bbox: VisualBoundingBox
    evidence_ids: list[str] = Field(min_length=1, max_length=_MAX_REFERENCES)

    @model_validator(mode="after")
    def validate_references(self) -> "VisualModelRegion":
        _require_sorted_unique(self.evidence_ids, "region-evidence")
        if self.page_bbox.width <= 0 or self.page_bbox.height <= 0:
            raise ValueError("visual-model region must have positive area")
        return self


class VisualModelRequest(VisualModelContract):
    schema_version: Literal["1.0"]
    request_id: str = Field(pattern=_ID_PATTERN)
    document_sha256: str = Field(pattern=_SHA256_PATTERN)
    region: VisualModelRegion
    crop: VisualModelCrop
    evidence: list[VisualModelEvidenceReference] = Field(
        min_length=1,
        max_length=_MAX_EVIDENCE,
    )
    requested_observation_types: list[
        Literal[
            "generated_description",
            "visual_identification",
            "derived_measurement",
            "inferred_relationship",
        ]
    ] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_request_graph(self) -> "VisualModelRequest":
        evidence_ids = [record.id for record in self.evidence]
        if evidence_ids != sorted(evidence_ids) or len(evidence_ids) != len(
            set(evidence_ids)
        ):
            raise ValueError("submitted evidence identities must be sorted and unique")
        if not set(self.region.evidence_ids) <= set(evidence_ids):
            raise ValueError("region references unknown submitted evidence")
        if any(record.page_index != self.region.page_index for record in self.evidence):
            raise ValueError("submitted evidence crosses the requested page")
        if any(
            record.page_bbox is not None
            and not _contains(self.region.page_bbox, record.page_bbox)
            for record in self.evidence
        ):
            raise ValueError("submitted evidence leaves the requested region")
        if (
            self.requested_observation_types
            != sorted(self.requested_observation_types)
            or len(self.requested_observation_types)
            != len(set(self.requested_observation_types))
        ):
            raise ValueError(
                "requested observation types must be sorted and unique"
            )
        return self


class VisualModelIdentity(VisualModelContract):
    adapter_kind: Literal["local", "hosted", "test_double"]
    adapter_name: str = Field(min_length=1, max_length=128)
    adapter_version: str = Field(min_length=1, max_length=64)
    model_name: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=128)
    prompt_version: str = Field(min_length=1, max_length=64)
    response_schema_version: Literal["1.0"]
    artifact_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    artifact_source: str | None = Field(default=None, min_length=1, max_length=512)
    license_id: str | None = Field(default=None, min_length=1, max_length=256)


class VisualModelConfidenceDimensions(VisualModelContract):
    """Model-reported dimensions; none imply source confidence."""

    model: ConfidenceNumber
    geometry: ConfidenceNumber | None = None
    semantic: ConfidenceNumber | None = None
    value: ConfidenceNumber | None = None
    direction: ConfidenceNumber | None = None


class VisualModelMeasurement(VisualModelContract):
    value: FiniteNumber
    display_value: str = Field(min_length=1, max_length=128)
    units: str = Field(min_length=1, max_length=128)
    method: Literal["explicit_text", "vector_measured", "raster_measured"]
    mark_evidence_ids: list[str] = Field(
        min_length=1,
        max_length=_MAX_REFERENCES,
    )
    axis_evidence_ids: list[str] = Field(
        min_length=1,
        max_length=_MAX_REFERENCES,
    )
    tolerance: NumericTolerance
    validation_state: Literal["pending_independent_validation"]

    @model_validator(mode="after")
    def validate_references(self) -> "VisualModelMeasurement":
        _require_sorted_unique(self.mark_evidence_ids, "measurement-mark")
        _require_sorted_unique(self.axis_evidence_ids, "measurement-axis")
        return self


class VisualModelRelationship(VisualModelContract):
    source_evidence_ids: list[str] = Field(
        min_length=1,
        max_length=_MAX_REFERENCES,
    )
    target_evidence_ids: list[str] = Field(
        min_length=1,
        max_length=_MAX_REFERENCES,
    )
    directed: bool
    directional_evidence_ids: list[str] = Field(
        default_factory=list,
        max_length=_MAX_REFERENCES,
    )

    @model_validator(mode="after")
    def validate_direction(self) -> "VisualModelRelationship":
        _require_sorted_unique(self.source_evidence_ids, "relationship-source")
        _require_sorted_unique(self.target_evidence_ids, "relationship-target")
        _require_sorted_unique(
            self.directional_evidence_ids,
            "relationship-direction",
        )
        if self.directed and not self.directional_evidence_ids:
            raise ValueError("directed model relationship lacks directional evidence")
        return self


class VisualModelObservation(VisualModelContract):
    id: str = Field(pattern=_ID_PATTERN)
    operation: Literal["add"]
    observation_type: Literal[
        "generated_description",
        "visual_identification",
        "derived_measurement",
        "inferred_relationship",
    ]
    origin: Literal[
        "model_generated_description",
        "model_visual_identification",
        "model_derived_measurement",
        "model_inferred_relationship",
    ]
    explicitness: Literal["generated", "derived", "inferred"]
    method: Literal[
        "generated_description",
        "visual_classification",
        "explicit_text",
        "vector_measured",
        "raster_measured",
        "relationship_inference",
    ]
    text: str = Field(min_length=1, max_length=4_096)
    region_id: str = Field(pattern=_ID_PATTERN)
    page_index: int = Field(ge=1, le=1_000_000)
    page_bbox: VisualBoundingBox | None = None
    evidence_ids: list[str] = Field(min_length=1, max_length=_MAX_REFERENCES)
    identity: VisualModelIdentity
    confidence: VisualModelConfidenceDimensions
    measurement: VisualModelMeasurement | None = None
    relationship: VisualModelRelationship | None = None

    @model_validator(mode="after")
    def validate_claim_shape(self) -> "VisualModelObservation":
        _require_sorted_unique(self.evidence_ids, "observation-evidence")
        expected = {
            "generated_description": (
                "model_generated_description",
                "generated",
                {"generated_description"},
            ),
            "visual_identification": (
                "model_visual_identification",
                "derived",
                {"visual_classification", "explicit_text"},
            ),
            "derived_measurement": (
                "model_derived_measurement",
                "derived",
                {"explicit_text", "vector_measured", "raster_measured"},
            ),
            "inferred_relationship": (
                "model_inferred_relationship",
                "inferred",
                {"relationship_inference"},
            ),
        }[self.observation_type]
        if (
            self.origin != expected[0]
            or self.explicitness != expected[1]
            or self.method not in expected[2]
        ):
            raise ValueError("visual-model observation origin or method differs")
        if self.observation_type == "derived_measurement":
            if self.measurement is None or self.relationship is not None:
                raise ValueError("derived measurement claim shape differs")
            if self.method != self.measurement.method:
                raise ValueError("derived measurement method differs")
            required = {
                *self.measurement.mark_evidence_ids,
                *self.measurement.axis_evidence_ids,
            }
            if not required <= set(self.evidence_ids):
                raise ValueError("derived measurement omits cited evidence")
        elif self.observation_type == "inferred_relationship":
            if self.relationship is None or self.measurement is not None:
                raise ValueError("relationship claim shape differs")
            required = {
                *self.relationship.source_evidence_ids,
                *self.relationship.target_evidence_ids,
                *self.relationship.directional_evidence_ids,
            }
            if not required <= set(self.evidence_ids):
                raise ValueError("relationship observation omits cited evidence")
        elif self.measurement is not None or self.relationship is not None:
            raise ValueError("non-structural observation carries structural claim")
        if self.page_bbox is not None and (
            self.page_bbox.width <= 0 or self.page_bbox.height <= 0
        ):
            raise ValueError("observation bbox must have positive area")
        return self


class VisualModelConcern(VisualModelContract):
    code: str = Field(pattern=_CONCERN_PATTERN)
    stage: Literal["contract", "adapter", "routing", "grounding", "merge"]
    severity: Literal["info", "warning", "error"] = "warning"
    observation_id: str | None = Field(default=None, pattern=_ID_PATTERN)


class VisualModelResponse(VisualModelContract):
    schema_version: Literal["1.0"]
    request_id: str = Field(pattern=_ID_PATTERN)
    identity: VisualModelIdentity
    observations: list[VisualModelObservation] = Field(
        default_factory=list,
        max_length=_MAX_OBSERVATIONS,
    )
    concerns: list[VisualModelConcern] = Field(default_factory=list, max_length=256)

    @model_validator(mode="after")
    def validate_response(self) -> "VisualModelResponse":
        observation_ids = [observation.id for observation in self.observations]
        if observation_ids != sorted(observation_ids) or len(observation_ids) != len(
            set(observation_ids)
        ):
            raise ValueError("response observations must have sorted unique IDs")
        if any(observation.identity != self.identity for observation in self.observations):
            raise ValueError("observation identity differs from response identity")
        if any(
            concern.observation_id is not None
            and concern.observation_id not in set(observation_ids)
            for concern in self.concerns
        ):
            raise ValueError("response concern references an unknown observation")
        return self


class VisualModelContractEnvelope(VisualModelContract):
    status: Literal["accepted", "rejected"]
    response: VisualModelResponse | None = None
    concerns: list[VisualModelConcern] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_state(self) -> "VisualModelContractEnvelope":
        if (self.status == "accepted") != (self.response is not None):
            raise ValueError("contract validation envelope state differs")
        return self


class VisualModelEvidenceBundle(VisualModelContract):
    """Accepted, origin-labelled observations exposed additively at US06."""

    schema_version: Literal["1.0"]
    merge_version: Literal["p06-additive-merge-v1"]
    validation_version: Literal["p06-grounding-p05-v1"]
    public_item_id: str = Field(pattern=_ID_PATTERN)
    region_id: str = Field(pattern=_ID_PATTERN)
    page_index: int = Field(ge=1, le=1_000_000)
    source_evidence_preserved: Literal[True]
    observations: list[VisualModelObservation] = Field(
        min_length=1,
        max_length=_MAX_OBSERVATIONS,
    )

    @model_validator(mode="after")
    def validate_bundle(self) -> "VisualModelEvidenceBundle":
        identifiers = [observation.id for observation in self.observations]
        if identifiers != sorted(identifiers) or len(identifiers) != len(
            set(identifiers)
        ):
            raise ValueError("merged observations must have sorted unique IDs")
        if any(
            observation.region_id != self.region_id
            or observation.page_index != self.page_index
            or not observation.origin.startswith("model_")
            or observation.operation != "add"
            for observation in self.observations
        ):
            raise ValueError("merged observation ownership or origin differs")
        return self


class _ReferenceFailure(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _validate_response_references(
    request: VisualModelRequest,
    response: VisualModelResponse,
) -> None:
    if response.request_id != request.request_id:
        raise _ReferenceFailure("visual_model_request_identity_mismatch")
    allowed_types = set(request.requested_observation_types)
    evidence = {record.id: record for record in request.evidence}
    for observation in response.observations:
        if observation.observation_type not in allowed_types:
            raise _ReferenceFailure("visual_model_observation_type_unrequested")
        if observation.region_id != request.region.id:
            raise _ReferenceFailure("visual_model_unknown_region_reference")
        if observation.page_index != request.region.page_index:
            raise _ReferenceFailure("visual_model_cross_page_reference")
        if not set(observation.evidence_ids) <= set(evidence):
            raise _ReferenceFailure("visual_model_unknown_evidence_reference")
        if observation.page_bbox is not None and not _contains(
            request.region.page_bbox,
            observation.page_bbox,
        ):
            raise _ReferenceFailure("visual_model_observation_outside_region")
        if any(
            evidence[evidence_id].page_index != observation.page_index
            for evidence_id in observation.evidence_ids
        ):
            raise _ReferenceFailure("visual_model_cross_page_reference")


def validate_visual_model_response(
    request: VisualModelRequest,
    raw_response: Any,
) -> VisualModelContractEnvelope:
    """Validate one adapter payload without ever returning malformed content."""

    try:
        raw_bytes = json.dumps(
            raw_response,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            default=lambda value: value.model_dump(mode="json"),
        ).encode("utf-8")
        if len(raw_bytes) > _MAX_RESPONSE_BYTES:
            raise _ReferenceFailure("visual_model_response_limit")
        response = VisualModelResponse.model_validate(raw_response, strict=True)
        _validate_response_references(request, response)
    except _ReferenceFailure as exc:
        code = exc.code
    except (MemoryError, TypeError, ValueError, OverflowError):
        code = "visual_model_response_malformed"
    else:
        return VisualModelContractEnvelope(
            status="accepted",
            response=response,
            concerns=[
                VisualModelConcern(
                    code="visual_model_contract_validated",
                    stage="contract",
                    severity="info",
                )
            ],
        )
    return VisualModelContractEnvelope(
        status="rejected",
        concerns=[VisualModelConcern(code=code, stage="contract", severity="error")],
    )


def canonical_visual_model_json(value: VisualModelContract) -> str:
    """Return stable JSON for hashing, tests, transport framing, and audit."""

    payload = value.model_dump(mode="json", exclude_none=True)
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def finite_visual_model_payload(value: Any, *, budget: int = 16_384) -> None:
    """Reject recursive, oversized, or non-finite untrusted adapter values."""

    remaining = [budget]

    def visit(member: Any, depth: int) -> None:
        if depth > 12 or remaining[0] <= 0:
            raise ValueError("visual-model payload exceeds its structural limit")
        remaining[0] -= 1
        if member is None or isinstance(member, (str, bytes, bool)):
            return
        if isinstance(member, (int, float)):
            if isinstance(member, float) and not math.isfinite(member):
                raise ValueError("visual-model payload contains a non-finite value")
            return
        if type(member) is dict:
            if len(member) > 2_048:
                raise ValueError("visual-model mapping exceeds its entry limit")
            for key, nested in member.items():
                if type(key) is not str or len(key) > 256:
                    raise ValueError("visual-model mapping key is invalid")
                visit(nested, depth + 1)
            return
        if type(member) is list:
            if len(member) > 2_048:
                raise ValueError("visual-model sequence exceeds its entry limit")
            for nested in member:
                visit(nested, depth + 1)
            return
        raise ValueError("visual-model payload contains an unsupported value")

    visit(value, 0)


__all__ = [
    "VisualModelConfidenceDimensions",
    "VisualModelConcern",
    "VisualModelContract",
    "VisualModelContractEnvelope",
    "VisualModelCrop",
    "VisualModelEvidenceReference",
    "VisualModelEvidenceBundle",
    "VisualModelIdentity",
    "VisualModelMeasurement",
    "VisualModelObservation",
    "VisualModelRegion",
    "VisualModelRelationship",
    "VisualModelRequest",
    "VisualModelResponse",
    "canonical_visual_model_json",
    "finite_visual_model_payload",
    "validate_visual_model_response",
]
