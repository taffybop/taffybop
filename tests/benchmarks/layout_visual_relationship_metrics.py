"""Retained real-document and bounded-stage metrics for P03-US02."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import resource
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from app.config import Settings
from app.services.ir import round_trip_document
from app.services.layout import apply_layout_projection
from app.services.pipeline import parse_document
from app.services.serializer import to_markdown
from tests.regression.phase_03.test_p03_us02_real_visual_benchmarks import (
    COMPONENT_CAPTION,
    EXPECTED_UBER_CONTAINED_VALUES,
    EXHIBIT_8_CHILDREN,
    EXPECTED_LINKED_CAPTIONS,
    UBER_FALSE_PHOTO_OCR,
)
from tests.stories.phase_03.test_p03_us02_visual_children import (
    _box,
    _document,
    _enabled,
    _raw_graph,
    _raw_visual,
    _text_node,
    _visual_item,
)


WORKSPACE = Path(__file__).resolve().parents[2]
CORPUS = WORKSPACE / "benchmark-expertmodeldata"
CASES = (
    "catastrophe-recap",
    "manufacturing-report",
    "uber-earnings",
    "component-datasheet",
    "finance-10k",
)
EXPECTED_INPUTS = {
    "catastrophe-recap": {
        "size_bytes": 58_779,
        "sha256": (
            "d4d365e06715c4bf9b9ab2159caf79c1ef827234b3bf0b586357e3601795b87e"
        ),
    },
    "manufacturing-report": {
        "size_bytes": 380_274,
        "sha256": (
            "414570f576f16adb8cbe37c43f92ef474a0a0a218d3a2b5a77ffb595dc9eb58f"
        ),
    },
    "uber-earnings": {
        "size_bytes": 7_584_019,
        "sha256": (
            "76a4d3fb8af06adc88ed68538997ef28afb26b377f41014cd83eeaddcbcd29e5"
        ),
    },
    "component-datasheet": {
        "size_bytes": 329_199,
        "sha256": (
            "5fc8143f33d156d914b0f139177344be6ad2b0a8d2906413424d6dda93fe36a4"
        ),
    },
    "finance-10k": {
        "size_bytes": 87_105,
        "sha256": (
            "e924db5e2dbe8845997093d550b3dcdea5560b5c4a75957b6ef084f556149086"
        ),
    },
}
PHASE_02_PERFORMANCE_BASELINES = {
    "manufacturing-report": {
        "wall_seconds": 11.58,
        "peak_rss_mib": 1_825.8,
    },
    "uber-earnings": {
        "wall_seconds": 29.15,
        "peak_rss_mib": 2_589.5,
    },
}
LAYOUT_OVERHEAD_CEILING_SECONDS = (
    PHASE_02_PERFORMANCE_BASELINES["manufacturing-report"]["wall_seconds"]
    * 0.05
)
CODE_PATHS = (
    ".env.example",
    "README.md",
    "app/config.py",
    "app/models.py",
    "app/services/ir.py",
    "app/services/layout.py",
    "app/services/pipeline.py",
    "app/services/presentation.py",
    "app/services/serializer.py",
    "tests/stories/phase_03/test_p03_us01_table_captions.py",
    "tests/stories/phase_03/test_p03_us02_visual_children.py",
    "tests/contract/test_p03_us01_table_caption_contract.py",
    "tests/contract/test_p03_us02_visual_relationship_contract.py",
    "tests/regression/phase_03/test_p03_us02_real_visual_benchmarks.py",
    "tests/performance/test_p03_us02_visual_relationship_performance.py",
    "tests/benchmarks/layout_visual_relationship_metrics.py",
    "frontend/lib/types.ts",
    "frontend/lib/canonical-presentation.ts",
    "frontend/lib/layout-relationships.ts",
    "frontend/lib/normalize-document-json.ts",
    "frontend/lib/primary-item-text.ts",
    "frontend/lib/serialize-output.ts",
    "frontend/app/clearleaf-workspace.tsx",
    "frontend/app/globals.css",
    "frontend/README.md",
    "frontend/tests/p03-us01-table-captions.test.mts",
    "frontend/tests/p03-us02-visual-relationships.test.mts",
    (
        "tracker/phase-03-layout/decisions/"
        "P03-visual-relationship-policy.md"
    ),
)

_VISUAL_TYPES = frozenset({"image", "chart", "diagram"})
_UBER_PHOTO_BBOX = (68.978, 69.672, 1781.229, 522.914)
_COMPONENT_PHOTO_BBOX = (114.983, 151.646, 295.742, 265.243)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _settings(enabled: bool) -> Settings:
    return Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        layout_visual_relationships_enabled=enabled,
    )


def _semantic_payload(payload: dict[str, Any]) -> dict[str, Any]:
    detached = json.loads(_canonical_json(payload))
    detached.get("processing", {}).pop("duration_ms", None)
    return detached


def _box_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "x": value["x"],
        "y": value["y"],
        "width": value["width"],
        "height": value["height"],
    }


def _public_box_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **_box_identity(value),
        "unit": value["unit"],
    }


def _box_tuple(value: Mapping[str, Any]) -> tuple[float, float, float, float]:
    return (
        float(value["x"]),
        float(value["y"]),
        float(value["width"]),
        float(value["height"]),
    )


def _containment_ratio(
    child: Mapping[str, Any],
    owner: Mapping[str, Any],
) -> float:
    child_x, child_y, child_width, child_height = _box_tuple(child)
    owner_x, owner_y, owner_width, owner_height = _box_tuple(owner)
    overlap_width = max(
        min(child_x + child_width, owner_x + owner_width)
        - max(child_x, owner_x),
        0.0,
    )
    overlap_height = max(
        min(child_y + child_height, owner_y + owner_height)
        - max(child_y, owner_y),
        0.0,
    )
    child_area = child_width * child_height
    return (
        overlap_width * overlap_height / child_area
        if child_area > 0
        else 0.0
    )


def _expected_caption_records(case: str) -> list[dict[str, Any]]:
    return [
        {
            "page_index": page_index,
            "value": value,
            "bbox": {
                "x": caption_bbox[0],
                "y": caption_bbox[1],
                "width": caption_bbox[2],
                "height": caption_bbox[3],
            },
            "owner_bbox": {
                "x": owner_bbox[0],
                "y": owner_bbox[1],
                "width": owner_bbox[2],
                "height": owner_bbox[3],
            },
            "side": side,
        }
        for (
            page_index,
            value,
            caption_bbox,
            owner_bbox,
            side,
        ) in EXPECTED_LINKED_CAPTIONS.get(case, [])
    ]


def _visual_caption_records(
    payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for page in payload["pages"]:
        page_items = page["items"]
        positions = {
            str(item.get("id")): index
            for index, item in enumerate(page_items)
        }
        items_by_id = {
            str(item.get("id")): item for item in page_items
        }
        for caption_position, item in enumerate(page_items):
            if item.get("type") != "caption":
                continue
            owner_id = item.get("caption_of")
            owner = items_by_id.get(str(owner_id))
            if not isinstance(owner, Mapping):
                continue
            if str(owner.get("type") or "").casefold() not in _VISUAL_TYPES:
                continue
            caption_box = item.get("bbox") or {}
            owner_box = owner.get("bbox") or {}
            caption_bottom = float(caption_box.get("y") or 0) + float(
                caption_box.get("height") or 0
            )
            owner_bottom = float(owner_box.get("y") or 0) + float(
                owner_box.get("height") or 0
            )
            if caption_bottom <= float(owner_box.get("y") or 0):
                side = "above"
            elif owner_bottom <= float(caption_box.get("y") or 0):
                side = "below"
            else:
                side = "ambiguous"
            owner_position = positions[str(owner_id)]
            relationship_id = item.get("relationship_id")
            relationships = owner.get("relationships") or []
            owner_linked_back = any(
                isinstance(relationship, Mapping)
                and relationship.get("id") == relationship_id
                and relationship.get("type") == "caption_of"
                and relationship.get("source_id") == item.get("id")
                and relationship.get("target_id") == owner.get("id")
                for relationship in relationships
            )
            value = str(item.get("value") or "")
            records.append(
                {
                    "page_index": page["page_index"],
                    "id": item["id"],
                    "value": value,
                    "bbox": item["bbox"],
                    "source": item.get("source"),
                    "confidence": item.get("confidence"),
                    "caption_of": owner_id,
                    "relationship_id": relationship_id,
                    "relationship_type": item.get("relationship_type"),
                    "relationship_basis": item.get("relationship_basis"),
                    "owner_type": owner.get("type"),
                    "owner_bbox": owner.get("bbox"),
                    "owner_linked_back": owner_linked_back,
                    "side": side,
                    "side_order_correct": (
                        (
                            side == "above"
                            and caption_position + 1 == owner_position
                        )
                        or (
                            side == "below"
                            and owner_position + 1 == caption_position
                        )
                    ),
                    "owner_external_text_clean": all(
                        value not in str(owner.get(field) or "")
                        for field in ("value", "md", "caption")
                    ),
                }
            )
    return records


def _caption_identity_records(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "page_index": record["page_index"],
            "value": record["value"],
            "bbox": _box_identity(record["bbox"]),
            "owner_bbox": _box_identity(record["owner_bbox"]),
            "side": record["side"],
        }
        for record in records
    ]


def _visual_owner_summaries(
    payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for page in payload["pages"]:
        for item in page["items"]:
            if str(item.get("type") or "").casefold() not in _VISUAL_TYPES:
                continue
            contained = item.get("contained_items") or []
            summaries.append(
                {
                    "page_index": page["page_index"],
                    "id": item["id"],
                    "type": item["type"],
                    "bbox": item.get("bbox"),
                    "include_ocr_in_primary": item.get(
                        "include_ocr_in_primary"
                    ),
                    "caption_field_present": bool(item.get("caption")),
                    "caption_source_field_present": bool(
                        item.get("caption_source")
                    ),
                    "caption_count": len(item.get("caption_ids") or []),
                    "contains_count": len(item.get("contains_ids") or []),
                    "contained_item_count": len(contained),
                    "contained_value_sha256": _sha256_bytes(
                        _canonical_json(
                            sorted(
                                str(child.get("value") or "")
                                for child in contained
                                if isinstance(child, Mapping)
                            )
                        ).encode("utf-8")
                    ),
                }
            )
    return summaries


def _relationship_summary(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    counts = {
        "relationship_count": 0,
        "caption_relationship_count": 0,
        "contains_relationship_count": 0,
        "unresolved_endpoint_count": 0,
        "duplicate_page_item_id_count": 0,
        "duplicate_contained_item_id_count": 0,
        "duplicate_relationship_id_count": 0,
        "invalid_caption_relationship_count": 0,
        "invalid_contains_relationship_count": 0,
        "caption_backlink_failure_count": 0,
        "contains_backlink_failure_count": 0,
        "contained_semantics_failure_count": 0,
        "contained_page_item_leak_count": 0,
        "contained_canonical_primary_leak_count": 0,
        "missing_canonical_presentation_count": 0,
        "missing_canonical_page_count": 0,
        "duplicate_canonical_page_index_count": 0,
        "missing_canonical_blocks_count": 0,
        "extra_canonical_page_count": 0,
    }
    canonical = payload.get("canonical_presentation")
    canonical_page_list = (
        canonical.get("pages")
        if isinstance(canonical, Mapping)
        else None
    )
    if not isinstance(canonical_page_list, list):
        counts["missing_canonical_presentation_count"] = 1
        canonical_page_list = []
    canonical_pages_by_index: dict[Any, list[Mapping[str, Any]]] = (
        defaultdict(list)
    )
    for canonical_page in canonical_page_list:
        if isinstance(canonical_page, Mapping):
            canonical_pages_by_index[
                canonical_page.get("page_index")
            ].append(canonical_page)
    payload_page_indexes = {
        page["page_index"] for page in payload["pages"]
    }
    counts["extra_canonical_page_count"] = sum(
        len(pages)
        for page_index, pages in canonical_pages_by_index.items()
        if page_index not in payload_page_indexes
    )
    document_relationship_ids: list[str] = []

    for page in payload["pages"]:
        page_items = [
            item for item in page["items"] if isinstance(item, Mapping)
        ]
        page_item_id_list = [str(item["id"]) for item in page_items]
        counts["duplicate_page_item_id_count"] += (
            len(page_item_id_list) - len(set(page_item_id_list))
        )
        items_by_id = {
            str(item["id"]): item for item in page_items
        }
        page_item_ids = set(items_by_id)
        contained_by_owner: dict[str, dict[str, Mapping[str, Any]]] = {}
        contained_id_lists: dict[str, list[str]] = {}
        all_page_contained_ids: list[str] = []
        for owner in page_items:
            owner_id = str(owner["id"])
            child_ids = [
                str(child["id"])
                for child in owner.get("contained_items") or []
                if isinstance(child, Mapping)
            ]
            contained_id_lists[owner_id] = child_ids
            all_page_contained_ids.extend(child_ids)
            contained_by_owner[owner_id] = {
                str(child["id"]): child
                for child in owner.get("contained_items") or []
                if isinstance(child, Mapping)
            }
        counts["duplicate_contained_item_id_count"] += (
            len(all_page_contained_ids)
            - len(set(all_page_contained_ids))
        )
        contained_ids = {
            child_id
            for children in contained_by_owner.values()
            for child_id in children
        }
        resolved_ids = page_item_ids | contained_ids
        counts["contained_page_item_leak_count"] += len(
            contained_ids & page_item_ids
        )

        canonical_page_candidates = canonical_pages_by_index.get(
            page["page_index"], []
        )
        if not canonical_page_candidates:
            counts["missing_canonical_page_count"] += 1
            canonical_page = None
        else:
            canonical_page = canonical_page_candidates[0]
            counts["duplicate_canonical_page_index_count"] += max(
                len(canonical_page_candidates) - 1,
                0,
            )
        canonical_blocks = (
            canonical_page.get("blocks")
            if isinstance(canonical_page, Mapping)
            else None
        )
        if not isinstance(canonical_blocks, list):
            counts["missing_canonical_blocks_count"] += 1
            canonical_blocks = []
        included_element_ids = {
            str(element_id)
            for block in canonical_blocks
            if isinstance(block, Mapping)
            and block.get("omission_reason") is None
            for element_id in [
                block.get("primary_element_id"),
                *(block.get("contributing_element_ids") or []),
            ]
            if isinstance(element_id, str)
        }
        counts["contained_canonical_primary_leak_count"] += len(
            contained_ids & included_element_ids
        )

        page_relationships: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
        for owner in page_items:
            for relationship in owner.get("relationships") or []:
                if (
                    isinstance(relationship, Mapping)
                    and relationship.get("type")
                    in {"caption_of", "contains"}
                ):
                    page_relationships.append((owner, relationship))
        document_relationship_ids.extend(
            str(relationship.get("id") or "")
            for _owner, relationship in page_relationships
        )
        counts["relationship_count"] += len(page_relationships)

        for owner, relationship in page_relationships:
            relationship_type = relationship.get("type")
            relationship_id = str(relationship.get("id") or "")
            source_id = str(relationship.get("source_id") or "")
            target_id = str(relationship.get("target_id") or "")
            owner_id = str(owner["id"])
            if source_id not in resolved_ids or target_id not in resolved_ids:
                counts["unresolved_endpoint_count"] += 1

            if relationship_type == "caption_of":
                counts["caption_relationship_count"] += 1
                caption = items_by_id.get(source_id)
                valid = bool(
                    relationship_id
                    and target_id == owner_id
                    and isinstance(caption, Mapping)
                    and caption.get("type") == "caption"
                    and caption.get("caption_of") == owner_id
                    and caption.get("relationship_id") == relationship_id
                    and caption.get("relationship_type") == "caption_of"
                )
                if not valid:
                    counts["invalid_caption_relationship_count"] += 1
                caption_ids = owner.get("caption_ids")
                if (
                    not isinstance(caption_ids, list)
                    or caption_ids.count(source_id) != 1
                ):
                    counts["caption_backlink_failure_count"] += 1
                continue

            counts["contains_relationship_count"] += 1
            child = contained_by_owner.get(owner_id, {}).get(target_id)
            valid = bool(
                relationship_id
                and str(owner.get("type") or "").casefold()
                in _VISUAL_TYPES
                and source_id == owner_id
                and isinstance(child, Mapping)
                and child.get("relationship_id") == relationship_id
                and child.get("relationship_type") == "contains"
            )
            if not valid:
                counts["invalid_contains_relationship_count"] += 1
            contains_ids = owner.get("contains_ids")
            if (
                not isinstance(contains_ids, list)
                or contains_ids.count(target_id) != 1
            ):
                counts["contains_backlink_failure_count"] += 1
            if (
                not isinstance(child, Mapping)
                or child.get("contained_by") != owner_id
                or child.get("presentation_role") != "subordinate"
                or child.get("type") != "visual_text"
            ):
                counts["contained_semantics_failure_count"] += 1

        for owner in page_items:
            if str(owner.get("type") or "").casefold() not in _VISUAL_TYPES:
                continue
            owner_id = str(owner["id"])
            owner_relationships = [
                relationship
                for relationship_owner, relationship in page_relationships
                if relationship_owner is owner
            ]
            descriptor_caption_ids = [
                str(relationship.get("source_id") or "")
                for relationship in owner_relationships
                if relationship.get("type") == "caption_of"
                and relationship.get("target_id") == owner_id
            ]
            page_caption_ids = [
                item_id
                for item_id, item in items_by_id.items()
                if item.get("type") == "caption"
                and item.get("caption_of") == owner_id
            ]
            raw_caption_ids = owner.get("caption_ids")
            declared_caption_ids = (
                [str(value) for value in raw_caption_ids]
                if isinstance(raw_caption_ids, list)
                else []
            )
            raw_owner_caption_of = owner.get("caption_of")
            owner_caption_of_ids = (
                [str(value) for value in raw_owner_caption_of]
                if isinstance(raw_owner_caption_of, list)
                else []
            )
            caption_shape_valid = (
                raw_caption_ids is None
                or isinstance(raw_caption_ids, list)
            ) and (
                raw_owner_caption_of is None
                or isinstance(raw_owner_caption_of, list)
            )
            if (
                not caption_shape_valid
                or len(declared_caption_ids)
                != len(set(declared_caption_ids))
                or sorted(declared_caption_ids)
                != sorted(descriptor_caption_ids)
                or sorted(declared_caption_ids)
                != sorted(page_caption_ids)
                or (
                    raw_owner_caption_of is not None
                    and sorted(owner_caption_of_ids)
                    != sorted(declared_caption_ids)
                )
            ):
                counts["caption_backlink_failure_count"] += 1
            if sorted(descriptor_caption_ids) != sorted(page_caption_ids):
                counts["invalid_caption_relationship_count"] += 1

            descriptor_contains_ids = [
                str(relationship.get("target_id") or "")
                for relationship in owner_relationships
                if relationship.get("type") == "contains"
                and relationship.get("source_id") == owner_id
            ]
            raw_contains_ids = owner.get("contains_ids")
            declared_contains_ids = (
                [str(value) for value in raw_contains_ids]
                if isinstance(raw_contains_ids, list)
                else []
            )
            nested_contains_ids = contained_id_lists.get(owner_id, [])
            if (
                (
                    raw_contains_ids is not None
                    and not isinstance(raw_contains_ids, list)
                )
                or len(declared_contains_ids)
                != len(set(declared_contains_ids))
                or sorted(declared_contains_ids)
                != sorted(descriptor_contains_ids)
                or sorted(declared_contains_ids)
                != sorted(nested_contains_ids)
            ):
                counts["contains_backlink_failure_count"] += 1
            if sorted(descriptor_contains_ids) != sorted(
                nested_contains_ids
            ):
                counts["invalid_contains_relationship_count"] += 1

    counts["duplicate_relationship_id_count"] = (
        len(document_relationship_ids)
        - len(set(document_relationship_ids))
    )
    return counts


def _find_visual_by_bbox(
    payload: Mapping[str, Any],
    expected_bbox: tuple[float, float, float, float],
) -> Mapping[str, Any] | None:
    return next(
        (
            item
            for page in payload["pages"]
            for item in page["items"]
            if str(item.get("type") or "").casefold() in _VISUAL_TYPES
            and isinstance(item.get("bbox"), Mapping)
            and _box_tuple(item["bbox"]) == expected_bbox
        ),
        None,
    )


def _case_controls(
    case: str,
    payload: Mapping[str, Any],
    markdown: str,
) -> dict[str, Any]:
    captions = _visual_caption_records(payload)
    page_items = [
        item for page in payload["pages"] for item in page["items"]
    ]
    if case == "catastrophe-recap":
        expected_caption = EXPECTED_LINKED_CAPTIONS[case][0][1]
        caption = next(
            (
                item
                for item in captions
                if item["value"] == expected_caption
            ),
            None,
        )
        owner = (
            next(
                (
                    item
                    for item in page_items
                    if item.get("id") == caption["caption_of"]
                ),
                None,
            )
            if caption is not None
            else None
        )
        contained = {
            str(item.get("value")): item
            for item in (
                owner.get("contained_items") or []
                if isinstance(owner, Mapping)
                else []
            )
        }
        expected_children = [
            {
                "value": value,
                "bbox": {
                    "x": bbox[0],
                    "y": bbox[1],
                    "width": bbox[2],
                    "height": bbox[3],
                },
            }
            for value, bbox in EXHIBIT_8_CHILDREN.items()
        ]
        actual_children = [
            {
                "value": value,
                "bbox": (
                    _box_identity(contained[value]["bbox"])
                    if value in contained
                    else None
                ),
            }
            for value in EXHIBIT_8_CHILDREN
        ]
        return {
            "expected_exhibit_8_children": expected_children,
            "actual_exhibit_8_children": actual_children,
            "exact_exhibit_8_children": (
                actual_children == expected_children
            ),
            "caption_fragment_leak_count": sum(
                fragment in record["value"].splitlines()
                for record in captions
                for fragment in EXHIBIT_8_CHILDREN
            ),
        }
    if case == "uber-earnings":
        owner = _find_visual_by_bbox(payload, _UBER_PHOTO_BBOX)
        contained = (
            owner.get("contained_items") or []
            if isinstance(owner, Mapping)
            else []
        )
        values = [
            str(item.get("value") or "")
            for item in contained
            if isinstance(item, Mapping)
        ]
        primary_lines = {
            line.strip()
            for field in ("value", "md", "caption")
            for line in str(
                owner.get(field) or ""
                if isinstance(owner, Mapping)
                else ""
            ).splitlines()
            if line.strip()
        }
        return {
            "photo_found": owner is not None,
            "photo_bbox": (
                _public_box_identity(owner["bbox"])
                if isinstance(owner, Mapping)
                and isinstance(owner.get("bbox"), Mapping)
                else None
            ),
            "include_ocr_in_primary": (
                owner.get("include_ocr_in_primary")
                if isinstance(owner, Mapping)
                else None
            ),
            "caption_fields_empty": bool(
                isinstance(owner, Mapping)
                and not owner.get("caption")
                and not owner.get("caption_source")
            ),
            "linked_caption_count": sum(
                record.get("caption_of") == owner.get("id")
                for record in captions
            )
            if isinstance(owner, Mapping)
            else 0,
            "contained_item_count": len(contained),
            "contained_values": sorted(values),
            "contained_value_sha256": _sha256_bytes(
                _canonical_json(sorted(values)).encode("utf-8")
            ),
            "contained_values_exact": bool(
                len(values) == len(set(values)) == 15
                and set(values) == EXPECTED_UBER_CONTAINED_VALUES
            ),
            "contained_values_are_strict_source_subset": (
                set(values) < UBER_FALSE_PHOTO_OCR
            ),
            "minimum_containment_ratio": min(
                (
                    _containment_ratio(
                        item["bbox"],
                        owner["bbox"],
                    )
                    for item in contained
                    if isinstance(item, Mapping)
                    and isinstance(item.get("bbox"), Mapping)
                    and isinstance(owner, Mapping)
                    and isinstance(owner.get("bbox"), Mapping)
                ),
                default=0.0,
            ),
            "false_ocr_value_coverage": (
                len(set(values) & UBER_FALSE_PHOTO_OCR)
                / len(UBER_FALSE_PHOTO_OCR)
            ),
            "false_ocr_primary_leak_count": len(
                primary_lines & UBER_FALSE_PHOTO_OCR
            ),
        }
    if case == "component-datasheet":
        owner = _find_visual_by_bbox(payload, _COMPONENT_PHOTO_BBOX)
        source_caption_items = [
            item
            for item in page_items
            if item.get("value") == COMPONENT_CAPTION
        ]
        return {
            "photo_found": owner is not None,
            "source_caption_page_item_count": len(source_caption_items),
            "source_caption_unowned": bool(
                len(source_caption_items) == 1
                and not source_caption_items[0].get("caption_of")
                and (
                    not isinstance(owner, Mapping)
                    or source_caption_items[0].get("id")
                    not in {
                        *list(owner.get("caption_ids") or []),
                        *list(owner.get("caption_of") or []),
                    }
                )
            ),
            "source_caption_markdown_count": markdown.count(
                COMPONENT_CAPTION
            ),
            "invented_caption_link_count": sum(
                record.get("caption_of") == owner.get("id")
                for record in captions
            )
            if isinstance(owner, Mapping)
            else 0,
        }
    if case == "finance-10k":
        return {
            "visual_owner_count": sum(
                str(item.get("type") or "").casefold() in _VISUAL_TYPES
                for item in page_items
            ),
            "visual_caption_count": len(captions),
        }
    return {}


def _table_content(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "page_index": page["page_index"],
            "rows": item.get("rows"),
            "cells": item.get("cells"),
        }
        for page in payload["pages"]
        for item in page["items"]
        if item.get("type") == "table"
    ]


def _parse_snapshot(
    case: str,
    enabled: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = CORPUS / f"{case}.pdf"
    started = time.perf_counter()
    result = parse_document(
        path.read_bytes(),
        path.name,
        _settings(enabled),
    )
    wall_seconds = time.perf_counter() - started
    payload = result.model_dump(mode="json", exclude_none=False)
    serialized_json = _canonical_json(payload).encode("utf-8")
    markdown = to_markdown(payload)
    markdown_bytes = markdown.encode("utf-8")
    return payload, {
        "enabled": enabled,
        "wall_seconds": round(wall_seconds, 6),
        "processing_duration_ms": payload["processing"]["duration_ms"],
        "peak_rss_bytes": _rss_bytes(),
        "json_size_bytes": len(serialized_json),
        "json_sha256": _sha256_bytes(serialized_json),
        "semantic_json_sha256": _sha256_bytes(
            _canonical_json(_semantic_payload(payload)).encode("utf-8")
        ),
        "markdown_size_bytes": len(markdown_bytes),
        "markdown_sha256": _sha256_bytes(markdown_bytes),
        "caption_records": _visual_caption_records(payload),
        "visual_owner_summaries": _visual_owner_summaries(payload),
        "relationship_summary": _relationship_summary(payload),
        "controls": _case_controls(case, payload, markdown),
        "table_content_sha256": _sha256_bytes(
            _canonical_json(_table_content(payload)).encode("utf-8")
        ),
    }


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _parse_snapshot_fresh(
    case: str,
    enabled: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    with tempfile.TemporaryDirectory(
        prefix=f"p03-us02-{case}-",
    ) as temporary_directory:
        snapshot_path = Path(temporary_directory) / "snapshot.json"
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "tests.benchmarks.layout_visual_relationship_metrics",
                "--worker-case",
                case,
                "--worker-enabled",
                "true" if enabled else "false",
                "--output",
                str(snapshot_path),
            ],
            cwd=WORKSPACE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=330,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "fresh metrics worker failed for "
                f"{case}/{enabled}: {completed.stderr[-4000:]}"
            )
        snapshot = json.loads(
            snapshot_path.read_text(encoding="utf-8")
        )
    return snapshot["payload"], snapshot["metrics"]


def _stage_metrics() -> dict[str, Any]:
    raw = _raw_graph(
        texts=[
            _text_node(
                "#/texts/0",
                "Figure title",
                _box(10, 20, 60, 25),
            ),
            _text_node(
                "#/texts/1",
                "er cas",
                _box(20, 42, 50, 47),
                label="text",
            ),
            _text_node(
                "#/texts/2",
                "C",
                _box(55, 52, 58, 57),
                label="text",
            ),
        ],
        visuals=[
            _raw_visual(
                box=_box(10, 30, 80, 70),
                captions=("#/texts/0",),
                children=("#/texts/0", "#/texts/1", "#/texts/2"),
            )
        ],
    )
    _, ir = round_trip_document(
        _document(
            _visual_item(
                value="Figure title\ner cas\nC\nTrusted OCR",
                ocr_text="Trusted OCR",
                include_ocr_in_primary=True,
            )
        ),
        raw_graph=raw,
        native_texts=("Figure title er cas C",),
    )
    settings = _enabled()
    for _ in range(5):
        apply_layout_projection(ir, settings)
    samples: list[float] = []
    tracemalloc.start()
    for _ in range(100):
        started = time.perf_counter()
        apply_layout_projection(ir, settings)
        samples.append(time.perf_counter() - started)
    _current, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "warmup_count": 5,
        "sample_count": 100,
        "p50_seconds": round(statistics.median(samples), 9),
        "p95_seconds": round(
            statistics.quantiles(
                samples,
                n=100,
                method="inclusive",
            )[94],
            9,
        ),
        "max_seconds": round(max(samples), 9),
        "min_seconds": round(min(samples), 9),
        "peak_allocated_bytes": peak_bytes,
        "phase_02_reference_seconds": (
            PHASE_02_PERFORMANCE_BASELINES[
                "manufacturing-report"
            ]["wall_seconds"]
        ),
        "five_percent_ceiling_seconds": (
            LAYOUT_OVERHEAD_CEILING_SECONDS
        ),
    }


def generate_artifact() -> dict[str, Any]:
    cases: dict[str, Any] = {}
    for case in CASES:
        _disabled_payload, disabled = _parse_snapshot_fresh(case, False)
        enabled_payload, enabled = _parse_snapshot_fresh(case, True)
        expected_records = _expected_caption_records(case)
        actual_records = _caption_identity_records(
            enabled["caption_records"]
        )
        expected_keys = {
            _canonical_json(record) for record in expected_records
        }
        actual_keys = {
            _canonical_json(record) for record in actual_records
        }
        matched_count = len(expected_keys & actual_keys)
        expected_texts = [
            record["value"] for record in expected_records
        ]
        enabled_markdown = to_markdown(enabled_payload)
        source_path = CORPUS / f"{case}.pdf"
        cases[case] = {
            "input_path": f"benchmark-expertmodeldata/{case}.pdf",
            "input_size_bytes": source_path.stat().st_size,
            "input_sha256": _sha256_file(source_path),
            "expected_caption_count": len(expected_records),
            "expected_caption_records": expected_records,
            "expected_caption_texts": expected_texts,
            "actual_caption_count": len(actual_records),
            "actual_caption_records": actual_records,
            "actual_caption_texts": [
                record["value"] for record in actual_records
            ],
            "matched_caption_count": matched_count,
            "unexpected_caption_count": len(actual_keys - expected_keys),
            "exact_caption_identities": (
                actual_records == expected_records
            ),
            "caption_recall": (
                matched_count / len(expected_records)
                if expected_records
                else float(not actual_records)
            ),
            "caption_precision": (
                matched_count / len(actual_records)
                if actual_records
                else float(not expected_records)
            ),
            "markdown_caption_occurrences": {
                text: enabled_markdown.count(text)
                for text in expected_texts
            },
            "table_content_equal": (
                enabled["table_content_sha256"]
                == disabled["table_content_sha256"]
            ),
            "semantic_flag_on_off_equal": (
                enabled["semantic_json_sha256"]
                == disabled["semantic_json_sha256"]
            ),
            "wall_seconds_delta": round(
                enabled["wall_seconds"] - disabled["wall_seconds"],
                6,
            ),
            "processing_duration_ms_delta": (
                enabled["processing_duration_ms"]
                - disabled["processing_duration_ms"]
            ),
            "peak_rss_bytes_delta": (
                enabled["peak_rss_bytes"]
                - disabled["peak_rss_bytes"]
            ),
            "json_size_bytes_delta": (
                enabled["json_size_bytes"]
                - disabled["json_size_bytes"]
            ),
            "flag_off": disabled,
            "flag_on": enabled,
        }

    caption_records = [
        record
        for case in cases.values()
        for record in case["flag_on"]["caption_records"]
    ]
    expected_count = sum(
        case["expected_caption_count"] for case in cases.values()
    )
    actual_count = sum(
        case["actual_caption_count"] for case in cases.values()
    )
    matched_count = sum(
        case["matched_caption_count"] for case in cases.values()
    )
    relationship_summaries = [
        case["flag_on"]["relationship_summary"]
        for case in cases.values()
    ]
    artifact: dict[str, Any] = {
        "schema_version": "1.0",
        "story": "P03-US02",
        "generated_at": datetime.now(UTC).isoformat(),
        "policy": {
            "feature_flag": (
                "PARSER_LAYOUT_VISUAL_RELATIONSHIPS_ENABLED"
            ),
            "default_enabled": False,
            "rollback_value": False,
            "eligible_owner_types": ["image", "chart", "diagram"],
            "relationship_types": ["caption_of", "contains"],
            "minimum_horizontal_overlap": 0.20,
            "maximum_gap_points": 72.0,
            "maximum_internal_overlap": 0.20,
            "minimum_child_containment": 0.80,
            "maximum_caption_references_per_owner": 64,
            "maximum_child_references_per_owner": 256,
            "maximum_visual_owners_per_page": 512,
            "maximum_caption_candidates_per_page": 512,
            "maximum_same_text_candidates_per_page": 128,
            "maximum_caption_bytes": 64 * 1024,
            "maximum_contained_items_bytes": 256 * 1024,
            "hosted_requests": 0,
            "hosted_tokens": 0,
            "hosted_cost_usd": 0,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "docling": importlib.metadata.version("docling"),
            "docling_core": importlib.metadata.version("docling-core"),
            "pydantic": importlib.metadata.version("pydantic"),
        },
        "measurement": {
            "full_parser_process_model": (
                "one fresh subprocess per case and flag state"
            ),
            "full_parser_cache_state": (
                "no in-process converter or model reuse between snapshots"
            ),
            "peak_rss_semantics": (
                "per-worker parse-and-snapshot high-water mark before "
                "evidence-file serialization"
            ),
            "full_parser_deltas_are_paired_process_snapshots": True,
            "layout_stage_isolated_from_full_parser": True,
        },
        "phase_02_performance_baselines": (
            PHASE_02_PERFORMANCE_BASELINES
        ),
        "code_sha256": {
            path: _sha256_file(WORKSPACE / path)
            for path in CODE_PATHS
        },
        "cases": cases,
        "layout_stage": _stage_metrics(),
        "aggregate": {
            "reviewed_caption_expected": expected_count,
            "reviewed_caption_actual": actual_count,
            "reviewed_caption_matched": matched_count,
            "reviewed_caption_recall": matched_count / expected_count,
            "reviewed_caption_precision": matched_count / actual_count,
            "exact_caption_identities_all_cases": all(
                case["exact_caption_identities"]
                for case in cases.values()
            ),
            "duplicate_markdown_caption_count": sum(
                max(count - 1, 0)
                for case in cases.values()
                for count in case[
                    "markdown_caption_occurrences"
                ].values()
            ),
            "caption_bbox_coverage": (
                sum(
                    isinstance(record.get("bbox"), Mapping)
                    and float(record["bbox"].get("width", 0)) > 0
                    and float(record["bbox"].get("height", 0)) > 0
                    for record in caption_records
                )
                / expected_count
            ),
            "caption_relationship_coverage": (
                sum(
                    isinstance(record.get("caption_of"), str)
                    and bool(record["caption_of"])
                    and isinstance(
                        record.get("relationship_id"), str
                    )
                    and bool(record["relationship_id"])
                    and record.get("relationship_type") == "caption_of"
                    and record.get("relationship_basis")
                    == "graph_and_geometry"
                    and record.get("owner_linked_back") is True
                    for record in caption_records
                )
                / expected_count
            ),
            "side_order_coverage": (
                sum(
                    record.get("side_order_correct") is True
                    for record in caption_records
                )
                / expected_count
            ),
            "owner_external_text_clean_coverage": (
                sum(
                    record.get("owner_external_text_clean") is True
                    for record in caption_records
                )
                / expected_count
            ),
            "unresolved_relationship_endpoint_count": sum(
                summary["unresolved_endpoint_count"]
                for summary in relationship_summaries
            ),
            "caption_relationship_count": sum(
                summary["caption_relationship_count"]
                for summary in relationship_summaries
            ),
            "contains_relationship_count": sum(
                summary["contains_relationship_count"]
                for summary in relationship_summaries
            ),
            "contained_page_item_leak_count": sum(
                summary["contained_page_item_leak_count"]
                for summary in relationship_summaries
            ),
            "contained_canonical_primary_leak_count": sum(
                summary["contained_canonical_primary_leak_count"]
                for summary in relationship_summaries
            ),
            "table_content_equal_all_cases": all(
                case["table_content_equal"]
                for case in cases.values()
            ),
            "catastrophe_exact_children": cases[
                "catastrophe-recap"
            ]["flag_on"]["controls"]["exact_exhibit_8_children"],
            "catastrophe_caption_fragment_leak_count": cases[
                "catastrophe-recap"
            ]["flag_on"]["controls"]["caption_fragment_leak_count"],
            "uber_false_ocr_primary_leak_count": cases[
                "uber-earnings"
            ]["flag_on"]["controls"]["false_ocr_primary_leak_count"],
            "uber_false_ocr_value_coverage": cases[
                "uber-earnings"
            ]["flag_on"]["controls"]["false_ocr_value_coverage"],
            "uber_contained_value_sha256": cases[
                "uber-earnings"
            ]["flag_on"]["controls"]["contained_value_sha256"],
            "component_source_caption_count": cases[
                "component-datasheet"
            ]["flag_on"]["controls"]["source_caption_page_item_count"],
            "component_invented_caption_link_count": cases[
                "component-datasheet"
            ]["flag_on"]["controls"]["invented_caption_link_count"],
            "finance_control_semantic_equal": cases[
                "finance-10k"
            ]["semantic_flag_on_off_equal"],
        },
    }
    semantic = {
        key: value
        for key, value in artifact.items()
        if key not in {"generated_at", "semantic_sha256"}
    }
    artifact["semantic_sha256"] = _sha256_bytes(
        _canonical_json(semantic).encode("utf-8")
    )
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--worker-case", choices=CASES)
    parser.add_argument(
        "--worker-enabled",
        choices=("true", "false"),
    )
    arguments = parser.parse_args()
    if arguments.worker_case is not None:
        if arguments.worker_enabled is None:
            parser.error("--worker-enabled is required with --worker-case")
        payload, metrics = _parse_snapshot(
            arguments.worker_case,
            arguments.worker_enabled == "true",
        )
        _write_json_atomic(
            arguments.output,
            {"payload": payload, "metrics": metrics},
        )
        return
    if arguments.worker_enabled is not None:
        parser.error("--worker-case is required with --worker-enabled")
    _write_json_atomic(arguments.output, generate_artifact())


if __name__ == "__main__":
    main()
