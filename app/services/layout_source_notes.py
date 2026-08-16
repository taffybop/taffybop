"""Bounded source-note OCR and PDF-link evidence for Phase 03.

This module only prepares source-visible evidence.  Ownership and public
projection remain the responsibility of :mod:`app.services.layout`.
"""

from __future__ import annotations

import hashlib
import io
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Mapping, MutableMapping, Sequence
from urllib.parse import urlsplit

from app.services.ocr import ImageRegion, PdfRegionRequest


SOURCE_NOTE_ZONE_CONTENT_TYPE = "layout_source_note_zone"
SOURCE_NOTE_ZONE_MARKER = "layout_source_note_zone"
SOURCE_NOTE_OWNER_REF = "layout_source_note_owner_ref"
SOURCE_NOTE_OWNER_BBOX = "layout_source_note_owner_bbox"
SOURCE_NOTE_EVIDENCE_LEDGER = "layout_source_note_evidence"
SOURCE_NOTE_OCR_MARKER = "layout_source_note_rendered_ocr"
SOURCE_NOTE_ANNOTATION_MARKER = "layout_source_note_pdf_annotation"

MAX_SOURCE_NOTE_ZONE_HEIGHT = 36.0
MAX_SOURCE_NOTE_ZONE_REQUESTS_PER_PAGE = 16
MAX_SOURCE_NOTE_OWNER_SCAN_PER_PAGE = 512
MAX_SOURCE_NOTE_TEXT_SCAN_PER_PAGE = 2048
MAX_SOURCE_NOTE_OCR_LINES_PER_PAGE = 64
MAX_SOURCE_NOTE_TEXT_BYTES = 16 * 1024
MAX_SOURCE_NOTE_OWNER_REF_BYTES = 512
MAX_PDF_ANNOTATIONS_PER_PAGE = 256
MAX_PDF_ANNOTATIONS_PER_DOCUMENT = 1024
MAX_PDF_ANNOTATION_TARGET_BYTES = 2048
MAX_VISIBLE_ANNOTATION_TEXT_BYTES = 16 * 1024
MAX_SOURCE_NOTE_LEDGER_CONCERNS = 256
MAX_SOURCE_NOTE_LEDGER_CONCERNS_PER_PAGE = 32

_NOTE_PREFIX_RE = re.compile(r"^(?:data|note|source)\s*:", re.IGNORECASE)
_HTTP_URL_RE = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)
_RAW_COLLECTIONS = ("texts", "pictures", "tables", "groups")
_NOTE_FIELDS = ("source_notes", "source_note", "footnotes", "footnote")
_EPSILON = 0.05
_LEDGER_CONCERN_CODES = frozenset(
    {
        "layout_source_note_annotation_document_limit",
        "layout_source_note_annotation_owner_scan_limit",
        "layout_source_note_annotation_page_limit",
        "layout_source_note_annotation_rejected",
        "layout_source_note_annotation_unavailable",
        "layout_source_note_evidence_unavailable",
        "layout_source_note_owner_field_rejected",
        "layout_source_note_owner_scan_limit",
        "layout_source_note_text_collection_unavailable",
        "layout_source_note_text_scan_limit",
        "layout_source_note_zone_rejected",
        "layout_source_note_zone_request_limit",
    }
)
_LEDGER_REASONS = frozenset(
    {
        "backslash_target",
        "control_or_non_ascii_target",
        "credentialed_target",
        "credentials_not_allowed",
        "empty_target",
        "invalid_geometry",
        "invalid_marker_or_geometry",
        "invalid_port",
        "invalid_scheme",
        "invalid_target_type",
        "malformed_annotation",
        "malformed_target",
        "malformed_source_notes_field",
        "missing_or_malformed_host",
        "missing_host",
        "non_ascii_target",
        "non_text_target",
        "non_printable_target",
        "not_near_structured_owner",
        "oversized_target",
        "target_not_source_visible",
        "unsafe_scheme",
        "unsafe_target",
        "visible_text_unavailable",
        "immutable_or_missing_owner",
    }
)
_SAFE_ERROR_TYPE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,127}$")


@dataclass(frozen=True, slots=True)
class SourceNoteEvidencePlan:
    """Selective render requests and sanitized planning concerns."""

    requests: tuple[PdfRegionRequest, ...]
    concerns: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class SourceNoteEvidenceAugmentation:
    """References synthesized from source-visible OCR and annotations."""

    source_note_refs: tuple[str, ...]
    annotation_refs: tuple[str, ...]
    concerns: tuple[dict[str, Any], ...]


def _bounded_utf8(value: str, limit: int) -> tuple[int, bool]:
    byte_count = 0
    for offset in range(0, len(value), 4096):
        try:
            byte_count += len(
                value[offset : offset + 4096].encode("utf-8")
            )
        except UnicodeEncodeError:
            return limit + 1, True
        if byte_count > limit:
            return byte_count, True
    return byte_count, False


def _raw_reference(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    return str(value.get("$ref") or value.get("cref") or "").strip()


def _reference_items(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return list(value[:1024])
    return [value]


def _reference_map(
    raw_graph: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    output: dict[str, Mapping[str, Any]] = {}
    for collection in _RAW_COLLECTIONS:
        values = raw_graph.get(collection)
        if not isinstance(values, Sequence) or isinstance(
            values,
            (str, bytes, bytearray),
        ):
            continue
        for value in values:
            if not isinstance(value, Mapping):
                continue
            reference = str(value.get("self_ref") or "").strip()
            if reference and reference not in output:
                output[reference] = value
    return output


def _coerce_box(value: Any) -> dict[str, float] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        x = float(value["x"])
        y = float(value["y"])
        width = float(value.get("width", value.get("w")))
        height = float(value.get("height", value.get("h")))
    except (KeyError, TypeError, ValueError):
        return None
    if (
        width <= 0
        or height <= 0
        or not all(math.isfinite(item) for item in (x, y, width, height))
    ):
        return None
    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
    }


def _raw_provenance_page_box(
    record: Mapping[str, Any],
    page_heights: Mapping[int, float],
) -> tuple[int, dict[str, float]] | None:
    try:
        page_index = int(record["page_no"])
        raw_box = record["bbox"]
        left = float(raw_box["l"])
        top = float(raw_box["t"])
        right = float(raw_box["r"])
        bottom = float(raw_box["b"])
    except (KeyError, TypeError, ValueError):
        return None
    if (
        page_index not in page_heights
        or not isinstance(raw_box, Mapping)
        or not all(
            math.isfinite(item) for item in (left, top, right, bottom)
        )
    ):
        return None
    origin = str(raw_box.get("coord_origin", "BOTTOMLEFT")).upper()
    if origin == "TOPLEFT":
        width = right - left
        height = bottom - top
        y = top
    elif origin == "BOTTOMLEFT":
        width = right - left
        height = top - bottom
        y = page_heights[page_index] - top
    else:
        return None
    if width <= 0 or height <= 0:
        return None
    return (
        page_index,
        {
            "x": left,
            "y": y,
            "width": width,
            "height": height,
        },
    )


def _raw_page_boxes(
    raw_item: Mapping[str, Any],
    page_heights: Mapping[int, float],
) -> list[tuple[int, dict[str, float], Mapping[str, Any]]]:
    provenance = raw_item.get("prov")
    if not isinstance(provenance, Sequence) or isinstance(
        provenance,
        (str, bytes, bytearray),
    ):
        return []
    output: list[
        tuple[int, dict[str, float], Mapping[str, Any]]
    ] = []
    for record in provenance[:16]:
        if not isinstance(record, Mapping):
            continue
        page_box = _raw_provenance_page_box(record, page_heights)
        if page_box is None:
            continue
        page_index, box = page_box
        output.append((page_index, box, record))
    return output


def _raw_page_box(
    raw_item: Mapping[str, Any],
    page_heights: Mapping[int, float],
) -> tuple[int, dict[str, float]] | None:
    page_boxes = _raw_page_boxes(raw_item, page_heights)
    if page_boxes:
        page_index, box, _record = page_boxes[0]
        return page_index, box
    return None


def _raw_visible_note_link_boxes(
    raw_item: Mapping[str, Any],
    page_heights: Mapping[int, float],
) -> list[tuple[int, dict[str, float]]]:
    text = _raw_text(raw_item)
    _byte_count, oversized = _bounded_utf8(
        text,
        MAX_VISIBLE_ANNOTATION_TEXT_BYTES,
    )
    if not text or oversized:
        return []
    visible_spans: list[tuple[int, int]] = []
    prefix_match = _NOTE_PREFIX_RE.match(text)
    if prefix_match is not None:
        visible_spans.append((prefix_match.start(), len(text)))
    for match in _HTTP_URL_RE.finditer(text):
        target = match.group(0).rstrip(".,);]")
        if safe_http_annotation_target(target) is not None:
            visible_spans.append(
                (
                    match.start(),
                    match.start() + len(target),
                )
            )
    if not visible_spans:
        return []

    output: list[tuple[int, dict[str, float]]] = []
    for page_index, box, record in _raw_page_boxes(
        raw_item,
        page_heights,
    ):
        charspan = record.get("charspan")
        if (
            isinstance(charspan, Sequence)
            and not isinstance(charspan, (str, bytes, bytearray))
            and len(charspan) == 2
        ):
            try:
                span_start = int(charspan[0])
                span_end = int(charspan[1])
            except (TypeError, ValueError):
                continue
            if not any(
                note_start < span_end and note_end > span_start
                for note_start, note_end in visible_spans
            ):
                continue
        elif len(visible_spans) != 1 or visible_spans[0][0] != 0:
            continue
        output.append((page_index, box))
    return output


def _horizontal_overlap(first: Mapping[str, float], second: Mapping[str, float]) -> float:
    left = max(first["x"], second["x"])
    right = min(
        first["x"] + first["width"],
        second["x"] + second["width"],
    )
    denominator = min(first["width"], second["width"])
    return max(right - left, 0.0) / denominator if denominator > 0 else 0.0


def _is_external_below(
    candidate: Mapping[str, float],
    owner: Mapping[str, float],
    *,
    maximum_gap: float,
) -> bool:
    owner_bottom = owner["y"] + owner["height"]
    candidate_top = candidate["y"]
    return bool(
        candidate_top + _EPSILON >= owner_bottom
        and candidate_top - owner_bottom <= maximum_gap + _EPSILON
        and _horizontal_overlap(candidate, owner) >= 0.20
    )


def _has_caption(raw_owner: Mapping[str, Any]) -> bool:
    for field_name in ("captions", "caption"):
        values = _reference_items(raw_owner.get(field_name))
        if any(_raw_reference(value) for value in values):
            return True
    return False


def _has_declared_note(
    raw_owner: Mapping[str, Any],
    references: Mapping[str, Mapping[str, Any]],
) -> bool:
    for field_name in _NOTE_FIELDS:
        if field_name not in raw_owner:
            continue
        values = _reference_items(raw_owner.get(field_name))
        # A malformed nonempty declaration fails closed instead of triggering
        # an additional OCR inference path.
        if values:
            return True
    for value in _reference_items(raw_owner.get("children")):
        reference = _raw_reference(value)
        target = references.get(reference)
        label = (
            str(target.get("label") or "").casefold()
            if isinstance(target, Mapping)
            else ""
        )
        if label in {"footnote", "source_note"}:
            return True
    return False


def _raw_text(raw_item: Mapping[str, Any]) -> str:
    for key in ("text", "orig", "value"):
        value = raw_item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _raw_page_indices(raw_item: Mapping[str, Any]) -> set[int]:
    provenance = raw_item.get("prov")
    if not isinstance(provenance, Sequence) or isinstance(
        provenance,
        (str, bytes, bytearray),
    ):
        return set()
    output: set[int] = set()
    for record in provenance[:16]:
        if not isinstance(record, Mapping):
            continue
        raw_page = record.get("page_no")
        if isinstance(raw_page, bool):
            continue
        try:
            page_index = int(raw_page)
        except (TypeError, ValueError):
            continue
        if page_index > 0:
            output.add(page_index)
    return output


def _planning_concern(
    code: str,
    *,
    page_index: int,
    candidate_count: int,
    limit: int,
) -> dict[str, Any]:
    return {
        "code": code,
        "page_index": page_index,
        "candidate_count": candidate_count,
        "limit": limit,
    }


def plan_source_note_zone_requests(
    pages: Sequence[Mapping[str, Any]],
    raw_graph: Mapping[str, Any],
) -> SourceNoteEvidencePlan:
    """Plan small below-visual OCR strips without increasing owner crops."""

    page_heights: dict[int, float] = {}
    page_widths: dict[int, float] = {}
    for page in pages:
        try:
            page_index = int(page["page_index"])
            page_width = float(page["page_width"])
            page_height = float(page["page_height"])
        except (KeyError, TypeError, ValueError):
            continue
        if (
            page_index > 0
            and page_width > 0
            and page_height > 0
            and math.isfinite(page_width)
            and math.isfinite(page_height)
        ):
            page_widths[page_index] = page_width
            page_heights[page_index] = page_height

    references = _reference_map(raw_graph)
    visible_notes_by_page: dict[
        int,
        list[dict[str, float]],
    ] = defaultdict(list)
    text_counts: Counter[int] = Counter()
    blocked_text_pages: set[int] = set()
    raw_texts = raw_graph.get("texts")
    if isinstance(raw_texts, Sequence) and not isinstance(
        raw_texts,
        (str, bytes, bytearray),
    ):
        for raw_text in raw_texts:
            if not isinstance(raw_text, Mapping):
                continue
            page_boxes = _raw_page_boxes(raw_text, page_heights)
            for page_index in {
                page_index
                for page_index, _box, _record in page_boxes
            }:
                text_counts[page_index] += 1
                if (
                    text_counts[page_index]
                    > MAX_SOURCE_NOTE_TEXT_SCAN_PER_PAGE
                ):
                    blocked_text_pages.add(page_index)
                    visible_notes_by_page.pop(page_index, None)
            for page_index, box in _raw_visible_note_link_boxes(
                raw_text,
                page_heights,
            ):
                if page_index not in blocked_text_pages:
                    visible_notes_by_page[page_index].append(box)

    concerns: list[dict[str, Any]] = [
        _planning_concern(
            "layout_source_note_text_scan_limit",
            page_index=page_index,
            candidate_count=text_counts[page_index],
            limit=MAX_SOURCE_NOTE_TEXT_SCAN_PER_PAGE,
        )
        for page_index in sorted(blocked_text_pages)
    ]
    owners_by_page: dict[
        int,
        list[tuple[str, dict[str, float]]],
    ] = defaultdict(list)
    owner_counts: Counter[int] = Counter()
    blocked_owner_pages: set[int] = set()
    raw_pictures = raw_graph.get("pictures")
    if isinstance(raw_pictures, Sequence) and not isinstance(
        raw_pictures,
        (str, bytes, bytearray),
    ):
        for raw_owner in raw_pictures:
            if (
                not isinstance(raw_owner, Mapping)
                or not _has_caption(raw_owner)
                or _has_declared_note(raw_owner, references)
            ):
                continue
            owner_ref = str(raw_owner.get("self_ref") or "").strip()
            ref_bytes, ref_oversized = _bounded_utf8(
                owner_ref,
                MAX_SOURCE_NOTE_OWNER_REF_BYTES,
            )
            if (
                not owner_ref
                or ref_oversized
                or ref_bytes == 0
            ):
                continue
            page_box = _raw_page_box(raw_owner, page_heights)
            if page_box is None:
                continue
            page_index, owner_box = page_box
            owner_counts[page_index] += 1
            if (
                owner_counts[page_index]
                > MAX_SOURCE_NOTE_OWNER_SCAN_PER_PAGE
            ):
                blocked_owner_pages.add(page_index)
                owners_by_page.pop(page_index, None)
                continue
            if (
                page_index in blocked_owner_pages
                or page_index in blocked_text_pages
                or any(
                    _is_external_below(
                        note_box,
                        owner_box,
                        maximum_gap=72.0,
                    )
                    for note_box in visible_notes_by_page.get(
                        page_index,
                        (),
                    )
                )
            ):
                continue
            owners_by_page[page_index].append((owner_ref, owner_box))

    concerns.extend(
        _planning_concern(
            "layout_source_note_owner_scan_limit",
            page_index=page_index,
            candidate_count=owner_counts[page_index],
            limit=MAX_SOURCE_NOTE_OWNER_SCAN_PER_PAGE,
        )
        for page_index in sorted(blocked_owner_pages)
    )

    requests: list[PdfRegionRequest] = []
    for page_index, owner_candidates in sorted(owners_by_page.items()):
        owner_candidates.sort(
            key=lambda item: (
                item[1]["y"],
                item[1]["x"],
                item[0],
            )
        )
        if len(owner_candidates) > MAX_SOURCE_NOTE_ZONE_REQUESTS_PER_PAGE:
            concerns.append(
                _planning_concern(
                    "layout_source_note_zone_request_limit",
                    page_index=page_index,
                    candidate_count=len(owner_candidates),
                    limit=MAX_SOURCE_NOTE_ZONE_REQUESTS_PER_PAGE,
                )
            )
        for owner_ref, owner_box in owner_candidates[
            :MAX_SOURCE_NOTE_ZONE_REQUESTS_PER_PAGE
        ]:
            page_width = page_widths[page_index]
            page_height = page_heights[page_index]
            left = max(owner_box["x"], 0.0)
            right = min(
                owner_box["x"] + owner_box["width"],
                page_width,
            )
            owner_bottom = owner_box["y"] + owner_box["height"]
            height = min(
                MAX_SOURCE_NOTE_ZONE_HEIGHT,
                page_height - owner_bottom,
            )
            if right - left <= 0.01 or height <= 0.01:
                continue
            normalized_owner_box = {
                "x": round(owner_box["x"], 3),
                "y": round(owner_box["y"], 3),
                "width": round(owner_box["width"], 3),
                "height": round(owner_box["height"], 3),
                "unit": "pt",
            }
            requests.append(
                PdfRegionRequest(
                    page_index=page_index,
                    bbox={
                        "x": round(left, 3),
                        "y": round(owner_bottom, 3),
                        "width": round(right - left, 3),
                        "height": round(height, 3),
                    },
                    content_type=SOURCE_NOTE_ZONE_CONTENT_TYPE,
                    region_role="content_region",
                    metadata={
                        "render_reason": SOURCE_NOTE_ZONE_CONTENT_TYPE,
                        SOURCE_NOTE_ZONE_MARKER: True,
                        SOURCE_NOTE_OWNER_REF: owner_ref,
                        SOURCE_NOTE_OWNER_BBOX: normalized_owner_box,
                    },
                )
            )
    return SourceNoteEvidencePlan(
        requests=tuple(requests),
        concerns=tuple(concerns),
    )


def is_source_note_zone_region(region: ImageRegion) -> bool:
    """Return whether a rendered region is private source-note evidence."""

    return bool(
        region.content_type == SOURCE_NOTE_ZONE_CONTENT_TYPE
        or region.metadata.get(SOURCE_NOTE_ZONE_MARKER) is True
    )


def discard_source_note_zone_regions(
    image_regions: MutableMapping[int, list[ImageRegion]],
) -> None:
    """Remove all private note-zone renders before shared public analysis."""

    for page_index, regions in list(image_regions.items()):
        image_regions[page_index] = [
            region
            for region in regions
            if not is_source_note_zone_region(region)
        ]


def _stable_raw_ref(prefix: str, *values: Any) -> str:
    payload = "\0".join(str(value) for value in values).encode(
        "utf-8",
        errors="strict",
    )
    return f"#/texts/{prefix}-{hashlib.sha256(payload).hexdigest()[:24]}"


def _raw_provenance(
    *,
    page_index: int,
    bbox: Mapping[str, float],
    text: str,
) -> list[dict[str, Any]]:
    return [
        {
            "page_no": page_index,
            "bbox": {
                "l": round(bbox["x"], 3),
                "t": round(bbox["y"], 3),
                "r": round(bbox["x"] + bbox["width"], 3),
                "b": round(bbox["y"] + bbox["height"], 3),
                "coord_origin": "TOPLEFT",
            },
            "charspan": [0, len(text)],
        }
    ]


def _append_reference(
    raw_owner: MutableMapping[str, Any],
    field_name: str,
    reference: str,
) -> bool:
    existing = raw_owner.get(field_name)
    if existing is None:
        raw_owner[field_name] = [{"$ref": reference}]
        return True
    if not isinstance(existing, list):
        return False
    if reference not in {
        _raw_reference(value)
        for value in existing[:1024]
    }:
        existing.append({"$ref": reference})
    return True


def _valid_zone(
    region: ImageRegion,
    references: Mapping[str, Mapping[str, Any]],
    visual_owner_refs: set[str],
) -> tuple[str, dict[str, float], dict[str, float]] | None:
    metadata = region.metadata
    owner_ref = str(metadata.get(SOURCE_NOTE_OWNER_REF) or "").strip()
    _ref_bytes, ref_oversized = _bounded_utf8(
        owner_ref,
        MAX_SOURCE_NOTE_OWNER_REF_BYTES,
    )
    owner_box = _coerce_box(metadata.get(SOURCE_NOTE_OWNER_BBOX))
    region_box = _coerce_box(region.bbox)
    raw_owner = references.get(owner_ref)
    owner_pages = (
        _raw_page_indices(raw_owner)
        if isinstance(raw_owner, Mapping)
        else set()
    )
    if (
        region.content_type != SOURCE_NOTE_ZONE_CONTENT_TYPE
        or metadata.get(SOURCE_NOTE_ZONE_MARKER) is not True
        or region.region_role != "content_region"
        or region.region_origin != "pdf_page_render"
        or region.coordinate_unit != "pt"
        or not owner_ref
        or ref_oversized
        or owner_ref not in visual_owner_refs
        or region.page_index not in owner_pages
        or not isinstance(
            metadata.get(SOURCE_NOTE_OWNER_BBOX),
            Mapping,
        )
        or metadata[SOURCE_NOTE_OWNER_BBOX].get("unit") != "pt"
        or owner_box is None
        or region_box is None
        or region_box["x"] < 0
        or region_box["y"] < 0
        or region_box["height"] > MAX_SOURCE_NOTE_ZONE_HEIGHT + _EPSILON
    ):
        return None
    owner_bottom = owner_box["y"] + owner_box["height"]
    if (
        abs(region_box["x"] - owner_box["x"]) > _EPSILON
        or abs(region_box["width"] - owner_box["width"]) > _EPSILON
        or abs(region_box["y"] - owner_bottom) > _EPSILON
    ):
        return None
    return owner_ref, owner_box, region_box


def _line_is_inside_zone(
    line_box: Mapping[str, float],
    owner_box: Mapping[str, float],
    region_box: Mapping[str, float],
) -> bool:
    owner_bottom = owner_box["y"] + owner_box["height"]
    region_bottom = region_box["y"] + region_box["height"]
    return bool(
        line_box["y"] + _EPSILON >= owner_bottom
        and line_box["y"] + line_box["height"] <= region_bottom + 1.0
        and line_box["x"] + 1.0 >= region_box["x"]
        and (
            line_box["x"] + line_box["width"]
            <= region_box["x"] + region_box["width"] + 1.0
        )
        and _horizontal_overlap(line_box, owner_box) >= 0.20
    )


def _safe_http_target_with_reason(value: Any) -> tuple[str | None, str | None]:
    if isinstance(value, bytes):
        try:
            target = value.decode("ascii")
        except UnicodeDecodeError:
            return None, "non_ascii_target"
    elif isinstance(value, str):
        target = value
    else:
        return None, "non_text_target"
    if not target:
        return None, "empty_target"
    if len(target) > MAX_PDF_ANNOTATION_TARGET_BYTES:
        return None, "oversized_target"
    byte_count, oversized = _bounded_utf8(
        target,
        MAX_PDF_ANNOTATION_TARGET_BYTES,
    )
    if oversized or byte_count == 0:
        return None, "oversized_target"
    if any(ord(character) < 0x21 or ord(character) > 0x7E for character in target):
        return None, "control_or_non_ascii_target"
    if "\\" in target:
        return None, "backslash_target"
    try:
        parsed = urlsplit(target)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None, "malformed_target"
    if parsed.scheme.casefold() not in {"http", "https"}:
        return None, "unsafe_scheme"
    if (
        not parsed.netloc
        or hostname is None
    ):
        return None, "missing_or_malformed_host"
    if parsed.username is not None or parsed.password is not None:
        return None, "credentialed_target"
    if port is not None and not 1 <= port <= 65535:
        return None, "invalid_port"
    return target, None


def safe_http_annotation_target(value: Any) -> str | None:
    """Return a bounded safe HTTP(S) annotation target, otherwise ``None``."""

    target, _reason = _safe_http_target_with_reason(value)
    return target


def _annotation_box(
    annotation: Mapping[str, Any],
    *,
    page_width: float,
    page_height: float,
) -> dict[str, float] | None:
    try:
        left = float(annotation["x0"])
        top = float(annotation["top"])
        right = float(annotation["x1"])
        bottom = float(annotation["bottom"])
    except (KeyError, TypeError, ValueError):
        return None
    if (
        not all(math.isfinite(item) for item in (left, top, right, bottom))
        or left < 0
        or top < 0
        or right <= left
        or bottom <= top
        or right > page_width + _EPSILON
        or bottom > page_height + _EPSILON
    ):
        return None
    return {
        "x": left,
        "y": top,
        "width": right - left,
        "height": bottom - top,
    }


def _annotation_owner_boxes(
    raw_graph: Mapping[str, Any],
    page_heights: Mapping[int, float],
) -> tuple[
    dict[int, list[dict[str, float]]],
    list[dict[str, Any]],
]:
    owners_by_page: dict[int, list[dict[str, float]]] = defaultdict(list)
    owner_counts: Counter[int] = Counter()
    blocked_pages: set[int] = set()
    for collection_name in ("pictures", "tables"):
        raw_owners = raw_graph.get(collection_name)
        if not isinstance(raw_owners, Sequence) or isinstance(
            raw_owners,
            (str, bytes, bytearray),
        ):
            continue
        for raw_owner in raw_owners:
            if not isinstance(raw_owner, Mapping):
                continue
            page_box = _raw_page_box(raw_owner, page_heights)
            if page_box is None:
                continue
            page_index, owner_box = page_box
            owner_counts[page_index] += 1
            if (
                owner_counts[page_index]
                > MAX_SOURCE_NOTE_OWNER_SCAN_PER_PAGE
            ):
                blocked_pages.add(page_index)
                owners_by_page.pop(page_index, None)
                continue
            if page_index not in blocked_pages:
                owners_by_page[page_index].append(owner_box)
    concerns = [
        _planning_concern(
            "layout_source_note_annotation_owner_scan_limit",
            page_index=page_index,
            candidate_count=owner_counts[page_index],
            limit=MAX_SOURCE_NOTE_OWNER_SCAN_PER_PAGE,
        )
        for page_index in sorted(blocked_pages)
    ]
    return dict(owners_by_page), concerns


def _annotation_nodes(
    pdf_bytes: bytes,
    raw_graph: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        import pdfplumber
    except ImportError:
        return [], [{"code": "layout_source_note_annotation_unavailable"}]

    nodes: list[dict[str, Any]] = []
    concerns: list[dict[str, Any]] = []
    rejected: Counter[tuple[int, str]] = Counter()
    examined_count = 0
    retained_count = 0
    document_limited = False
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as document:
            owner_boxes_by_page: (
                dict[int, list[dict[str, float]]] | None
            ) = None
            if raw_graph is not None:
                owner_boxes_by_page, owner_concerns = (
                    _annotation_owner_boxes(
                        raw_graph,
                        {
                            page_index: float(page.height)
                            for page_index, page in enumerate(
                                document.pages,
                                1,
                            )
                        },
                    )
                )
                concerns.extend(owner_concerns)
            for page_index, page in enumerate(document.pages, 1):
                annotations = page.hyperlinks
                if not isinstance(annotations, Sequence):
                    continue
                if len(annotations) > MAX_PDF_ANNOTATIONS_PER_PAGE:
                    concerns.append(
                        _planning_concern(
                            "layout_source_note_annotation_page_limit",
                            page_index=page_index,
                            candidate_count=len(annotations),
                            limit=MAX_PDF_ANNOTATIONS_PER_PAGE,
                        )
                    )
                for annotation in annotations[
                    :MAX_PDF_ANNOTATIONS_PER_PAGE
                ]:
                    if examined_count >= MAX_PDF_ANNOTATIONS_PER_DOCUMENT:
                        document_limited = True
                        break
                    examined_count += 1
                    if not isinstance(annotation, Mapping):
                        rejected[(page_index, "malformed_annotation")] += 1
                        continue
                    target, reason = _safe_http_target_with_reason(
                        annotation.get("uri")
                    )
                    if target is None:
                        rejected[
                            (page_index, reason or "unsafe_target")
                        ] += 1
                        continue
                    box = _annotation_box(
                        annotation,
                        page_width=float(page.width),
                        page_height=float(page.height),
                    )
                    if box is None:
                        rejected[(page_index, "invalid_geometry")] += 1
                        continue
                    if (
                        owner_boxes_by_page is not None
                        and not any(
                            _is_external_below(
                                box,
                                owner_box,
                                maximum_gap=72.0,
                            )
                            for owner_box in owner_boxes_by_page.get(
                                page_index,
                                (),
                            )
                        )
                    ):
                        rejected[
                            (
                                page_index,
                                "not_near_structured_owner",
                            )
                        ] += 1
                        continue
                    try:
                        crop = page.crop(
                            (
                                box["x"],
                                box["y"],
                                box["x"] + box["width"],
                                box["y"] + box["height"],
                            )
                        )
                        visible_text = str(
                            crop.extract_text(
                                x_tolerance=2,
                                y_tolerance=2,
                            )
                            or ""
                        ).strip()
                    except Exception:
                        rejected[
                            (page_index, "visible_text_unavailable")
                        ] += 1
                        continue
                    _text_bytes, text_oversized = _bounded_utf8(
                        visible_text,
                        MAX_VISIBLE_ANNOTATION_TEXT_BYTES,
                    )
                    if (
                        not visible_text
                        or text_oversized
                        or target not in visible_text
                    ):
                        rejected[
                            (page_index, "target_not_source_visible")
                        ] += 1
                        continue
                    reference = _stable_raw_ref(
                        "layout-source-note-annotation",
                        page_index,
                        box,
                        target,
                        visible_text,
                    )
                    nodes.append(
                        {
                            "self_ref": reference,
                            "label": "annotation",
                            "text": visible_text,
                            "source": "native",
                            "evidence_methods": ["native"],
                            "prov": _raw_provenance(
                                page_index=page_index,
                                bbox=box,
                                text=visible_text,
                            ),
                            "hyperlink": target,
                            "meta": {
                                SOURCE_NOTE_ANNOTATION_MARKER: {
                                    "source_visible": True,
                                    "bbox": {
                                        **{
                                            key: round(value, 3)
                                            for key, value in box.items()
                                        },
                                        "unit": "pt",
                                    },
                                }
                            },
                        }
                    )
                    retained_count += 1
                if document_limited:
                    break
    except Exception as exc:
        return (
            [],
            [
                {
                    "code": "layout_source_note_annotation_unavailable",
                    "error_type": type(exc).__name__,
                }
            ],
        )

    if document_limited:
        concerns.append(
            {
                "code": "layout_source_note_annotation_document_limit",
                "examined_count": examined_count,
                "retained_count": retained_count,
                "limit": MAX_PDF_ANNOTATIONS_PER_DOCUMENT,
            }
        )
    concerns.extend(
        {
            "code": "layout_source_note_annotation_rejected",
            "page_index": page_index,
            "reason": reason,
            "candidate_count": count,
        }
        for (page_index, reason), count in sorted(rejected.items())
    )
    return nodes, concerns


def _merge_evidence_ledger(
    raw_graph: MutableMapping[str, Any],
    *,
    source_note_refs: Sequence[str] = (),
    annotation_refs: Sequence[str] = (),
    concerns: Sequence[Mapping[str, Any]] = (),
) -> None:
    existing = raw_graph.get(SOURCE_NOTE_EVIDENCE_LEDGER)
    if not isinstance(existing, MutableMapping):
        existing = {
            "schema_version": "1.0",
            "source_note_refs": [],
            "annotation_refs": [],
            "concerns": [],
        }
        raw_graph[SOURCE_NOTE_EVIDENCE_LEDGER] = existing
    for key, values in (
        ("source_note_refs", source_note_refs),
        ("annotation_refs", annotation_refs),
    ):
        target = existing.setdefault(key, [])
        if not isinstance(target, list):
            continue
        for value in values:
            if value not in target:
                target.append(value)
    target_concerns = existing.setdefault("concerns", [])
    if not isinstance(target_concerns, list):
        return
    for concern in concerns:
        sanitized = dict(concern)
        if sanitized not in target_concerns:
            target_concerns.append(sanitized)


def record_source_note_evidence_concerns(
    raw_graph: MutableMapping[str, Any],
    concerns: Sequence[Mapping[str, Any]],
) -> None:
    """Retain sanitized planning/failure concerns for the IR projector."""

    _merge_evidence_ledger(raw_graph, concerns=concerns)


def attach_source_note_evidence_concerns(
    ir: Any,
    raw_graph: Mapping[str, Any],
) -> Any:
    """Attach bounded, content-free evidence diagnostics to a document IR."""

    ledger = raw_graph.get(SOURCE_NOTE_EVIDENCE_LEDGER)
    if not isinstance(ledger, Mapping):
        return ir
    raw_concerns = ledger.get("concerns")
    if not isinstance(raw_concerns, Sequence) or isinstance(
        raw_concerns,
        (str, bytes, bytearray),
    ):
        return ir

    from app.services.ir import IRConcern

    retained: list[tuple[str, dict[str, Any]]] = []
    retained_keys: set[tuple[Any, ...]] = set()
    page_counts: Counter[int] = Counter()
    suppressed_count = 0
    for raw_concern in raw_concerns:
        if not isinstance(raw_concern, Mapping):
            suppressed_count += 1
            continue
        code = str(raw_concern.get("code") or "")
        if code not in _LEDGER_CONCERN_CODES:
            suppressed_count += 1
            continue
        page_index_value = raw_concern.get("page_index")
        page_index = (
            int(page_index_value)
            if isinstance(page_index_value, int)
            and not isinstance(page_index_value, bool)
            and page_index_value > 0
            else None
        )
        page_key = page_index or 0
        if (
            len(retained) >= MAX_SOURCE_NOTE_LEDGER_CONCERNS
            or page_counts[page_key]
            >= MAX_SOURCE_NOTE_LEDGER_CONCERNS_PER_PAGE
        ):
            suppressed_count += 1
            continue

        sanitized: dict[str, Any] = {}
        if page_index is not None:
            sanitized["page_index"] = page_index
        for key in (
            "candidate_count",
            "examined_count",
            "retained_count",
            "limit",
        ):
            value = raw_concern.get(key)
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and value >= 0
            ):
                sanitized[key] = value
        reason = raw_concern.get("reason")
        if isinstance(reason, str) and reason in _LEDGER_REASONS:
            sanitized["reason"] = reason
        error_type = raw_concern.get("error_type")
        if (
            isinstance(error_type, str)
            and _SAFE_ERROR_TYPE_RE.fullmatch(error_type)
        ):
            sanitized["error_type"] = error_type

        retained_key = (
            code,
            tuple(sorted(sanitized.items())),
        )
        if retained_key in retained_keys:
            continue
        retained_keys.add(retained_key)
        retained.append((code, sanitized))
        page_counts[page_key] += 1

    if not retained and suppressed_count == 0:
        return ir

    attached_concerns = list(ir.concerns)
    for code, sanitized in retained:
        attached_concerns.append(
            IRConcern(
                code=code,
                message=(
                    "Bounded source-note evidence extraction retained a "
                    "sanitized diagnostic."
                ),
                metadata={"source_note_evidence": sanitized},
            )
        )
    if suppressed_count:
        attached_concerns.append(
            IRConcern(
                code="layout_source_note_evidence_concerns_truncated",
                message=(
                    "Source-note evidence diagnostics exceeded validation or "
                    "emission bounds; a content-free aggregate was retained."
                ),
                metadata={
                    "suppressed_count": suppressed_count,
                    "document_limit": MAX_SOURCE_NOTE_LEDGER_CONCERNS,
                    "page_limit": (
                        MAX_SOURCE_NOTE_LEDGER_CONCERNS_PER_PAGE
                    ),
                },
            )
        )
    # The source graph, relationships, and evidence are unchanged; avoid a
    # second deep copy and whole-document validation merely to append already
    # validated concern models to the freshly built IR.
    return ir.model_copy(update={"concerns": attached_concerns})


def augment_source_note_evidence(
    raw_graph: MutableMapping[str, Any],
    image_regions: MutableMapping[int, list[ImageRegion]],
    *,
    pdf_bytes: bytes,
    accept_ocr_line: Callable[[Any], bool],
) -> SourceNoteEvidenceAugmentation:
    """Convert private note strips and PDF links into bounded raw evidence.

    Marked render regions are removed before any processing, so even a later
    refusal cannot expose them as public image or prose items.
    """

    marked_regions: list[ImageRegion] = []
    for page_index, regions in list(image_regions.items()):
        retained: list[ImageRegion] = []
        for region in regions:
            if is_source_note_zone_region(region):
                marked_regions.append(region)
            else:
                retained.append(region)
        image_regions[page_index] = retained

    concerns: list[dict[str, Any]] = []
    references = _reference_map(raw_graph)
    mutable_references = {
        reference: raw_item
        for reference, raw_item in references.items()
        if isinstance(raw_item, MutableMapping)
    }
    raw_pictures = raw_graph.get("pictures")
    visual_owner_refs = {
        str(raw_picture.get("self_ref") or "").strip()
        for raw_picture in (
            raw_pictures
            if isinstance(raw_pictures, Sequence)
            and not isinstance(raw_pictures, (str, bytes, bytearray))
            else ()
        )
        if isinstance(raw_picture, Mapping)
        and _has_caption(raw_picture)
    }
    raw_texts = raw_graph.get("texts")
    if not isinstance(raw_texts, list):
        concerns.append(
            {"code": "layout_source_note_text_collection_unavailable"}
        )
        _merge_evidence_ledger(raw_graph, concerns=concerns)
        return SourceNoteEvidenceAugmentation(
            source_note_refs=(),
            annotation_refs=(),
            concerns=tuple(concerns),
        )

    # Resolve annotations before mutating the raw graph. An unexpected adapter
    # failure can therefore never leave a partially augmented evidence graph.
    annotation_nodes, annotation_concerns = _annotation_nodes(
        pdf_bytes,
        raw_graph,
    )
    concerns.extend(annotation_concerns)
    existing_refs = {
        str(value.get("self_ref") or "")
        for value in raw_texts
        if isinstance(value, Mapping)
    }
    source_note_refs: list[str] = []
    lines_by_page: Counter[int] = Counter()
    regions_by_page: Counter[int] = Counter()
    for region in marked_regions:
        regions_by_page[region.page_index] += 1
        if (
            regions_by_page[region.page_index]
            > MAX_SOURCE_NOTE_ZONE_REQUESTS_PER_PAGE
        ):
            continue
        validated_zone = _valid_zone(
            region,
            references,
            visual_owner_refs,
        )
        if validated_zone is None:
            concerns.append(
                {
                    "code": "layout_source_note_zone_rejected",
                    "page_index": region.page_index,
                    "reason": "invalid_marker_or_geometry",
                }
            )
            continue
        owner_ref, owner_box, region_box = validated_zone
        raw_owner = mutable_references.get(owner_ref)
        if raw_owner is None:
            concerns.append(
                {
                    "code": "layout_source_note_zone_rejected",
                    "page_index": region.page_index,
                    "reason": "immutable_or_missing_owner",
                }
            )
            continue
        for line in region.lines[:MAX_SOURCE_NOTE_OCR_LINES_PER_PAGE]:
            if (
                lines_by_page[region.page_index]
                >= MAX_SOURCE_NOTE_OCR_LINES_PER_PAGE
            ):
                break
            lines_by_page[region.page_index] += 1
            try:
                accepted = accept_ocr_line(line) is True
            except Exception:
                accepted = False
            text = str(getattr(line, "text", "") or "").strip()
            _text_bytes, text_oversized = _bounded_utf8(
                text,
                MAX_SOURCE_NOTE_TEXT_BYTES,
            )
            line_box = _coerce_box(getattr(line, "bbox", None))
            if (
                not accepted
                or not _NOTE_PREFIX_RE.match(text)
                or text_oversized
                or line_box is None
                or not _line_is_inside_zone(
                    line_box,
                    owner_box,
                    region_box,
                )
            ):
                continue
            reference = _stable_raw_ref(
                "layout-source-note-ocr",
                region.page_index,
                owner_ref,
                line_box,
                text,
            )
            confidence = getattr(line, "confidence", None)
            if not (
                isinstance(confidence, (int, float))
                and math.isfinite(float(confidence))
                and 0 <= float(confidence) <= 1
            ):
                confidence = None
            node: dict[str, Any] = {
                "self_ref": reference,
                "label": "source_note",
                "text": text,
                "source": "ocr",
                "evidence_methods": ["ocr"],
                "prov": _raw_provenance(
                    page_index=region.page_index,
                    bbox=line_box,
                    text=text,
                ),
                "meta": {
                    SOURCE_NOTE_OCR_MARKER: {
                        "owner_ref": owner_ref,
                        "source_visible": True,
                    }
                },
            }
            if confidence is not None:
                node["confidence"] = round(float(confidence), 4)
            if reference not in existing_refs:
                raw_texts.append(node)
                existing_refs.add(reference)
            if not _append_reference(
                raw_owner,
                "source_notes",
                reference,
            ):
                concerns.append(
                    {
                        "code": "layout_source_note_owner_field_rejected",
                        "page_index": region.page_index,
                        "reason": "malformed_source_notes_field",
                    }
                )
                continue
            source_note_refs.append(reference)

    annotation_refs: list[str] = []
    for node in annotation_nodes:
        reference = str(node["self_ref"])
        if reference not in existing_refs:
            raw_texts.append(node)
            existing_refs.add(reference)
        annotation_refs.append(reference)

    source_note_refs = list(dict.fromkeys(source_note_refs))
    annotation_refs = list(dict.fromkeys(annotation_refs))
    _merge_evidence_ledger(
        raw_graph,
        source_note_refs=source_note_refs,
        annotation_refs=annotation_refs,
        concerns=concerns,
    )
    return SourceNoteEvidenceAugmentation(
        source_note_refs=tuple(source_note_refs),
        annotation_refs=tuple(annotation_refs),
        concerns=tuple(concerns),
    )
