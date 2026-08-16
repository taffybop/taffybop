"""Source-grounded Phase 03 layout normalization.

Only behavior whose story flag is enabled is projected into the public
compatibility view.  Raw IR evidence and relationships are never discarded.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from collections import defaultdict
from copy import deepcopy
from functools import lru_cache
from typing import Any, Callable, Mapping, MutableMapping
from urllib.parse import urlsplit

from app.config import Settings
from app.services.ir import (
    RAW_GENERATION_PROVENANCE_PROPERTY,
    DocumentIR,
    ElementRecord,
    EvidenceMethod,
    IRConcern,
    RelationshipRecord,
    RelationshipType,
    has_untrusted_generation_provenance,
)
from app.services.source_note_contracts import (
    SOURCE_NOTE_OWNER_TYPES,
    is_eligible_unresolved_table_candidate,
    is_source_note_owner_item,
)


_SPACE_RE = re.compile(r"\s+")
_MIN_HORIZONTAL_OVERLAP = 0.20
_MAX_CAPTION_GAP_POINTS = 72.0
_MAX_INTERNAL_OVERLAP = 0.20
_MAX_TABLE_CAPTION_REFERENCES = 64
_MAX_SAME_TEXT_CAPTION_CANDIDATES = 128
_MAX_PAGE_CAPTION_CANDIDATES = 512
_VISUAL_TYPES = frozenset({"image", "chart", "diagram"})
_MIN_CHILD_CONTAINMENT = 0.80
_MAX_VISUAL_CAPTION_REFERENCES = 64
_MAX_VISUAL_CHILD_REFERENCES = 256
_MAX_VISUAL_OWNERS_PER_PAGE = 512
_MAX_VISUAL_CAPTION_BYTES = 64 * 1024
_MAX_CONTAINED_ITEMS_BYTES = 256 * 1024
_MAX_VISUAL_SOURCE_TEXT_BYTES = 64 * 1024
_MAX_VISUAL_SOURCE_TEXT_OCCURRENCES = 512
_MAX_VISUAL_SOURCE_TEXT_LINES = 512
_MAX_VISUAL_CONCERNS_PER_OWNER = 16
_MAX_VISUAL_CONCERNS_PER_PAGE = 256
_MAX_PUNCTUATION_FALLBACK_BYTES = 4096
_CONTAINED_ITEM_BBOX_RESERVE_BYTES = 256
# OCR and source-layout boxes can differ by a sub-point crop/rounding seam even
# when they describe the same owned visual.  Keep that interoperability margin
# deliberately no larger than one layout point so it cannot admit neighboring
# text or text owned by another visual.
_PRIMARY_OCR_BBOX_TOLERANCE_PT = 1.0
_SOURCE_NOTE_OWNER_TYPES = SOURCE_NOTE_OWNER_TYPES
_SOURCE_NOTE_TYPES = frozenset(
    {"source_note", "footnote", "source-note", "note"}
)
_SOURCE_NOTE_PREFIX_RE = re.compile(
    r"^\s*(?P<label>source|data|note|footnote)\s*:",
    re.IGNORECASE,
)
_STATLINK_PREFIX_RE = re.compile(r"^\s*statlink(?:\s|\d|:)", re.IGNORECASE)
_HTTP_URL_RE = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)
_MAX_SOURCE_NOTE_REFERENCES = 64
_MAX_SOURCE_NOTE_OWNERS_PER_PAGE = 256
_MAX_SOURCE_NOTE_CANDIDATES_PER_PAGE = 512
_MAX_SAME_TEXT_SOURCE_NOTE_CANDIDATES = 128
_MAX_SOURCE_NOTE_BYTES = 16 * 1024
_MAX_SOURCE_NOTE_URI_BYTES = 2 * 1024
_MAX_SOURCE_NOTE_LINKS = 16
_MAX_SOURCE_NOTE_CONCERNS_PER_PAGE = 256
_MAX_SOURCE_NOTE_GAP_POINTS = 72.0
_ACCEPTED_RAW_SOURCE_METHODS = frozenset(
    {
        EvidenceMethod.NATIVE,
        EvidenceMethod.OCR,
        EvidenceMethod.VECTOR,
        EvidenceMethod.EMBEDDED,
        EvidenceMethod.RECOVERED,
    }
)


def _bounded_utf8_size(value: str, limit: int) -> tuple[int, bool]:
    """Count UTF-8 bytes with bounded temporary memory and early overflow."""

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


def _bounded_json_size(
    values: list[Mapping[str, Any]],
    limit: int,
) -> tuple[int, bool]:
    """Stream a JSON array byte count without materializing its serialization."""

    encoder = json.JSONEncoder(
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    byte_count = 2
    for index, value in enumerate(values):
        if index:
            byte_count += 1
        for chunk in encoder.iterencode(value):
            chunk_bytes, overflow = _bounded_utf8_size(
                chunk,
                limit - min(byte_count, limit),
            )
            byte_count += chunk_bytes
            if overflow or byte_count > limit:
                return byte_count, True
    return byte_count, False


def _normalized_text_digest(value: Any) -> str:
    """Hash normalized text incrementally for bounded same-text grouping."""

    digest = hashlib.sha256()
    emitted = False
    pending_space = False
    for character in str(value or ""):
        if character.isspace():
            if emitted:
                pending_space = True
            continue
        if pending_space:
            digest.update(b" ")
            pending_space = False
        folded = character.casefold()
        digest.update(folded.encode("utf-8"))
        emitted = True
    return digest.hexdigest()


def _legacy_item(element: ElementRecord) -> dict[str, Any]:
    value = element.properties.get("legacy_item")
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    return {
        "id": element.id,
        "type": element.type,
        "reading_order": element.reading_order or 0,
        "value": deepcopy(element.value),
        "md": element.markdown,
    }


def _is_source_note_owner(element: ElementRecord) -> bool:
    if element.type.casefold() in _SOURCE_NOTE_OWNER_TYPES:
        return True
    legacy = element.properties.get("legacy_item")
    return (
        isinstance(legacy, Mapping)
        and str(legacy.get("type") or "").casefold()
        == element.type.casefold()
        and is_source_note_owner_item(legacy)
    )


def _is_table_caption_owner(element: ElementRecord) -> bool:
    if element.type.casefold() == "table":
        return True
    legacy = element.properties.get("legacy_item")
    if not isinstance(legacy, Mapping) or (
        str(legacy.get("type") or "").casefold()
        != element.type.casefold()
    ):
        return False
    return is_eligible_unresolved_table_candidate(legacy)


def _normalized_text(value: Any) -> str:
    return _SPACE_RE.sub(" ", str(value or "")).strip().casefold()


def _public_relationship_id(source_id: str, target_id: str) -> str:
    digest = hashlib.sha256(
        f"P03-US01\0caption_of\0{source_id}\0{target_id}".encode("utf-8")
    ).hexdigest()
    return f"layout-rel-{digest[:20]}"


def _public_visual_relationship_id(
    relationship_type: RelationshipType,
    source_id: str,
    target_id: str,
) -> str:
    digest = hashlib.sha256(
        (
            f"P03-US02\0{relationship_type.value}\0"
            f"{source_id}\0{target_id}"
        ).encode("utf-8")
    ).hexdigest()
    return f"layout-rel-{digest[:20]}"


def _public_source_note_relationship_id(
    relationship_type: RelationshipType,
    source_id: str,
    target_id: str,
) -> str:
    digest = hashlib.sha256(
        (
            f"P03-US03\0{relationship_type.value}\0"
            f"{source_id}\0{target_id}"
        ).encode("utf-8")
    ).hexdigest()
    return f"layout-rel-{digest[:20]}"


def _stable_source_note_public_id(
    owner_public_id: str,
    note: ElementRecord,
    note_box: Mapping[str, Any] | None,
) -> str:
    raw_refs = sorted(
        str(reference)
        for reference in note.properties.get("raw_refs", [])
        if str(reference)
    )
    digest = hashlib.sha256(
        json.dumps(
            (
                "P03-US03",
                "source-note",
                owner_public_id,
                raw_refs,
                _normalized_text(note.value),
                note_box,
            ),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    return f"layout-note-{digest[:20]}"


def _stable_visual_caption_public_id(
    owner_public_id: str,
    caption: ElementRecord,
    caption_box: Mapping[str, Any] | None,
) -> str:
    raw_refs = sorted(
        str(reference)
        for reference in caption.properties.get("raw_refs", [])
        if str(reference)
    )
    digest = hashlib.sha256(
        json.dumps(
            (
                "P03-US02",
                "caption",
                owner_public_id,
                raw_refs,
                _normalized_text(caption.value),
                caption_box,
            ),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    return f"layout-caption-{digest[:20]}"


def _compatibility_element_id(
    ir: DocumentIR,
    page: Any,
    public_id: str,
) -> str:
    payload = json.dumps(
        (ir.id, page.page_index, ("legacy_id", public_id)),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"el-{hashlib.sha256(payload).hexdigest()[:20]}"


def _transform_point(
    transform: tuple[float, float, float, float, float, float],
    x: float,
    y: float,
) -> tuple[float, float]:
    a, b, c, d, e, f = transform
    return a * x + c * y + e, b * x + d * y + f


def _page_bbox(
    element: ElementRecord,
    *,
    boxes: Mapping[str, Any],
    coordinates: Mapping[str, Any],
    pages: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Project an element box into its page's top-left coordinate system."""

    page = pages.get(element.page_id)
    if page is None:
        return None
    page_coordinate = coordinates.get(page.coordinate_system_id)
    if page_coordinate is None:
        return None
    raw_bbox_ids = [
        record.bbox_id
        for evidence_id in element.evidence_ids
        if (record := evidence.get(evidence_id)) is not None
        and record.bbox_id is not None
        and record.metadata.get("raw_ref")
    ]
    # Prefer the union of every usable raw provenance box. Captions are often
    # split across source runs or lines; returning only the first run would
    # understate both exported geometry and promotion gating. Fall back to the
    # element's retained boxes only when raw provenance has no usable box.
    candidate_sets = (
        list(dict.fromkeys(raw_bbox_ids)),
        list(dict.fromkeys(element.bbox_ids)),
    )
    for bbox_ids in candidate_sets:
        projected_boxes: list[tuple[float, float, float, float]] = []
        for bbox_id in bbox_ids:
            box = boxes.get(bbox_id)
            if box is None:
                continue
            coordinate = coordinates.get(box.coordinate_system_id)
            if (
                coordinate is None
                or coordinate.page_id != page.id
                or coordinate.transform_to_page is None
                or coordinate.unit != page_coordinate.unit
            ):
                continue
            corners = [
                _transform_point(
                    coordinate.transform_to_page,
                    x,
                    y,
                )
                for x, y in (
                    (box.x, box.y),
                    (box.x + box.width, box.y),
                    (box.x, box.y + box.height),
                    (box.x + box.width, box.y + box.height),
                )
            ]
            left = min(point[0] for point in corners)
            top = min(point[1] for point in corners)
            right = max(point[0] for point in corners)
            bottom = max(point[1] for point in corners)
            values = (left, top, right, bottom)
            if all(math.isfinite(value) for value in values):
                projected_boxes.append(values)
        if not projected_boxes:
            continue
        left = min(box[0] for box in projected_boxes)
        top = min(box[1] for box in projected_boxes)
        right = max(box[2] for box in projected_boxes)
        bottom = max(box[3] for box in projected_boxes)
        return {
            "x": round(left, 3),
            "y": round(top, 3),
            "width": round(max(right - left, 0.0), 3),
            "height": round(max(bottom - top, 0.0), 3),
            "unit": page_coordinate.unit,
        }
    return None


def _area(box: Mapping[str, Any] | None) -> float:
    if box is None:
        return 0.0
    return float(box["width"]) * float(box["height"])


def _intersection_area(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> float:
    left = max(float(first["x"]), float(second["x"]))
    top = max(float(first["y"]), float(second["y"]))
    right = min(
        float(first["x"]) + float(first["width"]),
        float(second["x"]) + float(second["width"]),
    )
    bottom = min(
        float(first["y"]) + float(first["height"]),
        float(second["y"]) + float(second["height"]),
    )
    return max(right - left, 0.0) * max(bottom - top, 0.0)


def _overlap_components(
    boxes: list[Mapping[str, Any] | None],
) -> list[list[int]]:
    """Return order-stable transitive components at the equivalence threshold."""

    parent = list(range(len(boxes)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root == second_root:
            return
        if first_root < second_root:
            parent[second_root] = first_root
        else:
            parent[first_root] = second_root

    for first_index, first in enumerate(boxes):
        if first is None:
            continue
        for second_index in range(first_index + 1, len(boxes)):
            second = boxes[second_index]
            if second is None:
                continue
            smaller = min(_area(first), _area(second))
            overlap = (
                _intersection_area(first, second) / smaller
                if smaller > 0
                else 0.0
            )
            if overlap >= 0.80:
                union(first_index, second_index)

    grouped: dict[int, list[int]] = defaultdict(list)
    for index in range(len(boxes)):
        grouped[find(index)].append(index)
    return sorted(grouped.values(), key=lambda group: group[0])


def _horizontal_overlap(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> float:
    left = max(float(first["x"]), float(second["x"]))
    right = min(
        float(first["x"]) + float(first["width"]),
        float(second["x"]) + float(second["width"]),
    )
    denominator = min(float(first["width"]), float(second["width"]))
    return max(right - left, 0.0) / denominator if denominator > 0 else 0.0


def _vertical_gap(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> float:
    first_top = float(first["y"])
    first_bottom = first_top + float(first["height"])
    second_top = float(second["y"])
    second_bottom = second_top + float(second["height"])
    if first_bottom < second_top:
        return second_top - first_bottom
    if second_bottom < first_top:
        return first_top - second_bottom
    return 0.0


def _external_caption_geometry(
    caption_box: Mapping[str, Any] | None,
    owner_box: Mapping[str, Any] | None,
) -> tuple[bool, str]:
    if caption_box is None:
        return False, "caption_geometry_unavailable"
    if owner_box is None:
        return False, "table_geometry_unavailable"
    if _area(caption_box) <= 0:
        return False, "caption_geometry_empty"
    if _area(owner_box) <= 0:
        return False, "table_geometry_empty"
    smaller = min(_area(caption_box), _area(owner_box))
    overlap = (
        _intersection_area(caption_box, owner_box) / smaller
        if smaller > 0
        else 0.0
    )
    if overlap > _MAX_INTERNAL_OVERLAP:
        return False, "caption_inside_or_overlapping_table"
    if _horizontal_overlap(caption_box, owner_box) < _MIN_HORIZONTAL_OVERLAP:
        return False, "caption_not_horizontally_aligned"
    if _vertical_gap(caption_box, owner_box) > _MAX_CAPTION_GAP_POINTS:
        return False, "caption_too_distant_from_table"
    return True, "graph_and_geometry"


def _external_visual_caption_geometry(
    caption_box: Mapping[str, Any] | None,
    owner_box: Mapping[str, Any] | None,
) -> tuple[bool, str, str | None]:
    valid, basis = _external_caption_geometry(caption_box, owner_box)
    if not valid:
        return False, basis.replace("table", "visual"), None
    assert caption_box is not None
    assert owner_box is not None
    caption_top = float(caption_box["y"])
    caption_bottom = caption_top + float(caption_box["height"])
    owner_top = float(owner_box["y"])
    owner_bottom = owner_top + float(owner_box["height"])
    if caption_bottom <= owner_top:
        return True, basis, "before"
    if owner_bottom <= caption_top:
        return True, basis, "after"
    return False, "caption_side_ambiguous", None


def _external_source_note_geometry(
    note_box: Mapping[str, Any] | None,
    owner_box: Mapping[str, Any] | None,
) -> tuple[bool, str]:
    if note_box is None:
        return False, "source_note_geometry_unavailable"
    if owner_box is None:
        return False, "source_note_owner_geometry_unavailable"
    if _area(note_box) <= 0:
        return False, "source_note_geometry_empty"
    if _area(owner_box) <= 0:
        return False, "source_note_owner_geometry_empty"
    if str(note_box.get("unit")) != str(owner_box.get("unit")):
        return False, "source_note_coordinate_unit_mismatch"
    if _intersection_area(note_box, owner_box) > 0:
        return False, "source_note_inside_or_overlapping_owner"
    owner_bottom = float(owner_box["y"]) + float(owner_box["height"])
    if float(note_box["y"]) < owner_bottom:
        return False, "source_note_not_below_owner"
    if _horizontal_overlap(note_box, owner_box) < _MIN_HORIZONTAL_OVERLAP:
        return False, "source_note_not_horizontally_aligned"
    if float(note_box["y"]) - owner_bottom > _MAX_SOURCE_NOTE_GAP_POINTS:
        return False, "source_note_too_distant_from_owner"
    return True, "graph_and_geometry"


def _child_containment_geometry(
    child_box: Mapping[str, Any] | None,
    owner_box: Mapping[str, Any] | None,
) -> tuple[bool, str, float]:
    if child_box is None:
        return False, "child_geometry_unavailable", 0.0
    if owner_box is None:
        return False, "visual_geometry_unavailable", 0.0
    child_area = _area(child_box)
    if child_area <= 0:
        return False, "child_geometry_empty", 0.0
    if _area(owner_box) <= 0:
        return False, "visual_geometry_empty", 0.0
    containment = _intersection_area(child_box, owner_box) / child_area
    if containment < _MIN_CHILD_CONTAINMENT:
        return False, "child_not_contained_by_visual", containment
    return True, "graph_and_geometry", containment


def _evidence_source(
    element: ElementRecord,
    evidence: Mapping[str, Any],
) -> str | None:
    methods = {
        evidence[evidence_id].method
        for evidence_id in element.evidence_ids
        if evidence_id in evidence
    }
    if not methods:
        return None
    if len(methods) > 1:
        return "mixed"
    method = next(iter(methods))
    if method is EvidenceMethod.OCR:
        return "ocr"
    if method in {
        EvidenceMethod.NATIVE,
        EvidenceMethod.VECTOR,
        EvidenceMethod.EMBEDDED,
        EvidenceMethod.RECOVERED,
    }:
        return "native"
    return "derived"


def _evidence_confidence(
    element: ElementRecord,
    evidence: Mapping[str, Any],
) -> float | None:
    scores = [
        record.confidence.score
        for evidence_id in element.evidence_ids
        if (record := evidence.get(evidence_id)) is not None
        and record.confidence.score is not None
    ]
    return min(scores) if scores else None


def _source_note_kind(
    element: ElementRecord,
    declared_types: set[RelationshipType],
) -> RelationshipType | None:
    if len(declared_types) > 1:
        return None
    if declared_types:
        return next(iter(declared_types))

    raw_label = str(element.properties.get("raw_label") or "").casefold()
    element_type = element.type.casefold()
    if "source" in raw_label and "note" in raw_label:
        return RelationshipType.SOURCE_NOTE_OF
    if "footnote" in raw_label:
        return RelationshipType.FOOTNOTE_OF
    if element_type in {"source_note", "source-note"}:
        return RelationshipType.SOURCE_NOTE_OF
    if element_type == "footnote":
        return RelationshipType.FOOTNOTE_OF

    value = element.value
    if not isinstance(value, str):
        return None
    match = _SOURCE_NOTE_PREFIX_RE.match(value)
    if match is not None:
        return (
            RelationshipType.SOURCE_NOTE_OF
            if match.group("label").casefold() in {"source", "data"}
            else RelationshipType.FOOTNOTE_OF
        )
    if _STATLINK_PREFIX_RE.match(value):
        return RelationshipType.FOOTNOTE_OF

    marker = element.properties.get("layout_source_note_candidate")
    raw_record = element.properties.get("raw_record")
    if marker is None and isinstance(raw_record, Mapping):
        marker = raw_record.get("layout_source_note_candidate")
        raw_meta = raw_record.get("meta")
        if (
            marker is None
            and isinstance(raw_meta, Mapping)
            and isinstance(
                raw_meta.get("layout_source_note_pdf_annotation"),
                Mapping,
            )
        ):
            marker = {
                "kind": "link",
                "annotation_backed": True,
            }
    if isinstance(marker, Mapping):
        marker_kind = str(marker.get("kind") or "").casefold()
        if marker_kind == "source_note":
            return RelationshipType.SOURCE_NOTE_OF
        if marker_kind in {"footnote", "link"}:
            return RelationshipType.FOOTNOTE_OF
    return None


def _safe_source_note_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    byte_count, oversized = _bounded_utf8_size(
        value,
        _MAX_SOURCE_NOTE_URI_BYTES,
    )
    if oversized or byte_count == 0:
        return None
    if any(
        ord(character) < 0x21 or ord(character) > 0x7E
        for character in value
    ):
        return None
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        return None
    if parsed.scheme.casefold() not in {"http", "https"}:
        return None
    if (
        not parsed.netloc
        or hostname is None
        or "\\" in value
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    if port is not None and not (0 < port <= 65535):
        return None
    return value


def _source_note_links(element: ElementRecord) -> list[dict[str, str]]:
    values: list[Any] = []
    raw_links = element.properties.get("links")
    if isinstance(raw_links, list):
        values.extend(raw_links[: _MAX_SOURCE_NOTE_LINKS + 1])
    raw_record = element.properties.get("raw_record")
    if isinstance(raw_record, Mapping):
        if raw_record.get("hyperlink") is not None:
            values.append(
                {
                    "kind": "hyperlink",
                    "target": raw_record.get("hyperlink"),
                }
            )
        record_links = raw_record.get("links")
        if isinstance(record_links, list):
            values.extend(record_links[: _MAX_SOURCE_NOTE_LINKS + 1])

    # A source-visible URL remains plain note text unless the evidence
    # augmentation path explicitly retained an annotation-backed link.
    marker = element.properties.get("layout_source_note_candidate")
    annotation_backed = (
        isinstance(marker, Mapping)
        and marker.get("annotation_backed") is True
    )
    output: list[dict[str, str]] = []
    for candidate in values:
        if not isinstance(candidate, Mapping):
            continue
        target = _safe_source_note_url(candidate.get("target"))
        if target is None:
            continue
        kind = str(candidate.get("kind") or "hyperlink").casefold()
        if kind not in {"hyperlink", "source_link", "statlink"}:
            kind = "hyperlink"
        record = {"kind": kind, "target": target}
        if record not in output:
            output.append(record)
        if len(output) >= _MAX_SOURCE_NOTE_LINKS:
            break
    if not output and annotation_backed and isinstance(element.value, str):
        for match in _HTTP_URL_RE.finditer(element.value):
            target = _safe_source_note_url(match.group(0).rstrip(".,);]"))
            if target is None:
                continue
            output.append({"kind": "hyperlink", "target": target})
            break
    return output


def _raw_source_note_link_candidate_count(element: ElementRecord) -> int:
    """Count bounded, de-duplicated raw link assertions without exposing them."""

    values: list[Any] = []
    raw_links = element.properties.get("links")
    if isinstance(raw_links, list):
        values.extend(raw_links[: _MAX_SOURCE_NOTE_LINKS + 1])
    raw_record = element.properties.get("raw_record")
    if isinstance(raw_record, Mapping):
        if raw_record.get("hyperlink") is not None:
            values.append(
                {
                    "kind": "hyperlink",
                    "target": raw_record.get("hyperlink"),
                }
            )
        record_links = raw_record.get("links")
        if isinstance(record_links, list):
            values.extend(record_links[: _MAX_SOURCE_NOTE_LINKS + 1])

    candidates: set[tuple[str, str]] = set()
    for index, candidate in enumerate(values):
        if not isinstance(candidate, Mapping):
            candidates.add(("unsupported", type(candidate).__name__))
            continue
        kind = str(candidate.get("kind") or "hyperlink").casefold()
        target = candidate.get("target")
        if not isinstance(target, str):
            candidates.add((kind, type(target).__name__))
            continue
        byte_count, oversized = _bounded_utf8_size(
            target,
            _MAX_SOURCE_NOTE_URI_BYTES,
        )
        if oversized:
            # Retain only a bounded digest input. The index distinguishes
            # separate over-limit assertions without materializing them in
            # diagnostics.
            bounded_prefix = target[: _MAX_SOURCE_NOTE_URI_BYTES + 1]
            bounded_digest = hashlib.sha256(
                bounded_prefix.encode(
                    "utf-8",
                    errors="surrogatepass",
                )
            ).hexdigest()
            target_key = (
                f"oversized:{index}:"
                f"{bounded_digest}"
            )
        else:
            target_key = f"{byte_count}:{target}"
        candidates.add((kind, target_key))
        if len(candidates) >= _MAX_SOURCE_NOTE_LINKS + 1:
            break
    return len(candidates)


def _has_source_visible_evidence(
    element: ElementRecord,
    evidence: Mapping[str, Any],
) -> bool:
    if bool(element.properties.get("generated")):
        return False
    methods = {
        record.method
        for evidence_id in element.evidence_ids
        if (record := evidence.get(evidence_id)) is not None
    }
    return bool(
        methods
        & {
            EvidenceMethod.NATIVE,
            EvidenceMethod.OCR,
            EvidenceMethod.VECTOR,
            EvidenceMethod.EMBEDDED,
            EvidenceMethod.RECOVERED,
        }
    )


def _raw_source_evidence(
    element: ElementRecord,
    evidence: Mapping[str, Any],
) -> list[Any]:
    return [
        record
        for evidence_id in element.evidence_ids
        if (record := evidence.get(evidence_id)) is not None
        and record.metadata.get("raw_ref")
    ]


def _has_raw_source_evidence(
    element: ElementRecord,
    evidence: Mapping[str, Any],
) -> bool:
    return bool(_raw_source_evidence(element, evidence))


def _raw_source_value(
    element: ElementRecord,
    evidence: Mapping[str, Any],
) -> Any:
    return deepcopy(_raw_source_value_view(element, evidence))


def _raw_source_value_view(
    element: ElementRecord,
    evidence: Mapping[str, Any],
) -> Any:
    """Return the selected raw value without copying potentially large data."""

    values: list[Any] = []
    for record in _raw_source_evidence(element, evidence):
        if record.value is None:
            continue
        if any(
            record.value is existing or record.value == existing
            for existing in values
        ):
            continue
        values.append(record.value)
    if len(values) == 1:
        return values[0]
    return element.value


def _has_accepted_raw_source_provenance(
    element: ElementRecord,
    evidence: Mapping[str, Any],
    *,
    allow_inferred_punctuation: bool = False,
) -> bool:
    if bool(
        element.properties.get("generated")
        or element.properties.get(RAW_GENERATION_PROVENANCE_PROPERTY)
    ):
        return False
    for property_name in ("raw_record", "raw_metadata"):
        property_value = element.properties.get(property_name)
        if has_untrusted_generation_provenance(
            property_value,
            _scan_all_values=True,
        ):
            return False
        if property_name == "raw_metadata" and property_value is not None:
            if (
                not isinstance(property_value, Mapping)
                or len(property_value) > 64
                or any(
                    has_untrusted_generation_provenance(nested)
                    for nested in property_value.values()
                )
            ):
                return False
    for property_name in ("legacy_child", "legacy_item"):
        if has_untrusted_generation_provenance(
            element.properties.get(property_name),
            include_derived_source=False,
        ):
            return False
    raw_records = _raw_source_evidence(element, evidence)
    if not raw_records:
        return False
    if all(
        record.method in _ACCEPTED_RAW_SOURCE_METHODS
        for record in raw_records
    ):
        return True
    if not allow_inferred_punctuation:
        return False

    # Docling can retain source-visible punctuation with a real raw bbox while
    # its alphanumeric method inference remains DERIVED. Admit that narrow
    # fallback only when the same element matched an already accepted legacy
    # native/OCR diagnostic. Raw explicit derived/model declarations and all
    # generated or unscannable provenance have already failed above.
    if not all(
        record.method is EvidenceMethod.DERIVED for record in raw_records
    ):
        return False
    for record in raw_records:
        raw_value = record.value
        if (
            record.bbox_id is None
            or not isinstance(raw_value, str)
            or not raw_value.strip()
        ):
            return False
        _byte_count, oversized = _bounded_utf8_size(
            raw_value,
            _MAX_PUNCTUATION_FALLBACK_BYTES,
        )
        if oversized or any(
            character.isalnum() for character in raw_value
        ):
            return False
    for property_name in ("legacy_child", "legacy_item"):
        legacy_value = element.properties.get(property_name)
        if not isinstance(legacy_value, Mapping):
            continue
        if str(legacy_value.get("source") or "").strip().casefold() in {
            "native",
            "ocr",
            "mixed",
            "vector",
            "embedded",
            "recovered",
        }:
            return True
    return False


def _visual_caption_payload_overflow(
    element: ElementRecord,
    evidence: Mapping[str, Any],
) -> tuple[int, bool]:
    observed_bytes = 0
    candidates = [
        _raw_source_value_view(element, evidence),
        element.markdown,
    ]
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        byte_count, oversized = _bounded_utf8_size(
            candidate,
            _MAX_VISUAL_CAPTION_BYTES,
        )
        observed_bytes = max(observed_bytes, byte_count)
        if oversized:
            return observed_bytes, True
    return observed_bytes, False


def _normalized_contributions(value: str) -> list[str]:
    return [
        normalized
        for line in value.splitlines()
        if (normalized := _normalized_text(line))
    ]


def _normalized_public_bbox(
    value: Any,
) -> tuple[float, float, float, float, str] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        x = float(value["x"])
        y = float(value["y"])
        width = float(value.get("width", value.get("w")))
        height = float(value.get("height", value.get("h")))
        unit = str(value["unit"])
    except (KeyError, TypeError, ValueError):
        return None
    if (
        unit not in {"pt", "px"}
        or width < 0
        or height < 0
        or not all(math.isfinite(item) for item in (x, y, width, height))
    ):
        return None
    return x, y, width, height, unit


def _bbox_fully_inside(
    child: Any,
    owner: Any,
) -> bool:
    child_box = _normalized_public_bbox(child)
    owner_box = _normalized_public_bbox(owner)
    if child_box is None or owner_box is None:
        return False
    child_x, child_y, child_width, child_height, child_unit = child_box
    owner_x, owner_y, owner_width, owner_height, owner_unit = owner_box
    tolerance = (
        _PRIMARY_OCR_BBOX_TOLERANCE_PT
        if child_unit == owner_unit == "pt"
        else 0.0
    )
    return bool(
        child_unit == owner_unit
        and child_width > 0
        and child_height > 0
        and owner_width > 0
        and owner_height > 0
        and child_x >= owner_x - tolerance
        and child_y >= owner_y - tolerance
        and child_x + child_width <= owner_x + owner_width + tolerance
        and child_y + child_height <= owner_y + owner_height + tolerance
    )


def _bbox_strictly_inside(
    child: Any,
    owner: Any,
) -> bool:
    """Require exact same-unit containment for promoted native visual text."""

    child_box = _normalized_public_bbox(child)
    owner_box = _normalized_public_bbox(owner)
    if child_box is None or owner_box is None:
        return False
    child_x, child_y, child_width, child_height, child_unit = child_box
    owner_x, owner_y, owner_width, owner_height, owner_unit = owner_box
    return bool(
        child_unit == owner_unit
        and child_width > 0
        and child_height > 0
        and owner_width > 0
        and owner_height > 0
        and child_x >= owner_x
        and child_y >= owner_y
        and child_x + child_width <= owner_x + owner_width
        and child_y + child_height <= owner_y + owner_height
    )


def _bbox_reciprocal_overlap(first: Any, second: Any) -> float:
    first_box = _normalized_public_bbox(first)
    second_box = _normalized_public_bbox(second)
    if first_box is None or second_box is None:
        return 0.0
    first_x, first_y, first_width, first_height, first_unit = first_box
    second_x, second_y, second_width, second_height, second_unit = second_box
    if first_unit != second_unit:
        return 0.0
    left = max(first_x, second_x)
    top = max(first_y, second_y)
    right = min(first_x + first_width, second_x + second_width)
    bottom = min(first_y + first_height, second_y + second_height)
    intersection = max(right - left, 0.0) * max(bottom - top, 0.0)
    smaller = min(first_width * first_height, second_width * second_height)
    return intersection / smaller if smaller > 0 else 0.0


def _owned_visual_source_children_valid(
    source_meta: Mapping[str, Any],
    contained_items: list[Mapping[str, Any]],
    *,
    owner_bbox: Any,
    owner_public_id: Any,
    declared_contains_ids: Any,
    relationships: Any,
    occurrences: list[Mapping[str, Any]],
    lines: list[Mapping[str, Any]],
    occurrence_line_ids: set[str],
) -> bool:
    expected_source_meta_keys = {
        "method",
        "text_sha256",
        "occurrence_count",
        "promoted_primary",
        "page_index",
        "coordinate_unit",
        "source_sha256",
        "owned_child_ids",
        "owned_children",
        "source_line_ids",
        "source_lineage_sha256",
        "containment_tolerance_pt",
    }
    owned_child_ids = source_meta.get("owned_child_ids")
    owned_children = source_meta.get("owned_children")
    source_line_ids = source_meta.get("source_line_ids")
    source_sha256 = source_meta.get("source_sha256")
    source_lineage_sha256 = source_meta.get("source_lineage_sha256")
    tolerance = source_meta.get("containment_tolerance_pt")
    if (
        len(source_meta) != len(expected_source_meta_keys)
        or set(source_meta) != expected_source_meta_keys
        or source_meta.get("coordinate_unit") != "pt"
        or not isinstance(source_meta.get("page_index"), int)
        or isinstance(source_meta.get("page_index"), bool)
        or int(source_meta["page_index"]) < 1
        or not isinstance(source_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None
        or not isinstance(tolerance, (int, float))
        or isinstance(tolerance, bool)
        or not math.isfinite(float(tolerance))
        or not 0 <= float(tolerance) <= _PRIMARY_OCR_BBOX_TOLERANCE_PT
        or not isinstance(owned_child_ids, list)
        or not owned_child_ids
        or len(owned_child_ids) > _MAX_VISUAL_CHILD_REFERENCES
        or any(not isinstance(value, str) or not value for value in owned_child_ids)
        or len(set(owned_child_ids)) != len(owned_child_ids)
        or not isinstance(owned_children, list)
        or len(owned_children) != len(owned_child_ids)
        or not isinstance(source_line_ids, list)
        or len(source_line_ids) != len(owned_children)
        or any(not isinstance(value, str) or not value for value in source_line_ids)
        or len(set(source_line_ids)) != len(source_line_ids)
        or set(source_line_ids) != occurrence_line_ids
        or not isinstance(source_lineage_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", source_lineage_sha256) is None
        or not isinstance(owner_public_id, str)
        or not owner_public_id
        or _bounded_utf8_size(
            owner_public_id, _MAX_VISUAL_SOURCE_TEXT_BYTES
        )[1]
        or not isinstance(declared_contains_ids, list)
        or len(declared_contains_ids) != len(owned_child_ids)
        or any(
            not isinstance(value, str) or not value
            for value in declared_contains_ids
        )
        or len(set(declared_contains_ids)) != len(declared_contains_ids)
        or not isinstance(relationships, list)
        or len(relationships)
        > _MAX_VISUAL_CHILD_REFERENCES + _MAX_VISUAL_CAPTION_REFERENCES
        or any(not isinstance(value, Mapping) for value in relationships)
        or any(not isinstance(child, Mapping) for child in contained_items)
        or len(contained_items) != len(owned_child_ids)
    ):
        return False
    public_child_ids = [child.get("id") for child in contained_items]
    if (
        any(not isinstance(value, str) or not value for value in public_child_ids)
        or len(set(public_child_ids)) != len(public_child_ids)
        or set(public_child_ids) != set(declared_contains_ids)
        or any(
            _bounded_utf8_size(value, _MAX_VISUAL_SOURCE_TEXT_BYTES)[1]
            for value in public_child_ids
        )
    ):
        return False
    owner_contains = [
        relationship
        for relationship in relationships
        if relationship.get("type") == RelationshipType.CONTAINS.value
        and relationship.get("source_id") == owner_public_id
    ]
    owner_contains_targets = [
        relationship.get("target_id") for relationship in owner_contains
    ]
    owner_contains_relationship_ids = [
        relationship.get("id") for relationship in owner_contains
    ]
    if (
        len(owner_contains) != len(contained_items)
        or any(not isinstance(relationship, Mapping) for relationship in relationships)
        or any(
            not isinstance(value, str)
            or not value
            or _bounded_utf8_size(value, _MAX_VISUAL_SOURCE_TEXT_BYTES)[1]
            for value in owner_contains_targets
        )
        or len(set(owner_contains_targets)) != len(owner_contains_targets)
        or set(owner_contains_targets) != set(public_child_ids)
        or any(
            not isinstance(value, str)
            or not value
            or _bounded_utf8_size(value, _MAX_VISUAL_SOURCE_TEXT_BYTES)[1]
            for value in owner_contains_relationship_ids
        )
        or len(set(owner_contains_relationship_ids))
        != len(owner_contains_relationship_ids)
    ):
        return False
    for relationship in relationships:
        if (
            relationship.get("type") == RelationshipType.CONTAINS.value
            and relationship.get("source_id") == owner_public_id
            and (
            len(relationship) != 4
            or set(relationship)
            != {"id", "type", "source_id", "target_id"}
            )
        ):
            return False
    try:
        from app.services.visual_source_text import (
            owned_visual_source_lineage_sha256,
        )

        expected_lineage_sha256 = owned_visual_source_lineage_sha256(
            source_sha256=source_sha256,
            page_index=source_meta.get("page_index"),
            coordinate_unit=source_meta.get("coordinate_unit"),
            owned_child_ids=owned_child_ids,
            owned_children=owned_children,
            source_line_ids=source_line_ids,
            occurrences=occurrences,
            lines=lines,
        )
    except (MemoryError, TypeError, ValueError):
        return False
    if (
        expected_lineage_sha256 is None
        or source_lineage_sha256 != expected_lineage_sha256
    ):
        return False
    unmatched = list(contained_items)
    proof_child_ids: set[str] = set()
    proof_line_ids: set[str] = set()
    for proof in owned_children:
        if not isinstance(proof, Mapping):
            return False
        proof_id = proof.get("id")
        proof_line_id = proof.get("source_line_id")
        proof_box = proof.get("bbox")
        normalized_hash = proof.get("normalized_text_sha256")
        if (
            not isinstance(proof_id, str)
            or proof_id not in owned_child_ids
            or proof_id in proof_child_ids
            or not isinstance(proof_line_id, str)
            or proof_line_id not in occurrence_line_ids
            or proof_line_id in proof_line_ids
            or not isinstance(normalized_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", normalized_hash) is None
            or not _bbox_fully_inside(proof_box, owner_bbox)
        ):
            return False
        proof_child_ids.add(proof_id)
        proof_line_ids.add(proof_line_id)
        matching_indexes: list[int] = []
        for index, child in enumerate(unmatched):
            value = child.get("value")
            child_id = child.get("id")
            relationship_id = child.get("relationship_id")
            if (
                not isinstance(value, str)
                or _bounded_utf8_size(value, _MAX_VISUAL_SOURCE_TEXT_BYTES)[1]
                or not isinstance(child_id, str)
                or _bounded_utf8_size(
                    child_id, _MAX_VISUAL_SOURCE_TEXT_BYTES
                )[1]
                or not isinstance(relationship_id, str)
                or _bounded_utf8_size(
                    relationship_id, _MAX_VISUAL_SOURCE_TEXT_BYTES
                )[1]
            ):
                continue
            normalized = re.sub(
                r"\s+",
                "",
                unicodedata.normalize("NFC", str(value or "")).casefold(),
            )
            matching_relationships = [
                relationship
                for relationship in relationships
                if relationship.get("id") == relationship_id
                and relationship.get("type") == RelationshipType.CONTAINS.value
                and relationship.get("source_id") == owner_public_id
                and relationship.get("target_id") == child_id
            ]
            if (
                normalized
                and hashlib.sha256(normalized.encode("utf-8")).hexdigest()
                == normalized_hash
                and _bbox_fully_inside(child.get("bbox"), owner_bbox)
                and _bbox_reciprocal_overlap(child.get("bbox"), proof_box)
                >= 0.75
                and str(child.get("type") or "").casefold() == "visual_text"
                and str(child.get("content_type") or "").casefold()
                == "visual_text"
                and type(child.get("page_index")) is int
                and child.get("page_index") == source_meta.get("page_index")
                and child.get("md") == value
                and str(child.get("source") or "").casefold() == "native"
                and child.get("presentation_role") == "subordinate"
                and child.get("contained_by") == owner_public_id
                and relationship_id
                and child.get("relationship_type")
                == RelationshipType.CONTAINS.value
                and child.get("relationship_basis") == "graph_and_geometry"
                and len(matching_relationships) == 1
            ):
                matching_indexes.append(index)
        if len(matching_indexes) != 1:
            return False
        unmatched.pop(matching_indexes[0])
    return bool(
        proof_child_ids == set(owned_child_ids)
        and proof_line_ids == set(source_line_ids)
        and not unmatched
    )


def _bind_compact_visual_public_child_ids(
    owner_legacy: MutableMapping[str, Any],
    contained_items: list[Mapping[str, Any]],
) -> bool:
    """Bind source contributor proofs to the exact projected child IDs."""

    raw_meta = owner_legacy.get("meta")
    compact = (
        raw_meta.get("compact_visual_ocr_primary")
        if isinstance(raw_meta, MutableMapping)
        else None
    )
    if not isinstance(compact, MutableMapping):
        return False
    source_child_ids = compact.get("native_overlay_source_child_ids")
    source_line_ids = compact.get("native_overlay_source_line_ids")
    child_proofs = compact.get("native_overlay_children")
    if (
        not isinstance(source_child_ids, list)
        or not source_child_ids
        or any(not isinstance(value, str) or not value for value in source_child_ids)
        or len(set(source_child_ids)) != len(source_child_ids)
        or not isinstance(source_line_ids, list)
        or len(source_line_ids) != len(source_child_ids)
        or any(not isinstance(value, str) or not value for value in source_line_ids)
        or len(set(source_line_ids)) != len(source_line_ids)
        or not isinstance(child_proofs, list)
        or len(child_proofs) != len(source_child_ids)
        or len(contained_items) != len(child_proofs)
        or any(not isinstance(value, Mapping) for value in contained_items)
    ):
        return False
    unmatched = list(contained_items)
    public_child_ids: list[str] = []
    proof_source_child_ids: set[str] = set()
    proof_source_line_ids: set[str] = set()
    for proof in child_proofs:
        if not isinstance(proof, Mapping):
            return False
        source_child_id = proof.get("source_child_id")
        source_line_id = proof.get("source_line_id")
        normalized_hash = proof.get("normalized_text_sha256")
        proof_box = proof.get("bbox")
        if (
            not isinstance(source_child_id, str)
            or source_child_id not in source_child_ids
            or source_child_id in proof_source_child_ids
            or not isinstance(source_line_id, str)
            or source_line_id not in source_line_ids
            or source_line_id in proof_source_line_ids
            or not isinstance(normalized_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", normalized_hash) is None
            or _normalized_public_bbox(proof_box) is None
        ):
            return False
        matches: list[int] = []
        for index, child in enumerate(unmatched):
            child_value = child.get("value")
            normalized = re.sub(
                r"\s+",
                "",
                unicodedata.normalize("NFC", str(child_value or "")).casefold(),
            )
            if (
                normalized
                and hashlib.sha256(normalized.encode("utf-8")).hexdigest()
                == normalized_hash
                and _bbox_reciprocal_overlap(child.get("bbox"), proof_box)
                >= 0.75
                and child.get("relationship_type")
                == RelationshipType.CONTAINS.value
                and isinstance(child.get("id"), str)
                and child.get("id")
            ):
                matches.append(index)
        if len(matches) != 1:
            return False
        matched = unmatched.pop(matches[0])
        public_child_ids.append(str(matched["id"]))
        proof_source_child_ids.add(source_child_id)
        proof_source_line_ids.add(source_line_id)
    if (
        proof_source_child_ids != set(source_child_ids)
        or proof_source_line_ids != set(source_line_ids)
        or len(set(public_child_ids)) != len(public_child_ids)
    ):
        return False
    compact["native_overlay_child_ids"] = public_child_ids
    return True


def _grounded_primary_visual_source_text(
    owner_legacy: Mapping[str, Any],
    contained_items: list[Mapping[str, Any]] | None = None,
) -> tuple[str, str | None]:
    """Admit exact PDF-layer text only for an explicitly routed P05 visual."""

    source_text = owner_legacy.get("visual_source_text")
    occurrences = owner_legacy.get("visual_source_text_occurrences")
    lines = owner_legacy.get("visual_source_text_lines")
    meta = owner_legacy.get("meta")
    source_meta = (
        meta.get("phase05_visual_source_text")
        if isinstance(meta, Mapping)
        else None
    )
    if (
        not isinstance(source_text, str)
        or not isinstance(occurrences, list)
        or not occurrences
        or len(occurrences) > _MAX_VISUAL_SOURCE_TEXT_OCCURRENCES
        or not isinstance(lines, list)
        or not lines
        or len(lines) > _MAX_VISUAL_SOURCE_TEXT_LINES
        or not isinstance(source_meta, Mapping)
    ):
        return "", "visual_source_payload_incomplete"
    _text_bytes, text_overflow = _bounded_utf8_size(
        source_text,
        _MAX_VISUAL_SOURCE_TEXT_BYTES,
    )
    if text_overflow:
        return "", "visual_source_text_byte_limit"
    if not source_text.strip():
        return "", "visual_source_payload_incomplete"
    owner_type = str(owner_legacy.get("type") or "").casefold()
    method = source_meta.get("method")
    owned_child_method = method == "pdf_source_line_owned_by_visual_child"
    if owned_child_method:
        if (
            owner_type != "image"
            or str(owner_legacy.get("content_type") or "").casefold()
            != "image"
            or str(owner_legacy.get("region_role") or "").casefold()
            != "content_region"
            or not isinstance(contained_items, list)
        ):
            return "", "visual_source_owner_not_routed"
    else:
        structure = owner_legacy.get("visual_structure")
        region = structure.get("region") if isinstance(structure, Mapping) else None
        if (
            method != "pdf_text_layer_inside_visual_bbox"
            or owner_type not in {"chart", "diagram"}
            or not isinstance(region, Mapping)
            or str(region.get("kind") or "").casefold() != owner_type
        ):
            return "", "visual_source_owner_not_routed"
    if (
        source_meta.get("promoted_primary") is not True
        or source_meta.get("occurrence_count") != len(occurrences)
        or source_meta.get("text_sha256")
        != hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    ):
        return "", "visual_source_metadata_mismatch"

    owner_bbox = owner_legacy.get("bbox")
    occurrence_ids: set[str] = set()
    occurrence_line_ids: set[str] = set()
    occurrence_by_id: dict[str, Mapping[str, Any]] = {}
    source_character_ids: set[str] = set()
    occurrence_text_bytes = 0
    for occurrence in occurrences:
        if not isinstance(occurrence, Mapping):
            return "", "visual_source_occurrence_invalid"
        occurrence_id = occurrence.get("occurrence_id")
        occurrence_text = occurrence.get("text")
        if not isinstance(occurrence_text, str):
            return "", "visual_source_occurrence_invalid"
        text_bytes, text_overflow = _bounded_utf8_size(
            occurrence_text,
            _MAX_VISUAL_SOURCE_TEXT_BYTES - min(
                occurrence_text_bytes,
                _MAX_VISUAL_SOURCE_TEXT_BYTES,
            ),
        )
        occurrence_text_bytes += text_bytes
        if text_overflow or occurrence_text_bytes > _MAX_VISUAL_SOURCE_TEXT_BYTES:
            return "", "visual_source_occurrence_invalid"
        if (
            not isinstance(occurrence_id, str)
            or not occurrence_id
            or occurrence_id in occurrence_ids
            or occurrence.get("id") != occurrence_id
            or occurrence.get("accepted") is not True
            or occurrence.get("selected") is not True
            or str(occurrence.get("source") or "").casefold() != "native"
            or not occurrence_text.strip()
            or not (
                _bbox_fully_inside(occurrence.get("bbox"), owner_bbox)
                if owned_child_method
                else _bbox_strictly_inside(occurrence.get("bbox"), owner_bbox)
            )
        ):
            return "", "visual_source_occurrence_invalid"
        occurrence_ids.add(occurrence_id)
        occurrence_by_id[occurrence_id] = occurrence
        if owned_child_method:
            source_line_id = occurrence.get("source_line_id")
            character_ids = occurrence.get("source_character_ids")
            if (
                not isinstance(source_line_id, str)
                or not source_line_id
                or source_line_id in occurrence_line_ids
                or not isinstance(character_ids, list)
                or not character_ids
                or len(character_ids) > _MAX_VISUAL_SOURCE_TEXT_BYTES
                or any(
                    not isinstance(value, str)
                    or not value
                    or value in source_character_ids
                    for value in character_ids
                )
                or len(set(character_ids)) != len(character_ids)
            ):
                return "", "visual_source_occurrence_invalid"
            occurrence_line_ids.add(source_line_id)
            source_character_ids.update(character_ids)

    referenced_ids: list[str] = []
    line_text: list[str] = []
    line_source_ids: set[str] = set()
    line_text_bytes = 0
    for line in lines:
        raw_line_text = line.get("text") if isinstance(line, Mapping) else None
        if not isinstance(raw_line_text, str):
            return "", "visual_source_line_invalid"
        text_bytes, text_overflow = _bounded_utf8_size(
            raw_line_text,
            _MAX_VISUAL_SOURCE_TEXT_BYTES - min(
                line_text_bytes,
                _MAX_VISUAL_SOURCE_TEXT_BYTES,
            ),
        )
        line_text_bytes += text_bytes
        if text_overflow or line_text_bytes > _MAX_VISUAL_SOURCE_TEXT_BYTES:
            return "", "visual_source_line_invalid"
        if (
            not isinstance(line, Mapping)
            or not raw_line_text.strip()
            or not (
                _bbox_fully_inside(line.get("bbox"), owner_bbox)
                if owned_child_method
                else _bbox_strictly_inside(line.get("bbox"), owner_bbox)
            )
            or not isinstance(line.get("source_token_ids"), list)
            or not line.get("source_token_ids")
            or any(
                not isinstance(value, str) or value not in occurrence_ids
                for value in line.get("source_token_ids") or []
            )
        ):
            return "", "visual_source_line_invalid"
        if owned_child_method:
            line_source_id = line.get("source_line_id")
            source_token_ids = line.get("source_token_ids")
            source_occurrence = (
                occurrence_by_id.get(source_token_ids[0])
                if isinstance(source_token_ids, list)
                and len(source_token_ids) == 1
                else None
            )
            if (
                not isinstance(line_source_id, str)
                or not line_source_id
                or line_source_id not in occurrence_line_ids
                or line_source_id in line_source_ids
                or not isinstance(source_occurrence, Mapping)
                or source_occurrence.get("source_line_id") != line_source_id
                or source_occurrence.get("text") != line.get("text")
                or _normalized_public_bbox(source_occurrence.get("bbox"))
                != _normalized_public_bbox(line.get("bbox"))
            ):
                return "", "visual_source_line_invalid"
            line_source_ids.add(line_source_id)
        referenced_ids.extend(line["source_token_ids"])
        line_text.append(line["text"])
    if (
        len(referenced_ids) != len(occurrence_ids)
        or len(set(referenced_ids)) != len(referenced_ids)
        or set(referenced_ids) != occurrence_ids
        or "\n".join(line_text).strip() != source_text.strip()
        or (
            owned_child_method
            and (
                line_source_ids != occurrence_line_ids
                or len(lines) != len(occurrence_line_ids)
            )
        )
    ):
        return "", "visual_source_lineage_mismatch"
    if owned_child_method and not _owned_visual_source_children_valid(
        source_meta,
        contained_items or [],
        owner_bbox=owner_bbox,
        owner_public_id=owner_legacy.get("id"),
        declared_contains_ids=owner_legacy.get("contains_ids"),
        relationships=owner_legacy.get("relationships"),
        occurrences=occurrences,
        lines=lines,
        occurrence_line_ids=occurrence_line_ids,
    ):
        return "", "visual_source_child_ownership_mismatch"
    return source_text.strip(), None


def _authoritative_structured_visual_output(
    owner_legacy: Mapping[str, Any],
) -> str:
    """Retain an already sealed Phase-05 visual serialization on re-entry.

    Layout relationships may add caption/containment descriptors after visual
    semantics has committed. They must not replace an independently validated
    chart or diagram serialization with its predecessor OCR. Exact public
    value/Markdown equality is required before replay, and raster diagrams are
    revalidated from their complete raw/evidence custody rather than trusted by
    status alone.
    """

    owner_type = str(owner_legacy.get("type") or "").casefold()
    if owner_type not in {"chart", "diagram"}:
        return ""
    raw_structure = owner_legacy.get("visual_structure")
    model_dump = getattr(raw_structure, "model_dump", None)
    if callable(model_dump):
        raw_structure = model_dump(mode="json")
    if not isinstance(raw_structure, Mapping):
        return ""
    try:
        from app.services.visual_contracts import VisualStructure

        structure = VisualStructure.model_validate(raw_structure, strict=True)
        serialization = structure.serialization
        expected_status = (
            "structured_chart" if owner_type == "chart" else "diagram_topology"
        )
        if (
            structure.region.kind != owner_type
            or structure.fallback.active
            or serialization is None
            or serialization.status != expected_status
            or not serialization.markdown
            or owner_legacy.get("value") != serialization.markdown
            or owner_legacy.get("md") != serialization.markdown
            or (
                isinstance(owner_legacy.get("caption"), str)
                and str(owner_legacy.get("caption") or "").strip()
                and serialization.caption_occurrences != 1
            )
        ):
            return ""
        if owner_type == "diagram":
            from app.services.visual_diagram_topology import (
                validate_raster_diagram_item_contract,
            )

            validate_raster_diagram_item_contract(owner_legacy, structure)
    except (MemoryError, OverflowError, RecursionError, TypeError, ValueError):
        return ""
    return serialization.markdown


class _StructuredVisualTransitionError(ValueError):
    """An authoritative visual cannot be rebound to layout relationships."""


def _externalize_authoritative_structured_caption(
    owner_legacy: MutableMapping[str, Any],
    accepted_captions: list[Mapping[str, Any]],
) -> None:
    """Remove one exactly replayable structured caption before projection.

    Caption relationships render their public caption separately. When an
    authoritative visual serialization already owns that same caption, update
    only its sealed serialization fields after proving the exact escaped prefix.
    Any ambiguity raises so the caller restores the complete layout predecessor.
    """

    raw_structure = owner_legacy.get("visual_structure")
    if not isinstance(raw_structure, Mapping):
        raise _StructuredVisualTransitionError
    from app.services.visual_contracts import (
        VisualSerialization,
        VisualStructure,
    )

    structure = VisualStructure.model_validate(raw_structure, strict=True)
    serialization = structure.serialization
    if serialization is None:
        raise _StructuredVisualTransitionError
    if serialization.caption_occurrences == 0:
        return
    if serialization.caption_occurrences != 1 or not accepted_captions:
        raise _StructuredVisualTransitionError

    candidates: list[str] = []
    raw_caption = owner_legacy.get("caption")
    if isinstance(raw_caption, str) and raw_caption.strip():
        candidates.append(raw_caption.strip())
    candidates.extend(
        label.text.strip()
        for label in structure.labels
        if label.role == "caption" and label.text.strip()
    )
    accepted_values = {
        str(caption.get("value"))
        for caption in accepted_captions
        if isinstance(caption.get("value"), str)
        and caption.get("value") == caption.get("md")
    }
    prefixes = {
        (
            candidate.replace("\\", "\\\\")
            .replace("|", "\\|")
            .replace("\r\n", "<br>")
            .replace("\r", "<br>")
            .replace("\n", "<br>")
            .strip()
            + "\n\n"
        )
        for candidate in candidates
        if candidate in accepted_values
    }
    matching = {
        prefix
        for prefix in prefixes
        if serialization.markdown.startswith(prefix)
    }
    if len(matching) != 1:
        raise _StructuredVisualTransitionError
    body = serialization.markdown[len(next(iter(matching))) :]
    if not body:
        raise _StructuredVisualTransitionError
    rebound = structure.model_copy(
        update={
            "serialization": VisualSerialization(
                status=serialization.status,
                markdown=body,
                caption_occurrences=0,
                row_count=serialization.row_count,
            )
        }
    )
    owner_legacy["visual_structure"] = rebound.model_dump(
        mode="json", exclude_none=True
    )
    owner_legacy["value"] = body
    owner_legacy["md"] = body


def _grounded_primary_ocr(
    owner_legacy: Mapping[str, Any],
) -> tuple[str, str | None, int, int]:
    """Admit OCR only when every retained contribution has accepted geometry."""

    if owner_legacy.get("include_ocr_in_primary") is not True:
        return "", None, 0, 0
    ocr_text = str(owner_legacy.get("ocr_text") or "").strip()
    contributions = _normalized_contributions(ocr_text)
    if not contributions:
        return "", None, 0, 0
    diagnostics = owner_legacy.get("items")
    if not isinstance(diagnostics, list):
        return "", "accepted_ocr_diagnostics_missing", len(contributions), 0

    available: Counter[str] = Counter()
    owner_bbox = owner_legacy.get("bbox")
    for diagnostic in diagnostics[:4096]:
        if (
            not isinstance(diagnostic, Mapping)
            or diagnostic.get("accepted") is not True
            or str(diagnostic.get("source") or "").casefold() != "ocr"
            or not _bbox_fully_inside(diagnostic.get("bbox"), owner_bbox)
        ):
            continue
        diagnostic_value = diagnostic.get("text")
        if not isinstance(diagnostic_value, str):
            diagnostic_value = diagnostic.get("value")
        if not isinstance(diagnostic_value, str):
            continue
        available.update(_normalized_contributions(diagnostic_value))

    backed_count = 0
    for contribution in contributions:
        if available[contribution] <= 0:
            return (
                "",
                "ocr_text_not_fully_grounded",
                len(contributions),
                backed_count,
            )
        available[contribution] -= 1
        backed_count += 1
    return ocr_text, None, len(contributions), backed_count


def _grounded_proven_visual_owner_output(
    owner_legacy: Mapping[str, Any],
    *,
    source_document_identity: str | None = None,
    page_index: int | None = None,
) -> tuple[str, str | None, str | None]:
    """Return an exact image-owner value only after its proof revalidates."""

    contained_items = owner_legacy.get("contained_items")
    source_text, source_rejection = _grounded_primary_visual_source_text(
        owner_legacy,
        contained_items if isinstance(contained_items, list) else None,
    )
    if source_text:
        raw_meta = owner_legacy.get("meta")
        source_meta = (
            raw_meta.get("phase05_visual_source_text")
            if isinstance(raw_meta, Mapping)
            else None
        )
        if (
            isinstance(source_document_identity, str)
            and re.fullmatch(r"[0-9a-f]{64}", source_document_identity) is not None
            and isinstance(source_meta, Mapping)
            and source_meta.get("source_sha256") == source_document_identity
            and type(page_index) is int
            and page_index >= 1
            and source_meta.get("page_index") == page_index
            and owner_legacy.get("value") == source_text
            and owner_legacy.get("md") == source_text
            and str(owner_legacy.get("source") or "").casefold() == "native"
        ):
            return source_text, "native", None
        return "", None, "visual_source_owner_projection_mismatch"

    raw_meta = owner_legacy.get("meta")
    compact_meta = (
        raw_meta.get("compact_visual_ocr_primary")
        if isinstance(raw_meta, Mapping)
        else None
    )
    if not isinstance(compact_meta, Mapping):
        return "", None, source_rejection
    primary_ocr, ocr_rejection, _count, _backed = _grounded_primary_ocr(
        owner_legacy
    )
    if not primary_ocr:
        return "", None, ocr_rejection or "compact_visual_ocr_not_grounded"
    try:
        from app.services.visual_source_text import (
            revalidate_compact_visual_ocr_primary_evidence,
        )

        compact_valid = revalidate_compact_visual_ocr_primary_evidence(
            owner_legacy,
            primary_ocr,
            source_document_identity=source_document_identity,
            page_index=page_index,
        )
    except (MemoryError, TypeError, ValueError):
        compact_valid = False
    if not compact_valid:
        return "", None, "compact_visual_ocr_proof_mismatch"
    if (
        owner_legacy.get("value") != primary_ocr
        or owner_legacy.get("md") != primary_ocr
        or str(owner_legacy.get("source") or "").casefold() != "ocr"
    ):
        return "", None, "compact_visual_owner_projection_mismatch"
    return primary_ocr, "ocr", None


def _independent_visual_native_child_outputs(
    owner_legacy: Mapping[str, Any],
    *,
    source_document_identity: str,
    page_index: int,
) -> dict[str, Any]:
    """Retain attributable native children when an owner proof fails closed.

    A complete compact/native proof still owns its exact overlay contributors.
    Any additional, independently declared native child remains presentable so
    ambiguity cannot silently erase source content.  This helper never promotes
    a partial owner proof.
    """

    owner_id = owner_legacy.get("id")
    owner_bbox = owner_legacy.get("bbox")
    contained_items = owner_legacy.get("contained_items")
    contains_ids = owner_legacy.get("contains_ids")
    relationships = owner_legacy.get("relationships")
    empty_result: dict[str, Any] = {
        "owner_output": "",
        "owner_source": None,
        "children": [],
    }
    if (
        str(owner_legacy.get("type") or "").casefold() != "image"
        or str(owner_legacy.get("content_type") or "").casefold()
        != "image"
        or str(owner_legacy.get("region_role") or "").casefold()
        != "content_region"
        or not isinstance(owner_id, str)
        or not owner_id
        or _bounded_utf8_size(
            owner_id, _MAX_VISUAL_SOURCE_TEXT_BYTES
        )[1]
        or type(page_index) is not int
        or page_index < 1
        or not isinstance(source_document_identity, str)
        or re.fullmatch(r"[0-9a-f]{64}", source_document_identity) is None
        or not isinstance(contained_items, list)
        or not contained_items
        or len(contained_items) > _MAX_VISUAL_CHILD_REFERENCES
        or not isinstance(contains_ids, list)
        or len(contains_ids) > _MAX_VISUAL_CHILD_REFERENCES
        or not isinstance(relationships, list)
        or len(relationships)
        > _MAX_VISUAL_CHILD_REFERENCES + _MAX_VISUAL_CAPTION_REFERENCES
    ):
        return empty_result
    bounded_contains_ids = [
        value
        for value in contains_ids
        if isinstance(value, str)
        and value
        and not _bounded_utf8_size(
            value, _MAX_VISUAL_SOURCE_TEXT_BYTES
        )[1]
    ]
    contains_counts = Counter(bounded_contains_ids)
    public_ids = [
        child.get("id") if isinstance(child, Mapping) else None
        for child in contained_items
    ]
    bounded_public_ids = [
        value
        for value in public_ids
        if isinstance(value, str)
        and value
        and not _bounded_utf8_size(
            value, _MAX_VISUAL_SOURCE_TEXT_BYTES
        )[1]
    ]
    public_counts = Counter(bounded_public_ids)

    owner_contains = [
        relationship
        for relationship in relationships
        if isinstance(relationship, Mapping)
        if relationship.get("type") == RelationshipType.CONTAINS.value
        and relationship.get("source_id") == owner_id
    ]
    owner_contains_targets = [
        relationship.get("target_id") for relationship in owner_contains
    ]
    owner_contains_relationship_ids = [
        relationship.get("id") for relationship in owner_contains
    ]
    graph_is_globally_closed = bool(
        len(owner_contains) != len(contained_items)
        or len(bounded_contains_ids) != len(contains_ids)
        or len(bounded_public_ids) != len(contained_items)
        or len(set(bounded_contains_ids)) != len(bounded_contains_ids)
        or len(set(bounded_public_ids)) != len(bounded_public_ids)
        or bounded_public_ids != bounded_contains_ids
        or any(
            len(relationship) != 4
            or set(relationship)
            != {"id", "type", "source_id", "target_id"}
            for relationship in owner_contains
        )
        or any(
            not isinstance(value, str)
            or not value
            or _bounded_utf8_size(value, _MAX_VISUAL_SOURCE_TEXT_BYTES)[1]
            for value in owner_contains_targets
        )
        or len(set(owner_contains_targets)) != len(owner_contains_targets)
        or set(owner_contains_targets) != set(bounded_public_ids)
        or any(
            not isinstance(value, str)
            or not value
            or _bounded_utf8_size(value, _MAX_VISUAL_SOURCE_TEXT_BYTES)[1]
            for value in owner_contains_relationship_ids
        )
        or len(set(owner_contains_relationship_ids))
        != len(owner_contains_relationship_ids)
    ) is False

    valid_children: list[Mapping[str, Any]] = []
    for child in contained_items:
        if not isinstance(child, Mapping):
            graph_is_globally_closed = False
            continue
        child_id = child.get("id")
        relationship_id = child.get("relationship_id")
        value = child.get("value")
        matching_relationships = [
            relationship
            for relationship in owner_contains
            if len(relationship) == 4
            and set(relationship)
            == {"id", "type", "source_id", "target_id"}
            if relationship.get("id") == relationship_id
            and relationship.get("target_id") == child_id
        ]
        if (
            not isinstance(child_id, str)
            or _bounded_utf8_size(
                child_id, _MAX_VISUAL_SOURCE_TEXT_BYTES
            )[1]
            or public_counts.get(child_id) != 1
            or contains_counts.get(child_id) != 1
            or not isinstance(relationship_id, str)
            or not relationship_id
            or _bounded_utf8_size(
                relationship_id, _MAX_VISUAL_SOURCE_TEXT_BYTES
            )[1]
            or not isinstance(value, str)
            or not value.strip()
            or _bounded_utf8_size(value, _MAX_VISUAL_SOURCE_TEXT_BYTES)[1]
            or str(child.get("type") or "").casefold() != "visual_text"
            or str(child.get("content_type") or "").casefold()
            != "visual_text"
            or type(child.get("page_index")) is not int
            or child.get("page_index") != page_index
            or child.get("md") != value
            or str(child.get("source") or "").casefold() != "native"
            or child.get("presentation_role") != "subordinate"
            or child.get("contained_by") != owner_id
            or child.get("relationship_type")
            != RelationshipType.CONTAINS.value
            or child.get("relationship_basis") != "graph_and_geometry"
            or not _bbox_fully_inside(child.get("bbox"), owner_bbox)
            or len(matching_relationships) != 1
        ):
            graph_is_globally_closed = False
            continue
        valid_children.append(child)

    if not valid_children:
        return empty_result
    if len(valid_children) != len(contained_items):
        graph_is_globally_closed = False

    proof_covered_ids: set[str] = set()
    raw_meta = owner_legacy.get("meta")
    source_meta = (
        raw_meta.get("phase05_visual_source_text")
        if isinstance(raw_meta, Mapping)
        else None
    )
    compact_meta = (
        raw_meta.get("compact_visual_ocr_primary")
        if isinstance(raw_meta, Mapping)
        else None
    )

    candidate_proof_ids: list[str] = []
    if (
        graph_is_globally_closed
        and isinstance(source_meta, Mapping)
        and not isinstance(compact_meta, Mapping)
    ):
        child_proofs = source_meta.get("owned_children")
        if (
            isinstance(child_proofs, list)
            and child_proofs
            and len(child_proofs) <= _MAX_VISUAL_CHILD_REFERENCES
            and all(isinstance(proof, Mapping) for proof in child_proofs)
        ):
            unmatched = list(valid_children)
            for proof in child_proofs:
                normalized_hash = proof.get("normalized_text_sha256")
                proof_box = proof.get("bbox")
                matches = []
                for index, child in enumerate(unmatched):
                    value = child.get("value")
                    if not isinstance(value, str):
                        continue
                    normalized = re.sub(
                        r"\s+",
                        "",
                        unicodedata.normalize("NFC", value).casefold(),
                    )
                    if (
                        isinstance(normalized_hash, str)
                        and hashlib.sha256(normalized.encode("utf-8")).hexdigest()
                        == normalized_hash
                        and _bbox_reciprocal_overlap(child.get("bbox"), proof_box)
                        >= 0.75
                    ):
                        matches.append(index)
                if len(matches) != 1:
                    candidate_proof_ids = []
                    break
                matched = unmatched.pop(matches[0])
                candidate_proof_ids.append(str(matched["id"]))
    elif (
        graph_is_globally_closed
        and isinstance(compact_meta, Mapping)
        and not isinstance(source_meta, Mapping)
    ):
        raw_ids = compact_meta.get("native_overlay_child_ids")
        if (
            isinstance(raw_ids, list)
            and raw_ids
            and len(raw_ids) <= _MAX_VISUAL_CHILD_REFERENCES
            and all(isinstance(value, str) and value for value in raw_ids)
            and all(
                not _bounded_utf8_size(
                    value, _MAX_VISUAL_SOURCE_TEXT_BYTES
                )[1]
                for value in raw_ids
            )
            and len(set(raw_ids)) == len(raw_ids)
            and set(raw_ids) <= set(public_ids)
        ):
            candidate_proof_ids = list(raw_ids)

    filtered_owner_output = ""
    filtered_owner_source: str | None = None
    if candidate_proof_ids:
        candidate_id_set = set(candidate_proof_ids)
        proof_children = [
            child for child in valid_children if child.get("id") in candidate_id_set
        ]
        proof_relationships = [
            relationship
            for relationship in relationships
            if isinstance(relationship, Mapping)
            and (
            not (
                relationship.get("type") == RelationshipType.CONTAINS.value
                and relationship.get("source_id") == owner_id
            )
            or relationship.get("target_id") in candidate_id_set
            )
        ]
        proof_owner = dict(owner_legacy)
        proof_owner["contained_items"] = proof_children
        proof_owner["contains_ids"] = [
            str(child["id"]) for child in proof_children
        ]
        proof_owner["relationships"] = proof_relationships
        proof_value, proof_source, _proof_reason = (
            _grounded_proven_visual_owner_output(
                proof_owner,
                source_document_identity=source_document_identity,
                page_index=page_index,
            )
        )
        if proof_value:
            proof_covered_ids = candidate_id_set
            filtered_owner_output = proof_value
            filtered_owner_source = proof_source

    return {
        "owner_output": filtered_owner_output,
        "owner_source": filtered_owner_source,
        "children": [
            {
                "id": str(child["id"]),
                "value": str(child["value"]),
                "relationship_id": str(child["relationship_id"]),
            }
            for child in valid_children
            if child.get("id") not in proof_covered_ids
        ],
    }


def _contained_item_preflight_size(
    *,
    owner_public_id: str,
    relationships: list[RelationshipRecord],
    elements: Mapping[str, ElementRecord],
    evidence: Mapping[str, Any],
) -> tuple[int, bool]:
    """Conservatively stream the prospective nested-child payload size."""

    probes: list[Mapping[str, Any]] = []
    for relationship in relationships:
        child = elements[relationship.target_id]
        child_value = _raw_source_value_view(child, evidence)
        legacy = child.properties.get("legacy_item")
        extras = (
            {
                key: value
                for key, value in legacy.items()
                if key
                not in {
                    "id",
                    "type",
                    "value",
                    "md",
                    "bbox",
                    "source",
                    "confidence",
                    "presentation_role",
                    "contained_by",
                    "relationship_id",
                    "relationship_type",
                    "relationship_basis",
                }
            }
            if isinstance(legacy, Mapping)
            else {}
        )
        public_child_id = str(
            legacy.get("id")
            if isinstance(legacy, Mapping) and legacy.get("id")
            else child.id
        )
        text = child_value if isinstance(child_value, str) else ""
        markdown = (
            child.markdown
            if isinstance(child.markdown, str)
            else text
        )
        probes.append(
            {
                **extras,
                "id": public_child_id,
                "type": "visual_text",
                "value": text,
                "md": markdown,
                # This intentionally exceeds the maximum serialized footprint
                # of the fixed five-field public bbox produced below.
                "bbox_reserve": (
                    "x" * _CONTAINED_ITEM_BBOX_RESERVE_BYTES
                ),
                "source": "derived",
                "confidence": None,
                "presentation_role": "subordinate",
                "contained_by": owner_public_id,
                "relationship_id": "layout-rel-" + ("0" * 20),
                "relationship_type": RelationshipType.CONTAINS.value,
                "relationship_basis": "graph_and_geometry",
            }
        )
    return _bounded_json_size(probes, _MAX_CONTAINED_ITEMS_BYTES)


def _raw_source_name(
    element: ElementRecord,
    evidence: Mapping[str, Any],
) -> str | None:
    raw_records = _raw_source_evidence(element, evidence)
    if not raw_records:
        return _evidence_source(element, evidence)
    methods = {record.method for record in raw_records}
    if len(methods) > 1:
        return "mixed"
    method = next(iter(methods))
    if method is EvidenceMethod.OCR:
        return "ocr"
    if method in {
        EvidenceMethod.NATIVE,
        EvidenceMethod.VECTOR,
        EvidenceMethod.EMBEDDED,
        EvidenceMethod.RECOVERED,
    }:
        return "native"
    return "derived"


def _raw_source_confidence(
    element: ElementRecord,
    evidence: Mapping[str, Any],
) -> float | None:
    raw_records = _raw_source_evidence(element, evidence)
    if not raw_records:
        return _evidence_confidence(element, evidence)
    scores = [record.confidence.score for record in raw_records]
    if not scores or any(score is None for score in scores):
        return None
    return min(float(score) for score in scores if score is not None)


def _relationship_order_key(
    relationship: RelationshipRecord,
    caption: ElementRecord,
    declared_rank: int,
) -> tuple[float, int, str]:
    indexes: list[float] = []

    def collect(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                if key in {"index", "child_index", "source_child_index"}:
                    try:
                        indexes.append(float(nested))
                    except (TypeError, ValueError):
                        pass
                elif key == "reference_metadata":
                    collect(nested)
        elif isinstance(value, list):
            for nested in value:
                collect(nested)

    collect(relationship.metadata)
    return (
        min(indexes) if indexes else float(declared_rank),
        int(caption.properties.get("source_position") or 0),
        relationship.id,
    )


def _concern(
    ir: DocumentIR,
    code: str,
    message: str,
    *,
    source_ref: str | None = None,
    target_ref: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> bool:
    candidate = IRConcern(
        code=code,
        message=message,
        source_ref=source_ref,
        target_ref=target_ref,
        metadata=dict(metadata or {}),
    )
    identity = candidate.model_dump_json()
    cache = ir.__dict__.get("_layout_concern_identity_cache")
    if cache is None:
        cache = {
            concern.model_dump_json()
            for concern in ir.concerns
        }
        ir.__dict__["_layout_concern_identity_cache"] = cache
    if identity in cache:
        return False
    cache.add(identity)
    ir.concerns.append(candidate)
    return True


def _equivalent_caption_groups(
    ir: DocumentIR,
    relationships: list[RelationshipRecord],
    elements: Mapping[str, ElementRecord],
    bbox_for: Callable[[str], dict[str, Any] | None],
) -> list[list[RelationshipRecord]]:
    """Group duplicate graph routes without collapsing distinct source boxes."""

    by_text: dict[str, list[RelationshipRecord]] = defaultdict(list)
    for relationship in relationships:
        caption = elements[relationship.source_id]
        by_text[_normalized_text(caption.value)].append(relationship)

    groups: list[list[RelationshipRecord]] = []
    for same_text in by_text.values():
        grounded_relationships = [
            relationship
            for relationship in same_text
            if bbox_for(relationship.source_id) is not None
        ]
        grounded = [
            [grounded_relationships[index] for index in component]
            for component in _overlap_components(
                [
                    bbox_for(relationship.source_id)
                    for relationship in grounded_relationships
                ]
            )
        ]
        ungrounded = [
            relationship
            for relationship in same_text
            if bbox_for(relationship.source_id) is None
        ]
        if grounded:
            # Semantic compatibility children often lack their own box. Attach
            # them to the single grounded graph route only; with more than one
            # grounded occurrence they remain ambiguous diagnostics.
            if len(grounded) == 1:
                grounded[0].extend(ungrounded)
            else:
                groups.extend([[relationship] for relationship in ungrounded])
            groups.extend(grounded)
        else:
            groups.extend([[relationship] for relationship in ungrounded])
    return groups


def _select_representative(
    group: list[RelationshipRecord],
    elements: Mapping[str, ElementRecord],
    bbox_for: Callable[[str], dict[str, Any] | None],
    presented: set[str],
) -> RelationshipRecord:
    return min(
        group,
        key=lambda relationship: (
            0 if relationship.source_id in presented else 1,
            0 if bbox_for(relationship.source_id) else 1,
            -len(elements[relationship.source_id].evidence_ids),
            relationship.id,
        ),
    )


def _cross_projection_caption_preflight(
    ir: DocumentIR,
) -> tuple[set[str], set[str]]:
    """Bound and arbitrate caption candidates shared by enabled domains."""

    elements = {element.id: element for element in ir.elements}
    page_by_id = {page.id: page for page in ir.pages}
    boxes_by_id = {box.id: box for box in ir.bboxes}
    coordinates_by_id = {
        coordinate.id: coordinate for coordinate in ir.coordinate_systems
    }
    evidence_by_id = {record.id: record for record in ir.evidence}

    @lru_cache(maxsize=None)
    def bbox_for(element_id: str) -> dict[str, Any] | None:
        return _page_bbox(
            elements[element_id],
            boxes=boxes_by_id,
            coordinates=coordinates_by_id,
            pages=page_by_id,
            evidence=evidence_by_id,
        )

    owners_by_caption: dict[str, set[str]] = defaultdict(set)
    owner_domain: dict[str, str] = {}
    for relationship in ir.relationships:
        if relationship.type is not RelationshipType.CAPTION_OF:
            continue
        owner = elements[relationship.target_id]
        table_owner = _is_table_caption_owner(owner)
        if not table_owner and owner.type.casefold() not in _VISUAL_TYPES:
            continue
        owners_by_caption[relationship.source_id].add(owner.id)
        owner_domain[owner.id] = (
            "table" if table_owner else "visual"
        )

    ambiguous = {
        caption_id
        for caption_id, owner_ids in owners_by_caption.items()
        if len(owner_ids) > 1
    }
    caption_ids_by_page: dict[str, list[str]] = defaultdict(list)
    for caption_id in owners_by_caption:
        caption_ids_by_page[elements[caption_id].page_id].append(caption_id)
    overflow: set[str] = set()
    for page_id, page_caption_ids in caption_ids_by_page.items():
        eligible_page_caption_ids: list[str] = []
        for caption_id in page_caption_ids:
            caption = elements[caption_id]
            if not _has_accepted_raw_source_provenance(
                caption,
                evidence_by_id,
            ):
                continue
            # Oversized visual candidates are rejected by the owner-level
            # projector. Keep them out of common normalization and geometry.
            if any(
                owner_domain[owner_id] == "visual"
                for owner_id in owners_by_caption[caption_id]
            ):
                _count, oversized = _visual_caption_payload_overflow(
                    caption,
                    evidence_by_id,
                )
                if oversized:
                    continue
            eligible_page_caption_ids.append(caption_id)

        if (
            len(eligible_page_caption_ids)
            > _MAX_PAGE_CAPTION_CANDIDATES
        ):
            overflow.update(eligible_page_caption_ids)
            domain_counts = Counter(
                owner_domain[owner_id]
                for caption_id in eligible_page_caption_ids
                for owner_id in owners_by_caption[caption_id]
            )
            _concern(
                ir,
                "layout_caption_page_candidate_limit",
                "The combined table and visual caption candidate set exceeded "
                "the page limit and remained evidence-only.",
                metadata={
                    "page_id": page_id,
                    "candidate_count": len(eligible_page_caption_ids),
                    "limit": _MAX_PAGE_CAPTION_CANDIDATES,
                    "table_owner_claim_count": domain_counts["table"],
                    "visual_owner_claim_count": domain_counts["visual"],
                },
            )
            continue

        by_normalized_digest: dict[str, list[str]] = defaultdict(list)
        for caption_id in eligible_page_caption_ids:
            caption = elements[caption_id]
            by_normalized_digest[
                _normalized_text_digest(
                    _raw_source_value_view(caption, evidence_by_id)
                )
            ].append(caption_id)
        for digest, same_text_ids in by_normalized_digest.items():
            if len(same_text_ids) <= _MAX_SAME_TEXT_CAPTION_CANDIDATES:
                continue
            overflow.update(same_text_ids)
            domain_counts = Counter(
                owner_domain[owner_id]
                for caption_id in same_text_ids
                for owner_id in owners_by_caption[caption_id]
            )
            _concern(
                ir,
                "layout_caption_same_text_candidate_limit",
                "The combined table and visual same-text caption candidate set "
                "exceeded the page limit and remained evidence-only.",
                metadata={
                    "page_id": page_id,
                    "normalized_text_sha256": digest,
                    "candidate_count": len(same_text_ids),
                    "limit": _MAX_SAME_TEXT_CAPTION_CANDIDATES,
                    "table_owner_claim_count": domain_counts["table"],
                    "visual_owner_claim_count": domain_counts["visual"],
                },
            )

        bounded_caption_ids = [
            caption_id
            for caption_id in eligible_page_caption_ids
            if caption_id not in overflow
        ]
        for component in _overlap_components(
            [bbox_for(caption_id) for caption_id in bounded_caption_ids]
        ):
            cluster = [bounded_caption_ids[index] for index in component]
            owner_ids = {
                owner_id
                for caption_id in cluster
                for owner_id in owners_by_caption[caption_id]
            }
            if len(owner_ids) > 1:
                ambiguous.update(cluster)
    return ambiguous, overflow


def _project_table_captions(
    ir: DocumentIR,
    *,
    cross_projection_ambiguous_ids: frozenset[str] = frozenset(),
    common_overflow_caption_ids: frozenset[str] = frozenset(),
) -> None:
    elements = {element.id: element for element in ir.elements}
    page_by_id = {page.id: page for page in ir.pages}
    boxes_by_id = {box.id: box for box in ir.bboxes}
    coordinates_by_id = {
        coordinate.id: coordinate for coordinate in ir.coordinate_systems
    }
    evidence_by_id = {record.id: record for record in ir.evidence}
    presented = {
        element_id
        for page in ir.pages
        for element_id in page.presentation_element_ids
    }

    @lru_cache(maxsize=None)
    def bbox_for(element_id: str) -> dict[str, Any] | None:
        return _page_bbox(
            elements[element_id],
            boxes=boxes_by_id,
            coordinates=coordinates_by_id,
            pages=page_by_id,
            evidence=evidence_by_id,
        )

    incoming: dict[str, list[RelationshipRecord]] = defaultdict(list)
    owners_by_caption: dict[str, set[str]] = defaultdict(set)
    for relationship in ir.relationships:
        if relationship.type is not RelationshipType.CAPTION_OF:
            continue
        caption = elements[relationship.source_id]
        owner = elements[relationship.target_id]
        if not _is_table_caption_owner(owner):
            continue
        incoming[owner.id].append(relationship)
        owners_by_caption[caption.id].add(owner.id)

    # Cluster equivalent physical caption occurrences across owners. Small
    # extractor jitter must not turn one shared source caption into two
    # independently asserted captions.
    physical_owner_ids: dict[str, set[str]] = {
        caption_id: set(owner_ids)
        for caption_id, owner_ids in owners_by_caption.items()
    }
    caption_ids_by_page: dict[str, list[str]] = defaultdict(list)
    for caption_id in owners_by_caption:
        if caption_id in common_overflow_caption_ids:
            continue
        caption = elements[caption_id]
        caption_ids_by_page[caption.page_id].append(caption_id)
    overflow_caption_ids: set[str] = set()
    for page_id, page_caption_ids in caption_ids_by_page.items():
        if len(page_caption_ids) > _MAX_PAGE_CAPTION_CANDIDATES:
            overflow_caption_ids.update(page_caption_ids)
            _concern(
                ir,
                "table_caption_page_candidate_limit",
                "One page exceeded the bounded caption candidate limit; "
                "those candidates remained evidence-only.",
                metadata={
                    "page_id": page_id,
                    "candidate_count": len(page_caption_ids),
                    "limit": _MAX_PAGE_CAPTION_CANDIDATES,
                },
            )
            continue
        caption_ids_by_text: dict[str, list[str]] = defaultdict(list)
        for caption_id in page_caption_ids:
            caption_ids_by_text[
                _normalized_text(elements[caption_id].value)
            ].append(caption_id)
        for normalized_text, same_text_ids in caption_ids_by_text.items():
            if (
                len(same_text_ids)
                <= _MAX_SAME_TEXT_CAPTION_CANDIDATES
            ):
                continue
            overflow_caption_ids.update(same_text_ids)
            _concern(
                ir,
                "table_caption_same_text_candidate_limit",
                "One page exceeded the bounded same-text caption candidate "
                "limit; those candidates remained evidence-only.",
                metadata={
                    "page_id": page_id,
                    "normalized_text_sha256": hashlib.sha256(
                        normalized_text.encode("utf-8")
                    ).hexdigest(),
                    "candidate_count": len(same_text_ids),
                    "limit": _MAX_SAME_TEXT_CAPTION_CANDIDATES,
                },
            )
        caption_ids = [
            caption_id
            for caption_id in page_caption_ids
            if caption_id not in overflow_caption_ids
            and caption_id not in common_overflow_caption_ids
        ]
        clusters = [
            [caption_ids[index] for index in component]
            for component in _overlap_components(
                [bbox_for(caption_id) for caption_id in caption_ids]
            )
        ]
        for cluster in clusters:
            cluster_owners = {
                owner_id
                for caption_id in cluster
                for owner_id in owners_by_caption[caption_id]
            }
            for caption_id in cluster:
                physical_owner_ids[caption_id] = set(cluster_owners)

    promoted_by_caption: dict[str, str] = {}
    changed_page_ids: set[str] = set()
    captions_before_owner: dict[str, list[str]] = {}
    removed_presentation_ids: dict[str, set[str]] = defaultdict(set)
    for owner_id, owner_relationships in incoming.items():
        owner = elements[owner_id]
        if (
            owner.id not in presented
            or not isinstance(owner.properties.get("legacy_item"), Mapping)
        ):
            _concern(
                ir,
                "table_caption_owner_not_presented",
                "A raw table-caption relationship has no presented public "
                "table owner and remained evidence-only.",
                target_ref=owner.id,
            )
            continue
        if len(owner_relationships) > _MAX_TABLE_CAPTION_REFERENCES:
            _concern(
                ir,
                "table_caption_reference_limit",
                "A table exceeded the bounded caption-reference limit; all "
                "candidate captions remained evidence-only.",
                target_ref=owner.id,
                metadata={
                    "reference_count": len(owner_relationships),
                    "limit": _MAX_TABLE_CAPTION_REFERENCES,
                },
            )
            continue
        owner_box = bbox_for(owner.id)
        owner_legacy = _legacy_item(owner)
        owner_public_id = str(owner_legacy.get("id") or owner.id)
        relationship_rank = {
            relationship.id: index
            for index, relationship in enumerate(owner_relationships)
        }
        accepted: list[
            tuple[int, RelationshipRecord, ElementRecord, dict[str, Any]]
        ] = []
        suppressed_caption_ids: set[str] = set()
        groups = _equivalent_caption_groups(
            ir,
            owner_relationships,
            elements,
            bbox_for,
        )
        for group in groups:
            representative_relationship = _select_representative(
                group,
                elements,
                bbox_for,
                presented,
            )
            caption = elements[representative_relationship.source_id]
            if any(
                relationship.source_id in overflow_caption_ids
                for relationship in group
            ):
                continue
            if any(
                relationship.source_id in common_overflow_caption_ids
                for relationship in group
            ):
                continue
            if any(
                relationship.source_id
                in cross_projection_ambiguous_ids
                for relationship in group
            ):
                _concern(
                    ir,
                    "shared_layout_caption",
                    "Equivalent caption evidence is claimed across table and "
                    "visual owners; all enabled projections remained "
                    "evidence-only.",
                    source_ref=caption.id,
                    target_ref=owner.id,
                )
                continue
            if caption.value is None or (
                isinstance(caption.value, str)
                and not _normalized_text(caption.value)
            ):
                _concern(
                    ir,
                    "empty_table_caption",
                    "A declared table caption has no source-visible text and "
                    "remained evidence-only.",
                    source_ref=caption.id,
                    target_ref=owner.id,
                )
                continue
            if not isinstance(caption.value, str):
                _concern(
                    ir,
                    "unsupported_table_caption_value",
                    "A declared table caption has unsupported non-text "
                    "content and remained evidence-only.",
                    source_ref=caption.id,
                    target_ref=owner.id,
                    metadata={"value_type": type(caption.value).__name__},
                )
                continue
            has_raw_caption_evidence = bool(
                _raw_source_evidence(caption, evidence_by_id)
            )
            source_visible = (
                _has_accepted_raw_source_provenance(
                    caption,
                    evidence_by_id,
                )
                if has_raw_caption_evidence
                else _has_source_visible_evidence(
                    caption,
                    evidence_by_id,
                )
            )
            if not source_visible:
                _concern(
                    ir,
                    "generated_table_caption_not_promoted",
                    "A generated or derived-only table caption remained "
                    "evidence-only.",
                    source_ref=caption.id,
                    target_ref=owner.id,
                )
                continue
            grounded_caption = next(
                (
                    elements[relationship.source_id]
                    for relationship in group
                    if bbox_for(relationship.source_id) is not None
                ),
                caption,
            )
            caption_box = bbox_for(grounded_caption.id)
            occurrence_owner_ids = physical_owner_ids[
                grounded_caption.id
            ]
            if len(occurrence_owner_ids) > 1:
                _concern(
                    ir,
                    "shared_table_caption",
                    "Equivalent caption evidence at one physical source "
                    "location is referenced by multiple tables; ownership "
                    "remained evidence-only.",
                    source_ref=caption.id,
                    metadata={
                        "owner_element_ids": sorted(occurrence_owner_ids),
                    },
                )
                continue
            shared_owner_ids = owners_by_caption[caption.id]
            if len(shared_owner_ids) > 1:
                _concern(
                    ir,
                    "shared_table_caption",
                    "One caption is referenced by multiple tables; the "
                    "relationships remain evidence-only because ownership is "
                    "ambiguous.",
                    source_ref=caption.id,
                    metadata={
                        "owner_element_ids": sorted(shared_owner_ids),
                    },
                )
                continue
            valid, basis = _external_caption_geometry(
                caption_box,
                owner_box,
            )
            if not valid:
                _concern(
                    ir,
                    "table_caption_not_promoted",
                    "A declared table caption lacked agreeing external "
                    "geometry and remained evidence-only.",
                    source_ref=caption.id,
                    target_ref=owner.id,
                    metadata={"reason": basis},
                )
                continue
            duplicate_ids = sorted(
                {
                    relationship.source_id
                    for relationship in group
                    if relationship.source_id != caption.id
                }
            )
            if duplicate_ids:
                _concern(
                    ir,
                    "duplicate_table_caption_evidence",
                    "Equivalent table-caption graph routes were retained as "
                    "evidence and projected once.",
                    source_ref=caption.id,
                    target_ref=owner.id,
                    metadata={"duplicate_element_ids": duplicate_ids},
                )
                for duplicate_id in duplicate_ids:
                    elements[duplicate_id].presentation_role = "diagnostic"
                    suppressed_caption_ids.add(duplicate_id)
            public_caption_id = promoted_by_caption.setdefault(
                caption.id,
                str(_legacy_item(caption).get("id") or caption.id),
            )
            public_caption = _legacy_item(caption)
            caption_source = _evidence_source(caption, evidence_by_id)
            if caption_source is None:
                caption_source = _evidence_source(
                    grounded_caption,
                    evidence_by_id,
                )
            caption_confidence = _evidence_confidence(
                caption,
                evidence_by_id,
            )
            if caption_confidence is None:
                caption_confidence = _evidence_confidence(
                    grounded_caption,
                    evidence_by_id,
                )
            public_relationship_id = _public_relationship_id(
                public_caption_id,
                owner_public_id,
            )
            public_caption.update(
                {
                    "id": public_caption_id,
                    "type": "caption",
                    "reading_order": 0,
                    "value": deepcopy(caption.value),
                    "md": (
                        caption.markdown
                        or public_caption.get("md")
                        or str(caption.value or "")
                    ),
                    "bbox": caption_box,
                    "source": caption_source,
                    "confidence": caption_confidence,
                    "caption_of": owner_public_id,
                    "relationship_id": public_relationship_id,
                    "relationship_type": (
                        RelationshipType.CAPTION_OF.value
                    ),
                    "relationship_basis": basis,
                }
            )
            caption.type = "caption"
            caption.presentation_role = "primary"
            caption.properties["legacy_item"] = public_caption
            caption.properties["layout_projection"] = {
                "story": "P03-US01",
                "relationship_id": public_relationship_id,
                "source_relationship_id": representative_relationship.id,
                "basis": basis,
            }
            accepted.append(
                (
                    min(
                        relationship_rank[relationship.id]
                        for relationship in group
                    ),
                    representative_relationship,
                    caption,
                    public_caption,
                )
            )

        if not accepted:
            continue
        accepted.sort(
            key=lambda item: _relationship_order_key(
                item[1],
                item[2],
                item[0],
            )
        )
        if len(accepted) > 1:
            _concern(
                ir,
                "multiple_table_captions",
                "A table has multiple externally grounded caption "
                "relationships; all remain separate and ordered.",
                target_ref=owner.id,
                metadata={
                    "caption_element_ids": [
                        caption.id for _, _, caption, _ in accepted
                    ]
                },
            )
        relationships = list(owner_legacy.get("relationships") or [])
        caption_ids = list(owner_legacy.get("caption_ids") or [])
        for _, relationship, caption, public_caption in accepted:
            caption_id = str(public_caption["id"])
            if caption_id not in caption_ids:
                caption_ids.append(caption_id)
            descriptor = {
                "id": str(public_caption["relationship_id"]),
                "type": RelationshipType.CAPTION_OF.value,
                "source_id": caption_id,
                "target_id": owner_public_id,
            }
            relationships = [
                existing
                for existing in relationships
                if not (
                    isinstance(existing, Mapping)
                    and existing.get("type")
                    == RelationshipType.CAPTION_OF.value
                    and existing.get("source_id") == caption_id
                    and existing.get("target_id") == owner_public_id
                )
            ]
            if descriptor not in relationships:
                relationships.append(descriptor)
        owner_legacy["caption_ids"] = caption_ids
        owner_legacy["caption_of"] = list(caption_ids)
        owner_legacy["relationships"] = relationships
        owner.properties["legacy_item"] = owner_legacy

        accepted_caption_ids = [
            caption.id for _, _, caption, _ in accepted
        ]
        captions_before_owner[owner.id] = accepted_caption_ids
        removed_presentation_ids[owner.page_id].update(
            accepted_caption_ids
        )
        removed_presentation_ids[owner.page_id].update(
            suppressed_caption_ids
        )
        changed_page_ids.add(owner.page_id)

    for page in ir.pages:
        if page.id not in changed_page_ids:
            continue
        rebuilt_ids: list[str] = []
        removed_ids = removed_presentation_ids[page.id]
        for element_id in page.presentation_element_ids:
            if element_id in removed_ids:
                continue
            rebuilt_ids.extend(captions_before_owner.get(element_id, ()))
            rebuilt_ids.append(element_id)
        page.presentation_element_ids = rebuilt_ids
        for reading_order, element_id in enumerate(
            page.presentation_element_ids
        ):
            element = elements[element_id]
            element.reading_order = reading_order
            legacy = element.properties.get("legacy_item")
            if isinstance(legacy, Mapping):
                updated = deepcopy(dict(legacy))
                updated["reading_order"] = reading_order
                element.properties["legacy_item"] = updated


def _project_visual_relationships(
    ir: DocumentIR,
    *,
    cross_projection_ambiguous_ids: frozenset[str] = frozenset(),
    common_overflow_caption_ids: frozenset[str] = frozenset(),
) -> None:
    elements = {element.id: element for element in ir.elements}
    page_by_id = {page.id: page for page in ir.pages}
    boxes_by_id = {box.id: box for box in ir.bboxes}
    coordinates_by_id = {
        coordinate.id: coordinate for coordinate in ir.coordinate_systems
    }
    evidence_by_id = {record.id: record for record in ir.evidence}
    presented = {
        element_id
        for page in ir.pages
        for element_id in page.presentation_element_ids
    }

    @lru_cache(maxsize=None)
    def bbox_for(element_id: str) -> dict[str, Any] | None:
        return _page_bbox(
            elements[element_id],
            boxes=boxes_by_id,
            coordinates=coordinates_by_id,
            pages=page_by_id,
            evidence=evidence_by_id,
        )

    incoming_captions: dict[str, list[RelationshipRecord]] = defaultdict(list)
    outgoing_children: dict[str, list[RelationshipRecord]] = defaultdict(list)
    owners_by_caption: dict[str, set[str]] = defaultdict(set)
    owners_by_child: dict[str, set[str]] = defaultdict(set)
    for relationship in ir.relationships:
        if relationship.type is RelationshipType.CAPTION_OF:
            owner = elements[relationship.target_id]
            if owner.type.casefold() not in _VISUAL_TYPES:
                continue
            caption = elements[relationship.source_id]
            if not _has_raw_source_evidence(caption, evidence_by_id):
                continue
            incoming_captions[owner.id].append(relationship)
            owners_by_caption[relationship.source_id].add(owner.id)
        elif relationship.type is RelationshipType.CONTAINS:
            owner = elements[relationship.source_id]
            if owner.type.casefold() not in _VISUAL_TYPES:
                continue
            child = elements[relationship.target_id]
            if not _has_raw_source_evidence(child, evidence_by_id):
                continue
            outgoing_children[owner.id].append(relationship)
            owners_by_child[relationship.target_id].add(owner.id)

    owner_ids = list(
        dict.fromkeys([*incoming_captions, *outgoing_children])
    )
    emitted_by_owner: Counter[str] = Counter()
    emitted_by_page: Counter[str] = Counter()
    suppressed_by_page: dict[str, Counter[str]] = defaultdict(Counter)
    suppressed_candidates_by_page: dict[str, Counter[str]] = defaultdict(
        Counter
    )
    suppressed_owner_ids_by_page: dict[str, set[str]] = defaultdict(set)

    def emit_visual_concern(
        code: str,
        message: str,
        *,
        owner_id: str | None = None,
        source_ref: str | None = None,
        target_ref: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        priority: bool = False,
    ) -> None:
        resolved_owner_id = owner_id
        if resolved_owner_id is None and target_ref in elements:
            target = elements[str(target_ref)]
            if target.type.casefold() in _VISUAL_TYPES:
                resolved_owner_id = target.id
        page_id = (
            elements[resolved_owner_id].page_id
            if resolved_owner_id in elements
            else None
        )
        if (
            page_id is not None
            and (
                emitted_by_page[page_id]
                >= _MAX_VISUAL_CONCERNS_PER_PAGE
                or (
                    not priority
                    and emitted_by_owner[resolved_owner_id]
                    >= _MAX_VISUAL_CONCERNS_PER_OWNER
                )
            )
        ):
            suppressed_by_page[page_id][code] += 1
            candidate_count = (
                metadata.get("candidate_count")
                if isinstance(metadata, Mapping)
                else None
            )
            suppression_weight = (
                int(candidate_count)
                if isinstance(candidate_count, int)
                and 0 < candidate_count <= 4096
                else 1
            )
            suppressed_candidates_by_page[page_id][
                code
            ] += suppression_weight
            suppressed_owner_ids_by_page[page_id].add(resolved_owner_id)
            return
        appended = _concern(
            ir,
            code,
            message,
            source_ref=source_ref,
            target_ref=target_ref,
            metadata=metadata,
        )
        if appended and page_id is not None:
            emitted_by_owner[resolved_owner_id] += 1
            emitted_by_page[page_id] += 1

    owner_ids_by_page: dict[str, list[str]] = defaultdict(list)
    for owner_id in owner_ids:
        owner_ids_by_page[elements[owner_id].page_id].append(owner_id)
    blocked_owner_ids: set[str] = set()
    for page_id, page_owner_ids in owner_ids_by_page.items():
        if len(page_owner_ids) <= _MAX_VISUAL_OWNERS_PER_PAGE:
            continue
        blocked_owner_ids.update(page_owner_ids)
        _concern(
            ir,
            "visual_owner_page_limit",
            "One page exceeded the bounded visual-owner limit; its visual "
            "relationships remained evidence-only.",
            metadata={
                "page_id": page_id,
                "owner_count": len(page_owner_ids),
                "limit": _MAX_VISUAL_OWNERS_PER_PAGE,
            },
        )

    generated_caption_ids: set[str] = set()
    rejected_raw_child_ids: set[str] = set()
    for owner_id in owner_ids:
        if owner_id in blocked_owner_ids:
            continue
        owner = elements[owner_id]
        caption_relationships = incoming_captions.get(owner_id, [])
        child_relationships = outgoing_children.get(owner_id, [])
        if (
            owner.id not in presented
            or not isinstance(owner.properties.get("legacy_item"), Mapping)
        ):
            emit_visual_concern(
                "visual_relationship_owner_not_presented",
                "A visual relationship has no presented public owner and "
                "remained evidence-only.",
                owner_id=owner.id,
                target_ref=owner.id,
                priority=True,
            )
            blocked_owner_ids.add(owner.id)
            continue
        if len(caption_relationships) > _MAX_VISUAL_CAPTION_REFERENCES:
            emit_visual_concern(
                "visual_caption_reference_limit",
                "A visual exceeded the bounded caption-reference limit; all "
                "of its relationships remained evidence-only.",
                owner_id=owner.id,
                target_ref=owner.id,
                metadata={
                    "reference_count": len(caption_relationships),
                    "limit": _MAX_VISUAL_CAPTION_REFERENCES,
                },
                priority=True,
            )
            blocked_owner_ids.add(owner.id)
            continue
        if len(child_relationships) > _MAX_VISUAL_CHILD_REFERENCES:
            emit_visual_concern(
                "visual_child_reference_limit",
                "A visual exceeded the bounded child-reference limit; all "
                "of its relationships remained evidence-only.",
                owner_id=owner.id,
                target_ref=owner.id,
                metadata={
                    "reference_count": len(child_relationships),
                    "limit": _MAX_VISUAL_CHILD_REFERENCES,
                },
                priority=True,
            )
            blocked_owner_ids.add(owner.id)
            continue

        owner_generated_caption_ids: set[str] = set()
        oversized_count = 0
        observed_caption_bytes = 0
        for relationship in caption_relationships:
            caption = elements[relationship.source_id]
            if not _has_accepted_raw_source_provenance(
                caption,
                evidence_by_id,
            ):
                generated_caption_ids.add(caption.id)
                owner_generated_caption_ids.add(caption.id)
                continue
            byte_count, oversized = _visual_caption_payload_overflow(
                caption,
                evidence_by_id,
            )
            if oversized:
                oversized_count += 1
                observed_caption_bytes = max(
                    observed_caption_bytes,
                    byte_count,
                )
        if owner_generated_caption_ids:
            emit_visual_concern(
                "generated_visual_caption_not_promoted",
                "A generated, model-derived, or derived-only visual caption "
                "remained evidence-only.",
                owner_id=owner.id,
                target_ref=owner.id,
                metadata={
                    "candidate_count": len(owner_generated_caption_ids),
                },
                priority=True,
            )
        if oversized_count:
            emit_visual_concern(
                "visual_caption_byte_limit",
                "A visual had an oversized caption candidate; its complete "
                "relationship candidate set remained evidence-only.",
                owner_id=owner.id,
                target_ref=owner.id,
                metadata={
                    "oversized_candidate_count": oversized_count,
                    "observed_bytes_at_least": observed_caption_bytes,
                    "limit": _MAX_VISUAL_CAPTION_BYTES,
                },
                priority=True,
            )
            blocked_owner_ids.add(owner.id)
            continue

        owner_rejected_child_ids = {
            relationship.target_id
            for relationship in child_relationships
            if not _has_accepted_raw_source_provenance(
                elements[relationship.target_id],
                evidence_by_id,
                allow_inferred_punctuation=True,
            )
        }
        rejected_raw_child_ids.update(owner_rejected_child_ids)
        if owner_rejected_child_ids:
            emit_visual_concern(
                "generated_visual_child_not_projected",
                "Generated, model-derived, or derived-only visual children "
                "remained retained IR evidence only.",
                owner_id=owner.id,
                target_ref=owner.id,
                metadata={
                    "candidate_count": len(owner_rejected_child_ids),
                },
                priority=True,
            )
        eligible_child_relationships = [
            relationship
            for relationship in child_relationships
            if relationship.target_id not in owner_rejected_child_ids
        ]

        owner_legacy = owner.properties["legacy_item"]
        owner_public_id = str(owner_legacy.get("id") or owner.id)
        contained_bytes, contained_overflow = (
            _contained_item_preflight_size(
                owner_public_id=owner_public_id,
                relationships=eligible_child_relationships,
                elements=elements,
                evidence=evidence_by_id,
            )
        )
        if contained_overflow:
            emit_visual_concern(
                "visual_contained_items_byte_limit",
                "A visual exceeded the bounded contained-item output limit; "
                "all of its relationships remained evidence-only.",
                owner_id=owner.id,
                target_ref=owner.id,
                metadata={
                    "candidate_count": len(eligible_child_relationships),
                    "observed_bytes_at_least": contained_bytes,
                    "limit": _MAX_CONTAINED_ITEMS_BYTES,
                },
                priority=True,
            )
            blocked_owner_ids.add(owner.id)

    blocked_caption_ids = set(common_overflow_caption_ids)
    blocked_caption_ids.update(generated_caption_ids)
    blocked_caption_ids.update(cross_projection_ambiguous_ids)
    active_owners_by_caption: dict[str, set[str]] = defaultdict(set)
    for caption_id, caption_owner_ids in owners_by_caption.items():
        if caption_id in blocked_caption_ids:
            continue
        active_owner_ids = {
            owner_id
            for owner_id in caption_owner_ids
            if owner_id not in blocked_owner_ids
        }
        if active_owner_ids:
            active_owners_by_caption[caption_id].update(active_owner_ids)

    caption_ids_by_page: dict[str, list[str]] = defaultdict(list)
    for caption_id in active_owners_by_caption:
        caption_ids_by_page[elements[caption_id].page_id].append(caption_id)
    overflow_caption_ids: set[str] = set()
    for page_id, page_caption_ids in caption_ids_by_page.items():
        if len(page_caption_ids) > _MAX_PAGE_CAPTION_CANDIDATES:
            overflow_caption_ids.update(page_caption_ids)
            _concern(
                ir,
                "visual_caption_page_candidate_limit",
                "One page exceeded the bounded visual-caption candidate "
                "limit; those candidates remained evidence-only.",
                metadata={
                    "page_id": page_id,
                    "candidate_count": len(page_caption_ids),
                    "limit": _MAX_PAGE_CAPTION_CANDIDATES,
                },
            )
            continue
        caption_ids_by_text: dict[str, list[str]] = defaultdict(list)
        for caption_id in page_caption_ids:
            caption_ids_by_text[
                _normalized_text_digest(
                    _raw_source_value_view(
                        elements[caption_id],
                        evidence_by_id,
                    )
                )
            ].append(caption_id)
        for normalized_digest, same_text_ids in caption_ids_by_text.items():
            if len(same_text_ids) <= _MAX_SAME_TEXT_CAPTION_CANDIDATES:
                continue
            overflow_caption_ids.update(same_text_ids)
            _concern(
                ir,
                "visual_caption_same_text_candidate_limit",
                "One page exceeded the bounded same-text visual-caption "
                "limit; those candidates remained evidence-only.",
                metadata={
                    "page_id": page_id,
                    "normalized_text_sha256": normalized_digest,
                    "candidate_count": len(same_text_ids),
                    "limit": _MAX_SAME_TEXT_CAPTION_CANDIDATES,
                },
            )

    physical_owner_ids = {
        caption_id: set(owner_ids)
        for caption_id, owner_ids in active_owners_by_caption.items()
    }
    for page_caption_ids in caption_ids_by_page.values():
        bounded_caption_ids = [
            caption_id
            for caption_id in page_caption_ids
            if caption_id not in overflow_caption_ids
        ]
        for component in _overlap_components(
            [bbox_for(caption_id) for caption_id in bounded_caption_ids]
        ):
            cluster = [
                bounded_caption_ids[index] for index in component
            ]
            cluster_owner_ids = {
                owner_id
                for caption_id in cluster
                for owner_id in active_owners_by_caption[caption_id]
            }
            for caption_id in cluster:
                physical_owner_ids[caption_id] = set(cluster_owner_ids)

    captions_before_owner: dict[str, list[str]] = defaultdict(list)
    captions_after_owner: dict[str, list[str]] = defaultdict(list)
    removed_presentation_ids: dict[str, set[str]] = defaultdict(set)
    changed_page_ids: set[str] = set()
    promoted_by_caption: dict[str, str] = {}

    for owner_id in owner_ids:
        owner = elements[owner_id]
        declared_caption_relationships = incoming_captions.get(owner_id, [])
        child_relationships = [
            relationship
            for relationship in outgoing_children.get(owner_id, [])
            if relationship.target_id not in rejected_raw_child_ids
        ]
        if owner_id in blocked_owner_ids:
            continue
        ambiguous_caption_ids = {
            relationship.source_id
            for relationship in declared_caption_relationships
            if relationship.source_id in cross_projection_ambiguous_ids
            and relationship.source_id
            not in common_overflow_caption_ids
            and relationship.source_id not in generated_caption_ids
        }
        if ambiguous_caption_ids:
            emit_visual_concern(
                "shared_layout_caption",
                "Equivalent caption evidence is claimed across table and "
                "visual owners; all enabled projections remained "
                "evidence-only.",
                owner_id=owner.id,
                target_ref=owner.id,
                metadata={
                    "candidate_count": len(ambiguous_caption_ids),
                },
                priority=True,
            )
        caption_relationships = [
            relationship
            for relationship in declared_caption_relationships
            if relationship.source_id not in generated_caption_ids
            and relationship.source_id not in common_overflow_caption_ids
            and relationship.source_id not in cross_projection_ambiguous_ids
            and relationship.source_id not in overflow_caption_ids
        ]

        owner_box = bbox_for(owner.id)
        owner_legacy = _legacy_item(owner)
        owner_public_id = str(owner_legacy.get("id") or owner.id)
        relationship_rank = {
            relationship.id: index
            for index, relationship in enumerate(caption_relationships)
        }
        accepted_captions: list[
            tuple[
                int,
                RelationshipRecord,
                ElementRecord,
                ElementRecord,
                dict[str, Any],
                str,
                set[str],
            ]
        ] = []
        accepted_caption_element_ids: set[str] = set()

        for group in _equivalent_caption_groups(
            ir,
            caption_relationships,
            elements,
            bbox_for,
        ):
            representative_relationship = _select_representative(
                group,
                elements,
                bbox_for,
                presented,
            )
            public_element = elements[representative_relationship.source_id]
            group_element_ids = {
                relationship.source_id for relationship in group
            }
            grounded_caption = next(
                (
                    elements[relationship.source_id]
                    for relationship in group
                    if bbox_for(relationship.source_id) is not None
                ),
                public_element,
            )
            caption_value = _raw_source_value(
                grounded_caption,
                evidence_by_id,
            )
            if (
                not isinstance(caption_value, str)
                or not _normalized_text(caption_value)
            ):
                emit_visual_concern(
                    "invalid_visual_caption",
                    "A declared visual caption has no supported source-visible "
                    "text and remained evidence-only.",
                    owner_id=owner.id,
                    source_ref=grounded_caption.id,
                    target_ref=owner.id,
                )
                continue
            if not _has_accepted_raw_source_provenance(
                grounded_caption,
                evidence_by_id,
            ):
                emit_visual_concern(
                    "generated_visual_caption_not_promoted",
                    "A generated or derived-only visual caption remained "
                    "evidence-only.",
                    owner_id=owner.id,
                    source_ref=grounded_caption.id,
                    target_ref=owner.id,
                )
                continue
            if grounded_caption.page_id != owner.page_id:
                emit_visual_concern(
                    "visual_caption_not_promoted",
                    "A declared visual caption lacked agreeing external "
                    "geometry and remained evidence-only.",
                    owner_id=owner.id,
                    source_ref=grounded_caption.id,
                    target_ref=owner.id,
                    metadata={"reason": "caption_cross_page"},
                )
                continue
            occurrence_owner_ids = physical_owner_ids.get(
                grounded_caption.id,
                set(),
            )
            if (
                len(occurrence_owner_ids) > 1
                or len(
                    active_owners_by_caption[grounded_caption.id]
                )
                > 1
            ):
                emit_visual_concern(
                    "shared_visual_caption",
                    "Equivalent visual-caption evidence is referenced by "
                    "multiple owners and remained evidence-only.",
                    owner_id=owner.id,
                    source_ref=grounded_caption.id,
                    target_ref=owner.id,
                    metadata={
                        "owner_element_ids": sorted(occurrence_owner_ids),
                    },
                )
                continue
            valid, basis, side = _external_visual_caption_geometry(
                bbox_for(grounded_caption.id),
                owner_box,
            )
            if not valid or side is None:
                emit_visual_concern(
                    "visual_caption_not_promoted",
                    "A declared visual caption lacked agreeing external "
                    "geometry and remained evidence-only.",
                    owner_id=owner.id,
                    source_ref=grounded_caption.id,
                    target_ref=owner.id,
                    metadata={"reason": basis},
                )
                continue

            existing_legacy = public_element.properties.get("legacy_item")
            if (
                public_element.id in presented
                and isinstance(existing_legacy, Mapping)
                and str(existing_legacy.get("id") or "")
            ):
                proposed_public_caption_id = str(existing_legacy["id"])
            else:
                proposed_public_caption_id = (
                    _stable_visual_caption_public_id(
                        owner_public_id,
                        grounded_caption,
                        bbox_for(grounded_caption.id),
                    )
                )
            public_caption_id = promoted_by_caption.setdefault(
                grounded_caption.id,
                proposed_public_caption_id,
            )
            desired_element_id = _compatibility_element_id(
                ir,
                page_by_id[owner.page_id],
                public_caption_id,
            )
            if public_element.id != desired_element_id:
                existing_projection = elements.get(desired_element_id)
                if existing_projection is not None:
                    public_element = existing_projection
                else:
                    projection_element = public_element.model_copy(deep=True)
                    projection_element.id = desired_element_id
                    projection_element.evidence_ids = []
                    projection_element.bbox_ids = list(
                        grounded_caption.bbox_ids
                    )
                    projection_element.properties.pop("raw_refs", None)
                    projection_element.properties.pop("raw_label", None)
                    projection_element.properties[
                        "projection_source_element_id"
                    ] = grounded_caption.id
                    ir.elements.append(projection_element)
                    elements[projection_element.id] = projection_element
                    page_by_id[owner.page_id].element_ids.append(
                        projection_element.id
                    )
                    projection_region = next(
                        region
                        for region in ir.regions
                        if region.page_id == owner.page_id
                    )
                    projection_region.element_ids.append(
                        projection_element.id
                    )
                    public_element = projection_element
            public_caption = _legacy_item(public_element)
            public_relationship_id = _public_visual_relationship_id(
                RelationshipType.CAPTION_OF,
                public_caption_id,
                owner_public_id,
            )
            public_caption.update(
                {
                    "id": public_caption_id,
                    "type": "caption",
                    "reading_order": 0,
                    "value": deepcopy(caption_value),
                    "md": (
                        grounded_caption.markdown
                        if grounded_caption.markdown
                        and _normalized_text(grounded_caption.markdown)
                        == _normalized_text(caption_value)
                        else str(caption_value)
                    ),
                    "bbox": bbox_for(grounded_caption.id),
                    "source": _raw_source_name(
                        grounded_caption,
                        evidence_by_id,
                    ),
                    "confidence": _raw_source_confidence(
                        grounded_caption,
                        evidence_by_id,
                    ),
                    "caption_of": owner_public_id,
                    "relationship_id": public_relationship_id,
                    "relationship_type": (
                        RelationshipType.CAPTION_OF.value
                    ),
                    "relationship_basis": basis,
                }
            )
            if (
                representative_relationship.metadata.get("field")
                == "children"
            ):
                emit_visual_concern(
                    "visual_relationship_role_conflict",
                    "One externally grounded caption was also declared "
                    "through the visual child field; caption semantics won "
                    "once and the child route remained diagnostic.",
                    owner_id=owner.id,
                    source_ref=grounded_caption.id,
                    target_ref=owner.id,
                    priority=True,
                )
            accepted_captions.append(
                (
                    min(
                        relationship_rank[relationship.id]
                        for relationship in group
                    ),
                    representative_relationship,
                    public_element,
                    grounded_caption,
                    public_caption,
                    side,
                    group_element_ids,
                )
            )
            accepted_caption_element_ids.update(group_element_ids)

        accepted_captions.sort(
            key=lambda item: _relationship_order_key(
                item[1],
                item[3],
                item[0],
            )
        )

        contained_items: list[dict[str, Any]] = []
        contained_elements: list[
            tuple[ElementRecord, dict[str, Any]]
        ] = []
        child_diagnostic_counts: Counter[tuple[str, str | None]] = Counter()
        for relationship in child_relationships:
            child = elements[relationship.target_id]
            child_value = _raw_source_value(child, evidence_by_id)
            if child.id in accepted_caption_element_ids:
                child_diagnostic_counts[
                    ("duplicate_visual_caption_child_role", None)
                ] += 1
                continue
            if len(owners_by_child[child.id]) > 1:
                child_diagnostic_counts[("shared_visual_child", None)] += 1
                continue
            if (
                child.page_id != owner.page_id
                or not isinstance(child_value, str)
                or not _normalized_text(child_value)
                or not _has_accepted_raw_source_provenance(
                    child,
                    evidence_by_id,
                    allow_inferred_punctuation=True,
                )
            ):
                child_diagnostic_counts[
                    ("visual_child_not_projected", None)
                ] += 1
                continue
            valid, basis, containment = _child_containment_geometry(
                bbox_for(child.id),
                owner_box,
            )
            if not valid:
                child_diagnostic_counts[
                    ("visual_child_not_exposed", basis)
                ] += 1
                continue
            public_child = _legacy_item(child)
            public_child_id = str(public_child.get("id") or child.id)
            public_relationship_id = _public_visual_relationship_id(
                RelationshipType.CONTAINS,
                owner_public_id,
                public_child_id,
            )
            public_child.update(
                {
                    "id": public_child_id,
                    "type": "visual_text",
                    "content_type": "visual_text",
                    "page_index": page_by_id[owner.page_id].page_index,
                    "value": deepcopy(child_value),
                    "md": (
                        child.markdown
                        if child.markdown
                        and _normalized_text(child.markdown)
                        == _normalized_text(child_value)
                        else str(child_value)
                    ),
                    "bbox": bbox_for(child.id),
                    "source": _raw_source_name(child, evidence_by_id),
                    "confidence": _raw_source_confidence(
                        child,
                        evidence_by_id,
                    ),
                    "presentation_role": "subordinate",
                    "contained_by": owner_public_id,
                    "relationship_id": public_relationship_id,
                    "relationship_type": RelationshipType.CONTAINS.value,
                    "relationship_basis": basis,
                }
            )
            contained_items.append(public_child)
            contained_elements.append((child, public_child))

        child_messages = {
            "duplicate_visual_caption_child_role": (
                "Externally grounded caption nodes also had child routes; "
                "each caption role projected once."
            ),
            "shared_visual_child": (
                "Visual children were claimed by multiple owners and remained "
                "retained IR evidence only."
            ),
            "visual_child_not_projected": (
                "Declared visual children lacked supported same-page source "
                "evidence and remained IR-only."
            ),
            "visual_child_not_exposed": (
                "Declared visual children lacked agreeing containment and "
                "remained retained IR evidence only."
            ),
        }
        for (code, reason), candidate_count in sorted(
            child_diagnostic_counts.items()
        ):
            metadata: dict[str, Any] = {
                "candidate_count": candidate_count,
            }
            if reason is not None:
                metadata["reason"] = reason
            emit_visual_concern(
                code,
                child_messages[code],
                owner_id=owner.id,
                target_ref=owner.id,
                metadata=metadata,
                priority=(
                    code == "duplicate_visual_caption_child_role"
                ),
            )

        contained_bytes = len(
            json.dumps(
                contained_items,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if contained_bytes > _MAX_CONTAINED_ITEMS_BYTES:
            emit_visual_concern(
                "visual_contained_items_byte_limit",
                "A visual exceeded the bounded contained-item output limit; "
                "all of its relationships remained evidence-only.",
                owner_id=owner.id,
                target_ref=owner.id,
                metadata={
                    "item_count": len(contained_items),
                    "byte_count": contained_bytes,
                    "limit": _MAX_CONTAINED_ITEMS_BYTES,
                },
            )
            continue

        for (
            _rank,
            relationship,
            public_element,
            grounded_caption,
            public_caption,
            side,
            group_element_ids,
        ) in accepted_captions:
            caption_value = public_caption["value"]
            public_element.type = "caption"
            public_element.value = deepcopy(caption_value)
            public_element.markdown = str(public_caption["md"])
            public_element.presentation_role = "primary"
            public_element.properties["legacy_item"] = public_caption
            public_element.properties["layout_projection"] = {
                "story": "P03-US02",
                "relationship_id": public_caption["relationship_id"],
                "source_relationship_id": relationship.id,
                "basis": public_caption["relationship_basis"],
                "placement": side,
            }
            duplicate_ids = sorted(
                group_element_ids - {grounded_caption.id}
            )
            if duplicate_ids:
                emit_visual_concern(
                    "duplicate_visual_caption_evidence",
                    "Equivalent visual-caption routes were retained as "
                    "evidence and projected once.",
                    owner_id=owner.id,
                    source_ref=public_element.id,
                    target_ref=owner.id,
                    metadata={"duplicate_element_ids": duplicate_ids},
                )
                for duplicate_id in duplicate_ids:
                    elements[duplicate_id].presentation_role = "diagnostic"
            placement = (
                captions_before_owner
                if side == "before"
                else captions_after_owner
            )
            placement[owner.id].append(public_element.id)
            removed_presentation_ids[owner.page_id].update(
                group_element_ids
            )

        for child, public_child in contained_elements:
            child.presentation_role = "subordinate"
            child.properties["layout_projection"] = {
                "story": "P03-US02",
                "relationship_id": public_child["relationship_id"],
                "basis": public_child["relationship_basis"],
            }
            removed_presentation_ids[owner.page_id].add(child.id)

        relationships = list(owner_legacy.get("relationships") or [])
        caption_ids = [
            str(item[4]["id"]) for item in accepted_captions
        ]
        contains_ids = [str(item["id"]) for item in contained_items]
        new_descriptors = [
            {
                "id": str(item[4]["relationship_id"]),
                "type": RelationshipType.CAPTION_OF.value,
                "source_id": str(item[4]["id"]),
                "target_id": owner_public_id,
            }
            for item in accepted_captions
        ] + [
            {
                "id": str(item["relationship_id"]),
                "type": RelationshipType.CONTAINS.value,
                "source_id": owner_public_id,
                "target_id": str(item["id"]),
            }
            for item in contained_items
        ]
        new_descriptor_ids = {
            descriptor["id"] for descriptor in new_descriptors
        }
        relationships = [
            relationship
            for relationship in relationships
            if not (
                isinstance(relationship, Mapping)
                and (
                    relationship.get("id") in new_descriptor_ids
                    or (
                        relationship.get("type")
                        == RelationshipType.CONTAINS.value
                        and relationship.get("source_id") == owner_public_id
                    )
                    or (
                        relationship.get("type")
                        == RelationshipType.CAPTION_OF.value
                        and relationship.get("target_id") == owner_public_id
                    )
                )
            )
        ]
        relationships.extend(new_descriptors)

        structured_visual_predecessor = (
            _authoritative_structured_visual_output(owner_legacy)
        )
        if structured_visual_predecessor:
            _externalize_authoritative_structured_caption(
                owner_legacy,
                [item[4] for item in accepted_captions],
            )
        for key in (
            "caption",
            "caption_source",
            "caption_generated",
            "caption_confidence",
        ):
            owner_legacy.pop(key, None)
        # The source-owned visual proof is revalidated against the complete
        # public containment graph.  Make that graph visible atomically before
        # selecting the owner text; the same values are retained below.
        if contains_ids:
            owner_legacy["contains_ids"] = contains_ids
            owner_legacy["contained_items"] = contained_items
        else:
            owner_legacy.pop("contains_ids", None)
            owner_legacy.pop("contained_items", None)
        if relationships:
            owner_legacy["relationships"] = relationships
        else:
            owner_legacy.pop("relationships", None)
        _bind_compact_visual_public_child_ids(
            owner_legacy,
            contained_items,
        )
        structured_visual_text = _authoritative_structured_visual_output(
            owner_legacy
        )
        if structured_visual_predecessor and not structured_visual_text:
            raise _StructuredVisualTransitionError
        if structured_visual_text:
            primary_source_text = ""
            primary_text = structured_visual_text
            primary_ocr_rejection = None
            primary_ocr_contribution_count = 0
            primary_ocr_backed_count = 0
        else:
            primary_source_text, _primary_source_rejection = (
                _grounded_primary_visual_source_text(
                    owner_legacy,
                    contained_items,
                )
            )
            if primary_source_text:
                primary_text = primary_source_text
                primary_ocr_rejection = None
                primary_ocr_contribution_count = 0
                primary_ocr_backed_count = 0
            else:
                (
                    primary_text,
                    primary_ocr_rejection,
                    primary_ocr_contribution_count,
                    primary_ocr_backed_count,
                ) = _grounded_primary_ocr(owner_legacy)
        if primary_ocr_rejection is not None:
            emit_visual_concern(
                "visual_primary_ocr_not_promoted",
                "Visual OCR was not fully backed by accepted same-unit "
                "diagnostic geometry and remained subordinate.",
                owner_id=owner.id,
                target_ref=owner.id,
                metadata={
                    "reason": primary_ocr_rejection,
                    "contribution_count": primary_ocr_contribution_count,
                    "backed_contribution_count": primary_ocr_backed_count,
                },
                priority=True,
            )
        content_type = str(
            owner_legacy.get("content_type")
            or owner_legacy.get("type")
            or owner.type
        ).casefold()
        owner_markdown = primary_text or (
            f"[{content_type.capitalize()} detected; "
            "no reliable text extracted.]"
        )
        owner_legacy["value"] = primary_text
        owner_legacy["md"] = owner_markdown
        if structured_visual_text:
            owner_legacy["source"] = str(
                owner_legacy.get("source") or "derived"
            )
        else:
            owner_legacy["source"] = (
                "native"
                if primary_source_text
                else ("ocr" if primary_text else "derived")
            )
            if primary_source_text:
                owner_legacy["layout_visual_source_text_promoted"] = True
            else:
                owner_legacy.pop("layout_visual_source_text_promoted", None)
        owner_legacy["layout_visual_relationships_projected"] = True
        if caption_ids:
            owner_legacy["caption_ids"] = caption_ids
            owner_legacy["caption_of"] = list(caption_ids)
        else:
            owner_legacy.pop("caption_ids", None)
            owner_legacy.pop("caption_of", None)
        if contains_ids:
            owner_legacy["contains_ids"] = contains_ids
            owner_legacy["contained_items"] = contained_items
        else:
            owner_legacy.pop("contains_ids", None)
            owner_legacy.pop("contained_items", None)
        if relationships:
            owner_legacy["relationships"] = relationships
        else:
            owner_legacy.pop("relationships", None)

        owner.value = primary_text
        owner.markdown = owner_markdown
        owner.properties["legacy_item"] = owner_legacy
        owner.properties["layout_projection"] = {
            "story": "P03-US02",
            "caption_count": len(caption_ids),
            "contained_item_count": len(contained_items),
        }
        changed_page_ids.add(owner.page_id)

    for page_id, suppressed_codes in suppressed_by_page.items():
        _concern(
            ir,
            "visual_relationship_concerns_truncated",
            "Visual relationship diagnostics exceeded bounded emission limits; "
            "a sanitized aggregate was retained.",
            metadata={
                "page_id": page_id,
                "suppressed_count": sum(suppressed_codes.values()),
                "suppressed_candidate_count": sum(
                    suppressed_candidates_by_page[page_id].values()
                ),
                "affected_owner_count": len(
                    suppressed_owner_ids_by_page[page_id]
                ),
                "suppressed_by_code": dict(
                    sorted(suppressed_codes.items())
                ),
                "suppressed_candidates_by_code": dict(
                    sorted(
                        suppressed_candidates_by_page[page_id].items()
                    )
                ),
                "owner_limit": _MAX_VISUAL_CONCERNS_PER_OWNER,
                "page_limit": _MAX_VISUAL_CONCERNS_PER_PAGE,
            },
        )

    for page in ir.pages:
        if page.id not in changed_page_ids:
            continue
        rebuilt_ids: list[str] = []
        removed_ids = removed_presentation_ids[page.id]
        for element_id in page.presentation_element_ids:
            if element_id in removed_ids:
                continue
            rebuilt_ids.extend(captions_before_owner.get(element_id, ()))
            rebuilt_ids.append(element_id)
            rebuilt_ids.extend(captions_after_owner.get(element_id, ()))
        page.presentation_element_ids = rebuilt_ids
        for reading_order, element_id in enumerate(
            page.presentation_element_ids
        ):
            element = elements[element_id]
            element.reading_order = reading_order
            legacy = element.properties.get("legacy_item")
            if isinstance(legacy, Mapping):
                updated = deepcopy(dict(legacy))
                updated["reading_order"] = reading_order
                element.properties["legacy_item"] = updated


def _make_source_note_relationships_canonical_inert(ir: DocumentIR) -> None:
    """Route every raw note assertion through the enabled US03 validator."""

    for relationship in ir.relationships:
        if relationship.type not in {
            RelationshipType.SOURCE_NOTE_OF,
            RelationshipType.FOOTNOTE_OF,
        }:
            continue
        relationship.metadata["canonical_presentation_inert"] = True
        relationship.metadata["layout_projection_managed"] = True


def _project_source_notes(ir: DocumentIR) -> None:
    """Project bounded source-visible notes as distinct public items."""

    if any(
        isinstance(element.properties.get("source_note_projection"), Mapping)
        and element.properties["source_note_projection"].get("story")
        == "P03-US03"
        for element in ir.elements
    ):
        # The projection is intentionally idempotent. A projected document is
        # an immutable input to subsequent compatibility/canonical passes.
        return

    elements = {element.id: element for element in ir.elements}
    page_by_id = {page.id: page for page in ir.pages}
    boxes_by_id = {box.id: box for box in ir.bboxes}
    coordinates_by_id = {
        coordinate.id: coordinate for coordinate in ir.coordinate_systems
    }
    evidence_by_id = {record.id: record for record in ir.evidence}
    presented = {
        element_id
        for page in ir.pages
        for element_id in page.presentation_element_ids
    }

    @lru_cache(maxsize=None)
    def bbox_for(element_id: str) -> dict[str, Any] | None:
        return _page_bbox(
            elements[element_id],
            boxes=boxes_by_id,
            coordinates=coordinates_by_id,
            pages=page_by_id,
            evidence=evidence_by_id,
        )

    owners_by_page: dict[str, list[str]] = defaultdict(list)
    for element_id in presented:
        element = elements[element_id]
        if _is_source_note_owner(element) and isinstance(
            element.properties.get("legacy_item"), Mapping
        ):
            owners_by_page[element.page_id].append(element.id)
    for owner_ids in owners_by_page.values():
        owner_ids.sort(
            key=lambda owner_id: (
                elements[owner_id].reading_order
                if elements[owner_id].reading_order is not None
                else math.inf,
                owner_id,
            )
        )

    blocked_pages: set[str] = set()
    for page_id, owner_ids in owners_by_page.items():
        if len(owner_ids) <= _MAX_SOURCE_NOTE_OWNERS_PER_PAGE:
            continue
        blocked_pages.add(page_id)
        _concern(
            ir,
            "source_note_owner_page_limit",
            "One page exceeded the bounded source-note owner limit; its "
            "associations remained evidence-only.",
            metadata={
                "page_id": page_id,
                "owner_count": len(owner_ids),
                "limit": _MAX_SOURCE_NOTE_OWNERS_PER_PAGE,
            },
        )

    declared_by_candidate: dict[str, list[RelationshipRecord]] = defaultdict(
        list
    )
    declared_by_owner: dict[str, list[RelationshipRecord]] = defaultdict(list)
    for relationship in ir.relationships:
        if relationship.type not in {
            RelationshipType.SOURCE_NOTE_OF,
            RelationshipType.FOOTNOTE_OF,
        }:
            continue
        owner = elements.get(relationship.target_id)
        source = elements.get(relationship.source_id)
        if (
            owner is None
            or source is None
            or not _is_source_note_owner(owner)
        ):
            continue
        declared_by_candidate[source.id].append(relationship)
        declared_by_owner[owner.id].append(relationship)

    blocked_owners: set[str] = set()
    for owner_id, relationships in declared_by_owner.items():
        if len(relationships) <= _MAX_SOURCE_NOTE_REFERENCES:
            continue
        blocked_owners.add(owner_id)
        _concern(
            ir,
            "source_note_reference_limit",
            "One owner exceeded the bounded source-note reference limit; "
            "its associations remained evidence-only.",
            target_ref=owner_id,
            metadata={
                "reference_count": len(relationships),
                "limit": _MAX_SOURCE_NOTE_REFERENCES,
            },
        )

    candidate_ids = set(declared_by_candidate)
    for element in ir.elements:
        if (
            _is_source_note_owner(element)
            or element.type.casefold() in {"header", "footer"}
            or element.page_id not in owners_by_page
        ):
            continue
        if _source_note_kind(element, set()) is not None:
            candidate_ids.add(element.id)

    candidates_by_page: dict[str, list[str]] = defaultdict(list)
    for candidate_id in candidate_ids:
        candidates_by_page[elements[candidate_id].page_id].append(candidate_id)

    blocked_candidates: set[str] = set()
    for page_id, page_candidate_ids in candidates_by_page.items():
        if len(page_candidate_ids) > _MAX_SOURCE_NOTE_CANDIDATES_PER_PAGE:
            blocked_candidates.update(page_candidate_ids)
            _concern(
                ir,
                "source_note_page_candidate_limit",
                "One page exceeded the bounded source-note candidate limit; "
                "its candidates remained evidence-only.",
                metadata={
                    "page_id": page_id,
                    "candidate_count": len(page_candidate_ids),
                    "limit": _MAX_SOURCE_NOTE_CANDIDATES_PER_PAGE,
                },
            )
            continue
        same_text: dict[str, list[str]] = defaultdict(list)
        for candidate_id in page_candidate_ids:
            same_text[
                _normalized_text_digest(elements[candidate_id].value)
            ].append(candidate_id)
        for digest, same_text_ids in same_text.items():
            if (
                len(same_text_ids)
                <= _MAX_SAME_TEXT_SOURCE_NOTE_CANDIDATES
            ):
                continue
            blocked_candidates.update(same_text_ids)
            _concern(
                ir,
                "source_note_same_text_candidate_limit",
                "One page exceeded the bounded same-text source-note limit; "
                "those candidates remained evidence-only.",
                metadata={
                    "page_id": page_id,
                    "normalized_text_sha256": digest,
                    "candidate_count": len(same_text_ids),
                    "limit": _MAX_SAME_TEXT_SOURCE_NOTE_CANDIDATES,
                },
            )

    emitted_concerns: Counter[str] = Counter()
    suppressed_concerns: dict[str, Counter[str]] = defaultdict(Counter)

    def emit_note_concern(
        code: str,
        message: str,
        *,
        page_id: str,
        source_ref: str | None = None,
        target_ref: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if emitted_concerns[page_id] >= _MAX_SOURCE_NOTE_CONCERNS_PER_PAGE:
            suppressed_concerns[page_id][code] += 1
            return
        if _concern(
            ir,
            code,
            message,
            source_ref=source_ref,
            target_ref=target_ref,
            metadata=metadata,
        ):
            emitted_concerns[page_id] += 1

    accepted: list[dict[str, Any]] = []
    for candidate_id in sorted(candidate_ids):
        candidate = elements[candidate_id]
        page_id = candidate.page_id
        if (
            candidate_id in blocked_candidates
            or page_id in blocked_pages
        ):
            continue
        relationships = declared_by_candidate.get(candidate_id, [])
        declared_types = {
            relationship.type for relationship in relationships
        }
        note_kind = _source_note_kind(candidate, declared_types)
        if note_kind is None:
            emit_note_concern(
                "source_note_role_ambiguous",
                "A source-note candidate had conflicting or unsupported "
                "roles and remained evidence-only.",
                page_id=page_id,
                source_ref=candidate.id,
                metadata={"declared_role_count": len(declared_types)},
            )
            continue
        value = _raw_source_value_view(candidate, evidence_by_id)
        if not isinstance(value, str) or not value.strip():
            emit_note_concern(
                "source_note_value_unsupported",
                "A source-note candidate had no supported source-visible text "
                "and remained evidence-only.",
                page_id=page_id,
                source_ref=candidate.id,
                metadata={"value_type": type(value).__name__},
            )
            continue
        byte_count, oversized = _bounded_utf8_size(
            value,
            _MAX_SOURCE_NOTE_BYTES,
        )
        if oversized:
            emit_note_concern(
                "source_note_byte_limit",
                "An oversized source-note candidate remained evidence-only.",
                page_id=page_id,
                source_ref=candidate.id,
                metadata={
                    "observed_bytes_at_least": byte_count,
                    "limit": _MAX_SOURCE_NOTE_BYTES,
                },
            )
            continue
        if not _has_accepted_raw_source_provenance(
            candidate,
            evidence_by_id,
        ):
            emit_note_concern(
                "source_note_untrusted_provenance",
                "A generated, model-derived, or ungrounded source-note "
                "candidate remained evidence-only.",
                page_id=page_id,
                source_ref=candidate.id,
            )
            continue
        note_box = bbox_for(candidate.id)
        declared_owner_ids = {
            relationship.target_id for relationship in relationships
        }
        if len(declared_owner_ids) > 1:
            emit_note_concern(
                "source_note_owner_ambiguous",
                "A source-note candidate was declared by multiple owners and "
                "remained evidence-only.",
                page_id=page_id,
                source_ref=candidate.id,
                metadata={"owner_count": len(declared_owner_ids)},
            )
            continue

        owner_id: str | None = None
        basis = "geometry_and_source_evidence"
        source_relationship: RelationshipRecord | None = None
        if declared_owner_ids:
            proposed_owner_id = next(iter(declared_owner_ids))
            owner = elements[proposed_owner_id]
            valid, reason = _external_source_note_geometry(
                note_box,
                bbox_for(proposed_owner_id),
            )
            if (
                proposed_owner_id in blocked_owners
                or proposed_owner_id not in presented
                or owner.page_id != candidate.page_id
                or not valid
            ):
                emit_note_concern(
                    "declared_source_note_not_promoted",
                    "A declared source note lacked agreeing same-page "
                    "external geometry and remained evidence-only.",
                    page_id=page_id,
                    source_ref=candidate.id,
                    target_ref=proposed_owner_id,
                    metadata={
                        "reason": (
                            reason
                            if proposed_owner_id not in blocked_owners
                            else "owner_reference_limit"
                        )
                    },
                )
                continue
            other_plausible_owner_ids = []
            for alternative_owner_id in owners_by_page.get(page_id, ()):
                if alternative_owner_id == proposed_owner_id:
                    continue
                alternative_valid, _alternative_reason = (
                    _external_source_note_geometry(
                        note_box,
                        bbox_for(alternative_owner_id),
                    )
                )
                if alternative_valid:
                    other_plausible_owner_ids.append(
                        alternative_owner_id
                    )
            if other_plausible_owner_ids:
                emit_note_concern(
                    "source_note_owner_ambiguous",
                    "A declared source-note candidate also matched another "
                    "plausible owner and remained evidence-only.",
                    page_id=page_id,
                    source_ref=candidate.id,
                    target_ref=proposed_owner_id,
                    metadata={
                        "owner_count": (
                            1 + len(other_plausible_owner_ids)
                        )
                    },
                )
                continue
            owner_id = proposed_owner_id
            source_relationship = min(
                relationships,
                key=lambda relationship: relationship.id,
            )
            basis = "graph_and_geometry"
        else:
            plausible_owner_ids = []
            for proposed_owner_id in owners_by_page.get(page_id, ()):
                if proposed_owner_id in blocked_owners:
                    continue
                valid, _reason = _external_source_note_geometry(
                    note_box,
                    bbox_for(proposed_owner_id),
                )
                if valid:
                    plausible_owner_ids.append(proposed_owner_id)
            if len(plausible_owner_ids) != 1:
                emit_note_concern(
                    (
                        "source_note_owner_ambiguous"
                        if plausible_owner_ids
                        else "source_note_owner_unresolved"
                    ),
                    (
                        "A source-note candidate matched multiple plausible "
                        "owners and remained independently presented."
                        if plausible_owner_ids
                        else "A source-note candidate had no unique nearby "
                        "owner and remained independently presented."
                    ),
                    page_id=page_id,
                    source_ref=candidate.id,
                    metadata={"owner_count": len(plausible_owner_ids)},
                )
                continue
            owner_id = plausible_owner_ids[0]
            if _raw_source_name(candidate, evidence_by_id) == "ocr":
                basis = "ocr_and_geometry"

        assert owner_id is not None
        raw_link_count = _raw_source_note_link_candidate_count(candidate)
        links = [
            link
            for link in _source_note_links(candidate)
            if link["target"] in value
        ]
        raw_label = str(
            candidate.properties.get("raw_label") or ""
        ).casefold()
        raw_record = candidate.properties.get("raw_record")
        raw_meta = (
            raw_record.get("meta")
            if isinstance(raw_record, Mapping)
            else None
        )
        annotation_backed = bool(
            "annotation" in raw_label
            or (
                isinstance(raw_meta, Mapping)
                and isinstance(
                    raw_meta.get("layout_source_note_pdf_annotation"),
                    Mapping,
                )
            )
        )
        if annotation_backed and not any(
            link["target"] in value for link in links
        ):
            emit_note_concern(
                "source_note_annotation_text_mismatch",
                "An annotation target was not literally present in the "
                "candidate's source-visible text and remained evidence-only.",
                page_id=page_id,
                source_ref=candidate.id,
                target_ref=owner_id,
                metadata={"accepted_link_count": len(links)},
            )
            continue
        if source_relationship is None and links:
            basis = (
                "annotation_and_geometry"
                if annotation_backed
                else "source_link_and_geometry"
            )
        if raw_link_count > len(links):
            emit_note_concern(
                "source_note_link_rejected",
                "One or more source-note link targets failed the bounded "
                "safe-URL contract and were omitted.",
                page_id=page_id,
                source_ref=candidate.id,
                target_ref=owner_id,
                metadata={
                    "candidate_count": raw_link_count,
                    "accepted_count": len(links),
                },
            )
        declared_rank = math.inf
        if source_relationship is not None:
            declared_rank = _relationship_order_key(
                source_relationship,
                candidate,
                relationships.index(source_relationship),
            )[0]
        accepted.append(
            {
                "candidate": candidate,
                "owner_id": owner_id,
                "kind": note_kind,
                "value": value,
                "bbox": note_box,
                "basis": basis,
                "links": links,
                "annotation_backed": annotation_backed,
                "source_relationship": source_relationship,
                "declared_rank": declared_rank,
            }
        )

    # A PDF annotation can cover only the URL substring of an already-visible
    # StatLink block. Upgrade that visible physical note with the grounded
    # target instead of presenting a second URL-only note.
    merged_annotation_source_ids: set[str] = set()
    retained_accepted: list[dict[str, Any]] = []
    for record in accepted:
        if (
            not record["annotation_backed"]
            or not record["links"]
        ):
            retained_accepted.append(record)
            continue
        matching_visible = [
            visible
            for visible in accepted
            if (
                visible is not record
                and visible["owner_id"] == record["owner_id"]
                and not visible["annotation_backed"]
                and _intersection_area(
                    visible["bbox"],
                    record["bbox"],
                )
                > 0
                and any(
                    link["target"] in visible["value"]
                    for link in record["links"]
                )
            )
        ]
        if len(matching_visible) == 1:
            visible = matching_visible[0]
            for link in record["links"]:
                if link not in visible["links"]:
                    visible["links"].append(link)
            visible["basis"] = "annotation_and_geometry"
            candidate = record["candidate"]
            merged_annotation_source_ids.add(candidate.id)
            emit_note_concern(
                "source_note_annotation_merged",
                "An annotation-backed URL was merged into its overlapping "
                "source-visible note and projected once.",
                page_id=candidate.page_id,
                source_ref=candidate.id,
                target_ref=str(record["owner_id"]),
                metadata={"visible_candidate_count": 1},
            )
            continue
        if len(matching_visible) > 1:
            candidate = record["candidate"]
            merged_annotation_source_ids.add(candidate.id)
            emit_note_concern(
                "source_note_annotation_ambiguous",
                "An annotation-backed URL overlapped multiple visible notes "
                "and remained evidence-only.",
                page_id=candidate.page_id,
                source_ref=candidate.id,
                target_ref=str(record["owner_id"]),
                metadata={
                    "visible_candidate_count": len(matching_visible)
                },
            )
            continue
        retained_accepted.append(record)
    accepted = retained_accepted

    # Collapse duplicate graph routes only when they describe the same
    # physical text occurrence and agree on one owner.
    accepted_by_page_text: dict[
        tuple[str, str], list[dict[str, Any]]
    ] = defaultdict(list)
    for record in accepted:
        candidate = record["candidate"]
        accepted_by_page_text[
            (
                candidate.page_id,
                _normalized_text_digest(record["value"]),
            )
        ].append(record)
    selected: list[dict[str, Any]] = []
    suppressed_source_ids: set[str] = set(
        merged_annotation_source_ids
    )
    for (_page_id, _digest), records in accepted_by_page_text.items():
        for component in _overlap_components(
            [record["bbox"] for record in records]
        ):
            physical_records = [records[index] for index in component]
            owner_ids = {
                str(record["owner_id"]) for record in physical_records
            }
            if len(owner_ids) > 1:
                representative = min(
                    physical_records,
                    key=lambda record: record["candidate"].id,
                )
                candidate = representative["candidate"]
                emit_note_concern(
                    "source_note_physical_owner_ambiguous",
                    "Equivalent source-note evidence at one physical location "
                    "matched multiple owners and remained evidence-only.",
                    page_id=candidate.page_id,
                    source_ref=candidate.id,
                    metadata={"owner_count": len(owner_ids)},
                )
                continue
            representative = min(
                physical_records,
                key=lambda record: (
                    0 if record["candidate"].id in presented else 1,
                    0 if record["source_relationship"] is not None else 1,
                    -len(record["candidate"].evidence_ids),
                    record["candidate"].id,
                ),
            )
            selected.append(representative)
            duplicate_ids = {
                record["candidate"].id
                for record in physical_records
                if record is not representative
            }
            if duplicate_ids:
                suppressed_source_ids.update(duplicate_ids)
                candidate = representative["candidate"]
                emit_note_concern(
                    "duplicate_source_note_evidence",
                    "Equivalent source-note routes were retained as evidence "
                    "and projected once.",
                    page_id=candidate.page_id,
                    source_ref=candidate.id,
                    target_ref=str(representative["owner_id"]),
                    metadata={
                        "duplicate_count": len(duplicate_ids),
                        "duplicate_element_ids": sorted(duplicate_ids),
                    },
                )

    selected.sort(
        key=lambda record: (
            elements[str(record["owner_id"])].page_id,
            elements[str(record["owner_id"])].reading_order
            if elements[str(record["owner_id"])].reading_order is not None
            else math.inf,
            record["declared_rank"],
            float(record["bbox"]["y"]),
            float(record["bbox"]["x"]),
            record["candidate"].id,
        )
    )

    projected_by_owner: dict[
        str, list[tuple[ElementRecord, dict[str, Any], RelationshipType]]
    ] = defaultdict(list)
    removed_presentation_ids: dict[str, set[str]] = defaultdict(set)
    changed_page_ids: set[str] = set()
    existing_relationship_ids = {
        relationship.id for relationship in ir.relationships
    }
    for record in selected:
        candidate: ElementRecord = record["candidate"]
        owner_id = str(record["owner_id"])
        owner = elements[owner_id]
        owner_legacy = _legacy_item(owner)
        owner_public_id = str(owner_legacy.get("id") or owner.id)
        existing_legacy = candidate.properties.get("legacy_item")
        if (
            candidate.id in presented
            and isinstance(existing_legacy, Mapping)
            and str(existing_legacy.get("id") or "")
        ):
            public_note_id = str(existing_legacy["id"])
            public_element = candidate
        else:
            physical_presented_matches: list[ElementRecord] = []
            for presented_id in page_by_id[
                candidate.page_id
            ].presentation_element_ids:
                presented_element = elements[presented_id]
                if (
                    presented_element.id == owner.id
                    or _is_source_note_owner(presented_element)
                    or presented_element.type.casefold()
                    in {"header", "footer"}
                    or bool(
                        presented_element.properties.get("generated")
                        or presented_element.properties.get(
                            RAW_GENERATION_PROVENANCE_PROPERTY
                        )
                    )
                ):
                    continue
                presented_legacy = presented_element.properties.get(
                    "legacy_item"
                )
                if not isinstance(presented_legacy, Mapping):
                    continue
                if (
                    _normalized_text(presented_legacy.get("value"))
                    != _normalized_text(record["value"])
                    or str(
                        presented_legacy.get("source") or ""
                    ).casefold()
                    not in {
                        "native",
                        "ocr",
                        "mixed",
                        "vector",
                        "embedded",
                        "recovered",
                    }
                ):
                    continue
                presented_box = bbox_for(presented_element.id)
                smaller = min(
                    _area(presented_box),
                    _area(record["bbox"]),
                )
                overlap = (
                    _intersection_area(
                        presented_box,
                        record["bbox"],
                    )
                    / smaller
                    if presented_box is not None and smaller > 0
                    else 0.0
                )
                if overlap >= 0.80:
                    physical_presented_matches.append(
                        presented_element
                    )
            if len(physical_presented_matches) > 1:
                emit_note_concern(
                    "source_note_public_identity_ambiguous",
                    "A source-note occurrence matched multiple presented "
                    "items and remained evidence-only.",
                    page_id=candidate.page_id,
                    source_ref=candidate.id,
                    target_ref=owner.id,
                    metadata={
                        "presented_match_count": len(
                            physical_presented_matches
                        )
                    },
                )
                continue
            if physical_presented_matches:
                public_element = physical_presented_matches[0]
                matched_legacy = _legacy_item(public_element)
                public_note_id = str(
                    matched_legacy.get("id") or public_element.id
                )
            else:
                public_note_id = _stable_source_note_public_id(
                    owner_public_id,
                    candidate,
                    record["bbox"],
                )
                desired_element_id = _compatibility_element_id(
                    ir,
                    page_by_id[owner.page_id],
                    public_note_id,
                )
                public_element = elements.get(desired_element_id)
                if public_element is None:
                    public_element = candidate.model_copy(deep=True)
                    public_element.id = desired_element_id
                    public_element.evidence_ids = []
                    public_element.properties.pop("raw_refs", None)
                    public_element.properties.pop("raw_label", None)
                    public_element.properties[
                        "projection_source_element_id"
                    ] = candidate.id
                    ir.elements.append(public_element)
                    elements[public_element.id] = public_element
                    page_by_id[owner.page_id].element_ids.append(
                        public_element.id
                    )
                    projection_region = next(
                        region
                        for region in ir.regions
                        if region.page_id == owner.page_id
                    )
                    projection_region.element_ids.append(
                        public_element.id
                    )

        relationship_type: RelationshipType = record["kind"]
        public_relationship_id = _public_source_note_relationship_id(
            relationship_type,
            public_note_id,
            owner_public_id,
        )
        public_note = _legacy_item(public_element)
        public_note.pop("source_note_of", None)
        public_note.pop("footnote_of", None)
        public_note.update(
            {
                "id": public_note_id,
                "type": (
                    "source_note"
                    if relationship_type
                    is RelationshipType.SOURCE_NOTE_OF
                    else "footnote"
                ),
                "reading_order": 0,
                "value": record["value"],
                "md": (
                    candidate.markdown
                    if isinstance(candidate.markdown, str)
                    and _normalized_text(candidate.markdown)
                    == _normalized_text(record["value"])
                    else record["value"]
                ),
                "bbox": record["bbox"],
                "source": _raw_source_name(candidate, evidence_by_id),
                "confidence": _raw_source_confidence(
                    candidate,
                    evidence_by_id,
                ),
                (
                    "source_note_of"
                    if relationship_type
                    is RelationshipType.SOURCE_NOTE_OF
                    else "footnote_of"
                ): owner_public_id,
                "relationship_id": public_relationship_id,
                "relationship_type": relationship_type.value,
                "relationship_basis": record["basis"],
            }
        )
        if record["links"]:
            public_note["links"] = deepcopy(record["links"])
        else:
            public_note.pop("links", None)

        public_element.type = str(public_note["type"])
        public_element.value = record["value"]
        public_element.markdown = str(public_note["md"])
        public_element.presentation_role = "primary"
        public_element.properties["legacy_item"] = public_note
        public_element.properties["source_note_projection"] = {
            "story": "P03-US03",
            "relationship_id": public_relationship_id,
            "source_relationship_id": (
                record["source_relationship"].id
                if record["source_relationship"] is not None
                else None
            ),
            "basis": record["basis"],
        }

        if public_relationship_id not in existing_relationship_ids:
            ir.relationships.append(
                RelationshipRecord(
                    id=public_relationship_id,
                    type=relationship_type,
                    source_id=public_element.id,
                    target_id=owner.id,
                    # The assertion is a deterministic layout projection.
                    # Source evidence remains attached to the retained raw
                    # candidate; copying those IDs to a compatibility clone
                    # would violate IR evidence ownership.
                    evidence_ids=[],
                    metadata={
                        "story": "P03-US03",
                        "basis": record["basis"],
                        "layout_projection_managed": True,
                        "canonical_presentation_inert": True,
                        "source_relationship_id": (
                            record["source_relationship"].id
                            if record["source_relationship"] is not None
                            else None
                        ),
                    },
                )
            )
            existing_relationship_ids.add(public_relationship_id)

        candidate.presentation_role = (
            "primary"
            if candidate.id == public_element.id
            else "diagnostic"
        )
        projected_by_owner[owner.id].append(
            (public_element, public_note, relationship_type)
        )
        removed_presentation_ids[owner.page_id].add(candidate.id)
        removed_presentation_ids[owner.page_id].add(public_element.id)
        changed_page_ids.add(owner.page_id)

    for duplicate_id in suppressed_source_ids:
        duplicate = elements[duplicate_id]
        duplicate.presentation_role = "diagnostic"
        removed_presentation_ids[duplicate.page_id].add(duplicate.id)

    for owner_id, projected_notes in projected_by_owner.items():
        owner = elements[owner_id]
        owner_legacy = _legacy_item(owner)
        owner_public_id = str(owner_legacy.get("id") or owner.id)
        relationships = [
            deepcopy(dict(relationship))
            for relationship in owner_legacy.get("relationships") or []
            if isinstance(relationship, Mapping)
        ]
        source_note_ids: list[str] = []
        footnote_ids: list[str] = []
        new_descriptors: list[dict[str, str]] = []
        for _element, public_note, relationship_type in projected_notes:
            note_id = str(public_note["id"])
            if relationship_type is RelationshipType.SOURCE_NOTE_OF:
                source_note_ids.append(note_id)
            else:
                footnote_ids.append(note_id)
            new_descriptors.append(
                {
                    "id": str(public_note["relationship_id"]),
                    "type": relationship_type.value,
                    "source_id": note_id,
                    "target_id": owner_public_id,
                }
            )
        descriptor_ids = {
            descriptor["id"] for descriptor in new_descriptors
        }
        relationships = [
            relationship
            for relationship in relationships
            if relationship.get("id") not in descriptor_ids
        ]
        relationships.extend(new_descriptors)
        if source_note_ids:
            owner_legacy["source_note_ids"] = source_note_ids
        else:
            owner_legacy.pop("source_note_ids", None)
        if footnote_ids:
            owner_legacy["footnote_ids"] = footnote_ids
        else:
            owner_legacy.pop("footnote_ids", None)
        owner_legacy["relationships"] = relationships
        owner_legacy["layout_source_notes_projected"] = True
        owner.properties["legacy_item"] = owner_legacy
        owner.properties["source_note_projection"] = {
            "story": "P03-US03",
            "source_note_count": len(source_note_ids),
            "footnote_count": len(footnote_ids),
        }
    notes_after_anchor: dict[str, list[str]] = defaultdict(list)
    for page in ir.pages:
        page_owner_ids = [
            owner_id
            for owner_id in projected_by_owner
            if elements[owner_id].page_id == page.id
        ]
        if not page_owner_ids:
            continue
        positions = {
            element_id: index
            for index, element_id in enumerate(
                page.presentation_element_ids
            )
        }
        for owner_id in page_owner_ids:
            anchor_id = owner_id
            owner_public_id = str(
                _legacy_item(elements[owner_id]).get("id") or owner_id
            )
            owner_position = positions.get(owner_id)
            if owner_position is not None:
                for following_id in page.presentation_element_ids[
                    owner_position + 1 :
                ]:
                    following_legacy = _legacy_item(elements[following_id])
                    if (
                        str(following_legacy.get("type") or "").casefold()
                        != "caption"
                        or following_legacy.get("caption_of")
                        != owner_public_id
                    ):
                        break
                    anchor_id = following_id
            notes_after_anchor[anchor_id].extend(
                note.id
                for note, _legacy, _kind in projected_by_owner[owner_id]
            )

    for page in ir.pages:
        if page.id not in changed_page_ids:
            continue
        removed_ids = removed_presentation_ids[page.id]
        rebuilt_ids: list[str] = []
        for element_id in page.presentation_element_ids:
            if element_id in removed_ids:
                continue
            rebuilt_ids.append(element_id)
            rebuilt_ids.extend(notes_after_anchor.get(element_id, ()))
        page.presentation_element_ids = rebuilt_ids
        for reading_order, element_id in enumerate(
            page.presentation_element_ids
        ):
            element = elements[element_id]
            element.reading_order = reading_order
            legacy = element.properties.get("legacy_item")
            if isinstance(legacy, Mapping):
                updated = deepcopy(dict(legacy))
                updated["reading_order"] = reading_order
                element.properties["legacy_item"] = updated

    for page_id, suppressed_codes in suppressed_concerns.items():
        _concern(
            ir,
            "source_note_concerns_truncated",
            "Source-note diagnostics exceeded the bounded page limit; a "
            "sanitized aggregate was retained.",
            metadata={
                "page_id": page_id,
                "suppressed_count": sum(suppressed_codes.values()),
                "suppressed_by_code": dict(sorted(suppressed_codes.items())),
                "page_limit": _MAX_SOURCE_NOTE_CONCERNS_PER_PAGE,
            },
        )


def apply_layout_projection(
    ir: DocumentIR,
    settings: Settings,
    *,
    text_run_evidence: Any | None = None,
    form_evidence: Any | None = None,
    form_metrics: MutableMapping[str, float] | None = None,
    outline_evidence: Any | None = None,
    outline_metrics: MutableMapping[str, Any] | None = None,
) -> DocumentIR:
    """Apply enabled Phase 03 projections while preserving flag-off parity."""

    working = ir.model_copy(deep=True)
    cross_projection_ambiguous_ids = frozenset()
    common_overflow_caption_ids = frozenset()
    if (
        settings.layout_table_captions_enabled
        and settings.layout_visual_relationships_enabled
    ):
        (
            cross_projection_ambiguous,
            common_overflow,
        ) = _cross_projection_caption_preflight(working)
        cross_projection_ambiguous_ids = frozenset(
            cross_projection_ambiguous
        )
        common_overflow_caption_ids = frozenset(
            common_overflow
        )
    if settings.layout_table_captions_enabled:
        _project_table_captions(
            working,
            cross_projection_ambiguous_ids=(
                cross_projection_ambiguous_ids
            ),
            common_overflow_caption_ids=(
                common_overflow_caption_ids
            ),
        )
    if settings.layout_visual_relationships_enabled:
        predecessor = working.model_copy(deep=True)
        try:
            _project_visual_relationships(
                working,
                cross_projection_ambiguous_ids=(
                    cross_projection_ambiguous_ids
                ),
                common_overflow_caption_ids=(
                    common_overflow_caption_ids
                ),
            )
        except Exception as exc:
            working = predecessor
            _concern(
                working,
                "visual_relationship_projection_failed_closed",
                "Visual relationship projection failed closed.",
                metadata={"error_type": type(exc).__name__},
            )
    if settings.layout_source_notes_enabled:
        # This mutation precedes the rollback snapshot. An unexpected
        # projection exception must not reactivate unvalidated raw
        # relationships in canonical output.
        _make_source_note_relationships_canonical_inert(working)
        predecessor = working.model_copy(deep=True)
        try:
            _project_source_notes(working)
        except Exception as exc:
            working = predecessor
            _concern(
                working,
                "source_note_projection_failed_closed",
                "Source-note projection failed closed.",
                metadata={"error_type": type(exc).__name__},
            )
    if settings.layout_relationship_order_enabled:
        predecessor: DocumentIR | None = None
        try:
            predecessor = working.model_copy(deep=True)
            from app.services.layout_order import project_relationship_order

            project_relationship_order(working)
            working = DocumentIR.model_validate(
                working.model_dump(mode="json")
            )
        except Exception as exc:
            if predecessor is not None:
                working = predecessor
            _concern(
                working,
                "relationship_order_projection_failed_closed",
                "Relationship-aware reading order failed closed.",
                metadata={"error_type": type(exc).__name__},
            )
    if settings.layout_text_run_semantics_enabled:
        predecessor = working.model_copy(deep=True)
        try:
            from app.services.text_run_semantics import (
                project_text_run_semantics,
            )

            working = project_text_run_semantics(
                working,
                text_run_evidence,
            )
            working = DocumentIR.model_validate(
                working.model_dump(mode="json")
            )
        except Exception as exc:
            working = predecessor
            _concern(
                working,
                "text_run_projection_failed_closed",
                "Text-run semantics projection failed closed.",
                metadata={"error_type": type(exc).__name__},
            )
    if settings.layout_forms_enabled:
        predecessor = working.model_copy(deep=True)
        try:
            from app.services.form_semantics import project_form_semantics

            working = project_form_semantics(
                working,
                form_evidence,
                metrics=form_metrics,
            )
            working = DocumentIR.model_validate(
                working.model_dump(mode="json")
            )
        except Exception as exc:
            working = predecessor
            _concern(
                working,
                "form_projection_failed_closed",
                "Form semantics projection failed closed.",
                metadata={"error_type": type(exc).__name__},
            )
    if settings.layout_outline_structure_enabled:
        predecessor = working.model_copy(deep=True)
        try:
            from app.services.outline_structure import (
                project_outline_structure,
            )

            working = project_outline_structure(
                working,
                outline_evidence,
                metrics=outline_metrics,
            )
            working = DocumentIR.model_validate(
                working.model_dump(mode="json")
            )
        except Exception as exc:
            working = predecessor
            _concern(
                working,
                "outline_projection_failed_closed",
                "Outline structure projection failed closed.",
                metadata={"error_type": type(exc).__name__},
            )
    return DocumentIR.model_validate(working.model_dump(mode="json"))
