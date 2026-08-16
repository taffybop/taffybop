"""Bounded source-raster evidence for rectangular flow diagrams.

This module owns the narrow raster-only producer used after the existing
diagram/vector evidence seams decline a visual.  Public items are never
mutated in place: one detected source owner is proved first, then a copied
item may be staged on that owner's complete bbox.  Any malformed, ambiguous,
partial, or over-budget input returns ``None``.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import time
from collections import deque
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Literal

from PIL import Image, UnidentifiedImageError

_MAX_DETECTED_OWNERS = 256
_MAX_PAGE_ITEMS = 4_096
_MAX_OCR_LINES = 512
_MAX_OCR_TOKENS = 4_096
_MAX_TEXT_CODEPOINTS = 262_144
_MAX_PIXEL_EDGE = 16_384
_MAX_PIXEL_COUNT = 32_000_000
_MAX_TREE_DEPTH = 12
_MAX_TREE_NODES = 65_536
_MAX_TREE_TEXT_BYTES = 8_388_608
_MIN_RECIPROCAL_COVERAGE = 0.95
_MAX_MAPPING_TOLERANCE_RATIO = 0.015
_MIN_MAPPING_TOLERANCE = 1.5
_PDF_ANALYSIS_PIXELS_PER_POINT = 3.0
_MAX_ANALYSIS_EDGE = 4_096
_MAX_ANALYSIS_PIXELS = 8_388_608
_MAX_RASTER_NODES = 128
_MAX_RASTER_CONNECTORS = 256
_MAX_PATH_POINTS = 64
_MAX_ANALYSIS_SECONDS = 5.0
_MAX_SOURCE_BYTES = 134_217_728
_MAX_LABEL_CODEPOINTS = 1_024
_MAX_LABEL_BYTES = 4_096
_UNSAFE_LABEL_CHARACTERS = frozenset(
    {
        "\u2028",
        "\u2029",
        "\u202a",
        "\u202b",
        "\u202c",
        "\u202d",
        "\u202e",
        "\u2066",
        "\u2067",
        "\u2068",
        "\u2069",
    }
)


class _Refusal(ValueError):
    """One item-local raster proof cannot be admitted."""


@dataclass(frozen=True, slots=True)
class _Box:
    x: float
    y: float
    width: float
    height: float
    unit: Literal["pt", "px"]

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def area(self) -> float:
        return self.width * self.height

    def public(self) -> dict[str, Any]:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "unit": self.unit,
        }


@dataclass(frozen=True, slots=True)
class RasterDiagramOwnerBinding:
    """One exact, page-local source raster claim and its staged item copy."""

    owner_id: str
    owner_index: int
    item: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _RasterLabel:
    text: str
    page_box: _Box
    source_pixel_box: _Box
    analysis_box: tuple[int, int, int, int]
    source_token_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _RasterNode:
    identifier: str
    analysis_box: tuple[int, int, int, int]
    source_pixel_box: _Box
    page_box: _Box
    label: _RasterLabel
    details: tuple[tuple[_RasterLabel, tuple[int, int, int, int]], ...]


@dataclass(frozen=True, slots=True)
class _RasterArrow:
    identifier: str
    component_index: int
    analysis_box: tuple[int, int, int, int]
    target_index: int


@dataclass(frozen=True, slots=True)
class _RasterPath:
    identifier: str
    component_index: int
    source_index: int
    target_index: int
    analysis_points: tuple[tuple[float, float], ...]
    arrow: _RasterArrow
    label: _RasterLabel | None = None


@dataclass(frozen=True, slots=True)
class _BulletClaim:
    analysis_box: tuple[int, int, int, int]
    source_token_ids: tuple[str, ...]
    detail_line_id: str
    reading_direction: Literal["right", "left", "down", "up"]


@dataclass(frozen=True, slots=True)
class _TokenRecord:
    identifier: str
    line_identifier: str
    text: str
    word_index: int
    page_box: _Box
    analysis_box: tuple[int, int, int, int]


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _Refusal("raster diagram geometry is non-numeric")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise _Refusal("raster diagram geometry is non-finite") from exc
    if not math.isfinite(result):
        raise _Refusal("raster diagram geometry is non-finite")
    return result


def _positive_int(value: Any, *, maximum: int) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1 <= value <= maximum
    ):
        raise _Refusal("raster diagram pixel dimension is invalid")
    return value


def _text(value: Any, *, maximum: int = _MAX_TEXT_CODEPOINTS) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise _Refusal("raster diagram text is invalid")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise _Refusal("raster diagram text is not valid UTF-8") from exc
    return value


def _visual_label_component(value: Any) -> str:
    """Validate one OCR line/token before it can become diagram text.

    OCR line and token records are single-line source components.  Multiline
    node labels are reconstructed from separately grounded lines later; a
    control character inside either source component is therefore malformed,
    not a formatting instruction.  This is intentionally stricter than the
    final typed label contract, which can represent normalized line breaks
    from other trusted producers.
    """

    result = _text(value, maximum=_MAX_LABEL_CODEPOINTS)
    encoded = result.encode("utf-8", errors="strict")
    if (
        len(encoded) > _MAX_LABEL_BYTES
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in result)
        or any(character in _UNSAFE_LABEL_CHARACTERS for character in result)
    ):
        raise _Refusal("raster diagram visual label text is unsafe")
    return result


def _validated_visual_label(value: str) -> str:
    """Apply the public label bound after token/line aggregation."""

    return _visual_label_component(value)


def _identifier(value: Any) -> str:
    result = _text(value, maximum=128)
    if not result or result.strip() != result:
        raise _Refusal("raster diagram identity is invalid")
    return result


def _sequence(value: Any, *, maximum: int, label: str) -> list[Any]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or len(value) > maximum
    ):
        raise _Refusal(f"raster diagram {label} is unbounded")
    return list(value)


def _validate_bounded_tree(
    value: Any,
    *,
    depth: int = 0,
    nodes: list[int] | None = None,
    text_bytes: list[int] | None = None,
) -> None:
    """Reject hostile public projections before deepcopy/JSON materialization."""

    if nodes is None:
        nodes = [_MAX_TREE_NODES]
    if text_bytes is None:
        text_bytes = [_MAX_TREE_TEXT_BYTES]
    if depth > _MAX_TREE_DEPTH or nodes[0] <= 0:
        raise _Refusal("raster diagram evidence exceeds its structural bound")
    nodes[0] -= 1
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        if value.bit_length() > 1_024:
            raise _Refusal("raster diagram integer exceeds its bound")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _Refusal("raster diagram evidence contains non-finite data")
        return
    if isinstance(value, str):
        try:
            encoded = value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise _Refusal("raster diagram evidence text is invalid") from exc
        text_bytes[0] -= len(encoded)
        if text_bytes[0] < 0:
            raise _Refusal("raster diagram evidence text exceeds its byte bound")
        return
    if isinstance(value, Mapping):
        if len(value) > 2_048:
            raise _Refusal("raster diagram evidence mapping is unbounded")
        for key, member in value.items():
            if not isinstance(key, str) or len(key) > 256:
                raise _Refusal("raster diagram evidence key is invalid")
            _validate_bounded_tree(
                member,
                depth=depth + 1,
                nodes=nodes,
                text_bytes=text_bytes,
            )
        return
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        if len(value) > 8_192:
            raise _Refusal("raster diagram evidence sequence is unbounded")
        for member in value:
            _validate_bounded_tree(
                member,
                depth=depth + 1,
                nodes=nodes,
                text_bytes=text_bytes,
            )
        return
    raise _Refusal("raster diagram evidence value type is unsupported")


def _box(value: Any, *, default_unit: str) -> _Box:
    if not isinstance(value, Mapping):
        raise _Refusal("raster diagram bbox is unavailable")
    allowed = {"x", "y", "width", "height", "w", "h", "unit"}
    if set(value) - allowed:
        raise _Refusal("raster diagram bbox fields differ")
    width = _number(value.get("width", value.get("w")))
    height = _number(value.get("height", value.get("h")))
    if "width" in value and "w" in value and _number(value["w"]) != width:
        raise _Refusal("raster diagram bbox width aliases differ")
    if "height" in value and "h" in value and _number(value["h"]) != height:
        raise _Refusal("raster diagram bbox height aliases differ")
    unit = str(value.get("unit") or default_unit)
    if unit not in {"pt", "px"}:
        raise _Refusal("raster diagram bbox unit differs")
    result = _Box(
        x=_number(value.get("x")),
        y=_number(value.get("y")),
        width=width,
        height=height,
        unit=unit,  # type: ignore[arg-type]
    )
    if min(result.x, result.y) < 0 or result.width <= 0 or result.height <= 0:
        raise _Refusal("raster diagram bbox has invalid area")
    return result


def _coverage(first: _Box, second: _Box) -> tuple[float, float]:
    if first.unit != second.unit:
        return 0.0, 0.0
    width = max(min(first.right, second.right) - max(first.x, second.x), 0.0)
    height = max(min(first.bottom, second.bottom) - max(first.y, second.y), 0.0)
    intersection = width * height
    return intersection / first.area, intersection / second.area


def _mapping_tolerance(owner: _Box) -> tuple[float, float]:
    return (
        max(_MIN_MAPPING_TOLERANCE, owner.width * _MAX_MAPPING_TOLERANCE_RATIO),
        max(_MIN_MAPPING_TOLERANCE, owner.height * _MAX_MAPPING_TOLERANCE_RATIO),
    )


def _near_contained(layout: _Box, owner: _Box) -> bool:
    if layout.unit != owner.unit:
        return False
    tolerance_x, tolerance_y = _mapping_tolerance(owner)
    layout_coverage, owner_coverage = _coverage(layout, owner)
    return (
        layout.x >= owner.x - tolerance_x
        and layout.y >= owner.y - tolerance_y
        and layout.right <= owner.right + tolerance_x
        and layout.bottom <= owner.bottom + tolerance_y
        and layout_coverage >= _MIN_RECIPROCAL_COVERAGE
        and owner_coverage >= _MIN_RECIPROCAL_COVERAGE
    )


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise _Refusal("raster diagram evidence is not canonical JSON") from exc


def _stable(prefix: str, *parts: Any) -> str:
    return (
        f"{prefix}-"
        + hashlib.sha256(_canonical(parts).encode("utf-8")).hexdigest()[:24]
    )


def _same_box(first: _Box, second: _Box, *, tolerance: float = 1e-3) -> bool:
    return first.unit == second.unit and all(
        abs(left - right) <= tolerance
        for left, right in (
            (first.x, second.x),
            (first.y, second.y),
            (first.width, second.width),
            (first.height, second.height),
        )
    )


def _owner_proof(binding: RasterDiagramOwnerBinding) -> dict[str, Any]:
    item = binding.item
    raw_meta = item.get("meta")
    proof = (
        raw_meta.get("phase05_raster_diagram_owner")
        if isinstance(raw_meta, Mapping)
        else None
    )
    expected = {
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
    if (
        not isinstance(proof, Mapping)
        or set(proof) != expected
        or proof.get("schema_version") != "1.0"
        or proof.get("owner_id") != binding.owner_id
        or not isinstance(proof.get("ocr_ledger_sha256"), str)
        or len(str(proof.get("ocr_ledger_sha256"))) != 64
    ):
        raise _Refusal("raster diagram owner proof differs")
    detected = _box(proof.get("detected_bbox"), default_unit="pt")
    item_box = _box(item.get("bbox"), default_unit=detected.unit)
    if not _same_box(detected, item_box):
        raise _Refusal("raster diagram staged owner bbox differs")
    return deepcopy(dict(proof))


def _load_bound_raster(
    binding: RasterDiagramOwnerBinding,
    source_document_bytes: bytes,
    *,
    page_index: int,
    input_kind: str,
) -> tuple[Image.Image, _Box, int, int]:
    proof = _owner_proof(binding)
    if (
        not source_document_bytes
        or proof.get("page_index") != page_index
        or proof.get("input_kind") != input_kind
    ):
        raise _Refusal("raster diagram source custody differs")
    owner = _box(proof["detected_bbox"], default_unit="pt")
    pixel_width = _positive_int(proof.get("pixel_width"), maximum=_MAX_PIXEL_EDGE)
    pixel_height = _positive_int(proof.get("pixel_height"), maximum=_MAX_PIXEL_EDGE)
    if pixel_width * pixel_height > _MAX_PIXEL_COUNT:
        raise _Refusal("raster diagram source pixels exceed their bound")

    if input_kind == "image":
        try:
            with Image.open(io.BytesIO(source_document_bytes)) as opened:
                frame_count = int(getattr(opened, "n_frames", 1) or 1)
                frame = page_index - 1 if frame_count > 1 else 0
                if frame >= frame_count:
                    raise _Refusal("raster diagram image frame is unavailable")
                opened.seek(frame)
                if owner.unit != "px":
                    raise _Refusal("direct raster diagram owner unit differs")
                left, top, right, bottom = (
                    round(owner.x),
                    round(owner.y),
                    round(owner.right),
                    round(owner.bottom),
                )
                if (
                    min(left, top) < 0
                    or right > opened.width
                    or bottom > opened.height
                    or any(
                        abs(left_value - right_value) > 1e-6
                        for left_value, right_value in (
                            (left, owner.x),
                            (top, owner.y),
                            (right, owner.right),
                            (bottom, owner.bottom),
                        )
                    )
                    or right - left != pixel_width
                    or bottom - top != pixel_height
                ):
                    raise _Refusal("direct raster diagram crop identity differs")
                return (
                    opened.crop((left, top, right, bottom)).convert("RGB"),
                    owner,
                    pixel_width,
                    pixel_height,
                )
        except (OSError, UnidentifiedImageError) as exc:
            raise _Refusal("direct raster diagram cannot be decoded") from exc

    if input_kind != "pdf" or owner.unit != "pt":
        raise _Refusal("raster diagram source kind is unsupported")
    try:
        import pypdfium2 as pdfium
        from pypdfium2 import raw as pdfium_raw

        document: Any | None = None
        page: Any | None = None
        images: list[Any] = []
        bitmap: Any | None = None
        try:
            document = pdfium.PdfDocument(source_document_bytes)
            if not 1 <= page_index <= len(document):
                raise _Refusal("raster diagram PDF page is unavailable")
            page = document[page_index - 1]
            page_width, page_height = (float(value) for value in page.get_size())
            images = list(page.get_objects(filter=(pdfium_raw.FPDF_PAGEOBJ_IMAGE,)))
            candidates: list[Any] = []
            for image in images:
                left, bottom, right, top = (
                    float(value) for value in image.get_bounds()
                )
                box = _Box(
                    x=left,
                    y=page_height - top,
                    width=right - left,
                    height=top - bottom,
                    unit="pt",
                )
                width, height = (int(value) for value in image.get_px_size())
                matrix = image.get_matrix()
                if (
                    _same_box(box, owner, tolerance=1e-3)
                    and (width, height) == (pixel_width, pixel_height)
                    and abs(float(matrix.b)) <= 1e-6
                    and abs(float(matrix.c)) <= 1e-6
                    and float(matrix.a) > 0
                    and float(matrix.d) > 0
                    and 0 <= box.x < page_width
                    and 0 <= box.y < page_height
                ):
                    candidates.append(image)
            if len(candidates) != 1:
                raise _Refusal("raster diagram PDF image binding is ambiguous")
            bitmap = candidates[0].get_bitmap(render=False)
            raster = bitmap.to_pil().convert("RGB")
            if raster.size != (pixel_width, pixel_height):
                raster.close()
                raise _Refusal("raster diagram PDF bitmap dimensions differ")
            return raster, owner, pixel_width, pixel_height
        finally:
            if bitmap is not None:
                bitmap.close()
            for image in images:
                image.close()
            if page is not None:
                page.close()
            if document is not None:
                document.close()
    except _Refusal:
        raise
    except Exception as exc:
        raise _Refusal("raster diagram PDF bitmap cannot be decoded") from exc


def _analysis_size(
    owner: _Box,
    source_width: int,
    source_height: int,
    *,
    input_kind: str,
) -> tuple[int, int]:
    if input_kind == "pdf":
        width = min(
            source_width,
            max(1, round(owner.width * _PDF_ANALYSIS_PIXELS_PER_POINT)),
        )
        height = min(
            source_height,
            max(1, round(owner.height * _PDF_ANALYSIS_PIXELS_PER_POINT)),
        )
    else:
        width, height = source_width, source_height
    scale = min(
        1.0,
        _MAX_ANALYSIS_EDGE / max(width, height),
        math.sqrt(_MAX_ANALYSIS_PIXELS / (width * height)),
    )
    width = max(1, round(width * scale))
    height = max(1, round(height * scale))
    if min(width, height) < 96 or width * height > _MAX_ANALYSIS_PIXELS:
        raise _Refusal("raster diagram analysis dimensions are unsupported")
    return width, height


def _analysis_box_from_page(
    box: _Box,
    *,
    owner: _Box,
    analysis_width: int,
    analysis_height: int,
) -> tuple[int, int, int, int]:
    if box.unit != owner.unit:
        raise _Refusal("raster diagram OCR/page units differ")
    left = round((box.x - owner.x) * analysis_width / owner.width)
    top = round((box.y - owner.y) * analysis_height / owner.height)
    right = round((box.right - owner.x) * analysis_width / owner.width)
    bottom = round((box.bottom - owner.y) * analysis_height / owner.height)
    left = min(max(left, 0), analysis_width)
    top = min(max(top, 0), analysis_height)
    right = min(max(right, 0), analysis_width)
    bottom = min(max(bottom, 0), analysis_height)
    if right <= left or bottom <= top:
        raise _Refusal("raster diagram projected bbox has no area")
    return left, top, right - left, bottom - top


def _source_box_from_analysis(
    box: tuple[int, int, int, int],
    *,
    source_width: int,
    source_height: int,
    analysis_width: int,
    analysis_height: int,
) -> _Box:
    x, y, width, height = box
    return _Box(
        x=x * source_width / analysis_width,
        y=y * source_height / analysis_height,
        width=width * source_width / analysis_width,
        height=height * source_height / analysis_height,
        unit="px",
    )


def _page_box_from_source(
    box: _Box,
    *,
    owner: _Box,
    source_width: int,
    source_height: int,
) -> _Box:
    if box.unit != "px":
        raise _Refusal("raster diagram source bbox unit differs")
    return _Box(
        x=owner.x + box.x * owner.width / source_width,
        y=owner.y + box.y * owner.height / source_height,
        width=box.width * owner.width / source_width,
        height=box.height * owner.height / source_height,
        unit=owner.unit,
    )


def _deduplicate_boxes(
    values: Sequence[tuple[int, int, int, int]],
    *,
    tolerance: int,
) -> list[tuple[int, int, int, int]]:
    output: list[tuple[int, int, int, int]] = []
    for box in sorted(values, key=lambda value: (value[1], value[0])):
        match = next(
            (
                index
                for index, current in enumerate(output)
                if all(
                    abs(left - right) <= tolerance
                    for left, right in zip(box, current, strict=True)
                )
            ),
            None,
        )
        if match is None:
            output.append(box)
            continue
        x, y, width, height = box
        cx, cy, cwidth, cheight = output[match]
        left, top = min(x, cx), min(y, cy)
        right = max(x + width, cx + cwidth)
        bottom = max(y + height, cy + cheight)
        output[match] = (left, top, right - left, bottom - top)
    return sorted(output, key=lambda value: (value[1], value[0]))


def _detect_rectangular_nodes(binary: Any, cv2: Any) -> list[tuple[int, int, int, int]]:
    height, width = binary.shape[:2]
    horizontal = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (max(15, width // 12), 1),
        ),
    )
    vertical = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (1, max(9, height // 80)),
        ),
    )
    mask = cv2.bitwise_or(horizontal, vertical)
    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)),
    )
    contours, _hierarchy = cv2.findContours(
        mask,
        cv2.RETR_LIST,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    candidates: list[tuple[int, int, int, int]] = []
    for contour in contours:
        x, y, box_width, box_height = (
            int(value) for value in cv2.boundingRect(contour)
        )
        if (
            box_width > width * 0.02
            and box_height > height * 0.02
            and (box_width > width * 0.15 or box_height > height * 0.15)
            and box_width < width * 0.98
            and box_height < height * 0.90
        ):
            candidates.append((x, y, box_width, box_height))
    nodes = _deduplicate_boxes(
        candidates,
        tolerance=max(2, round(min(width, height) * 0.002)),
    )
    nodes = [box for box in nodes if _box_has_border_support(binary, box)]
    if not 2 <= len(nodes) <= _MAX_RASTER_NODES:
        raise _Refusal("raster diagram rectangle accounting differs")
    return nodes


def _box_has_border_support(
    binary: Any,
    box: tuple[int, int, int, int],
) -> bool:
    height, width = binary.shape[:2]
    x, y, box_width, box_height = box
    thickness = max(2, round(min(width, height) * 0.002))
    strips = (
        binary[
            max(0, y - thickness) : min(height, y + thickness + 1),
            x : x + box_width,
        ],
        binary[
            max(0, y + box_height - thickness) : min(
                height, y + box_height + thickness + 1
            ),
            x : x + box_width,
        ],
        binary[
            y : y + box_height,
            max(0, x - thickness) : min(width, x + thickness + 1),
        ],
        binary[
            y : y + box_height,
            max(0, x + box_width - thickness) : min(
                width, x + box_width + thickness + 1
            ),
        ],
    )
    return all(
        strip.size > 0 and float((strip > 0).sum()) / max(strip.shape) >= 0.45
        for strip in strips
    )


def _inside_box(
    point: tuple[float, float],
    box: tuple[int, int, int, int],
    *,
    tolerance: float = 0.0,
) -> bool:
    x, y, width, height = box
    return (
        x - tolerance <= point[0] <= x + width + tolerance
        and y - tolerance <= point[1] <= y + height + tolerance
    )


def _box_center(box: tuple[int, int, int, int]) -> tuple[float, float]:
    return box[0] + box[2] / 2.0, box[1] + box[3] / 2.0


def _union_analysis_boxes(
    boxes: Sequence[tuple[int, int, int, int]],
) -> tuple[int, int, int, int]:
    if not boxes:
        raise _Refusal("raster diagram label geometry is empty")
    left = min(box[0] for box in boxes)
    top = min(box[1] for box in boxes)
    right = max(box[0] + box[2] for box in boxes)
    bottom = max(box[1] + box[3] for box in boxes)
    return left, top, right - left, bottom - top


def _detect_bullets(
    binary: Any,
    node_boxes: Sequence[tuple[int, int, int, int]],
    cv2: Any,
) -> dict[int, list[tuple[int, int, int, int]]]:
    minimum = min(binary.shape[:2])
    output: dict[int, list[tuple[int, int, int, int]]] = {}
    for node_index, (node_x, node_y, node_width, node_height) in enumerate(node_boxes):
        if node_width <= 4 or node_height <= 4:
            raise _Refusal("raster diagram node is too small")
        crop = binary[
            node_y + 2 : node_y + node_height - 2,
            node_x + 2 : node_x + node_width - 2,
        ]
        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(crop)
        values: list[tuple[int, int, int, int]] = []
        for index in range(1, count):
            x, y, width, height, area = (int(value) for value in stats[index])
            fill = area / (width * height)
            if (
                minimum * 0.004 <= width <= minimum * 0.012
                and minimum * 0.004 <= height <= minimum * 0.012
                and 0.65 <= width / height <= 1.5
                and 0.62 <= fill <= 0.88
            ):
                values.append((node_x + 2 + x, node_y + 2 + y, width, height))
        if values:
            output[node_index] = sorted(values, key=lambda value: (value[1], value[0]))
    return output


def _source_box_from_page(
    box: _Box,
    *,
    owner: _Box,
    source_width: int,
    source_height: int,
) -> _Box:
    if box.unit != owner.unit:
        raise _Refusal("raster diagram label/page units differ")
    return _Box(
        x=(box.x - owner.x) * source_width / owner.width,
        y=(box.y - owner.y) * source_height / owner.height,
        width=box.width * source_width / owner.width,
        height=box.height * source_height / owner.height,
        unit="px",
    )


def _page_union(boxes: Sequence[_Box]) -> _Box:
    if not boxes or len({box.unit for box in boxes}) != 1:
        raise _Refusal("raster diagram label page geometry differs")
    left = min(box.x for box in boxes)
    top = min(box.y for box in boxes)
    right = max(box.right for box in boxes)
    bottom = max(box.bottom for box in boxes)
    return _Box(left, top, right - left, bottom - top, boxes[0].unit)


def _analysis_gap(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> float:
    return math.hypot(
        max(first[0] - (second[0] + second[2]), second[0] - (first[0] + first[2]), 0),
        max(first[1] - (second[1] + second[3]), second[1] - (first[1] + first[3]), 0),
    )


def _overlap_area(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> int:
    return max(
        min(first[0] + first[2], second[0] + second[2]) - max(first[0], second[0]),
        0,
    ) * max(
        min(first[1] + first[3], second[1] + second[3]) - max(first[1], second[1]),
        0,
    )


def _token_records(
    item: Mapping[str, Any],
    *,
    owner: _Box,
    analysis_width: int,
    analysis_height: int,
) -> list[_TokenRecord]:
    raw_values = _sequence(
        item.get("ocr_token_occurrences"),
        maximum=_MAX_OCR_TOKENS,
        label="diagram OCR token occurrences",
    )
    output: list[_TokenRecord] = []
    identifiers: set[str] = set()
    for raw in raw_values:
        if (
            not isinstance(raw, Mapping)
            or raw.get("selected") is not True
            or raw.get("primary_selected") is not True
        ):
            continue
        identifier = _identifier(raw.get("occurrence_id"))
        line_identifier = _identifier(raw.get("line_occurrence_id"))
        if identifier in identifiers:
            raise _Refusal("raster diagram OCR token identity repeats")
        identifiers.add(identifier)
        word_index = raw.get("word_index")
        if (
            not isinstance(word_index, int)
            or isinstance(word_index, bool)
            or word_index < 0
        ):
            raise _Refusal("raster diagram OCR token order differs")
        page_box = _box(raw.get("bbox"), default_unit=owner.unit)
        output.append(
            _TokenRecord(
                identifier=identifier,
                line_identifier=line_identifier,
                text=_text(raw.get("text"), maximum=1_024),
                word_index=word_index,
                page_box=page_box,
                analysis_box=_analysis_box_from_page(
                    page_box,
                    owner=owner,
                    analysis_width=analysis_width,
                    analysis_height=analysis_height,
                ),
            )
        )
    if not output:
        raise _Refusal("raster diagram has no primary OCR tokens")
    return output


def _qualified_bullets(
    candidates_by_node: Mapping[int, Sequence[tuple[int, int, int, int]]],
    tokens: Sequence[_TokenRecord],
    node_boxes: Sequence[tuple[int, int, int, int]],
) -> dict[int, list[_BulletClaim]]:
    """Admit only closed, text-owned bullet columns.

    Compact glyph components are merely candidates.  A real detail bullet must
    sit left of one lexical line and participate in a repeated size/column
    pattern within its node.  A short overlapping OCR artifact is optional
    removal evidence, never required evidence: OCR commonly misses the glyph.
    The repeated pattern deliberately fails closed on isolated punctuation,
    dots over letters, and compact digits.
    """

    tokens_by_line: dict[str, list[_TokenRecord]] = {}
    for token in tokens:
        tokens_by_line.setdefault(token.line_identifier, []).append(token)
    output: dict[int, list[_BulletClaim]] = {}
    for node_index, candidates in candidates_by_node.items():
        if not 0 <= node_index < len(node_boxes):
            raise _Refusal("raster diagram bullet node differs")
        node_box = node_boxes[node_index]
        candidate_centers = [_box_center(value) for value in candidates]
        vertical_column = max(value[1] for value in candidate_centers) - min(
            value[1] for value in candidate_centers
        ) >= max(value[0] for value in candidate_centers) - min(
            value[0] for value in candidate_centers
        )
        allowed_directions = {"right", "left"} if vertical_column else {"down", "up"}
        provisional: list[_BulletClaim] = []
        used_tokens: set[str] = set()
        used_lines: set[str] = set()
        for candidate in candidates:
            center = _box_center(candidate)
            glyphs = [
                token
                for token in tokens
                if len(token.text.strip()) <= 2
                and _inside_box(
                    center,
                    token.analysis_box,
                    tolerance=max(1.0, min(candidate[2:]) * 0.25),
                )
                and token.analysis_box[2] <= max(candidate[2] * 2.75, candidate[2] + 3)
                and token.analysis_box[3] <= max(candidate[3] * 2.75, candidate[3] + 3)
            ]
            if len(glyphs) > 1 or any(
                glyph.identifier in used_tokens for glyph in glyphs
            ):
                continue
            glyph_ids = {glyph.identifier for glyph in glyphs}
            lexical_lines: list[tuple[str, Literal["right", "left", "down", "up"]]] = []
            for line_id, line_tokens in tokens_by_line.items():
                lexical = [
                    token
                    for token in line_tokens
                    if token.identifier not in glyph_ids
                    and any(character.isalnum() for character in token.text)
                ]
                if not lexical:
                    continue
                line_box = _union_analysis_boxes(
                    [token.analysis_box for token in lexical]
                )
                diameter = (candidate[2] + candidate[3]) / 2.0
                line_center = _box_center(line_box)
                relations = (
                    (
                        "right",
                        line_box[0] - (candidate[0] + candidate[2]),
                        abs(center[1] - line_center[1]),
                        line_box[3],
                        node_box[2],
                    ),
                    (
                        "left",
                        candidate[0] - (line_box[0] + line_box[2]),
                        abs(center[1] - line_center[1]),
                        line_box[3],
                        node_box[2],
                    ),
                    (
                        "down",
                        line_box[1] - (candidate[1] + candidate[3]),
                        abs(center[0] - line_center[0]),
                        line_box[2],
                        node_box[3],
                    ),
                    (
                        "up",
                        candidate[1] - (line_box[1] + line_box[3]),
                        abs(center[0] - line_center[0]),
                        line_box[2],
                        node_box[3],
                    ),
                )
                owned_directions = [
                    direction
                    for direction, forward_gap, cross_delta, line_thickness, span in relations
                    if direction in allowed_directions
                    and candidate[2] * 0.5 <= forward_gap <= span * 0.22
                    and cross_delta <= max(1.5, line_thickness * 0.30)
                    and 0.25 <= diameter / line_thickness <= 1.0
                ]
                if len(owned_directions) == 1 and _inside_box(
                    line_center,
                    node_box,
                    tolerance=1.0,
                ):
                    lexical_lines.append((line_id, owned_directions[0]))
            if len(lexical_lines) != 1:
                continue
            used_tokens.update(glyph_ids)
            detail_line_id, reading_direction = lexical_lines[0]
            if detail_line_id in used_lines:
                continue
            used_lines.add(detail_line_id)
            provisional.append(
                _BulletClaim(
                    candidate,
                    tuple(sorted(glyph_ids)),
                    detail_line_id,
                    reading_direction,
                )
            )

        # One dot is not enough to distinguish a bullet from punctuation.
        if len(provisional) < 2:
            continue
        if len({claim.reading_direction for claim in provisional}) != 1:
            continue
        direction = provisional[0].reading_direction
        widths = sorted(claim.analysis_box[2] for claim in provisional)
        heights = sorted(claim.analysis_box[3] for claim in provisional)
        alignment_axis = 0 if direction in {"right", "left"} else 1
        alignment_values = [
            _box_center(claim.analysis_box)[alignment_axis] for claim in provisional
        ]
        median_width = widths[len(widths) // 2]
        median_height = heights[len(heights) // 2]
        if (
            max(widths) > min(widths) * 1.75
            or max(heights) > min(heights) * 1.75
            or max(alignment_values) - min(alignment_values)
            > max(3.0, median_width * 1.5)
        ):
            continue
        ordered = sorted(
            provisional,
            key=lambda claim: (
                claim.analysis_box[1],
                claim.analysis_box[0],
                claim.source_token_ids,
            ),
        )
        # Distinct rows are part of the ownership proof.
        if any(
            _analysis_gap(left.analysis_box, right.analysis_box)
            < max(1.0, median_height * 0.5)
            for left, right in pairwise(ordered)
        ):
            continue
        output[node_index] = ordered
    return output


def _token_is_bullet(
    token: _TokenRecord,
    bullets: Sequence[tuple[int, int, int, int]],
) -> bool:
    for bullet in bullets:
        overlap = _overlap_area(token.analysis_box, bullet)
        token_area = token.analysis_box[2] * token.analysis_box[3]
        if overlap / token_area >= 0.25 or _inside_box(
            _box_center(token.analysis_box),
            bullet,
            tolerance=max(1.0, min(bullet[2], bullet[3]) * 0.25),
        ):
            return True
    return False


def _line_text(tokens: Sequence[_TokenRecord]) -> str:
    ordered = sorted(
        tokens, key=lambda value: (value.word_index, value.analysis_box[0])
    )
    pieces: list[str] = []
    previous: _TokenRecord | None = None
    for token in ordered:
        if previous is not None:
            gap = _analysis_gap(previous.analysis_box, token.analysis_box)
            threshold = max(
                0.5,
                min(
                    token.analysis_box[2],
                    token.analysis_box[3],
                    previous.analysis_box[2],
                    previous.analysis_box[3],
                )
                * 0.08,
            )
            if gap > threshold:
                pieces.append(" ")
        pieces.append(token.text)
        previous = token
    result = _validated_visual_label("".join(pieces).strip())
    if not result:
        raise _Refusal("raster diagram OCR label is empty")
    return result


def _label_from_lines(
    lines: Sequence[Sequence[_TokenRecord]],
    *,
    owner: _Box,
    source_width: int,
    source_height: int,
) -> _RasterLabel:
    if not lines:
        raise _Refusal("raster diagram label has no source line")
    # Callers provide a source-ledger order that has already been reconciled
    # with the node's inferred reading axis.  Re-sorting here by page y/x
    # would reverse multiline labels after a right-angle source transform.
    ordered_lines = list(lines)
    tokens = [token for line in ordered_lines for token in line]
    text = _validated_visual_label(
        " ".join(_line_text(line) for line in ordered_lines).strip()
    )
    page_box = _page_union([token.page_box for token in tokens])
    analysis_box = _union_analysis_boxes([token.analysis_box for token in tokens])
    return _RasterLabel(
        text=text,
        page_box=page_box,
        source_pixel_box=_source_box_from_page(
            page_box,
            owner=owner,
            source_width=source_width,
            source_height=source_height,
        ),
        analysis_box=analysis_box,
        source_token_ids=tuple(sorted(token.identifier for token in tokens)),
    )


def _group_primary_token_lines(
    tokens: Sequence[_TokenRecord],
    *,
    bullet_token_ids: set[str],
) -> list[list[_TokenRecord]]:
    by_line: dict[str, list[_TokenRecord]] = {}
    for token in tokens:
        if token.identifier in bullet_token_ids:
            continue
        by_line.setdefault(token.line_identifier, []).append(token)
    return [
        sorted(values, key=lambda value: (value.word_index, value.analysis_box[0]))
        for values in by_line.values()
        if values
    ]


def _build_raster_nodes(
    node_boxes: Sequence[tuple[int, int, int, int]],
    bullets_by_node: Mapping[int, Sequence[_BulletClaim]],
    tokens: Sequence[_TokenRecord],
    *,
    owner_id: str,
    owner: _Box,
    source_width: int,
    source_height: int,
    analysis_width: int,
    analysis_height: int,
) -> tuple[list[_RasterNode], list[list[_TokenRecord]]]:
    bullet_token_ids = {
        identifier
        for values in bullets_by_node.values()
        for claim in values
        for identifier in claim.source_token_ids
    }
    token_lines = _group_primary_token_lines(
        tokens,
        bullet_token_ids=bullet_token_ids,
    )
    lines_by_node: dict[int, list[list[_TokenRecord]]] = {
        index: [] for index in range(len(node_boxes))
    }
    outside: list[list[_TokenRecord]] = []
    for line in token_lines:
        line_box = _union_analysis_boxes([token.analysis_box for token in line])
        owners = [
            index
            for index, node_box in enumerate(node_boxes)
            if _inside_box(_box_center(line_box), node_box, tolerance=1.0)
        ]
        if len(owners) > 1:
            raise _Refusal("raster diagram OCR line has ambiguous node ownership")
        if owners:
            lines_by_node[owners[0]].append(line)
        else:
            outside.append(line)

    output: list[_RasterNode] = []
    for node_index, node_box in enumerate(node_boxes):
        lines = lines_by_node[node_index]
        if not lines:
            raise _Refusal("raster diagram node has no grounded label")
        bullet_claims = list(bullets_by_node.get(node_index, ()))
        bullets = [claim.analysis_box for claim in bullet_claims]
        detail_sources: list[
            tuple[list[list[_TokenRecord]], tuple[int, int, int, int]]
        ] = []
        if bullets:
            available = set(range(len(lines)))
            line_indexes_by_id = {
                line[0].line_identifier: index for index, line in enumerate(lines)
            }
            matches: list[tuple[int, int, tuple[int, int, int, int]]] = []
            for bullet_index, claim in enumerate(bullet_claims):
                bullet = claim.analysis_box
                line_index = line_indexes_by_id.get(claim.detail_line_id)
                if line_index is None or line_index not in available:
                    raise _Refusal("raster diagram bullet ownership is ambiguous")
                available.remove(line_index)
                matches.append((bullet_index, line_index, bullet))

            direction = bullet_claims[0].reading_direction
            if any(claim.reading_direction != direction for claim in bullet_claims):
                raise _Refusal("raster diagram bullet reading direction differs")
            axis = 1 if direction in {"right", "left"} else 0
            sign = 1.0 if direction in {"right", "up"} else -1.0

            def reading_coordinate(
                box: tuple[int, int, int, int],
                *,
                _axis: int = axis,
                _sign: float = sign,
            ) -> float:
                return _sign * _box_center(box)[_axis]

            matches.sort(key=lambda value: (reading_coordinate(value[2]), value[0]))
            matched_line_indexes = {value[1] for value in matches}
            first_coordinate = reading_coordinate(matches[0][2])
            heading_indexes: list[int] = []
            continuations: dict[int, list[int]] = {
                position: [] for position in range(len(matches))
            }
            for line_index in available:
                line_box = _union_analysis_boxes(
                    [token.analysis_box for token in lines[line_index]]
                )
                coordinate = reading_coordinate(line_box)
                if coordinate < first_coordinate:
                    heading_indexes.append(line_index)
                    continue
                position = max(
                    (
                        index
                        for index, match in enumerate(matches)
                        if reading_coordinate(match[2]) <= coordinate
                    ),
                    default=-1,
                )
                if position < 0:
                    heading_indexes.append(line_index)
                else:
                    continuations[position].append(line_index)
            if not heading_indexes:
                raise _Refusal("raster diagram group node has no heading")
            heading_lines = [
                lines[index]
                for index in sorted(
                    heading_indexes,
                    key=lambda index: reading_coordinate(
                        _union_analysis_boxes(
                            [token.analysis_box for token in lines[index]]
                        )
                    ),
                )
            ]
            for position, (_bullet_index, line_index, bullet) in enumerate(matches):
                detail_lines = [lines[line_index]] + [
                    lines[index]
                    for index in sorted(
                        continuations[position],
                        key=lambda index: reading_coordinate(
                            _union_analysis_boxes(
                                [token.analysis_box for token in lines[index]]
                            )
                        ),
                    )
                ]
                detail_sources.append((detail_lines, bullet))
            consumed = (
                set(heading_indexes)
                | matched_line_indexes
                | {index for values in continuations.values() for index in values}
            )
            if consumed != set(range(len(lines))):
                raise _Refusal("raster diagram group text accounting differs")
        else:
            heading_lines = lines

        source_box = _source_box_from_analysis(
            node_box,
            source_width=source_width,
            source_height=source_height,
            analysis_width=analysis_width,
            analysis_height=analysis_height,
        )
        page_box = _page_box_from_source(
            source_box,
            owner=owner,
            source_width=source_width,
            source_height=source_height,
        )
        label = _label_from_lines(
            heading_lines,
            owner=owner,
            source_width=source_width,
            source_height=source_height,
        )
        details = tuple(
            (
                _label_from_lines(
                    detail_lines,
                    owner=owner,
                    source_width=source_width,
                    source_height=source_height,
                ),
                bullet,
            )
            for detail_lines, bullet in detail_sources
        )
        output.append(
            _RasterNode(
                identifier=_stable(
                    "raster-node",
                    owner_id,
                    source_box.public(),
                ),
                analysis_box=node_box,
                source_pixel_box=source_box,
                page_box=page_box,
                label=label,
                details=details,
            )
        )
    return output, outside


def _check_deadline(started: float) -> None:
    if time.monotonic() - started > _MAX_ANALYSIS_SECONDS:
        raise _Refusal("raster diagram analysis deadline exceeded")


def _node_border_support(
    binary: Any,
    boxes: Sequence[tuple[int, int, int, int]],
) -> None:
    for x, y, box_width, box_height in boxes:
        if not _box_has_border_support(binary, (x, y, box_width, box_height)):
            raise _Refusal("raster diagram rectangle border is incomplete")


def _boxes_agree(
    first: Sequence[tuple[int, int, int, int]],
    second: Sequence[tuple[int, int, int, int]],
    *,
    tolerance: int,
) -> bool:
    return len(first) == len(second) and all(
        all(abs(left - right) <= tolerance for left, right in zip(a, b, strict=True))
        for a, b in zip(first, second, strict=True)
    )


def _accepted_line_analysis_boxes(
    item: Mapping[str, Any],
    *,
    owner: _Box,
    analysis_width: int,
    analysis_height: int,
) -> list[tuple[int, int, int, int]]:
    output: list[tuple[int, int, int, int]] = []
    for raw in _sequence(
        item.get("items"),
        maximum=_MAX_OCR_LINES,
        label="accepted diagram OCR lines",
    ):
        if not isinstance(raw, Mapping):
            raise _Refusal("raster diagram OCR line differs")
        if raw.get("accepted") is not True:
            continue
        output.append(
            _analysis_box_from_page(
                _box(raw.get("bbox"), default_unit=owner.unit),
                owner=owner,
                analysis_width=analysis_width,
                analysis_height=analysis_height,
            )
        )
    if not output:
        raise _Refusal("raster diagram has no accepted OCR lines")
    return output


def _reject_coherent_unowned_ink(
    mask: Any,
    *,
    cv2: Any,
    label: str,
) -> None:
    """Ignore at most isolated compression specks, never coherent strokes."""

    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask)
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        width = int(stats[index, cv2.CC_STAT_WIDTH])
        height = int(stats[index, cv2.CC_STAT_HEIGHT])
        if area > 2 or width > 2 or height > 2:
            raise _Refusal(label)
    # Thin glyph strokes and antialiased marks can fragment into individually
    # tiny components at the conservative guard threshold.  Join only
    # immediate neighbours for the custody decision, then count original
    # foreground pixels so a coherent word cannot masquerade as unrelated
    # one-pixel compression noise.
    clustered = cv2.dilate(
        mask,
        cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
    )
    cluster_count, cluster_labels = cv2.connectedComponents(clustered)
    for cluster_index in range(1, cluster_count):
        if cv2.countNonZero(mask[cluster_labels == cluster_index]) > 2:
            raise _Refusal(label)


def _validate_node_ink_accounting(
    binary: Any,
    node_boxes: Sequence[tuple[int, int, int, int]],
    line_boxes: Sequence[tuple[int, int, int, int]],
    bullets_by_node: Mapping[int, Sequence[_BulletClaim]],
    *,
    cv2: Any,
) -> None:
    """Require all label-bearing node ink to have OCR or bullet custody."""

    minimum = min(binary.shape[:2])
    inset = max(3, round(minimum * 0.003))
    padding = max(2, round(minimum * 0.002))
    for node_index, (x, y, width, height) in enumerate(node_boxes):
        if width <= inset * 2 or height <= inset * 2:
            raise _Refusal("raster diagram node interior is unsupported")
        crop = binary[
            y + inset : y + height - inset,
            x + inset : x + width - inset,
        ].copy()
        for line_box in line_boxes:
            if not _inside_box(_box_center(line_box), (x, y, width, height)):
                continue
            left = max(0, line_box[0] - x - inset - padding)
            top = max(0, line_box[1] - y - inset - padding)
            right = min(
                crop.shape[1] - 1,
                line_box[0] + line_box[2] - x - inset + padding,
            )
            bottom = min(
                crop.shape[0] - 1,
                line_box[1] + line_box[3] - y - inset + padding,
            )
            if right >= left and bottom >= top:
                cv2.rectangle(crop, (left, top), (right, bottom), 0, -1)
        for claim in bullets_by_node.get(node_index, ()):
            bullet = claim.analysis_box
            left = max(0, bullet[0] - x - inset - 1)
            top = max(0, bullet[1] - y - inset - 1)
            right = min(
                crop.shape[1] - 1,
                bullet[0] + bullet[2] - x - inset + 1,
            )
            bottom = min(
                crop.shape[0] - 1,
                bullet[1] + bullet[3] - y - inset + 1,
            )
            if right >= left and bottom >= top:
                cv2.rectangle(crop, (left, top), (right, bottom), 0, -1)
        _reject_coherent_unowned_ink(
            crop,
            cv2=cv2,
            label="raster diagram node contains ungrounded ink",
        )
        residual = cv2.morphologyEx(
            crop,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)),
        )
        if cv2.countNonZero(residual):
            raise _Refusal("raster diagram node contains ungrounded ink")


def _point_box_distance(
    point: tuple[float, float],
    box: tuple[int, int, int, int],
) -> float:
    x, y, width, height = box
    return math.hypot(
        max(x - point[0], point[0] - (x + width), 0.0),
        max(y - point[1], point[1] - (y + height), 0.0),
    )


def _project_to_boundary(
    point: tuple[float, float],
    box: tuple[int, int, int, int],
) -> tuple[float, float]:
    x, y, width, height = box
    right, bottom = x + width, y + height
    px = min(max(point[0], x), right)
    py = min(max(point[1], y), bottom)
    distances = (
        (abs(px - x), (float(x), py)),
        (abs(px - right), (float(right), py)),
        (abs(py - y), (px, float(y))),
        (abs(py - bottom), (px, float(bottom))),
    )
    return min(distances, key=lambda value: (value[0], value[1]))[1]


def _nearest_node(
    points: Sequence[tuple[int, int]],
    node_boxes: Sequence[tuple[int, int, int, int]],
    *,
    tolerance: float,
) -> int:
    ranked = sorted(
        (
            min(_point_box_distance((float(x), float(y)), box) for x, y in points),
            index,
        )
        for index, box in enumerate(node_boxes)
    )
    if (
        not ranked
        or ranked[0][0] > tolerance
        or (len(ranked) > 1 and ranked[1][0] - ranked[0][0] <= 1.0)
    ):
        raise _Refusal("raster diagram arrow target is ambiguous")
    return ranked[0][1]


def _component_contacts(
    points: Sequence[tuple[int, int]],
    node_boxes: Sequence[tuple[int, int, int, int]],
    *,
    tolerance: float,
) -> set[int]:
    return {
        index
        for index, box in enumerate(node_boxes)
        if min(_point_box_distance((float(x), float(y)), box) for x, y in points)
        <= tolerance
    }


def _shortest_component_path(
    points: Sequence[tuple[int, int]],
    *,
    source_box: tuple[int, int, int, int],
    target_box: tuple[int, int, int, int],
    arrow_points: Sequence[tuple[int, int]],
    cv2: Any,
    np: Any,
    minimum_dimension: int,
) -> tuple[tuple[float, float], ...]:
    available = set(points)
    if not available or not arrow_points:
        raise _Refusal("raster diagram connector path is empty")
    start = min(
        available,
        key=lambda point: (
            _point_box_distance(point, source_box),
            point[1],
            point[0],
        ),
    )
    goal = min(
        (point for point in arrow_points if point in available),
        key=lambda point: (
            _point_box_distance(point, target_box),
            point[1],
            point[0],
        ),
        default=None,
    )
    if goal is None:
        raise _Refusal("raster diagram arrow leaves its connector")
    queue: deque[tuple[int, int]] = deque([start])
    predecessor: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    directions = (
        (-1, -1),
        (0, -1),
        (1, -1),
        (-1, 0),
        (1, 0),
        (-1, 1),
        (0, 1),
        (1, 1),
    )
    while queue:
        current = queue.popleft()
        if current == goal:
            break
        for dx, dy in directions:
            candidate = current[0] + dx, current[1] + dy
            if candidate in available and candidate not in predecessor:
                predecessor[candidate] = current
                queue.append(candidate)
    if goal not in predecessor:
        raise _Refusal("raster diagram connector path is discontinuous")
    reversed_path: list[tuple[int, int]] = []
    cursor: tuple[int, int] | None = goal
    while cursor is not None:
        reversed_path.append(cursor)
        cursor = predecessor[cursor]
    path = list(reversed(reversed_path))
    contour = np.asarray(path, dtype=np.float32).reshape((-1, 1, 2))
    simplified = cv2.approxPolyDP(
        contour,
        max(1.0, minimum_dimension * 0.001),
        False,
    ).reshape((-1, 2))
    values = [(float(point[0]), float(point[1])) for point in simplified]
    if len(values) > _MAX_PATH_POINTS:
        step = (len(values) - 1) / (_MAX_PATH_POINTS - 1)
        values = [values[round(index * step)] for index in range(_MAX_PATH_POINTS)]
    values[0] = _project_to_boundary(values[0], source_box)
    values[-1] = _project_to_boundary(values[-1], target_box)
    compact: list[tuple[float, float]] = []
    for value in values:
        if not compact or value != compact[-1]:
            compact.append(value)
    if len(compact) < 2:
        raise _Refusal("raster diagram connector path is degenerate")
    return tuple(compact)


def _morphological_skeleton(mask: Any, *, cv2: Any, np: Any) -> Any:
    skeleton = np.zeros_like(mask)
    work = mask.copy()
    element = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    # Each iteration removes at least one boundary layer; the raster edge cap
    # and item deadline bound this loop independently of document content.
    while cv2.countNonZero(work):
        opened = cv2.morphologyEx(work, cv2.MORPH_OPEN, element)
        skeleton = cv2.bitwise_or(skeleton, cv2.subtract(work, opened))
        work = cv2.erode(work, element)
    return skeleton


def _paths_cover_component(
    component_mask: Any,
    paths: Sequence[_RasterPath],
    *,
    arrow_boxes: Sequence[tuple[int, int, int, int]],
    cv2: Any,
    np: Any,
    minimum_dimension: int,
) -> None:
    line_only = component_mask.copy()
    arrow_padding = max(2, round(minimum_dimension * 0.002))
    for x, y, width, height in arrow_boxes:
        cv2.rectangle(
            line_only,
            (max(0, x - arrow_padding), max(0, y - arrow_padding)),
            (
                min(line_only.shape[1] - 1, x + width + arrow_padding),
                min(line_only.shape[0] - 1, y + height + arrow_padding),
            ),
            0,
            -1,
        )
    skeleton = _morphological_skeleton(line_only, cv2=cv2, np=np)
    ys, xs = np.where(skeleton > 0)
    tolerance = max(2.5, minimum_dimension * 0.004)
    for py, px in zip(ys, xs, strict=True):
        point = float(px), float(py)
        distance = min(
            _point_segment_distance(point, start, end)
            for path in paths
            for start, end in pairwise(path.analysis_points)
        )
        if distance > tolerance:
            raise _Refusal("raster diagram connector has an unowned spur")


def _detect_raster_paths(
    binary: Any,
    source_binary: Any,
    node_boxes: Sequence[tuple[int, int, int, int]],
    line_boxes: Sequence[tuple[int, int, int, int]],
    *,
    owner_id: str,
    cv2: Any,
    np: Any,
    started: float,
) -> tuple[list[_RasterPath], int]:
    height, width = binary.shape[:2]
    if source_binary.shape[:2] != (height, width):
        raise _Refusal("raster diagram connector source dimensions differ")
    minimum = min(height, width)
    connector = binary.copy()
    source_connector = source_binary.copy()
    line_padding = max(2, round(minimum * 0.0015))
    for x, y, box_width, box_height in line_boxes:
        for foreground in (connector, source_connector):
            cv2.rectangle(
                foreground,
                (max(0, x - line_padding), max(0, y - line_padding)),
                (
                    min(width - 1, x + box_width + line_padding),
                    min(height - 1, y + box_height + line_padding),
                ),
                0,
                -1,
            )
    for x, y, box_width, box_height in node_boxes:
        for foreground in (connector, source_connector):
            cv2.rectangle(
                foreground,
                (max(0, x - 1), max(0, y - 1)),
                (
                    min(width - 1, x + box_width + 1),
                    min(height - 1, y + box_height + 1),
                ),
                0,
                -1,
            )
    # Retain a source-component ledger before the recognition-only opening.
    # Isolated one/two-pixel compression specks are non-topological noise;
    # every coherent source component must survive into exactly one recognized
    # component and is later used for full path/spur accounting.
    source_count, source_labels, source_stats, _source_centroids = (
        cv2.connectedComponentsWithStats(source_connector)
    )
    coherent_source_components: list[int] = []
    for source_index in range(1, source_count):
        area = int(source_stats[source_index, cv2.CC_STAT_AREA])
        component_width = int(source_stats[source_index, cv2.CC_STAT_WIDTH])
        component_height = int(source_stats[source_index, cv2.CC_STAT_HEIGHT])
        if area <= 2 and component_width <= 2 and component_height <= 2:
            connector[source_labels == source_index] = 0
        else:
            coherent_source_components.append(source_index)
    connector = cv2.morphologyEx(
        connector,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)),
    )
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(connector)
    minimum_area = max(12, round(minimum * minimum * 0.000008))
    minimum_span = max(8, round(minimum * 0.006))
    components = list(range(1, count))
    if not components or len(components) > _MAX_RASTER_CONNECTORS:
        raise _Refusal("raster diagram connector component count differs")
    if any(
        int(stats[index, cv2.CC_STAT_AREA]) < minimum_area
        or max(
            int(stats[index, cv2.CC_STAT_WIDTH]),
            int(stats[index, cv2.CC_STAT_HEIGHT]),
        )
        < minimum_span
        for index in components
    ):
        raise _Refusal("raster diagram has unowned connector foreground")
    if sum(int(stats[index, cv2.CC_STAT_AREA]) for index in components) != int(
        cv2.countNonZero(connector)
    ):
        raise _Refusal("raster diagram connector pixel accounting differs")
    node_border_tolerance = max(3, round(minimum * 0.0025))
    node_border_bands: list[Any] = []
    for node_x, node_y, node_width, node_height in node_boxes:
        band = np.zeros_like(connector)
        cv2.rectangle(
            band,
            (
                max(0, node_x - node_border_tolerance),
                max(0, node_y - node_border_tolerance),
            ),
            (
                min(width - 1, node_x + node_width + node_border_tolerance),
                min(height - 1, node_y + node_height + node_border_tolerance),
            ),
            255,
            -1,
        )
        cv2.rectangle(
            band,
            (
                min(width - 1, node_x + node_border_tolerance),
                min(height - 1, node_y + node_border_tolerance),
            ),
            (
                max(0, node_x + node_width - node_border_tolerance),
                max(0, node_y + node_height - node_border_tolerance),
            ),
            0,
            -1,
        )
        node_border_bands.append(band)

    recognized_by_source: dict[int, int] = {}
    for source_index in coherent_source_components:
        recognized = {
            int(value)
            for value in np.unique(labels[source_labels == source_index])
            if int(value) in components
        }
        if not recognized:
            source_pixels = source_labels == source_index
            owned_borders = sum(
                bool(np.all(band[source_pixels] != 0)) for band in node_border_bands
            )
            if owned_borders == 1:
                continue
        if len(recognized) != 1:
            raise _Refusal("raster diagram source connector was not retained exactly")
        recognized_by_source[source_index] = next(iter(recognized))
    if len(set(recognized_by_source.values())) != len(recognized_by_source):
        raise _Refusal("raster diagram source connectors merged during recognition")
    source_by_recognized = {
        recognized: source for source, recognized in recognized_by_source.items()
    }
    if set(source_by_recognized) != set(components):
        raise _Refusal("raster diagram recognized connector lacks source custody")
    opened = cv2.morphologyEx(
        connector,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)),
    )
    arrow_count, arrow_labels, arrow_stats, _arrow_centroids = (
        cv2.connectedComponentsWithStats(opened)
    )
    arrows_by_component: dict[
        int, list[tuple[int, tuple[int, int, int, int], list[tuple[int, int]]]]
    ] = {}
    for arrow_index in range(1, arrow_count):
        x = int(arrow_stats[arrow_index, cv2.CC_STAT_LEFT])
        y = int(arrow_stats[arrow_index, cv2.CC_STAT_TOP])
        box_width = int(arrow_stats[arrow_index, cv2.CC_STAT_WIDTH])
        box_height = int(arrow_stats[arrow_index, cv2.CC_STAT_HEIGHT])
        area = int(arrow_stats[arrow_index, cv2.CC_STAT_AREA])
        if not (
            minimum * 0.003 <= box_width <= minimum * 0.04
            and minimum * 0.003 <= box_height <= minimum * 0.04
            and minimum * minimum * 0.000008 <= area <= minimum * minimum * 0.0009
        ):
            continue
        ys, xs = np.where(arrow_labels == arrow_index)
        arrow_points = sorted(
            ((int(px), int(py)) for py, px in zip(ys, xs, strict=True)),
            key=lambda value: (value[1], value[0]),
        )
        owned = {
            int(value)
            for value in np.unique(labels[arrow_labels == arrow_index])
            if int(value) in components
        }
        if len(owned) != 1:
            raise _Refusal("raster diagram arrow/component ownership differs")
        component_index = next(iter(owned))
        arrows_by_component.setdefault(component_index, []).append(
            (arrow_index, (x, y, box_width, box_height), arrow_points)
        )
    if (
        sum(len(values) for values in arrows_by_component.values())
        > _MAX_RASTER_CONNECTORS
    ):
        raise _Refusal("raster diagram arrowhead count exceeds its bound")

    paths: list[_RasterPath] = []
    # Node discovery follows the outer edge of a raster border while connector
    # recognition erases that border with a bounded padding.  Keep endpoint
    # ownership tolerant to the same one-pixel-normalized inset; the nearest
    # node helper still requires a unique, well-separated candidate.
    contact_tolerance = max(5.0, minimum * 0.006)
    for component_index in components:
        _check_deadline(started)
        raw_arrows = arrows_by_component.get(component_index, [])
        if not raw_arrows:
            raise _Refusal("raster diagram connector has no explicit arrowhead")
        ys, xs = np.where(labels == component_index)
        component_points = sorted(
            ((int(px), int(py)) for py, px in zip(ys, xs, strict=True)),
            key=lambda value: (value[1], value[0]),
        )
        target_values: list[
            tuple[int, int, tuple[int, int, int, int], list[tuple[int, int]]]
        ] = []
        for arrow_index, arrow_box, arrow_points in raw_arrows:
            target_values.append(
                (
                    arrow_index,
                    _nearest_node(
                        arrow_points,
                        node_boxes,
                        tolerance=contact_tolerance,
                    ),
                    arrow_box,
                    arrow_points,
                )
            )
        targets = [value[1] for value in target_values]
        if len(set(targets)) != len(targets):
            raise _Refusal("raster diagram connector repeats a target")
        contacts = _component_contacts(
            component_points,
            node_boxes,
            tolerance=contact_tolerance,
        )
        sources = contacts - set(targets)
        if len(sources) != 1:
            raise _Refusal("raster diagram connector source is ambiguous")
        source_index = next(iter(sources))
        component_paths: list[_RasterPath] = []
        for arrow_index, target_index, arrow_box, arrow_points in target_values:
            analysis_points = _shortest_component_path(
                component_points,
                source_box=node_boxes[source_index],
                target_box=node_boxes[target_index],
                arrow_points=arrow_points,
                cv2=cv2,
                np=np,
                minimum_dimension=minimum,
            )
            arrow = _RasterArrow(
                identifier=_stable(
                    "raster-arrow",
                    owner_id,
                    arrow_box,
                    target_index,
                ),
                component_index=component_index,
                analysis_box=arrow_box,
                target_index=target_index,
            )
            component_paths.append(
                _RasterPath(
                    identifier=_stable(
                        "raster-connector",
                        owner_id,
                        component_index,
                        source_index,
                        target_index,
                        arrow_box,
                    ),
                    component_index=component_index,
                    source_index=source_index,
                    target_index=target_index,
                    analysis_points=analysis_points,
                    arrow=arrow,
                )
            )
        recognized_component = np.zeros_like(connector)
        recognized_component[labels == component_index] = 255
        source_component = np.zeros_like(connector)
        source_component[
            source_labels == source_by_recognized[component_index]
        ] = 255
        for node_x, node_y, node_width, node_height in node_boxes:
            cv2.rectangle(
                source_component,
                (
                    max(0, node_x - node_border_tolerance),
                    max(0, node_y - node_border_tolerance),
                ),
                (
                    min(width - 1, node_x + node_width + node_border_tolerance),
                    min(height - 1, node_y + node_height + node_border_tolerance),
                ),
                0,
                -1,
            )
        fringe_tolerance = max(2, round(minimum * 0.002))
        recognized_neighborhood = cv2.dilate(
            recognized_component,
            cv2.getStructuringElement(
                cv2.MORPH_RECT,
                (fringe_tolerance * 2 + 1, fringe_tolerance * 2 + 1),
            ),
        )
        unrecognized_source = cv2.bitwise_and(
            source_component,
            cv2.bitwise_not(recognized_neighborhood),
        )
        component_mask = cv2.bitwise_or(
            recognized_component,
            unrecognized_source,
        )
        _paths_cover_component(
            component_mask,
            component_paths,
            arrow_boxes=[value[2] for value in target_values],
            cv2=cv2,
            np=np,
            minimum_dimension=minimum,
        )
        paths.extend(component_paths)
    if not paths or len(paths) > _MAX_RASTER_CONNECTORS:
        raise _Refusal("raster diagram connector accounting differs")
    return sorted(
        paths,
        key=lambda value: (
            value.source_index,
            value.target_index,
            value.identifier,
        ),
    ), len(components)


def _point_segment_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-12:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    projection = min(
        1.0,
        max(
            0.0,
            ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared,
        ),
    )
    closest = start[0] + projection * dx, start[1] + projection * dy
    return math.hypot(point[0] - closest[0], point[1] - closest[1])


def _assign_connector_labels(
    paths: Sequence[_RasterPath],
    outside_lines: Sequence[Sequence[_TokenRecord]],
    *,
    owner: _Box,
    source_width: int,
    source_height: int,
    minimum_dimension: int,
) -> list[_RasterPath]:
    labels = [
        _label_from_lines(
            [line],
            owner=owner,
            source_width=source_width,
            source_height=source_height,
        )
        for line in outside_lines
    ]
    assigned: dict[int, _RasterLabel] = {}
    for label in labels:
        center = _box_center(label.analysis_box)
        corridor = max(
            3.0,
            label.analysis_box[3] * 2.0,
            minimum_dimension * 0.012,
        )
        owners = [
            index
            for index, path in enumerate(paths)
            if min(
                _point_segment_distance(center, start, end)
                for start, end in pairwise(path.analysis_points)
            )
            <= corridor
        ]
        if len(owners) != 1 or owners[0] in assigned:
            raise _Refusal("raster diagram connector label ownership differs")
        assigned[owners[0]] = label
    return [
        _RasterPath(
            identifier=path.identifier,
            component_index=path.component_index,
            source_index=path.source_index,
            target_index=path.target_index,
            analysis_points=path.analysis_points,
            arrow=path.arrow,
            label=assigned.get(index),
        )
        for index, path in enumerate(paths)
    ]


def _validate_primary_line_accounting(
    item: Mapping[str, Any],
    tokens: Sequence[_TokenRecord],
    *,
    owner: _Box,
) -> None:
    by_line: dict[str, list[_TokenRecord]] = {}
    for token in tokens:
        by_line.setdefault(token.line_identifier, []).append(token)
    projections = [
        (
            line_id,
            _line_text(values),
            _page_union([token.page_box for token in values]),
        )
        for line_id, values in by_line.items()
    ]
    used: set[str] = set()
    for raw in _sequence(
        item.get("items"),
        maximum=_MAX_OCR_LINES,
        label="primary diagram OCR lines",
    ):
        if not isinstance(raw, Mapping) or raw.get("accepted") is not True:
            continue
        raw_text = _text(raw.get("text", raw.get("value")), maximum=4_096)
        raw_box = _box(raw.get("bbox"), default_unit=owner.unit)
        candidates = [
            line_id
            for line_id, text, box in projections
            if line_id not in used
            and text == raw_text
            and _coverage(raw_box, box)[0] >= 0.80
            and _coverage(raw_box, box)[1] >= 0.80
        ]
        if len(candidates) != 1:
            raise _Refusal("raster diagram accepted OCR line accounting differs")
        used.add(candidates[0])
    if used != set(by_line):
        raise _Refusal("raster diagram primary OCR line accounting differs")


def _analysis_point_to_source(
    point: tuple[float, float],
    *,
    source_width: int,
    source_height: int,
    analysis_width: int,
    analysis_height: int,
) -> tuple[float, float]:
    return (
        point[0] * source_width / analysis_width,
        point[1] * source_height / analysis_height,
    )


def _source_point_to_page(
    point: tuple[float, float],
    *,
    owner: _Box,
    source_width: int,
    source_height: int,
) -> tuple[float, float]:
    return (
        owner.x + point[0] * owner.width / source_width,
        owner.y + point[1] * owner.height / source_height,
    )


def _label_public(label: _RasterLabel) -> dict[str, Any]:
    return {
        "text": label.text,
        "page_bbox": label.page_box.public(),
        "raster_pixel_bbox": label.source_pixel_box.public(),
        "source_token_ids": list(label.source_token_ids),
    }


def derive_raster_diagram_topology_evidence(
    binding: RasterDiagramOwnerBinding,
    source_document_bytes: bytes,
    *,
    page_index: int,
    input_kind: Any,
) -> dict[str, Any] | None:
    """Derive one complete rectangular directed graph from a bound raster.

    OpenCV and NumPy remain item-local optional imports.  Any unsupported
    image, dependency absence, ambiguity, unowned topology-bearing component,
    incomplete label ledger, or deadline breach returns ``None`` without
    mutating the bound item.
    """

    raster: Image.Image | None = None
    started = time.monotonic()
    try:
        if (
            not isinstance(binding, RasterDiagramOwnerBinding)
            or not isinstance(source_document_bytes, bytes)
            or not 0 < len(source_document_bytes) <= _MAX_SOURCE_BYTES
        ):
            raise _Refusal("raster diagram source payload differs")
        raw_input_kind = getattr(input_kind, "value", input_kind)
        if raw_input_kind not in {"pdf", "image"}:
            raise _Refusal("raster diagram source kind differs")
        import cv2
        import numpy as np

        raster, owner, source_width, source_height = _load_bound_raster(
            binding,
            source_document_bytes,
            page_index=page_index,
            input_kind=raw_input_kind,
        )
        analysis_width, analysis_height = _analysis_size(
            owner,
            source_width,
            source_height,
            input_kind=raw_input_kind,
        )
        resized = raster.resize(
            (analysis_width, analysis_height),
            Image.Resampling.LANCZOS,
        )
        pixels = np.asarray(resized, dtype=np.uint8)
        resized.close()
        gray = cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY)
        dark = float(np.percentile(gray, 1.0))
        white = float(np.percentile(gray, 95.0))
        if not math.isfinite(dark + white) or white - dark < 80.0:
            raise _Refusal("raster diagram tonal range is unsupported")
        normalized = np.clip(
            (gray.astype(np.float32) - dark) * 255.0 / (white - dark),
            0.0,
            255.0,
        ).astype(np.uint8)
        border_binary = (normalized < 200).astype(np.uint8) * 255
        guard_binary = (normalized < 220).astype(np.uint8) * 255
        # Completeness custody is intentionally more permissive than either
        # recognition mask.  It never creates nodes or paths; it only proves
        # that visibly coherent light-gray ink was not silently discarded as
        # background.
        custody_binary = (normalized < 240).astype(np.uint8) * 255
        core_binary = (normalized < 96).astype(np.uint8) * 255
        nodes = _detect_rectangular_nodes(border_binary, cv2)
        guarded_nodes = _detect_rectangular_nodes(guard_binary, cv2)
        agreement_tolerance = max(
            2,
            round(min(analysis_width, analysis_height) * 0.0025),
        )
        if not _boxes_agree(
            nodes,
            guarded_nodes,
            tolerance=agreement_tolerance,
        ):
            raise _Refusal("raster diagram rectangle thresholds disagree")
        _node_border_support(border_binary, nodes)
        _node_border_support(guard_binary, guarded_nodes)
        _check_deadline(started)

        tokens = _token_records(
            binding.item,
            owner=owner,
            analysis_width=analysis_width,
            analysis_height=analysis_height,
        )
        _validate_primary_line_accounting(binding.item, tokens, owner=owner)
        bullet_candidates = _detect_bullets(core_binary, nodes, cv2)
        bullets = _qualified_bullets(bullet_candidates, tokens, nodes)
        raster_nodes, outside_lines = _build_raster_nodes(
            nodes,
            bullets,
            tokens,
            owner_id=binding.owner_id,
            owner=owner,
            source_width=source_width,
            source_height=source_height,
            analysis_width=analysis_width,
            analysis_height=analysis_height,
        )
        line_boxes = _accepted_line_analysis_boxes(
            binding.item,
            owner=owner,
            analysis_width=analysis_width,
            analysis_height=analysis_height,
        )
        _validate_node_ink_accounting(
            custody_binary,
            nodes,
            line_boxes,
            bullets,
            cv2=cv2,
        )
        raster_paths, component_count = _detect_raster_paths(
            border_binary,
            custody_binary,
            nodes,
            line_boxes,
            owner_id=binding.owner_id,
            cv2=cv2,
            np=np,
            started=started,
        )
        raster_paths = _assign_connector_labels(
            raster_paths,
            outside_lines,
            owner=owner,
            source_width=source_width,
            source_height=source_height,
            minimum_dimension=min(analysis_width, analysis_height),
        )
        _check_deadline(started)

        public_nodes: list[dict[str, Any]] = []
        for node in raster_nodes:
            details: list[dict[str, Any]] = []
            for detail, bullet_box in node.details:
                bullet_source_box = _source_box_from_analysis(
                    bullet_box,
                    source_width=source_width,
                    source_height=source_height,
                    analysis_width=analysis_width,
                    analysis_height=analysis_height,
                )
                bullet_page_box = _page_box_from_source(
                    bullet_source_box,
                    owner=owner,
                    source_width=source_width,
                    source_height=source_height,
                )
                details.append(
                    {
                        **_label_public(detail),
                        "bullet": {
                            "source_object_id": _stable(
                                "raster-bullet",
                                binding.owner_id,
                                bullet_source_box.public(),
                            ),
                            "page_bbox": bullet_page_box.public(),
                            "raster_pixel_bbox": bullet_source_box.public(),
                        },
                    }
                )
            public_nodes.append(
                {
                    "source_object_id": node.identifier,
                    "shape": "rectangle",
                    "page_bbox": node.page_box.public(),
                    "raster_pixel_bbox": node.source_pixel_box.public(),
                    "label": _label_public(node.label),
                    "details": details,
                    "confidence": 1.0,
                }
            )

        public_connectors: list[dict[str, Any]] = []
        for path in raster_paths:
            source_points = [
                _analysis_point_to_source(
                    point,
                    source_width=source_width,
                    source_height=source_height,
                    analysis_width=analysis_width,
                    analysis_height=analysis_height,
                )
                for point in path.analysis_points
            ]
            page_points = [
                _source_point_to_page(
                    point,
                    owner=owner,
                    source_width=source_width,
                    source_height=source_height,
                )
                for point in source_points
            ]
            arrow_source_box = _source_box_from_analysis(
                path.arrow.analysis_box,
                source_width=source_width,
                source_height=source_height,
                analysis_width=analysis_width,
                analysis_height=analysis_height,
            )
            arrow_page_box = _page_box_from_source(
                arrow_source_box,
                owner=owner,
                source_width=source_width,
                source_height=source_height,
            )
            arrow_source_tip = source_points[-1]
            arrow_page_tip = page_points[-1]
            connector: dict[str, Any] = {
                "source_object_id": path.identifier,
                "component_index": path.component_index,
                "source_node_source_object_id": raster_nodes[
                    path.source_index
                ].identifier,
                "target_node_source_object_id": raster_nodes[
                    path.target_index
                ].identifier,
                "path_points": [{"x": x, "y": y} for x, y in page_points],
                "raster_path_points": [{"x": x, "y": y} for x, y in source_points],
                "arrowhead": {
                    "source_object_id": path.arrow.identifier,
                    "page_bbox": arrow_page_box.public(),
                    "raster_pixel_bbox": arrow_source_box.public(),
                    "tip": {"x": arrow_page_tip[0], "y": arrow_page_tip[1]},
                    "raster_tip": {
                        "x": arrow_source_tip[0],
                        "y": arrow_source_tip[1],
                    },
                },
                "endpoint_tolerance": max(
                    owner.width / analysis_width,
                    owner.height / analysis_height,
                )
                * max(5.0, min(analysis_width, analysis_height) * 0.006),
                "confidence": 1.0,
                "direction_confidence": 1.0,
            }
            if path.label is not None:
                connector["label"] = _label_public(path.label)
            public_connectors.append(connector)

        proof = _owner_proof(binding)
        evidence = {
            "schema_version": "1.0",
            "source": {
                "kind": "raster",
                "owner_id": binding.owner_id,
                "page_bbox": owner.public(),
                "raster_pixel_bbox": _Box(
                    0.0,
                    0.0,
                    float(source_width),
                    float(source_height),
                    "px",
                ).public(),
                "transform": [
                    owner.width / source_width,
                    0.0,
                    0.0,
                    owner.height / source_height,
                    owner.x,
                    owner.y,
                ],
                "ocr_ledger_sha256": proof["ocr_ledger_sha256"],
            },
            "nodes": public_nodes,
            "connectors": public_connectors,
            "accounting": {
                "node_count": len(public_nodes),
                "connector_component_count": component_count,
                "connector_count": len(public_connectors),
                "arrowhead_count": len(public_connectors),
                "detail_count": sum(len(node["details"]) for node in public_nodes),
                "unowned_topology_component_count": 0,
            },
        }
        _validate_bounded_tree(evidence)
        _canonical(evidence)
        return evidence
    except (
        ImportError,
        MemoryError,
        OverflowError,
        RecursionError,
        _Refusal,
        TypeError,
        ValueError,
    ):
        return None
    except Exception:  # noqa: BLE001 - optional backend exception taxonomy varies
        # Optional image/PDF/CV backends expose implementation-specific
        # exception types.  The public analyzer boundary is item-local and
        # always fails closed without suppressing process-level interrupts.
        return None
    finally:
        if raster is not None:
            raster.close()


def _line_ledger(value: Any, *, unit: str, owner: _Box) -> list[dict[str, Any]]:
    lines = _sequence(value, maximum=_MAX_OCR_LINES, label="OCR line ledger")
    if not lines:
        raise _Refusal("raster diagram OCR line ledger is empty")
    output: list[dict[str, Any]] = []
    for raw in lines:
        if not isinstance(raw, Mapping):
            raise _Refusal("raster diagram OCR line is malformed")
        allowed = {
            "acceptance_note",
            "accepted",
            "bbox",
            "confidence",
            "rejection_reason",
            "source",
            "text",
            "value",
            "word_count",
        }
        if set(raw) - allowed:
            raise _Refusal("raster diagram OCR line fields differ")
        if raw.get("accepted") not in {True, False}:
            raise _Refusal("raster diagram OCR line acceptance differs")
        confidence_value = raw.get("confidence")
        if confidence_value is not None:
            confidence = _number(confidence_value)
            if not 0.0 <= confidence <= 1.0:
                raise _Refusal("raster diagram OCR line confidence differs")
        word_count = raw.get("word_count")
        if (
            not isinstance(word_count, int)
            or isinstance(word_count, bool)
            or not 0 <= word_count <= 4_096
        ):
            raise _Refusal("raster diagram OCR line word count differs")
        text = _visual_label_component(raw.get("text", raw.get("value")))
        if not text.strip():
            raise _Refusal("raster diagram OCR line text is empty")
        line_box = _box(raw.get("bbox"), default_unit=unit)
        if line_box.unit != owner.unit:
            raise _Refusal("raster diagram OCR line unit differs")
        tolerance_x, tolerance_y = _mapping_tolerance(owner)
        if (
            line_box.x < owner.x - tolerance_x
            or line_box.y < owner.y - tolerance_y
            or line_box.right > owner.right + tolerance_x
            or line_box.bottom > owner.bottom + tolerance_y
        ):
            raise _Refusal("raster diagram OCR line leaves its owner")
        output.append(deepcopy(dict(raw)))
    return output


def _summary(value: Any, *, token_count: int) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _Refusal("raster diagram occurrence summary is unavailable")
    allowed = {
        "duplicate_occurrences",
        "fail_closed_overflow",
        "invalid_occurrences",
        "occurrence_limit_reached",
        "overflow_reason",
        "oversized_text_occurrences",
        "primary_selected_occurrences",
        "schema_version",
        "selected_occurrences",
        "serialized_byte_limit_reached",
        "serialized_occurrence_bytes",
        "short_alternative_limit_reached",
        "short_alternative_occurrences",
        "source_token_limit_reached",
        "total_occurrences",
        "truncated_occurrences",
    }
    if set(value) != allowed:
        raise _Refusal("raster diagram occurrence summary fields differ")
    if value.get("schema_version") != "1.0":
        raise _Refusal("raster diagram occurrence summary version differs")
    if value.get("overflow_reason") is not None:
        raise _Refusal("raster diagram occurrence overflow reason differs")
    required_flags = {
        "fail_closed_overflow",
        "occurrence_limit_reached",
        "serialized_byte_limit_reached",
        "short_alternative_limit_reached",
        "source_token_limit_reached",
    }
    for key in (
        allowed
        - required_flags
        - {
            "overflow_reason",
            "schema_version",
        }
    ):
        member = value.get(key)
        if (
            not isinstance(member, int)
            or isinstance(member, bool)
            or not 0 <= member <= 8_388_608
        ):
            raise _Refusal("raster diagram occurrence summary count differs")
    if any(value.get(flag) is not False for flag in required_flags):
        raise _Refusal("raster diagram occurrence ledger is incomplete")
    total = value.get("total_occurrences")
    if not isinstance(total, int) or isinstance(total, bool) or total != token_count:
        raise _Refusal("raster diagram occurrence count differs")
    serialized = value.get("serialized_occurrence_bytes")
    if (
        not isinstance(serialized, int)
        or isinstance(serialized, bool)
        or serialized < 0
        or serialized > 8_388_608
    ):
        raise _Refusal("raster diagram occurrence byte count differs")
    return deepcopy(dict(value))


def _token_projection(
    value: Any,
    *,
    unit: str,
    owner: _Box,
) -> tuple[list[dict[str, Any]], list[tuple[Any, ...]]]:
    raw_tokens = _sequence(
        value,
        maximum=_MAX_OCR_TOKENS,
        label="OCR occurrence ledger",
    )
    if not raw_tokens:
        raise _Refusal("raster diagram OCR occurrence ledger is empty")
    output: list[dict[str, Any]] = []
    projections: list[tuple[Any, ...]] = []
    for raw in raw_tokens:
        if not isinstance(raw, Mapping):
            raise _Refusal("raster diagram OCR occurrence is malformed")
        allowed = {
            "bbox",
            "confidence",
            "crop_pixel_bbox",
            "duplicate_of",
            "line_occurrence_id",
            "occurrence_id",
            "ocr_pass",
            "primary_selected",
            "retention_reason",
            "selected",
            "short_alternative",
            "text",
            "word_index",
        }
        required = allowed - {"crop_pixel_bbox", "duplicate_of"}
        if set(raw) - allowed or not required <= set(raw):
            raise _Refusal("raster diagram OCR occurrence fields differ")
        text = _visual_label_component(raw.get("text"))
        ocr_pass = _text(raw.get("ocr_pass"), maximum=128)
        if not text or not ocr_pass:
            raise _Refusal("raster diagram OCR occurrence identity differs")
        confidence = _number(raw.get("confidence"))
        if not 0.0 <= confidence <= 1.0:
            raise _Refusal("raster diagram OCR occurrence confidence differs")
        if any(
            not isinstance(raw.get(key), bool)
            for key in ("primary_selected", "selected", "short_alternative")
        ):
            raise _Refusal("raster diagram OCR occurrence flags differ")
        word_index = raw.get("word_index")
        if (
            not isinstance(word_index, int)
            or isinstance(word_index, bool)
            or not 0 <= word_index <= 4_096
        ):
            raise _Refusal("raster diagram OCR word index differs")
        page_box = _box(raw.get("bbox"), default_unit=unit)
        if page_box.unit != owner.unit:
            raise _Refusal("raster diagram OCR occurrence unit differs")
        tolerance_x, tolerance_y = _mapping_tolerance(owner)
        if (
            page_box.x < owner.x - tolerance_x
            or page_box.y < owner.y - tolerance_y
            or page_box.right > owner.right + tolerance_x
            or page_box.bottom > owner.bottom + tolerance_y
        ):
            raise _Refusal("raster diagram OCR occurrence leaves its owner")
        crop_value = raw.get("crop_pixel_bbox")
        crop_box = (
            _box(crop_value, default_unit="px") if crop_value is not None else None
        )
        if crop_box is not None and crop_box.unit != "px":
            raise _Refusal("raster diagram OCR crop occurrence unit differs")
        output.append(deepcopy(dict(raw)))
        projections.append(
            (
                text,
                ocr_pass,
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
                raw.get("selected"),
                raw.get("primary_selected"),
                raw.get("short_alternative"),
            )
        )
    return output, projections


def _eligible_owner(
    value: Any,
    *,
    page_unit: str,
    input_kind: str,
) -> tuple[str, _Box, int, int, Mapping[str, Any]]:
    if not isinstance(value, Mapping):
        raise _Refusal("detected raster owner is malformed")
    owner_id = _identifier(value.get("id"))
    if value.get("type") != "image":
        raise _Refusal("detected raster owner type differs")
    role = value.get("region_role")
    origin = value.get("region_origin")
    if input_kind == "pdf":
        if role != "content_region" or origin != "pdf_embedded":
            raise _Refusal("PDF raster owner provenance differs")
    elif input_kind == "image":
        if role not in {"page_source", "content_region"} or origin != "uploaded_page":
            raise _Refusal("direct-image raster owner provenance differs")
    else:
        raise _Refusal("raster owner input kind is unsupported")
    box = _box(value.get("bbox"), default_unit=page_unit)
    if box.unit != page_unit:
        raise _Refusal("raster owner page unit differs")
    width = _positive_int(value.get("pixel_width"), maximum=_MAX_PIXEL_EDGE)
    height = _positive_int(value.get("pixel_height"), maximum=_MAX_PIXEL_EDGE)
    if width * height > _MAX_PIXEL_COUNT:
        raise _Refusal("raster owner pixel budget exceeded")
    return owner_id, box, width, height, value


def _claimed_by(
    owner: _Box,
    page_items: Sequence[Any],
    *,
    page_unit: str,
) -> list[int]:
    claims: list[int] = []
    for index, value in enumerate(page_items):
        if (
            not isinstance(value, Mapping)
            or value.get("region_role") != "content_region"
        ):
            continue
        declared = str(value.get("type") or value.get("content_type") or "")
        if declared not in {"image", "chart", "diagram"}:
            continue
        try:
            layout = _box(value.get("bbox"), default_unit=page_unit)
        except _Refusal:
            continue
        if _near_contained(layout, owner):
            claims.append(index)
    return claims


def bind_raster_diagram_owner(
    item: Mapping[str, Any],
    *,
    page_items: Sequence[Any],
    detected_images: Sequence[Any],
    page_index: int,
    page_unit: str,
    input_kind: Any,
) -> RasterDiagramOwnerBinding | None:
    """Bind one visual to one complete detected source raster, or refuse.

    The layout visual and detected owner are independent projections.  Their
    geometry, complete OCR line ledger, bounded occurrence summary, and token
    text/pass/bboxes must agree.  Occurrence IDs are intentionally excluded
    from the token comparison because the two public owner projections may
    re-key identical source tokens.
    """

    try:
        raw_input_kind = getattr(input_kind, "value", input_kind)
        if raw_input_kind not in {"pdf", "image"}:
            raise _Refusal("raster diagram input kind is unsupported")
        if (
            not isinstance(page_index, int)
            or isinstance(page_index, bool)
            or page_index < 1
            or page_unit not in {"pt", "px"}
            or not isinstance(item, Mapping)
        ):
            raise _Refusal("raster diagram owner context differs")
        _validate_bounded_tree(item)
        _validate_bounded_tree(detected_images)
        bounded_page_items = _sequence(
            page_items,
            maximum=_MAX_PAGE_ITEMS,
            label="page item list",
        )
        bounded_owners = _sequence(
            detected_images,
            maximum=_MAX_DETECTED_OWNERS,
            label="detected owner list",
        )
        layout = _box(item.get("bbox"), default_unit=page_unit)
        if layout.unit != page_unit or item.get("region_role") != "content_region":
            raise _Refusal("diagram layout owner differs")

        candidates: list[tuple[int, str, _Box, int, int, Mapping[str, Any]]] = []
        for owner_index, value in enumerate(bounded_owners):
            try:
                owner_id, owner_box, width, height, owner = _eligible_owner(
                    value,
                    page_unit=page_unit,
                    input_kind=raw_input_kind,
                )
            except _Refusal:
                continue
            if not _near_contained(layout, owner_box):
                continue
            claims = _claimed_by(
                owner_box,
                bounded_page_items,
                page_unit=page_unit,
            )
            matching_claims = [
                index for index in claims if bounded_page_items[index] is item
            ]
            if len(claims) != 1 or len(matching_claims) != 1:
                continue
            candidates.append((owner_index, owner_id, owner_box, width, height, owner))
        if len(candidates) != 1:
            raise _Refusal("raster diagram owner claim is ambiguous")
        owner_index, owner_id, owner_box, pixel_width, pixel_height, owner = candidates[
            0
        ]

        owner_lines = _line_ledger(owner.get("items"), unit=page_unit, owner=owner_box)
        item_lines = _line_ledger(item.get("items"), unit=page_unit, owner=owner_box)
        if _canonical(owner_lines) != _canonical(item_lines):
            raise _Refusal("raster diagram OCR line ledgers differ")
        accepted_text = "\n".join(
            _text(line.get("text", line.get("value")), maximum=4_096)
            for line in owner_lines
            if line.get("accepted") is True
        )
        owner_primary_values = [
            _text(owner.get(key))
            for key in ("value", "md", "ocr_text", "cleaned_ocr_text")
        ]
        if any(value != accepted_text for value in owner_primary_values):
            raise _Refusal("raster diagram primary OCR projections differ")
        if _text(item.get("ocr_text")) != accepted_text:
            raise _Refusal("diagram and detected-owner OCR text differ")
        raw_ocr_text = _text(owner.get("raw_ocr_text"))
        if _text(item.get("raw_ocr_text")) != raw_ocr_text:
            raise _Refusal("diagram and detected-owner raw OCR differ")

        owner_tokens, owner_projection = _token_projection(
            owner.get("ocr_token_occurrences"),
            unit=page_unit,
            owner=owner_box,
        )
        _item_tokens, item_projection = _token_projection(
            item.get("ocr_token_occurrences"),
            unit=page_unit,
            owner=owner_box,
        )
        if owner_projection != item_projection:
            raise _Refusal("diagram and detected-owner OCR occurrences differ")
        owner_summary = _summary(
            owner.get("ocr_occurrence_summary"),
            token_count=len(owner_tokens),
        )
        item_summary = _summary(
            item.get("ocr_occurrence_summary"),
            token_count=len(owner_tokens),
        )
        if _canonical(owner_summary) != _canonical(item_summary):
            raise _Refusal("diagram and detected-owner summaries differ")

        layout_coverage, detected_coverage = _coverage(layout, owner_box)
        tolerance_x, tolerance_y = _mapping_tolerance(owner_box)
        ledger_projection = {
            "value": accepted_text,
            "md": accepted_text,
            "raw_ocr_text": raw_ocr_text,
            "items": owner_lines,
            "ocr_occurrence_summary": owner_summary,
            "ocr_tokens": owner_projection,
        }
        ledger_hash = hashlib.sha256(
            _canonical(ledger_projection).encode("utf-8")
        ).hexdigest()
        staged = deepcopy(dict(item))
        staged["bbox"] = owner_box.public()
        staged["items"] = owner_lines
        staged["ocr_text"] = accepted_text
        staged["raw_ocr_text"] = raw_ocr_text
        staged["ocr_token_occurrences"] = owner_tokens
        staged["ocr_occurrence_summary"] = owner_summary
        caption = item.get("caption")
        primary = [
            value
            for value in (
                caption if isinstance(caption, str) and caption else None,
                accepted_text,
            )
            if value
        ]
        staged["value"] = "\n".join(primary)
        staged["md"] = "\n".join(primary)
        raw_meta = item.get("meta")
        meta = deepcopy(dict(raw_meta)) if isinstance(raw_meta, Mapping) else {}
        meta["phase05_raster_diagram_owner"] = {
            "schema_version": "1.0",
            "owner_id": owner_id,
            "page_index": page_index,
            "input_kind": raw_input_kind,
            "region_role": owner.get("region_role"),
            "region_origin": owner.get("region_origin"),
            "layout_bbox": layout.public(),
            "detected_bbox": owner_box.public(),
            "pixel_width": pixel_width,
            "pixel_height": pixel_height,
            "layout_coverage": layout_coverage,
            "detected_coverage": detected_coverage,
            "mapping_tolerance_x": tolerance_x,
            "mapping_tolerance_y": tolerance_y,
            "ocr_ledger_sha256": ledger_hash,
        }
        staged["meta"] = meta
        return RasterDiagramOwnerBinding(
            owner_id=owner_id,
            owner_index=owner_index,
            item=staged,
        )
    except (
        MemoryError,
        OverflowError,
        RecursionError,
        _Refusal,
        TypeError,
        ValueError,
    ):
        return None
    except Exception:  # noqa: BLE001 - Mapping implementations may vary
        return None


__all__ = [
    "RasterDiagramOwnerBinding",
    "bind_raster_diagram_owner",
    "derive_raster_diagram_topology_evidence",
]
