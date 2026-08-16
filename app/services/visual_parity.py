"""Shared PDF-render/direct-image semantic parity contracts.

The parity boundary compares meaning rather than adapter-local identifiers.
Each source declares an invertible transform into one common coordinate space;
elements, relationships, concerns, and canonical views are then normalized and
compared with bounded, actionable mismatch codes.  Source identity and origin
remain explicit in the input contract even though the expected
``uploaded_page``/``pdf_page_render`` packaging difference is not itself a
semantic mismatch.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from typing import Annotated, Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.services.adapter_contracts import (
    AdapterBoundingBox,
    AdapterCoordinateTransform,
)


VISUAL_PARITY_VERSION = "1.0"
MAX_PARITY_RASTER_BYTES = 25 * 1024 * 1024
MAX_PARITY_PIXELS = 16_000_000
MAX_PARITY_ELEMENTS = 4_096
MAX_PARITY_RELATIONSHIPS = 16_384
MAX_PARITY_CONCERNS = 1_024
MAX_PARITY_MISMATCHES = 64
MAX_PARITY_TEXT_BYTES = 64 * 1024
MAX_PARITY_PRESENTATION_BYTES = 1024 * 1024

_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
_TYPE_PATTERN = r"^[a-z][a-z0-9_]{1,63}$"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_MISMATCH_PATTERN = r"^parity_[a-z0-9_]{2,72}$"

FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]


class VisualParityContract(BaseModel):
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
            raise ValueError("visual parity values must be exact objects")
        return value


def _utf8_size(value: str) -> int:
    return len(value.encode("utf-8"))


def _normalized_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).replace("\r\n", "\n")
    normalized = normalized.replace("\r", "\n")
    return " ".join(normalized.split())


def _normalized_presentation(value: str | None) -> str | None:
    if value is None:
        return None
    lines = unicodedata.normalize("NFKC", value).replace("\r\n", "\n").replace(
        "\r", "\n"
    ).split("\n")
    return "\n".join(line.rstrip() for line in lines).strip()


def _sorted_unique(values: list[str], label: str) -> None:
    if values != sorted(values) or len(values) != len(set(values)):
        raise ValueError(f"{label} must be sorted and unique")


class VisualParitySource(VisualParityContract):
    """One raster source and its declaration into the comparison space."""

    source_id: str = Field(pattern=_ID_PATTERN)
    variant: Literal["direct_image", "pdf_render", "office_render"]
    content_origin: Literal[
        "uploaded_page",
        "pdf_page_render",
        "office_rendered_region",
    ]
    page_index: int = Field(ge=1, le=1_000_000)
    page_label: str = Field(min_length=1, max_length=128)
    source_width: FiniteFloat = Field(gt=0.0, le=1_000_000.0)
    source_height: FiniteFloat = Field(gt=0.0, le=1_000_000.0)
    source_sha256: str = Field(pattern=_SHA256_PATTERN)
    transform_to_common: AdapterCoordinateTransform

    @model_validator(mode="after")
    def validate_origin(self) -> "VisualParitySource":
        expected = {
            "direct_image": "uploaded_page",
            "pdf_render": "pdf_page_render",
            "office_render": "office_rendered_region",
        }[self.variant]
        if self.content_origin != expected:
            raise ValueError("visual parity source origin differs from its variant")
        page = AdapterBoundingBox(
            x=0.0,
            y=0.0,
            width=self.source_width,
            height=self.source_height,
            unit=self.transform_to_common.source_unit,
        )
        normalized = self.transform_to_common.apply_bbox(page)
        if normalized.width <= 0.0 or normalized.height <= 0.0:
            raise ValueError("visual parity source transform has no positive area")
        return self

    def common_page_bbox(self) -> AdapterBoundingBox:
        return self.transform_to_common.apply_bbox(
            AdapterBoundingBox(
                x=0.0,
                y=0.0,
                width=self.source_width,
                height=self.source_height,
                unit=self.transform_to_common.source_unit,
            )
        )


class VisualParityElement(VisualParityContract):
    id: str = Field(pattern=_ID_PATTERN)
    ordinal: int = Field(ge=0, le=MAX_PARITY_ELEMENTS)
    page_index: int = Field(ge=1, le=1_000_000)
    type: str = Field(pattern=_TYPE_PATTERN)
    text: str = Field(default="", max_length=MAX_PARITY_TEXT_BYTES)
    role: str = Field(default="primary", pattern=_TYPE_PATTERN)
    bbox: AdapterBoundingBox | None = None
    content_origin: Literal[
        "uploaded_page",
        "pdf_page_render",
        "native",
        "native_embedded",
        "rendered",
        "ocr",
        "generated",
        "derived",
    ]
    evidence_methods: list[
        Literal[
            "native",
            "ocr",
            "vector",
            "embedded",
            "recovered",
            "model",
            "derived",
            "raster",
            "layout",
            "explicit_text",
        ]
    ] = Field(min_length=1, max_length=11)
    source_locator: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_element(self) -> "VisualParityElement":
        if _utf8_size(self.text) > MAX_PARITY_TEXT_BYTES:
            raise ValueError("visual parity element text exceeds its byte limit")
        _sorted_unique(self.evidence_methods, "element evidence methods")
        return self


class VisualParityRelationship(VisualParityContract):
    id: str = Field(pattern=_ID_PATTERN)
    type: str = Field(pattern=_TYPE_PATTERN)
    source_id: str = Field(pattern=_ID_PATTERN)
    target_id: str = Field(pattern=_ID_PATTERN)


class VisualParityEnvelope(VisualParityContract):
    schema_version: Literal["1.0"] = VISUAL_PARITY_VERSION
    source: VisualParitySource
    elements: list[VisualParityElement] = Field(
        default_factory=list,
        max_length=MAX_PARITY_ELEMENTS,
    )
    relationships: list[VisualParityRelationship] = Field(
        default_factory=list,
        max_length=MAX_PARITY_RELATIONSHIPS,
    )
    concerns: list[str] = Field(default_factory=list, max_length=MAX_PARITY_CONCERNS)
    canonical_markdown: str | None = Field(
        default=None,
        max_length=MAX_PARITY_PRESENTATION_BYTES,
    )
    canonical_text: str | None = Field(
        default=None,
        max_length=MAX_PARITY_PRESENTATION_BYTES,
    )

    @model_validator(mode="after")
    def validate_graph(self) -> "VisualParityEnvelope":
        ids = [element.id for element in self.elements]
        if len(ids) != len(set(ids)):
            raise ValueError("visual parity elements repeat an ID")
        ordinals = [element.ordinal for element in self.elements]
        if len(ordinals) != len(set(ordinals)):
            raise ValueError("visual parity elements repeat an ordinal")
        if any(element.page_index != self.source.page_index for element in self.elements):
            raise ValueError("visual parity element crosses the source page")
        if any(
            element.bbox is not None
            and element.bbox.unit != self.source.transform_to_common.source_unit
            for element in self.elements
        ):
            raise ValueError("visual parity element bbox uses the wrong source unit")

        relationship_ids = [value.id for value in self.relationships]
        if len(relationship_ids) != len(set(relationship_ids)):
            raise ValueError("visual parity relationships repeat an ID")
        element_ids = set(ids)
        if any(
            value.source_id not in element_ids or value.target_id not in element_ids
            for value in self.relationships
        ):
            raise ValueError("visual parity relationship references an unknown element")
        semantic_relationships = [
            (value.type, value.source_id, value.target_id)
            for value in self.relationships
        ]
        if len(semantic_relationships) != len(set(semantic_relationships)):
            raise ValueError("visual parity relationship is duplicated")

        _sorted_unique(self.concerns, "visual parity concerns")
        if any(re.fullmatch(_TYPE_PATTERN, value) is None for value in self.concerns):
            raise ValueError("visual parity concern code is invalid")
        for value in (self.canonical_markdown, self.canonical_text):
            if value is not None and _utf8_size(value) > MAX_PARITY_PRESENTATION_BYTES:
                raise ValueError("visual parity presentation exceeds its byte limit")
        return self


class SharedVisualServiceRequest(VisualParityContract):
    """Input-neutral request consumed by one approved visual service."""

    schema_version: Literal["1.0"] = VISUAL_PARITY_VERSION
    request_id: str = Field(pattern=_ID_PATTERN)
    source: VisualParitySource
    raster_width: int = Field(ge=1, le=8_192)
    raster_height: int = Field(ge=1, le=8_192)
    raster_byte_length: int = Field(ge=1, le=MAX_PARITY_RASTER_BYTES)
    raster_sha256: str = Field(pattern=_SHA256_PATTERN)
    raster_bytes: bytes = Field(
        min_length=1,
        max_length=MAX_PARITY_RASTER_BYTES,
        repr=False,
    )
    evidence_ids: list[str] = Field(default_factory=list, max_length=256)

    @model_validator(mode="after")
    def validate_request(self) -> "SharedVisualServiceRequest":
        if self.raster_width * self.raster_height > MAX_PARITY_PIXELS:
            raise ValueError("shared visual request exceeds its pixel limit")
        if len(self.raster_bytes) != self.raster_byte_length:
            raise ValueError("shared visual request byte length differs")
        if hashlib.sha256(self.raster_bytes).hexdigest() != self.raster_sha256:
            raise ValueError("shared visual request digest differs")
        common_page = self.source.common_page_bbox()
        if (
            common_page.unit != "px"
            or not math.isclose(common_page.x, 0.0, rel_tol=0.0, abs_tol=1e-6)
            or not math.isclose(common_page.y, 0.0, rel_tol=0.0, abs_tol=1e-6)
            or not math.isclose(
                common_page.width,
                float(self.raster_width),
                rel_tol=0.0,
                abs_tol=1e-6,
            )
            or not math.isclose(
                common_page.height,
                float(self.raster_height),
                rel_tol=0.0,
                abs_tol=1e-6,
            )
        ):
            raise ValueError(
                "shared visual raster dimensions differ from the declared transform"
            )
        _sorted_unique(self.evidence_ids, "shared visual evidence IDs")
        return self


@runtime_checkable
class SharedVisualService(Protocol):
    def analyze(self, request: SharedVisualServiceRequest) -> VisualParityEnvelope: ...


class VisualParityError(ValueError):
    def __init__(
        self,
        code: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.details = dict(details or {})


def run_shared_visual_service(
    request: SharedVisualServiceRequest,
    service: SharedVisualService | Callable[[SharedVisualServiceRequest], Any],
) -> VisualParityEnvelope:
    """Invoke one shared service exactly once and validate its source binding."""

    analyzer = getattr(service, "analyze", None)
    if analyzer is None and callable(service):
        analyzer = service
    if not callable(analyzer):
        raise VisualParityError("parity_service_unavailable")
    try:
        raw = analyzer(request)
        envelope = (
            raw
            if isinstance(raw, VisualParityEnvelope)
            else VisualParityEnvelope.model_validate(raw, strict=True)
        )
    except VisualParityError:
        raise
    except Exception as exc:
        raise VisualParityError(
            "parity_service_failed",
            details={"error_type": type(exc).__name__},
        ) from exc
    if envelope.source != request.source:
        raise VisualParityError("parity_service_source_mismatch")
    return envelope


class NormalizedParityElement(VisualParityContract):
    semantic_id: str = Field(pattern=_ID_PATTERN)
    type: str = Field(pattern=_TYPE_PATTERN)
    text: str = Field(max_length=MAX_PARITY_TEXT_BYTES)
    role: str = Field(pattern=_TYPE_PATTERN)
    occurrence: int = Field(ge=0, le=MAX_PARITY_ELEMENTS)
    bbox: AdapterBoundingBox | None = None
    origin: Literal[
        "visual_source",
        "native",
        "native_embedded",
        "rendered",
        "ocr",
        "generated",
        "derived",
    ]
    evidence_methods: list[str] = Field(min_length=1, max_length=11)


class NormalizedParityRelationship(VisualParityContract):
    type: str = Field(pattern=_TYPE_PATTERN)
    source_semantic_id: str = Field(pattern=_ID_PATTERN)
    target_semantic_id: str = Field(pattern=_ID_PATTERN)


class NormalizedVisualSemantics(VisualParityContract):
    source_variant: Literal["direct_image", "pdf_render", "office_render"]
    page_index: int = Field(ge=1, le=1_000_000)
    page_label: str = Field(min_length=1, max_length=128)
    common_page_bbox: AdapterBoundingBox
    elements: list[NormalizedParityElement] = Field(max_length=MAX_PARITY_ELEMENTS)
    relationships: list[NormalizedParityRelationship] = Field(
        max_length=MAX_PARITY_RELATIONSHIPS
    )
    concerns: list[str] = Field(max_length=MAX_PARITY_CONCERNS)
    canonical_markdown: str | None = Field(
        default=None,
        max_length=MAX_PARITY_PRESENTATION_BYTES,
    )
    canonical_text: str | None = Field(
        default=None,
        max_length=MAX_PARITY_PRESENTATION_BYTES,
    )


def _normalized_origin(value: str) -> str:
    if value in {
        "uploaded_page",
        "pdf_page_render",
        "office_rendered_region",
    }:
        return "visual_source"
    return value


def _semantic_digest(parts: Sequence[Any]) -> str:
    encoded = json.dumps(
        list(parts),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def normalize_visual_semantics(
    value: VisualParityEnvelope | Mapping[str, Any],
) -> NormalizedVisualSemantics:
    envelope = (
        value
        if isinstance(value, VisualParityEnvelope)
        else VisualParityEnvelope.model_validate(value, strict=True)
    )
    occurrences: defaultdict[tuple[str, str, str, str, tuple[str, ...]], int] = (
        defaultdict(int)
    )
    id_map: dict[str, str] = {}
    normalized_elements: list[NormalizedParityElement] = []
    for element in sorted(envelope.elements, key=lambda item: (item.ordinal, item.id)):
        text = _normalized_text(element.text)
        origin = _normalized_origin(element.content_origin)
        signature = (
            element.type,
            text,
            element.role,
            origin,
            tuple(element.evidence_methods),
        )
        occurrence = occurrences[signature]
        occurrences[signature] += 1
        semantic_id = f"semantic-{_semantic_digest((*signature, occurrence))}"
        id_map[element.id] = semantic_id
        normalized_elements.append(
            NormalizedParityElement(
                semantic_id=semantic_id,
                type=element.type,
                text=text,
                role=element.role,
                occurrence=occurrence,
                bbox=(
                    envelope.source.transform_to_common.apply_bbox(element.bbox)
                    if element.bbox is not None
                    else None
                ),
                origin=origin,
                evidence_methods=list(element.evidence_methods),
            )
        )

    normalized_relationships = sorted(
        (
            NormalizedParityRelationship(
                type=relationship.type,
                source_semantic_id=id_map[relationship.source_id],
                target_semantic_id=id_map[relationship.target_id],
            )
            for relationship in envelope.relationships
        ),
        key=lambda value: (
            value.type,
            value.source_semantic_id,
            value.target_semantic_id,
        ),
    )
    normalized_elements.sort(key=lambda value: value.semantic_id)
    return NormalizedVisualSemantics(
        source_variant=envelope.source.variant,
        page_index=envelope.source.page_index,
        page_label=envelope.source.page_label,
        common_page_bbox=envelope.source.common_page_bbox(),
        elements=normalized_elements,
        relationships=normalized_relationships,
        concerns=list(envelope.concerns),
        canonical_markdown=_normalized_presentation(envelope.canonical_markdown),
        canonical_text=_normalized_presentation(envelope.canonical_text),
    )


class VisualParityMismatch(VisualParityContract):
    code: str = Field(pattern=_MISMATCH_PATTERN)
    scope: Literal[
        "input",
        "page",
        "transform",
        "element",
        "relationship",
        "concern",
        "presentation",
    ]
    message: str = Field(min_length=1, max_length=256)
    left_count: int | None = Field(default=None, ge=0)
    right_count: int | None = Field(default=None, ge=0)


class VisualParityReport(VisualParityContract):
    schema_version: Literal["1.0"] = VISUAL_PARITY_VERSION
    status: Literal["match", "mismatch"]
    left_variant: str = Field(min_length=1, max_length=32)
    right_variant: str = Field(min_length=1, max_length=32)
    compared_element_count: int = Field(ge=0, le=MAX_PARITY_ELEMENTS)
    compared_relationship_count: int = Field(ge=0, le=MAX_PARITY_RELATIONSHIPS)
    coordinate_tolerance: FiniteFloat = Field(ge=0.0, le=10.0)
    mismatches: list[VisualParityMismatch] = Field(
        default_factory=list,
        max_length=MAX_PARITY_MISMATCHES,
    )

    @model_validator(mode="after")
    def validate_status(self) -> "VisualParityReport":
        if (self.status == "match") == bool(self.mismatches):
            raise ValueError("visual parity status and mismatches differ")
        return self

    @property
    def equivalent(self) -> bool:
        return self.status == "match"

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return tuple(value.code for value in self.mismatches)


_MISMATCH_MESSAGES = {
    "parity_input_invalid": "A visual parity input failed strict validation.",
    "parity_source_pair_invalid": "Parity requires one direct image and one PDF render.",
    "parity_page_identity_mismatch": "Physical page index or printed label differs.",
    "parity_transform_mismatch": "Declared transforms do not reach the same page space.",
    "parity_element_count_mismatch": "The normalized element counts differ.",
    "parity_type_mismatch": "The normalized element types differ.",
    "parity_text_mismatch": "The normalized visible text differs.",
    "parity_provenance_mismatch": "The normalized provenance or evidence methods differ.",
    "parity_element_mismatch": "The normalized semantic elements differ.",
    "parity_geometry_mismatch": "Equivalent elements differ after coordinate normalization.",
    "parity_relationship_mismatch": "The normalized relationship graph differs.",
    "parity_concern_mismatch": "The bounded concern codes differ.",
    "parity_presentation_mismatch": "Canonical Markdown or text differs.",
}


def _mismatch(
    code: str,
    scope: Literal[
        "input",
        "page",
        "transform",
        "element",
        "relationship",
        "concern",
        "presentation",
    ],
    *,
    left_count: int | None = None,
    right_count: int | None = None,
) -> VisualParityMismatch:
    return VisualParityMismatch(
        code=code,
        scope=scope,
        message=_MISMATCH_MESSAGES[code],
        left_count=left_count,
        right_count=right_count,
    )


def _bbox_close(
    left: AdapterBoundingBox | None,
    right: AdapterBoundingBox | None,
    tolerance: float,
) -> bool:
    if left is None or right is None:
        return left is right
    return bool(
        left.unit == right.unit
        and all(
            math.isclose(a, b, rel_tol=0.0, abs_tol=tolerance)
            for a, b in (
                (left.x, right.x),
                (left.y, right.y),
                (left.width, right.width),
                (left.height, right.height),
            )
        )
    )


def _element_core(value: NormalizedParityElement) -> tuple[Any, ...]:
    return (
        value.type,
        value.text,
        value.role,
        value.occurrence,
        value.origin,
        tuple(value.evidence_methods),
    )


def _report(
    *,
    left_variant: str,
    right_variant: str,
    tolerance: float,
    left_elements: int,
    right_elements: int,
    left_relationships: int,
    right_relationships: int,
    mismatches: list[VisualParityMismatch],
) -> VisualParityReport:
    compared_elements = min(left_elements, right_elements)
    compared_relationships = min(left_relationships, right_relationships)
    return VisualParityReport(
        status="mismatch" if mismatches else "match",
        left_variant=left_variant,
        right_variant=right_variant,
        compared_element_count=compared_elements,
        compared_relationship_count=compared_relationships,
        coordinate_tolerance=tolerance,
        mismatches=mismatches[:MAX_PARITY_MISMATCHES],
    )


def compare_visual_parity(
    left: VisualParityEnvelope | Mapping[str, Any],
    right: VisualParityEnvelope | Mapping[str, Any],
    *,
    coordinate_tolerance: float = 0.5,
) -> VisualParityReport:
    """Compare two bounded visual envelopes without comparing local IDs."""

    if (
        isinstance(coordinate_tolerance, bool)
        or not isinstance(coordinate_tolerance, (int, float))
        or not math.isfinite(float(coordinate_tolerance))
        or not 0.0 <= float(coordinate_tolerance) <= 10.0
    ):
        raise ValueError("coordinate_tolerance must be finite and between 0 and 10")
    tolerance = float(coordinate_tolerance)
    try:
        normalized_left = normalize_visual_semantics(left)
        normalized_right = normalize_visual_semantics(right)
    except (TypeError, ValueError, ValidationError):
        return _report(
            left_variant="unknown",
            right_variant="unknown",
            tolerance=tolerance,
            left_elements=0,
            right_elements=0,
            left_relationships=0,
            right_relationships=0,
            mismatches=[_mismatch("parity_input_invalid", "input")],
        )

    mismatches: list[VisualParityMismatch] = []
    variants = {normalized_left.source_variant, normalized_right.source_variant}
    if variants != {"direct_image", "pdf_render"}:
        mismatches.append(_mismatch("parity_source_pair_invalid", "input"))
    if (
        normalized_left.page_index != normalized_right.page_index
        or normalized_left.page_label != normalized_right.page_label
    ):
        mismatches.append(_mismatch("parity_page_identity_mismatch", "page"))
    if not _bbox_close(
        normalized_left.common_page_bbox,
        normalized_right.common_page_bbox,
        tolerance,
    ):
        mismatches.append(_mismatch("parity_transform_mismatch", "transform"))

    left_elements = normalized_left.elements
    right_elements = normalized_right.elements
    if len(left_elements) != len(right_elements):
        mismatches.append(
            _mismatch(
                "parity_element_count_mismatch",
                "element",
                left_count=len(left_elements),
                right_count=len(right_elements),
            )
        )
    if Counter(value.type for value in left_elements) != Counter(
        value.type for value in right_elements
    ):
        mismatches.append(_mismatch("parity_type_mismatch", "element"))
    if Counter(value.text for value in left_elements) != Counter(
        value.text for value in right_elements
    ):
        mismatches.append(_mismatch("parity_text_mismatch", "element"))
    if Counter(
        (value.origin, tuple(value.evidence_methods)) for value in left_elements
    ) != Counter(
        (value.origin, tuple(value.evidence_methods)) for value in right_elements
    ):
        mismatches.append(_mismatch("parity_provenance_mismatch", "element"))

    left_by_core = {_element_core(value): value for value in left_elements}
    right_by_core = {_element_core(value): value for value in right_elements}
    if left_by_core.keys() != right_by_core.keys():
        mismatches.append(_mismatch("parity_element_mismatch", "element"))
    elif any(
        not _bbox_close(left_by_core[key].bbox, right_by_core[key].bbox, tolerance)
        for key in left_by_core
    ):
        mismatches.append(_mismatch("parity_geometry_mismatch", "element"))

    left_relationship_signature = [
        (value.type, value.source_semantic_id, value.target_semantic_id)
        for value in normalized_left.relationships
    ]
    right_relationship_signature = [
        (value.type, value.source_semantic_id, value.target_semantic_id)
        for value in normalized_right.relationships
    ]
    if left_relationship_signature != right_relationship_signature:
        mismatches.append(
            _mismatch(
                "parity_relationship_mismatch",
                "relationship",
                left_count=len(left_relationship_signature),
                right_count=len(right_relationship_signature),
            )
        )
    if normalized_left.concerns != normalized_right.concerns:
        mismatches.append(_mismatch("parity_concern_mismatch", "concern"))
    if (
        normalized_left.canonical_markdown != normalized_right.canonical_markdown
        or normalized_left.canonical_text != normalized_right.canonical_text
    ):
        mismatches.append(
            _mismatch("parity_presentation_mismatch", "presentation")
        )

    return _report(
        left_variant=normalized_left.source_variant,
        right_variant=normalized_right.source_variant,
        tolerance=tolerance,
        left_elements=len(left_elements),
        right_elements=len(right_elements),
        left_relationships=len(left_relationship_signature),
        right_relationships=len(right_relationship_signature),
        mismatches=mismatches,
    )


def _bounded_public_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        result = value
    elif isinstance(value, (int, float, bool)):
        result = str(value)
    else:
        try:
            result = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError):
            result = ""
    if _utf8_size(result) > MAX_PARITY_TEXT_BYTES:
        raise VisualParityError("parity_public_text_limit")
    return result


def _public_bbox(
    value: Any,
    *,
    unit: Literal["pt", "px"],
) -> AdapterBoundingBox | None:
    if not isinstance(value, Mapping):
        return None
    try:
        raw_unit = str(value.get("unit") or unit)
        if raw_unit not in {"pt", "px"}:
            return None
        return AdapterBoundingBox(
            x=float(value["x"]),
            y=float(value["y"]),
            width=float(value.get("width", value.get("w"))),
            height=float(value.get("height", value.get("h"))),
            unit=raw_unit,
        )
    except (KeyError, TypeError, ValueError):
        return None


def _public_origin(
    item: Mapping[str, Any],
    source: VisualParitySource,
) -> Literal[
    "uploaded_page",
    "pdf_page_render",
    "native",
    "native_embedded",
    "rendered",
    "ocr",
    "generated",
    "derived",
]:
    raw = str(item.get("region_origin") or item.get("content_origin") or "")
    aliases = {
        "pdf_embedded": "native_embedded",
        "native": "native",
        "embedded": "native_embedded",
        "pdf_page_render": "pdf_page_render",
        "rendered": "rendered",
        "uploaded_page": "uploaded_page",
        "ocr": "ocr",
        "generated": "generated",
        "derived": "derived",
    }
    return aliases.get(raw, source.content_origin)  # type: ignore[return-value]


def _public_methods(item: Mapping[str, Any]) -> list[str]:
    values: set[str] = set()
    source = str(item.get("source") or "").casefold()
    if source in {
        "native",
        "ocr",
        "vector",
        "embedded",
        "recovered",
        "model",
        "derived",
        "raster",
        "layout",
        "explicit_text",
    }:
        values.add(source)
    visual = item.get("visual_structure")
    if isinstance(visual, Mapping):
        for evidence in visual.get("evidence") or []:
            if not isinstance(evidence, Mapping):
                continue
            provenance = evidence.get("provenance")
            if not isinstance(provenance, Mapping):
                continue
            method = str(provenance.get("extraction_method") or "").casefold()
            if method in {
                "native",
                "ocr",
                "vector",
                "embedded",
                "recovered",
                "model",
                "derived",
                "raster",
                "layout",
                "explicit_text",
            }:
                values.add(method)
    return sorted(values or {"derived"})


def visual_parity_envelope_from_public(
    payload: Mapping[str, Any] | BaseModel,
    source: VisualParitySource,
    *,
    include_types: Sequence[str] | None = None,
) -> VisualParityEnvelope:
    """Build a bounded parity view from public JSON without snapshot masking."""

    if isinstance(payload, BaseModel):
        raw_payload = payload.model_dump(mode="json", exclude_unset=True)
    elif isinstance(payload, Mapping):
        raw_payload = dict(payload)
    else:
        raise VisualParityError("parity_public_payload_invalid")
    raw_pages = raw_payload.get("pages")
    if not isinstance(raw_pages, list) or len(raw_pages) > 1_000:
        raise VisualParityError("parity_public_page_limit")
    selected_types = (
        {str(value).casefold() for value in include_types}
        if include_types is not None
        else None
    )
    elements: list[VisualParityElement] = []
    pending_relationships: list[VisualParityRelationship] = []
    concerns: set[str] = set()
    for page in raw_pages:
        if not isinstance(page, Mapping):
            continue
        try:
            page_index = int(page.get("page_index"))
        except (TypeError, ValueError):
            continue
        if page_index != source.page_index:
            continue
        page_unit = str(page.get("unit") or source.transform_to_common.source_unit)
        if page_unit not in {"pt", "px"}:
            raise VisualParityError("parity_public_unit_invalid")
        raw_items = page.get("items") or []
        if not isinstance(raw_items, list) or len(raw_items) > MAX_PARITY_ELEMENTS:
            raise VisualParityError("parity_public_element_limit")
        for raw_item in raw_items:
            if not isinstance(raw_item, Mapping):
                continue
            item_type = str(raw_item.get("type") or "unknown").casefold()
            if re.fullmatch(_TYPE_PATTERN, item_type) is None:
                item_type = "unknown"
            if selected_types is not None and item_type not in selected_types:
                continue
            ordinal = len(elements)
            item_id = str(raw_item.get("id") or f"p{page_index}-item-{ordinal}")
            if re.fullmatch(_ID_PATTERN, item_id) is None:
                item_id = f"p{page_index}-item-{ordinal}"
            text = _bounded_public_text(
                raw_item.get("value")
                if raw_item.get("value") is not None
                else raw_item.get("ocr_text", raw_item.get("md", ""))
            )
            elements.append(
                VisualParityElement(
                    id=item_id,
                    ordinal=ordinal,
                    page_index=page_index,
                    type=item_type,
                    text=text,
                    role="primary",
                    bbox=_public_bbox(raw_item.get("bbox"), unit=page_unit),
                    content_origin=_public_origin(raw_item, source),
                    evidence_methods=_public_methods(raw_item),
                    source_locator=f"page:{page_index}:item:{ordinal}",
                )
            )
            for raw_concern in raw_item.get("parse_concerns") or []:
                code = str(raw_concern).casefold()
                if re.fullmatch(_TYPE_PATTERN, code):
                    concerns.add(code)
            visual = raw_item.get("visual_structure")
            if isinstance(visual, Mapping):
                for raw_concern in visual.get("concerns") or []:
                    if isinstance(raw_concern, Mapping):
                        code = str(raw_concern.get("code") or "").casefold()
                        if re.fullmatch(_TYPE_PATTERN, code):
                            concerns.add(code)
                for raw_relationship in visual.get("relationships") or []:
                    if not isinstance(raw_relationship, Mapping):
                        continue
                    relationship_id = str(
                        raw_relationship.get("id")
                        or f"relationship-{len(pending_relationships)}"
                    )
                    relationship_type = str(
                        raw_relationship.get("type") or "references"
                    ).casefold()
                    source_id = str(raw_relationship.get("source_id") or "")
                    target_id = str(raw_relationship.get("target_id") or "")
                    if (
                        re.fullmatch(_ID_PATTERN, relationship_id)
                        and re.fullmatch(_TYPE_PATTERN, relationship_type)
                        and source_id
                        and target_id
                    ):
                        pending_relationships.append(
                            VisualParityRelationship(
                                id=relationship_id,
                                type=relationship_type,
                                source_id=source_id,
                                target_id=target_id,
                            )
                        )

            for raw_relationship in raw_item.get("relationships") or []:
                if not isinstance(raw_relationship, Mapping):
                    continue
                relationship_id = str(
                    raw_relationship.get("id")
                    or f"relationship-{len(pending_relationships)}"
                )
                relationship_type = str(
                    raw_relationship.get("type") or "references"
                ).casefold()
                relationship_source_id = str(
                    raw_relationship.get("source_id") or item_id
                )
                relationship_target_id = str(
                    raw_relationship.get("target_id") or ""
                )
                if (
                    re.fullmatch(_ID_PATTERN, relationship_id)
                    and re.fullmatch(_TYPE_PATTERN, relationship_type)
                    and relationship_source_id
                    and relationship_target_id
                ):
                    pending_relationships.append(
                        VisualParityRelationship(
                            id=relationship_id,
                            type=relationship_type,
                            source_id=relationship_source_id,
                            target_id=relationship_target_id,
                        )
                    )

    canonical = raw_payload.get("canonical_presentation")
    markdown: str | None = None
    text: str | None = None
    if isinstance(canonical, Mapping):
        full = canonical.get("full")
        if isinstance(full, Mapping):
            if isinstance(full.get("markdown"), str):
                markdown = full["markdown"]
            if isinstance(full.get("text"), str):
                text = full["text"]
    public_ids = {element.id for element in elements}
    relationships = [
        relationship
        for relationship in pending_relationships
        if relationship.source_id in public_ids
        and relationship.target_id in public_ids
    ]
    relationship_ids: set[str] = set()
    deduplicated_relationships: list[VisualParityRelationship] = []
    for relationship in relationships:
        if relationship.id in relationship_ids:
            continue
        relationship_ids.add(relationship.id)
        deduplicated_relationships.append(relationship)
    return VisualParityEnvelope(
        source=source,
        elements=elements,
        relationships=deduplicated_relationships,
        concerns=sorted(concerns),
        canonical_markdown=markdown,
        canonical_text=text,
    )


__all__ = [
    "MAX_PARITY_ELEMENTS",
    "MAX_PARITY_MISMATCHES",
    "MAX_PARITY_RASTER_BYTES",
    "NormalizedParityElement",
    "NormalizedParityRelationship",
    "NormalizedVisualSemantics",
    "SharedVisualService",
    "SharedVisualServiceRequest",
    "VISUAL_PARITY_VERSION",
    "VisualParityElement",
    "VisualParityEnvelope",
    "VisualParityError",
    "VisualParityMismatch",
    "VisualParityRelationship",
    "VisualParityReport",
    "VisualParitySource",
    "compare_visual_parity",
    "normalize_visual_semantics",
    "run_shared_visual_service",
    "visual_parity_envelope_from_public",
]
