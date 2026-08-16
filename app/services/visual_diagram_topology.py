"""Build conservative, source-grounded topology for simple diagrams."""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Literal

from app.services.visual_contracts import (
    DiagramConnector,
    DiagramNode,
    VisualBoundingBox,
    VisualConcern,
    VisualConfidenceDimensions,
    VisualEvidence,
    VisualFallback,
    VisualLabel,
    VisualProvenance,
    VisualSerialization,
    VisualStructure,
    VisualTransform,
    ensure_finite_mapping,
)

_MAX_NODES = 512
_MAX_CONNECTORS = 1_024
_MAX_PATH_POINTS = 64
_MAX_REFERENCES = 64
_MAX_PDF_LINES = 1_024
_MAX_ARROW_WING_CANDIDATES = 16
_NODE_SHAPES = frozenset(
    {"rectangle", "rounded_rectangle", "ellipse", "diamond"}
)
_RASTER_LABEL_CODEPOINTS = 1_024
_RASTER_LABEL_BYTES = 4_096
_PDF_ANALYSIS_PIXELS_PER_POINT = 3.0
_MAX_ANALYSIS_EDGE = 4_096
_MAX_ANALYSIS_PIXELS = 8_388_608
_RASTER_SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_UNSAFE_DIRECTIONAL_CHARACTERS = frozenset(
    "\u2028\u2029\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
)


def _stable_id(prefix: str, *parts: Any) -> str:
    encoded = json.dumps(
        parts,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _text(value: Any, *, maximum: int = 256) -> str:
    if not isinstance(value, str):
        raise ValueError("diagram topology identity must be a string")
    result = value.strip()
    if not result or len(result) > maximum:
        raise ValueError("diagram topology identity is empty or too long")
    return result


def _raster_source_id(value: Any) -> str:
    """Require the exact bounded identifier alphabet used by public contracts."""

    if not isinstance(value, str) or _RASTER_SOURCE_ID_RE.fullmatch(value) is None:
        raise ValueError("raster diagram source identity is unsafe")
    return value


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("diagram topology coordinate must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("diagram topology coordinate must be finite")
    return result


def _confidence(value: Any, *, default: float = 1.0) -> float:
    if value is None:
        return default
    result = _number(value)
    if not 0.0 <= result <= 1.0:
        raise ValueError("diagram topology confidence is outside 0..1")
    return result


def _sequence(value: Any, *, label: str, maximum: int) -> list[Any]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or len(value) > maximum
    ):
        raise ValueError(f"diagram {label} exceeds its entry limit")
    return list(value)


def _bbox(value: Any, *, unit: Literal["pt", "px"]) -> VisualBoundingBox:
    if not isinstance(value, Mapping):
        raise ValueError("diagram bbox must be an object")
    if set(value) - {"x", "y", "width", "height", "w", "h", "unit"}:
        raise ValueError("diagram bbox has unsupported fields")
    if (
        ("width" in value) == ("w" in value)
        or ("height" in value) == ("h" in value)
    ):
        raise ValueError("diagram bbox dimensions are missing or ambiguous")
    declared_unit = str(value.get("unit") or unit)
    if declared_unit != unit:
        raise ValueError("diagram bbox coordinate unit differs")
    box = VisualBoundingBox(
        x=_number(value.get("x")),
        y=_number(value.get("y")),
        width=_number(value.get("width", value.get("w"))),
        height=_number(value.get("height", value.get("h"))),
        unit=unit,
    )
    if box.width <= 0 or box.height <= 0:
        raise ValueError("diagram bbox must have positive area")
    return box


def _point(value: Any) -> tuple[float, float]:
    if not isinstance(value, Mapping) or set(value) != {"x", "y"}:
        raise ValueError("diagram path point must contain only x/y")
    x = _number(value.get("x"))
    y = _number(value.get("y"))
    if x < 0 or y < 0:
        raise ValueError("diagram path point must be non-negative")
    return x, y


def _point_box(
    point: tuple[float, float],
    *,
    unit: Literal["pt", "px"],
) -> VisualBoundingBox:
    return VisualBoundingBox(
        x=point[0],
        y=point[1],
        width=0.0,
        height=0.0,
        unit=unit,
    )


def _path_box(
    points: Sequence[tuple[float, float]],
    *,
    unit: Literal["pt", "px"],
) -> VisualBoundingBox:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return VisualBoundingBox(
        x=min(xs),
        y=min(ys),
        width=max(xs) - min(xs),
        height=max(ys) - min(ys),
        unit=unit,
    )


def _inside(
    outer: VisualBoundingBox,
    inner: VisualBoundingBox,
    *,
    tolerance: float = 1e-6,
) -> bool:
    return (
        inner.unit == outer.unit
        and inner.x >= outer.x - tolerance
        and inner.y >= outer.y - tolerance
        and inner.x + inner.width <= outer.x + outer.width + tolerance
        and inner.y + inner.height <= outer.y + outer.height + tolerance
    )


def _positive_area_overlap(
    first: VisualBoundingBox,
    second: VisualBoundingBox,
) -> bool:
    return (
        first.unit == second.unit
        and min(first.x + first.width, second.x + second.width)
        > max(first.x, second.x) + 1e-6
        and min(first.y + first.height, second.y + second.height)
        > max(first.y, second.y) + 1e-6
    )


def _point_box_contact_distance(
    point: tuple[float, float],
    box: VisualBoundingBox,
) -> float:
    return math.hypot(
        max(box.x - point[0], point[0] - (box.x + box.width), 0.0),
        max(box.y - point[1], point[1] - (box.y + box.height), 0.0),
    )


def _segment_enters_box_interior(
    first: tuple[float, float],
    second: tuple[float, float],
    box: VisualBoundingBox,
) -> bool:
    """Return whether a segment crosses a rectangle's positive-area interior."""

    inset = 1e-6
    left = box.x + inset
    top = box.y + inset
    right = box.x + box.width - inset
    bottom = box.y + box.height - inset
    if left > right or top > bottom:
        return False
    delta_x = second[0] - first[0]
    delta_y = second[1] - first[1]
    lower, upper = 0.0, 1.0
    for coefficient, offset in (
        (-delta_x, first[0] - left),
        (delta_x, right - first[0]),
        (-delta_y, first[1] - top),
        (delta_y, bottom - first[1]),
    ):
        if abs(coefficient) <= 1e-12:
            if offset < 0.0:
                return False
            continue
        ratio = offset / coefficient
        if coefficient < 0.0:
            lower = max(lower, ratio)
        else:
            upper = min(upper, ratio)
        if lower > upper:
            return False
    return True


def _boundary_distance(
    point: tuple[float, float],
    box: VisualBoundingBox,
) -> float:
    x, y = point
    left = box.x
    top = box.y
    right = box.x + box.width
    bottom = box.y + box.height
    if left <= x <= right and top <= y <= bottom:
        return min(x - left, right - x, y - top, bottom - y)
    dx = max(left - x, 0.0, x - right)
    dy = max(top - y, 0.0, y - bottom)
    return math.hypot(dx, dy)


def _node_boundary_distance(
    point: tuple[float, float],
    node: DiagramNode,
) -> float:
    if node.shape in {"rectangle", "rounded_rectangle"}:
        return _boundary_distance(point, node.page_bbox)
    box = node.page_bbox
    radius_x = box.width / 2.0
    radius_y = box.height / 2.0
    center_x = box.x + radius_x
    center_y = box.y + radius_y
    normalized_x = abs(point[0] - center_x) / radius_x
    normalized_y = abs(point[1] - center_y) / radius_y
    boundary_measure = (
        math.hypot(normalized_x, normalized_y)
        if node.shape == "ellipse"
        else normalized_x + normalized_y
    )
    return abs(boundary_measure - 1.0) * min(radius_x, radius_y)


def _raw_evidence(item: Mapping[str, Any]) -> Any:
    direct = item.get("diagram_topology_evidence")
    if direct is not None:
        return direct
    meta = item.get("meta")
    return (
        meta.get("phase05_diagram_topology_evidence")
        if isinstance(meta, Mapping)
        else None
    )


def _append_concerns(
    structure: VisualStructure,
    codes: Sequence[str],
) -> VisualStructure:
    payload = structure.model_dump(mode="json", exclude_none=True)
    concerns = payload.setdefault("concerns", [])
    existing = {
        str(value.get("code"))
        for value in concerns
        if isinstance(value, Mapping)
    }
    for code in codes:
        if code in existing or len(concerns) >= 256:
            continue
        concerns.append(
            VisualConcern(
                code=code,
                stage="diagram_topology",
                evidence_ids=list(structure.region.evidence_ids),
            ).model_dump(mode="json", exclude_none=True)
        )
        existing.add(code)
    return VisualStructure.model_validate(payload)


def _label_source_map(structure: VisualStructure) -> dict[str, VisualLabel]:
    evidence = {record.id: record for record in structure.evidence}
    result: dict[str, VisualLabel] = {}
    for label in structure.labels:
        for evidence_id in label.evidence_ids:
            record = evidence[evidence_id]
            for source_token_id in record.provenance.source_token_ids:
                if (
                    source_token_id in result
                    and result[source_token_id].id != label.id
                ):
                    raise ValueError("diagram OCR source identity is ambiguous")
                result[source_token_id] = label
    return result


def _pdf_point(
    value: Mapping[str, Any],
    *,
    endpoint: int,
    page_height: float,
) -> tuple[float, float]:
    x = _number(value.get(f"x{endpoint}"))
    source_y = _number(value.get(f"y{endpoint}"))
    return x, page_height - source_y


def _near(
    first: tuple[float, float],
    second: tuple[float, float],
    tolerance: float,
) -> bool:
    return math.dist(first, second) <= tolerance


def _arrow_wings(
    lines: Sequence[tuple[str, tuple[float, float], tuple[float, float]]],
    *,
    main_index: int,
    source: tuple[float, float],
    tip: tuple[float, float],
) -> tuple[
    tuple[str, tuple[float, float], tuple[float, float]],
    tuple[str, tuple[float, float], tuple[float, float]],
] | None:
    main_length = math.dist(source, tip)
    if main_length <= 0:
        return None
    direction = (tip[0] - source[0], tip[1] - source[1])
    candidates: list[
        tuple[str, tuple[float, float], tuple[float, float]]
    ] = []
    for line_index, (source_id, first, second) in enumerate(lines):
        if line_index == main_index:
            continue
        length = math.dist(first, second)
        if not 1.0 <= length <= min(24.0, main_length * 0.4):
            continue
        if _near(first, tip, 1.5):
            outside = second
        elif _near(second, tip, 1.5):
            outside = first
        else:
            continue
        wing = (outside[0] - tip[0], outside[1] - tip[1])
        # Arrow wings must trail the tip rather than extend beyond it.
        if direction[0] * wing[0] + direction[1] * wing[1] >= -1e-6:
            continue
        candidates.append((source_id, first, second))
        if len(candidates) > _MAX_ARROW_WING_CANDIDATES:
            return None
    pairs: list[
        tuple[
            tuple[str, tuple[float, float], tuple[float, float]],
            tuple[str, tuple[float, float], tuple[float, float]],
        ]
    ] = []
    for first_index, first in enumerate(candidates):
        for second in candidates[first_index + 1 :]:
            first_outside = first[2] if _near(first[1], tip, 1.5) else first[1]
            second_outside = second[2] if _near(second[1], tip, 1.5) else second[1]
            first_vector = (
                first_outside[0] - tip[0],
                first_outside[1] - tip[1],
            )
            second_vector = (
                second_outside[0] - tip[0],
                second_outside[1] - tip[1],
            )
            first_cross = (
                direction[0] * first_vector[1]
                - direction[1] * first_vector[0]
            )
            second_cross = (
                direction[0] * second_vector[1]
                - direction[1] * second_vector[0]
            )
            if first_cross * second_cross < -1e-6:
                pairs.append((first, second))
    return pairs[0] if len(pairs) == 1 else None


def extract_pdf_diagram_topology_evidence(
    source_pdf_bytes: bytes,
    structure: VisualStructure,
    *,
    page_index: int,
) -> dict[str, Any] | None:
    """Recover only rectangular nodes and explicit line-arrow connectors.

    The extractor deliberately requires one contained spatial OCR occurrence
    per rectangle and a two-wing vector arrowhead at exactly one path endpoint.
    It does not infer direction from layout or synthesize relationships from
    nearby shapes.
    """

    if not source_pdf_bytes or structure.region.page_bbox.unit != "pt":
        return None
    import pdfplumber

    region_box = structure.region.page_bbox
    evidence = {record.id: record for record in structure.evidence}
    spatial_labels: list[tuple[VisualLabel, str]] = []
    for label in structure.labels:
        if label.role != "node" or label.page_bbox is None:
            continue
        source_token_ids = {
            source_token_id
            for evidence_id in label.evidence_ids
            for source_token_id in evidence[evidence_id].provenance.source_token_ids
        }
        if len(source_token_ids) == 1:
            spatial_labels.append((label, next(iter(source_token_ids))))

    with pdfplumber.open(io.BytesIO(source_pdf_bytes)) as document:
        if not 1 <= page_index <= len(document.pages):
            return None
        page = document.pages[page_index - 1]
        raw_rect_values = page.rects
        raw_line_values = page.lines
        if (
            not isinstance(raw_rect_values, Sequence)
            or isinstance(raw_rect_values, (str, bytes, bytearray))
            or len(raw_rect_values) > _MAX_NODES
            or not isinstance(raw_line_values, Sequence)
            or isinstance(raw_line_values, (str, bytes, bytearray))
            or len(raw_line_values) > _MAX_PDF_LINES
        ):
            raise ValueError("diagram PDF vector evidence exceeds its resource limit")
        raw_rects = list(raw_rect_values)
        raw_lines = list(raw_line_values)
        page_height = _number(page.height)

    nodes: list[dict[str, Any]] = []
    node_boxes: list[tuple[str, VisualBoundingBox]] = []
    for rect_index, raw_rect in enumerate(raw_rects):
        if not isinstance(raw_rect, Mapping):
            continue
        try:
            box = VisualBoundingBox(
                x=_number(raw_rect.get("x0")),
                y=_number(raw_rect.get("top")),
                width=_number(raw_rect.get("x1")) - _number(raw_rect.get("x0")),
                height=_number(raw_rect.get("bottom"))
                - _number(raw_rect.get("top")),
                unit="pt",
            )
        except (TypeError, ValueError):
            continue
        if (
            box.width < 12.0
            or box.height < 8.0
            or not _inside(region_box, box)
            or box.width >= region_box.width * 0.9
            or box.height >= region_box.height * 0.9
        ):
            continue
        contained = [
            (label, source_token_id)
            for label, source_token_id in spatial_labels
            if label.page_bbox is not None and _inside(box, label.page_bbox)
        ]
        if len(contained) != 1:
            continue
        source_object_id = f"pdfplumber:p{page_index}:rect:{rect_index}"
        nodes.append(
            {
                "source_object_id": source_object_id,
                "shape": "rectangle",
                "page_bbox": box.model_dump(mode="json"),
                "label_source_token_id": contained[0][1],
                "confidence": 1.0,
            }
        )
        node_boxes.append((source_object_id, box))
    if len(nodes) < 2:
        return None

    lines: list[tuple[str, tuple[float, float], tuple[float, float]]] = []
    for line_index, raw_line in enumerate(raw_lines):
        if not isinstance(raw_line, Mapping):
            continue
        try:
            first = _pdf_point(raw_line, endpoint=0, page_height=page_height)
            second = _pdf_point(raw_line, endpoint=1, page_height=page_height)
        except (TypeError, ValueError):
            continue
        if first == second or not all(
            region_box.x - 1e-6 <= point[0] <= region_box.x + region_box.width + 1e-6
            and region_box.y - 1e-6
            <= point[1]
            <= region_box.y + region_box.height + 1e-6
            for point in (first, second)
        ):
            continue
        lines.append(
            (f"pdfplumber:p{page_index}:line:{line_index}", first, second)
        )

    connectors: list[dict[str, Any]] = []
    owned_pairs: set[tuple[str, str]] = set()
    for line_index, (line_source_id, first, second) in enumerate(lines):
        if math.dist(first, second) < 8.0:
            continue
        first_nodes = [
            (source_id, box)
            for source_id, box in node_boxes
            if _boundary_distance(first, box) <= 3.0
        ]
        second_nodes = [
            (source_id, box)
            for source_id, box in node_boxes
            if _boundary_distance(second, box) <= 3.0
        ]
        if (
            len(first_nodes) != 1
            or len(second_nodes) != 1
            or first_nodes[0][0] == second_nodes[0][0]
        ):
            continue
        first_arrow = _arrow_wings(
            lines,
            main_index=line_index,
            source=second,
            tip=first,
        )
        second_arrow = _arrow_wings(
            lines,
            main_index=line_index,
            source=first,
            tip=second,
        )
        if (first_arrow is None) == (second_arrow is None):
            continue
        if second_arrow is not None:
            source_node_id, target_node_id = first_nodes[0][0], second_nodes[0][0]
            source_point, target_point = first, second
            wings = second_arrow
        else:
            source_node_id, target_node_id = second_nodes[0][0], first_nodes[0][0]
            source_point, target_point = second, first
            assert first_arrow is not None
            wings = first_arrow
        pair = (source_node_id, target_node_id)
        if pair in owned_pairs:
            continue
        owned_pairs.add(pair)
        arrow_points = [
            target_point,
            wings[0][1],
            wings[0][2],
            wings[1][1],
            wings[1][2],
        ]
        arrow_box = _path_box(arrow_points, unit="pt")
        if arrow_box.width <= 0 or arrow_box.height <= 0:
            continue
        if len(connectors) >= _MAX_CONNECTORS:
            raise ValueError("diagram PDF connector evidence exceeds its resource limit")
        connectors.append(
            {
                "source_object_id": line_source_id,
                "source_node_source_object_id": source_node_id,
                "target_node_source_object_id": target_node_id,
                "path_points": [
                    {"x": source_point[0], "y": source_point[1]},
                    {"x": target_point[0], "y": target_point[1]},
                ],
                "arrowhead": {
                    "source_object_ids": sorted((wings[0][0], wings[1][0])),
                    "bbox": arrow_box.model_dump(mode="json"),
                    "tip": {"x": target_point[0], "y": target_point[1]},
                },
                "endpoint_tolerance": 3.0,
                "confidence": 1.0,
                "direction_confidence": 1.0,
            }
        )
    return {"nodes": nodes, "connectors": connectors} if connectors else None


def _proper_segment_intersection(
    first: tuple[tuple[float, float], tuple[float, float]],
    second: tuple[tuple[float, float], tuple[float, float]],
) -> bool:
    (ax, ay), (bx, by) = first
    (cx, cy), (dx, dy) = second
    rx, ry = bx - ax, by - ay
    sx, sy = dx - cx, dy - cy
    denominator = rx * sy - ry * sx
    if abs(denominator) <= 1e-9:
        return False
    qpx, qpy = cx - ax, cy - ay
    t = (qpx * sy - qpy * sx) / denominator
    u = (qpx * ry - qpy * rx) / denominator
    epsilon = 1e-7
    return epsilon < t < 1.0 - epsilon and epsilon < u < 1.0 - epsilon


def _path_crosses_itself(points: Sequence[tuple[float, float]]) -> bool:
    segments = list(zip(points, points[1:]))
    return any(
        _proper_segment_intersection(first, second)
        for first_index, first in enumerate(segments)
        for second_index, second in enumerate(segments)
        if second_index > first_index + 1
    )


def _paths_cross(
    first: Sequence[tuple[float, float]],
    second: Sequence[tuple[float, float]],
) -> bool:
    return any(
        _proper_segment_intersection(first_segment, second_segment)
        for first_segment in zip(first, first[1:])
        for second_segment in zip(second, second[1:])
    )


def _paths_touch(
    first: Sequence[tuple[float, float]],
    second: Sequence[tuple[float, float]],
) -> bool:
    tolerance = 1e-6
    return (
        _paths_cross(first, second)
        or any(_point_path_distance(point, second) <= tolerance for point in first)
        or any(_point_path_distance(point, first) <= tolerance for point in second)
    )


def _point_path_distance(
    point: tuple[float, float],
    path: Sequence[tuple[float, float]],
) -> float:
    distances: list[float] = []
    for index in range(len(path) - 1):
        start, end = path[index], path[index + 1]
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length_squared = dx * dx + dy * dy
        if length_squared <= 1e-12:
            distances.append(math.dist(point, start))
            continue
        fraction = max(
            0.0,
            min(
                1.0,
                ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy)
                / length_squared,
            ),
        )
        projection = (start[0] + fraction * dx, start[1] + fraction * dy)
        distances.append(math.dist(point, projection))
    return min(distances) if distances else math.inf


@dataclass(frozen=True, slots=True)
class _NodeCandidate:
    source_object_id: str
    node: DiagramNode
    evidence: VisualEvidence


@dataclass(frozen=True, slots=True)
class _ConnectorCandidate:
    source_object_id: str
    source: _NodeCandidate
    target: _NodeCandidate
    points: tuple[tuple[float, float], ...]
    arrow_source_object_ids: tuple[str, ...]
    arrow_box: VisualBoundingBox
    geometry_confidence: float
    direction_confidence: float


@dataclass(frozen=True, slots=True)
class _RasterGraphProjection:
    transform: VisualTransform
    region_evidence_id: str
    labels: tuple[VisualLabel, ...]
    nodes: tuple[DiagramNode, ...]
    connectors: tuple[DiagramConnector, ...]
    evidence: tuple[VisualEvidence, ...]
    markdown: str
    caption_occurrences: int


def _exact_object(
    value: Any,
    fields: set[str],
    *,
    label: str,
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        raise ValueError(f"raster diagram {label} fields differ")
    return value


def _exact_list(value: Any, *, maximum: int, label: str) -> list[Any]:
    if type(value) is not list or len(value) > maximum:
        raise ValueError(f"raster diagram {label} exceeds its entry limit")
    return value


def _raster_text(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("raster diagram label text must be a string")
    result = value.replace("\r\n", "\n").replace("\r", "\n")
    if (
        not result
        or result.strip() != result
        or len(result) > _RASTER_LABEL_CODEPOINTS
        or any(ord(character) < 0x20 and character != "\n" for character in result)
        or any(character in _UNSAFE_DIRECTIONAL_CHARACTERS for character in result)
    ):
        raise ValueError("raster diagram label text is unsafe")
    try:
        encoded = result.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError("raster diagram label text is not valid UTF-8") from exc
    if len(encoded) > _RASTER_LABEL_BYTES:
        raise ValueError("raster diagram label text exceeds its UTF-8 byte limit")
    return result


def _normalize_raster_label_text(value: str) -> str:
    """Correct only unambiguous OCR whitespace around scalar equality."""

    return re.sub(r"(?<=[A-Za-z])\s*=\s*(?=[0-9])", " = ", value)


def _boxes_close(
    first: VisualBoundingBox,
    second: VisualBoundingBox,
    *,
    tolerance: float = 1e-6,
) -> bool:
    return first.unit == second.unit and all(
        math.isclose(left, right, rel_tol=1e-9, abs_tol=tolerance)
        for left, right in (
            (first.x, second.x),
            (first.y, second.y),
            (first.width, second.width),
            (first.height, second.height),
        )
    )


def _transform_point(
    point: tuple[float, float],
    matrix: Sequence[float],
) -> tuple[float, float]:
    a, b, c, d, e, f = matrix
    return (
        a * point[0] + c * point[1] + e,
        b * point[0] + d * point[1] + f,
    )


def _transform_box(
    box: VisualBoundingBox,
    matrix: Sequence[float],
    *,
    unit: Literal["pt", "px"],
) -> VisualBoundingBox:
    corners = (
        (box.x, box.y),
        (box.x + box.width, box.y),
        (box.x, box.y + box.height),
        (box.x + box.width, box.y + box.height),
    )
    mapped = [_transform_point(point, matrix) for point in corners]
    xs = [point[0] for point in mapped]
    ys = [point[1] for point in mapped]
    return VisualBoundingBox(
        x=min(xs),
        y=min(ys),
        width=max(xs) - min(xs),
        height=max(ys) - min(ys),
        unit=unit,
    )


def _require_box_transform(
    page_box: VisualBoundingBox,
    pixel_box: VisualBoundingBox,
    matrix: Sequence[float],
) -> None:
    if pixel_box.unit != "px" or not _boxes_close(
        page_box,
        _transform_box(pixel_box, matrix, unit=page_box.unit),
    ):
        raise ValueError("raster diagram page/pixel geometry differs")


def _expected_analysis_size(
    page_box: VisualBoundingBox,
    pixel_box: VisualBoundingBox,
    *,
    input_kind: Literal["pdf", "image", "unknown"],
) -> tuple[int, int]:
    source_width = round(pixel_box.width)
    source_height = round(pixel_box.height)
    if source_width != pixel_box.width or source_height != pixel_box.height:
        raise ValueError("raster diagram source pixel dimensions differ")
    if input_kind == "pdf":
        analysis_width = min(
            source_width,
            max(1, round(page_box.width * _PDF_ANALYSIS_PIXELS_PER_POINT)),
        )
        analysis_height = min(
            source_height,
            max(1, round(page_box.height * _PDF_ANALYSIS_PIXELS_PER_POINT)),
        )
    elif input_kind == "image":
        analysis_width, analysis_height = source_width, source_height
    else:
        raise ValueError("raster diagram input kind differs")
    scale = min(
        1.0,
        _MAX_ANALYSIS_EDGE / max(analysis_width, analysis_height),
        math.sqrt(
            _MAX_ANALYSIS_PIXELS / (analysis_width * analysis_height)
        ),
    )
    analysis_width = max(1, round(analysis_width * scale))
    analysis_height = max(1, round(analysis_height * scale))
    if (
        min(analysis_width, analysis_height) < 96
        or analysis_width * analysis_height > _MAX_ANALYSIS_PIXELS
    ):
        raise ValueError("raster diagram analysis dimensions differ")
    return analysis_width, analysis_height


def _expected_endpoint_tolerance(
    page_box: VisualBoundingBox,
    pixel_box: VisualBoundingBox,
    *,
    input_kind: Literal["pdf", "image", "unknown"],
) -> float:
    analysis_width, analysis_height = _expected_analysis_size(
        page_box,
        pixel_box,
        input_kind=input_kind,
    )
    return max(
        page_box.width / analysis_width,
        page_box.height / analysis_height,
    ) * max(5.0, min(analysis_width, analysis_height) * 0.006)


def _raw_raster_evidence(item: Mapping[str, Any]) -> dict[str, Any] | None:
    raw = _raw_evidence(item)
    if not isinstance(raw, Mapping):
        return None
    source = raw.get("source")
    if not isinstance(source, Mapping) or source.get("kind") != "raster":
        return None
    if type(raw) is not dict:
        raise ValueError("raster diagram evidence must be an exact object")
    return raw


def _item_box(item: Mapping[str, Any], *, unit: Literal["pt", "px"]) -> VisualBoundingBox:
    return _bbox(item.get("bbox"), unit=unit)


def _source_bbox(
    value: Any,
    *,
    unit: Literal["pt", "px"],
) -> VisualBoundingBox:
    """Accept a lossless predecessor width/height alias projection."""

    if not isinstance(value, Mapping):
        raise TypeError("raster diagram source bbox differs")
    normalized = dict(value)
    for primary, alias in (("width", "w"), ("height", "h")):
        if primary in normalized and alias in normalized:
            if _number(normalized[primary]) != _number(normalized[alias]):
                raise ValueError("raster diagram source bbox aliases differ")
            normalized.pop(alias)
    return _bbox(normalized, unit=unit)


def _owner_proof(item: Mapping[str, Any]) -> dict[str, Any]:
    meta = item.get("meta")
    proof = (
        meta.get("phase05_raster_diagram_owner")
        if isinstance(meta, Mapping)
        else None
    )
    fields = {
        "schema_version",
        "owner_id",
        "page_index",
        "input_kind",
        "region_role",
        "region_origin",
        "layout_bbox",
        "detected_bbox",
        "pixel_width",
        "pixel_height",
        "layout_coverage",
        "detected_coverage",
        "mapping_tolerance_x",
        "mapping_tolerance_y",
        "ocr_ledger_sha256",
    }
    return _exact_object(proof, fields, label="owner proof")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _replay_ocr_ledger_sha256(
    item: Mapping[str, Any],
    *,
    unit: Literal["pt", "px"],
) -> str:
    lines = _exact_list(item.get("items"), maximum=512, label="OCR lines")
    tokens = _exact_list(
        item.get("ocr_token_occurrences"),
        maximum=4_096,
        label="OCR tokens",
    )
    summary = item.get("ocr_occurrence_summary")
    if type(summary) is not dict:
        raise ValueError("raster diagram OCR summary differs")
    accepted: list[str] = []
    for raw_line in lines:
        if type(raw_line) is not dict:
            raise ValueError("raster diagram OCR line differs")
        if raw_line.get("accepted") is True:
            line_text = raw_line.get("text", raw_line.get("value"))
            if not isinstance(line_text, str):
                raise ValueError("raster diagram OCR line text differs")
            accepted.append(line_text)
    accepted_text = "\n".join(accepted)
    if item.get("ocr_text") != accepted_text:
        raise ValueError("raster diagram OCR primary projection differs")
    token_projection: list[tuple[Any, ...]] = []
    for raw_token in tokens:
        if type(raw_token) is not dict:
            raise ValueError("raster diagram OCR token differs")
        page_box = _source_bbox(raw_token.get("bbox"), unit=unit)
        crop = raw_token.get("crop_pixel_bbox")
        crop_box = _source_bbox(crop, unit="px") if crop is not None else None
        token_projection.append(
            (
                raw_token.get("text"),
                raw_token.get("ocr_pass"),
                (
                    page_box.x,
                    page_box.y,
                    page_box.width,
                    page_box.height,
                    page_box.unit,
                ),
                (
                    None
                    if crop_box is None
                    else (
                        crop_box.x,
                        crop_box.y,
                        crop_box.width,
                        crop_box.height,
                        crop_box.unit,
                    )
                ),
                raw_token.get("selected"),
                raw_token.get("primary_selected"),
                raw_token.get("short_alternative"),
            )
        )
    projection = {
        "value": accepted_text,
        "md": accepted_text,
        "raw_ocr_text": item.get("raw_ocr_text"),
        "items": lines,
        "ocr_occurrence_summary": summary,
        "ocr_tokens": token_projection,
    }
    return hashlib.sha256(_canonical_json(projection).encode("utf-8")).hexdigest()


def _markdown_text(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r\n", "<br>")
        .replace("\r", "<br>")
        .replace("\n", "<br>")
        .strip()
    )


def _build_raster_markdown(
    item: Mapping[str, Any],
    labels: Sequence[VisualLabel],
    nodes: Sequence[DiagramNode],
    connectors: Sequence[DiagramConnector],
) -> tuple[str, int]:
    """Serialize an explicit directed graph as a deterministic list forest."""

    labels_by_id = {label.id: label for label in labels}
    nodes_by_id = {node.id: node for node in nodes}
    if (
        not nodes
        or not connectors
        or len(nodes_by_id) != len(nodes)
        or any(node.label_id is None for node in nodes)
    ):
        raise ValueError("raster diagram graph is incomplete")
    names = {
        node.id: _markdown_text(labels_by_id[node.label_id].text)
        for node in nodes
        if node.label_id is not None
    }
    name_counts: dict[str, int] = {}
    for name in names.values():
        name_counts[name] = name_counts.get(name, 0) + 1

    incoming: dict[str, int] = {node.id: 0 for node in nodes}
    outgoing: dict[str, list[DiagramConnector]] = {
        node.id: [] for node in nodes
    }
    undirected: dict[str, set[str]] = {node.id: set() for node in nodes}
    pairs: set[tuple[str, str]] = set()
    for connector in connectors:
        pair = (connector.source_node_id, connector.target_node_id)
        if (
            connector.source_node_id not in nodes_by_id
            or connector.target_node_id not in nodes_by_id
            or connector.source_node_id == connector.target_node_id
            or pair in pairs
        ):
            raise ValueError("raster diagram edge ownership differs")
        pairs.add(pair)
        incoming[connector.target_node_id] += 1
        outgoing[connector.source_node_id].append(connector)
        undirected[connector.source_node_id].add(connector.target_node_id)
        undirected[connector.target_node_id].add(connector.source_node_id)

    def node_key(node_id: str) -> tuple[float, float, float, float, str]:
        box = nodes_by_id[node_id].page_bbox
        return (box.y, box.x, box.width, box.height, node_id)

    def edge_key(
        connector: DiagramConnector,
    ) -> tuple[float, float, float, float, str, str]:
        return (*node_key(connector.target_node_id), connector.id)

    for values in outgoing.values():
        values.sort(key=edge_key)
    roots = sorted(
        (node_id for node_id, count in incoming.items() if count == 0),
        key=node_key,
    )
    if not roots:
        raise ValueError("raster diagram has no arrow-grounded starting point")

    # Every weak component must have an explicit indegree-zero start.  This
    # rejects a disconnected rootless cycle while still allowing a loop that
    # is reached from a real starting node.
    seen_components: set[str] = set()
    root_set = set(roots)
    for candidate in sorted(nodes_by_id, key=node_key):
        if candidate in seen_components:
            continue
        component: set[str] = set()
        pending = [candidate]
        while pending:
            current = pending.pop()
            if current in component:
                continue
            component.add(current)
            pending.extend(undirected[current] - component)
        seen_components.update(component)
        if not component & root_set:
            raise ValueError("raster diagram contains a rootless component")

    lines: list[str] = []
    raw_caption = item.get("caption")
    caption = _raster_text(raw_caption) if isinstance(raw_caption, str) and raw_caption else ""
    if caption:
        lines.extend((_markdown_text(caption), ""))

    expanded: set[str] = set()
    active: set[str] = set()

    def connector_prefix(connector: DiagramConnector) -> str:
        if connector.label_id is None:
            return ""
        return f"{_markdown_text(labels_by_id[connector.label_id].text)}: "

    def emit_node(
        node_id: str,
        depth: int,
        connector: DiagramConnector | None = None,
    ) -> None:
        if depth > _MAX_NODES:
            raise ValueError("raster diagram hierarchy exceeds its depth limit")
        node = nodes_by_id[node_id]
        prefix = connector_prefix(connector) if connector is not None else ""
        lines.append(f"{'  ' * depth}- {prefix}{names[node_id]}")
        for detail_label_id in node.detail_label_ids:
            lines.append(
                f"{'  ' * (depth + 1)}- "
                f"{_markdown_text(labels_by_id[detail_label_id].text)}"
            )
        expanded.add(node_id)
        active.add(node_id)
        for edge in outgoing[node_id]:
            target = edge.target_node_id
            if target in active:
                if name_counts[names[target]] != 1:
                    raise ValueError("raster loop reference text is ambiguous")
                lines.append(
                    f"{'  ' * (depth + 1)}- {connector_prefix(edge)}"
                    f"Returns to: {names[target]}"
                )
            elif target in expanded:
                if name_counts[names[target]] != 1:
                    raise ValueError("raster merge reference text is ambiguous")
                lines.append(
                    f"{'  ' * (depth + 1)}- {connector_prefix(edge)}"
                    f"Continues at: {names[target]}"
                )
            else:
                emit_node(target, depth + 1, edge)
        active.remove(node_id)

    for root in roots:
        if root in expanded:
            continue
        emit_node(root, 0)
    if expanded != set(nodes_by_id):
        raise ValueError("raster diagram graph is not fully reachable")
    markdown = "\n".join(lines)
    if len(markdown.encode("utf-8")) > 262_144:
        raise ValueError("raster diagram Markdown exceeds its public limit")
    return markdown, 1 if caption else 0


def _raster_graph_projection(
    item: Mapping[str, Any],
    structure: VisualStructure,
    raw: dict[str, Any],
    *,
    page_index: int,
    input_kind: Literal["pdf", "image", "unknown"],
    label_occurrence_offset: int | None = None,
) -> _RasterGraphProjection:
    _exact_object(
        raw,
        {"schema_version", "source", "nodes", "connectors", "accounting"},
        label="evidence",
    )
    if raw.get("schema_version") != "1.0" or input_kind == "unknown":
        raise ValueError("raster diagram evidence version or source kind differs")
    unit: Literal["pt", "px"] = structure.region.page_bbox.unit
    source = _exact_object(
        raw.get("source"),
        {
            "kind",
            "owner_id",
            "page_bbox",
            "raster_pixel_bbox",
            "transform",
            "ocr_ledger_sha256",
        },
        label="source",
    )
    if source.get("kind") != "raster":
        raise ValueError("raster diagram source kind differs")
    owner_id = _raster_source_id(source.get("owner_id"))
    page_box = _bbox(source.get("page_bbox"), unit=unit)
    pixel_box = _bbox(source.get("raster_pixel_bbox"), unit="px")
    if (
        pixel_box.x != 0.0
        or pixel_box.y != 0.0
        or not _boxes_close(page_box, structure.region.page_bbox)
        or not _boxes_close(page_box, _item_box(item, unit=unit))
    ):
        raise ValueError("raster diagram source owner geometry differs")
    matrix_values = _exact_list(
        source.get("transform"), maximum=6, label="source transform"
    )
    if len(matrix_values) != 6:
        raise ValueError("raster diagram source transform length differs")
    matrix = [_number(value) for value in matrix_values]
    if (
        matrix[0] <= 0.0
        or matrix[3] <= 0.0
        or matrix[1] != 0.0
        or matrix[2] != 0.0
    ):
        raise ValueError("raster diagram source transform is unsupported")
    _require_box_transform(page_box, pixel_box, matrix)

    proof = _owner_proof(item)
    digest = source.get("ocr_ledger_sha256")
    layout_box = _bbox(proof.get("layout_bbox"), unit=unit)
    detected_box = _bbox(proof.get("detected_bbox"), unit=unit)
    intersection_width = max(
        0.0,
        min(layout_box.x + layout_box.width, detected_box.x + detected_box.width)
        - max(layout_box.x, detected_box.x),
    )
    intersection_height = max(
        0.0,
        min(layout_box.y + layout_box.height, detected_box.y + detected_box.height)
        - max(layout_box.y, detected_box.y),
    )
    intersection_area = intersection_width * intersection_height
    expected_layout_coverage = intersection_area / (
        layout_box.width * layout_box.height
    )
    expected_detected_coverage = intersection_area / (
        detected_box.width * detected_box.height
    )
    proof_layout_coverage = _number(proof.get("layout_coverage"))
    proof_detected_coverage = _number(proof.get("detected_coverage"))
    expected_tolerance_x = max(1.5, detected_box.width * 0.015)
    expected_tolerance_y = max(1.5, detected_box.height * 0.015)
    expected_role_origin = (
        ({"content_region"}, "pdf_embedded")
        if input_kind == "pdf"
        else ({"page_source", "content_region"}, "uploaded_page")
    )
    if (
        proof.get("schema_version") != "1.0"
        or proof.get("owner_id") != owner_id
        or proof.get("page_index") != page_index
        or proof.get("input_kind") != input_kind
        or proof.get("ocr_ledger_sha256") != digest
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        or _replay_ocr_ledger_sha256(item, unit=unit) != digest
        or not _boxes_close(detected_box, page_box)
        or not isinstance(proof.get("pixel_width"), int)
        or isinstance(proof.get("pixel_width"), bool)
        or not isinstance(proof.get("pixel_height"), int)
        or isinstance(proof.get("pixel_height"), bool)
        or proof.get("pixel_width") != pixel_box.width
        or proof.get("pixel_height") != pixel_box.height
        or proof.get("region_role") not in expected_role_origin[0]
        or proof.get("region_origin") != expected_role_origin[1]
        or proof_layout_coverage < 0.95
        or proof_detected_coverage < 0.95
        or not math.isclose(
            proof_layout_coverage,
            expected_layout_coverage,
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
        or not math.isclose(
            proof_detected_coverage,
            expected_detected_coverage,
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
        or not math.isclose(
            _number(proof.get("mapping_tolerance_x")),
            expected_tolerance_x,
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
        or not math.isclose(
            _number(proof.get("mapping_tolerance_y")),
            expected_tolerance_y,
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
    ):
        raise ValueError("raster diagram source custody differs")

    transform_id = _stable_id(
        "visual-transform", structure.region.id, "raster", owner_id, matrix
    )
    transform = VisualTransform(
        id=transform_id,
        source_space="raster_pixel",
        target_space="page",
        matrix=matrix,
    )
    public_item_ids = {
        evidence.provenance.public_item_id for evidence in structure.evidence
    }
    if len(public_item_ids) != 1:
        raise ValueError("raster diagram public owner identity differs")
    public_item_id = next(iter(public_item_ids))
    if item.get("id") != public_item_id:
        raise ValueError("raster diagram public item identity differs")
    analysis_width, analysis_height = _expected_analysis_size(
        page_box,
        pixel_box,
        input_kind=input_kind,
    )

    token_records: dict[str, dict[str, Any]] = {}
    token_ledger_indexes: dict[str, int] = {}
    selected_primary_token_ids: set[str] = set()
    for token_ledger_index, raw_token in enumerate(
        _exact_list(
            item.get("ocr_token_occurrences"),
            maximum=4_096,
            label="OCR tokens",
        )
    ):
        if type(raw_token) is not dict:
            raise ValueError("raster diagram OCR token differs")
        token_id = _raster_source_id(raw_token.get("occurrence_id"))
        _raster_source_id(raw_token.get("line_occurrence_id"))
        if token_id in token_records:
            raise ValueError("raster diagram OCR token identity repeats")
        token_records[token_id] = raw_token
        token_ledger_indexes[token_id] = token_ledger_index
        if (
            raw_token.get("selected") is True
            and raw_token.get("primary_selected") is True
        ):
            selected_primary_token_ids.add(token_id)

    labels: list[VisualLabel] = []
    evidence: list[VisualEvidence] = []
    owned_token_ids: set[str] = set()
    occurrence_offset = (
        len(structure.labels)
        if label_occurrence_offset is None
        else label_occurrence_offset
    )
    if not 0 <= occurrence_offset <= len(structure.labels):
        raise ValueError("raster diagram label occurrence offset differs")

    def provenance(
        *,
        source_object_ids: Sequence[str] = (),
        source_token_ids: Sequence[str] = (),
    ) -> VisualProvenance:
        return VisualProvenance(
            public_item_id=public_item_id,
            page_index=page_index,
            input_kind=input_kind,
            source_object_ids=sorted(source_object_ids),
            source_token_ids=sorted(source_token_ids),
            extraction_method="raster",
        )

    region_evidence_id = _stable_id(
        "visual-evidence", structure.region.id, "raster-source", owner_id
    )
    evidence.append(
        VisualEvidence(
            id=region_evidence_id,
            kind="source_object",
            page_bbox=page_box,
            raster_pixel_bbox=pixel_box,
            transform_ids=[transform_id],
            provenance=provenance(source_object_ids=[owner_id]),
        )
    )

    def parse_label(
        value: Any,
        *,
        role: Literal["node", "node_detail", "connector"],
        source_identity: str,
        owner_page_box: VisualBoundingBox | None,
        owner_pixel_box: VisualBoundingBox | None,
    ) -> tuple[VisualLabel, VisualEvidence]:
        raw_label = _exact_object(
            value,
            {"text", "page_bbox", "raster_pixel_bbox", "source_token_ids"},
            label=f"{role} label",
        )
        source_label_text = _raster_text(raw_label.get("text"))
        label_text = _normalize_raster_label_text(source_label_text)
        label_page_box = _bbox(raw_label.get("page_bbox"), unit=unit)
        label_pixel_box = _bbox(raw_label.get("raster_pixel_bbox"), unit="px")
        _require_box_transform(label_page_box, label_pixel_box, matrix)
        if (
            not _inside(page_box, label_page_box)
            or not _inside(pixel_box, label_pixel_box)
            or (
                owner_page_box is not None
                and not _inside(owner_page_box, label_page_box)
            )
            or (
                owner_pixel_box is not None
                and not _inside(owner_pixel_box, label_pixel_box)
            )
        ):
            raise ValueError("raster diagram label leaves its owner")
        source_token_ids = _exact_list(
            raw_label.get("source_token_ids"),
            maximum=_MAX_REFERENCES,
            label="label source tokens",
        )
        if not source_token_ids:
            raise ValueError("raster diagram label has no source token")
        normalized_ids = [_raster_source_id(value) for value in source_token_ids]
        if normalized_ids != sorted(set(normalized_ids)):
            raise ValueError("raster diagram label token ownership differs")
        if owned_token_ids & set(normalized_ids):
            raise ValueError("raster diagram OCR token has multiple semantic owners")
        owned_token_ids.update(normalized_ids)
        selected_tokens: list[dict[str, Any]] = []
        for token_id in normalized_ids:
            token = token_records.get(token_id)
            if (
                token is None
                or token.get("selected") is not True
                or token.get("primary_selected") is not True
                or not isinstance(token.get("text"), str)
            ):
                raise ValueError("raster diagram label token is unavailable")
            selected_tokens.append(token)
        token_boxes = [
            _source_bbox(token.get("bbox"), unit=unit)
            for token in selected_tokens
        ]
        token_union = VisualBoundingBox(
            x=min(box.x for box in token_boxes),
            y=min(box.y for box in token_boxes),
            width=max(box.x + box.width for box in token_boxes)
            - min(box.x for box in token_boxes),
            height=max(box.y + box.height for box in token_boxes)
            - min(box.y for box in token_boxes),
            unit=unit,
        )
        if not _boxes_close(token_union, label_page_box):
            raise ValueError("raster diagram label token geometry differs")
        lines: dict[str, list[dict[str, Any]]] = {}
        for token in selected_tokens:
            line_id = _raster_source_id(token.get("line_occurrence_id"))
            word_index = token.get("word_index")
            if (
                not isinstance(word_index, int)
                or isinstance(word_index, bool)
                or word_index < 0
            ):
                raise ValueError("raster diagram OCR word order differs")
            lines.setdefault(line_id, []).append(token)

        def token_box(token: Mapping[str, Any]) -> VisualBoundingBox:
            return _source_bbox(token.get("bbox"), unit=unit)

        def token_ledger_index(token: Mapping[str, Any]) -> int:
            return token_ledger_indexes[
                _raster_source_id(token.get("occurrence_id"))
            ]

        def token_analysis_box(token: Mapping[str, Any]) -> VisualBoundingBox:
            box = token_box(token)
            left = round((box.x - page_box.x) * analysis_width / page_box.width)
            top = round((box.y - page_box.y) * analysis_height / page_box.height)
            right = round(
                (box.x + box.width - page_box.x)
                * analysis_width
                / page_box.width
            )
            bottom = round(
                (box.y + box.height - page_box.y)
                * analysis_height
                / page_box.height
            )
            left = min(max(left, 0), analysis_width)
            top = min(max(top, 0), analysis_height)
            right = min(max(right, 0), analysis_width)
            bottom = min(max(bottom, 0), analysis_height)
            if right <= left or bottom <= top:
                raise ValueError("raster diagram OCR token projection differs")
            return VisualBoundingBox(
                x=float(left),
                y=float(top),
                width=float(right - left),
                height=float(bottom - top),
                unit="px",
            )

        ordered_lines = sorted(
            lines.values(),
            key=lambda values: min(token_ledger_index(token) for token in values),
        )
        rendered_lines: list[str] = []
        for line in ordered_lines:
            ordered = sorted(
                line,
                key=lambda token: (
                    token.get("word_index"),
                    token_analysis_box(token).x,
                ),
            )
            pieces: list[str] = []
            previous: Mapping[str, Any] | None = None
            for token in ordered:
                if previous is not None:
                    prior_analysis_box = token_analysis_box(previous)
                    current_analysis_box = token_analysis_box(token)
                    gap = math.hypot(
                        max(
                            prior_analysis_box.x
                            - (
                                current_analysis_box.x
                                + current_analysis_box.width
                            ),
                            current_analysis_box.x
                            - (prior_analysis_box.x + prior_analysis_box.width),
                            0.0,
                        ),
                        max(
                            prior_analysis_box.y
                            - (
                                current_analysis_box.y
                                + current_analysis_box.height
                            ),
                            current_analysis_box.y
                            - (prior_analysis_box.y + prior_analysis_box.height),
                            0.0,
                        ),
                    )
                    threshold = max(
                        0.5,
                        min(
                            current_analysis_box.width,
                            current_analysis_box.height,
                            prior_analysis_box.width,
                            prior_analysis_box.height,
                        )
                        * 0.08,
                    )
                    if gap > threshold:
                        pieces.append(" ")
                pieces.append(str(token.get("text")))
                previous = token
            rendered_lines.append("".join(pieces).strip())
        if " ".join(rendered_lines).strip() != source_label_text:
            raise ValueError("raster diagram label text differs from its tokens")
        evidence_id = _stable_id(
            "visual-evidence", structure.region.id, role, source_identity
        )
        label_id = _stable_id(
            "visual-label", structure.region.id, role, source_identity
        )
        record = VisualEvidence(
            id=evidence_id,
            kind="label",
            page_bbox=label_page_box,
            raster_pixel_bbox=label_pixel_box,
            transform_ids=[transform_id],
            provenance=provenance(source_token_ids=normalized_ids),
        )
        label = VisualLabel(
            id=label_id,
            text=label_text,
            role=role,
            page_bbox=label_page_box,
            raster_pixel_bbox=label_pixel_box,
            evidence_ids=[evidence_id],
            occurrence_index=occurrence_offset + len(labels),
        )
        labels.append(label)
        evidence.append(record)
        return label, record

    raw_nodes = _exact_list(raw.get("nodes"), maximum=_MAX_NODES, label="nodes")
    if not raw_nodes:
        raise ValueError("raster diagram has no nodes")
    node_candidates: list[_NodeCandidate] = []
    nodes_by_source: dict[str, _NodeCandidate] = {}
    node_pixel_boxes: dict[str, VisualBoundingBox] = {}
    owned_node_regions: list[
        tuple[str, VisualBoundingBox, VisualBoundingBox]
    ] = []
    source_object_ids: set[str] = {owner_id}
    detail_count = 0
    for raw_node in raw_nodes:
        node_value = _exact_object(
            raw_node,
            {
                "source_object_id",
                "shape",
                "page_bbox",
                "raster_pixel_bbox",
                "label",
                "details",
                "confidence",
            },
            label="node",
        )
        source_id = _raster_source_id(node_value.get("source_object_id"))
        if source_id in source_object_ids:
            raise ValueError("raster diagram source identity repeats")
        source_object_ids.add(source_id)
        if node_value.get("shape") != "rectangle":
            raise ValueError("raster diagram node shape is unsupported")
        node_page_box = _bbox(node_value.get("page_bbox"), unit=unit)
        node_pixel_box = _bbox(node_value.get("raster_pixel_bbox"), unit="px")
        _require_box_transform(node_page_box, node_pixel_box, matrix)
        if not _inside(page_box, node_page_box) or not _inside(pixel_box, node_pixel_box):
            raise ValueError("raster diagram node leaves its source owner")
        label, label_evidence = parse_label(
            node_value.get("label"),
            role="node",
            source_identity=source_id,
            owner_page_box=node_page_box,
            owner_pixel_box=node_pixel_box,
        )
        assert label_evidence.page_bbox is not None
        assert label_evidence.raster_pixel_bbox is not None
        owned_node_regions.append(
            (source_id, label_evidence.page_bbox, label_evidence.raster_pixel_bbox)
        )
        node_evidence_id = _stable_id(
            "visual-evidence", structure.region.id, "raster-node", source_id
        )
        node_record = VisualEvidence(
            id=node_evidence_id,
            kind="node",
            page_bbox=node_page_box,
            raster_pixel_bbox=node_pixel_box,
            transform_ids=[transform_id],
            provenance=provenance(source_object_ids=[source_id]),
        )
        evidence.append(node_record)
        node_evidence_ids = [node_evidence_id, label_evidence.id]
        detail_label_ids: list[str] = []
        for detail_index, raw_detail in enumerate(
            _exact_list(
                node_value.get("details"),
                maximum=_MAX_REFERENCES,
                label="node details",
            )
        ):
            detail_value = _exact_object(
                raw_detail,
                {
                    "text",
                    "page_bbox",
                    "raster_pixel_bbox",
                    "source_token_ids",
                    "bullet",
                },
                label="node detail",
            )
            bullet = _exact_object(
                detail_value.get("bullet"),
                {"source_object_id", "page_bbox", "raster_pixel_bbox"},
                label="detail bullet",
            )
            bullet_id = _raster_source_id(bullet.get("source_object_id"))
            if bullet_id in source_object_ids:
                raise ValueError("raster diagram source identity repeats")
            source_object_ids.add(bullet_id)
            bullet_page_box = _bbox(bullet.get("page_bbox"), unit=unit)
            bullet_pixel_box = _bbox(bullet.get("raster_pixel_bbox"), unit="px")
            _require_box_transform(bullet_page_box, bullet_pixel_box, matrix)
            if (
                not _inside(node_page_box, bullet_page_box)
                or not _inside(node_pixel_box, bullet_pixel_box)
            ):
                raise ValueError("raster diagram bullet leaves its node")
            bullet_token_ids: list[str] = []
            for token_id in sorted(selected_primary_token_ids - owned_token_ids):
                token_box = _source_bbox(
                    token_records[token_id].get("bbox"),
                    unit=unit,
                )
                intersection_width = max(
                    0.0,
                    min(
                        token_box.x + token_box.width,
                        bullet_page_box.x + bullet_page_box.width,
                    )
                    - max(token_box.x, bullet_page_box.x),
                )
                intersection_height = max(
                    0.0,
                    min(
                        token_box.y + token_box.height,
                        bullet_page_box.y + bullet_page_box.height,
                    )
                    - max(token_box.y, bullet_page_box.y),
                )
                overlap = intersection_width * intersection_height
                center = (
                    token_box.x + token_box.width / 2.0,
                    token_box.y + token_box.height / 2.0,
                )
                if (
                    overlap / (token_box.width * token_box.height) >= 0.25
                    or (
                        bullet_page_box.x - 1e-6
                        <= center[0]
                        <= bullet_page_box.x + bullet_page_box.width + 1e-6
                        and bullet_page_box.y - 1e-6
                        <= center[1]
                        <= bullet_page_box.y + bullet_page_box.height + 1e-6
                    )
                ):
                    bullet_token_ids.append(token_id)
            if len(bullet_token_ids) > 1:
                raise ValueError("raster diagram bullet token ownership is ambiguous")
            owned_token_ids.update(bullet_token_ids)
            detail_label, detail_record = parse_label(
                {key: detail_value[key] for key in (
                    "text", "page_bbox", "raster_pixel_bbox", "source_token_ids"
                )},
                role="node_detail",
                source_identity=f"{source_id}:{bullet_id}:{detail_index}",
                owner_page_box=node_page_box,
                owner_pixel_box=node_pixel_box,
            )
            bullet_evidence_id = _stable_id(
                "visual-evidence", structure.region.id, "bullet", bullet_id
            )
            bullet_record = VisualEvidence(
                id=bullet_evidence_id,
                kind="source_object",
                page_bbox=bullet_page_box,
                raster_pixel_bbox=bullet_pixel_box,
                transform_ids=[transform_id],
                provenance=provenance(
                    source_object_ids=[bullet_id],
                    source_token_ids=bullet_token_ids,
                ),
            )
            assert detail_record.page_bbox is not None
            assert detail_record.raster_pixel_bbox is not None
            owned_node_regions.extend(
                (
                    (
                        source_id,
                        detail_record.page_bbox,
                        detail_record.raster_pixel_bbox,
                    ),
                    (source_id, bullet_page_box, bullet_pixel_box),
                )
            )
            evidence.append(bullet_record)
            # The detail owns both its lexical evidence and its bullet marker.
            labels[-1] = detail_label.model_copy(
                update={
                    "evidence_ids": [detail_record.id, bullet_evidence_id]
                }
            )
            detail_label_ids.append(detail_label.id)
            node_evidence_ids.extend((detail_record.id, bullet_evidence_id))
            detail_count += 1
        node = DiagramNode(
            id=_stable_id("diagram-node", structure.region.id, source_id),
            shape="rectangle",
            label_id=label.id,
            detail_label_ids=detail_label_ids,
            page_bbox=node_page_box,
            evidence_ids=node_evidence_ids,
            confidence=VisualConfidenceDimensions(
                geometry=_confidence(node_value.get("confidence"))
            ),
        )
        candidate = _NodeCandidate(source_id, node, node_record)
        node_candidates.append(candidate)
        nodes_by_source[source_id] = candidate
        node_pixel_boxes[source_id] = node_pixel_box

    for node_index, first in enumerate(node_candidates):
        first_pixel_box = node_pixel_boxes[first.source_object_id]
        for second in node_candidates[node_index + 1 :]:
            if _positive_area_overlap(first.node.page_bbox, second.node.page_bbox) or (
                _positive_area_overlap(
                    first_pixel_box,
                    node_pixel_boxes[second.source_object_id],
                )
            ):
                raise ValueError("raster diagram node ownership overlaps")
    for owner_source_id, owned_page_box, owned_pixel_box in owned_node_regions:
        page_owners = {
            candidate.source_object_id
            for candidate in node_candidates
            if _inside(candidate.node.page_bbox, owned_page_box)
        }
        pixel_owners = {
            source_id
            for source_id, candidate_box in node_pixel_boxes.items()
            if _inside(candidate_box, owned_pixel_box)
        }
        if page_owners != {owner_source_id} or pixel_owners != {owner_source_id}:
            raise ValueError("raster diagram node content ownership is ambiguous")

    raw_connectors = _exact_list(
        raw.get("connectors"), maximum=_MAX_CONNECTORS, label="connectors"
    )
    if not raw_connectors:
        raise ValueError("raster diagram has no connectors")
    analysis_node_boxes = {
        source_id: VisualBoundingBox(
            x=(box.x - pixel_box.x) * analysis_width / pixel_box.width,
            y=(box.y - pixel_box.y) * analysis_height / pixel_box.height,
            width=box.width * analysis_width / pixel_box.width,
            height=box.height * analysis_height / pixel_box.height,
            unit="px",
        )
        for source_id, box in node_pixel_boxes.items()
    }
    contact_tolerance = max(
        5.0,
        min(analysis_width, analysis_height) * 0.006,
    )

    def require_unique_endpoint_owner(
        point: tuple[float, float],
        declared_source_id: str,
    ) -> None:
        analysis_point = (
            (point[0] - pixel_box.x) * analysis_width / pixel_box.width,
            (point[1] - pixel_box.y) * analysis_height / pixel_box.height,
        )
        distances = {
            source_id: _point_box_contact_distance(analysis_point, box)
            for source_id, box in analysis_node_boxes.items()
        }
        owned_distance = distances[declared_source_id]
        competing_distance = min(
            distance
            for source_id, distance in distances.items()
            if source_id != declared_source_id
        )
        if (
            owned_distance > contact_tolerance + 1e-6
            or competing_distance - owned_distance <= 1.0 + 1e-6
        ):
            raise ValueError("raster diagram connector endpoint owner is ambiguous")

    connectors: list[DiagramConnector] = []
    connector_paths: list[tuple[tuple[float, float], ...]] = []
    connector_component_ids: list[int] = []
    connector_source_ids: list[str] = []
    connector_label_claims: list[tuple[int, VisualLabel]] = []
    component_indexes: set[int] = set()
    directed_pairs: set[tuple[str, str]] = set()
    for connector_index, raw_connector in enumerate(raw_connectors):
        allowed = {
            "source_object_id",
            "component_index",
            "source_node_source_object_id",
            "target_node_source_object_id",
            "path_points",
            "raster_path_points",
            "arrowhead",
            "endpoint_tolerance",
            "confidence",
            "direction_confidence",
        }
        if type(raw_connector) is not dict or set(raw_connector) not in (
            allowed,
            allowed | {"label"},
        ):
            raise ValueError("raster diagram connector fields differ")
        connector_source_id = _raster_source_id(
            raw_connector.get("source_object_id")
        )
        if connector_source_id in source_object_ids:
            raise ValueError("raster diagram source identity repeats")
        source_object_ids.add(connector_source_id)
        component_index = raw_connector.get("component_index")
        if (
            not isinstance(component_index, int)
            or isinstance(component_index, bool)
            or not 0 <= component_index < _MAX_CONNECTORS
        ):
            raise ValueError("raster diagram connector component differs")
        component_indexes.add(component_index)
        source_node_source_id = _raster_source_id(
            raw_connector.get("source_node_source_object_id")
        )
        target_node_source_id = _raster_source_id(
            raw_connector.get("target_node_source_object_id")
        )
        source_node = nodes_by_source.get(source_node_source_id)
        target_node = nodes_by_source.get(target_node_source_id)
        pair = (source_node_source_id, target_node_source_id)
        if (
            source_node is None
            or target_node is None
            or source_node is target_node
            or pair in directed_pairs
        ):
            raise ValueError("raster diagram connector endpoint ownership differs")
        directed_pairs.add(pair)
        page_points = tuple(
            _point(value)
            for value in _exact_list(
                raw_connector.get("path_points"),
                maximum=_MAX_PATH_POINTS,
                label="connector page path",
            )
        )
        pixel_points = tuple(
            _point(value)
            for value in _exact_list(
                raw_connector.get("raster_path_points"),
                maximum=_MAX_PATH_POINTS,
                label="connector raster path",
            )
        )
        if (
            len(page_points) < 2
            or len(page_points) != len(pixel_points)
            or any(
                not (
                    math.isclose(page[0], mapped[0], rel_tol=1e-9, abs_tol=1e-6)
                    and math.isclose(page[1], mapped[1], rel_tol=1e-9, abs_tol=1e-6)
                )
                for page, mapped in zip(
                    page_points,
                    (_transform_point(point, matrix) for point in pixel_points),
                    strict=True,
                )
            )
            or _path_crosses_itself(page_points)
        ):
            raise ValueError("raster diagram connector path geometry differs")
        path_page_box = _path_box(page_points, unit=unit)
        path_pixel_box = _path_box(pixel_points, unit="px")
        if not _inside(page_box, path_page_box) or not _inside(pixel_box, path_pixel_box):
            raise ValueError("raster diagram connector leaves its source owner")
        tolerance = _number(raw_connector.get("endpoint_tolerance"))
        expected_tolerance = _expected_endpoint_tolerance(
            page_box,
            pixel_box,
            input_kind=input_kind,
        )
        if not math.isclose(
            tolerance,
            expected_tolerance,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise ValueError("raster diagram connector tolerance differs")
        if (
            _node_boundary_distance(page_points[0], source_node.node) > tolerance
            or _node_boundary_distance(page_points[-1], target_node.node) > tolerance
        ):
            raise ValueError("raster diagram connector endpoints differ")
        require_unique_endpoint_owner(pixel_points[0], source_node_source_id)
        require_unique_endpoint_owner(pixel_points[-1], target_node_source_id)
        for candidate in node_candidates:
            if candidate.source_object_id in {
                source_node_source_id,
                target_node_source_id,
            }:
                continue
            candidate_pixel_box = node_pixel_boxes[candidate.source_object_id]
            if any(
                _segment_enters_box_interior(first, second, candidate.node.page_bbox)
                for first, second in pairwise(page_points)
            ) or any(
                _segment_enters_box_interior(first, second, candidate_pixel_box)
                for first, second in pairwise(pixel_points)
            ):
                raise ValueError("raster diagram connector crosses a non-endpoint node")
        arrow = _exact_object(
            raw_connector.get("arrowhead"),
            {
                "source_object_id",
                "page_bbox",
                "raster_pixel_bbox",
                "tip",
                "raster_tip",
            },
            label="arrowhead",
        )
        arrow_id = _raster_source_id(arrow.get("source_object_id"))
        if arrow_id in source_object_ids:
            raise ValueError("raster diagram source identity repeats")
        source_object_ids.add(arrow_id)
        arrow_page_box = _bbox(arrow.get("page_bbox"), unit=unit)
        arrow_pixel_box = _bbox(arrow.get("raster_pixel_bbox"), unit="px")
        _require_box_transform(arrow_page_box, arrow_pixel_box, matrix)
        if not _inside(page_box, arrow_page_box) or not _inside(
            pixel_box, arrow_pixel_box
        ):
            raise ValueError("raster diagram arrowhead leaves its source owner")
        arrow_tip = _point(arrow.get("tip"))
        raster_tip = _point(arrow.get("raster_tip"))
        mapped_tip = _transform_point(raster_tip, matrix)
        if (
            not math.isclose(arrow_tip[0], mapped_tip[0], rel_tol=1e-9, abs_tol=1e-6)
            or not math.isclose(arrow_tip[1], mapped_tip[1], rel_tol=1e-9, abs_tol=1e-6)
            or math.dist(arrow_tip, page_points[-1]) > tolerance
            or math.dist(raster_tip, pixel_points[-1])
            > tolerance / min(matrix[0], matrix[3])
            or not (
                arrow_page_box.x - tolerance
                <= arrow_tip[0]
                <= arrow_page_box.x + arrow_page_box.width + tolerance
                and arrow_page_box.y - tolerance
                <= arrow_tip[1]
                <= arrow_page_box.y + arrow_page_box.height + tolerance
            )
        ):
            raise ValueError("raster diagram arrowhead geometry differs")

        path_evidence_id = _stable_id(
            "visual-evidence", structure.region.id, "raster-path", connector_source_id
        )
        source_endpoint_id = _stable_id(
            "visual-evidence", structure.region.id, "raster-source-endpoint", connector_source_id
        )
        target_endpoint_id = _stable_id(
            "visual-evidence", structure.region.id, "raster-target-endpoint", connector_source_id
        )
        direction_evidence_id = _stable_id(
            "visual-evidence", structure.region.id, "raster-direction", connector_source_id
        )
        connector_evidence_ids = [
            path_evidence_id,
            source_endpoint_id,
            target_endpoint_id,
            direction_evidence_id,
        ]
        evidence.extend(
            (
                VisualEvidence(
                    id=path_evidence_id,
                    kind="path",
                    page_bbox=path_page_box,
                    raster_pixel_bbox=path_pixel_box,
                    transform_ids=[transform_id],
                    provenance=provenance(
                        source_object_ids=[connector_source_id]
                    ),
                ),
                VisualEvidence(
                    id=source_endpoint_id,
                    kind="point",
                    page_bbox=_point_box(page_points[0], unit=unit),
                    raster_pixel_bbox=_point_box(pixel_points[0], unit="px"),
                    transform_ids=[transform_id],
                    provenance=provenance(
                        source_object_ids=[connector_source_id, source_node_source_id]
                    ),
                ),
                VisualEvidence(
                    id=target_endpoint_id,
                    kind="point",
                    page_bbox=_point_box(page_points[-1], unit=unit),
                    raster_pixel_bbox=_point_box(pixel_points[-1], unit="px"),
                    transform_ids=[transform_id],
                    provenance=provenance(
                        source_object_ids=[connector_source_id, target_node_source_id]
                    ),
                ),
                VisualEvidence(
                    id=direction_evidence_id,
                    kind="connector",
                    page_bbox=arrow_page_box,
                    raster_pixel_bbox=arrow_pixel_box,
                    transform_ids=[transform_id],
                    provenance=provenance(
                        source_object_ids=[connector_source_id, arrow_id]
                    ),
                ),
            )
        )
        connector_label_id: str | None = None
        if "label" in raw_connector:
            connector_label, connector_label_record = parse_label(
                raw_connector.get("label"),
                role="connector",
                source_identity=connector_source_id,
                owner_page_box=None,
                owner_pixel_box=None,
            )
            if any(
                _inside(candidate.node.page_bbox, connector_label.page_bbox)
                for candidate in node_candidates
                if connector_label.page_bbox is not None
            ):
                raise ValueError("raster diagram connector label is node-owned")
            connector_label_id = connector_label.id
            connector_evidence_ids.append(connector_label_record.id)
            connector_label_claims.append((connector_index, connector_label))
        connectors.append(
            DiagramConnector(
                id=_stable_id(
                    "diagram-connector", structure.region.id, connector_source_id
                ),
                source_node_id=source_node.node.id,
                target_node_id=target_node.node.id,
                label_id=connector_label_id,
                directed=True,
                path_evidence_id=path_evidence_id,
                endpoint_evidence_ids=[source_endpoint_id, target_endpoint_id],
                direction_evidence_id=direction_evidence_id,
                evidence_ids=connector_evidence_ids,
                confidence=VisualConfidenceDimensions(
                    geometry=_confidence(raw_connector.get("confidence")),
                    direction=_confidence(
                        raw_connector.get("direction_confidence")
                    ),
                ),
            )
        )
        connector_paths.append(page_points)
        connector_component_ids.append(component_index)
        connector_source_ids.append(source_node_source_id)

    if component_indexes != set(range(1, len(component_indexes) + 1)):
        raise ValueError("raster diagram connector component indexes differ")
    for component_index in component_indexes:
        members = [
            index
            for index, value in enumerate(connector_component_ids)
            if value == component_index
        ]
        if len({connector_source_ids[index] for index in members}) != 1:
            raise ValueError("raster diagram connector component source differs")
        reached = {members[0]}
        pending = [members[0]]
        while pending:
            current = pending.pop()
            for candidate in members:
                if candidate not in reached and _paths_touch(
                    connector_paths[current], connector_paths[candidate]
                ):
                    reached.add(candidate)
                    pending.append(candidate)
        if reached != set(members):
            raise ValueError("raster diagram connector component is disconnected")
    if any(
        connector_component_ids[first_index]
        != connector_component_ids[second_index]
        and _paths_touch(first, second)
        for first_index, first in enumerate(connector_paths)
        for second_index, second in enumerate(connector_paths)
        if second_index > first_index
    ):
        raise ValueError("raster diagram connector component ownership differs")
    if any(
        _paths_cross(first, second)
        for first_index, first in enumerate(connector_paths)
        for second in connector_paths[first_index + 1 :]
    ):
        raise ValueError("raster diagram connector paths cross ambiguously")
    for owner_index, connector_label in connector_label_claims:
        assert connector_label.page_bbox is not None
        label_box = connector_label.page_bbox
        center = (
            label_box.x + label_box.width / 2.0,
            label_box.y + label_box.height / 2.0,
        )
        distances = [
            _point_path_distance(center, path) for path in connector_paths
        ]
        owned_distance = distances[owner_index]
        competing = [
            distance
            for index, distance in enumerate(distances)
            if index != owner_index
        ]
        if (
            owned_distance
            > max(label_box.width, label_box.height, 1.0) * 4.0
            or any(
                math.isclose(
                    owned_distance,
                    distance,
                    rel_tol=1e-6,
                    abs_tol=1e-6,
                )
                for distance in competing
            )
            or (competing and owned_distance > min(competing))
        ):
            raise ValueError("raster diagram connector label corridor is ambiguous")

    accounting = _exact_object(
        raw.get("accounting"),
        {
            "node_count",
            "connector_component_count",
            "connector_count",
            "arrowhead_count",
            "detail_count",
            "unowned_topology_component_count",
        },
        label="accounting",
    )
    expected_accounting = {
        "node_count": len(node_candidates),
        "connector_component_count": len(component_indexes),
        "connector_count": len(connectors),
        "arrowhead_count": len(connectors),
        "detail_count": detail_count,
        "unowned_topology_component_count": 0,
    }
    if accounting != expected_accounting:
        raise ValueError("raster diagram topology accounting differs")
    if owned_token_ids != selected_primary_token_ids:
        raise ValueError("raster diagram selected OCR token coverage differs")

    all_labels = [*structure.labels[:occurrence_offset], *labels]
    markdown, caption_occurrences = _build_raster_markdown(
        item,
        all_labels,
        [candidate.node for candidate in node_candidates],
        connectors,
    )
    return _RasterGraphProjection(
        transform=transform,
        region_evidence_id=region_evidence_id,
        labels=tuple(labels),
        nodes=tuple(candidate.node for candidate in node_candidates),
        connectors=tuple(connectors),
        evidence=tuple(evidence),
        markdown=markdown,
        caption_occurrences=caption_occurrences,
    )


def _build_markdown(
    item: Mapping[str, Any],
    structure: VisualStructure,
    nodes: Sequence[DiagramNode],
    connectors: Sequence[DiagramConnector],
) -> tuple[str, int]:
    labels = {label.id: label.text for label in structure.labels}
    node_names = {
        node.id: (
            labels[node.label_id] if node.label_id is not None else f"Node {index}"
        )
        for index, node in enumerate(nodes, start=1)
    }
    raw_caption = item.get("caption")
    caption = raw_caption.strip() if isinstance(raw_caption, str) else ""
    lines: list[str] = []
    if caption:
        lines.extend((_markdown_text(caption), ""))
    lines.append("### Nodes")
    for node in nodes:
        lines.append(
            f"- {_markdown_text(node_names[node.id])} ({node.shape})"
        )
    lines.extend(
        (
            "",
            "### Connections",
            "| Source | Direction | Target |",
            "| --- | :---: | --- |",
        )
    )
    for connector in connectors:
        lines.append(
            "| "
            + " | ".join(
                (
                    _markdown_text(node_names[connector.source_node_id]),
                    "→",
                    _markdown_text(node_names[connector.target_node_id]),
                )
            )
            + " |"
        )
    markdown = "\n".join(lines)
    if len(markdown.encode("utf-8")) > 262_144:
        raise ValueError("diagram topology Markdown exceeds its public limit")
    return markdown, 1 if caption else 0


def _commit_raster_projection(
    structure: VisualStructure,
    projection: _RasterGraphProjection,
) -> VisualStructure:
    if structure.nodes or structure.connectors or not structure.fallback.active:
        raise ValueError("raster diagram predecessor is not a clean fallback")
    payload = structure.model_dump(mode="json", exclude_none=True)
    if projection.transform.id in {value["id"] for value in payload["transforms"]}:
        raise ValueError("raster diagram transform identity repeats")
    payload["transforms"].append(
        projection.transform.model_dump(mode="json", exclude_none=True)
    )
    payload["region"]["evidence_ids"].append(projection.region_evidence_id)
    payload["labels"].extend(
        label.model_dump(mode="json", exclude_none=True)
        for label in projection.labels
    )
    payload["nodes"] = [
        node.model_dump(mode="json", exclude_none=True)
        for node in projection.nodes
    ]
    payload["connectors"] = [
        connector.model_dump(mode="json", exclude_none=True)
        for connector in projection.connectors
    ]
    payload["evidence"].extend(
        record.model_dump(mode="json", exclude_none=True)
        for record in projection.evidence
    )
    payload["concerns"] = [
        concern
        for concern in payload.get("concerns", [])
        if concern.get("code") != "diagram_topology_unresolved"
    ]
    payload["fallback"] = VisualFallback(
        active=False,
        reason="none",
        predecessor_concern="diagram_relationships_not_structured",
    ).model_dump(mode="json", exclude_none=True)
    payload["serialization"] = VisualSerialization(
        status="diagram_topology",
        markdown=projection.markdown,
        caption_occurrences=projection.caption_occurrences,
        row_count=len(projection.connectors),
    ).model_dump(mode="json", exclude_none=True)
    return VisualStructure.model_validate(payload)


def validate_raster_diagram_item_contract(
    item: Mapping[str, Any],
    structure: VisualStructure,
) -> None:
    """Independently replay an authoritative raster graph from raw custody."""

    raw = _raw_raster_evidence(item)
    if raw is None:
        if (
            any(
                record.provenance.extraction_method == "raster"
                for record in structure.evidence
            )
            or any(node.detail_label_ids for node in structure.nodes)
            or any(connector.label_id is not None for connector in structure.connectors)
        ):
            raise ValueError("authoritative raster diagram source evidence is absent")
        return
    # Raw evidence can be staged transiently beneath a fallback before the
    # atomic topology commit.  It carries no public authority in that state.
    if structure.fallback.active:
        if any(
            record.provenance.extraction_method == "raster"
            for record in structure.evidence
        ):
            raise ValueError("fallback diagram carries raster semantic authority")
        return
    raw_node_values = raw.get("nodes")
    raw_connector_values = raw.get("connectors")
    if type(raw_node_values) is not list or type(raw_connector_values) is not list:
        raise ValueError("authoritative raster diagram raw graph differs")
    expected_label_count = sum(
        1 + len(node.get("details", []))
        for node in raw_node_values
        if type(node) is dict and type(node.get("details")) is list
    ) + sum(
        1
        for connector in raw_connector_values
        if type(connector) is dict and "label" in connector
    )
    if expected_label_count <= 0 or len(structure.labels) < expected_label_count:
        raise ValueError("authoritative raster diagram label coverage differs")
    base_label_count = len(structure.labels) - expected_label_count
    region_provenance = structure.evidence[0].provenance
    projection = _raster_graph_projection(
        item,
        structure,
        raw,
        page_index=region_provenance.page_index,
        input_kind=region_provenance.input_kind,
        label_occurrence_offset=base_label_count,
    )
    expected_labels = list(projection.labels)
    actual_labels = structure.labels[base_label_count:]
    if actual_labels != expected_labels:
        raise ValueError("authoritative raster diagram labels differ")
    expected_label_ids = {label.id for label in expected_labels}
    if {
        label.id
        for label in structure.labels
        if label.role in {"node_detail", "connector"}
    } != {
        label.id
        for label in expected_labels
        if label.role in {"node_detail", "connector"}
    }:
        raise ValueError("authoritative raster diagram semantic label ownership differs")
    if structure.nodes != list(projection.nodes):
        raise ValueError("authoritative raster diagram nodes differ")
    if structure.connectors != list(projection.connectors):
        raise ValueError("authoritative raster diagram connectors differ")
    referenced_detail_ids = [
        label_id for node in structure.nodes for label_id in node.detail_label_ids
    ]
    referenced_connector_ids = [
        connector.label_id
        for connector in structure.connectors
        if connector.label_id is not None
    ]
    if (
        len(referenced_detail_ids) != len(set(referenced_detail_ids))
        or len(referenced_connector_ids) != len(set(referenced_connector_ids))
        or set(referenced_detail_ids + referenced_connector_ids)
        != {
            label.id
            for label in expected_labels
            if label.role in {"node_detail", "connector"}
        }
    ):
        raise ValueError("authoritative raster diagram label ownership repeats")
    actual_raster_evidence = [
        record
        for record in structure.evidence
        if record.provenance.extraction_method == "raster"
    ]
    if actual_raster_evidence != list(projection.evidence):
        raise ValueError("authoritative raster diagram evidence differs")
    transform = next(
        (value for value in structure.transforms if value.id == projection.transform.id),
        None,
    )
    if transform != projection.transform:
        raise ValueError("authoritative raster diagram transform differs")
    if structure.region.evidence_ids.count(projection.region_evidence_id) != 1:
        raise ValueError("authoritative raster diagram region evidence differs")
    serialization = structure.serialization
    if (
        serialization is None
        or serialization.status != "diagram_topology"
        or serialization.markdown != projection.markdown
        or serialization.caption_occurrences != projection.caption_occurrences
        or serialization.row_count != len(projection.connectors)
        or item.get("value") != projection.markdown
        or item.get("md") != projection.markdown
        or not expected_label_ids
    ):
        raise ValueError("authoritative raster diagram serialization differs")


def structure_diagram_topology(
    item: Mapping[str, Any],
    structure: VisualStructure,
    *,
    page_index: int,
    input_kind: Any,
    source_pdf_bytes: bytes | None = None,
) -> VisualStructure:
    """Admit only explicit, direction-grounded simple diagram topology."""

    if structure.region.kind != "diagram":
        raise ValueError("diagram topology requires a diagram structure")
    raw_input_kind = getattr(input_kind, "value", input_kind)
    normalized_input_kind: Literal["pdf", "image", "unknown"] = (
        raw_input_kind if raw_input_kind in {"pdf", "image"} else "unknown"
    )
    try:
        raster_raw = _raw_raster_evidence(item)
        if raster_raw is not None:
            ensure_finite_mapping(raster_raw)
            projection = _raster_graph_projection(
                item,
                structure,
                raster_raw,
                page_index=page_index,
                input_kind=normalized_input_kind,
            )
            return _commit_raster_projection(structure, projection)
    except (MemoryError, OverflowError, RecursionError, TypeError, ValueError):
        # Raster graphs are all-or-nothing.  Unlike the established vector
        # branch below, no partial nodes or clean-neighbor edges survive a
        # failed raw-source/accounting/serialization replay.
        return _append_concerns(
            structure,
            ["diagram_raster_topology_failed_closed"],
        )
    raw = _raw_evidence(item)
    if raw is None and normalized_input_kind == "pdf" and source_pdf_bytes:
        try:
            raw = extract_pdf_diagram_topology_evidence(
                source_pdf_bytes,
                structure,
                page_index=page_index,
            )
        except Exception:
            # PDF parsers expose backend-specific syntax/IO exception classes;
            # none may escape this optional, item-local producer boundary.
            return _append_concerns(
                structure,
                ["diagram_topology_source_failed_closed"],
            )
    if raw is None:
        return _append_concerns(
            structure,
            ["diagram_topology_evidence_unavailable"],
        )
    if not isinstance(raw, Mapping):
        return _append_concerns(
            structure,
            ["diagram_topology_evidence_malformed"],
        )
    try:
        ensure_finite_mapping(raw)
        if set(raw) != {"nodes", "connectors"}:
            raise ValueError("diagram topology evidence fields differ")
        raw_nodes = _sequence(raw.get("nodes"), label="nodes", maximum=_MAX_NODES)
        raw_connectors = _sequence(
            raw.get("connectors"),
            label="connectors",
            maximum=_MAX_CONNECTORS,
        )
    except (TypeError, ValueError):
        return _append_concerns(
            structure,
            ["diagram_topology_evidence_malformed"],
        )

    unit: Literal["pt", "px"] = structure.region.page_bbox.unit
    public_item_id = structure.evidence[0].provenance.public_item_id
    labels = _label_source_map(structure)
    node_candidates: list[_NodeCandidate] = []
    nodes_by_source: dict[str, _NodeCandidate] = {}
    staged_evidence: list[VisualEvidence] = []
    concerns: list[str] = []

    for raw_node in raw_nodes:
        if not isinstance(raw_node, Mapping):
            concerns.append("diagram_node_candidate_malformed")
            continue
        try:
            if set(raw_node) - {
                "source_object_id",
                "shape",
                "page_bbox",
                "label_source_token_id",
                "confidence",
            }:
                raise ValueError("diagram node fields differ")
            source_object_id = _text(raw_node.get("source_object_id"))
            if source_object_id in nodes_by_source:
                raise ValueError("diagram node source identity repeats")
            shape = str(raw_node.get("shape") or "")
            if shape not in _NODE_SHAPES:
                concerns.append("diagram_node_unsupported_shape")
                continue
            box = _bbox(raw_node.get("page_bbox"), unit=unit)
            if not _inside(structure.region.page_bbox, box):
                concerns.append("diagram_node_outside_region")
                continue
            label: VisualLabel | None = None
            raw_label_source = raw_node.get("label_source_token_id")
            if raw_label_source is not None:
                label = labels.get(_text(raw_label_source, maximum=128))
                if label is None or label.role != "node":
                    label = None
                    concerns.append("diagram_label_unresolved")
                elif label.page_bbox is None or not _inside(box, label.page_bbox):
                    label = None
                    concerns.append("diagram_label_outside_node")
            node_evidence_id = _stable_id(
                "visual-evidence",
                structure.region.id,
                "node",
                source_object_id,
            )
            node_evidence = VisualEvidence(
                id=node_evidence_id,
                kind="node",
                page_bbox=box,
                provenance=VisualProvenance(
                    public_item_id=public_item_id,
                    page_index=page_index,
                    input_kind=normalized_input_kind,
                    source_object_ids=[source_object_id],
                    extraction_method="layout",
                ),
            )
            node = DiagramNode(
                id=_stable_id(
                    "diagram-node",
                    structure.region.id,
                    source_object_id,
                ),
                shape=shape,
                label_id=label.id if label is not None else None,
                page_bbox=box,
                evidence_ids=[
                    node_evidence_id,
                    *(label.evidence_ids if label is not None else ()),
                ],
                confidence=VisualConfidenceDimensions(
                    geometry=_confidence(raw_node.get("confidence"))
                ),
            )
            candidate = _NodeCandidate(source_object_id, node, node_evidence)
            node_candidates.append(candidate)
            nodes_by_source[source_object_id] = candidate
            staged_evidence.append(node_evidence)
        except (TypeError, ValueError):
            concerns.append("diagram_node_candidate_malformed")

    connector_candidates: list[_ConnectorCandidate] = []
    connector_sources: set[str] = set()
    for raw_connector in raw_connectors:
        if not isinstance(raw_connector, Mapping):
            concerns.append("diagram_connector_candidate_malformed")
            continue
        try:
            if set(raw_connector) - {
                "source_object_id",
                "source_node_source_object_id",
                "target_node_source_object_id",
                "path_points",
                "arrowhead",
                "endpoint_tolerance",
                "crossed",
                "disconnected",
                "direction_ambiguous",
                "confidence",
                "direction_confidence",
            }:
                raise ValueError("diagram connector fields differ")
            source_object_id = _text(raw_connector.get("source_object_id"))
            if source_object_id in connector_sources:
                raise ValueError("diagram connector source identity repeats")
            connector_sources.add(source_object_id)
            if raw_connector.get("crossed") is True:
                concerns.append("diagram_connector_crossing_ambiguous")
                continue
            if raw_connector.get("disconnected") is True:
                concerns.append("diagram_connector_disconnected")
                continue
            if raw_connector.get("direction_ambiguous") is True:
                concerns.append("diagram_connector_direction_ambiguous")
                continue
            source_node_id = _text(
                raw_connector.get("source_node_source_object_id")
            )
            target_node_id = _text(
                raw_connector.get("target_node_source_object_id")
            )
            source = nodes_by_source.get(source_node_id)
            target = nodes_by_source.get(target_node_id)
            if source is None or target is None:
                concerns.append("diagram_connector_endpoint_unresolved")
                continue
            if source.node.id == target.node.id:
                concerns.append("diagram_connector_self_loop_unsupported")
                continue
            for flag_name in ("crossed", "disconnected", "direction_ambiguous"):
                if flag_name in raw_connector and not isinstance(
                    raw_connector[flag_name], bool
                ):
                    raise ValueError("diagram connector flag must be boolean")
            points = tuple(
                _point(value)
                for value in _sequence(
                    raw_connector.get("path_points"),
                    label="path points",
                    maximum=_MAX_PATH_POINTS,
                )
            )
            if len(points) < 2 or any(
                first == second for first, second in zip(points, points[1:])
            ):
                raise ValueError("diagram connector path is incomplete")
            path_box = _path_box(points, unit=unit)
            if not _inside(structure.region.page_bbox, path_box):
                concerns.append("diagram_connector_disconnected")
                continue
            tolerance = _number(raw_connector.get("endpoint_tolerance", 3.0))
            if not 0.0 <= tolerance <= 32.0:
                raise ValueError("diagram endpoint tolerance is unsupported")
            if (
                _node_boundary_distance(points[0], source.node) > tolerance
                or _node_boundary_distance(points[-1], target.node) > tolerance
            ):
                concerns.append("diagram_connector_disconnected")
                continue
            arrow = raw_connector.get("arrowhead")
            if not isinstance(arrow, Mapping) or frozenset(arrow) not in {
                frozenset({"source_object_id", "bbox", "tip"}),
                frozenset({"source_object_ids", "bbox", "tip"}),
            }:
                concerns.append("diagram_connector_direction_ambiguous")
                continue
            if "source_object_ids" in arrow:
                arrow_source_object_ids = tuple(
                    _text(value)
                    for value in _sequence(
                        arrow.get("source_object_ids"),
                        label="arrow source objects",
                        maximum=4,
                    )
                )
                if (
                    len(arrow_source_object_ids) != 2
                    or len(set(arrow_source_object_ids)) != 2
                ):
                    raise ValueError("diagram arrow source identity differs")
            else:
                arrow_source_object_ids = (
                    _text(arrow.get("source_object_id")),
                )
            arrow_box = _bbox(arrow.get("bbox"), unit=unit)
            arrow_tip = _point(arrow.get("tip"))
            if (
                not _inside(structure.region.page_bbox, arrow_box)
                or not (
                    arrow_box.x - tolerance
                    <= arrow_tip[0]
                    <= arrow_box.x + arrow_box.width + tolerance
                    and arrow_box.y - tolerance
                    <= arrow_tip[1]
                    <= arrow_box.y + arrow_box.height + tolerance
                )
                or math.dist(arrow_tip, points[-1]) > tolerance
                or _node_boundary_distance(arrow_tip, target.node) > tolerance
            ):
                concerns.append("diagram_connector_direction_ambiguous")
                continue
            if _path_crosses_itself(points):
                concerns.append("diagram_connector_crossing_ambiguous")
                continue
            connector_candidates.append(
                _ConnectorCandidate(
                    source_object_id=source_object_id,
                    source=source,
                    target=target,
                    points=points,
                    arrow_source_object_ids=arrow_source_object_ids,
                    arrow_box=arrow_box,
                    geometry_confidence=_confidence(raw_connector.get("confidence")),
                    direction_confidence=_confidence(
                        raw_connector.get("direction_confidence")
                    ),
                )
            )
        except (TypeError, ValueError):
            concerns.append("diagram_connector_candidate_malformed")

    crossing_indexes: set[int] = set()
    for first_index, first in enumerate(connector_candidates):
        for second_index in range(first_index + 1, len(connector_candidates)):
            if _paths_cross(first.points, connector_candidates[second_index].points):
                crossing_indexes.update((first_index, second_index))
    if crossing_indexes:
        concerns.append("diagram_connector_crossing_ambiguous")

    connectors: list[DiagramConnector] = []
    directed_pairs: set[tuple[str, str]] = set()
    for connector_index, candidate in enumerate(connector_candidates):
        if connector_index in crossing_indexes:
            continue
        pair = (candidate.source.node.id, candidate.target.node.id)
        if pair in directed_pairs:
            concerns.append("diagram_connector_candidate_malformed")
            continue
        directed_pairs.add(pair)
        path_evidence_id = _stable_id(
            "visual-evidence",
            structure.region.id,
            "path",
            candidate.source_object_id,
        )
        source_endpoint_id = _stable_id(
            "visual-evidence",
            structure.region.id,
            "endpoint-source",
            candidate.source_object_id,
        )
        target_endpoint_id = _stable_id(
            "visual-evidence",
            structure.region.id,
            "endpoint-target",
            candidate.source_object_id,
        )
        direction_evidence_id = _stable_id(
            "visual-evidence",
            structure.region.id,
            "direction",
            candidate.source_object_id,
        )
        connector_evidence = [
            VisualEvidence(
                id=path_evidence_id,
                kind="path",
                page_bbox=_path_box(candidate.points, unit=unit),
                provenance=VisualProvenance(
                    public_item_id=public_item_id,
                    page_index=page_index,
                    input_kind=normalized_input_kind,
                    source_object_ids=[candidate.source_object_id],
                    extraction_method="layout",
                ),
            ),
            VisualEvidence(
                id=source_endpoint_id,
                kind="point",
                page_bbox=_point_box(candidate.points[0], unit=unit),
                provenance=VisualProvenance(
                    public_item_id=public_item_id,
                    page_index=page_index,
                    input_kind=normalized_input_kind,
                    source_object_ids=sorted(
                        [candidate.source_object_id, candidate.source.source_object_id]
                    ),
                    extraction_method="layout",
                ),
            ),
            VisualEvidence(
                id=target_endpoint_id,
                kind="point",
                page_bbox=_point_box(candidate.points[-1], unit=unit),
                provenance=VisualProvenance(
                    public_item_id=public_item_id,
                    page_index=page_index,
                    input_kind=normalized_input_kind,
                    source_object_ids=sorted(
                        [candidate.source_object_id, candidate.target.source_object_id]
                    ),
                    extraction_method="layout",
                ),
            ),
            VisualEvidence(
                id=direction_evidence_id,
                kind="connector",
                page_bbox=candidate.arrow_box,
                provenance=VisualProvenance(
                    public_item_id=public_item_id,
                    page_index=page_index,
                    input_kind=normalized_input_kind,
                    source_object_ids=sorted(
                        [
                            *candidate.arrow_source_object_ids,
                            candidate.source_object_id,
                        ]
                    ),
                    extraction_method="layout",
                ),
            ),
        ]
        evidence_ids = [record.id for record in connector_evidence]
        connectors.append(
            DiagramConnector(
                id=_stable_id(
                    "diagram-connector",
                    structure.region.id,
                    candidate.source_object_id,
                ),
                source_node_id=candidate.source.node.id,
                target_node_id=candidate.target.node.id,
                directed=True,
                path_evidence_id=path_evidence_id,
                endpoint_evidence_ids=[source_endpoint_id, target_endpoint_id],
                direction_evidence_id=direction_evidence_id,
                evidence_ids=evidence_ids,
                confidence=VisualConfidenceDimensions(
                    geometry=candidate.geometry_confidence,
                    direction=candidate.direction_confidence,
                ),
            )
        )
        staged_evidence.extend(connector_evidence)

    payload = structure.model_dump(mode="json", exclude_none=True)
    payload["nodes"] = [
        candidate.node.model_dump(mode="json", exclude_none=True)
        for candidate in node_candidates
    ]
    payload["connectors"] = [
        connector.model_dump(mode="json", exclude_none=True)
        for connector in connectors
    ]
    payload["evidence"] = [
        *payload["evidence"],
        *(
            record.model_dump(mode="json", exclude_none=True)
            for record in staged_evidence
        ),
    ]
    payload["concerns"] = [
        concern
        for concern in payload.get("concerns", [])
        if not connectors or concern.get("code") != "diagram_topology_unresolved"
    ]
    try:
        # Fallback diagrams may retain admitted nodes, but the contract does
        # not permit connector candidates before the complete authoritative
        # topology and its serialization are committed together.
        payload["connectors"] = []
        staged = _append_concerns(
            VisualStructure.model_validate(payload),
            concerns,
        )
        if not connectors:
            return staged
        markdown, caption_occurrences = _build_markdown(
            item,
            structure,
            [candidate.node for candidate in node_candidates],
            connectors,
        )
        payload = staged.model_dump(mode="json", exclude_none=True)
        payload["connectors"] = [
            connector.model_dump(mode="json", exclude_none=True)
            for connector in connectors
        ]
        payload["fallback"] = VisualFallback(
            active=False,
            reason="none",
            predecessor_concern="diagram_relationships_not_structured",
        ).model_dump(mode="json", exclude_none=True)
        payload["serialization"] = VisualSerialization(
            status="diagram_topology",
            markdown=markdown,
            caption_occurrences=caption_occurrences,
            row_count=len(connectors),
        ).model_dump(mode="json", exclude_none=True)
        return VisualStructure.model_validate(payload)
    except (MemoryError, TypeError, ValueError):
        return _append_concerns(
            structure,
            ["diagram_topology_serialization_failed_closed"],
        )


__all__ = [
    "extract_pdf_diagram_topology_evidence",
    "structure_diagram_topology",
    "validate_raster_diagram_item_contract",
]
