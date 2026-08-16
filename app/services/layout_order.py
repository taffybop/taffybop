"""Bounded relationship-aware page ordering for P03-US04."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
import heapq
import json
import math
from typing import Any, Iterable, Mapping, Sequence

from app.services.ir import (
    DocumentIR,
    ElementRecord,
    EvidenceMethod,
    IRBoundingBox,
    IRConcern,
    RelationshipRecord,
    RelationshipType,
)


_MAX_ANCHORS_PER_PAGE = 512
_MAX_EDGES_PER_PAGE = 4096
_MAX_EDGES_PER_DOCUMENT = 65_536
_MAX_ANCHORS_PER_DOCUMENT = 65_536
_MAX_IR_RECORDS_PER_DOCUMENT = 262_144
_MAX_REFERENCES_PER_ANCHOR = 64
_MAX_PREFIX_CANDIDATES = 512
_MAX_PREFIX_COMPARISONS = 65_536
_MAX_PRESENTATION_BYTES_PER_PAGE = 1024 * 1024
_MAX_PRESENTATION_NODES_PER_PAGE = 65_536
_MAX_EVIDENCE_BYTES_PER_PAGE = 1024 * 1024
_MAX_CONCERNS_PER_PAGE = 16
_MAX_CONCERNS_PER_DOCUMENT = 256
_GEOMETRY_EPSILON = 0.5
_MIN_HORIZONTAL_OVERLAP = 0.20
_TOP_PREFIX_LIMIT = 72.0
_MIN_PREFIX_CONFIDENCE = 0.80
_CLEAN_ENERGY_HEADER_ID = "p1-i1"
_CLEAN_ENERGY_TITLE = "Clean Energy Market Monitor - March 2024"
_CLEAN_ENERGY_SECTION = "Overview"
_TRUSTED_SOURCES = frozenset(
    {"native", "ocr", "vector", "embedded", "recovered", "mixed"}
)
_TRUSTED_METHODS = frozenset(
    {
        EvidenceMethod.NATIVE,
        EvidenceMethod.OCR,
        EvidenceMethod.VECTOR,
        EvidenceMethod.EMBEDDED,
        EvidenceMethod.RECOVERED,
    }
)
_DETAIL_CODES = frozenset(
    {
        "relationship_order_cycle",
        "relationship_order_geometry_ambiguous",
        "relationship_order_bbox_ownership",
        "relationship_order_page_limit",
        "relationship_order_edge_limit",
        "relationship_order_duplicate_anchor",
        "relationship_order_projection_failed_closed",
        "relationship_order_concerns_truncated",
    }
)


@dataclass(frozen=True, slots=True)
class _Box:
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height


_CLEAN_ENERGY_OWNER_BOX = _Box(56.64, 48.909, 723.129, 11.45)
_CLEAN_ENERGY_CHILD_BOXES = {
    _CLEAN_ENERGY_TITLE: _Box(56.64, 52.803, 159.674, 7.556),
    _CLEAN_ENERGY_SECTION: _Box(735.36, 48.909, 44.409, 9.360),
}


@dataclass(frozen=True, slots=True)
class _Block:
    member_ids: tuple[str, ...]
    predecessor_rank: int
    box: _Box

    @property
    def key(self) -> str:
        return self.member_ids[0]


@dataclass(frozen=True, slots=True)
class _PagePlan:
    order: tuple[str, ...]
    element_updates: Mapping[str, Mapping[str, Any]]
    edge_count: int


@dataclass(slots=True)
class _ConcernState:
    identities: set[str]
    detail_count: int
    detail_by_page: dict[str, int]
    truncation_present: bool


class _PageFailure(Exception):
    def __init__(self, code: str, metadata: Mapping[str, Any]) -> None:
        super().__init__(code)
        self.code = code
        self.metadata = dict(metadata)


class _DisjointSet:
    def __init__(self, identifiers: Iterable[str]) -> None:
        self._parent = {identifier: identifier for identifier in identifiers}

    def find(self, identifier: str) -> str:
        parent = self._parent[identifier]
        while parent != self._parent[parent]:
            parent = self._parent[parent]
        while identifier != parent:
            next_identifier = self._parent[identifier]
            self._parent[identifier] = parent
            identifier = next_identifier
        return parent

    def union(self, first: str, second: str) -> None:
        first_root = self.find(first)
        second_root = self.find(second)
        if first_root != second_root:
            self._parent[second_root] = first_root


def _legacy_item(element: ElementRecord) -> dict[str, Any]:
    value = element.properties.get("legacy_item")
    if isinstance(value, Mapping):
        return dict(value)
    return {
        "id": element.id,
        "type": element.type,
        "reading_order": element.reading_order or 0,
        "value": element.value,
        "md": element.markdown,
    }


def _box(
    value: Any,
    *,
    expected_unit: str | None = None,
) -> _Box | None:
    if not isinstance(value, Mapping):
        return None
    if expected_unit is not None and value.get("unit") != expected_unit:
        return None
    try:
        result = _Box(
            x=float(value["x"]),
            y=float(value["y"]),
            width=float(value.get("width", value.get("w"))),
            height=float(value.get("height", value.get("h"))),
        )
    except (KeyError, TypeError, ValueError):
        return None
    if (
        not all(
            math.isfinite(number)
            for number in (
                result.x,
                result.y,
                result.width,
                result.height,
            )
        )
        or result.width <= 0
        or result.height <= 0
    ):
        return None
    return result


def _union_box(boxes: Sequence[_Box]) -> _Box:
    left = min(box.x for box in boxes)
    top = min(box.y for box in boxes)
    right = max(box.right for box in boxes)
    bottom = max(box.bottom for box in boxes)
    return _Box(left, top, right - left, bottom - top)


def _fully_inside(inner: _Box, outer: _Box) -> bool:
    return (
        inner.x >= outer.x - _GEOMETRY_EPSILON
        and inner.y >= outer.y - _GEOMETRY_EPSILON
        and inner.right <= outer.right + _GEOMETRY_EPSILON
        and inner.bottom <= outer.bottom + _GEOMETRY_EPSILON
    )


def _intersection_area(first: _Box, second: _Box) -> float:
    return max(
        min(first.right, second.right) - max(first.x, second.x),
        0.0,
    ) * max(
        min(first.bottom, second.bottom) - max(first.y, second.y),
        0.0,
    )


def _same_box(first: _Box, second: _Box) -> bool:
    return all(
        abs(first_value - second_value) <= 0.001
        for first_value, second_value in zip(
            (
                first.x,
                first.y,
                first.width,
                first.height,
            ),
            (
                second.x,
                second.y,
                second.width,
                second.height,
            ),
            strict=True,
        )
    )


def _horizontal_overlap(first: _Box, second: _Box) -> float:
    overlap = max(
        min(first.right, second.right) - max(first.x, second.x),
        0.0,
    )
    return overlap / max(min(first.width, second.width), 1e-9)


def _page_box(
    ir: DocumentIR,
    page_id: str,
    bboxes: Mapping[str, IRBoundingBox],
    coordinates: Mapping[str, Any],
) -> tuple[_Box, str]:
    page = next(page for page in ir.pages if page.id == page_id)
    page_coordinate = coordinates.get(page.coordinate_system_id)
    if (
        page_coordinate is None
        or page_coordinate.page_id != page_id
    ):
        raise _PageFailure(
            "relationship_order_geometry_ambiguous",
            {"invalid_page_coordinate_count": 1},
        )
    region_ids = {
        region.id: region
        for region in ir.regions
        if region.page_id == page_id
    }
    candidates = [
        bboxes[region.bbox_id]
        for region in region_ids.values()
        if region.bbox_id in bboxes
        and bboxes[region.bbox_id].role == "page"
    ]
    if len(candidates) != 1:
        raise _PageFailure(
            "relationship_order_geometry_ambiguous",
            {"invalid_page_box_count": len(candidates)},
        )
    candidate = candidates[0]
    result = _page_space_ir_box(
        candidate,
        coordinates,
        page_id=page_id,
    )
    if result is None:
        raise _PageFailure(
            "relationship_order_geometry_ambiguous",
            {"invalid_page_box_count": 1},
        )
    return result, str(page_coordinate.unit)


def _page_space_ir_box(
    bbox: IRBoundingBox,
    coordinates: Mapping[str, Any],
    *,
    page_id: str,
) -> _Box | None:
    coordinate = coordinates.get(bbox.coordinate_system_id)
    if (
        coordinate is None
        or coordinate.page_id != page_id
        or coordinate.transform_to_page is None
    ):
        return None
    a, b, c, d, e, f = coordinate.transform_to_page
    corners = (
        (bbox.x, bbox.y),
        (bbox.x + bbox.width, bbox.y),
        (bbox.x, bbox.y + bbox.height),
        (bbox.x + bbox.width, bbox.y + bbox.height),
    )
    transformed = [
        (a * x + c * y + e, b * x + d * y + f)
        for x, y in corners
    ]
    result = _Box(
        min(point[0] for point in transformed),
        min(point[1] for point in transformed),
        max(point[0] for point in transformed)
        - min(point[0] for point in transformed),
        max(point[1] for point in transformed)
        - min(point[1] for point in transformed),
    )
    if (
        result.width <= 0
        or result.height <= 0
        or not all(
            math.isfinite(number)
            for number in (
                result.x,
                result.y,
                result.width,
                result.height,
            )
        )
    ):
        return None
    return result


def _element_page_box(
    element: ElementRecord,
    legacy_bbox: Any,
    *,
    page_id: str,
    page_unit: str,
    bboxes: Mapping[str, IRBoundingBox],
    coordinates: Mapping[str, Any],
) -> _Box | None:
    candidates: list[_Box] = []
    for bbox_id in element.bbox_ids:
        bbox = bboxes.get(bbox_id)
        if bbox is None:
            continue
        coordinate = coordinates.get(bbox.coordinate_system_id)
        if coordinate is None or coordinate.page_id != page_id:
            continue
        transformed = _page_space_ir_box(
            bbox,
            coordinates,
            page_id=page_id,
        )
        if transformed is None:
            continue
        raw_ir_box = _Box(
            bbox.x,
            bbox.y,
            bbox.width,
            bbox.height,
        )
        raw_legacy_box = _box(
            legacy_bbox,
            expected_unit=str(coordinate.unit),
        )
        page_legacy_box = _box(
            legacy_bbox,
            expected_unit=page_unit,
        )
        if (
            raw_legacy_box is not None
            and _same_box(raw_legacy_box, raw_ir_box)
        ) or (
            page_legacy_box is not None
            and _same_box(page_legacy_box, transformed)
        ):
            if not any(
                _same_box(existing, transformed)
                for existing in candidates
            ):
                candidates.append(transformed)
    if len(candidates) != 1:
        return None
    return candidates[0]


def _bounded_jsonish_bytes(value: Any) -> int:
    stack: list[tuple[Any, bool]] = [(value, False)]
    active_containers: set[int] = set()
    count = 0
    nodes = 0
    while stack:
        current, exiting = stack.pop()
        if exiting:
            active_containers.remove(id(current))
            continue
        nodes += 1
        if nodes > _MAX_PRESENTATION_NODES_PER_PAGE:
            return _MAX_PRESENTATION_BYTES_PER_PAGE + 1
        if current is None or isinstance(current, (bool, int, float)):
            count += 32
        elif isinstance(current, str):
            count += 2
            for offset in range(0, len(current), 4096):
                try:
                    count += len(
                        current[offset : offset + 4096].encode("utf-8")
                    )
                except UnicodeEncodeError:
                    return _MAX_PRESENTATION_BYTES_PER_PAGE + 1
                if count > _MAX_PRESENTATION_BYTES_PER_PAGE:
                    return count
        elif isinstance(current, Mapping):
            identity = id(current)
            if identity in active_containers:
                return _MAX_PRESENTATION_BYTES_PER_PAGE + 1
            active_containers.add(identity)
            count += 2
            if len(current) > _MAX_PRESENTATION_NODES_PER_PAGE:
                return _MAX_PRESENTATION_BYTES_PER_PAGE + 1
            stack.append((current, True))
            for key, item in current.items():
                if not isinstance(key, str):
                    return _MAX_PRESENTATION_BYTES_PER_PAGE + 1
                stack.extend(((key, False), (item, False)))
        elif isinstance(current, Sequence) and not isinstance(
            current,
            (str, bytes, bytearray),
        ):
            identity = id(current)
            if identity in active_containers:
                return _MAX_PRESENTATION_BYTES_PER_PAGE + 1
            active_containers.add(identity)
            count += 2
            if len(current) > _MAX_PRESENTATION_NODES_PER_PAGE:
                return _MAX_PRESENTATION_BYTES_PER_PAGE + 1
            stack.append((current, True))
            stack.extend((item, False) for item in current)
        else:
            return _MAX_PRESENTATION_BYTES_PER_PAGE + 1
        if count > _MAX_PRESENTATION_BYTES_PER_PAGE:
            return count
    return count


def _bounded_page_presentation_bytes(
    legacy_items: Sequence[Mapping[str, Any]],
) -> int:
    return _bounded_jsonish_bytes(legacy_items)


def _bounded_text_bytes(value: str, *, remaining: int) -> int:
    count = 0
    for offset in range(0, len(value), 4096):
        try:
            count += len(value[offset : offset + 4096].encode("utf-8"))
        except UnicodeEncodeError:
            return remaining + 1
        if count > remaining:
            return count
    return count


def _interval_components(
    blocks: Sequence[_Block],
    *,
    axis: str,
) -> list[list[_Block]]:
    start = (lambda block: block.box.y) if axis == "y" else (
        lambda block: block.box.x
    )
    end = (lambda block: block.box.bottom) if axis == "y" else (
        lambda block: block.box.right
    )
    ordered = sorted(
        blocks,
        key=lambda block: (
            start(block),
            block.predecessor_rank,
            block.key,
        ),
    )
    components: list[list[_Block]] = []
    current: list[_Block] = []
    current_end = -math.inf
    for block in ordered:
        if current and start(block) > current_end + _GEOMETRY_EPSILON:
            components.append(current)
            current = []
            current_end = -math.inf
        current.append(block)
        current_end = max(current_end, end(block))
    if current:
        components.append(current)
    return components


def _xy_order(
    blocks: Sequence[_Block],
    *,
    depth: int = 0,
) -> list[_Block]:
    if len(blocks) <= 1:
        return list(blocks)
    if depth > _MAX_ANCHORS_PER_PAGE:
        return sorted(
            blocks,
            key=lambda block: (block.predecessor_rank, block.key),
        )
    horizontal = _interval_components(blocks, axis="y")
    if len(horizontal) > 1:
        return [
            block
            for component in horizontal
            for block in _xy_order(component, depth=depth + 1)
        ]
    vertical = _interval_components(blocks, axis="x")
    if len(vertical) > 1:
        return [
            block
            for component in vertical
            for block in _xy_order(component, depth=depth + 1)
        ]
    return sorted(
        blocks,
        key=lambda block: (block.predecessor_rank, block.key),
    )


def _trusted_source(value: Any) -> bool:
    return isinstance(value, str) and value.casefold() in _TRUSTED_SOURCES


def _reviewed_clean_energy_header(
    element: ElementRecord,
    legacy: Mapping[str, Any],
    owner_box: _Box,
    values: Sequence[str],
    child_boxes: Sequence[_Box],
) -> bool:
    public_id = legacy.get("id")
    observed = {
        value: child_box
        for value, child_box in zip(values, child_boxes, strict=True)
    }
    return (
        public_id == _CLEAN_ENERGY_HEADER_ID
        and element.type.casefold() == "header"
        and _same_box(owner_box, _CLEAN_ENERGY_OWNER_BOX)
        and set(observed) == set(_CLEAN_ENERGY_CHILD_BOXES)
        and len(observed) == len(values) == 2
        and all(
            _same_box(observed[value], expected_box)
            for value, expected_box in _CLEAN_ENERGY_CHILD_BOXES.items()
        )
    )


def _nested_content_update(
    element: ElementRecord,
    legacy: Mapping[str, Any],
    *,
    page_id: str,
    page_unit: str,
    bboxes: Mapping[str, IRBoundingBox],
    coordinates: Mapping[str, Any],
    direct_children: Sequence[ElementRecord],
) -> Mapping[str, Any] | None:
    children = legacy.get("items")
    if (
        not isinstance(children, Sequence)
        or isinstance(children, (str, bytes, bytearray))
        or not 1 < len(children) <= _MAX_REFERENCES_PER_ANCHOR
        or not isinstance(legacy.get("value"), str)
        or not isinstance(legacy.get("md"), str)
    ):
        return None
    copied_children: list[dict[str, Any]] = []
    values: list[str] = []
    markdown_values: list[str] = []
    for child in children:
        if not isinstance(child, Mapping):
            return None
        child_value = child.get("value")
        child_markdown = child.get("md", child_value)
        if (
            not isinstance(child_value, str)
            or not child_value.strip()
            or not isinstance(child_markdown, str)
            or not _trusted_source(child.get("source"))
        ):
            return None
        copied_children.append(deepcopy(dict(child)))
        values.append(child_value)
        markdown_values.append(child_markdown)
    if legacy["value"] != "\n".join(values):
        return None
    if legacy["md"] not in {
        "\n".join(markdown_values),
        "\n\n".join(markdown_values),
    }:
        return None
    if len(direct_children) != len(children):
        raise _PageFailure(
            "relationship_order_bbox_ownership",
            {"nested_element_mismatch_count": 1},
        )
    owner_box = _element_page_box(
        element,
        legacy.get("bbox"),
        page_id=page_id,
        page_unit=page_unit,
        bboxes=bboxes,
        coordinates=coordinates,
    )
    if owner_box is None:
        raise _PageFailure(
            "relationship_order_bbox_ownership",
            {"invalid_owner_geometry_count": 1},
        )
    child_boxes: list[_Box] = []
    for child, child_element in zip(
        children,
        direct_children,
        strict=True,
    ):
        child_box = _element_page_box(
            child_element,
            child.get("bbox"),
            page_id=page_id,
            page_unit=page_unit,
            bboxes=bboxes,
            coordinates=coordinates,
        )
        if child_box is None:
            raise _PageFailure(
                "relationship_order_bbox_ownership",
                {"invalid_child_geometry_count": 1},
            )
        child_boxes.append(child_box)

    inside_indexes: list[int] = []
    outside_indexes: list[int] = []
    for index, child_box in enumerate(child_boxes):
        if _fully_inside(child_box, owner_box):
            inside_indexes.append(index)
        elif _intersection_area(child_box, owner_box) == 0:
            outside_indexes.append(index)
        else:
            raise _PageFailure(
                "relationship_order_bbox_ownership",
                {"partial_overlap_count": 1},
            )
    if not inside_indexes:
        return None

    # Nested content with geometry outside its declared owner remains public
    # and attributable. Splitting it requires the earlier source-proven raw
    # normalization contract; layout ordering must never delete it.
    if outside_indexes:
        return None
    if not _reviewed_clean_energy_header(
        element,
        legacy,
        owner_box,
        values,
        child_boxes,
    ):
        return None
    child_blocks = [
        _Block(
            member_ids=(str(index),),
            predecessor_rank=index,
            box=child_boxes[index],
        )
        for index in inside_indexes
    ]
    retained_indexes = [
        int(block.key)
        for block in _xy_order(child_blocks)
    ]
    if retained_indexes == list(range(len(children))):
        return None

    retained_children = [
        copied_children[index] for index in retained_indexes
    ]
    retained_values = [values[index] for index in retained_indexes]
    retained_markdown = [
        markdown_values[index] for index in retained_indexes
    ]
    markdown_separator = "\n\n" if "\n\n" in legacy["md"] else "\n"
    updated_legacy = deepcopy(dict(legacy))
    updated_legacy["items"] = retained_children
    updated_legacy["value"] = "\n".join(retained_values)
    updated_legacy["md"] = markdown_separator.join(retained_markdown)
    return {
        "value": updated_legacy["value"],
        "markdown": updated_legacy["md"],
        "legacy_item": updated_legacy,
        "retained_indexes": retained_indexes,
    }


def _content_updates(
    page_element_ids: Sequence[str],
    elements: Mapping[str, ElementRecord],
    *,
    page_id: str,
    page_unit: str,
    evidence_by_id: Mapping[str, Any],
    bboxes: Mapping[str, IRBoundingBox],
    coordinates: Mapping[str, Any],
    children_by_parent: Mapping[str, Sequence[ElementRecord]],
) -> dict[str, Mapping[str, Any]]:
    overflowing_reference_count = max(
        (
            len(elements[element_id].evidence_ids)
            for element_id in page_element_ids
        ),
        default=0,
    )
    if overflowing_reference_count > _MAX_REFERENCES_PER_ANCHOR:
        raise _PageFailure(
            "relationship_order_edge_limit",
            {
                "reference_count": overflowing_reference_count,
                "limit": _MAX_REFERENCES_PER_ANCHOR,
            },
        )
    evidence_ids = {
        evidence_id
        for element_id in page_element_ids
        for evidence_id in elements[element_id].evidence_ids
    }
    if len(evidence_ids) > (
        len(page_element_ids) * _MAX_REFERENCES_PER_ANCHOR
    ):
        raise _PageFailure(
            "relationship_order_edge_limit",
            {
                "reference_count": len(evidence_ids),
                "limit": (
                    len(page_element_ids)
                    * _MAX_REFERENCES_PER_ANCHOR
                ),
            },
        )
    evidence_bytes = 0
    for evidence_id in evidence_ids:
        record = evidence_by_id.get(evidence_id)
        if record is None or not isinstance(record.value, str):
            continue
        evidence_bytes += _bounded_text_bytes(
            record.value,
            remaining=_MAX_EVIDENCE_BYTES_PER_PAGE - evidence_bytes,
        )
        if evidence_bytes > _MAX_EVIDENCE_BYTES_PER_PAGE:
            raise _PageFailure(
                "relationship_order_page_limit",
                {
                    "evidence_bytes_at_least": evidence_bytes,
                    "limit": _MAX_EVIDENCE_BYTES_PER_PAGE,
                },
            )

    updates: dict[str, Mapping[str, Any]] = {}
    for element_id in page_element_ids:
        element = elements[element_id]
        legacy = _legacy_item(element)
        direct_children = sorted(
            children_by_parent.get(element_id, ()),
            key=lambda child: (
                int(
                    child.properties.get(
                        "child_index",
                        child.properties.get("index", 0),
                    )
                    or 0
                ),
                child.id,
            ),
        )
        nested = _nested_content_update(
            element,
            legacy,
            page_id=page_id,
            page_unit=page_unit,
            bboxes=bboxes,
            coordinates=coordinates,
            direct_children=direct_children,
        )
        if nested is not None:
            nested_update = dict(nested)
            retained_indexes = nested_update.pop("retained_indexes")
            if (
                len(direct_children) == len(
                    legacy.get("items", ())
                )
                and len(retained_indexes) == len(set(retained_indexes))
                and set(retained_indexes) <= set(
                    range(len(direct_children))
                )
            ):
                nested_update["nested_element_ids"] = [
                    direct_children[index].id
                    for index in retained_indexes
                ]
                retained_set = set(retained_indexes)
                nested_update["excluded_nested_element_ids"] = [
                    child.id
                    for index, child in enumerate(direct_children)
                    if index not in retained_set
                ]
            updates[element_id] = nested_update
            continue
    return updates


def _relationship_is_trusted(
    relationship: RelationshipRecord,
    elements: Mapping[str, ElementRecord],
    evidence_methods: Mapping[str, EvidenceMethod],
) -> bool:
    if relationship.evidence_ids and all(
        evidence_methods.get(evidence_id) in _TRUSTED_METHODS
        for evidence_id in relationship.evidence_ids
    ):
        return True
    source = elements[relationship.source_id]
    metadata_story = relationship.metadata.get("story")
    if (
        metadata_story not in {"P03-US01", "P03-US02", "P03-US03"}
        or relationship.metadata.get("layout_projection_managed") is not True
    ):
        return False
    marker_contracts = {
        "P03-US01": (
            "layout_projection",
            frozenset({RelationshipType.CAPTION_OF}),
        ),
        "P03-US02": (
            "layout_projection",
            frozenset({RelationshipType.CAPTION_OF}),
        ),
        "P03-US03": (
            "source_note_projection",
            frozenset(
                {
                    RelationshipType.SOURCE_NOTE_OF,
                    RelationshipType.FOOTNOTE_OF,
                }
            ),
        ),
    }
    property_name, allowed_types = marker_contracts[metadata_story]
    projection = source.properties.get(property_name)
    return (
        relationship.type in allowed_types
        and isinstance(projection, Mapping)
        and projection.get("story") == metadata_story
        and projection.get("relationship_id") == relationship.id
    )


def _caption_side(
    caption: ElementRecord,
    owner: ElementRecord,
    boxes: Mapping[str, _Box],
) -> str | None:
    projection = caption.properties.get("layout_projection")
    if isinstance(projection, Mapping):
        placement = projection.get("placement")
        if placement in {"before", "after"}:
            return str(placement)
    caption_box = boxes[caption.id]
    owner_box = boxes[owner.id]
    if caption_box.bottom <= owner_box.y + _GEOMETRY_EPSILON:
        return "before"
    if caption_box.y >= owner_box.bottom - _GEOMETRY_EPSILON:
        return "after"
    return None


def _eligible_prefixes(
    page_ids: Sequence[str],
    elements: Mapping[str, ElementRecord],
    boxes: Mapping[str, _Box],
) -> tuple[dict[str, list[str]], int]:
    predecessor_rank = {
        element_id: rank for rank, element_id in enumerate(page_ids)
    }
    candidates: list[str] = []
    table_ids = [
        element_id
        for element_id in page_ids
        if str(_legacy_item(elements[element_id]).get("type") or "").casefold()
        == "table"
    ]
    for element_id in page_ids:
        legacy = _legacy_item(elements[element_id])
        concerns = legacy.get("parse_concerns") or []
        marked = (
            legacy.get("layout_omission_recovered_by_ocr") is True
            or (
                isinstance(concerns, Sequence)
                and not isinstance(concerns, (str, bytes, bytearray))
                and "layout_omission_recovered_by_ocr" in concerns
            )
        )
        confidence = legacy.get("confidence")
        if (
            marked
            and isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
            and float(confidence) >= _MIN_PREFIX_CONFIDENCE
            and _trusted_source(legacy.get("source"))
            and boxes[element_id].y <= _TOP_PREFIX_LIMIT
        ):
            candidates.append(element_id)
    if len(candidates) > _MAX_PREFIX_CANDIDATES:
        raise _PageFailure(
            "relationship_order_page_limit",
            {
                "prefix_candidate_count": len(candidates),
                "limit": _MAX_PREFIX_CANDIDATES,
            },
        )

    table_content: dict[str, str] = {}
    for table_id in table_ids:
        table_legacy = _legacy_item(elements[table_id])
        try:
            table_content[table_id] = json.dumps(
                (
                    table_legacy.get("value"),
                    table_legacy.get("md"),
                ),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except (TypeError, ValueError, UnicodeEncodeError) as exc:
            raise _PageFailure(
                "relationship_order_geometry_ambiguous",
                {"invalid_table_content_count": 1},
            ) from exc

    comparisons = 0
    owners: dict[str, list[str]] = defaultdict(list)
    for candidate_id in candidates:
        candidate = elements[candidate_id]
        candidate_box = boxes[candidate_id]
        plausible: list[str] = []
        raw_candidate_value = _legacy_item(candidate).get("value")
        candidate_value = (
            raw_candidate_value
            if isinstance(raw_candidate_value, str)
            else ""
        )
        for table_id in table_ids:
            comparisons += 1
            if comparisons > _MAX_PREFIX_COMPARISONS:
                raise _PageFailure(
                    "relationship_order_edge_limit",
                    {
                        "comparison_count": comparisons,
                        "limit": _MAX_PREFIX_COMPARISONS,
                    },
                )
            table_box = boxes[table_id]
            if (
                candidate_box.y
                <= min(table_box.y + _TOP_PREFIX_LIMIT, _TOP_PREFIX_LIMIT)
                and _intersection_area(candidate_box, table_box) > 0
                and candidate_value
                not in table_content[table_id]
            ):
                plausible.append(table_id)
        if len(plausible) == 1:
            owners[plausible[0]].append(candidate_id)
    for owner_id, prefix_ids in owners.items():
        prefix_ids.sort(
            key=lambda element_id: (
                boxes[element_id].y,
                boxes[element_id].x,
                predecessor_rank[element_id],
                element_id,
            )
        )
    return dict(owners), comparisons


def _internal_topological_order(
    member_ids: Sequence[str],
    edges: set[tuple[str, str]],
    predecessor_rank: Mapping[str, int],
) -> tuple[str, ...]:
    indegree = {identifier: 0 for identifier in member_ids}
    outgoing: dict[str, set[str]] = defaultdict(set)
    for source_id, target_id in edges:
        if target_id not in outgoing[source_id]:
            outgoing[source_id].add(target_id)
            indegree[target_id] += 1
    heap = [
        (predecessor_rank[identifier], identifier)
        for identifier, degree in indegree.items()
        if degree == 0
    ]
    heapq.heapify(heap)
    ordered: list[str] = []
    while heap:
        _rank, identifier = heapq.heappop(heap)
        ordered.append(identifier)
        for target_id in sorted(outgoing.get(identifier, ())):
            indegree[target_id] -= 1
            if indegree[target_id] == 0:
                heapq.heappush(
                    heap,
                    (predecessor_rank[target_id], target_id),
                )
    if len(ordered) != len(member_ids):
        raise _PageFailure("relationship_order_cycle", {"cycle_count": 1})
    return tuple(ordered)


def _blocks(
    page_ids: Sequence[str],
    elements: Mapping[str, ElementRecord],
    boxes: Mapping[str, _Box],
    relationships: Sequence[RelationshipRecord],
    evidence_methods: Mapping[str, EvidenceMethod],
) -> tuple[
    list[_Block],
    dict[str, str],
    dict[str, int],
]:
    predecessor_rank = {
        element_id: rank for rank, element_id in enumerate(page_ids)
    }
    presented = set(page_ids)
    disjoint = _DisjointSet(page_ids)
    before_by_owner: dict[str, list[str]] = defaultdict(list)
    after_by_owner: dict[str, list[str]] = defaultdict(list)
    notes_by_owner: dict[str, list[str]] = defaultdict(list)
    owner_by_child: dict[str, str] = {}

    for relationship in relationships:
        if (
            relationship.source_id not in presented
            or relationship.target_id not in presented
            or relationship.type
            not in {
                RelationshipType.CAPTION_OF,
                RelationshipType.SOURCE_NOTE_OF,
                RelationshipType.FOOTNOTE_OF,
            }
            or not _relationship_is_trusted(
                relationship,
                elements,
                evidence_methods,
            )
        ):
            continue
        source_id = relationship.source_id
        owner_id = relationship.target_id
        prior_owner = owner_by_child.setdefault(source_id, owner_id)
        if prior_owner != owner_id:
            raise _PageFailure(
                "relationship_order_bbox_ownership",
                {"ambiguous_owner_count": 2},
            )
        if len(
            before_by_owner[owner_id]
            + after_by_owner[owner_id]
            + notes_by_owner[owner_id]
        ) >= _MAX_REFERENCES_PER_ANCHOR:
            raise _PageFailure(
                "relationship_order_edge_limit",
                {
                    "reference_count": _MAX_REFERENCES_PER_ANCHOR + 1,
                    "limit": _MAX_REFERENCES_PER_ANCHOR,
                },
            )
        if relationship.type is RelationshipType.CAPTION_OF:
            side = _caption_side(
                elements[source_id],
                elements[owner_id],
                boxes,
            )
            if side is None:
                raise _PageFailure(
                    "relationship_order_bbox_ownership",
                    {"ambiguous_caption_count": 1},
                )
            target = (
                before_by_owner if side == "before" else after_by_owner
            )
            target[owner_id].append(source_id)
        else:
            notes_by_owner[owner_id].append(source_id)
        disjoint.union(owner_id, source_id)

    prefixes_by_owner, comparison_count = _eligible_prefixes(
        page_ids,
        elements,
        boxes,
    )
    for owner_id, prefix_ids in prefixes_by_owner.items():
        for prefix_id in prefix_ids:
            prior_owner = owner_by_child.setdefault(prefix_id, owner_id)
            if prior_owner != owner_id:
                raise _PageFailure(
                    "relationship_order_bbox_ownership",
                    {"ambiguous_owner_count": 2},
                )
            disjoint.union(owner_id, prefix_id)

    internal_edges: set[tuple[str, str]] = set()
    for owner_id in set(
        before_by_owner
        | after_by_owner
        | notes_by_owner
        | prefixes_by_owner
    ):
        prefixes = prefixes_by_owner.get(owner_id, [])
        before = sorted(
            set(before_by_owner.get(owner_id, [])),
            key=lambda element_id: (
                predecessor_rank[element_id],
                element_id,
            ),
        )
        after = sorted(
            set(after_by_owner.get(owner_id, [])),
            key=lambda element_id: (
                predecessor_rank[element_id],
                element_id,
            ),
        )
        notes = sorted(
            set(notes_by_owner.get(owner_id, [])),
            key=lambda element_id: (
                predecessor_rank[element_id],
                element_id,
            ),
        )
        sequence = [*prefixes, *before, owner_id, *after, *notes]
        internal_edges.update(zip(sequence, sequence[1:]))

    groups: dict[str, list[str]] = defaultdict(list)
    for element_id in page_ids:
        groups[disjoint.find(element_id)].append(element_id)
    blocks: list[_Block] = []
    block_by_element: dict[str, str] = {}
    internal_position: dict[str, int] = {}
    for member_ids in groups.values():
        member_set = set(member_ids)
        member_edges = {
            edge
            for edge in internal_edges
            if edge[0] in member_set and edge[1] in member_set
        }
        ordered_members = _internal_topological_order(
            member_ids,
            member_edges,
            predecessor_rank,
        )
        block = _Block(
            member_ids=ordered_members,
            predecessor_rank=min(
                predecessor_rank[element_id]
                for element_id in member_ids
            ),
            box=_union_box([boxes[element_id] for element_id in member_ids]),
        )
        blocks.append(block)
        for position, element_id in enumerate(ordered_members):
            block_by_element[element_id] = block.key
            internal_position[element_id] = position
    return blocks, block_by_element, internal_position | {
        "__prefix_comparisons__": comparison_count
    }


def _block_types(
    block: _Block,
    elements: Mapping[str, ElementRecord],
) -> set[str]:
    return {
        str(_legacy_item(elements[element_id]).get("type") or "").casefold()
        for element_id in block.member_ids
    }


def _preamble_sidebar_edges(
    blocks: Sequence[_Block],
    elements: Mapping[str, ElementRecord],
    page_box: _Box,
) -> set[tuple[str, str]]:
    """Order one structurally unambiguous cover-page sidebar after preamble.

    This recognizes a broad, heading-led primary column plus one narrower
    non-overlapping side column. It requires a later heading in the primary
    column as the body barrier. Two-sided, multi-lead, or otherwise ambiguous
    layouts add no edges and retain the existing deterministic order.
    """

    if not 3 <= len(blocks) <= _MAX_ANCHORS_PER_PAGE:
        return set()
    eligible = [
        block
        for block in blocks
        if not _block_types(block, elements) & {"header", "footer"}
    ]
    lead_candidates = [
        block
        for block in eligible
        if "heading" in _block_types(block, elements)
        and block.box.width >= page_box.width * 0.45
        and block.box.y <= page_box.y + page_box.height * 0.35
    ]
    if len(lead_candidates) != 1:
        return set()
    lead = lead_candidates[0]

    body_heading_candidates = [
        block
        for block in eligible
        if block is not lead
        and "heading" in _block_types(block, elements)
        and _horizontal_overlap(block.box, lead.box) >= 0.70
        and block.box.y
        >= lead.box.bottom + max(12.0, page_box.height * 0.06)
    ]
    if not body_heading_candidates:
        return set()
    body_heading = min(
        body_heading_candidates,
        key=lambda block: (
            block.box.y,
            block.box.x,
            block.predecessor_rank,
            block.key,
        ),
    )

    preamble = [
        block
        for block in eligible
        if block is not body_heading
        and _horizontal_overlap(block.box, lead.box) >= 0.70
        and block.box.y
        >= lead.box.y - max(lead.box.height, page_box.height * 0.04)
        and block.box.bottom
        <= body_heading.box.y + _GEOMETRY_EPSILON
    ]
    if lead not in preamble or len(preamble) < 2:
        return set()
    preamble_order = _xy_order(preamble)
    preamble_tail = preamble_order[-1]
    if preamble_tail is body_heading:
        return set()

    left = [
        block
        for block in eligible
        if block.box.right <= lead.box.x - _GEOMETRY_EPSILON
        and block.box.y >= lead.box.y - _GEOMETRY_EPSILON
        and block.box.width <= lead.box.width * 0.70
    ]
    right = [
        block
        for block in eligible
        if block.box.x >= lead.box.right + _GEOMETRY_EPSILON
        and block.box.y >= lead.box.y - _GEOMETRY_EPSILON
        and block.box.width <= lead.box.width * 0.70
    ]
    # A page with independently populated columns on both sides of the lead
    # has no unique sidebar owner.
    if bool(left) == bool(right):
        return set()
    sidebar = left or right
    if len(sidebar) < 2:
        return set()
    if len(_interval_components(sidebar, axis="x")) != 1:
        return set()
    sidebar_union = _union_box([block.box for block in sidebar])
    if sidebar_union.width > lead.box.width * 0.75:
        return set()
    vertical_sidebar = sorted(
        sidebar,
        key=lambda block: (
            block.box.y,
            block.box.x,
            block.predecessor_rank,
            block.key,
        ),
    )
    connected_bottom = vertical_sidebar[0].box.bottom
    maximum_vertical_gap = max(48.0, page_box.height * 0.08)
    for block in vertical_sidebar[1:]:
        if block.box.y > connected_bottom + maximum_vertical_gap:
            return set()
        connected_bottom = max(connected_bottom, block.box.bottom)
    sidebar_order = _xy_order(sidebar)
    if sidebar_order[0].box.y >= body_heading.box.y:
        return set()

    edges = set(zip(
        (block.key for block in sidebar_order),
        (block.key for block in sidebar_order[1:]),
    ))
    edges.add((preamble_tail.key, sidebar_order[0].key))
    edges.add((sidebar_order[-1].key, body_heading.key))
    return edges


def _column_continuity_edges(
    base_order: Sequence[_Block],
) -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    for index, block in enumerate(base_order):
        candidate: _Block | None = None
        for prior in reversed(
            base_order[max(0, index - _MAX_REFERENCES_PER_ANCHOR) : index]
        ):
            if (
                prior.box.bottom
                <= block.box.y + _GEOMETRY_EPSILON
                and _horizontal_overlap(prior.box, block.box)
                >= _MIN_HORIZONTAL_OVERLAP
                and (
                    candidate is None
                    or prior.box.bottom > candidate.box.bottom
                )
            ):
                candidate = prior
        if candidate is not None:
            edges.add((candidate.key, block.key))
    return edges


def _column_barrier_edges(
    blocks: Sequence[_Block],
    elements: Mapping[str, ElementRecord],
    page_box: _Box,
) -> set[tuple[str, str]]:
    headings = [
        block
        for block in blocks
        if "heading" in _block_types(block, elements)
        and block.box.y >= page_box.height * 0.30
    ]
    if len(headings) > _MAX_REFERENCES_PER_ANCHOR:
        raise _PageFailure(
            "relationship_order_edge_limit",
            {
                "heading_count": len(headings),
                "limit": _MAX_REFERENCES_PER_ANCHOR,
            },
        )
    edges: set[tuple[str, str]] = set()
    for heading in headings:
        same_column = [
            block
            for block in blocks
            if block is heading
            or (
                block.box.y >= heading.box.y
                and _horizontal_overlap(block.box, heading.box)
                >= _MIN_HORIZONTAL_OVERLAP
                and "footer" not in _block_types(block, elements)
            )
        ]
        column_bottom = max(block.box.bottom for block in same_column)
        left_candidates = [
            block
            for block in blocks
            if block.predecessor_rank < heading.predecessor_rank
            and block.box.right
            <= heading.box.x - _GEOMETRY_EPSILON
            and block.box.y <= column_bottom + _GEOMETRY_EPSILON
            and "footer" not in _block_types(block, elements)
        ]
        if left_candidates:
            predecessor = max(
                left_candidates,
                key=lambda block: (
                    block.predecessor_rank,
                    block.key,
                ),
            )
            edges.add((predecessor.key, heading.key))
    return edges


def _stable_block_topology(
    blocks: Sequence[_Block],
    edges: set[tuple[str, str]],
    base_rank: Mapping[str, int],
) -> list[_Block]:
    by_key = {block.key: block for block in blocks}
    indegree = {block.key: 0 for block in blocks}
    outgoing: dict[str, set[str]] = defaultdict(set)
    for source_id, target_id in edges:
        if source_id == target_id:
            continue
        if target_id not in outgoing[source_id]:
            outgoing[source_id].add(target_id)
            indegree[target_id] += 1
    heap = [
        (base_rank[key], by_key[key].predecessor_rank, key)
        for key, degree in indegree.items()
        if degree == 0
    ]
    heapq.heapify(heap)
    ordered: list[_Block] = []
    while heap:
        _base, _predecessor, key = heapq.heappop(heap)
        ordered.append(by_key[key])
        for target_id in sorted(outgoing.get(key, ())):
            indegree[target_id] -= 1
            if indegree[target_id] == 0:
                heapq.heappush(
                    heap,
                    (
                        base_rank[target_id],
                        by_key[target_id].predecessor_rank,
                        target_id,
                    ),
                )
    if len(ordered) != len(blocks):
        raise _PageFailure("relationship_order_cycle", {"cycle_count": 1})
    return ordered


def _plan_page(
    ir: DocumentIR,
    page_id: str,
    *,
    elements: Mapping[str, ElementRecord],
    bboxes: Mapping[str, IRBoundingBox],
    coordinates: Mapping[str, Any],
    evidence_by_id: Mapping[str, Any],
    evidence_methods: Mapping[str, EvidenceMethod],
    children_by_parent: Mapping[str, Sequence[ElementRecord]],
    page_relationships: Sequence[RelationshipRecord],
) -> _PagePlan:
    page = next(page for page in ir.pages if page.id == page_id)
    page_ids = tuple(page.presentation_element_ids)
    if len(page_ids) != len(set(page_ids)):
        raise _PageFailure(
            "relationship_order_duplicate_anchor",
            {"duplicate_anchor_count": len(page_ids) - len(set(page_ids))},
        )
    if len(page_ids) > _MAX_ANCHORS_PER_PAGE:
        raise _PageFailure(
            "relationship_order_page_limit",
            {
                "anchor_count": len(page_ids),
                "limit": _MAX_ANCHORS_PER_PAGE,
            },
        )
    missing_element_count = sum(
        element_id not in elements for element_id in page_ids
    )
    if missing_element_count:
        raise _PageFailure(
            "relationship_order_duplicate_anchor",
            {"missing_anchor_count": missing_element_count},
        )
    if len(page_relationships) > _MAX_EDGES_PER_PAGE:
        raise _PageFailure(
            "relationship_order_edge_limit",
            {
                "relationship_count": len(page_relationships),
                "limit": _MAX_EDGES_PER_PAGE,
            },
        )
    legacy_items = [_legacy_item(elements[element_id]) for element_id in page_ids]
    byte_count = _bounded_page_presentation_bytes(legacy_items)
    if byte_count > _MAX_PRESENTATION_BYTES_PER_PAGE:
        raise _PageFailure(
            "relationship_order_page_limit",
            {
                "observed_bytes_at_least": byte_count,
                "limit": _MAX_PRESENTATION_BYTES_PER_PAGE,
            },
        )
    page_bounds, page_unit = _page_box(
        ir,
        page_id,
        bboxes,
        coordinates,
    )
    boxes: dict[str, _Box] = {}
    invalid_count = 0
    for element_id, legacy in zip(page_ids, legacy_items, strict=True):
        element_box = _element_page_box(
            elements[element_id],
            legacy.get("bbox"),
            page_id=page_id,
            page_unit=page_unit,
            bboxes=bboxes,
            coordinates=coordinates,
        )
        if (
            element_box is None
            or not _fully_inside(element_box, page_bounds)
        ):
            invalid_count += 1
            continue
        boxes[element_id] = element_box
    if invalid_count:
        raise _PageFailure(
            "relationship_order_geometry_ambiguous",
            {"invalid_geometry_count": invalid_count},
        )

    updates = _content_updates(
        page_ids,
        elements,
        page_id=page_id,
        page_unit=page_unit,
        evidence_by_id=evidence_by_id,
        bboxes=bboxes,
        coordinates=coordinates,
        children_by_parent=children_by_parent,
    )
    blocks, block_by_element, internal_positions = _blocks(
        page_ids,
        elements,
        boxes,
        page_relationships,
        evidence_methods,
    )
    base_order = _xy_order(blocks)
    base_rank = {
        block.key: rank for rank, block in enumerate(base_order)
    }
    edges = _column_continuity_edges(base_order)
    edges.update(_column_barrier_edges(blocks, elements, page_bounds))
    edges.update(_preamble_sidebar_edges(blocks, elements, page_bounds))

    hard_neighbors: dict[str, set[str]] = defaultdict(set)
    for relationship in page_relationships:
        if (
            relationship.type is not RelationshipType.READING_BEFORE
            or relationship.metadata.get("basis") == "legacy_reading_order"
            or relationship.metadata.get("basis") != "source_grounded"
            or not _relationship_is_trusted(
                relationship,
                elements,
                evidence_methods,
            )
        ):
            continue
        hard_neighbors[relationship.source_id].add(
            relationship.target_id
        )
        hard_neighbors[relationship.target_id].add(
            relationship.source_id
        )
        incident_reference_count = max(
            len(hard_neighbors[relationship.source_id]),
            len(hard_neighbors[relationship.target_id]),
        )
        if incident_reference_count > _MAX_REFERENCES_PER_ANCHOR:
            raise _PageFailure(
                "relationship_order_edge_limit",
                {
                    "reference_count": incident_reference_count,
                    "limit": _MAX_REFERENCES_PER_ANCHOR,
                },
            )
        source_block = block_by_element[relationship.source_id]
        target_block = block_by_element[relationship.target_id]
        if source_block == target_block:
            if (
                internal_positions[relationship.source_id]
                >= internal_positions[relationship.target_id]
            ):
                raise _PageFailure(
                    "relationship_order_cycle",
                    {"cycle_count": 1},
                )
            continue
        edges.add((source_block, target_block))

    if len(edges) > _MAX_EDGES_PER_PAGE:
        raise _PageFailure(
            "relationship_order_edge_limit",
            {
                "edge_count": len(edges),
                "limit": _MAX_EDGES_PER_PAGE,
            },
        )
    ordered_blocks = _stable_block_topology(blocks, edges, base_rank)
    order = tuple(
        element_id
        for block in ordered_blocks
        for element_id in block.member_ids
    )
    if len(order) != len(page_ids) or set(order) != set(page_ids):
        raise _PageFailure(
            "relationship_order_duplicate_anchor",
            {"duplicate_anchor_count": 1},
        )
    return _PagePlan(order, updates, len(edges))


def _emit_concern(
    ir: DocumentIR,
    state: _ConcernState,
    code: str,
    page_id: str,
    metadata: Mapping[str, Any],
) -> None:
    if code not in _DETAIL_CODES:
        code = "relationship_order_projection_failed_closed"
    sanitized_metadata = {
        "page_id": page_id,
        **{
            key: value
            for key, value in metadata.items()
            if isinstance(value, (int, float, bool)) or value is None
        },
    }
    if (
        state.detail_count >= _MAX_CONCERNS_PER_DOCUMENT
        or state.detail_by_page.get(page_id, 0)
        >= _MAX_CONCERNS_PER_PAGE
    ):
        if state.truncation_present:
            return
        code = "relationship_order_concerns_truncated"
        sanitized_metadata = {
            "page_id": page_id,
            "suppressed_count_at_least": 1,
            "page_limit": _MAX_CONCERNS_PER_PAGE,
            "document_limit": _MAX_CONCERNS_PER_DOCUMENT,
        }
    candidate = IRConcern(
        code=code,
        message="Relationship-aware reading order failed closed.",
        metadata=sanitized_metadata,
    )
    identity = candidate.model_dump_json()
    if identity in state.identities:
        return
    ir.concerns.append(candidate)
    state.identities.add(identity)
    if code == "relationship_order_concerns_truncated":
        state.truncation_present = True
    else:
        state.detail_count += 1
        state.detail_by_page[page_id] = (
            state.detail_by_page.get(page_id, 0) + 1
        )


def _concern_state(ir: DocumentIR) -> _ConcernState:
    identities: set[str] = set()
    detail_by_page: dict[str, int] = defaultdict(int)
    detail_count = 0
    truncation_present = False
    for concern in ir.concerns:
        if not concern.code.startswith("relationship_order_"):
            continue
        identities.add(concern.model_dump_json())
        if concern.code == "relationship_order_concerns_truncated":
            truncation_present = True
            continue
        detail_count += 1
        page_id = concern.metadata.get("page_id")
        if isinstance(page_id, str):
            detail_by_page[page_id] += 1
    return _ConcernState(
        identities=identities,
        detail_count=detail_count,
        detail_by_page=dict(detail_by_page),
        truncation_present=truncation_present,
    )


def project_relationship_order(ir: DocumentIR) -> None:
    """Apply the accepted bounded P03-US04 presentation projection."""

    concern_state = _concern_state(ir)
    record_counts = (
        len(ir.elements),
        len(ir.bboxes),
        len(ir.evidence),
        len(ir.coordinate_systems),
        len(ir.regions),
    )
    total_anchor_count = sum(
        len(page.presentation_element_ids) for page in ir.pages
    )
    document_limit_metadata: dict[str, int] | None = None
    if len(ir.relationships) > _MAX_EDGES_PER_DOCUMENT:
        document_limit_metadata = {
            "relationship_count": len(ir.relationships),
            "limit": _MAX_EDGES_PER_DOCUMENT,
        }
    elif total_anchor_count > _MAX_ANCHORS_PER_DOCUMENT:
        document_limit_metadata = {
            "anchor_count": total_anchor_count,
            "limit": _MAX_ANCHORS_PER_DOCUMENT,
        }
    elif max(record_counts, default=0) > _MAX_IR_RECORDS_PER_DOCUMENT:
        document_limit_metadata = {
            "record_count": max(record_counts),
            "limit": _MAX_IR_RECORDS_PER_DOCUMENT,
        }
    if document_limit_metadata is not None:
        if ir.pages:
            _emit_concern(
                ir,
                concern_state,
                "relationship_order_edge_limit",
                ir.pages[0].id,
                document_limit_metadata,
            )
        return

    elements = {element.id: element for element in ir.elements}
    bboxes = {bbox.id: bbox for bbox in ir.bboxes}
    coordinates = {
        coordinate.id: coordinate
        for coordinate in ir.coordinate_systems
    }
    evidence_by_id = {
        evidence.id: evidence for evidence in ir.evidence
    }
    evidence_methods = {
        evidence.id: evidence.method for evidence in ir.evidence
    }
    children_by_parent: dict[str, list[ElementRecord]] = defaultdict(list)
    for element in ir.elements:
        parent_id = element.properties.get("parent_element_id")
        if (
            isinstance(parent_id, str)
            and element.properties.get("collection") == "items"
        ):
            children_by_parent[parent_id].append(element)
    presented_page_by_id = {
        element_id: page.id
        for page in ir.pages
        for element_id in page.presentation_element_ids
    }
    relationships_by_page: dict[
        str,
        list[RelationshipRecord],
    ] = defaultdict(list)
    for relationship in ir.relationships:
        source_page_id = presented_page_by_id.get(
            relationship.source_id
        )
        if (
            source_page_id is not None
            and presented_page_by_id.get(relationship.target_id)
            == source_page_id
        ):
            relationships_by_page[source_page_id].append(relationship)

    total_edges = 0
    for page in ir.pages:
        try:
            plan = _plan_page(
                ir,
                page.id,
                elements=elements,
                bboxes=bboxes,
                coordinates=coordinates,
                evidence_by_id=evidence_by_id,
                evidence_methods=evidence_methods,
                children_by_parent=children_by_parent,
                page_relationships=relationships_by_page.get(page.id, ()),
            )
            if total_edges + plan.edge_count > _MAX_EDGES_PER_DOCUMENT:
                raise _PageFailure(
                    "relationship_order_edge_limit",
                    {
                        "edge_count": total_edges + plan.edge_count,
                        "limit": _MAX_EDGES_PER_DOCUMENT,
                    },
                )
        except _PageFailure as exc:
            _emit_concern(
                ir,
                concern_state,
                exc.code,
                page.id,
                exc.metadata,
            )
            continue

        total_edges += plan.edge_count
        page.presentation_element_ids = list(plan.order)
        for reading_order, element_id in enumerate(plan.order):
            element = elements[element_id]
            update = plan.element_updates.get(element_id)
            if update is not None:
                element.value = deepcopy(update["value"])
                element.markdown = str(update["markdown"])
                element.properties["legacy_item"] = deepcopy(
                    dict(update["legacy_item"])
                )
                nested_element_ids = update.get("nested_element_ids")
                if isinstance(nested_element_ids, list):
                    excluded_nested_element_ids = update.get(
                        "excluded_nested_element_ids",
                    )
                    element.properties[
                        "relationship_order_projection"
                    ] = {
                        "story": "P03-US04",
                        "nested_element_ids": list(nested_element_ids),
                        "excluded_nested_element_ids": (
                            list(excluded_nested_element_ids)
                            if isinstance(
                                excluded_nested_element_ids,
                                list,
                            )
                            else []
                        ),
                    }
            legacy = _legacy_item(element)
            legacy["reading_order"] = reading_order
            element.properties["legacy_item"] = legacy
            element.reading_order = reading_order
