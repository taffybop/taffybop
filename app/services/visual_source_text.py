"""Recover source-grounded text and simple visual roles from born-digital PDFs.

The visual OCR path remains authoritative for raster-only figures.  This module
adds a narrower seam for PDF text that is physically printed inside an owned
visual region.  It never interpolates values, assigns semantic relationships,
or uses nearby prose as figure content.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any, Literal

import pdfplumber

from app.services.visual_contracts import (
    ChartAxis,
    ChartPanel,
    ChartTick,
    VisualBoundingBox,
    VisualConcern,
    VisualEvidence,
    VisualLabel,
    VisualProvenance,
    VisualStructure,
)


_MAX_SOURCE_WORDS = 512
_MAX_OWNED_VISUAL_CHILDREN = 32
_MAX_COMPACT_OCR_LINES = 3
_OWNED_VISUAL_TOLERANCE_PT = 1.0
_COMPACT_OCR_CONFIDENCE_FLOOR = 0.90
_COMPACT_TEXTUAL_CLASSES = frozenset({"icon", "logo"})
_MAX_UNCLASSIFIED_COMPACT_VISUAL_SIDE_PT = 96.0
_MAX_UNCLASSIFIED_COMPACT_VISUAL_AREA_PT2 = 9_216.0
_MIN_UNCLASSIFIED_OCR_WIDTH_RATIO = 0.40
_MIN_UNCLASSIFIED_OCR_UNION_AREA_RATIO = 0.08
_MAX_VISUAL_PROOF_IDENTIFIER_BYTES = 2_048
_MAX_VISUAL_PROOF_TEXT_BYTES = 16_384
_MAX_VISUAL_PROOF_PAYLOAD_BYTES = 512 * 1_024
_MAX_VISUAL_PROOF_CHARACTER_IDS = 65_536
_MAX_VISUAL_PROOF_RELATIONSHIPS = 128
_YEAR_RE = re.compile(
    r"^(?:(?:19|20)\d{2}|(?:CY|FY)\d{2,4}|Q[1-4]['’]?\d{2}(?:\s+ARR)?)$",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(
    r"^[+-]?(?:[$€£¥₹])?(?:(?:\d{1,3}(?:,\d{3})+)|\d+)"
    r"(?:\.\d+)?(?:[%BMK])?$",
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(r"(?<!\w)[+-]?\d+(?:\.\d+)?%(?!\w)")
_CURRENCY_RE = re.compile(
    r"(?<!\w)[$€£¥₹]\s*\d+(?:\.\d+)?(?:[BMK])?(?!\w)",
    re.IGNORECASE,
)
_YEAR_SEARCH_RE = re.compile(
    r"(?<!\w)(?:(?:19|20)\d{2}|(?:CY|FY)\d{2,4}|Q[1-4]['’]?\d{2})(?!\w)",
    re.IGNORECASE,
)
_NUMERIC_SEARCH_RE = re.compile(
    r"(?<!\w)[+-]?(?:[$€£¥₹])?\d+(?:[,.]\d+)*(?:[%BMK])?(?!\w)",
    re.IGNORECASE,
)
_CHART_DOMAIN_RE = re.compile(
    r"\b(?:percentile|growth|mortality|energy|electricity|fuel|hours|"
    r"country|countries|total|world|manufacturing|deployment|consumption)\b",
    re.IGNORECASE,
)


def _stable_id(prefix: str, *parts: Any) -> str:
    payload = json.dumps(
        parts,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(payload).hexdigest()[:24]}"


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _box(value: Any) -> VisualBoundingBox | None:
    if not isinstance(value, Mapping):
        return None
    x = _number(value.get("x"))
    y = _number(value.get("y"))
    width = _number(value.get("width", value.get("w")))
    height = _number(value.get("height", value.get("h")))
    unit = str(value.get("unit") or "pt")
    if (
        None in {x, y, width, height}
        or unit != "pt"
        or min(x or 0.0, y or 0.0) < 0
        or (width or 0.0) <= 0
        or (height or 0.0) <= 0
    ):
        return None
    return VisualBoundingBox(
        x=float(x),
        y=float(y),
        width=float(width),
        height=float(height),
        unit="pt",
    )


def _bounded_proof_string(value: Any, *, maximum: int) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        return None
    return value if len(encoded) <= maximum else None


def _proof_bbox(value: Any) -> dict[str, Any] | None:
    box = _box(value)
    return box.model_dump(mode="json") if box is not None else None


def _bounded_lineage_digest(payload: Mapping[str, Any]) -> str | None:
    try:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, UnicodeEncodeError, ValueError):
        return None
    if len(encoded) > _MAX_VISUAL_PROOF_PAYLOAD_BYTES:
        return None
    return hashlib.sha256(encoded).hexdigest()


def owned_visual_source_lineage_sha256(
    *,
    source_sha256: Any,
    page_index: Any,
    coordinate_unit: Any,
    owned_child_ids: Any,
    owned_children: Any,
    source_line_ids: Any,
    occurrences: Any,
    lines: Any,
) -> str | None:
    """Hash only a bounded, whitelisted native visual-source proof."""

    if (
        not isinstance(source_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None
        or type(page_index) is not int
        or page_index < 1
        or coordinate_unit != "pt"
        or not isinstance(owned_child_ids, list)
        or not 1 <= len(owned_child_ids) <= _MAX_OWNED_VISUAL_CHILDREN
        or not isinstance(owned_children, list)
        or len(owned_children) != len(owned_child_ids)
        or not isinstance(source_line_ids, list)
        or len(source_line_ids) != len(owned_child_ids)
        or not isinstance(occurrences, list)
        or len(occurrences) != len(owned_child_ids)
        or not isinstance(lines, list)
        or len(lines) != len(owned_child_ids)
    ):
        return None

    proof_bytes = 256

    def proof_string(value: Any, *, maximum: int) -> str | None:
        nonlocal proof_bytes
        result = _bounded_proof_string(value, maximum=maximum)
        if result is None:
            return None
        proof_bytes += len(result.encode("utf-8")) + 4
        return result if proof_bytes <= _MAX_VISUAL_PROOF_PAYLOAD_BYTES else None

    def reserve_record() -> bool:
        nonlocal proof_bytes
        proof_bytes += 256
        return proof_bytes <= _MAX_VISUAL_PROOF_PAYLOAD_BYTES

    def identifiers(values: list[Any]) -> list[str] | None:
        result: list[str] = []
        for value in values:
            bounded = proof_string(
                value, maximum=_MAX_VISUAL_PROOF_IDENTIFIER_BYTES
            )
            if bounded is None:
                return None
            result.append(bounded)
        return result if len(set(result)) == len(result) else None

    bounded_child_ids = identifiers(owned_child_ids)
    bounded_line_ids = identifiers(source_line_ids)
    if bounded_child_ids is None or bounded_line_ids is None:
        return None

    projected_children: list[dict[str, Any]] = []
    for child in owned_children:
        if (
            not isinstance(child, Mapping)
            or len(child) != 5
            or set(child) != {
                "id",
                "text_sha256",
                "normalized_text_sha256",
                "bbox",
                "source_line_id",
            }
            or not reserve_record()
        ):
            return None
        child_id = proof_string(
            child.get("id"), maximum=_MAX_VISUAL_PROOF_IDENTIFIER_BYTES
        )
        source_line_id = proof_string(
            child.get("source_line_id"),
            maximum=_MAX_VISUAL_PROOF_IDENTIFIER_BYTES,
        )
        text_sha256 = child.get("text_sha256")
        normalized_sha256 = child.get("normalized_text_sha256")
        bbox = _proof_bbox(child.get("bbox"))
        if (
            child_id is None
            or child_id not in bounded_child_ids
            or source_line_id is None
            or source_line_id not in bounded_line_ids
            or not isinstance(text_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", text_sha256) is None
            or not isinstance(normalized_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", normalized_sha256) is None
            or bbox is None
        ):
            return None
        projected_children.append(
            {
                "id": child_id,
                "text_sha256": text_sha256,
                "normalized_text_sha256": normalized_sha256,
                "bbox": bbox,
                "source_line_id": source_line_id,
            }
        )

    projected_occurrences: list[dict[str, Any]] = []
    all_character_ids: set[str] = set()
    for occurrence in occurrences:
        if (
            not isinstance(occurrence, Mapping)
            or len(occurrence) != 12
            or set(occurrence) != {
                "id",
                "occurrence_id",
                "text",
                "value",
                "bbox",
                "confidence",
                "word_count",
                "source",
                "accepted",
                "selected",
                "source_line_id",
                "source_character_ids",
            }
            or not reserve_record()
        ):
            return None
        occurrence_id = proof_string(
            occurrence.get("occurrence_id"),
            maximum=_MAX_VISUAL_PROOF_IDENTIFIER_BYTES,
        )
        source_line_id = proof_string(
            occurrence.get("source_line_id"),
            maximum=_MAX_VISUAL_PROOF_IDENTIFIER_BYTES,
        )
        text = proof_string(
            occurrence.get("text"), maximum=_MAX_VISUAL_PROOF_TEXT_BYTES
        )
        value = proof_string(
            occurrence.get("value"), maximum=_MAX_VISUAL_PROOF_TEXT_BYTES
        )
        bbox = _proof_bbox(occurrence.get("bbox"))
        character_ids = occurrence.get("source_character_ids")
        if (
            occurrence.get("id") != occurrence_id
            or occurrence_id is None
            or source_line_id is None
            or source_line_id not in bounded_line_ids
            or text is None
            or value != text
            or bbox is None
            or _number(occurrence.get("confidence")) != 1.0
            or type(occurrence.get("word_count")) is not int
            or occurrence.get("word_count") < 1
            or occurrence.get("source") != "native"
            or occurrence.get("accepted") is not True
            or occurrence.get("selected") is not True
            or not isinstance(character_ids, list)
            or not character_ids
            or len(character_ids) > _MAX_VISUAL_PROOF_CHARACTER_IDS
        ):
            return None
        bounded_character_ids = identifiers(character_ids)
        if (
            bounded_character_ids is None
            or all_character_ids.intersection(bounded_character_ids)
            or len(all_character_ids) + len(bounded_character_ids)
            > _MAX_VISUAL_PROOF_CHARACTER_IDS
        ):
            return None
        all_character_ids.update(bounded_character_ids)
        projected_occurrences.append(
            {
                "id": occurrence_id,
                "occurrence_id": occurrence_id,
                "text": text,
                "value": value,
                "bbox": bbox,
                "confidence": 1.0,
                "word_count": occurrence["word_count"],
                "source": "native",
                "accepted": True,
                "selected": True,
                "source_line_id": source_line_id,
                "source_character_ids": bounded_character_ids,
            }
        )

    projected_lines: list[dict[str, Any]] = []
    for line in lines:
        if (
            not isinstance(line, Mapping)
            or len(line) != 4
            or set(line)
            != {"text", "bbox", "source_token_ids", "source_line_id"}
            or not reserve_record()
        ):
            return None
        text = proof_string(
            line.get("text"), maximum=_MAX_VISUAL_PROOF_TEXT_BYTES
        )
        bbox = _proof_bbox(line.get("bbox"))
        source_line_id = proof_string(
            line.get("source_line_id"),
            maximum=_MAX_VISUAL_PROOF_IDENTIFIER_BYTES,
        )
        source_token_ids = line.get("source_token_ids")
        bounded_token_ids = (
            identifiers(source_token_ids)
            if isinstance(source_token_ids, list)
            else None
        )
        if (
            text is None
            or bbox is None
            or source_line_id is None
            or source_line_id not in bounded_line_ids
            or bounded_token_ids is None
            or len(bounded_token_ids) != 1
        ):
            return None
        projected_lines.append(
            {
                "text": text,
                "bbox": bbox,
                "source_token_ids": bounded_token_ids,
                "source_line_id": source_line_id,
            }
        )

    return _bounded_lineage_digest(
        {
            "source_sha256": source_sha256,
            "page_index": page_index,
            "coordinate_unit": coordinate_unit,
            "owned_child_ids": bounded_child_ids,
            "owned_children": projected_children,
            "source_line_ids": bounded_line_ids,
            "occurrences": projected_occurrences,
            "lines": projected_lines,
        }
    )


def compact_visual_overlay_lineage_sha256(
    *,
    source_sha256: Any,
    page_index: Any,
    coordinate_unit: Any,
    source_child_ids: Any,
    source_line_ids: Any,
    children: Any,
) -> str | None:
    """Hash a bounded projection of compact visual native-overlay proof."""

    if (
        not isinstance(source_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None
        or type(page_index) is not int
        or page_index < 1
        or coordinate_unit != "pt"
        or not isinstance(source_child_ids, list)
        or not 1 <= len(source_child_ids) <= _MAX_OWNED_VISUAL_CHILDREN
        or not isinstance(source_line_ids, list)
        or len(source_line_ids) != len(source_child_ids)
        or not isinstance(children, list)
        or len(children) != len(source_child_ids)
    ):
        return None

    proof_bytes = 256

    def proof_string(value: Any) -> str | None:
        nonlocal proof_bytes
        result = _bounded_proof_string(
            value, maximum=_MAX_VISUAL_PROOF_IDENTIFIER_BYTES
        )
        if result is None:
            return None
        proof_bytes += len(result.encode("utf-8")) + 4
        return result if proof_bytes <= _MAX_VISUAL_PROOF_PAYLOAD_BYTES else None

    bounded_child_ids: list[str | None] = []
    bounded_line_ids: list[str | None] = []
    for value in source_child_ids:
        bounded_child_ids.append(proof_string(value))
    for value in source_line_ids:
        bounded_line_ids.append(proof_string(value))
    if (
        any(value is None for value in bounded_child_ids)
        or any(value is None for value in bounded_line_ids)
        or len(set(bounded_child_ids)) != len(bounded_child_ids)
        or len(set(bounded_line_ids)) != len(bounded_line_ids)
    ):
        return None
    projected_children: list[dict[str, Any]] = []
    for index, child in enumerate(children):
        proof_bytes += 256
        if (
            not isinstance(child, Mapping)
            or len(child) != 4
            or set(child)
            != {
                "source_child_id",
                "normalized_text_sha256",
                "bbox",
                "source_line_id",
            }
            or proof_bytes > _MAX_VISUAL_PROOF_PAYLOAD_BYTES
        ):
            return None
        child_id = proof_string(child.get("source_child_id"))
        line_id = proof_string(child.get("source_line_id"))
        normalized_sha256 = child.get("normalized_text_sha256")
        bbox = _proof_bbox(child.get("bbox"))
        if (
            child_id != bounded_child_ids[index]
            or line_id != bounded_line_ids[index]
            or not isinstance(normalized_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", normalized_sha256) is None
            or bbox is None
        ):
            return None
        projected_children.append(
            {
                "source_child_id": child_id,
                "normalized_text_sha256": normalized_sha256,
                "bbox": bbox,
                "source_line_id": line_id,
            }
        )
    return _bounded_lineage_digest(
        {
            "source_sha256": source_sha256,
            "page_index": page_index,
            "coordinate_unit": coordinate_unit,
            "native_overlay_source_child_ids": bounded_child_ids,
            "native_overlay_source_line_ids": bounded_line_ids,
            "native_overlay_children": projected_children,
        }
    )


def _inside(
    outer: VisualBoundingBox,
    inner: VisualBoundingBox,
    *,
    tolerance: float = 0.75,
) -> bool:
    return (
        inner.unit == outer.unit
        and inner.x >= outer.x - tolerance
        and inner.y >= outer.y - tolerance
        and inner.x + inner.width <= outer.x + outer.width + tolerance
        and inner.y + inner.height <= outer.y + outer.height + tolerance
    )


def _bounded_text(value: Any, maximum: int = 256) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split()).strip()
    if not text or len(text) > maximum:
        return None
    try:
        if len(text.encode("utf-8")) > maximum * 4:
            return None
    except UnicodeEncodeError:
        return None
    return text


def _value(source: Any, key: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(key, default)
    return getattr(source, key, default)


def _evidence_box(value: Any) -> VisualBoundingBox | None:
    if isinstance(value, Mapping):
        return _box(value)
    return _box(
        {
            "x": _value(value, "x"),
            "y": _value(value, "y"),
            "width": _value(value, "width", _value(value, "w")),
            "height": _value(value, "height", _value(value, "h")),
            "unit": _value(value, "unit", "pt"),
        }
    )


def _normalized_visual_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFC", str(value or "")).casefold()
    return re.sub(r"\s+", "", normalized)


def _overlap_of_smaller(
    first: VisualBoundingBox,
    second: VisualBoundingBox,
) -> float:
    if first.unit != second.unit:
        return 0.0
    left = max(first.x, second.x)
    top = max(first.y, second.y)
    right = min(first.x + first.width, second.x + second.width)
    bottom = min(first.y + first.height, second.y + second.height)
    intersection = max(right - left, 0.0) * max(bottom - top, 0.0)
    smaller = min(first.width * first.height, second.width * second.height)
    return intersection / smaller if smaller > 0 else 0.0


def _source_page(
    source_text_evidence: Any,
    *,
    page_index: int,
    source_document_identity: str | None,
) -> Any | None:
    if (
        source_text_evidence is None
        or _value(source_text_evidence, "usable") is not True
        or type(page_index) is not int
        or page_index < 1
        or not isinstance(source_document_identity, str)
        or re.fullmatch(r"[0-9a-f]{64}", source_document_identity) is None
        or not isinstance(
            _value(source_text_evidence, "source_sha256"),
            str,
        )
        or re.fullmatch(
            r"[0-9a-f]{64}",
            str(_value(source_text_evidence, "source_sha256") or ""),
        )
        is None
        or _value(source_text_evidence, "source_sha256")
        != source_document_identity
    ):
        return None
    pages = _value(source_text_evidence, "pages", ())
    if (
        not isinstance(pages, Sequence)
        or isinstance(pages, (str, bytes, bytearray))
        or len(pages) > 10_000
    ):
        return None
    matching: list[Any] = []
    for page in pages:
        page_identity = _value(page, "page_index")
        page_width = _number(_value(page, "page_width"))
        page_height = _number(_value(page, "page_height"))
        if (
            type(page_identity) is not int
            or page_identity != page_index
            or _value(page, "unit", "pt") != "pt"
            or page_width is None
            or page_width <= 0
            or page_height is None
            or page_height <= 0
        ):
            continue
        matching.append(page)
    return matching[0] if len(matching) == 1 else None


def _source_line_candidates(
    source_page: Any,
    *,
    owner_box: VisualBoundingBox,
    child_box: VisualBoundingBox,
    child_text: str,
) -> list[Any]:
    lines = _value(source_page, "lines", ())
    if (
        not isinstance(lines, Sequence)
        or isinstance(lines, (str, bytes, bytearray))
        or len(lines) > 100_000
    ):
        return []
    normalized_child = _normalized_visual_text(child_text)
    if len(normalized_child) < 2:
        return []
    matches: list[Any] = []
    for line in lines:
        line_text = _bounded_text(_value(line, "text"))
        line_box = _evidence_box(_value(line, "bbox"))
        if (
            line_text is None
            or line_box is None
            or type(_value(line, "page_index")) is not int
            or _value(line, "page_index") != _value(source_page, "page_index")
            or _normalized_visual_text(line_text) != normalized_child
            or not _inside(
                owner_box,
                line_box,
                tolerance=_OWNED_VISUAL_TOLERANCE_PT,
            )
            or _overlap_of_smaller(child_box, line_box) < 0.75
        ):
            continue
        matches.append(line)
    return matches


def _source_characters_for_line(source_page: Any, line: Any) -> list[Any] | None:
    characters = _value(source_page, "characters", ())
    character_ids = _value(line, "source_character_ids", ())
    if (
        not isinstance(characters, Sequence)
        or isinstance(characters, (str, bytes, bytearray))
        or len(characters) > 1_000_000
        or not isinstance(character_ids, Sequence)
        or isinstance(character_ids, (str, bytes, bytearray))
        or not character_ids
        or len(character_ids) > 4_096
        or any(not isinstance(identifier, str) or not identifier for identifier in character_ids)
        or len(set(character_ids)) != len(character_ids)
    ):
        return None
    line_box = _evidence_box(_value(line, "bbox"))
    if line_box is None:
        return None
    by_id: dict[str, Any] = {}
    for character in characters:
        identifier = _value(character, "id")
        if not isinstance(identifier, str) or not identifier or identifier in by_id:
            return None
        by_id[identifier] = character
    selected: list[Any] = []
    for identifier in character_ids:
        if not isinstance(identifier, str) or identifier not in by_id:
            return None
        character = by_id[identifier]
        character_box = _evidence_box(_value(character, "bbox"))
        if (
            type(_value(character, "page_index")) is not int
            or _value(character, "page_index")
            != _value(source_page, "page_index")
            or character_box is None
            or not _inside(line_box, character_box, tolerance=0.1)
        ):
            return None
        selected.append(character)
    raw_glyphs = [_value(character, "raw_text") for character in selected]
    if any(not isinstance(glyph, str) for glyph in raw_glyphs):
        return None
    emitted = "".join(raw_glyphs)
    if _normalized_visual_text(emitted) != _normalized_visual_text(
        _value(line, "text")
    ):
        return None
    return selected


def _visible_source_line(source_page: Any, line: Any) -> bool:
    characters = _source_characters_for_line(source_page, line)
    if characters is None:
        return False
    visible = [
        character
        for character in characters
        if str(_value(character, "raw_text", "") or "").strip()
    ]
    if len(visible) < 2:
        return False
    colored = False
    for character in visible:
        rgba = _value(character, "fill_rgba")
        if (
            _value(character, "excluded_reason") is not None
            or not isinstance(rgba, Sequence)
            or isinstance(rgba, (str, bytes, bytearray))
            or len(rgba) != 4
            or any(
                not isinstance(channel, int)
                or isinstance(channel, bool)
                or not 0 <= channel <= 255
                for channel in rgba
            )
            or int(rgba[3]) <= 0
        ):
            return False
        if min(int(channel) for channel in rgba[:3]) < 250:
            colored = True
    return colored


def _white_nonlexical_source_line(source_page: Any, line: Any) -> bool:
    characters = _source_characters_for_line(source_page, line)
    text = _normalized_visual_text(_value(line, "text"))
    if characters is None or not 4 <= len(text) <= 128:
        return False
    counts = Counter(text)
    dominant_ratio = max(counts.values(), default=0) / len(text)
    alphabetic_ratio = sum(character.isalpha() for character in text) / len(text)
    nonlexical_shape = bool(
        len(counts) <= 2
        or (dominant_ratio >= 0.65 and alphabetic_ratio <= 0.35)
    )
    if not nonlexical_shape:
        return False
    visible = [
        character
        for character in characters
        if str(_value(character, "raw_text", "") or "").strip()
    ]
    return bool(
        visible
        and all(
            _value(character, "excluded_reason") is None
            and isinstance((rgba := _value(character, "fill_rgba")), Sequence)
            and not isinstance(rgba, (str, bytes, bytearray))
            and len(rgba) == 4
            and all(
                isinstance(channel, int)
                and not isinstance(channel, bool)
                and 0 <= channel <= 255
                for channel in rgba
            )
            and min(int(channel) for channel in rgba[:3]) >= 250
            and int(rgba[3]) > 0
            for character in visible
        )
    )


def _bound_visual_children_to_source(
    item: Mapping[str, Any],
    native_children: Sequence[Mapping[str, Any]],
    *,
    source_text_evidence: Any | None,
    source_document_identity: str | None,
    page_index: int,
) -> tuple[Any, VisualBoundingBox, list[tuple[Mapping[str, Any], Any]]] | None:
    owner_box = _box(item.get("bbox"))
    source_page = _source_page(
        source_text_evidence,
        page_index=page_index,
        source_document_identity=source_document_identity,
    )
    page_width = _number(_value(source_page, "page_width"))
    page_height = _number(_value(source_page, "page_height"))
    page_box = (
        VisualBoundingBox(
            x=0.0,
            y=0.0,
            width=float(page_width),
            height=float(page_height),
            unit="pt",
        )
        if page_width is not None and page_height is not None
        else None
    )
    if (
        owner_box is None
        or source_page is None
        or page_box is None
        or not _inside(page_box, owner_box, tolerance=0.0)
        or not isinstance(native_children, Sequence)
        or isinstance(native_children, (str, bytes, bytearray))
        or not native_children
        or len(native_children) > _MAX_OWNED_VISUAL_CHILDREN
    ):
        return None
    bound: list[tuple[Mapping[str, Any], Any]] = []
    used_line_ids: set[str] = set()
    used_child_ids: set[str] = set()
    for child in native_children:
        if not isinstance(child, Mapping):
            return None
        child_id = child.get("id")
        if not isinstance(child_id, str) or not child_id:
            return None
        try:
            child_id_size = len(child_id.encode("utf-8"))
        except UnicodeEncodeError:
            return None
        child_text = _bounded_text(child.get("text"))
        child_box = _box(child.get("bbox"))
        if (
            child_id_size > 4_096
            or child_id in used_child_ids
            or child_text is None
            or child_box is None
            or type(child.get("page_index")) is not int
            or child.get("page_index") != page_index
            or not _inside(
                owner_box,
                child_box,
                tolerance=_OWNED_VISUAL_TOLERANCE_PT,
            )
        ):
            return None
        used_child_ids.add(child_id)
        matches = _source_line_candidates(
            source_page,
            owner_box=owner_box,
            child_box=child_box,
            child_text=child_text,
        )
        if len(matches) != 1:
            return None
        line = matches[0]
        line_id = _value(line, "id")
        if (
            not isinstance(line_id, str)
            or not line_id
            or line_id in used_line_ids
        ):
            return None
        used_line_ids.add(line_id)
        bound.append((child, line))
    return source_page, owner_box, bound


def recover_owned_visual_source_text(
    item: Mapping[str, Any],
    native_children: Sequence[Mapping[str, Any]],
    *,
    source_text_evidence: Any | None,
    source_document_identity: str | None,
    page_index: int,
) -> dict[str, Any] | None:
    """Recover exact visible source lines uniquely owned by graph children.

    A one-point containment tolerance covers independent extractor rounding.
    The graph child, source line, page, coordinate unit, geometry, and source
    hash must all agree; otherwise the existing visual placeholder survives.
    """

    if (
        str(item.get("type") or item.get("content_type") or "").casefold()
        != "image"
        or str(item.get("region_role") or "").casefold()
        != "content_region"
    ):
        return None
    binding = _bound_visual_children_to_source(
        item,
        native_children,
        source_text_evidence=source_text_evidence,
        source_document_identity=source_document_identity,
        page_index=page_index,
    )
    if binding is None:
        return None
    source_page, _owner_box, bound = binding
    if any(not _visible_source_line(source_page, line) for _child, line in bound):
        return None
    bound.sort(
        key=lambda value: (
            float(_value(_value(value[1], "bbox"), "y", 0.0)),
            float(_value(_value(value[1], "bbox"), "x", 0.0)),
            str(_value(value[1], "id") or ""),
        )
    )
    occurrences: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    child_ids: list[str] = []
    for child, line in bound:
        text = str(_value(line, "text") or "").strip()
        line_box = _evidence_box(_value(line, "bbox"))
        line_id = str(_value(line, "id") or "")
        if not text or line_box is None or not line_id:
            return None
        occurrence_id = _stable_id(
            "visual-owned-source",
            source_document_identity,
            page_index,
            line_id,
            text,
            line_box.model_dump(mode="json"),
        )
        occurrence = {
            "id": occurrence_id,
            "occurrence_id": occurrence_id,
            "text": text,
            "value": text,
            "bbox": line_box.model_dump(mode="json"),
            "confidence": 1.0,
            "word_count": len(text.split()),
            "source": "native",
            "accepted": True,
            "selected": True,
            "source_line_id": line_id,
            "source_character_ids": list(
                _value(line, "source_character_ids", ())
            ),
        }
        occurrences.append(occurrence)
        lines.append(
            {
                "text": text,
                "bbox": line_box.model_dump(mode="json"),
                "source_token_ids": [occurrence_id],
                "source_line_id": line_id,
            }
        )
        child_id = child.get("id")
        if isinstance(child_id, str) and child_id:
            child_ids.append(child_id)
    text = "\n".join(line["text"] for line in lines).strip()
    if not text:
        return None
    owned_children = [
        {
            "id": child.get("id"),
            "text_sha256": hashlib.sha256(
                str(child.get("text") or "").encode("utf-8")
            ).hexdigest(),
            "normalized_text_sha256": hashlib.sha256(
                _normalized_visual_text(child.get("text")).encode("utf-8")
            ).hexdigest(),
            "bbox": deepcopy(child.get("bbox")),
            "source_line_id": str(_value(line, "id") or ""),
        }
        for child, line in bound
    ]
    source_line_ids = [str(_value(line, "id")) for _child, line in bound]
    source_lineage_sha256 = owned_visual_source_lineage_sha256(
        source_sha256=source_document_identity,
        page_index=page_index,
        coordinate_unit="pt",
        owned_child_ids=child_ids,
        owned_children=owned_children,
        source_line_ids=source_line_ids,
        occurrences=occurrences,
        lines=lines,
    )
    if source_lineage_sha256 is None:
        return None
    return {
        "method": "pdf_source_line_owned_by_visual_child",
        "text": text,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "occurrences": occurrences,
        "lines": lines,
        "page_index": page_index,
        "coordinate_unit": "pt",
        "source_sha256": source_document_identity,
        "owned_child_ids": child_ids,
        "owned_children": owned_children,
        "source_line_ids": source_line_ids,
        "source_lineage_sha256": source_lineage_sha256,
        "containment_tolerance_pt": _OWNED_VISUAL_TOLERANCE_PT,
    }


def compact_visual_ocr_primary_evidence(
    item: Mapping[str, Any],
    native_children: Sequence[Mapping[str, Any]],
    accepted_lines: Sequence[Any],
    rejected_lines: Sequence[Mapping[str, Any]],
    promoted_text: str,
    *,
    source_text_evidence: Any | None,
    source_document_identity: str | None,
    page_index: int,
    classification: Mapping[str, Any] | None,
    confidence_floor: float = _COMPACT_OCR_CONFIDENCE_FLOOR,
) -> dict[str, Any] | None:
    """Prove a compact icon's complete OCR using two independent passes."""

    owner_box = _box(item.get("bbox"))
    class_name = str((classification or {}).get("class_name") or "").casefold()
    class_confidence = _number((classification or {}).get("confidence"))
    classifier_unavailable = classification is None
    parsed_confidence_floor = _number(confidence_floor)
    if parsed_confidence_floor is None:
        return None
    confidence_floor = max(
        parsed_confidence_floor,
        _COMPACT_OCR_CONFIDENCE_FLOOR,
    )
    if (
        str(item.get("type") or item.get("content_type") or "").casefold()
        != "image"
        or str(item.get("region_role") or "").casefold()
        != "content_region"
        or owner_box is None
        or (
            not classifier_unavailable
            and (
                class_name not in _COMPACT_TEXTUAL_CLASSES
                or class_confidence is None
                or class_confidence < confidence_floor
            )
        )
        or (
            classifier_unavailable
            and (
                owner_box.width > _MAX_UNCLASSIFIED_COMPACT_VISUAL_SIDE_PT
                or owner_box.height > _MAX_UNCLASSIFIED_COMPACT_VISUAL_SIDE_PT
                or owner_box.width * owner_box.height
                > _MAX_UNCLASSIFIED_COMPACT_VISUAL_AREA_PT2
            )
        )
        or not isinstance(accepted_lines, Sequence)
        or isinstance(accepted_lines, (str, bytes, bytearray))
        or not 1 <= len(accepted_lines) <= _MAX_COMPACT_OCR_LINES
        or not isinstance(rejected_lines, Sequence)
        or isinstance(rejected_lines, (str, bytes, bytearray))
        or len(rejected_lines) > 256
        or any(not isinstance(candidate, Mapping) for candidate in rejected_lines)
    ):
        return None
    accepted: list[tuple[str, str, VisualBoundingBox, float]] = []
    total_words = 0
    for line in accepted_lines:
        text = _bounded_text(_value(line, "text"), maximum=128)
        normalized = _normalized_visual_text(text)
        line_box = _box(_value(line, "bbox"))
        line_confidence = _number(_value(line, "confidence"))
        ocr_pass = str(_value(line, "ocr_pass", "") or "")
        word_count = _value(line, "word_count")
        if (
            text is None
            or len(normalized) < 2
            or line_box is None
            or line_confidence is None
            or line_confidence < confidence_floor
            or ocr_pass not in {"standard", "sparse"}
            or not _inside(
                owner_box,
                line_box,
                tolerance=_OWNED_VISUAL_TOLERANCE_PT,
            )
            or not isinstance(word_count, int)
            or isinstance(word_count, bool)
            or word_count < 1
        ):
            return None
        total_words += word_count
        accepted.append((text, ocr_pass, line_box, line_confidence))
    combined_text = "\n".join(value[0] for value in accepted)
    if (
        not isinstance(promoted_text, str)
        or combined_text != promoted_text
        or not 2 <= total_words <= 8
        or not 4 <= len(combined_text) <= 192
    ):
        return None

    accepted_left = min(value[2].x for value in accepted)
    accepted_top = min(value[2].y for value in accepted)
    accepted_right = max(value[2].x + value[2].width for value in accepted)
    accepted_bottom = max(value[2].y + value[2].height for value in accepted)
    accepted_width_ratio = (accepted_right - accepted_left) / owner_box.width
    accepted_union_area_ratio = (
        (accepted_right - accepted_left) * (accepted_bottom - accepted_top)
        / (owner_box.width * owner_box.height)
    )
    if classifier_unavailable and (
        accepted_width_ratio < _MIN_UNCLASSIFIED_OCR_WIDTH_RATIO
        and accepted_union_area_ratio < _MIN_UNCLASSIFIED_OCR_UNION_AREA_RATIO
    ):
        return None

    corroborating: list[Mapping[str, Any]] = []
    used_corroborator_ids: set[int] = set()
    corroborating_passes: set[str] = set()
    for text, accepted_pass, accepted_box, _confidence in accepted:
        normalized = _normalized_visual_text(text)
        matches: list[Mapping[str, Any]] = []
        for candidate in rejected_lines:
            candidate_text = _bounded_text(candidate.get("text"), maximum=128)
            candidate_box = _box(candidate.get("bbox"))
            candidate_confidence = _number(candidate.get("confidence"))
            candidate_pass = str(candidate.get("ocr_pass") or "")
            if (
                candidate_text is None
                or candidate_box is None
                or candidate_confidence is None
                or candidate_confidence < confidence_floor
                or candidate_pass not in {"standard", "sparse"}
                or candidate_pass == accepted_pass
                or _normalized_visual_text(candidate_text) != normalized
                or not _inside(
                    owner_box,
                    candidate_box,
                    tolerance=_OWNED_VISUAL_TOLERANCE_PT,
                )
                or _overlap_of_smaller(accepted_box, candidate_box) < 0.80
            ):
                continue
            matches.append(candidate)
        if len(matches) != 1:
            return None
        if id(matches[0]) in used_corroborator_ids:
            return None
        corroborating.append(matches[0])
        used_corroborator_ids.add(id(matches[0]))
        corroborating_passes.update(
            {accepted_pass, str(matches[0].get("ocr_pass") or "")}
        )

    # A high-confidence alphanumeric alternative inside the compact region is
    # a conflict unless it is the unique corroborator of one retained line.
    used_ids = {id(value) for value in corroborating}
    for candidate in rejected_lines:
        if id(candidate) in used_ids:
            continue
        candidate_text = _bounded_text(candidate.get("text"), maximum=128)
        candidate_box = _box(candidate.get("bbox"))
        candidate_confidence = _number(candidate.get("confidence"))
        if (
            candidate_text is None
            or len(_normalized_visual_text(candidate_text)) < 2
            or candidate_box is None
            or candidate_confidence is None
            or candidate_confidence < confidence_floor
            or not _inside(
                owner_box,
                candidate_box,
                tolerance=_OWNED_VISUAL_TOLERANCE_PT,
            )
        ):
            continue
        return None

    binding = _bound_visual_children_to_source(
        item,
        native_children,
        source_text_evidence=source_text_evidence,
        source_document_identity=source_document_identity,
        page_index=page_index,
    )
    if binding is None:
        return None
    source_page, _owner_box, bound = binding
    accepted_normalized = {
        _normalized_visual_text(text) for text, _pass, _box_value, _confidence in accepted
    }
    if any(
        _normalized_visual_text(child.get("text")) in accepted_normalized
        or not _white_nonlexical_source_line(source_page, line)
        for child, line in bound
    ):
        return None
    overlay_source_child_ids = [
        str(child.get("id")) for child, _line in bound
    ]
    overlay_source_line_ids = [
        str(_value(line, "id")) for _child, line in bound
    ]
    overlay_children = [
        {
            "source_child_id": str(child.get("id")),
            "normalized_text_sha256": hashlib.sha256(
                _normalized_visual_text(child.get("text")).encode("utf-8")
            ).hexdigest(),
            "bbox": deepcopy(child.get("bbox")),
            "source_line_id": str(_value(line, "id")),
        }
        for child, line in bound
    ]
    overlay_lineage_sha256 = compact_visual_overlay_lineage_sha256(
        source_sha256=source_document_identity,
        page_index=page_index,
        coordinate_unit="pt",
        source_child_ids=overlay_source_child_ids,
        source_line_ids=overlay_source_line_ids,
        children=overlay_children,
    )
    if overlay_lineage_sha256 is None:
        return None
    return {
        "method": "source_bound_multi_pass_compact_visual_ocr",
        "text_sha256": hashlib.sha256(combined_text.encode("utf-8")).hexdigest(),
        "page_index": page_index,
        "coordinate_unit": "pt",
        "source_sha256": source_document_identity,
        "accepted_line_count": len(accepted),
        "corroborating_line_count": len(corroborating),
        "ocr_passes": sorted(corroborating_passes),
        "confidence_floor": confidence_floor,
        "classifier_status": (
            "unavailable"
            if classifier_unavailable
            else "explicit_textual_compact_class"
        ),
        "accepted_width_ratio": round(accepted_width_ratio, 6),
        "accepted_union_area_ratio": round(accepted_union_area_ratio, 6),
        "native_overlay_source_line_ids": overlay_source_line_ids,
        "native_overlay_source_child_ids": overlay_source_child_ids,
        # Layout replaces this source-ID alias with exact public child IDs
        # after the graph-and-geometry containment projection succeeds.
        "native_overlay_child_ids": overlay_source_child_ids,
        "native_overlay_children": overlay_children,
        "native_overlay_lineage_sha256": overlay_lineage_sha256,
    }


def _revalidate_compact_ocr_occurrences(
    item: Mapping[str, Any],
    accepted: Sequence[tuple[str, VisualBoundingBox]],
    *,
    owner_box: VisualBoundingBox,
    confidence_floor: float,
) -> bool:
    occurrences = item.get("ocr_token_occurrences")
    if (
        not isinstance(occurrences, list)
        or not occurrences
        or len(occurrences) > 4_096
        or any(not isinstance(value, Mapping) for value in occurrences)
    ):
        return False
    parsed: list[dict[str, Any]] = []
    occurrence_ids: set[str] = set()
    line_groups: dict[str, list[int]] = {}
    for occurrence in occurrences:
        occurrence_id = occurrence.get("occurrence_id")
        line_id = occurrence.get("line_occurrence_id")
        text = _bounded_text(occurrence.get("text"), maximum=128)
        token_box = _box(occurrence.get("bbox"))
        confidence = _number(occurrence.get("confidence"))
        ocr_pass = str(occurrence.get("ocr_pass") or "")
        word_index = occurrence.get("word_index")
        if (
            not isinstance(occurrence_id, str)
            or not occurrence_id
            or occurrence_id in occurrence_ids
            or not isinstance(line_id, str)
            or not line_id
            or text is None
            or token_box is None
            or not _inside(
                owner_box,
                token_box,
                tolerance=_OWNED_VISUAL_TOLERANCE_PT,
            )
            or confidence is None
            or ocr_pass not in {"standard", "sparse"}
            or type(word_index) is not int
            or word_index < 0
            or type(occurrence.get("selected")) is not bool
            or type(occurrence.get("primary_selected")) is not bool
        ):
            return False
        occurrence_ids.add(occurrence_id)
        parsed.append(
            {
                "raw": occurrence,
                "id": occurrence_id,
                "line_id": line_id,
                "text": text,
                "bbox": token_box,
                "confidence": confidence,
                "ocr_pass": ocr_pass,
                "word_index": word_index,
            }
        )
        line_groups.setdefault(line_id, []).append(len(parsed) - 1)

    def group_details(indexes: Sequence[int]) -> tuple[str, VisualBoundingBox, str] | None:
        values = [parsed[index] for index in indexes]
        word_indexes = [int(value["word_index"]) for value in values]
        passes = {str(value["ocr_pass"]) for value in values}
        if len(set(word_indexes)) != len(word_indexes) or len(passes) != 1:
            return None
        values.sort(key=lambda value: (int(value["word_index"]), str(value["id"])))
        text = " ".join(str(value["text"]) for value in values)
        left = min(value["bbox"].x for value in values)
        top = min(value["bbox"].y for value in values)
        right = max(value["bbox"].x + value["bbox"].width for value in values)
        bottom = max(value["bbox"].y + value["bbox"].height for value in values)
        return (
            text,
            VisualBoundingBox(
                x=left,
                y=top,
                width=right - left,
                height=bottom - top,
                unit="pt",
            ),
            next(iter(passes)),
        )

    primary_groups = {
        line_id: indexes
        for line_id, indexes in line_groups.items()
        if all(
            parsed[index]["raw"].get("primary_selected") is True
            and parsed[index]["raw"].get("selected") is True
            and parsed[index]["raw"].get("retention_reason")
            == "primary_ocr_token"
            and parsed[index]["confidence"] >= confidence_floor
            for index in indexes
        )
    }
    if len(primary_groups) != len(accepted):
        return False
    used_primary_lines: set[str] = set()
    used_corroborating_lines: set[str] = set()
    used_occurrence_ids: set[str] = set()
    for accepted_text, accepted_box in accepted:
        matches: list[tuple[str, list[int], tuple[str, VisualBoundingBox, str]]] = []
        for line_id, indexes in primary_groups.items():
            if line_id in used_primary_lines:
                continue
            details = group_details(indexes)
            if (
                details is not None
                and _normalized_visual_text(details[0])
                == _normalized_visual_text(accepted_text)
                and _overlap_of_smaller(details[1], accepted_box) >= 0.80
            ):
                matches.append((line_id, indexes, details))
        if len(matches) != 1:
            return False
        primary_line_id, primary_indexes, primary_details = matches[0]
        used_primary_lines.add(primary_line_id)
        corroborating_line_ids: set[str] = set()
        for primary_index in primary_indexes:
            primary = parsed[primary_index]
            duplicate_matches = [
                candidate
                for candidate in parsed
                if candidate["raw"].get("duplicate_of") == primary["id"]
                and candidate["raw"].get("selected") is False
                and candidate["raw"].get("primary_selected") is False
                and candidate["raw"].get("retention_reason")
                == "overlapping_equivalent_ocr_diagnostic"
                and candidate["ocr_pass"] != primary_details[2]
                and candidate["confidence"] >= confidence_floor
                and _normalized_visual_text(candidate["text"])
                == _normalized_visual_text(primary["text"])
                and _overlap_of_smaller(candidate["bbox"], primary["bbox"])
                >= 0.80
            ]
            if len(duplicate_matches) != 1:
                return False
            [duplicate] = duplicate_matches
            corroborating_line_ids.add(str(duplicate["line_id"]))
            used_occurrence_ids.add(str(duplicate["id"]))
            used_occurrence_ids.add(str(primary["id"]))
        if (
            len(corroborating_line_ids) != 1
            or corroborating_line_ids & used_corroborating_lines
        ):
            return False
        corroborating_line_id = next(iter(corroborating_line_ids))
        corroborating_details = group_details(
            line_groups.get(corroborating_line_id, ())
        )
        if (
            corroborating_details is None
            or _normalized_visual_text(corroborating_details[0])
            != _normalized_visual_text(accepted_text)
            or corroborating_details[2] == primary_details[2]
            or _overlap_of_smaller(corroborating_details[1], accepted_box)
            < 0.80
        ):
            return False
        used_corroborating_lines.update(corroborating_line_ids)

    for occurrence in parsed:
        if occurrence["id"] in used_occurrence_ids:
            continue
        normalized = _normalized_visual_text(occurrence["text"])
        if (
            occurrence["confidence"] >= confidence_floor
            and len(normalized) >= 2
            and any(value.isalnum() for value in normalized)
        ):
            return False
    return True


def revalidate_compact_visual_ocr_primary_evidence(
    item: Mapping[str, Any],
    promoted_text: str,
    *,
    source_document_identity: str | None = None,
    page_index: int | None = None,
) -> bool:
    """Revalidate the bounded public proof before canonical re-projection.

    The source extractor is intentionally not rerun at serialization time.
    Instead, this checks that the exact source-bound proof emitted during the
    parse still agrees with the complete promoted OCR ledger, compact owner
    geometry, and independently projected native graph children.  Any missing
    or altered field fails closed.
    """

    owner_box = _box(item.get("bbox"))
    raw_meta = item.get("meta")
    proof = (
        raw_meta.get("compact_visual_ocr_primary")
        if isinstance(raw_meta, Mapping)
        else None
    )
    if not isinstance(proof, Mapping):
        return False
    expected_proof_keys = {
        "method",
        "text_sha256",
        "page_index",
        "coordinate_unit",
        "source_sha256",
        "accepted_line_count",
        "corroborating_line_count",
        "ocr_passes",
        "confidence_floor",
        "classifier_status",
        "accepted_width_ratio",
        "accepted_union_area_ratio",
        "native_overlay_source_line_ids",
        "native_overlay_source_child_ids",
        "native_overlay_child_ids",
        "native_overlay_children",
        "native_overlay_lineage_sha256",
    }
    if len(proof) != len(expected_proof_keys) or set(proof) != expected_proof_keys:
        return False
    confidence_floor = _number(proof.get("confidence_floor"))
    proof_page_index = proof.get("page_index")
    source_sha256 = proof.get("source_sha256")
    accepted_count = proof.get("accepted_line_count")
    corroborating_count = proof.get("corroborating_line_count")
    overlay_child_ids = proof.get("native_overlay_child_ids")
    overlay_source_child_ids = proof.get("native_overlay_source_child_ids")
    overlay_line_ids = proof.get("native_overlay_source_line_ids")
    overlay_children = proof.get("native_overlay_children")
    overlay_lineage_sha256 = proof.get("native_overlay_lineage_sha256")
    if (
        str(item.get("type") or "").casefold() != "image"
        or str(item.get("content_type") or "").casefold() != "image"
        or str(item.get("region_role") or "").casefold() != "content_region"
        or item.get("include_ocr_in_primary") is not True
        or owner_box is None
        or proof.get("method")
        != "source_bound_multi_pass_compact_visual_ocr"
        or not isinstance(promoted_text, str)
        or not promoted_text.strip()
        or proof.get("text_sha256")
        != hashlib.sha256(promoted_text.encode("utf-8")).hexdigest()
        or type(page_index) is not int
        or page_index < 1
        or type(proof_page_index) is not int
        or proof_page_index < 1
        or proof_page_index != page_index
        or proof.get("coordinate_unit") != "pt"
        or not isinstance(source_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None
        or not isinstance(source_document_identity, str)
        or re.fullmatch(r"[0-9a-f]{64}", source_document_identity) is None
        or source_sha256 != source_document_identity
        or confidence_floor is None
        or not _COMPACT_OCR_CONFIDENCE_FLOOR <= confidence_floor <= 1.0
        or type(accepted_count) is not int
        or not 1 <= accepted_count <= _MAX_COMPACT_OCR_LINES
        or type(corroborating_count) is not int
        or not 1 <= corroborating_count <= _MAX_COMPACT_OCR_LINES
        or corroborating_count != accepted_count
        or proof.get("ocr_passes") != ["sparse", "standard"]
        or not isinstance(overlay_child_ids, list)
        or not overlay_child_ids
        or len(overlay_child_ids) > _MAX_OWNED_VISUAL_CHILDREN
        or any(not isinstance(value, str) or not value for value in overlay_child_ids)
        or any(
            _bounded_proof_string(
                value, maximum=_MAX_VISUAL_PROOF_IDENTIFIER_BYTES
            )
            is None
            for value in overlay_child_ids
        )
        or len(set(overlay_child_ids)) != len(overlay_child_ids)
        or not isinstance(overlay_source_child_ids, list)
        or len(overlay_source_child_ids) != len(overlay_child_ids)
        or any(
            not isinstance(value, str) or not value
            for value in overlay_source_child_ids
        )
        or len(set(overlay_source_child_ids)) != len(overlay_source_child_ids)
        or not isinstance(overlay_line_ids, list)
        or len(overlay_line_ids) != len(overlay_child_ids)
        or any(not isinstance(value, str) or not value for value in overlay_line_ids)
        or len(set(overlay_line_ids)) != len(overlay_line_ids)
        or not isinstance(overlay_children, list)
        or len(overlay_children) != len(overlay_child_ids)
        or not isinstance(overlay_lineage_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", overlay_lineage_sha256) is None
    ):
        return False
    expected_overlay_lineage_sha256 = compact_visual_overlay_lineage_sha256(
        source_sha256=source_sha256,
        page_index=proof_page_index,
        coordinate_unit=proof.get("coordinate_unit"),
        source_child_ids=overlay_source_child_ids,
        source_line_ids=overlay_line_ids,
        children=overlay_children,
    )
    if expected_overlay_lineage_sha256 is None:
        return False
    if overlay_lineage_sha256 != expected_overlay_lineage_sha256:
        return False

    diagnostics = item.get("items")
    if (
        not isinstance(diagnostics, list)
        or len(diagnostics) > 4_096
        or any(not isinstance(value, Mapping) for value in diagnostics)
    ):
        return False
    accepted: list[tuple[str, VisualBoundingBox]] = []
    total_words = 0
    for diagnostic in diagnostics:
        if diagnostic.get("accepted") is not True:
            continue
        text = _bounded_text(diagnostic.get("text"), maximum=128)
        line_box = _box(diagnostic.get("bbox"))
        confidence = _number(diagnostic.get("confidence"))
        word_count = diagnostic.get("word_count")
        if (
            str(diagnostic.get("source") or "").casefold() != "ocr"
            or text is None
            or line_box is None
            or not _inside(
                owner_box,
                line_box,
                tolerance=_OWNED_VISUAL_TOLERANCE_PT,
            )
            or confidence is None
            or confidence < confidence_floor
            or type(word_count) is not int
            or word_count < 1
        ):
            return False
        total_words += word_count
        accepted.append((text, line_box))
    if (
        len(accepted) != accepted_count
        or "\n".join(text for text, _box_value in accepted) != promoted_text
        or not 2 <= total_words <= 8
    ):
        return False

    accepted_left = min(value[1].x for value in accepted)
    accepted_top = min(value[1].y for value in accepted)
    accepted_right = max(value[1].x + value[1].width for value in accepted)
    accepted_bottom = max(value[1].y + value[1].height for value in accepted)
    width_ratio = (accepted_right - accepted_left) / owner_box.width
    union_area_ratio = (
        (accepted_right - accepted_left) * (accepted_bottom - accepted_top)
        / (owner_box.width * owner_box.height)
    )
    proof_width_ratio = _number(proof.get("accepted_width_ratio"))
    proof_area_ratio = _number(proof.get("accepted_union_area_ratio"))
    if (
        proof_width_ratio is None
        or proof_area_ratio is None
        or not math.isclose(
            proof_width_ratio,
            round(width_ratio, 6),
            rel_tol=0.0,
            abs_tol=1e-9,
        )
        or not math.isclose(
            proof_area_ratio,
            round(union_area_ratio, 6),
            rel_tol=0.0,
            abs_tol=1e-9,
        )
    ):
        return False

    classifier_status = proof.get("classifier_status")
    classification = item.get("classification")
    if classifier_status == "unavailable":
        if (
            classification is not None
            or owner_box.width > _MAX_UNCLASSIFIED_COMPACT_VISUAL_SIDE_PT
            or owner_box.height > _MAX_UNCLASSIFIED_COMPACT_VISUAL_SIDE_PT
            or owner_box.width * owner_box.height
            > _MAX_UNCLASSIFIED_COMPACT_VISUAL_AREA_PT2
            or (
                width_ratio < _MIN_UNCLASSIFIED_OCR_WIDTH_RATIO
                and union_area_ratio < _MIN_UNCLASSIFIED_OCR_UNION_AREA_RATIO
            )
        ):
            return False
    elif classifier_status == "explicit_textual_compact_class":
        if not isinstance(classification, Mapping):
            return False
        class_confidence = _number(classification.get("confidence"))
        if (
            str(classification.get("class_name") or "").casefold()
            not in _COMPACT_TEXTUAL_CLASSES
            or class_confidence is None
            or class_confidence < confidence_floor
        ):
            return False
    else:
        return False

    if not _revalidate_compact_ocr_occurrences(
        item,
        accepted,
        owner_box=owner_box,
        confidence_floor=confidence_floor,
    ):
        return False

    contained_items = item.get("contained_items")
    contains_ids = item.get("contains_ids")
    relationships = item.get("relationships")
    owner_id = item.get("id")
    if (
        not isinstance(owner_id, str)
        or not owner_id
        or _bounded_proof_string(
            owner_id, maximum=_MAX_VISUAL_PROOF_IDENTIFIER_BYTES
        )
        is None
        or not isinstance(contained_items, list)
        or len(contained_items) != len(overlay_child_ids)
        or any(not isinstance(value, Mapping) for value in contained_items)
        or not isinstance(contains_ids, list)
        or any(not isinstance(value, str) or not value for value in contains_ids)
        or any(
            _bounded_proof_string(
                value, maximum=_MAX_VISUAL_PROOF_IDENTIFIER_BYTES
            )
            is None
            for value in contains_ids
        )
        or len(set(contains_ids)) != len(contains_ids)
        or contains_ids
        != [str(value.get("id") or "") for value in contained_items]
        or set(overlay_child_ids) != set(contains_ids)
        or not isinstance(relationships, list)
        or len(relationships) > _MAX_VISUAL_PROOF_RELATIONSHIPS
        or any(not isinstance(value, Mapping) for value in relationships)
    ):
        return False
    relationships_by_id: dict[str, Mapping[str, Any]] = {}
    for relationship in relationships:
        if (
            relationship.get("type") == "contains"
            and relationship.get("source_id") == owner_id
            and (
                len(relationship) != 4
                or set(relationship)
                != {"id", "type", "source_id", "target_id"}
            )
        ):
            return False
        relationship_id = relationship.get("id")
        if (
            _bounded_proof_string(
                relationship_id,
                maximum=_MAX_VISUAL_PROOF_IDENTIFIER_BYTES,
            )
            is None
            or relationship_id in relationships_by_id
        ):
            return False
        relationships_by_id[relationship_id] = relationship
    owner_contains = [
        relationship
        for relationship in relationships
        if relationship.get("type") == "contains"
        and relationship.get("source_id") == owner_id
    ]
    owner_contains_targets = [
        relationship.get("target_id") for relationship in owner_contains
    ]
    if (
        len(owner_contains) != len(contained_items)
        or any(
            _bounded_proof_string(
                value,
                maximum=_MAX_VISUAL_PROOF_IDENTIFIER_BYTES,
            )
            is None
            for value in owner_contains_targets
        )
        or len(set(owner_contains_targets)) != len(owner_contains_targets)
        or set(owner_contains_targets) != set(contains_ids)
    ):
        return False

    accepted_normalized = {
        _normalized_visual_text(text) for text, _box_value in accepted
    }
    for child in contained_items:
        child_id = child.get("id")
        child_text = _bounded_text(child.get("value"), maximum=128)
        child_box = _box(child.get("bbox"))
        relationship_id = child.get("relationship_id")
        normalized_child = _normalized_visual_text(child_text)
        counts = Counter(normalized_child)
        dominant_ratio = max(counts.values(), default=0) / max(
            len(normalized_child),
            1,
        )
        alphabetic_ratio = sum(value.isalpha() for value in normalized_child) / max(
            len(normalized_child),
            1,
        )
        nonlexical_shape = bool(
            4 <= len(normalized_child) <= 128
            and (
                len(counts) <= 2
                or (dominant_ratio >= 0.65 and alphabetic_ratio <= 0.35)
            )
        )
        relationship = relationships_by_id.get(str(relationship_id or ""))
        if (
            not isinstance(child_id, str)
            or child_id not in contains_ids
            or str(child.get("type") or "").casefold() != "visual_text"
            or str(child.get("content_type") or "").casefold()
            != "visual_text"
            or type(child.get("page_index")) is not int
            or child.get("page_index") != proof_page_index
            or child_text is None
            or child.get("md") != child_text
            or child_box is None
            or not _inside(
                owner_box,
                child_box,
                tolerance=_OWNED_VISUAL_TOLERANCE_PT,
            )
            or str(child.get("source") or "").casefold() != "native"
            or child.get("contained_by") != owner_id
            or child.get("presentation_role") != "subordinate"
            or child.get("relationship_type") != "contains"
            or child.get("relationship_basis") != "graph_and_geometry"
            or not nonlexical_shape
            or normalized_child in accepted_normalized
            or relationship is None
            or relationship.get("source_id") != owner_id
            or relationship.get("target_id") != child_id
            or relationship.get("type") != "contains"
        ):
            return False

    unmatched = list(contained_items)
    used_source_child_ids: set[str] = set()
    used_source_line_ids: set[str] = set()
    for proof_index, child_proof in enumerate(overlay_children):
        if not isinstance(child_proof, Mapping):
            return False
        expected_public_id = overlay_child_ids[proof_index]
        source_child_id = child_proof.get("source_child_id")
        source_line_id = child_proof.get("source_line_id")
        normalized_hash = child_proof.get("normalized_text_sha256")
        proof_box = _box(child_proof.get("bbox"))
        if (
            source_child_id != overlay_source_child_ids[proof_index]
            or source_child_id in used_source_child_ids
            or source_line_id != overlay_line_ids[proof_index]
            or source_line_id in used_source_line_ids
            or not isinstance(normalized_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", normalized_hash) is None
            or proof_box is None
            or not _inside(
                owner_box,
                proof_box,
                tolerance=_OWNED_VISUAL_TOLERANCE_PT,
            )
        ):
            return False
        matches = [
            index
            for index, child in enumerate(unmatched)
            if child.get("id") == expected_public_id
            and hashlib.sha256(
                _normalized_visual_text(child.get("value")).encode("utf-8")
            ).hexdigest()
            == normalized_hash
            and (child_box := _box(child.get("bbox"))) is not None
            and _overlap_of_smaller(child_box, proof_box) >= 0.75
        ]
        if len(matches) != 1:
            return False
        unmatched.pop(matches[0])
        used_source_child_ids.add(str(source_child_id))
        used_source_line_ids.add(str(source_line_id))
    return bool(
        not unmatched
        and used_source_child_ids == set(overlay_source_child_ids)
        and used_source_line_ids == set(overlay_line_ids)
    )


def _source_word_text(raw: Mapping[str, Any]) -> str | None:
    """Normalize only direction metadata supplied by the PDF text layer.

    ``pdfplumber`` returns the character order reversed for the 90-degree
    labels used by several benchmark charts.  Reversing an explicitly
    non-upright word restores the authored glyph order; no OCR correction or
    value inference is involved.
    """

    text = _bounded_text(raw.get("text"))
    if text is None:
        return None
    if raw.get("upright") is False:
        text = text[::-1]
    return text


def _join_source_line(line: Sequence[Mapping[str, Any]]) -> str:
    """Join PDF words while coalescing character-split embedded-font runs."""

    output = ""
    previous: Mapping[str, Any] | None = None
    for value in line:
        text = str(value.get("text") or "")
        box = value.get("bbox")
        if not text or not isinstance(box, Mapping):
            continue
        if previous is not None:
            previous_box = previous.get("bbox")
            if isinstance(previous_box, Mapping):
                gap = float(box["x"]) - (
                    float(previous_box["x"]) + float(previous_box["width"])
                )
                height = min(float(box["height"]), float(previous_box["height"]))
                # A normal PDF word boundary is wider than this.  The tiny
                # gaps are produced when an embedded font exposes each glyph
                # as a separate word (notably the health-report chart).
                separator = "" if gap <= max(0.45, height * 0.11) else " "
                output += separator
        output += text
        previous = value
    return output.strip()


def recover_pdf_visual_source_text(
    item: Mapping[str, Any],
    *,
    source_pdf_bytes: bytes | None,
    page_index: int,
) -> dict[str, Any] | None:
    """Return exact PDF-text-layer words wholly contained by one visual."""

    region = _box(item.get("bbox"))
    if source_pdf_bytes is None or region is None or page_index < 1:
        return None
    try:
        with pdfplumber.open(io.BytesIO(source_pdf_bytes)) as document:
            if page_index > len(document.pages):
                return None
            page = document.pages[page_index - 1]
            if (
                region.x + region.width > float(page.width) + 0.75
                or region.y + region.height > float(page.height) + 0.75
            ):
                return None
            raw_words = page.extract_words(
                x_tolerance=1,
                y_tolerance=1,
                keep_blank_chars=False,
                use_text_flow=False,
            )
    except Exception:
        # This is an optional evidence producer.  Backend-specific parser and
        # syntax exceptions must remain item-local.
        return None
    if not isinstance(raw_words, Sequence) or len(raw_words) > 100_000:
        return None

    words: list[dict[str, Any]] = []
    identities: set[tuple[str, float, float, float, float]] = set()
    for raw in raw_words:
        if not isinstance(raw, Mapping):
            continue
        text = _source_word_text(raw)
        x0 = _number(raw.get("x0"))
        x1 = _number(raw.get("x1"))
        top = _number(raw.get("top"))
        bottom = _number(raw.get("bottom"))
        if text is None or None in {x0, x1, top, bottom}:
            continue
        assert x0 is not None and x1 is not None
        assert top is not None and bottom is not None
        word_box = VisualBoundingBox(
            x=x0,
            y=top,
            width=x1 - x0,
            height=bottom - top,
            unit="pt",
        )
        if word_box.width <= 0 or word_box.height <= 0 or not _inside(region, word_box):
            continue
        identity = (
            text,
            round(word_box.x, 3),
            round(word_box.y, 3),
            round(word_box.width, 3),
            round(word_box.height, 3),
        )
        if identity in identities:
            continue
        identities.add(identity)
        words.append(
            {
                "text": text,
                "bbox": word_box.model_dump(mode="json"),
                "upright": bool(raw.get("upright", True)),
            }
        )
        if len(words) > _MAX_SOURCE_WORDS:
            return None
    if len(words) < 2:
        return None
    words.sort(
        key=lambda value: (
            round(float(value["bbox"]["y"]), 2),
            round(float(value["bbox"]["x"]), 2),
            value["text"],
        )
    )

    occurrences: list[dict[str, Any]] = []
    for word in words:
        occurrence_id = _stable_id(
            "visual-source-token",
            page_index,
            word["text"],
            word["bbox"],
        )
        occurrences.append(
            {
                "id": occurrence_id,
                "occurrence_id": occurrence_id,
                "text": word["text"],
                "value": word["text"],
                "bbox": word["bbox"],
                "confidence": 1.0,
                "word_count": len(word["text"].split()),
                "source": "native",
                "accepted": True,
                "selected": True,
                "upright": word["upright"],
            }
        )

    lines: list[list[dict[str, Any]]] = []
    for occurrence in occurrences:
        box = occurrence["bbox"]
        matching: list[dict[str, Any]] | None = None
        center = float(box["y"]) + float(box["height"]) / 2.0
        for line in reversed(lines[-8:]):
            first_box = line[0]["bbox"]
            first_center = float(first_box["y"]) + float(first_box["height"]) / 2.0
            tolerance = max(
                1.25,
                min(float(box["height"]), float(first_box["height"])) * 0.45,
            )
            if abs(center - first_center) <= tolerance:
                matching = line
                break
        if matching is None:
            matching = []
            lines.append(matching)
        matching.append(occurrence)
    normalized_lines: list[dict[str, Any]] = []
    for line in lines:
        line.sort(key=lambda value: float(value["bbox"]["x"]))
        text = _join_source_line(line)
        if not text:
            continue
        left = min(float(value["bbox"]["x"]) for value in line)
        top = min(float(value["bbox"]["y"]) for value in line)
        right = max(
            float(value["bbox"]["x"]) + float(value["bbox"]["width"])
            for value in line
        )
        bottom = max(
            float(value["bbox"]["y"]) + float(value["bbox"]["height"])
            for value in line
        )
        normalized_lines.append(
            {
                "text": text,
                "bbox": {
                    "x": left,
                    "y": top,
                    "width": right - left,
                    "height": bottom - top,
                    "unit": "pt",
                },
                "source_token_ids": [value["occurrence_id"] for value in line],
            }
        )
    text = "\n".join(value["text"] for value in normalized_lines).strip()
    if not text:
        return None
    return {
        "method": "pdf_text_layer_inside_visual_bbox",
        "text": text,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "occurrences": occurrences,
        "lines": normalized_lines,
    }


def attach_visual_source_text(
    item: Mapping[str, Any],
    source_text: Mapping[str, Any],
    *,
    promote_primary: bool,
) -> dict[str, Any]:
    """Attach bounded source text, optionally replacing noisy primary OCR."""

    candidate = deepcopy(dict(item))
    candidate["visual_source_text_occurrences"] = deepcopy(
        list(source_text.get("occurrences") or [])
    )
    candidate["visual_source_text_lines"] = deepcopy(
        list(source_text.get("lines") or [])
    )
    candidate["visual_source_text"] = str(source_text.get("text") or "")
    raw_meta = candidate.get("meta")
    meta = deepcopy(dict(raw_meta)) if isinstance(raw_meta, Mapping) else {}
    source_meta: dict[str, Any] = {
        "method": source_text.get("method"),
        "text_sha256": source_text.get("text_sha256"),
        "occurrence_count": len(source_text.get("occurrences") or []),
        "promoted_primary": promote_primary,
    }
    for key in (
        "page_index",
        "coordinate_unit",
        "source_sha256",
        "owned_child_ids",
        "owned_children",
        "source_line_ids",
        "source_lineage_sha256",
        "containment_tolerance_pt",
    ):
        if source_text.get(key) is not None:
            source_meta[key] = deepcopy(source_text[key])
    meta["phase05_visual_source_text"] = source_meta
    candidate["meta"] = meta
    if promote_primary:
        text = str(source_text.get("text") or "").strip()
        if text:
            candidate["value"] = text
            candidate["md"] = text
            candidate["detected_text"] = True
            # The promoted primary value is wholly recovered from the native
            # PDF text layer.  OCR remains available in its diagnostic fields,
            # but labelling this exact primary as ``mixed`` lets later generic
            # reconciliation replace it with the rejected OCR predecessor.
            candidate["source"] = "native"
    return candidate


def visual_source_text_primary_eligible(
    item: Mapping[str, Any],
    source_text: Mapping[str, Any],
) -> bool:
    """Reject a native primary when explicit OCR proves it is incomplete.

    Some hybrid charts draw category years as paths while their other labels
    remain native PDF text.  In that case the native layer is still valuable
    semantic evidence, but replacing the complete OCR presentation would drop
    user-visible categories.  The check only withholds promotion; it never
    edits or infers a token.
    """

    text = str(source_text.get("text") or "").strip()
    occurrences = source_text.get("occurrences")
    if (
        not text
        or not isinstance(occurrences, Sequence)
        or isinstance(occurrences, (str, bytes, bytearray))
        or len(occurrences) < 4
        or len(occurrences) > _MAX_SOURCE_WORDS
    ):
        return False
    region = _box(item.get("bbox"))
    lines = source_text.get("lines")
    if (
        region is None
        or not isinstance(lines, Sequence)
        or isinstance(lines, (str, bytes, bytearray))
        or not lines
        or len(lines) > _MAX_SOURCE_WORDS
        or any(
            not isinstance(value, Mapping)
            or (value_box := _box(value.get("bbox"))) is None
            or not _inside(region, value_box, tolerance=0.0)
            for value in [*occurrences, *lines]
        )
    ):
        return False
    ocr_text = "\n".join(
        str(value)
        for value in (
            item.get("ocr_text"),
            item.get("detected_text"),
            item.get("value"),
        )
        if isinstance(value, str) and value.strip()
    )
    source_years = _YEAR_SEARCH_RE.findall(text)
    ocr_years = _YEAR_SEARCH_RE.findall(ocr_text)
    if len(ocr_years) >= 3 and not source_years:
        return False
    # PDF extraction can fuse an adjacent footnote marker into a year token
    # (for example ``FY24`` + superscript ``5`` -> ``FY245``).  That is exact
    # glyph evidence but not safe user-facing linear text; retain it in the
    # sidecar while leaving the complete OCR primary intact.
    if re.search(r"\b(?:CY|FY)\d{3,}\b", text, re.IGNORECASE):
        return False
    return True


def infer_source_grounded_chart(item: Mapping[str, Any]) -> bool:
    """Admit only explicit printed chart signatures, never mark geometry."""

    declared = str(item.get("type") or item.get("content_type") or "").casefold()
    if (
        declared != "image"
        or item.get("region_role") != "content_region"
        or any(
            key in item
            for key in ("table_evidence", "table_continuation", "rows", "cells", "fields")
        )
    ):
        return False
    text = str(item.get("visual_source_text") or "")
    if not text:
        return False
    primary_text = "\n".join(
        str(value)
        for value in (
            item.get("ocr_text"),
            item.get("detected_text"),
            item.get("value"),
        )
        if isinstance(value, str) and value.strip()
    )
    percent_count = len(_PERCENT_RE.findall(text))
    currency_count = len(_CURRENCY_RE.findall(text))
    year_count = len(_YEAR_SEARCH_RE.findall(text))
    numeric_count = len(_NUMERIC_SEARCH_RE.findall(text))
    domain = _CHART_DOMAIN_RE.search(text) is not None
    energy_label_count = sum(
        term in text.casefold()
        for term in ("electricity", "fuel", "steam", "cooling", "energy")
    )
    fiscal_row_count = len(
        re.findall(r"(?m)^(?:CY|FY)\d{2,4}(?:\s|$)", text, re.IGNORECASE)
    )
    primary_year_count = len(_YEAR_SEARCH_RE.findall(primary_text))
    return bool(
        (currency_count >= 2 and year_count >= 2 and numeric_count >= 6)
        or (
            currency_count >= 2
            and primary_year_count >= 3
            and numeric_count >= 2
        )
        or (
            percent_count >= 4
            and numeric_count >= 4
            and energy_label_count >= 3
        )
        or (fiscal_row_count >= 4 and numeric_count >= 16)
        or (percent_count >= 4 and numeric_count >= 8 and domain)
        or (year_count >= 3 and numeric_count >= 10 and domain)
    )


def derive_colored_node_topology_evidence(
    item: Mapping[str, Any],
    *,
    source_pdf_bytes: bytes | None,
    page_index: int,
) -> dict[str, Any] | None:
    """Detect repeated filled circular nodes; deliberately emit no edges."""

    declared = str(item.get("type") or item.get("content_type") or "").casefold()
    region = _box(item.get("bbox"))
    occurrences = item.get("visual_source_text_occurrences")
    if (
        declared != "image"
        or item.get("region_role") != "content_region"
        or any(
            key in item
            for key in (
                "table_evidence",
                "table_continuation",
                "rows",
                "cells",
                "fields",
            )
        )
        or source_pdf_bytes is None
        or region is None
        or not isinstance(occurrences, Sequence)
        or isinstance(occurrences, (str, bytes, bytearray))
        or len(occurrences) > _MAX_SOURCE_WORDS
    ):
        return None
    try:
        import cv2
        import numpy as np
        import pypdfium2 as pdfium

        document = pdfium.PdfDocument(source_pdf_bytes)
        try:
            if page_index < 1 or page_index > len(document):
                return None
            page = document[page_index - 1]
            try:
                page_width, page_height = (float(value) for value in page.get_size())
                bitmap = page.render(
                    scale=1.0,
                    crop=(
                        region.x,
                        page_height - (region.y + region.height),
                        page_width - (region.x + region.width),
                        region.y,
                    ),
                    fill_color=(255, 255, 255, 255),
                    optimize_mode="print",
                )
                try:
                    rgb = np.asarray(bitmap.to_pil().convert("RGB"))
                finally:
                    bitmap.close()
            finally:
                page.close()
        finally:
            document.close()
        if rgb.ndim != 3 or rgb.shape[0] * rgb.shape[1] > 4_000_000:
            return None
        maximum = rgb.max(axis=2)
        minimum = rgb.min(axis=2)
        mask = ((maximum - minimum >= 55) & (maximum >= 70)).astype("uint8")
        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
            mask,
            connectivity=8,
        )
    except Exception:
        return None

    height, width = int(rgb.shape[0]), int(rgb.shape[1])
    pixel_area = float(width * height)
    components: list[tuple[int, int, int, int, int]] = []
    for component_index in range(1, count):
        x, y, component_width, component_height, area = (
            int(value) for value in stats[component_index]
        )
        if component_width <= 0 or component_height <= 0:
            continue
        density = area / float(component_width * component_height)
        aspect = component_width / float(component_height)
        area_ratio = area / pixel_area
        if (
            0.018 <= area_ratio <= 0.30
            and 0.78 <= aspect <= 1.22
            and 0.62 <= density <= 0.90
            and component_width >= max(32, width * 0.08)
            and component_height >= max(32, height * 0.18)
        ):
            components.append((x, y, component_width, component_height, area))
    if not 4 <= len(components) <= 16:
        return None
    components.sort(key=lambda value: (value[1], value[0]))
    scale_x = region.width / width
    scale_y = region.height / height
    nodes: list[dict[str, Any]] = []
    labelled_components = 0
    for component_index, (x, y, component_width, component_height, _area) in enumerate(
        components
    ):
        page_box = {
            "x": region.x + x * scale_x,
            "y": region.y + y * scale_y,
            "width": component_width * scale_x,
            "height": component_height * scale_y,
            "unit": "pt",
        }
        contained: list[tuple[int, str]] = []
        for occurrence in occurrences:
            if not isinstance(occurrence, Mapping):
                continue
            token_box = _box(occurrence.get("bbox"))
            identifier = _bounded_text(
                occurrence.get("occurrence_id", occurrence.get("id")),
                maximum=128,
            )
            token_text = _bounded_text(occurrence.get("text"))
            if token_box is None or identifier is None or token_text is None:
                continue
            center_x = token_box.x + token_box.width / 2.0
            center_y = token_box.y + token_box.height / 2.0
            if (
                page_box["x"] <= center_x <= page_box["x"] + page_box["width"]
                and page_box["y"] <= center_y <= page_box["y"] + page_box["height"]
            ):
                contained.append((len(token_text), identifier))
        label_source_token_id = None
        if contained:
            label_source_token_id = max(contained)[1]
            labelled_components += 1
        source_object_id = _stable_id(
            "raster-node",
            page_index,
            component_index,
            page_box,
        )
        nodes.append(
            {
                "source_object_id": source_object_id,
                "shape": "ellipse",
                "page_bbox": page_box,
                "label_source_token_id": label_source_token_id,
                "confidence": 0.95,
            }
        )
    if labelled_components < 3:
        return None
    return {"nodes": nodes, "connectors": []}


def _label_source_map(structure: VisualStructure) -> dict[str, VisualLabel]:
    evidence = {value.id: value for value in structure.evidence}
    output: dict[str, VisualLabel] = {}
    for label in structure.labels:
        for evidence_id in label.evidence_ids:
            for token_id in evidence[evidence_id].provenance.source_token_ids:
                output[token_id] = label
    return output


def _numeric_value(text: str) -> float | None:
    normalized = text.strip().replace("−", "-")
    if normalized[:1] in {"$", "€", "£", "¥", "₹"}:
        normalized = normalized[1:]
    normalized = normalized.rstrip("%BMKbm k")
    if not re.fullmatch(r"[+-]?\d+(?:,\d{3})*(?:\.\d+)?", normalized):
        return None
    try:
        return float(normalized.replace(",", ""))
    except ValueError:
        return None


def structure_source_text_chart(
    item: Mapping[str, Any],
    structure: VisualStructure,
    *,
    page_index: int,
    input_kind: Literal["pdf", "image", "unknown"],
) -> VisualStructure:
    """Organize only printed category/tick alignment; never emit data points."""

    if structure.region.kind != "chart":
        return structure
    occurrences = item.get("visual_source_text_occurrences")
    if not isinstance(occurrences, Sequence) or isinstance(
        occurrences,
        (str, bytes, bytearray),
    ):
        return structure
    labels_by_source = _label_source_map(structure)
    source_records: list[tuple[str, VisualLabel]] = []
    for occurrence in occurrences:
        if not isinstance(occurrence, Mapping):
            continue
        source_id = _bounded_text(
            occurrence.get("occurrence_id", occurrence.get("id")),
            maximum=128,
        )
        if source_id is not None and source_id in labels_by_source:
            source_records.append((source_id, labels_by_source[source_id]))
    if len(source_records) < 2:
        return structure

    region = structure.region.page_bbox
    category_records = [
        (source_id, label)
        for source_id, label in source_records
        if _YEAR_RE.fullmatch(label.text.strip()) is not None
        and label.page_bbox is not None
    ]
    panels: list[tuple[float, float, list[tuple[str, VisualLabel]]]] = []
    by_text: dict[str, list[tuple[str, VisualLabel]]] = {}
    for record in category_records:
        by_text.setdefault(record[1].text.casefold(), []).append(record)
    repeated_counts = sorted(len(values) for values in by_text.values())
    if (
        len(by_text) == 2
        and repeated_counts[0] >= 3
        and repeated_counts[0] == repeated_counts[1]
    ):
        ordered = sorted(
            category_records,
            key=lambda value: (
                value[1].page_bbox.x + value[1].page_bbox.width / 2.0  # type: ignore[union-attr]
            ),
        )
        pairs = [ordered[index : index + 2] for index in range(0, len(ordered), 2)]
        if all(
            len(pair) == 2 and pair[0][1].text.casefold() != pair[1][1].text.casefold()
            for pair in pairs
        ):
            centers = [
                sum(
                    value[1].page_bbox.x + value[1].page_bbox.width / 2.0  # type: ignore[union-attr]
                    for value in pair
                )
                / 2.0
                for pair in pairs
            ]
            gaps = [right - left for left, right in zip(centers, centers[1:])]
            pair_widths = [
                abs(
                    pair[1][1].page_bbox.x  # type: ignore[union-attr]
                    - pair[0][1].page_bbox.x  # type: ignore[union-attr]
                )
                for pair in pairs
            ]
            if gaps and min(gaps) > max(pair_widths) * 1.35:
                boundaries = [region.x]
                boundaries.extend(
                    (left + right) / 2.0 for left, right in zip(centers, centers[1:])
                )
                boundaries.append(region.x + region.width)
                panels = [
                    (boundaries[index], boundaries[index + 1], pair)
                    for index, pair in enumerate(pairs)
                ]
    if not panels:
        panels = [(region.x, region.x + region.width, category_records)]

    payload = structure.model_dump(mode="json", exclude_none=True)
    label_positions = {value.id: index for index, value in enumerate(structure.labels)}
    labels = [value.model_copy(deep=True) for value in structure.labels]
    evidence = [value.model_copy(deep=True) for value in structure.evidence]
    panel_values: list[ChartPanel] = []
    axis_values: list[ChartAxis] = []
    public_item_id = structure.evidence[0].provenance.public_item_id

    def update_role(label: VisualLabel, role: Literal["category", "tick"]) -> VisualLabel:
        current = labels[label_positions[label.id]]
        updated = current.model_copy(update={"role": role}, deep=True)
        labels[label_positions[label.id]] = updated
        return updated

    for panel_index, (left, right, panel_categories) in enumerate(panels):
        panel_box = VisualBoundingBox(
            x=left,
            y=region.y,
            width=right - left,
            height=region.height,
            unit=region.unit,
        )
        panel_evidence_id = _stable_id(
            "visual-evidence",
            structure.region.id,
            "source-text-panel",
            panel_index,
            panel_box.model_dump(mode="json"),
        )
        evidence.append(
            VisualEvidence(
                id=panel_evidence_id,
                kind="panel",
                page_bbox=panel_box,
                chart_local_bbox=VisualBoundingBox(
                    x=panel_box.x - region.x,
                    y=0.0,
                    width=panel_box.width,
                    height=panel_box.height,
                    unit=region.unit,
                ),
                provenance=VisualProvenance(
                    public_item_id=public_item_id,
                    page_index=page_index,
                    input_kind=input_kind,
                    source_object_ids=[
                        _stable_id("source-text-panel", structure.region.id, panel_index)
                    ],
                    extraction_method="explicit_text",
                ),
            )
        )
        panel_id = _stable_id(
            "chart-panel",
            structure.region.id,
            panel_index,
            panel_box.model_dump(mode="json"),
        )
        panel_category_labels: list[VisualLabel] = []
        for _source_id, label in panel_categories:
            if label.page_bbox is None:
                continue
            center_x = label.page_bbox.x + label.page_bbox.width / 2.0
            if left - 0.75 <= center_x <= right + 0.75:
                panel_category_labels.append(update_role(label, "category"))
        panel_values.append(
            ChartPanel(
                id=panel_id,
                page_bbox=panel_box,
                chart_local_bbox=VisualBoundingBox(
                    x=panel_box.x - region.x,
                    y=0.0,
                    width=panel_box.width,
                    height=panel_box.height,
                    unit=region.unit,
                ),
                label_ids=[value.id for value in panel_category_labels],
                evidence_ids=[panel_evidence_id],
            )
        )
        if len(panel_category_labels) >= 2:
            category_boxes = [value.page_bbox for value in panel_category_labels]
            assert all(value is not None for value in category_boxes)
            top = min(value.y for value in category_boxes if value is not None)
            bottom = max(
                value.y + value.height for value in category_boxes if value is not None
            )
            axis_evidence_id = _stable_id(
                "visual-evidence",
                structure.region.id,
                panel_id,
                "x-axis-source-text",
            )
            source_ids = sorted(
                source_id
                for source_id, label in panel_categories
                if label.id in {value.id for value in panel_category_labels}
            )
            evidence.append(
                VisualEvidence(
                    id=axis_evidence_id,
                    kind="axis",
                    page_bbox=VisualBoundingBox(
                        x=left,
                        y=top,
                        width=right - left,
                        height=max(bottom - top, 0.01),
                        unit=region.unit,
                    ),
                    provenance=VisualProvenance(
                        public_item_id=public_item_id,
                        page_index=page_index,
                        input_kind=input_kind,
                        source_token_ids=source_ids,
                        extraction_method="explicit_text",
                    ),
                )
            )
            axis_values.append(
                ChartAxis(
                    id=_stable_id("chart-axis", panel_id, "x", source_ids),
                    panel_id=panel_id,
                    orientation="x",
                    scale="unresolved",
                    baseline_position=bottom,
                    category_label_ids=[value.id for value in panel_category_labels],
                    evidence_ids=[axis_evidence_id],
                )
            )

        numeric_records = [
            (source_id, label, _numeric_value(label.text))
            for source_id, label in source_records
            if label.page_bbox is not None
            and left - 0.75
            <= label.page_bbox.x + label.page_bbox.width / 2.0
            <= right + 0.75
            and not _YEAR_RE.fullmatch(label.text.strip())
            and _NUMBER_RE.fullmatch(label.text.strip())
        ]
        x_groups: list[list[tuple[str, VisualLabel, float | None]]] = []
        for record in sorted(
            numeric_records,
            key=lambda value: (
                value[1].page_bbox.x,  # type: ignore[union-attr]
                value[1].page_bbox.y,  # type: ignore[union-attr]
            ),
        ):
            center_x = record[1].page_bbox.x + record[1].page_bbox.width / 2.0  # type: ignore[union-attr]
            matching = next(
                (
                    group
                    for group in x_groups
                    if abs(
                        center_x
                        - (
                            group[0][1].page_bbox.x  # type: ignore[union-attr]
                            + group[0][1].page_bbox.width / 2.0  # type: ignore[union-attr]
                        )
                    )
                    <= 4.0
                ),
                None,
            )
            if matching is None:
                matching = []
                x_groups.append(matching)
            matching.append(record)
        eligible = [
            group
            for group in x_groups
            if len(group) >= 3
            and all(value[2] is not None for value in group)
            and (
                group[0][1].page_bbox.x  # type: ignore[union-attr]
                <= left + (right - left) * 0.25
            )
        ]
        if eligible:
            group = min(
                eligible,
                key=lambda values: values[0][1].page_bbox.x,  # type: ignore[union-attr]
            )
            tick_values: list[ChartTick] = []
            tick_evidence_ids: list[str] = []
            for source_id, label, numeric in sorted(
                group,
                key=lambda value: value[1].page_bbox.y,  # type: ignore[union-attr]
            ):
                assert label.page_bbox is not None and numeric is not None
                tick_label = update_role(label, "tick")
                tick_evidence_id = _stable_id(
                    "visual-evidence",
                    structure.region.id,
                    panel_id,
                    "y-tick",
                    source_id,
                )
                evidence.append(
                    VisualEvidence(
                        id=tick_evidence_id,
                        kind="tick",
                        page_bbox=label.page_bbox,
                        provenance=VisualProvenance(
                            public_item_id=public_item_id,
                            page_index=page_index,
                            input_kind=input_kind,
                            source_token_ids=[source_id],
                            extraction_method="explicit_text",
                        ),
                    )
                )
                tick_evidence_ids.append(tick_evidence_id)
                tick_values.append(
                    ChartTick(
                        id=_stable_id("chart-tick", panel_id, source_id),
                        value=numeric,
                        position=label.page_bbox.y + label.page_bbox.height / 2.0,
                        label_id=tick_label.id,
                        evidence_ids=[tick_evidence_id],
                    )
                )
            axis_box = VisualBoundingBox(
                x=min(value[1].page_bbox.x for value in group),  # type: ignore[union-attr]
                y=min(value[1].page_bbox.y for value in group),  # type: ignore[union-attr]
                width=max(value[1].page_bbox.width for value in group),  # type: ignore[union-attr]
                height=(
                    max(
                        value[1].page_bbox.y + value[1].page_bbox.height  # type: ignore[union-attr]
                        for value in group
                    )
                    - min(value[1].page_bbox.y for value in group)  # type: ignore[union-attr]
                ),
                unit=region.unit,
            )
            axis_evidence_id = _stable_id(
                "visual-evidence",
                structure.region.id,
                panel_id,
                "y-axis-source-text",
            )
            evidence.append(
                VisualEvidence(
                    id=axis_evidence_id,
                    kind="axis",
                    page_bbox=axis_box,
                    provenance=VisualProvenance(
                        public_item_id=public_item_id,
                        page_index=page_index,
                        input_kind=input_kind,
                        source_token_ids=sorted(value[0] for value in group),
                        extraction_method="explicit_text",
                    ),
                )
            )
            axis_values.append(
                ChartAxis(
                    id=_stable_id("chart-axis", panel_id, "y", axis_evidence_id),
                    panel_id=panel_id,
                    orientation="y",
                    scale="unresolved",
                    ticks=tick_values,
                    evidence_ids=[axis_evidence_id],
                )
            )

    payload["labels"] = [
        value.model_dump(mode="json", exclude_none=True) for value in labels
    ]
    payload["evidence"] = [
        value.model_dump(mode="json", exclude_none=True) for value in evidence
    ]
    payload["panels"] = [
        value.model_dump(mode="json", exclude_none=True) for value in panel_values
    ]
    payload["axes"] = [
        value.model_dump(mode="json", exclude_none=True) for value in axis_values
    ]
    if panel_values and not any(
        value.get("code") == "chart_source_text_structure_partial"
        for value in payload.get("concerns", [])
        if isinstance(value, Mapping)
    ):
        payload.setdefault("concerns", []).append(
            VisualConcern(
                code="chart_source_text_structure_partial",
                severity="info",
                stage="chart_structure",
                evidence_ids=list(structure.region.evidence_ids),
            ).model_dump(mode="json", exclude_none=True)
        )
    return VisualStructure.model_validate(payload)


__all__ = [
    "attach_visual_source_text",
    "derive_colored_node_topology_evidence",
    "infer_source_grounded_chart",
    "recover_pdf_visual_source_text",
    "structure_source_text_chart",
    "visual_source_text_primary_eligible",
]
