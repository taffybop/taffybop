"""Bounded deterministic chart and diagram semantics.

This service is deliberately placed on the normalized public-item seam.  It
does not create a second parse path: existing OCR/layout ownership remains the
source of visual regions, and every Phase 05 branch stages a closed sidecar
before committing it to one item.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, MutableMapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal

from app.services.visual_contracts import (
    VisualBoundingBox,
    VisualConcern,
    VisualConfidenceDimensions,
    VisualEvidence,
    VisualFallback,
    VisualLabel,
    VisualProvenance,
    VisualRegion,
    VisualSerialization,
    VisualStructure,
    ensure_finite_mapping,
)

_MAX_VISUALS_PER_DOCUMENT = 256
_MAX_LABELS_PER_VISUAL = 512
_TARGET_KINDS = frozenset({"chart", "diagram"})
_CHART_CLASSES = frozenset(
    {
        "bar_chart",
        "line_chart",
        "pie_chart",
        "area_chart",
        "scatter_plot",
        "chart",
        "plot",
        "histogram",
    }
)
_DIAGRAM_CLASSES = frozenset(
    {
        "flow_chart",
        "flowchart",
        "diagram",
        "network_diagram",
        "process_diagram",
    }
)
_CAPTION_DIAGRAM_RE = re.compile(
    r"\b(?:flow\s*chart|diagram|schematic|process\s+map|"
    r"pin\s+numbering|engineering\s+drawing)\b",
    re.IGNORECASE,
)
_CAPTION_CHART_RE = re.compile(
    r"\b(?:chart|graph|plot|distribution|deployment|loss(?:es)?|mortality|"
    r"growth|share|percentage|percent|value\s+added|hours|rate|trend|"
    r"number\s+of)\b",
    re.IGNORECASE,
)
_CAPTION_IMAGE_RE = re.compile(
    r"\b(?:photograph|photo|image|board|logo|icon|screenshot|illustration)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class _SourceCaptionRouting:
    page_index: int
    bbox: VisualBoundingBox
    caption: str
    caption_bbox: VisualBoundingBox
    visual_source_id: str
    caption_source_ids: tuple[str, ...]


def _stable_id(prefix: str, *parts: Any) -> str:
    payload = json.dumps(
        parts,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(payload).hexdigest()[:24]}"


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _bbox(value: Any, *, default_unit: str) -> VisualBoundingBox | None:
    if not isinstance(value, Mapping):
        return None
    x = _finite_number(value.get("x"))
    y = _finite_number(value.get("y"))
    width = _finite_number(value.get("width", value.get("w")))
    height = _finite_number(value.get("height", value.get("h")))
    unit = str(value.get("unit") or default_unit)
    if (
        x is None
        or y is None
        or width is None
        or height is None
        or min(x, y, width, height) < 0
        or unit not in {"pt", "px"}
    ):
        return None
    return VisualBoundingBox(x=x, y=y, width=width, height=height, unit=unit)


def _bounded_text(value: Any, *, maximum: int = 1_024) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        return None
    normalized = " ".join(value.split()).strip()
    if not normalized or len(encoded) > maximum * 4 or len(normalized) > maximum:
        return None
    return normalized


def _source_provenance_box(
    value: Any,
    *,
    page_heights: Mapping[int, float],
) -> tuple[int, VisualBoundingBox] | None:
    if not isinstance(value, Mapping):
        return None
    provenance = value.get("prov")
    if (
        not isinstance(provenance, Sequence)
        or isinstance(provenance, (str, bytes, bytearray))
        or not provenance
        or not isinstance(provenance[0], Mapping)
    ):
        return None
    record = provenance[0]
    page_index = record.get("page_no")
    raw = record.get("bbox")
    if (
        not isinstance(page_index, int)
        or isinstance(page_index, bool)
        or page_index < 1
        or not isinstance(raw, Mapping)
    ):
        return None
    left = _finite_number(raw.get("l"))
    top = _finite_number(raw.get("t"))
    right = _finite_number(raw.get("r"))
    bottom = _finite_number(raw.get("b"))
    page_height = _finite_number(page_heights.get(page_index))
    if None in {left, top, right, bottom, page_height}:
        return None
    assert left is not None
    assert top is not None
    assert right is not None
    assert bottom is not None
    assert page_height is not None
    if str(raw.get("coord_origin") or "BOTTOMLEFT").upper() == "TOPLEFT":
        y = top
        height = bottom - top
    else:
        y = page_height - top
        height = top - bottom
    width = right - left
    if min(left, y) < 0 or width <= 0 or height <= 0:
        return None
    return (
        page_index,
        VisualBoundingBox(
            x=left,
            y=y,
            width=width,
            height=height,
            unit="pt",
        ),
    )


def _caption_geometry_is_external(
    visual: VisualBoundingBox,
    caption: VisualBoundingBox,
) -> bool:
    if visual.unit != caption.unit:
        return False
    overlap_width = max(
        min(visual.x + visual.width, caption.x + caption.width)
        - max(visual.x, caption.x),
        0.0,
    )
    horizontal_agreement = overlap_width / min(visual.width, caption.width)
    overlap_height = max(
        min(visual.y + visual.height, caption.y + caption.height)
        - max(visual.y, caption.y),
        0.0,
    )
    overlap_area = overlap_width * overlap_height
    overlap_ratio = overlap_area / min(
        visual.width * visual.height,
        caption.width * caption.height,
    )
    vertical_gap = max(
        visual.y - (caption.y + caption.height),
        caption.y - (visual.y + visual.height),
        0.0,
    )
    return (
        horizontal_agreement >= 0.20
        and overlap_ratio <= 0.20
        and vertical_gap <= 72.0
    )


def _source_caption_routings(
    raw_graph: Mapping[str, Any] | None,
    pages: Sequence[Any],
) -> list[_SourceCaptionRouting]:
    """Return bounded graph-declared visual captions with source geometry."""

    if not isinstance(raw_graph, Mapping):
        return []
    page_heights: dict[int, float] = {}
    for page_position, page in enumerate(pages, start=1):
        if not isinstance(page, Mapping):
            continue
        page_index = page.get("page_index")
        height = _finite_number(page.get("page_height"))
        if (
            not isinstance(page_index, int)
            or isinstance(page_index, bool)
            or page_index < 1
            or height is None
            or height <= 0
        ):
            page_index = page_position
        if height is not None and height > 0:
            page_heights[page_index] = height

    raw_texts = raw_graph.get("texts")
    raw_pictures = raw_graph.get("pictures")
    if (
        not isinstance(raw_texts, Sequence)
        or isinstance(raw_texts, (str, bytes, bytearray))
        or len(raw_texts) > 16_384
        or not isinstance(raw_pictures, Sequence)
        or isinstance(raw_pictures, (str, bytes, bytearray))
        or len(raw_pictures) > _MAX_VISUALS_PER_DOCUMENT
    ):
        return []
    refs = {
        reference: value
        for value in raw_texts
        if isinstance(value, Mapping)
        and (reference := _bounded_text(value.get("self_ref"), maximum=256))
        is not None
    }
    output: list[_SourceCaptionRouting] = []
    for picture in raw_pictures:
        if not isinstance(picture, Mapping):
            continue
        visual_box = _source_provenance_box(
            picture,
            page_heights=page_heights,
        )
        source_id = _bounded_text(picture.get("self_ref"), maximum=256)
        captions = picture.get("captions")
        if (
            visual_box is None
            or source_id is None
            or not isinstance(captions, Sequence)
            or isinstance(captions, (str, bytes, bytearray))
            or not 1 <= len(captions) <= 16
        ):
            continue
        page_index, region_bbox = visual_box
        caption_parts: list[str] = []
        caption_boxes: list[VisualBoundingBox] = []
        caption_ids: list[str] = []
        for caption_ref in captions:
            if not isinstance(caption_ref, Mapping):
                continue
            reference = _bounded_text(caption_ref.get("$ref"), maximum=256)
            raw_caption = refs.get(reference or "")
            caption_text = _bounded_text(
                raw_caption.get("text") if raw_caption is not None else None,
                maximum=2_048,
            )
            caption_box = _source_provenance_box(
                raw_caption,
                page_heights=page_heights,
            )
            if (
                reference is None
                or caption_text is None
                or caption_box is None
                or caption_box[0] != page_index
                or not _caption_geometry_is_external(region_bbox, caption_box[1])
            ):
                continue
            caption_parts.append(caption_text)
            caption_boxes.append(caption_box[1])
            caption_ids.append(reference)
        if not caption_parts:
            continue
        left = min(box.x for box in caption_boxes)
        top = min(box.y for box in caption_boxes)
        right = max(box.x + box.width for box in caption_boxes)
        bottom = max(box.y + box.height for box in caption_boxes)
        output.append(
            _SourceCaptionRouting(
                page_index=page_index,
                bbox=region_bbox,
                caption="\n".join(dict.fromkeys(caption_parts)),
                caption_bbox=VisualBoundingBox(
                    x=left,
                    y=top,
                    width=right - left,
                    height=bottom - top,
                    unit=region_bbox.unit,
                ),
                visual_source_id=source_id,
                caption_source_ids=tuple(caption_ids),
            )
        )
    return output


def _same_visual_region(
    item: Mapping[str, Any],
    routing: _SourceCaptionRouting,
    *,
    page_index: int,
    page_unit: str,
) -> bool:
    box = _bbox(item.get("bbox"), default_unit=page_unit)
    if box is None or routing.page_index != page_index or box.unit != routing.bbox.unit:
        return False
    return all(
        abs(left - right) <= 1.5
        for left, right in (
            (box.x, routing.bbox.x),
            (box.y, routing.bbox.y),
            (box.width, routing.bbox.width),
            (box.height, routing.bbox.height),
        )
    )


def _accepted_visual_ocr_profile(
    item: Mapping[str, Any],
) -> tuple[int, int, int, float | None]:
    diagnostics = item.get("items")
    if not isinstance(diagnostics, Sequence) or isinstance(
        diagnostics,
        (str, bytes, bytearray),
    ):
        return 0, 0, 0, None
    line_count = 0
    word_count = 0
    numeric_count = 0
    weighted_confidence = 0.0
    confidence_weight = 0
    for diagnostic in diagnostics[:_MAX_LABELS_PER_VISUAL]:
        if not isinstance(diagnostic, Mapping) or diagnostic.get("accepted") is not True:
            continue
        text = _bounded_text(
            diagnostic.get("text", diagnostic.get("value")),
            maximum=256,
        )
        confidence = _finite_number(diagnostic.get("confidence"))
        if text is None or confidence is None or not 0 <= confidence <= 1:
            continue
        words = diagnostic.get("word_count")
        if not isinstance(words, int) or isinstance(words, bool) or words < 1:
            words = max(len(text.split()), 1)
        line_count += 1
        word_count += words
        numeric_count += len(re.findall(r"(?<!\w)[+-]?\d[\d,.%$'’]*(?!\w)", text))
        weighted_confidence += confidence * words
        confidence_weight += words
    aggregate = (
        weighted_confidence / confidence_weight
        if confidence_weight
        else None
    )
    return line_count, word_count, numeric_count, aggregate


def _caption_grounded_visual_kind(
    item: Mapping[str, Any],
    routing: _SourceCaptionRouting,
    *,
    confidence_floor: float,
) -> Literal["chart", "diagram"] | None:
    declared = str(item.get("type") or item.get("content_type") or "").casefold()
    if (
        declared != "image"
        or item.get("region_role") != "content_region"
        or any(
            key in item
            for key in ("table_evidence", "table_continuation", "rows", "cells", "fields")
        )
    ):
        return None
    caption = routing.caption
    if (
        _CAPTION_IMAGE_RE.search(caption)
        or re.search(r"^\s*(?:table|exhibit\s+table)\b", caption, re.IGNORECASE)
    ):
        return None
    line_count, word_count, numeric_count, confidence = (
        _accepted_visual_ocr_profile(item)
    )
    if (
        line_count < 4
        or word_count < 6
        or confidence is None
        or confidence < confidence_floor
    ):
        return None
    if _CAPTION_DIAGRAM_RE.search(caption):
        return "diagram"
    if _CAPTION_CHART_RE.search(caption) and numeric_count >= 3:
        return "chart"
    return None


def _declared_visual_kind(
    item: Mapping[str, Any],
    *,
    classification_threshold: float,
) -> tuple[Literal["chart", "diagram"] | None, bool]:
    """Return a conservative source-backed kind and classifier availability."""

    declared = str(item.get("type") or item.get("content_type") or "").casefold()
    if declared in _TARGET_KINDS:
        return declared, isinstance(item.get("classification"), Mapping)  # type: ignore[return-value]
    if (
        declared != "image"
        or item.get("region_role") != "content_region"
        or any(
            key in item
            for key in ("table_evidence", "table_continuation", "rows", "cells", "fields")
        )
    ):
        return None, isinstance(item.get("classification"), Mapping)

    for annotation in item.get("annotations") or ():
        if not isinstance(annotation, Mapping):
            continue
        if str(annotation.get("kind") or "").casefold() != "layout":
            continue
        label = str(annotation.get("label") or "").casefold()
        if label in _TARGET_KINDS:
            return label, isinstance(item.get("classification"), Mapping)  # type: ignore[return-value]

    metadata = item.get("metadata")
    if isinstance(metadata, Mapping):
        label = str(
            metadata.get("layout_label") or metadata.get("visual_kind") or ""
        ).casefold()
        if label in _TARGET_KINDS:
            return label, isinstance(item.get("classification"), Mapping)  # type: ignore[return-value]

    classification = item.get("classification")
    if not isinstance(classification, Mapping):
        return None, False
    name = str(classification.get("class_name") or "").casefold()
    confidence = _finite_number(classification.get("confidence"))
    if confidence is None or confidence < classification_threshold:
        return None, True
    if name in _CHART_CLASSES:
        return "chart", True
    if name in _DIAGRAM_CLASSES:
        return "diagram", True
    return None, True


def _could_require_visual_source_recovery(item: Mapping[str, Any]) -> bool:
    """Return whether native PDF evidence can affect visual admission/output.

    Every visual-admission branch owns either an already-declared chart or
    diagram, or an unowned content-region image.  Native text attachment does
    not change an item's declared type, region role, or table ownership, so
    opening the PDF for any item outside that envelope cannot make it visual.
    Keeping this gate identical to the downstream admission predicates avoids
    document-density-dependent work while preserving fail-closed routing.
    """

    declared = str(item.get("type") or item.get("content_type") or "").casefold()
    if declared in _TARGET_KINDS:
        return True
    return bool(
        declared == "image"
        and item.get("region_role") == "content_region"
        and not any(
            key in item
            for key in (
                "table_evidence",
                "table_continuation",
                "rows",
                "cells",
                "fields",
            )
        )
    )


def _fallback_concern(kind: str) -> str:
    return (
        "chart_values_not_structured"
        if kind == "chart"
        else "diagram_relationships_not_structured"
    )


def _public_item_identity(
    item: Mapping[str, Any],
    *,
    document_identity: str,
    page_index: int,
    item_index: int,
) -> str:
    legacy_id = _bounded_text(item.get("id"), maximum=128)
    if legacy_id is not None:
        return legacy_id
    return _stable_id(
        "visual-item",
        document_identity,
        page_index,
        item_index,
        item.get("type"),
        item.get("bbox"),
    )


def _source_ids(value: Any, *, maximum: int = 64) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    result: set[str] = set()
    for raw in value[:maximum]:
        text = _bounded_text(raw, maximum=256)
        if text is not None:
            result.add(text)
    return sorted(result)


def build_visual_fallback(
    item: Mapping[str, Any],
    *,
    kind: Literal["chart", "diagram"],
    page_index: int,
    page_unit: str,
    document_identity: str,
    item_index: int,
    input_kind: Literal["pdf", "image", "unknown"] = "unknown",
    classifier_available: bool = True,
    extra_concern: str | None = None,
    fallback_reason: Literal[
        "unresolved",
        "unsupported",
        "malformed_input",
        "validation_failed",
        "resource_limit",
        "timeout",
        "low_quality",
        "incomplete",
    ] = "unresolved",
) -> VisualStructure:
    """Build the evidence-only P05-US01 fallback for one owned visual."""

    def bounded_members(value: Any, *, label: str) -> list[Any]:
        if value is None:
            return []
        if not isinstance(value, Sequence) or isinstance(
            value,
            (str, bytes, bytearray),
        ):
            raise ValueError(f"visual {label} must be a sequence")
        if len(value) > _MAX_LABELS_PER_VISUAL:
            raise ValueError(f"visual {label} exceeds its entry limit")
        return list(value)

    item_lines = bounded_members(item.get("items"), label="OCR lines")
    token_occurrences = bounded_members(
        item.get("ocr_token_occurrences"),
        label="OCR token occurrences",
    )
    source_text_occurrences = bounded_members(
        item.get("visual_source_text_occurrences"),
        label="PDF source-text occurrences",
    )
    # A born-digital PDF text layer is explicit source evidence and is both
    # cleaner and stronger than a second OCR reading of the same printed
    # glyphs.  Keep the OCR diagnostics on the public item, but do not duplicate
    # them inside the visual sidecar when exact source text is available.
    raw_meta = item.get("meta")
    source_text_meta = (
        raw_meta.get("phase05_visual_source_text")
        if isinstance(raw_meta, Mapping)
        else None
    )
    source_text_is_primary = bool(
        isinstance(source_text_meta, Mapping)
        and source_text_meta.get("promoted_primary") is True
    )
    semantic_item_lines = (
        [] if source_text_occurrences and source_text_is_primary else item_lines
    )
    semantic_token_occurrences = (
        []
        if source_text_occurrences and source_text_is_primary
        else token_occurrences
    )
    safe_input = {
        "bbox": item.get("bbox"),
        "caption": item.get("caption"),
        "caption_bbox": item.get("caption_bbox"),
        "items": semantic_item_lines,
        "ocr_token_occurrences": semantic_token_occurrences,
        "visual_source_text_occurrences": source_text_occurrences,
    }
    ensure_finite_mapping(safe_input)
    region_bbox = _bbox(item.get("bbox"), default_unit=page_unit)
    if region_bbox is None:
        raise ValueError("visual region has no finite public bounding box")

    public_item_id = _public_item_identity(
        item,
        document_identity=document_identity,
        page_index=page_index,
        item_index=item_index,
    )
    routing_source_ids: list[str] = []
    raw_meta = item.get("meta")
    routing_meta = (
        raw_meta.get("phase05_source_caption_routing")
        if isinstance(raw_meta, Mapping)
        else None
    )
    if isinstance(routing_meta, Mapping):
        visual_source_id = _bounded_text(
            routing_meta.get("visual_source_id"),
            maximum=256,
        )
        if visual_source_id is not None:
            routing_source_ids.append(visual_source_id)
        routing_source_ids.extend(
            _source_ids(routing_meta.get("caption_source_ids"))
        )
    region_id = _stable_id("visual-region", public_item_id, kind, region_bbox.model_dump())
    region_evidence_id = _stable_id("visual-evidence", region_id, "region")
    evidence: list[VisualEvidence] = [
        VisualEvidence(
            id=region_evidence_id,
            kind="region",
            page_bbox=region_bbox,
            provenance=VisualProvenance(
                public_item_id=public_item_id,
                page_index=page_index,
                input_kind=input_kind,
                source_object_ids=sorted(
                    dict.fromkeys([public_item_id, *routing_source_ids])
                ),
                source_token_ids=[],
                extraction_method="layout",
            ),
        )
    ]
    labels: list[VisualLabel] = []
    label_occurrence = 0

    def add_label(
        text_value: Any,
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
        raw_bbox: Any,
        source_token_id: str | None,
        extraction_method: Literal["layout", "ocr", "explicit_text"],
    ) -> None:
        nonlocal label_occurrence
        if label_occurrence >= _MAX_LABELS_PER_VISUAL:
            return
        text = _bounded_text(text_value)
        if text is None:
            return
        page_bbox = _bbox(raw_bbox, default_unit=page_unit)
        if page_bbox is not None and (
            page_bbox.unit != region_bbox.unit
            or page_bbox.x < region_bbox.x - 1e-6
            or page_bbox.y < region_bbox.y - 1e-6
            or page_bbox.x + page_bbox.width
            > region_bbox.x + region_bbox.width + 1e-6
            or page_bbox.y + page_bbox.height
            > region_bbox.y + region_bbox.height + 1e-6
        ):
            # OCR outside the visual owner (commonly an external caption or
            # source note) remains on its predecessor item/relationship and
            # cannot become chart/diagram-owned semantic evidence.
            return
        token_ids = [source_token_id] if source_token_id else []
        evidence_id = _stable_id(
            "visual-evidence",
            region_id,
            "label",
            label_occurrence,
            text,
            page_bbox.model_dump() if page_bbox else None,
        )
        label_id = _stable_id(
            "visual-label",
            region_id,
            label_occurrence,
            text,
            page_bbox.model_dump() if page_bbox else None,
        )
        evidence.append(
            VisualEvidence(
                id=evidence_id,
                kind="label",
                page_bbox=page_bbox,
                provenance=VisualProvenance(
                    public_item_id=public_item_id,
                    page_index=page_index,
                    input_kind=input_kind,
                    source_object_ids=([] if token_ids else [public_item_id]),
                    source_token_ids=token_ids,
                    extraction_method=extraction_method,
                ),
            )
        )
        labels.append(
            VisualLabel(
                id=label_id,
                text=text,
                role=role,
                page_bbox=page_bbox,
                evidence_ids=[evidence_id],
                occurrence_index=label_occurrence,
            )
        )
        label_occurrence += 1

    caption = item.get("caption")
    if caption:
        add_label(
            caption,
            role="caption",
            raw_bbox=item.get("caption_bbox"),
            source_token_id=None,
            extraction_method="layout",
        )

    for line_index, line in enumerate(semantic_item_lines):
        if label_occurrence >= _MAX_LABELS_PER_VISUAL:
            break
        if not isinstance(line, Mapping) or line.get("accepted") is False:
            continue
        add_label(
            line.get("text", line.get("value")),
            role=("node" if kind == "diagram" else "other"),
            raw_bbox=line.get("bbox"),
            source_token_id=_stable_id("ocr-line", public_item_id, line_index),
            extraction_method="ocr",
        )

    # Spatial occurrences retain repeated short labels that line-level OCR may
    # have coalesced. Exact source bboxes keep every occurrence distinct.
    existing_occurrences = {
        (
            label.text,
            json.dumps(
                label.page_bbox.model_dump(mode="json") if label.page_bbox else None,
                sort_keys=True,
            ),
        )
        for label in labels
    }
    for token_index, token in enumerate(semantic_token_occurrences):
        if label_occurrence >= _MAX_LABELS_PER_VISUAL:
            break
        if not isinstance(token, Mapping):
            continue
        text = _bounded_text(token.get("text", token.get("value")))
        token_bbox = _bbox(token.get("bbox"), default_unit=page_unit)
        identity = (
            text,
            json.dumps(
                token_bbox.model_dump(mode="json") if token_bbox else None,
                sort_keys=True,
            ),
        )
        if text is None or identity in existing_occurrences:
            continue
        add_label(
            text,
            role=("node" if kind == "diagram" else "other"),
            raw_bbox=token.get("bbox"),
            source_token_id=(
                _bounded_text(token.get("occurrence_id"), maximum=128)
                or _bounded_text(token.get("id"), maximum=128)
                or _stable_id("ocr-token", public_item_id, token_index)
            ),
            extraction_method="ocr",
        )
        existing_occurrences.add(identity)

    for source_index, source_token in enumerate(source_text_occurrences):
        if label_occurrence >= _MAX_LABELS_PER_VISUAL:
            break
        if not isinstance(source_token, Mapping):
            continue
        add_label(
            source_token.get("text", source_token.get("value")),
            role=("node" if kind == "diagram" else "other"),
            raw_bbox=source_token.get("bbox"),
            source_token_id=(
                _bounded_text(source_token.get("occurrence_id"), maximum=128)
                or _bounded_text(source_token.get("id"), maximum=128)
                or _stable_id("visual-source-token", public_item_id, source_index)
            ),
            extraction_method="explicit_text",
        )

    concerns: list[VisualConcern] = [
        VisualConcern(
            code=(
                "chart_structure_unresolved"
                if kind == "chart"
                else "diagram_topology_unresolved"
            ),
            stage="schema",
            evidence_ids=[region_evidence_id],
        )
    ]
    if not classifier_available:
        concerns.append(
            VisualConcern(
                code="visual_classifier_unavailable",
                severity="info",
                stage="schema",
                evidence_ids=[region_evidence_id],
            )
        )
    if extra_concern is not None:
        concerns.append(
            VisualConcern(
                code=extra_concern,
                stage="schema",
                evidence_ids=[region_evidence_id],
            )
        )
    markdown = str(item.get("md") or item.get("value") or "")
    caption_text = _bounded_text(caption)
    return VisualStructure(
        schema_version="1.0",
        region=VisualRegion(
            id=region_id,
            kind=kind,
            page_bbox=region_bbox,
            evidence_ids=[region_evidence_id],
        ),
        labels=labels,
        evidence=evidence,
        confidence=VisualConfidenceDimensions(geometry=1.0),
        concerns=concerns,
        fallback=VisualFallback(
            active=True,
            reason=fallback_reason,
            predecessor_concern=_fallback_concern(kind),
        ),
        serialization=VisualSerialization(
            status="fallback",
            markdown=markdown,
            caption_occurrences=(1 if caption_text and caption_text in markdown else 0),
            row_count=0,
        ),
    )


def _stage_schema_item(
    item: Mapping[str, Any],
    *,
    kind: Literal["chart", "diagram"],
    classifier_available: bool,
    page_index: int,
    page_unit: str,
    document_identity: str,
    item_index: int,
    input_kind: Literal["pdf", "image", "unknown"],
) -> dict[str, Any]:
    staged = deepcopy(dict(item))
    staged["type"] = kind
    staged["content_type"] = kind
    predecessor_concern = _fallback_concern(kind)
    concerns = staged.get("parse_concerns")
    if not isinstance(concerns, list):
        concerns = []
    staged["parse_concerns"] = [
        *dict.fromkeys(
            [
                *(value for value in concerns if isinstance(value, str)),
                predecessor_concern,
            ]
        )
    ]
    structure = build_visual_fallback(
        staged,
        kind=kind,
        page_index=page_index,
        page_unit=page_unit,
        document_identity=document_identity,
        item_index=item_index,
        input_kind=input_kind,
        classifier_available=classifier_available,
    )
    staged["visual_structure"] = structure.model_dump(mode="json", exclude_none=True)
    # Validate the complete item before assignment so a bad region never
    # reaches document-wide ParseResult validation and poisons its neighbors.
    from app.models import ContentItem

    ContentItem.model_validate(deepcopy(staged))
    return staged


def _without_request_diagram_topology(
    item: Mapping[str, Any],
) -> dict[str, Any]:
    """Remove request-carried graph claims before any local producer runs."""

    staged = deepcopy(dict(item))
    staged.pop("diagram_topology_evidence", None)
    raw_meta = staged.get("meta")
    if isinstance(raw_meta, Mapping):
        meta = deepcopy(dict(raw_meta))
        meta.pop("phase05_diagram_topology_evidence", None)
        staged["meta"] = meta
    return staged


def apply_visual_semantics(
    payload: MutableMapping[str, Any],
    settings: Any,
    *,
    source_document_bytes: bytes | None = None,
    input_kind: Any | None = None,
    raw_graph: Mapping[str, Any] | None = None,
) -> MutableMapping[str, Any]:
    """Apply enabled Phase 05 branches atomically per owned visual region."""

    if not bool(getattr(settings, "visual_structure_schema_enabled", False)):
        return payload

    document = payload.get("document")
    document_identity = (
        str(document.get("sha256") or "")
        if isinstance(document, Mapping)
        else ""
    ) or _stable_id("visual-document", payload.get("schema_version"))
    raw_input_kind = getattr(input_kind, "value", input_kind)
    normalized_input_kind: Literal["pdf", "image", "unknown"] = (
        raw_input_kind if raw_input_kind in {"pdf", "image"} else "unknown"
    )
    threshold = float(
        getattr(settings, "image_picture_classification_threshold", 0.6)
    )
    visual_count = 0
    pages = payload.get("pages")
    if not isinstance(pages, list):
        return payload
    source_caption_routings = _source_caption_routings(raw_graph, pages)
    used_source_caption_routings: set[int] = set()
    for page_position, page in enumerate(pages, start=1):
        if not isinstance(page, MutableMapping):
            continue
        page_index = page.get("page_index")
        if not isinstance(page_index, int) or isinstance(page_index, bool):
            page_index = page_position
        page_unit = str(page.get("unit") or "pt")
        if page_unit not in {"pt", "px"}:
            page_unit = "pt"
        items = page.get("items")
        if not isinstance(items, list):
            continue
        for item_index, item in enumerate(tuple(items)):
            if visual_count >= _MAX_VISUALS_PER_DOCUMENT:
                payload.setdefault("warnings", []).append(
                    "Phase 05 visual region limit reached; remaining visuals kept "
                    "in predecessor form."
                )
                return payload
            if not isinstance(item, Mapping):
                continue
            could_require_source_recovery = _could_require_visual_source_recovery(
                item
            )
            source_item: Mapping[str, Any] = item
            source_text: Mapping[str, Any] | None = None
            colored_node_evidence: Mapping[str, Any] | None = None
            raster_diagram_binding: Any | None = None
            if (
                could_require_source_recovery
                and normalized_input_kind == "pdf"
                and source_document_bytes
            ):
                try:
                    from app.services.visual_source_text import (
                        attach_visual_source_text,
                        recover_pdf_visual_source_text,
                    )

                    source_text = recover_pdf_visual_source_text(
                        item,
                        source_pdf_bytes=source_document_bytes,
                        page_index=page_index,
                    )
                    if source_text is not None:
                        source_item = attach_visual_source_text(
                            item,
                            source_text,
                            promote_primary=False,
                        )
                except (MemoryError, OSError, RuntimeError, TypeError, ValueError):
                    source_item = item
                    source_text = None
            if bool(getattr(settings, "diagrams_topology_enabled", False)):
                source_item = _without_request_diagram_topology(source_item)
            kind, classifier_available = _declared_visual_kind(
                source_item,
                classification_threshold=threshold,
            )
            source_caption_routing: _SourceCaptionRouting | None = None
            if kind is None:
                candidates = [
                    (routing_index, routing)
                    for routing_index, routing in enumerate(source_caption_routings)
                    if routing_index not in used_source_caption_routings
                    and _same_visual_region(
                        source_item,
                        routing,
                        page_index=page_index,
                        page_unit=page_unit,
                    )
                ]
                if len(candidates) == 1:
                    routing_index, candidate_routing = candidates[0]
                    kind = _caption_grounded_visual_kind(
                        source_item,
                        candidate_routing,
                        confidence_floor=max(
                            threshold,
                            float(
                                getattr(
                                    settings,
                                    "image_primary_ocr_min_confidence",
                                    0.45,
                                )
                            ),
                        ),
                    )
                    if kind is not None:
                        used_source_caption_routings.add(routing_index)
                        source_caption_routing = candidate_routing
            if kind is None and source_text is not None:
                try:
                    from app.services.visual_source_text import (
                        derive_colored_node_topology_evidence,
                        infer_source_grounded_chart,
                    )

                    if infer_source_grounded_chart(source_item):
                        kind = "chart"
                    else:
                        colored_node_evidence = (
                            derive_colored_node_topology_evidence(
                                source_item,
                                source_pdf_bytes=source_document_bytes,
                                page_index=page_index,
                            )
                        )
                        if colored_node_evidence is not None:
                            kind = "diagram"
                except (MemoryError, OSError, RuntimeError, TypeError, ValueError):
                    colored_node_evidence = None
            if kind is None:
                continue
            visual_count += 1
            try:
                if source_text is not None:
                    from app.services.visual_source_text import (
                        attach_visual_source_text,
                        visual_source_text_primary_eligible,
                    )

                    source_item = attach_visual_source_text(
                        source_item,
                        source_text,
                        promote_primary=visual_source_text_primary_eligible(
                            item,
                            source_text,
                        ),
                    )
                if colored_node_evidence is not None:
                    source_item = deepcopy(dict(source_item))
                    raw_meta = source_item.get("meta")
                    source_meta = (
                        deepcopy(dict(raw_meta))
                        if isinstance(raw_meta, Mapping)
                        else {}
                    )
                    source_meta["phase05_diagram_topology_evidence"] = deepcopy(
                        dict(colored_node_evidence)
                    )
                    source_meta["phase05_source_shape_routing"] = {
                        "method": "repeated_filled_circular_nodes",
                        "kind": "diagram",
                        "node_count": len(colored_node_evidence.get("nodes") or []),
                        "connectors_emitted": 0,
                    }
                    source_item["meta"] = source_meta
                if source_caption_routing is not None:
                    source_item = deepcopy(dict(source_item))
                    source_item["caption"] = source_caption_routing.caption
                    source_item["caption_bbox"] = (
                        source_caption_routing.caption_bbox.model_dump(
                            mode="json",
                            exclude_none=True,
                        )
                    )
                    source_item["caption_source"] = "source_graph_caption"
                    raw_meta = source_item.get("meta")
                    source_meta = (
                        deepcopy(dict(raw_meta))
                        if isinstance(raw_meta, Mapping)
                        else {}
                    )
                    source_meta["phase05_source_caption_routing"] = {
                        "method": "declared_caption_geometry_and_ocr",
                        "kind": kind,
                        "visual_source_id": (
                            source_caption_routing.visual_source_id
                        ),
                        "caption_source_ids": list(
                            source_caption_routing.caption_source_ids
                        ),
                        "caption_sha256": hashlib.sha256(
                            source_caption_routing.caption.encode("utf-8")
                        ).hexdigest(),
                    }
                    source_item["meta"] = source_meta
                if (
                    kind == "diagram"
                    and bool(getattr(settings, "diagrams_topology_enabled", False))
                    and source_document_bytes
                ):
                    from app.services.visual_raster_diagram import (
                        RasterDiagramOwnerBinding,
                        bind_raster_diagram_owner,
                    )

                    detected_images = page.get("detected_images")
                    if isinstance(detected_images, list):
                        binding_item = _without_request_diagram_topology(item)
                        binding_page_items = list(items)
                        binding_page_items[item_index] = binding_item
                        raster_diagram_binding = bind_raster_diagram_owner(
                            binding_item,
                            page_items=binding_page_items,
                            detected_images=detected_images,
                            page_index=page_index,
                            page_unit=page_unit,
                            input_kind=normalized_input_kind,
                        )
                    if raster_diagram_binding is not None:
                        # The binder owns OCR and bbox custody.  Preserve only
                        # independently routed caption metadata from the
                        # already-staged source projection.
                        bound_item = _without_request_diagram_topology(
                            raster_diagram_binding.item
                        )
                        for key in ("caption", "caption_bbox", "caption_source"):
                            if key in source_item:
                                bound_item[key] = deepcopy(source_item[key])
                        routed_meta = source_item.get("meta")
                        if isinstance(routed_meta, Mapping):
                            bound_meta = bound_item.setdefault("meta", {})
                            for key in (
                                "phase05_source_caption_routing",
                                "phase05_source_shape_routing",
                            ):
                                if key in routed_meta:
                                    bound_meta[key] = deepcopy(routed_meta[key])
                        raster_diagram_binding = RasterDiagramOwnerBinding(
                            owner_id=raster_diagram_binding.owner_id,
                            owner_index=raster_diagram_binding.owner_index,
                            item=bound_item,
                        )
                        source_item = bound_item
                if kind == "diagram" and bool(
                    getattr(settings, "diagrams_topology_enabled", False)
                ):
                    source_item = deepcopy(dict(source_item))
                    source_item.pop("diagram_topology_evidence", None)
                    raw_meta = source_item.get("meta")
                    source_meta = (
                        deepcopy(dict(raw_meta))
                        if isinstance(raw_meta, Mapping)
                        else {}
                    )
                    source_meta.pop("phase05_diagram_topology_evidence", None)
                    if colored_node_evidence is not None:
                        source_meta[
                            "phase05_diagram_topology_evidence"
                        ] = deepcopy(dict(colored_node_evidence))
                    else:
                        vector_evidence: Mapping[str, Any] | None = None
                        vector_failed = False
                        if normalized_input_kind == "pdf" and source_document_bytes:
                            from app.services.visual_diagram_topology import (
                                extract_pdf_diagram_topology_evidence,
                            )

                            try:
                                vector_predecessor = build_visual_fallback(
                                    source_item,
                                    kind="diagram",
                                    page_index=page_index,
                                    page_unit=page_unit,
                                    document_identity=document_identity,
                                    item_index=item_index,
                                    input_kind=normalized_input_kind,
                                    classifier_available=classifier_available,
                                )
                                vector_evidence = (
                                    extract_pdf_diagram_topology_evidence(
                                        source_document_bytes,
                                        vector_predecessor,
                                        page_index=page_index,
                                    )
                                )
                            except Exception:  # noqa: BLE001
                                vector_failed = True
                        if vector_evidence is not None:
                            source_meta[
                                "phase05_diagram_topology_evidence"
                            ] = deepcopy(dict(vector_evidence))
                        elif not vector_failed and raster_diagram_binding is not None:
                            from app.services.visual_raster_diagram import (
                                derive_raster_diagram_topology_evidence,
                            )

                            raster_evidence = (
                                derive_raster_diagram_topology_evidence(
                                    raster_diagram_binding,
                                    source_document_bytes,
                                    page_index=page_index,
                                    input_kind=normalized_input_kind,
                                )
                            )
                            if raster_evidence is not None:
                                source_meta[
                                    "phase05_diagram_topology_evidence"
                                ] = deepcopy(raster_evidence)
                    source_item["meta"] = source_meta
                staged = _stage_schema_item(
                    source_item,
                    kind=kind,
                    classifier_available=classifier_available,
                    page_index=page_index,
                    page_unit=page_unit,
                    document_identity=document_identity,
                    item_index=item_index,
                    input_kind=normalized_input_kind,
                )
                if kind == "chart" and source_text is not None:
                    from app.models import ContentItem
                    from app.services.visual_source_text import (
                        structure_source_text_chart,
                    )

                    predecessor = VisualStructure.model_validate(
                        staged["visual_structure"]
                    )
                    if not predecessor.panels and not predecessor.axes:
                        structured = structure_source_text_chart(
                            staged,
                            predecessor,
                            page_index=page_index,
                            input_kind=normalized_input_kind,
                        )
                        candidate = deepcopy(staged)
                        candidate["visual_structure"] = structured.model_dump(
                            mode="json",
                            exclude_none=True,
                        )
                        ContentItem.model_validate(deepcopy(candidate))
                        staged = candidate
            except (MemoryError, TypeError, ValueError):
                # One malformed region retains its useful predecessor and a
                # bounded targeted concern; no partial sidecar is committed.
                staged = deepcopy(dict(item))
                concern = _fallback_concern(kind)
                existing = staged.get("parse_concerns")
                existing_values = (
                    [value for value in existing if isinstance(value, str)]
                    if isinstance(existing, list)
                    else []
                )
                staged["parse_concerns"] = list(
                    dict.fromkeys(
                        [
                            *existing_values,
                            concern,
                            "visual_structure_malformed_input",
                        ]
                    )
                )
                items[item_index] = staged
                continue
            raster_umbrella = bool(
                getattr(settings, "charts_raster_analysis_enabled", False)
            )
            if kind == "chart" and raster_umbrella:
                # Production inputs normally arrive with only owned source
                # bytes and spatial OCR.  Derive the existing private raster
                # seams conservatively when no upstream analyzer supplied any;
                # explicit evidence is never overwritten or mixed.
                raw_meta = staged.get("meta")
                meta = raw_meta if isinstance(raw_meta, Mapping) else {}
                has_raster_evidence = any(
                    staged.get(key) is not None
                    for key in (
                        "raster_gate_evidence",
                        "raster_structure_evidence",
                        "raster_bar_evidence",
                        "raster_line_evidence",
                    )
                ) or any(
                    meta.get(key) is not None
                    for key in (
                        "phase05_raster_gate_evidence",
                        "phase05_raster_structure_evidence",
                        "phase05_raster_bar_evidence",
                        "phase05_raster_line_evidence",
                    )
                )
                if not has_raster_evidence:
                    try:
                        from app.models import ContentItem
                        from app.services.visual_raster_source import (
                            derive_raster_chart_evidence,
                        )

                        derived = derive_raster_chart_evidence(
                            staged,
                            source_document_bytes=source_document_bytes,
                            page_index=page_index,
                            input_kind=normalized_input_kind,
                            settings=settings,
                        )
                        if derived is not None:
                            candidate = deepcopy(staged)
                            candidate_meta = (
                                deepcopy(dict(raw_meta))
                                if isinstance(raw_meta, Mapping)
                                else {}
                            )
                            allowed = {
                                "phase05_raster_gate_evidence",
                                "phase05_raster_structure_evidence",
                            }
                            if bool(
                                getattr(
                                    settings,
                                    "charts_raster_bar_values_enabled",
                                    False,
                                )
                            ):
                                allowed.add("phase05_raster_bar_evidence")
                            if bool(
                                getattr(
                                    settings,
                                    "charts_raster_line_values_enabled",
                                    False,
                                )
                            ):
                                allowed.add("phase05_raster_line_evidence")
                            candidate_meta.update(
                                {
                                    key: value
                                    for key, value in derived.items()
                                    if key in allowed
                                }
                            )
                            candidate["meta"] = candidate_meta
                            ContentItem.model_validate(deepcopy(candidate))
                            staged = candidate
                    except (MemoryError, OSError, RuntimeError, TypeError, ValueError):
                        # The outer gate will turn unavailable/incomplete source
                        # evidence into the established P05-US05 fallback.
                        pass
            raster_context: Any | None = None
            raster_predecessor: VisualStructure | None = None
            raster_rejection: Any | None = None
            if kind == "chart" and raster_umbrella:
                from app.services.visual_raster_gate import (
                    RasterGateRejected,
                    preflight_raster_analysis,
                )

                raster_predecessor = VisualStructure.model_validate(
                    staged["visual_structure"]
                )
                try:
                    raster_context = preflight_raster_analysis(
                        staged,
                        settings,
                        raster_predecessor,
                        input_kind=normalized_input_kind,
                    )
                except RasterGateRejected as rejection:
                    raster_rejection = rejection
            if (
                kind == "chart"
                and bool(getattr(settings, "charts_vector_inventory_enabled", False))
                and not raster_umbrella
            ):
                try:
                    from app.models import ContentItem
                    from app.services.visual_vector import inventory_vector_chart

                    structure = VisualStructure.model_validate(
                        staged["visual_structure"]
                    )
                    structured = inventory_vector_chart(
                        staged,
                        structure,
                        source_pdf_bytes=source_document_bytes,
                        page_index=page_index,
                        input_kind=normalized_input_kind,
                    )
                    staged["visual_structure"] = structured.model_dump(
                        mode="json",
                        exclude_none=True,
                    )
                    ContentItem.model_validate(deepcopy(staged))
                except (MemoryError, TypeError, ValueError):
                    # Inventory is an additive child stage.  Its refusal keeps
                    # the already validated US01 fallback rather than rolling
                    # the visual all the way back or affecting another item.
                    structure = VisualStructure.model_validate(
                        staged["visual_structure"]
                    )
                    structure_payload = structure.model_dump(
                        mode="json",
                        exclude_none=True,
                    )
                    structure_payload["concerns"].append(
                        VisualConcern(
                            code="vector_inventory_failed_closed",
                            stage="vector_inventory",
                            evidence_ids=list(structure.region.evidence_ids),
                        ).model_dump(mode="json", exclude_none=True)
                    )
                    staged["visual_structure"] = VisualStructure.model_validate(
                        structure_payload
                    ).model_dump(mode="json", exclude_none=True)
            if (
                kind == "chart"
                and bool(getattr(settings, "charts_structure_enabled", False))
                and not raster_umbrella
            ):
                try:
                    from app.models import ContentItem
                    from app.services.visual_chart_structure import (
                        structure_vector_chart,
                    )

                    structure = structure_vector_chart(
                        staged,
                        VisualStructure.model_validate(staged["visual_structure"]),
                        page_index=page_index,
                        input_kind=normalized_input_kind,
                    )
                    staged["visual_structure"] = structure.model_dump(
                        mode="json",
                        exclude_none=True,
                    )
                    ContentItem.model_validate(deepcopy(staged))
                except (MemoryError, TypeError, ValueError):
                    structure = VisualStructure.model_validate(
                        staged["visual_structure"]
                    )
                    structure_payload = structure.model_dump(
                        mode="json",
                        exclude_none=True,
                    )
                    structure_payload["concerns"].append(
                        VisualConcern(
                            code="chart_structure_failed_closed",
                            stage="chart_structure",
                            evidence_ids=list(structure.region.evidence_ids),
                        ).model_dump(mode="json", exclude_none=True)
                    )
                    staged["visual_structure"] = VisualStructure.model_validate(
                        structure_payload
                    ).model_dump(mode="json", exclude_none=True)
            if (
                kind == "chart"
                and bool(getattr(settings, "charts_vector_values_enabled", False))
                and not raster_umbrella
            ):
                try:
                    from app.models import ContentItem
                    from app.services.visual_vector_values import measure_vector_bars

                    structure = measure_vector_bars(
                        staged,
                        VisualStructure.model_validate(staged["visual_structure"]),
                        page_index=page_index,
                        input_kind=normalized_input_kind,
                    )
                    staged["visual_structure"] = structure.model_dump(
                        mode="json",
                        exclude_none=True,
                    )
                    ContentItem.model_validate(deepcopy(staged))
                except (MemoryError, TypeError, ValueError):
                    structure = VisualStructure.model_validate(
                        staged["visual_structure"]
                    )
                    structure_payload = structure.model_dump(
                        mode="json",
                        exclude_none=True,
                    )
                    structure_payload["concerns"].append(
                        VisualConcern(
                            code="vector_values_failed_closed",
                            stage="vector_values",
                            evidence_ids=list(structure.region.evidence_ids),
                        ).model_dump(mode="json", exclude_none=True)
                    )
                    staged["visual_structure"] = VisualStructure.model_validate(
                        structure_payload
                    ).model_dump(mode="json", exclude_none=True)
            if (
                kind == "chart"
                and bool(getattr(settings, "charts_raster_structure_enabled", False))
                and raster_umbrella
                and raster_rejection is None
            ):
                try:
                    from app.models import ContentItem
                    from app.services.visual_raster_structure import (
                        structure_raster_chart,
                    )

                    structure = structure_raster_chart(
                        staged,
                        VisualStructure.model_validate(staged["visual_structure"]),
                        page_index=page_index,
                        input_kind=normalized_input_kind,
                    )
                    candidate = deepcopy(staged)
                    candidate["visual_structure"] = structure.model_dump(
                        mode="json",
                        exclude_none=True,
                    )
                    ContentItem.model_validate(deepcopy(candidate))
                    staged = candidate
                except (MemoryError, TypeError, ValueError):
                    structure = VisualStructure.model_validate(
                        staged["visual_structure"]
                    )
                    structure_payload = structure.model_dump(
                        mode="json",
                        exclude_none=True,
                    )
                    if not any(
                        value.get("code") == "raster_structure_failed_closed"
                        for value in structure_payload.get("concerns", [])
                        if isinstance(value, Mapping)
                    ):
                        structure_payload["concerns"].append(
                            VisualConcern(
                                code="raster_structure_failed_closed",
                                stage="raster_structure",
                                evidence_ids=list(structure.region.evidence_ids),
                            ).model_dump(mode="json", exclude_none=True)
                        )
                    staged["visual_structure"] = VisualStructure.model_validate(
                        structure_payload
                    ).model_dump(mode="json", exclude_none=True)
            if (
                kind == "chart"
                and bool(getattr(settings, "charts_raster_bar_values_enabled", False))
                and raster_umbrella
                and raster_rejection is None
            ):
                try:
                    from app.models import ContentItem
                    from app.services.visual_raster_bars import measure_raster_bars

                    structure = measure_raster_bars(
                        staged,
                        VisualStructure.model_validate(staged["visual_structure"]),
                        page_index=page_index,
                        input_kind=normalized_input_kind,
                    )
                    candidate = deepcopy(staged)
                    candidate["visual_structure"] = structure.model_dump(
                        mode="json",
                        exclude_none=True,
                    )
                    ContentItem.model_validate(deepcopy(candidate))
                    staged = candidate
                except (MemoryError, TypeError, ValueError):
                    structure = VisualStructure.model_validate(
                        staged["visual_structure"]
                    )
                    structure_payload = structure.model_dump(
                        mode="json",
                        exclude_none=True,
                    )
                    if not any(
                        value.get("code") == "raster_bars_failed_closed"
                        for value in structure_payload.get("concerns", [])
                        if isinstance(value, Mapping)
                    ):
                        structure_payload["concerns"].append(
                            VisualConcern(
                                code="raster_bars_failed_closed",
                                stage="raster_bars",
                                evidence_ids=list(structure.region.evidence_ids),
                            ).model_dump(mode="json", exclude_none=True)
                        )
                    staged["visual_structure"] = VisualStructure.model_validate(
                        structure_payload
                    ).model_dump(mode="json", exclude_none=True)
            if (
                kind == "chart"
                and bool(getattr(settings, "charts_raster_line_values_enabled", False))
                and raster_umbrella
                and raster_rejection is None
            ):
                try:
                    from app.models import ContentItem
                    from app.services.visual_raster_lines import measure_raster_lines

                    structure = measure_raster_lines(
                        staged,
                        VisualStructure.model_validate(staged["visual_structure"]),
                        page_index=page_index,
                        input_kind=normalized_input_kind,
                    )
                    candidate = deepcopy(staged)
                    candidate["visual_structure"] = structure.model_dump(
                        mode="json",
                        exclude_none=True,
                    )
                    ContentItem.model_validate(deepcopy(candidate))
                    staged = candidate
                except (MemoryError, TypeError, ValueError):
                    structure = VisualStructure.model_validate(
                        staged["visual_structure"]
                    )
                    structure_payload = structure.model_dump(
                        mode="json",
                        exclude_none=True,
                    )
                    if not any(
                        value.get("code") == "raster_lines_failed_closed"
                        for value in structure_payload.get("concerns", [])
                        if isinstance(value, Mapping)
                    ):
                        structure_payload["concerns"].append(
                            VisualConcern(
                                code="raster_lines_failed_closed",
                                stage="raster_lines",
                                evidence_ids=list(structure.region.evidence_ids),
                            ).model_dump(mode="json", exclude_none=True)
                        )
                    staged["visual_structure"] = VisualStructure.model_validate(
                        structure_payload
                    ).model_dump(mode="json", exclude_none=True)
            if (
                kind == "chart"
                and bool(getattr(settings, "charts_structured_output_enabled", False))
                and (not raster_umbrella or raster_rejection is None)
            ):
                try:
                    from app.models import ContentItem
                    from app.services.visual_chart_validation import (
                        validate_and_serialize_chart,
                    )

                    structure = validate_and_serialize_chart(
                        staged,
                        VisualStructure.model_validate(staged["visual_structure"]),
                    )
                    candidate = deepcopy(staged)
                    candidate["visual_structure"] = structure.model_dump(
                        mode="json",
                        exclude_none=True,
                    )
                    if not structure.fallback.active:
                        existing = candidate.get("parse_concerns")
                        if isinstance(existing, list):
                            # The structured chart replaces only its own
                            # predecessor concern.  Other producer concerns
                            # remain visible and retain their original order.
                            candidate["parse_concerns"] = [
                                value
                                for value in existing
                                if value != "chart_values_not_structured"
                            ]
                    ContentItem.model_validate(deepcopy(candidate))
                    staged = candidate
                except (MemoryError, TypeError, ValueError):
                    # A broken validation/serialization stage cannot expose a
                    # partial projection.  Keep the complete validated
                    # predecessor sidecar and add one bounded stage concern.
                    structure = VisualStructure.model_validate(
                        staged["visual_structure"]
                    )
                    structure_payload = structure.model_dump(
                        mode="json",
                        exclude_none=True,
                    )
                    concern_codes = {
                        str(value.get("code"))
                        for value in structure_payload.get("concerns", [])
                        if isinstance(value, Mapping)
                    }
                    if (
                        "chart_validation_failed_closed" not in concern_codes
                        and len(structure_payload.get("concerns", [])) < 256
                    ):
                        structure_payload["concerns"].append(
                            VisualConcern(
                                code="chart_validation_failed_closed",
                                stage="validation",
                                evidence_ids=list(structure.region.evidence_ids),
                            ).model_dump(mode="json", exclude_none=True)
                        )
                    staged["visual_structure"] = VisualStructure.model_validate(
                        structure_payload
                    ).model_dump(mode="json", exclude_none=True)
            if kind == "chart" and raster_umbrella:
                from app.services.visual_raster_gate import (
                    RasterGateRejected,
                    postflight_raster_analysis,
                    raster_gate_fallback,
                )

                assert raster_predecessor is not None
                if raster_rejection is None:
                    try:
                        assert raster_context is not None
                        admitted = postflight_raster_analysis(
                            VisualStructure.model_validate(staged["visual_structure"]),
                            raster_context,
                        )
                        candidate = deepcopy(staged)
                        candidate["visual_structure"] = admitted.model_dump(
                            mode="json",
                            exclude_none=True,
                        )
                        from app.models import ContentItem

                        ContentItem.model_validate(deepcopy(candidate))
                        staged = candidate
                    except RasterGateRejected as rejection:
                        raster_rejection = rejection
                if raster_rejection is not None:
                    fallback = raster_gate_fallback(
                        raster_predecessor,
                        raster_rejection,
                        VisualStructure.model_validate(staged["visual_structure"]),
                    )
                    # The gate's predecessor is the already source-grounded
                    # visual, not the pre-Phase-05 OCR item.  Restoring the
                    # latter would keep the exact source labels in the
                    # sidecar while regressing the public Markdown/value back
                    # to noisy OCR.
                    staged = deepcopy(dict(source_item))
                    staged["type"] = kind
                    staged["content_type"] = kind
                    concerns = staged.get("parse_concerns")
                    concern_values = (
                        [value for value in concerns if isinstance(value, str)]
                        if isinstance(concerns, list)
                        else []
                    )
                    staged["parse_concerns"] = list(
                        dict.fromkeys(
                            [*concern_values, "chart_values_not_structured"]
                        )
                    )
                    staged["visual_structure"] = fallback.model_dump(
                        mode="json",
                        exclude_none=True,
                    )
            if kind == "diagram" and bool(
                getattr(settings, "diagrams_topology_enabled", False)
            ):
                try:
                    from app.models import ContentItem
                    from app.services.visual_diagram_topology import (
                        structure_diagram_topology,
                    )

                    topology_item = deepcopy(staged)
                    raw_meta = topology_item.get("meta")
                    topology_meta = (
                        deepcopy(dict(raw_meta))
                        if isinstance(raw_meta, Mapping)
                        else {}
                    )
                    topology_item["meta"] = topology_meta

                    structure = structure_diagram_topology(
                        topology_item,
                        VisualStructure.model_validate(staged["visual_structure"]),
                        page_index=page_index,
                        input_kind=normalized_input_kind,
                        source_pdf_bytes=source_document_bytes,
                    )
                    candidate = deepcopy(topology_item)
                    candidate["visual_structure"] = structure.model_dump(
                        mode="json",
                        exclude_none=True,
                    )
                    if not structure.fallback.active:
                        existing = candidate.get("parse_concerns")
                        if isinstance(existing, list):
                            candidate["parse_concerns"] = [
                                value
                                for value in existing
                                if value != "diagram_relationships_not_structured"
                            ]
                        admitted_raw = topology_meta.get(
                            "phase05_diagram_topology_evidence"
                        )
                        if (
                            isinstance(admitted_raw, Mapping)
                            and isinstance(admitted_raw.get("source"), Mapping)
                            and admitted_raw["source"].get("kind") == "raster"
                            and structure.serialization is not None
                        ):
                            candidate["value"] = structure.serialization.markdown
                            candidate["md"] = structure.serialization.markdown
                    ContentItem.model_validate(deepcopy(candidate))
                    staged = candidate
                except (MemoryError, TypeError, ValueError):
                    # A failed pass cannot expose a partial graph.  Preserve
                    # the complete US01 item-local sidecar and record one
                    # bounded topology-stage concern.
                    structure = VisualStructure.model_validate(
                        staged["visual_structure"]
                    )
                    structure_payload = structure.model_dump(
                        mode="json",
                        exclude_none=True,
                    )
                    concern_codes = {
                        str(value.get("code"))
                        for value in structure_payload.get("concerns", [])
                        if isinstance(value, Mapping)
                    }
                    if (
                        "diagram_topology_failed_closed" not in concern_codes
                        and len(structure_payload.get("concerns", [])) < 256
                    ):
                        structure_payload["concerns"].append(
                            VisualConcern(
                                code="diagram_topology_failed_closed",
                                stage="diagram_topology",
                                evidence_ids=list(structure.region.evidence_ids),
                            ).model_dump(mode="json", exclude_none=True)
                        )
                    staged["visual_structure"] = VisualStructure.model_validate(
                        structure_payload
                    ).model_dump(mode="json", exclude_none=True)
            items[item_index] = staged
    return payload


__all__ = [
    "apply_visual_semantics",
    "build_visual_fallback",
]
