"""Release-first Phase 06 orchestration over the deterministic Phase 05 result.

No runtime or transport is constructed here.  Production deployments must
explicitly inject an approved local loader or hosted transport through the
dependency boundary; the default registry is empty.  Tests use deterministic
adapters and crop providers, never model downloads or network calls.
"""

from __future__ import annotations

import hashlib
import io
import math
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

import pypdfium2 as pdfium
from PIL import Image, UnidentifiedImageError

from app.config import Settings
from app.services.input_documents import InputKind
from app.services.quality_telemetry import quality_telemetry_for_settings
from app.services.visual_contracts import VisualBoundingBox, VisualStructure
from app.services.visual_model_contracts import (
    VisualModelCrop,
    VisualModelEvidenceReference,
    VisualModelRegion,
    VisualModelRequest,
)
from app.services.visual_model_grounding import ground_visual_model_observations
from app.services.visual_model_merge import (
    VisualModelMergeEntry,
    merge_visual_model_evidence,
)
from app.services.visual_model_routing import (
    RoutableVisualAdapter,
    RoutingBudget,
    decide_visual_model_route,
    dispatch_visual_model_route,
)


CropProvider = Callable[
    [bytes, InputKind, int, VisualBoundingBox, Settings],
    VisualModelCrop | None,
]


@dataclass(frozen=True, slots=True)
class VisualModelDependencies:
    """Explicit runtime boundary used by configured adapters or test doubles."""

    adapters: Mapping[str, RoutableVisualAdapter]
    crop_provider: CropProvider
    deterministic_test_double: bool = False


def configured_visual_model_dependencies(
    _settings: Settings,
) -> VisualModelDependencies:
    """Return no callable adapters unless deployment wiring explicitly adds one."""

    return VisualModelDependencies(
        adapters={},
        crop_provider=render_visual_model_crop,
        deterministic_test_double=False,
    )


def _png_crop(image: Image.Image, settings: Settings) -> VisualModelCrop | None:
    try:
        converted = image.convert("RGB")
        if (
            converted.width <= 0
            or converted.height <= 0
            or converted.width > settings.visual_models_max_crop_width
            or converted.height > settings.visual_models_max_crop_height
            or converted.width * converted.height
            > settings.visual_models_max_crop_pixels
        ):
            converted.close()
            return None
        output = io.BytesIO()
        converted.save(output, format="PNG", optimize=False, compress_level=9)
        data = output.getvalue()
        converted.close()
        if not data or len(data) > settings.visual_models_max_request_bytes:
            return None
        return VisualModelCrop(
            mime_type="image/png",
            width=image.width,
            height=image.height,
            byte_length=len(data),
            content_sha256=hashlib.sha256(data).hexdigest(),
            data=data,
        )
    except (MemoryError, OSError, TypeError, ValueError, OverflowError):
        return None


def render_visual_model_crop(
    source: bytes,
    input_kind: InputKind,
    page_index: int,
    box: VisualBoundingBox,
    settings: Settings,
) -> VisualModelCrop | None:
    """Render only the requested region under the common Phase 06 bounds."""

    if not source or page_index < 1:
        return None
    if input_kind is InputKind.IMAGE:
        if box.unit != "px":
            return None
        try:
            with Image.open(io.BytesIO(source)) as opened:
                frame_count = int(getattr(opened, "n_frames", 1) or 1)
                frame = page_index - 1 if frame_count > 1 else 0
                if not 0 <= frame < frame_count:
                    return None
                opened.seek(frame)
                coordinates = (box.x, box.y, box.x + box.width, box.y + box.height)
                rounded = tuple(round(value) for value in coordinates)
                if any(abs(left - right) > 1e-6 for left, right in zip(coordinates, rounded)):
                    return None
                left, top, right, bottom = rounded
                if (
                    min(left, top) < 0
                    or right > opened.width
                    or bottom > opened.height
                    or right <= left
                    or bottom <= top
                ):
                    return None
                cropped = opened.crop((left, top, right, bottom))
                result = _png_crop(cropped, settings)
                cropped.close()
                return result
        except (MemoryError, OSError, UnidentifiedImageError, ValueError):
            return None
    if input_kind is not InputKind.PDF or box.unit != "pt":
        return None

    document: Any | None = None
    page: Any | None = None
    bitmap: Any | None = None
    try:
        document = pdfium.PdfDocument(source)
        if page_index > len(document):
            return None
        page = document[page_index - 1]
        page_width, page_height = (float(value) for value in page.get_size())
        if (
            box.x < 0
            or box.y < 0
            or box.width <= 0
            or box.height <= 0
            or box.x + box.width > page_width + 1e-6
            or box.y + box.height > page_height + 1e-6
        ):
            return None
        scale = min(
            2.0,
            settings.visual_models_max_crop_width / box.width,
            settings.visual_models_max_crop_height / box.height,
            math.sqrt(settings.visual_models_max_crop_pixels / (box.width * box.height)),
        )
        if not math.isfinite(scale) or scale <= 0:
            return None
        bitmap = page.render(
            scale=scale,
            crop=(
                box.x,
                page_height - (box.y + box.height),
                page_width - (box.x + box.width),
                box.y,
            ),
            fill_color=(255, 255, 255, 255),
            optimize_mode="print",
        )
        rendered = bitmap.to_pil()
        result = _png_crop(rendered, settings)
        rendered.close()
        return result
    except Exception:
        return None
    finally:
        if bitmap is not None:
            bitmap.close()
        if page is not None:
            page.close()
        if document is not None:
            document.close()


def _generated_caption_evidence(
    item: Mapping[str, Any],
    structure: VisualStructure,
) -> set[str]:
    concerns = item.get("parse_concerns")
    generated = bool(
        item.get("caption_generated") is True
        or (
            isinstance(concerns, list)
            and "model_generated_visual_description" in concerns
        )
    )
    if not generated:
        return set()
    caption = str(item.get("caption") or "").strip()
    return {
        evidence_id
        for label in structure.labels
        if label.role == "caption" and label.text.strip() == caption
        for evidence_id in label.evidence_ids
    }


def _candidate_structure(
    item: Mapping[str, Any],
) -> VisualStructure | None:
    item_type = str(item.get("type") or item.get("content_type") or "").casefold()
    if item_type not in {"chart", "diagram"}:
        return None
    raw = item.get("visual_structure")
    if not isinstance(raw, Mapping):
        return None
    try:
        structure = VisualStructure.model_validate(dict(raw), strict=True)
    except (MemoryError, TypeError, ValueError, OverflowError):
        return None
    expected_public = (
        "chart_values_not_structured"
        if item_type == "chart"
        else "diagram_relationships_not_structured"
    )
    expected_structured = (
        "chart_structure_unresolved"
        if item_type == "chart"
        else "diagram_topology_unresolved"
    )
    public_concerns = item.get("parse_concerns")
    if (
        structure.region.kind != item_type
        or not structure.fallback.active
        or not isinstance(public_concerns, list)
        or expected_public not in public_concerns
        or expected_structured not in {concern.code for concern in structure.concerns}
    ):
        return None
    return structure


def _is_incomplete_image(item: Mapping[str, Any]) -> bool:
    return bool(
        str(item.get("type") or item.get("content_type") or "").casefold()
        == "image"
        and item.get("caption") in {None, ""}
        and item.get("caption_generated") is not True
        and not str(item.get("ocr_text") or "").strip()
    )


def _visual_candidate(item: Mapping[str, Any]) -> bool:
    return _candidate_structure(item) is not None or _is_incomplete_image(item)


def _request_for_item(
    item: Mapping[str, Any],
    *,
    page_index: int,
    document_sha256: str,
    source: bytes,
    input_kind: InputKind,
    settings: Settings,
    crop_provider: CropProvider,
) -> VisualModelRequest | None:
    item_id = str(item.get("id") or "").strip()
    item_type = str(item.get("type") or item.get("content_type") or "").casefold()
    if not item_id or item_type not in {"image", "chart", "diagram"}:
        return None
    structure = _candidate_structure(item)
    references: list[VisualModelEvidenceReference] = []
    if structure is not None:
        region_id = structure.region.id
        region_box = structure.region.page_bbox
        region_evidence_ids = list(structure.region.evidence_ids)
        excluded = _generated_caption_evidence(item, structure)
        if set(region_evidence_ids) & excluded:
            return None
        label_text: dict[str, str] = {}
        ambiguous_text: set[str] = set()
        for label in structure.labels:
            for evidence_id in label.evidence_ids:
                prior = label_text.get(evidence_id)
                if prior is not None and prior != label.text:
                    ambiguous_text.add(evidence_id)
                else:
                    label_text[evidence_id] = label.text
        for record in structure.evidence:
            if record.id in excluded:
                continue
            provenance = record.provenance
            if provenance.page_index != page_index:
                return None
            references.append(
                VisualModelEvidenceReference(
                    id=record.id,
                    page_index=page_index,
                    kind=record.kind,
                    page_bbox=record.page_bbox,
                    source_origin=provenance.extraction_method,
                    text=(
                        label_text.get(record.id)
                        if record.id not in ambiguous_text
                        else None
                    ),
                    source_object_ids=sorted(provenance.source_object_ids),
                    source_token_ids=sorted(provenance.source_token_ids),
                )
            )
        requested = (
            ["derived_measurement", "visual_identification"]
            if item_type == "chart"
            else ["inferred_relationship", "visual_identification"]
        )
    elif _is_incomplete_image(item):
        raw_box = item.get("bbox")
        if not isinstance(raw_box, Mapping):
            return None
        try:
            region_box = VisualBoundingBox.model_validate(dict(raw_box), strict=True)
        except (TypeError, ValueError):
            return None
        region_id = "visual-model-image-region-" + hashlib.sha256(
            repr((document_sha256, page_index, item_id, dict(raw_box))).encode("utf-8")
        ).hexdigest()[:24]
        region_evidence_ids = [region_id]
        references = [
            VisualModelEvidenceReference(
                id=region_id,
                page_index=page_index,
                kind="region",
                page_bbox=region_box,
                source_origin="layout",
                source_object_ids=[item_id],
            )
        ]
        requested = ["generated_description"]
    else:
        return None

    try:
        crop = crop_provider(source, input_kind, page_index, region_box, settings)
        if crop is None:
            return None
        request_id = "visual-model-request-" + hashlib.sha256(
            repr(
                (
                    document_sha256,
                    page_index,
                    item_id,
                    region_id,
                    crop.content_sha256,
                    tuple(reference.id for reference in references),
                    tuple(requested),
                )
            ).encode("utf-8")
        ).hexdigest()[:24]
        return VisualModelRequest(
            schema_version="1.0",
            request_id=request_id,
            document_sha256=document_sha256,
            region=VisualModelRegion(
                id=region_id,
                public_item_id=item_id,
                page_index=page_index,
                kind=item_type,
                page_bbox=region_box,
                evidence_ids=sorted(region_evidence_ids),
            ),
            crop=crop,
            evidence=sorted(references, key=lambda reference: reference.id),
            requested_observation_types=sorted(requested),
        )
    except (MemoryError, TypeError, ValueError, OverflowError):
        return None


def _hosted_policy_allowed(settings: Settings) -> bool:
    return bool(
        settings.visual_models_hosted_enabled
        and settings.visual_models_hosted_policy_approved
        and settings.visual_models_hosted_data_approved
        and settings.visual_models_hosted_minimization_approved
        and settings.visual_models_hosted_retention_approved
        and settings.visual_models_hosted_vendor
        and settings.visual_models_hosted_model
        and settings.visual_models_hosted_processing_region
        and settings.visual_models_hosted_data_class
        and settings.visual_models_hosted_retention_policy
        and settings.visual_models_hosted_reserved_cost_microunits > 0
    )


def apply_optional_visual_models(
    predecessor: Mapping[str, Any],
    settings: Settings,
    *,
    source_document_bytes: bytes,
    input_kind: InputKind,
    dependencies: VisualModelDependencies | None = None,
) -> dict[str, Any]:
    """Run route/dispatch/ground/merge as one rollback-safe transaction."""

    baseline = deepcopy(dict(predecessor))
    if not all(
        (
            settings.visual_models_contract_enabled,
            settings.visual_models_routing_enabled,
            settings.visual_models_grounding_enabled,
            settings.visual_models_merge_enabled,
        )
    ):
        return baseline
    try:
        quality_telemetry = quality_telemetry_for_settings(settings)
        runtime = dependencies or configured_visual_model_dependencies(settings)
        adapters = dict(runtime.adapters)
        if not runtime.deterministic_test_double and not settings.visual_models_local_enabled:
            adapters.pop("local", None)

        # P08-US09 closes the hosted injection boundary for every runtime,
        # including deterministic test-double wiring.  A structural marker is
        # intentionally insufficient: only the concrete manifest-bound gateway
        # can occupy the hosted route, and the shipping flag is always honored.
        if not settings.visual_models_hosted_enabled:
            adapters.pop("hosted", None)
        else:
            from app.services.hosted_policy import HostedReleaseGateway

            hosted_adapter = adapters.get("hosted")
            if hosted_adapter is not None and type(hosted_adapter) is not HostedReleaseGateway:
                adapters.pop("hosted", None)
        if not adapters:
            quality_telemetry.route_decision(
                route="none",
                adapter="none",
                decision="fallback",
                reason="no_adapter_available",
                outcome="fallback",
                content_type="document",
            )
            quality_telemetry.fallback(
                reason="no_adapter_available",
                content_type="document",
                route="none",
            )
            return baseline
        document = baseline.get("document")
        pages = baseline.get("pages")
        if not isinstance(document, Mapping) or not isinstance(pages, list):
            return baseline
        document_sha256 = str(document.get("sha256") or "")
        if len(document_sha256) != 64:
            return baseline

        remaining_regions = settings.visual_models_routing_max_regions_per_document
        remaining_pixels = settings.visual_models_routing_max_document_pixels
        remaining_hosted_cost = settings.visual_models_hosted_max_cost_microunits
        entries: list[VisualModelMergeEntry] = []
        confidence_assessments: list[tuple[int, Any]] = []
        pending_quality: list[tuple[str, Any, str]] = []
        eligible_regions = 0
        for page in pages:
            if not isinstance(page, Mapping):
                return baseline
            page_index = page.get("page_index")
            items = page.get("items")
            if (
                not isinstance(page_index, int)
                or isinstance(page_index, bool)
                or not isinstance(items, list)
            ):
                return baseline
            for item in items:
                if not isinstance(item, Mapping) or not _visual_candidate(item):
                    continue
                eligible_regions += 1
                request = _request_for_item(
                    item,
                    page_index=page_index,
                    document_sha256=document_sha256,
                    source=source_document_bytes,
                    input_kind=input_kind,
                    settings=settings,
                    crop_provider=runtime.crop_provider,
                )
                if request is None:
                    return baseline
                decision = decide_visual_model_route(
                    item,
                    request,
                    contract_enabled=settings.visual_models_contract_enabled,
                    routing_enabled=settings.visual_models_routing_enabled,
                    adapters=adapters,
                    preference=settings.visual_models_routing_preference,  # type: ignore[arg-type]
                    budget=RoutingBudget(
                        remaining_regions=remaining_regions,
                        remaining_pixels=remaining_pixels,
                        remaining_hosted_cost_microunits=remaining_hosted_cost,
                    ),
                    hosted_policy_allowed=(
                        _hosted_policy_allowed(settings)
                    ),
                    hosted_reserved_cost_microunits=(
                        settings.visual_models_hosted_reserved_cost_microunits
                    ),
                )
                if decision.action == "skip":
                    dispatch_visual_model_route(
                        decision,
                        request,
                        adapters,
                        telemetry=quality_telemetry,
                    )
                    return baseline
                routed = dispatch_visual_model_route(
                    decision,
                    request,
                    adapters,
                    telemetry=quality_telemetry,
                )
                if (
                    routed.contract_envelope is None
                    or routed.contract_envelope.status != "accepted"
                ):
                    return baseline
                grounded = ground_visual_model_observations(
                    item,
                    request,
                    routed.contract_envelope,
                    enabled=settings.visual_models_grounding_enabled,
                    bbox_tolerance=(
                        settings.visual_models_grounding_bbox_tolerance
                    ),
                )
                if settings.visual_confidence_enabled:
                    # P08-US06 is a qualitative deterministic gate over the
                    # existing P05/P06 validators.  It never consumes model
                    # self-confidence and cannot partially promote a mixed
                    # grounding envelope.
                    from app.services.visual_confidence import (
                        assess_visual_confidence,
                    )

                    assessment = assess_visual_confidence(
                        item,
                        grounded,
                        enabled=True,
                    )
                    if assessment is None or assessment.decision != "accept":
                        quality_telemetry.fallback(
                            reason="validation_failed",
                            content_type=request.region.kind,
                            route=decision.action,
                        )
                        return baseline
                    confidence_assessments.append((page_index, assessment))
                if grounded.status != "accepted":
                    quality_telemetry.fallback(
                        reason="validation_failed",
                        content_type=request.region.kind,
                        route=decision.action,
                    )
                    return baseline
                for grounded_observation in grounded.observations[:256]:
                    pending_quality.append(
                        (
                            request.region.kind,
                            grounded_observation.observation.origin,
                            decision.action,
                        )
                    )
                entries.append(
                    VisualModelMergeEntry(
                        public_item_id=request.region.public_item_id,
                        page_index=page_index,
                        region_id=request.region.id,
                        grounding=grounded,
                    )
                )
                remaining_regions -= 1
                region_pixels = request.crop.width * request.crop.height
                remaining_pixels -= region_pixels
                if decision.action == "hosted":
                    remaining_hosted_cost -= decision.reserved_cost_microunits

        if eligible_regions == 0 or len(entries) != eligible_regions:
            if eligible_regions:
                quality_telemetry.fallback(
                    reason="validation_failed",
                    content_type="document",
                    route="none",
                )
            return baseline
        merged = merge_visual_model_evidence(
            baseline,
            entries,
            enabled=settings.visual_models_merge_enabled,
            max_observations=settings.visual_models_merge_max_observations,
            max_added_bytes=settings.visual_models_merge_max_added_bytes,
        )
        if merged.status != "accepted":
            for content_type, _origin, route in sorted(
                set(pending_quality),
                key=lambda value: (str(value[0]), str(value[2]), str(value[1])),
            ):
                quality_telemetry.fallback(
                    reason="validation_failed",
                    content_type=content_type,
                    route=route,
                )
            return baseline
        if settings.visual_confidence_enabled:
            from app.services.visual_confidence import (
                attach_visual_confidence_assessments,
            )

            projected = attach_visual_confidence_assessments(
                merged.payload,
                confidence_assessments,
                max_added_bytes=settings.visual_models_merge_max_added_bytes,
            )
            if projected is None:
                for content_type, _origin, route in sorted(
                    set(pending_quality),
                    key=lambda value: (str(value[0]), str(value[2]), str(value[1])),
                ):
                    quality_telemetry.fallback(
                        reason="validation_failed",
                        content_type=content_type,
                        route=route,
                    )
                return baseline
            final_payload = projected
        else:
            final_payload = merged.payload
        final_counts: dict[tuple[str, Any, str], int] = {}
        for key in pending_quality:
            final_counts[key] = min(256, final_counts.get(key, 0) + 1)
        for (content_type, origin, route), count in sorted(
            final_counts.items(),
            key=lambda value: (
                str(value[0][0]),
                str(value[0][2]),
                str(value[0][1]),
            ),
        ):
            quality_telemetry.quality_decision(
                decision="accept",
                reason="supported",
                origin=origin,
                content_type=content_type,
                route=route,
                outcome="success",
                value=count,
            )
        return final_payload
    except Exception:
        return baseline


__all__ = [
    "VisualModelDependencies",
    "apply_optional_visual_models",
    "configured_visual_model_dependencies",
    "render_visual_model_crop",
]
