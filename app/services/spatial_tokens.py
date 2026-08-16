"""Bounded, presentation-inert OCR token occurrence projection.

The legacy OCR line and canonical-presentation contracts intentionally remain
authoritative.  This module adds an addressable evidence view over the tokens
that produced those lines; it does not correct recognition or promote text.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from typing import Any, Iterable, Mapping, Sequence


SPATIAL_TOKEN_SCHEMA_VERSION = "1.0"
SPATIAL_TOKEN_OVERLAP_THRESHOLD = 0.80
SHORT_TOKEN_MIN_OWNER_CONTAINMENT = 0.95
MAX_SPATIAL_SOURCE_TOKENS = 4_096
MAX_SPATIAL_TOKEN_OCCURRENCES = 2_048
MAX_SPATIAL_SHORT_ALTERNATIVES = 256
MAX_SPATIAL_TOKEN_TEXT_CHARS = 256
MAX_SPATIAL_OCCURRENCE_JSON_BYTES = 1_048_576

_WHITESPACE_RE = re.compile(r"\s+")
_SHORT_TOKEN_RE = re.compile(r"[A-Za-z0-9]{1,3}")
_INCLUSIVE_RATIO_ABS_TOLERANCE = 1e-12


def _stable_id(prefix: str, payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()}"


def _normalized_equivalent_text(value: str) -> str:
    """Normalize only encoding and whitespace, never case or confusables."""

    return _WHITESPACE_RE.sub(
        " ",
        unicodedata.normalize("NFC", value),
    ).strip()


def _normalized_bbox(
    value: Mapping[str, Any] | None,
    *,
    coordinate_unit: str,
) -> dict[str, Any] | None:
    if coordinate_unit not in {"pt", "px"}:
        return None
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
        not all(math.isfinite(part) for part in (x, y, width, height))
        or width <= 0
        or height <= 0
    ):
        return None
    normalized_x = round(x, 3)
    normalized_y = round(y, 3)
    normalized_width = round(width, 3)
    normalized_height = round(height, 3)
    if normalized_width <= 0 or normalized_height <= 0:
        return None
    return {
        "x": normalized_x,
        "y": normalized_y,
        "w": normalized_width,
        "h": normalized_height,
        "width": normalized_width,
        "height": normalized_height,
        "unit": coordinate_unit,
    }


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


def _reciprocal_overlap(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> float:
    first_area = float(first["width"]) * float(first["height"])
    second_area = float(second["width"]) * float(second["height"])
    if first_area <= 0 or second_area <= 0:
        return 0.0
    intersection = _intersection_area(first, second)
    return min(intersection / first_area, intersection / second_area)


def _owner_containment(
    token_bbox: Mapping[str, Any],
    owner_bbox: Mapping[str, Any] | None,
) -> float:
    if owner_bbox is None:
        return 0.0
    token_area = float(token_bbox["width"]) * float(token_bbox["height"])
    if token_area <= 0:
        return 0.0
    return _intersection_area(token_bbox, owner_bbox) / token_area


def _meets_inclusive_ratio(value: float, threshold: float) -> bool:
    """Honor inclusive geometric thresholds across binary-float boundaries."""

    return value >= threshold or math.isclose(
        value,
        threshold,
        rel_tol=0.0,
        abs_tol=_INCLUSIVE_RATIO_ABS_TOLERANCE,
    )


def geometry_aware_line_values_with_selection(
    values: Iterable[tuple[str, Mapping[str, Any] | None]],
    *,
    coordinate_unit: str = "pt",
) -> tuple[list[str], frozenset[int]]:
    """Keep distant repetitions and collapse only overlapping exact text."""

    retained: list[str] = []
    retained_indexes: set[int] = set()
    seen_text: set[str] = set()
    invalid_geometry_text: set[str] = set()
    spatial_buckets: dict[
        tuple[str, int, int, int, int],
        list[dict[str, Any]],
    ] = {}
    for source_index, (raw_text, raw_bbox) in enumerate(values):
        text = str(raw_text or "").strip()
        if not text:
            continue
        normalized_text = _normalized_equivalent_text(text)
        bbox = _normalized_bbox(
            raw_bbox,
            coordinate_unit=coordinate_unit,
        )
        if bbox is None:
            if normalized_text in seen_text:
                continue
            retained.append(text)
            retained_indexes.add(source_index)
            seen_text.add(normalized_text)
            invalid_geometry_text.add(normalized_text)
            continue
        if normalized_text in invalid_geometry_text:
            continue

        width_bin = math.floor(math.log2(float(bbox["width"])))
        height_bin = math.floor(math.log2(float(bbox["height"])))
        center_x = float(bbox["x"]) + float(bbox["width"]) / 2.0
        center_y = float(bbox["y"]) + float(bbox["height"]) / 2.0
        duplicate = False
        for query_width_bin in range(width_bin - 1, width_bin + 2):
            width_scale = 2.0**query_width_bin
            center_cell_x = math.floor(center_x / width_scale)
            for query_height_bin in range(
                height_bin - 1,
                height_bin + 2,
            ):
                height_scale = 2.0**query_height_bin
                center_cell_y = math.floor(center_y / height_scale)
                for cell_x in range(center_cell_x - 1, center_cell_x + 2):
                    for cell_y in range(
                        center_cell_y - 1,
                        center_cell_y + 2,
                    ):
                        bucket = spatial_buckets.get(
                            (
                                normalized_text,
                                query_width_bin,
                                query_height_bin,
                                cell_x,
                                cell_y,
                            ),
                            (),
                        )
                        if any(
                            _meets_inclusive_ratio(
                                _reciprocal_overlap(bbox, prior_bbox),
                                SPATIAL_TOKEN_OVERLAP_THRESHOLD,
                            )
                            for prior_bbox in bucket
                        ):
                            duplicate = True
                            break
                    if duplicate:
                        break
                if duplicate:
                    break
            if duplicate:
                break
        if duplicate:
            continue

        retained.append(text)
        retained_indexes.add(source_index)
        seen_text.add(normalized_text)
        own_width_scale = 2.0**width_bin
        own_height_scale = 2.0**height_bin
        bucket_key = (
            normalized_text,
            width_bin,
            height_bin,
            math.floor(center_x / own_width_scale),
            math.floor(center_y / own_height_scale),
        )
        spatial_buckets.setdefault(bucket_key, []).append(bbox)
    return retained, frozenset(retained_indexes)


def geometry_aware_unique_line_values(
    values: Iterable[tuple[str, Mapping[str, Any] | None]],
    *,
    coordinate_unit: str = "pt",
) -> list[str]:
    retained, _selected_indexes = (
        geometry_aware_line_values_with_selection(
            values,
            coordinate_unit=coordinate_unit,
        )
    )
    return retained


def _value(source: Any, key: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(key, default)
    return getattr(source, key, default)


def _line_tokens(line: Any) -> Sequence[Any]:
    tokens = _value(line, "tokens", [])
    if (
        isinstance(tokens, Sequence)
        and not isinstance(tokens, (str, bytes))
        and tokens
    ):
        return tokens

    # A single-word OCRLine remains useful evidence in hand-built adapters and
    # older fixtures that predate the token field.
    text = str(_value(line, "text", "") or "")
    if text and not _WHITESPACE_RE.search(text.strip()):
        return [
            {
                "text": text,
                "bbox": _value(line, "bbox"),
                "confidence": _value(line, "confidence"),
                "ocr_pass": _value(line, "ocr_pass", "standard"),
                "word_index": 0,
                "_synthesized_from_line": True,
            }
        ]
    return []


def _confidence_value(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    confidence = float(value)
    if not math.isfinite(confidence) or confidence < 0 or confidence > 1:
        return None
    return confidence


def _empty_summary() -> dict[str, Any]:
    return {
        "schema_version": SPATIAL_TOKEN_SCHEMA_VERSION,
        "total_occurrences": 0,
        "selected_occurrences": 0,
        "primary_selected_occurrences": 0,
        "duplicate_occurrences": 0,
        "short_alternative_occurrences": 0,
        "invalid_occurrences": 0,
        "oversized_text_occurrences": 0,
        "truncated_occurrences": 0,
        "source_token_limit_reached": False,
        "occurrence_limit_reached": False,
        "short_alternative_limit_reached": False,
        "serialized_byte_limit_reached": False,
        "fail_closed_overflow": False,
        "overflow_reason": None,
        "serialized_occurrence_bytes": 2,
    }


def project_ocr_token_occurrences(
    *,
    page_index: int,
    owner_identity: Any,
    owner_bbox: Mapping[str, Any] | None,
    owner_content_type: str,
    coordinate_unit: str,
    lines: Sequence[Any],
    line_diagnostics: Sequence[Mapping[str, Any]],
    rejected_lines: Sequence[Mapping[str, Any]] = (),
    include_ocr_in_primary: bool,
    primary_confidence_threshold: float,
    owner_region_role: str = "content_region",
    primary_line_selections: Sequence[bool] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Project accepted and rejected OCR tokens into bounded occurrences."""

    summary = _empty_summary()
    if page_index < 1:
        summary["invalid_occurrences"] = 1
        return [], summary
    try:
        json.dumps(
            owner_identity,
            allow_nan=False,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        summary["invalid_occurrences"] = 1
        return [], summary

    if coordinate_unit not in {"pt", "px"}:
        summary["invalid_occurrences"] = 1
        return [], summary
    unit = coordinate_unit
    normalized_owner_bbox = _normalized_bbox(
        owner_bbox,
        coordinate_unit=unit,
    )
    if normalized_owner_bbox is None:
        summary["invalid_occurrences"] = 1
        return [], summary
    owner_anchor = {
        "schema_version": SPATIAL_TOKEN_SCHEMA_VERSION,
        "page_index": page_index,
        "owner_identity": owner_identity,
        "owner_bbox": normalized_owner_bbox,
        "owner_content_type": str(owner_content_type or "image"),
        "owner_region_role": str(owner_region_role or ""),
        "coordinate_unit": unit,
    }
    short_content = (
        str(owner_region_role or "").casefold() == "content_region"
        and str(owner_content_type or "").casefold()
        in {"chart", "diagram"}
    )
    short_floor = round(primary_confidence_threshold * 0.65, 12)
    candidates: list[dict[str, Any]] = []
    inspected = 0
    short_count = 0

    def source_entries() -> Iterable[
        tuple[Any, Mapping[str, Any], bool, int]
    ]:
        for line_index, line in enumerate(lines):
            diagnostic = (
                line_diagnostics[line_index]
                if line_index < len(line_diagnostics)
                else {}
            )
            yield line, diagnostic, False, line_index
        for line_index, line in enumerate(rejected_lines):
            yield (
                line,
                {
                    "accepted": False,
                    "rejection_reason": (
                        line.get("rejection_reason")
                        or "overlapping_ocr_candidate"
                    ),
                },
                True,
                line_index,
            )

    for (
        line,
        diagnostic,
        rejected_pass_candidate,
        line_index,
    ) in source_entries():
        line_text = str(_value(line, "text", "") or "")
        line_bbox = _normalized_bbox(
            _value(line, "bbox"),
            coordinate_unit=unit,
        )
        line_confidence = _confidence_value(_value(line, "confidence"))
        ocr_pass = str(_value(line, "ocr_pass", "standard") or "standard")
        quality_accepted = bool(diagnostic.get("accepted", False))
        rejection_reason = (
            str(diagnostic.get("rejection_reason") or "") or None
        )
        if (
            not rejected_pass_candidate
            and primary_line_selections is not None
            and line_index < len(primary_line_selections)
        ):
            primary_line = bool(
                primary_line_selections[line_index]
                and quality_accepted
                and include_ocr_in_primary
            )
        else:
            primary_line = bool(
                quality_accepted
                and include_ocr_in_primary
                and not rejected_pass_candidate
            )
        line_occurrence_id = _stable_id(
            "ocr-line",
            {
                **owner_anchor,
                "channel": (
                    "rejected_pass"
                    if rejected_pass_candidate
                    else "accepted_pass"
                ),
                "line_index": line_index,
                "line_text": line_text,
                "line_bbox": line_bbox,
                "ocr_pass": ocr_pass,
            },
        )

        line_tokens = _line_tokens(line)
        if line_bbox is None:
            remaining_budget = max(
                MAX_SPATIAL_SOURCE_TOKENS - inspected,
                0,
            )
            inspected_count = min(len(line_tokens), remaining_budget)
            inspected += inspected_count
            summary["invalid_occurrences"] += inspected_count or 1
            if len(line_tokens) > inspected_count:
                summary["source_token_limit_reached"] = True
                summary["truncated_occurrences"] += 1
                break
            continue
        for token_sequence_index, token in enumerate(line_tokens):
            inspected += 1
            if inspected > MAX_SPATIAL_SOURCE_TOKENS:
                summary["source_token_limit_reached"] = True
                summary["truncated_occurrences"] += 1
                break
            text = str(_value(token, "text", "") or "")
            if not text:
                summary["invalid_occurrences"] += 1
                continue
            if len(text) > MAX_SPATIAL_TOKEN_TEXT_CHARS:
                summary["oversized_text_occurrences"] += 1
                continue
            bbox = _normalized_bbox(
                _value(token, "bbox"),
                coordinate_unit=unit,
            )
            if bbox is None:
                summary["invalid_occurrences"] += 1
                continue
            if len(candidates) >= MAX_SPATIAL_TOKEN_OCCURRENCES:
                summary["occurrence_limit_reached"] = True
                summary["truncated_occurrences"] += 1
                continue

            token_confidence = _confidence_value(
                _value(token, "confidence")
            )
            synthesized_from_line = bool(
                _value(token, "_synthesized_from_line", False)
            )
            confidence = (
                line_confidence
                if synthesized_from_line
                else token_confidence
            )
            token_pass = str(
                _value(token, "ocr_pass", ocr_pass) or ocr_pass
            )
            try:
                word_index = int(_value(token, "word_index", 0))
            except (TypeError, ValueError):
                word_index = 0
            raw_crop_pixel_bbox = _value(token, "crop_pixel_bbox")
            crop_pixel_bbox = _normalized_bbox(
                raw_crop_pixel_bbox,
                coordinate_unit="px",
            )
            if (
                raw_crop_pixel_bbox is not None
                and crop_pixel_bbox is None
            ):
                summary["invalid_occurrences"] += 1
                continue
            normalized_text = _normalized_equivalent_text(text)
            if not normalized_text:
                summary["invalid_occurrences"] += 1
                continue

            is_short_alternative = bool(
                short_content
                and not quality_accepted
                and not rejected_pass_candidate
                and rejection_reason == "low_confidence"
                and _SHORT_TOKEN_RE.fullmatch(text)
                and confidence is not None
                and confidence >= short_floor
                and _meets_inclusive_ratio(
                    _owner_containment(bbox, normalized_owner_bbox),
                    SHORT_TOKEN_MIN_OWNER_CONTAINMENT,
                )
            )
            if is_short_alternative:
                if short_count >= MAX_SPATIAL_SHORT_ALTERNATIVES:
                    summary["short_alternative_limit_reached"] = True
                    summary["truncated_occurrences"] += 1
                    continue
                else:
                    short_count += 1

            occurrence_id = _stable_id(
                "ocr-token",
                {
                    **owner_anchor,
                    "line_occurrence_id": line_occurrence_id,
                    "text": text,
                    "bbox": bbox,
                    "crop_pixel_bbox": crop_pixel_bbox,
                    "ocr_pass": token_pass,
                    "word_index": word_index,
                    "token_sequence_index": token_sequence_index,
                },
            )
            occurrence: dict[str, Any] = {
                "occurrence_id": occurrence_id,
                "line_occurrence_id": line_occurrence_id,
                "text": text,
                "bbox": bbox,
                "confidence": confidence,
                "ocr_pass": token_pass,
                "word_index": word_index,
                "selected": True,
                "primary_selected": primary_line,
                "short_alternative": is_short_alternative,
                "retention_reason": "pending",
                "duplicate_of": None,
                "_normalized_text": normalized_text,
                "_quality_accepted": quality_accepted,
                "_rejected_pass_candidate": rejected_pass_candidate,
                "_line_index": line_index,
                "_source_order": len(candidates),
            }
            if crop_pixel_bbox is not None:
                occurrence["crop_pixel_bbox"] = crop_pixel_bbox

            # Reserve enough bytes for the final reason and a full duplicate
            # identifier so post-deduplication cannot exceed the hard bound.
            public_probe = {
                key: value
                for key, value in occurrence.items()
                if not key.startswith("_")
            }
            public_probe["retention_reason"] = (
                "overlapping_equivalent_ocr_diagnostic"
            )
            public_probe["duplicate_of"] = (
                "ocr-token-" + ("f" * 64)
            )
            public_probe["selected"] = False
            public_probe["primary_selected"] = False
            public_probe["short_alternative"] = False
            projected_bytes = len(
                json.dumps(
                    public_probe,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            current_bytes = int(summary["serialized_occurrence_bytes"])
            separator_bytes = 1 if candidates else 0
            if (
                current_bytes + separator_bytes + projected_bytes
                > MAX_SPATIAL_OCCURRENCE_JSON_BYTES
            ):
                summary["serialized_byte_limit_reached"] = True
                summary["truncated_occurrences"] += 1
                continue
            summary["serialized_occurrence_bytes"] = (
                current_bytes + separator_bytes + projected_bytes
            )
            candidates.append(occurrence)
        if summary["source_token_limit_reached"]:
            break

    by_text: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        by_text.setdefault(candidate["_normalized_text"], []).append(candidate)

    def selection_key(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            not bool(candidate["primary_selected"]),
            not bool(candidate["_quality_accepted"]),
            bool(candidate["_rejected_pass_candidate"]),
            -(
                float(candidate["confidence"])
                if candidate["confidence"] is not None
                else -1.0
            ),
            candidate["ocr_pass"] != "standard",
            candidate["_line_index"],
            candidate["word_index"],
            candidate["occurrence_id"],
        )

    # At most 2,048 candidates reach this bounded clustering stage. Exact
    # comparison text partitions the work before geometry is considered.
    for equivalents in by_text.values():
        parents = list(range(len(equivalents)))

        def find(index: int) -> int:
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index

        def union(first: int, second: int) -> None:
            first_root = find(first)
            second_root = find(second)
            if first_root != second_root:
                parents[second_root] = first_root

        geometry_representatives: dict[
            tuple[float, float, float, float],
            int,
        ] = {}
        unique_geometry_indexes: list[int] = []
        for index, candidate in enumerate(equivalents):
            bbox = candidate["bbox"]
            geometry_key = (
                float(bbox["x"]),
                float(bbox["y"]),
                float(bbox["width"]),
                float(bbox["height"]),
            )
            prior_index = geometry_representatives.get(geometry_key)
            if prior_index is None:
                geometry_representatives[geometry_key] = index
                unique_geometry_indexes.append(index)
            else:
                union(prior_index, index)

        ordered_indexes = sorted(
            unique_geometry_indexes,
            key=lambda index: (
                float(equivalents[index]["bbox"]["x"]),
                float(equivalents[index]["bbox"]["y"]),
                index,
            ),
        )
        for ordered_position, first_index in enumerate(ordered_indexes):
            first = equivalents[first_index]
            first_right = (
                float(first["bbox"]["x"])
                + float(first["bbox"]["width"])
            )
            for second_index in ordered_indexes[ordered_position + 1 :]:
                second = equivalents[second_index]
                if float(second["bbox"]["x"]) >= first_right:
                    break
                if _meets_inclusive_ratio(
                    _reciprocal_overlap(first["bbox"], second["bbox"]),
                    SPATIAL_TOKEN_OVERLAP_THRESHOLD,
                ):
                    union(first_index, second_index)

        components: dict[int, list[dict[str, Any]]] = {}
        for index, candidate in enumerate(equivalents):
            components.setdefault(find(index), []).append(candidate)
        for component in components.values():
            winner = min(component, key=selection_key)
            for candidate in component:
                if candidate is winner:
                    continue
                candidate["selected"] = False
                candidate["primary_selected"] = False
                candidate["duplicate_of"] = winner["occurrence_id"]

    for candidate in candidates:
        if candidate["duplicate_of"] is not None:
            candidate["retention_reason"] = (
                "overlapping_equivalent_ocr_diagnostic"
            )
        elif candidate["short_alternative"]:
            candidate["retention_reason"] = "grounded_short_alternative"
        elif candidate["_rejected_pass_candidate"]:
            candidate["retention_reason"] = "rejected_ocr_pass_diagnostic"
        elif not candidate["_quality_accepted"]:
            candidate["retention_reason"] = "quality_rejected_diagnostic"
        elif candidate["primary_selected"]:
            candidate["retention_reason"] = "primary_ocr_token"
        else:
            candidate["retention_reason"] = "subordinate_ocr_token"

    candidates.sort(key=lambda candidate: candidate["_source_order"])
    occurrences = [
        {
            key: value
            for key, value in candidate.items()
            if not key.startswith("_")
            and not (key == "duplicate_of" and value is None)
        }
        for candidate in candidates
    ]
    actual_bytes = len(
        json.dumps(
            occurrences,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    if actual_bytes > MAX_SPATIAL_OCCURRENCE_JSON_BYTES:
        summary.update(
            {
                "fail_closed_overflow": True,
                "overflow_reason": "serialized_payload_exceeded",
                "serialized_byte_limit_reached": True,
                "truncated_occurrences": (
                    int(summary["truncated_occurrences"])
                    + len(occurrences)
                ),
                "serialized_occurrence_bytes": 2,
            }
        )
        return [], summary

    summary.update(
        {
            "total_occurrences": len(occurrences),
            "selected_occurrences": sum(
                bool(item["selected"]) for item in occurrences
            ),
            "primary_selected_occurrences": sum(
                bool(item["primary_selected"]) for item in occurrences
            ),
            "duplicate_occurrences": sum(
                item.get("duplicate_of") is not None for item in occurrences
            ),
            "short_alternative_occurrences": sum(
                bool(item["short_alternative"]) for item in occurrences
            ),
            "serialized_occurrence_bytes": actual_bytes,
        }
    )
    return occurrences, summary
