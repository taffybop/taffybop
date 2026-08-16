"""Fail-closed canonical omission of source-contradicted page-render OCR.

This lane never removes or edits a public item or an IR record.  It is an
optional, terminal presentation-only transaction whose authority is a freshly
bound selected-vector table plus a complete PDFium object proof for the OCR
owner's padded render crop.
"""

from __future__ import annotations

import copy
import ctypes
import hashlib
import json
import math
import time
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw

from app.services.ir import DocumentIR, EvidenceMethod, RelationshipType
from app.services.ocr import PDF_RENDER_CROP_PADDING_POINTS
from app.services.presentation import (
    CanonicalPresentation,
    build_canonical_presentation,
    omit_source_contradicted_primary_ocr,
)
from app.services.source_text_alignment import (
    MAX_REPORT_BYTES,
    MAX_SCANNED_OWNERS,
    MAX_PDF_NAMES_INSPECTED,
    MAX_INPUT_BYTES,
    MAX_TOTAL_ALIGNMENT_SELECTIONS,
    SourceBBox,
    SourceTextEvidence,
    _admit_selected_vector_representations,
    _center_inside,
    _character_emits,
    _decoded_pdf_name,
    _intersection_area,
    _mapping_bbox_in_unit,
    _PDF_NAME_RE,
    _selected_vector_owner_shape,
    _selected_vector_page_reference_counts,
    _table_cell_covers_source_fragment,
    text_for_bbox,
)


SOURCE_CONTRADICTED_PRIMARY_OCR_REASON = "source_contradicted_primary_ocr"
SOURCE_CONTRADICTED_PRIMARY_OCR_POLICY_ID = (
    "p02-source-contradicted-primary-ocr-v1"
)
MAX_OMISSION_CANDIDATES = 64
MAX_OMISSION_PAGES = 100
MAX_OMISSION_OBJECTS = 16_384
MAX_OMISSION_SEGMENTS_PER_OBJECT = 16
MAX_OMISSION_COMPARISONS = 1_048_576
MAX_OMISSION_IR_RECORDS = 50_000
MAX_OMISSION_SECONDS = 2.0
MAX_OMISSION_DASH_VALUES = 16
MAX_OMISSION_NULL_PATHS = 4_096
MAX_OMISSION_NULL_PATH_DEPTH = 32
_GEOMETRY_TOLERANCE = 0.05
_PATH_BOUNDARY_TOLERANCE = 0.75
_STANDARD_FONTS = frozenset(pdfium.PdfFont.STANDARD_FONTS[:12])
_FORBIDDEN_PDF_NAMES = frozenset(
    {
        b"ActualText",
        b"BM",
        b"CIDFontType0",
        b"CIDFontType2",
        b"Differences",
        b"Encrypt",
        b"ExtGState",
        b"FontFile",
        b"FontFile2",
        b"FontFile3",
        b"ObjStm",
        b"OC",
        b"OCG",
        b"OCMD",
        b"OCProperties",
        b"Pattern",
        b"Shading",
        b"SMask",
        b"ToUnicode",
        b"TrueType",
        b"Type0",
        b"Type3",
    }
)
class CanonicalOcrOmissionRefusal(RuntimeError):
    pass


def _refuse(message: str) -> None:
    raise CanonicalOcrOmissionRefusal(message)


def _check_deadline(deadline: float) -> None:
    if time.perf_counter() > deadline:
        _refuse("canonical OCR omission deadline exceeded")


def _charge_comparisons(
    comparison_budget: list[int],
    deadline: float,
    amount: int = 1,
) -> None:
    if amount < 0:
        _refuse("canonical OCR omission comparison limit differs")
    prior = comparison_budget[0]
    comparison_budget[0] += amount
    if comparison_budget[0] > MAX_OMISSION_COMPARISONS:
        _refuse("canonical OCR omission comparison limit exceeded")
    if prior // 256 != comparison_budget[0] // 256:
        _check_deadline(deadline)


def _dump(value: Any) -> Any:
    method = getattr(value, "model_dump", None)
    if callable(method):
        return method(mode="json", exclude_none=True)
    return copy.deepcopy(value)


def _value_at_path(value: Any, path: Sequence[str | int]) -> Any:
    current = value
    for component in path:
        if type(component) is int:
            if type(current) is not list or not 0 <= component < len(current):
                _refuse("canonical OCR omission null path differs")
            current = current[component]
        else:
            if type(component) is not str or not isinstance(current, Mapping):
                _refuse("canonical OCR omission null path differs")
            if component not in current:
                _refuse("canonical OCR omission null path differs")
            current = current[component]
    return current


def _canonical_explicit_null_paths(
    raw_canonical: Mapping[str, Any],
    canonical: CanonicalPresentation,
) -> tuple[tuple[str | int, ...], ...]:
    paths: list[tuple[str | int, ...]] = []
    stack: list[tuple[Any, tuple[str | int, ...]]] = [(raw_canonical, ())]
    while stack:
        value, path = stack.pop()
        if len(path) > MAX_OMISSION_NULL_PATH_DEPTH:
            _refuse("canonical OCR omission null path depth exceeded")
        if value is None:
            paths.append(path)
            if len(paths) > MAX_OMISSION_NULL_PATHS:
                _refuse("canonical OCR omission null path limit exceeded")
            continue
        if isinstance(value, Mapping):
            if any(type(key) is not str for key in value):
                _refuse("canonical OCR omission null path differs")
            for key in sorted(value, reverse=True):
                stack.append((value[key], (*path, key)))
        elif type(value) is list:
            for index in range(len(value) - 1, -1, -1):
                stack.append((value[index], (*path, index)))
    ordered = tuple(
        sorted(
            paths,
            key=lambda value: json.dumps(
                value, ensure_ascii=False, separators=(",", ":")
            ),
        )
    )
    if len(ordered) != len(set(ordered)):
        _refuse("canonical OCR omission null path repeats")
    full = canonical.model_dump(mode="json")
    if any(_value_at_path(full, path) is not None for path in ordered):
        _refuse("canonical OCR omission null path differs")
    if len(
        json.dumps(
            ordered,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ) > MAX_REPORT_BYTES:
        _refuse("canonical OCR omission null path report limit exceeded")
    return ordered


def _restore_explicit_null_paths(
    compact: Mapping[str, Any],
    canonical: CanonicalPresentation,
    paths: Sequence[Sequence[str | int]],
) -> dict[str, Any]:
    restored = copy.deepcopy(dict(compact))
    full = canonical.model_dump(mode="json")
    normalized = tuple(tuple(path) for path in paths)
    if (
        len(normalized) > MAX_OMISSION_NULL_PATHS
        or len(normalized) != len(set(normalized))
        or any(
            not path
            or len(path) > MAX_OMISSION_NULL_PATH_DEPTH
            or any(type(value) not in {str, int} for value in path)
            for path in normalized
        )
    ):
        _refuse("canonical OCR omission null path differs")
    for path in normalized:
        final_value = _value_at_path(full, path)
        if final_value is not None:
            _refuse("canonical OCR omission null path changed")
        parent: Any = restored
        for component in path[:-1]:
            if type(component) is int:
                if type(parent) is not list or not 0 <= component < len(parent):
                    _refuse("canonical OCR omission null path differs")
                parent = parent[component]
            else:
                if type(parent) is not dict or component not in parent:
                    _refuse("canonical OCR omission null path differs")
                parent = parent[component]
        final = path[-1]
        if type(final) is int:
            if type(parent) is not list or not 0 <= final < len(parent):
                _refuse("canonical OCR omission null path differs")
            parent[final] = None
        else:
            if type(parent) is not dict:
                _refuse("canonical OCR omission null path differs")
            parent[final] = None
    return restored


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > MAX_REPORT_BYTES:
        _refuse("canonical OCR omission report limit exceeded")
    return hashlib.sha256(encoded).hexdigest()


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def _substantive(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFC", value)
        if not character.isspace()
    )


def _row_source_sequence_matches(source_text: str, row_text: str) -> bool:
    source_sequence = _substantive(source_text)
    return bool(source_sequence and source_sequence == _substantive(row_text))


def _box_right(box: SourceBBox) -> float:
    return box.x + box.width


def _box_bottom(box: SourceBBox) -> float:
    return box.y + box.height


def _box_union(boxes: Sequence[SourceBBox]) -> SourceBBox:
    if not boxes:
        _refuse("canonical OCR omission has no owned cells")
    left = min(box.x for box in boxes)
    top = min(box.y for box in boxes)
    right = max(_box_right(box) for box in boxes)
    bottom = max(_box_bottom(box) for box in boxes)
    return SourceBBox(x=left, y=top, width=right - left, height=bottom - top)


def _contains(outer: SourceBBox, inner: SourceBBox, tolerance: float) -> bool:
    return (
        outer.x - tolerance <= inner.x
        and outer.y - tolerance <= inner.y
        and _box_right(inner) <= _box_right(outer) + tolerance
        and _box_bottom(inner) <= _box_bottom(outer) + tolerance
    )


def _overlaps(first: SourceBBox, second: SourceBBox) -> bool:
    return _intersection_area(first, second) > 0.0


def _touches_or_overlaps(first: SourceBBox, second: SourceBBox) -> bool:
    return not (
        _box_right(first) < second.x
        or _box_right(second) < first.x
        or _box_bottom(first) < second.y
        or _box_bottom(second) < first.y
    )


def _top_left_box(
    bounds: Sequence[float],
    *,
    page_height: float,
) -> SourceBBox:
    if len(bounds) != 4:
        _refuse("canonical OCR omission object bounds differ")
    left, bottom, right, top = (float(value) for value in bounds)
    if not all(math.isfinite(value) for value in (left, bottom, right, top)):
        _refuse("canonical OCR omission object bounds differ")
    if right < left or top < bottom:
        _refuse("canonical OCR omission object bounds differ")
    return SourceBBox(
        x=left,
        y=page_height - top,
        width=right - left,
        height=top - bottom,
    )


def _crop_box(owner: SourceBBox, *, width: float, height: float) -> SourceBBox:
    left = max(0.0, owner.x - PDF_RENDER_CROP_PADDING_POINTS)
    top = max(0.0, owner.y - PDF_RENDER_CROP_PADDING_POINTS)
    right = min(width, _box_right(owner) + PDF_RENDER_CROP_PADDING_POINTS)
    bottom = min(height, _box_bottom(owner) + PDF_RENDER_CROP_PADDING_POINTS)
    if right <= left or bottom <= top:
        _refuse("canonical OCR omission crop differs")
    return SourceBBox(x=left, y=top, width=right - left, height=bottom - top)


def _rgba(function: Any, raw_object: Any) -> tuple[int, int, int, int]:
    channels = [ctypes.c_uint() for _ in range(4)]
    if not function(raw_object, *(ctypes.byref(value) for value in channels)):
        _refuse("canonical OCR omission color differs")
    result = tuple(int(value.value) for value in channels)
    if any(value < 0 or value > 255 for value in result):
        _refuse("canonical OCR omission color differs")
    return result  # type: ignore[return-value]


def _matrix_values(value: Any) -> tuple[float, float, float, float, float, float]:
    result = tuple(float(getattr(value, key)) for key in "abcdef")
    if not all(math.isfinite(part) for part in result):
        _refuse("canonical OCR omission object transform differs")
    a, b, c, d, _e, _f = result
    first_length = math.hypot(a, b)
    second_length = math.hypot(c, d)
    if (
        first_length <= 1e-9
        or second_length <= 1e-9
        or abs(a * c + b * d) > 1e-6 * first_length * second_length
        or abs(a * d - b * c) <= 1e-9
    ):
        _refuse("canonical OCR omission object transform differs")
    return result  # type: ignore[return-value]


def _transform_point(
    point: tuple[float, float],
    matrix: tuple[float, float, float, float, float, float],
) -> tuple[float, float]:
    x, y = point
    a, b, c, d, e, f = matrix
    return a * x + c * y + e, b * x + d * y + f


def _clip_is_empty(raw_object: Any) -> bool:
    # GetClipPath is a non-owning page-object handle; only handles returned by
    # FPDF_CreateClipPath may be destroyed by the caller.
    clip = pdfium_raw.FPDFPageObj_GetClipPath(raw_object)
    return int(pdfium_raw.FPDFClipPath_CountPaths(clip)) == -1


def _preflight_pdf_names(source_pdf_bytes: bytes, *, deadline: float) -> None:
    for index, match in enumerate(_PDF_NAME_RE.finditer(source_pdf_bytes), start=1):
        if index > MAX_PDF_NAMES_INSPECTED:
            _refuse("canonical OCR omission PDF name limit exceeded")
        if index % 256 == 0:
            _check_deadline(deadline)
        decoded = _decoded_pdf_name(match.group(1))
        if decoded is None or decoded in _FORBIDDEN_PDF_NAMES:
            _refuse("canonical OCR omission PDF font or paint state differs")


def _object_is_active(raw_object: Any) -> bool:
    active = ctypes.c_int()
    return bool(
        pdfium_raw.FPDFPageObj_GetIsActive(raw_object, ctypes.byref(active))
        and active.value == 1
    )


def _source_cells(
    pages: Sequence[Mapping[str, Any]],
    evidence: SourceTextEvidence,
    representations: Mapping[int, Sequence[Mapping[str, Any]]],
    *,
    candidate_page_indexes: set[int] | None = None,
    deadline: float,
    comparison_budget: list[int],
) -> tuple[
    dict[int, tuple[dict[str, Any], ...]],
    dict[int, tuple[dict[str, Any], ...]],
]:
    scoped_representations = (
        {
            page_index: values
            for page_index, values in representations.items()
            if page_index in candidate_page_indexes
        }
        if candidate_page_indexes is not None
        else representations
    )
    admitted = _admit_selected_vector_representations(
        scoped_representations,
        pages,
        evidence,
        deadline=deadline,
    )
    if not admitted:
        _refuse("canonical OCR omission vector authority is absent")
    source_pages = {page.page_index: page for page in evidence.pages}
    cells: dict[int, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[Any, ...]] = set()
    for page_index, records in admitted.items():
        source_page = source_pages.get(page_index)
        if source_page is None or len(
            {character.id for character in source_page.characters}
        ) != len(source_page.characters):
            _refuse("canonical OCR omission source page differs")
        source_characters_by_id = {
            character.id: character for character in source_page.characters
        }
        for representation in records:
            table_bbox = _mapping_bbox_in_unit(representation.get("bbox"), "pt")
            rows = representation.get("rows")
            raw_row_boxes = representation.get("row_bboxes")
            raw_cell_boxes = representation.get("cell_bboxes")
            if (
                table_bbox is None
                or type(rows) is not list
                or type(raw_row_boxes) is not list
                or type(raw_cell_boxes) is not list
                or not len(rows) == len(raw_row_boxes) == len(raw_cell_boxes)
            ):
                _refuse("canonical OCR omission table bounds differ")
            row_boxes = [
                _mapping_bbox_in_unit(value, "pt") for value in raw_row_boxes
            ]
            cell_boxes = [
                [_mapping_bbox_in_unit(value, "pt") for value in row]
                if type(row) is list
                else []
                for row in raw_cell_boxes
            ]
            if any(value is None for value in row_boxes) or any(
                type(row) is not list
                or len(row) != len(boxes)
                or any(value is None for value in boxes)
                for row, boxes in zip(rows, cell_boxes, strict=True)
            ):
                _refuse("canonical OCR omission cell bounds differ")
            fragments: list[list[list[Any]]] = [
                [[] for _ in row] for row in rows
            ]
            for character_index, character in enumerate(source_page.characters):
                if character_index % 128 == 0:
                    _check_deadline(deadline)
                if not _character_emits(character):
                    continue
                if character.bbox is None:
                    if character.text.isspace():
                        continue
                    _refuse("canonical OCR omission source character differs")
                if not _center_inside(character.bbox, table_bbox):
                    continue
                owning_rows: list[int] = []
                for row_index, row_box in enumerate(row_boxes):
                    _charge_comparisons(comparison_budget, deadline)
                    assert row_box is not None
                    if _center_inside(character.bbox, row_box):
                        owning_rows.append(row_index)
                owners: list[tuple[int, int]] = []
                for row_index in owning_rows:
                    for column_index, cell_box in enumerate(cell_boxes[row_index]):
                        _charge_comparisons(comparison_budget, deadline)
                        assert cell_box is not None
                        if _center_inside(character.bbox, cell_box):
                            owners.append((row_index, column_index))
                if len(owners) == 1:
                    row_index, column_index = owners[0]
                    fragments[row_index][column_index].append(character)
                elif character.text and not character.text.isspace():
                    _refuse("canonical OCR omission source cell ownership differs")

            for row_index, (row, boxes, row_fragments) in enumerate(
                zip(rows, cell_boxes, fragments, strict=True)
            ):
                row_characters = tuple(
                    sorted(
                        (
                            character
                            for fragment in row_fragments
                            for character in fragment
                        ),
                        key=lambda character: character.character_index,
                    )
                )
                owned_row_character_ids = tuple(
                    character.id for character in row_characters
                )
                owned_row_character_indexes = tuple(
                    character.character_index for character in row_characters
                )
                row_text = " ".join(
                    str(value) for value in row if str(value).strip()
                )
                row_box = row_boxes[row_index]
                assert row_box is not None
                matching_lines: list[tuple[Any, tuple[Any, ...], str]] = []
                for line in source_page.lines:
                    _charge_comparisons(comparison_budget, deadline)
                    line_area = line.bbox.width * line.bbox.height
                    row_area = row_box.width * row_box.height
                    denominator = min(line_area, row_area)
                    if (
                        denominator <= 0
                        or _intersection_area(line.bbox, row_box) / denominator
                        < 0.90
                        or line.has_unsafe_character
                        or len(line.source_character_ids)
                        != len(set(line.source_character_ids))
                    ):
                        continue
                    line_characters = tuple(
                        source_characters_by_id.get(identifier)
                        for identifier in line.source_character_ids
                    )
                    _charge_comparisons(
                        comparison_budget,
                        deadline,
                        len(line.source_character_ids),
                    )
                    if (
                        any(character is None for character in line_characters)
                    ):
                        continue
                    present_line_characters = tuple(
                        character
                        for character in line_characters
                        if character is not None
                    )
                    line_indexes = tuple(
                        character.character_index
                        for character in present_line_characters
                    )
                    boxed_line_ids = tuple(
                        character.id
                        for character in present_line_characters
                        if character.bbox is not None
                    )
                    owned_span = (
                        (
                            min(owned_row_character_indexes),
                            max(owned_row_character_indexes),
                        )
                        if owned_row_character_indexes
                        else None
                    )
                    span_indexes = (
                        tuple(
                            value
                            for value in line_indexes
                            if owned_span[0] <= value <= owned_span[1]
                        )
                        if owned_span is not None
                        else ()
                    )
                    if (
                        boxed_line_ids != owned_row_character_ids
                        or owned_span is None
                        or span_indexes
                        != tuple(range(owned_span[0], owned_span[1] + 1))
                        or line_indexes != tuple(sorted(line_indexes))
                        or len(line_indexes) != len(set(line_indexes))
                        or any(
                            character.excluded_reason is not None
                            or (
                                character.bbox is None
                                and not character.text.isspace()
                            )
                            for character in present_line_characters
                        )
                    ):
                        continue
                    line_text = "".join(
                        character.text
                        for character in present_line_characters
                    )
                    if (
                        _normalized(line_text) == _normalized(row_text)
                        and _row_source_sequence_matches(line_text, row_text)
                    ):
                        matching_lines.append(
                            (line, present_line_characters, line_text)
                        )
                closed_row_characters = (
                    matching_lines[0][1]
                    if len(matching_lines) == 1
                    else row_characters
                )
                row_character_ids = tuple(
                    character.id for character in closed_row_characters
                )
                row_character_indexes = tuple(
                    character.character_index
                    for character in closed_row_characters
                )
                row_source_text = (
                    matching_lines[0][2]
                    if len(matching_lines) == 1
                    else "".join(
                        character.text for character in row_characters
                    )
                )
                row_source_closed = bool(
                    len(matching_lines) == 1
                    and closed_row_characters
                    and len(row_character_ids) == len(set(row_character_ids))
                    and len(row_character_indexes)
                    == len(set(row_character_indexes))
                    and all(
                        character.excluded_reason is None
                        and (
                            character.bbox is not None
                            or character.text.isspace()
                        )
                        for character in closed_row_characters
                    )
                )
                row_source_line_id = (
                    matching_lines[0][0].id if row_source_closed else None
                )
                row_key = (
                    page_index,
                    representation["terminal_authority_sha256"],
                    row_index,
                )
                row_key_sha256 = _digest(list(row_key))
                row_source_text_sha256 = _digest(row_source_text)
                row_source_character_ids_sha256 = _digest(
                    list(row_character_ids)
                )
                row_boxed_character_ids_sha256 = _digest(
                    list(owned_row_character_ids)
                )
                row_source_character_indexes_sha256 = _digest(
                    list(row_character_indexes)
                )
                row_source_character_index_span = (
                    [
                        min(owned_row_character_indexes),
                        max(owned_row_character_indexes),
                    ]
                    if owned_row_character_indexes
                    else []
                )
                for column_index, (text, raw_box, fragment) in enumerate(
                    zip(row, boxes, row_fragments, strict=True)
                ):
                    cell_box = raw_box
                    assert cell_box is not None
                    key = (
                        page_index,
                        representation["terminal_authority_sha256"],
                        row_index,
                        column_index,
                    )
                    if key in seen:
                        _refuse("canonical OCR omission cell authority repeats")
                    seen.add(key)
                    characters = tuple(fragment)
                    substantive = tuple(
                        character
                        for character in characters
                        if character.excluded_reason is None
                        and character.text
                        and not character.text.isspace()
                    )
                    source_closed = bool(
                        substantive
                        and not any(
                            character.excluded_reason is not None
                            for character in characters
                        )
                        and all(
                            character.bbox is not None
                            for character in substantive
                        )
                        and _table_cell_covers_source_fragment(
                            fragment, str(text)
                        )
                    )
                    cell = {
                        "key": list(key),
                        "key_sha256": _digest(list(key)),
                        "page_index": page_index,
                        "table_id": representation["public_table_id"],
                        "table_bbox": table_bbox,
                        "row_index": row_index,
                        "column_index": column_index,
                        "bbox": cell_box,
                        "row_bbox": row_box,
                        "text": str(text),
                        "source_text": "".join(
                            character.text for character in characters
                        ),
                        "source_character_ids": tuple(
                            character.id for character in characters
                        ),
                        "source_character_ids_sha256": _digest(
                            [character.id for character in characters]
                        ),
                        "source_closed": source_closed,
                        "row_source_closed": row_source_closed,
                        "row_key_sha256": row_key_sha256,
                        "row_source_line_id": row_source_line_id,
                        "row_source_text_sha256": row_source_text_sha256,
                        "row_source_character_ids_sha256": (
                            row_source_character_ids_sha256
                        ),
                        "row_boxed_character_ids_sha256": (
                            row_boxed_character_ids_sha256
                        ),
                        "row_source_character_indexes_sha256": (
                            row_source_character_indexes_sha256
                        ),
                        "row_source_character_index_span": (
                            row_source_character_index_span
                        ),
                        "representation_sha256": representation[
                            "terminal_authority_sha256"
                        ],
                    }
                    if source_closed and _substantive(
                        cell["text"]
                    ) != _substantive(cell["source_text"]):
                        _refuse("canonical OCR omission cell source differs")
                    cells[page_index].append(cell)
    return admitted, {
        page_index: tuple(values) for page_index, values in cells.items()
    }


def _page_and_owner_indexes(
    pages: Sequence[Mapping[str, Any]],
) -> tuple[
    dict[int, Mapping[str, Any]],
    dict[tuple[int, str], tuple[int, Mapping[str, Any]]],
]:
    pages_by_index: dict[int, Mapping[str, Any]] = {}
    items: dict[tuple[int, str], tuple[int, Mapping[str, Any]]] = {}
    item_count = 0
    if len(pages) > MAX_OMISSION_PAGES:
        _refuse("canonical OCR omission page limit exceeded")
    for page_position, page in enumerate(pages, start=1):
        if type(page) is not dict:
            _refuse("canonical OCR omission page differs")
        page_index = page.get("page_index")
        if type(page_index) is not int:
            page_index = page_position
        raw_items = page.get("items")
        if page_index in pages_by_index or type(raw_items) is not list:
            _refuse("canonical OCR omission page differs")
        pages_by_index[page_index] = page
        for position, item in enumerate(raw_items):
            item_count += 1
            if item_count > MAX_SCANNED_OWNERS:
                _refuse("canonical OCR omission owner limit exceeded")
            identifier = item.get("id") if type(item) is dict else None
            if type(identifier) is not str or not identifier:
                continue
            key = (page_index, identifier)
            if key in items:
                _refuse("canonical OCR omission owner repeats")
            items[key] = (position, item)
    return pages_by_index, items


def _candidate_ir_and_canonical_custody(
    *,
    ir: DocumentIR,
    canonical: CanonicalPresentation,
    page_index: int,
    item_position: int,
    item: Mapping[str, Any],
    owner_box: SourceBBox,
    deadline: float | None = None,
    comparison_budget: list[int] | None = None,
) -> tuple[str, str, str]:
    if deadline is None:
        deadline = time.perf_counter() + MAX_OMISSION_SECONDS
    if comparison_budget is None:
        comparison_budget = [0]
    _charge_comparisons(
        comparison_budget,
        deadline,
        (
            3 * len(ir.elements)
            + len(ir.pages)
            + len(ir.bboxes)
            + len(ir.coordinate_systems)
            + len(ir.evidence)
            + len(ir.regions)
            + len(ir.relationships)
            + len(ir.concerns)
            + len(canonical.pages)
            + sum(len(page.blocks) for page in canonical.pages)
        ),
    )
    owner_id = str(item["id"])
    elements = [
        element
        for element in ir.elements
        if isinstance(element.properties.get("legacy_item"), Mapping)
        and element.properties["legacy_item"].get("id") == owner_id
    ]
    if len(elements) != 1:
        _refuse("canonical OCR omission IR owner differs")
    element = elements[0]
    ir_page = next((page for page in ir.pages if page.page_index == page_index), None)
    if (
        ir_page is None
        or element.page_id != ir_page.id
        or ir_page.element_ids.count(element.id) != 1
        or ir_page.presentation_element_ids.count(element.id) != 1
        or element.type.casefold() != str(item["type"]).casefold()
        or element.reading_order != item.get("reading_order")
        or element.value != item.get("value")
        or element.markdown != item.get("md")
        or element.presentation_role != "primary"
        or element.presentation.accepted is not True
        or element.presentation.include_subordinate_ocr is not None
        or element.text_run_ids
        or element.form_semantics is not None
        or element.outline_group is not None
        or element.outline_item is not None
        or element.running_region is not None
        or element.visual_model_evidence is not None
        or len(element.bbox_ids) != 1
        or len(element.evidence_ids) != 1
        or set(element.properties)
        != {
            "legacy_item",
            "generated",
            "region_role",
            "content_type",
            "source_position",
        }
        or element.properties.get("legacy_item") != dict(item)
        or element.properties.get("generated") is not False
        or element.properties.get("region_role") is not None
        or element.properties.get("content_type") is not None
        or element.properties.get("source_position") != item_position
    ):
        _refuse("canonical OCR omission IR owner differs")
    bbox = next((value for value in ir.bboxes if value.id == element.bbox_ids[0]), None)
    coordinate = (
        next(
            (
                value
                for value in ir.coordinate_systems
                if bbox is not None and value.id == bbox.coordinate_system_id
            ),
            None,
        )
    )
    evidence = next(
        (value for value in ir.evidence if value.id == element.evidence_ids[0]),
        None,
    )
    if (
        bbox is None
        or coordinate is None
        or evidence is None
        or bbox.role != "element"
        or coordinate.page_id != ir_page.id
        or coordinate.unit != "pt"
        or coordinate.origin != "top_left"
        or tuple(coordinate.transform_to_page or ()) != (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        or any(
            abs(first - second) > 1e-9
            for first, second in zip(
                (bbox.x, bbox.y, bbox.width, bbox.height),
                (owner_box.x, owner_box.y, owner_box.width, owner_box.height),
                strict=True,
            )
        )
        or evidence.element_id != element.id
        or evidence.method is not EvidenceMethod.OCR
        or evidence.bbox_id != bbox.id
        or evidence.value != item.get("value")
        or evidence.confidence.scope != "evidence"
        or evidence.confidence.score != item.get("confidence")
        or evidence.confidence.unavailable_reason is not None
        or evidence.metadata != {"source": "ocr", "engine": None}
        or sum(value.bbox_ids.count(bbox.id) for value in ir.elements) != 1
        or sum(value.evidence_ids.count(evidence.id) for value in ir.elements)
        != 1
    ):
        _refuse("canonical OCR omission IR evidence differs")
    containing_regions = [
        region
        for region in ir.regions
        if region.page_id == ir_page.id and element.id in region.element_ids
    ]
    if (
        len(containing_regions) != 1
        or containing_regions[0].element_ids.count(element.id) != 1
    ):
        _refuse("canonical OCR omission IR region differs")
    for relationship in ir.relationships:
        incident = element.id in {relationship.source_id, relationship.target_id}
        references_evidence = evidence.id in relationship.evidence_ids
        if not incident and not references_evidence:
            continue
        if (
            not incident
            or relationship.type is not RelationshipType.READING_BEFORE
            or relationship.evidence_ids
            or relationship.metadata != {"basis": "legacy_reading_order"}
        ):
            _refuse("canonical OCR omission IR relationship differs")
    custody_ids = {element.id, bbox.id, coordinate.id, evidence.id, owner_id}
    if any(
        concern.source_ref in custody_ids or concern.target_ref in custody_ids
        for concern in ir.concerns
    ):
        _refuse("canonical OCR omission IR concern differs")

    canonical_pages = [page for page in canonical.pages if page.page_id == ir_page.id]
    blocks = [
        block
        for page in canonical_pages
        for block in page.blocks
        if block.primary_element_id == element.id
    ]
    if (
        len(canonical_pages) != 1
        or canonical_pages[0].page_index != page_index
        or len(blocks) != 1
    ):
        _refuse("canonical OCR omission canonical owner differs")
    block = blocks[0]
    if (
        block.omission_reason is not None
        or block.primary_element_type.casefold() not in {"text", "heading"}
        or block.contributing_element_ids != [element.id]
        or block.relationship_ids
        or block.excluded_contributions
        or block.suppressed_by_element_id is not None
        or block.text != str(item["value"])
        or block.markdown != str(item["md"])
    ):
        _refuse("canonical OCR omission canonical owner differs")
    return element.id, block.id, _digest(_dump(block))


def _candidate_source_contradiction(
    *,
    evidence: SourceTextEvidence,
    page_index: int,
    owner_box: SourceBBox,
    owner_text: str,
    cells: Sequence[Mapping[str, Any]],
    expected_owner_cell_keys: Sequence[str],
    expected_table_id: str,
    expected_representation_sha256: str,
    deadline: float,
    comparison_budget: list[int] | None = None,
    source_characters_by_id: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    if comparison_budget is None:
        comparison_budget = [0]
    selection = text_for_bbox(
        evidence,
        page_index,
        owner_box,
        deadline=deadline,
    )
    if (
        selection is None
        or not selection.source_character_ids
        or not 1 <= len(selection.source_line_ids) <= 64
        or len(selection.source_line_ids) != len(set(selection.source_line_ids))
        or any(
            type(value) is not str or not value
            for value in selection.source_line_ids
        )
        or len(selection.source_character_ids)
        != len(selection.source_character_indexes)
        or len(selection.source_character_ids)
        != len(set(selection.source_character_ids))
        or tuple(selection.source_character_indexes)
        != tuple(sorted(selection.source_character_indexes))
        or len(selection.source_character_indexes)
        != len(set(selection.source_character_indexes))
    ):
        return None
    source_page = next(
        (value for value in evidence.pages if value.page_index == page_index),
        None,
    )
    if source_page is None:
        _refuse("canonical OCR omission source page differs")
    characters_by_id = (
        source_characters_by_id
        if source_characters_by_id is not None
        else {value.id: value for value in source_page.characters}
    )
    characters = tuple(
        characters_by_id.get(identifier)
        for identifier in selection.source_character_ids
    )
    if (
        any(value is None for value in characters)
        or tuple(
            value.character_index for value in characters if value is not None
        )
        != tuple(selection.source_character_indexes)
    ):
        _refuse("canonical OCR omission source selection differs")
    selected_cell_keys: list[str] = []
    for character in characters:
        _charge_comparisons(comparison_budget, deadline)
        assert character is not None
        if character.excluded_reason is not None:
            return None
        if character.bbox is None:
            if not character.text.isspace():
                return None
            continue
        if not _center_inside(character.bbox, owner_box):
            return None
        owning: list[Mapping[str, Any]] = []
        for cell in cells:
            _charge_comparisons(comparison_budget, deadline)
            if (
                isinstance(cell.get("bbox"), SourceBBox)
                and _center_inside(character.bbox, cell["bbox"])
                and character.id in cell.get("source_character_ids", ())
            ):
                owning.append(cell)
        if (
            len(owning) != 1
            or owning[0].get("source_closed") is not True
            or owning[0].get("table_id") != expected_table_id
            or owning[0].get("representation_sha256")
            != expected_representation_sha256
        ):
            return None
        key = owning[0].get("key_sha256")
        if type(key) is not str or len(key) != 64:
            _refuse("canonical OCR omission source cell differs")
        selected_cell_keys.append(key)
    source_sequence = _substantive(selection.text)
    owner_sequence = _substantive(owner_text)
    expected_keys = tuple(expected_owner_cell_keys)
    selected_keys = tuple(dict.fromkeys(selected_cell_keys))
    if (
        not source_sequence
        or not owner_sequence
        or source_sequence == owner_sequence
        or source_sequence in owner_sequence
        or owner_sequence in source_sequence
        or not selected_cell_keys
        or not expected_keys
        or len(expected_keys) != len(set(expected_keys))
        or any(type(value) is not str or len(value) != 64 for value in expected_keys)
        or not set(selected_keys).issubset(set(expected_keys))
    ):
        return None
    return {
        "text": selection.text,
        "text_sha256": _digest(selection.text),
        "raw_text_sha256": _digest(selection.raw_text),
        "bbox": selection.bbox.to_dict(),
        "source_line_ids": list(selection.source_line_ids),
        "source_character_ids": list(selection.source_character_ids),
        "source_character_indexes": list(selection.source_character_indexes),
        "type1_mapping_ids": list(selection.type1_evidence_ids),
        "source_roles": copy.deepcopy(list(selection.source_roles)),
        "cell_keys_sha256": _digest(list(selected_keys)),
        "cell_keys": list(selected_keys),
        "source_sequence_sha256": _digest(source_sequence),
        "owner_sequence_sha256": _digest(owner_sequence),
    }


def _path_segments(
    raw_object: Any,
    matrix: tuple[float, float, float, float, float, float],
) -> tuple[tuple[int, bool, float, float], ...]:
    count = int(pdfium_raw.FPDFPath_CountSegments(raw_object))
    if count < 1 or count > MAX_OMISSION_SEGMENTS_PER_OBJECT:
        _refuse("canonical OCR omission path segment limit exceeded")
    values: list[tuple[int, bool, float, float]] = []
    for index in range(count):
        segment = pdfium_raw.FPDFPath_GetPathSegment(raw_object, index)
        x = ctypes.c_float()
        y = ctypes.c_float()
        if not segment or not pdfium_raw.FPDFPathSegment_GetPoint(
            segment, ctypes.byref(x), ctypes.byref(y)
        ):
            _refuse("canonical OCR omission path differs")
        point = _transform_point((float(x.value), float(y.value)), matrix)
        if not all(math.isfinite(value) for value in point):
            _refuse("canonical OCR omission path differs")
        values.append(
            (
                int(pdfium_raw.FPDFPathSegment_GetType(segment)),
                bool(pdfium_raw.FPDFPathSegment_GetClose(segment)),
                round(point[0], 6),
                round(point[1], 6),
            )
        )
    return tuple(values)


def _boundary_coordinates(
    cells: Sequence[Mapping[str, Any]],
    *,
    page_height: float,
    deadline: float,
    comparison_budget: list[int],
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    x_values: set[float] = set()
    y_values: set[float] = set()
    for cell in cells:
        _charge_comparisons(comparison_budget, deadline)
        box = cell["bbox"]
        assert isinstance(box, SourceBBox)
        x_values.update((box.x, _box_right(box)))
        y_values.update((page_height - box.y, page_height - _box_bottom(box)))
    return tuple(sorted(x_values)), tuple(sorted(y_values))


def _near_any(
    value: float,
    candidates: Sequence[float],
    tolerance: float,
    *,
    deadline: float,
    comparison_budget: list[int],
) -> bool:
    for candidate in candidates:
        _charge_comparisons(comparison_budget, deadline)
        if abs(value - candidate) <= tolerance:
            return True
    return False


def _interval_is_covered(
    start: float,
    end: float,
    intervals: Sequence[tuple[float, float]],
    *,
    tolerance: float,
    deadline: float | None = None,
    comparison_budget: list[int] | None = None,
) -> bool:
    if deadline is None:
        deadline = time.perf_counter() + MAX_OMISSION_SECONDS
    if comparison_budget is None:
        comparison_budget = [0]
    cursor = min(start, end)
    target = max(start, end)
    for left, right in sorted(
        (min(first, second), max(first, second)) for first, second in intervals
    ):
        _charge_comparisons(comparison_budget, deadline)
        if right < cursor - tolerance:
            continue
        if left > cursor + tolerance:
            return False
        cursor = max(cursor, right)
        if cursor >= target - tolerance:
            return True
    return cursor >= target - tolerance


def _filled_path_owner(
    object_box: SourceBBox,
    cells: Sequence[Mapping[str, Any]],
    *,
    deadline: float | None = None,
    comparison_budget: list[int] | None = None,
) -> tuple[
    tuple[Mapping[str, Any], ...],
    SourceBBox,
    tuple[float, ...],
    dict[str, Any],
]:
    if comparison_budget is None:
        comparison_budget = [0]

    def charge() -> None:
        comparison_budget[0] += 1
        if comparison_budget[0] > MAX_OMISSION_COMPARISONS:
            _refuse("canonical OCR omission comparison limit exceeded")
        if (
            deadline is not None
            and comparison_budget[0] % 256 == 0
            and time.perf_counter() > deadline
        ):
            _refuse("canonical OCR omission deadline exceeded")

    owners: list[
        tuple[
            tuple[Mapping[str, Any], ...],
            SourceBBox,
            tuple[float, ...],
            dict[str, Any],
        ]
    ] = []

    def near_full_union(
        box: SourceBBox,
    ) -> tuple[tuple[float, float, float, float], dict[str, Any]] | None:
        if not _contains(box, object_box, _GEOMETRY_TOLERANCE):
            return None
        insets = (
            object_box.x - box.x,
            object_box.y - box.y,
            _box_right(box) - _box_right(object_box),
            _box_bottom(box) - _box_bottom(object_box),
        )
        area_ratio = object_box.width * object_box.height / (
            box.width * box.height
        )
        if (
            any(
                value < -_GEOMETRY_TOLERANCE or value > 1.0
                for value in insets
            )
            or area_ratio < 0.95
            or area_ratio > 1.0
        ):
            return None
        return insets, {
            "owner_area_ratio": round(area_ratio, 6),
            "owner_coverage_ratio": round(area_ratio, 6),
            "outside_owner_area_ratio": 0.0,
            "intersected_neighbor_cell_keys": [],
        }

    table_boxes = {
        (
            value.x,
            value.y,
            value.width,
            value.height,
        )
        for value in (cell.get("table_bbox") for cell in cells)
        if isinstance(value, SourceBBox)
    }
    if len(table_boxes) != 1:
        _refuse("canonical OCR omission filled path table differs")
    table_values = next(iter(table_boxes))
    table_box = SourceBBox(
        x=table_values[0],
        y=table_values[1],
        width=table_values[2],
        height=table_values[3],
    )
    if not _contains(table_box, object_box, _GEOMETRY_TOLERANCE):
        _refuse("canonical OCR omission filled path table differs")

    for cell in cells:
        charge()
        cell_box = cell.get("bbox")
        if (
            isinstance(cell_box, SourceBBox)
            and cell_box.width > 0
            and cell_box.height > 0
            and cell.get("source_closed") is True
        ):
            object_area = object_box.width * object_box.height
            owner_area = cell_box.width * cell_box.height
            intersection = _intersection_area(object_box, cell_box)
            area_ratio = object_area / owner_area
            coverage_ratio = intersection / owner_area
            outside_ratio = max(0.0, object_area - intersection) / owner_area
            insets = (
                object_box.x - cell_box.x,
                object_box.y - cell_box.y,
                _box_right(cell_box) - _box_right(object_box),
                _box_bottom(cell_box) - _box_bottom(object_box),
            )
            negative_insets = sum(value < -_GEOMETRY_TOLERANCE for value in insets)
            if (
                any(value < -0.125 or value > 1.0 for value in insets)
                or negative_insets > 1
                or not 0.94 <= area_ratio <= 1.0
                or coverage_ratio < 0.94
                or outside_ratio > 0.010001
            ):
                continue
            neighbor_keys: list[str] = []
            neighbor_interior_overlap = False
            for other in cells:
                charge()
                if other is cell:
                    continue
                other_box = other.get("bbox")
                if not isinstance(other_box, SourceBBox):
                    continue
                if _overlaps(object_box, other_box):
                    key = other.get("key_sha256")
                    if type(key) is not str or not key:
                        neighbor_interior_overlap = True
                        break
                    neighbor_keys.append(key)
                    if other_box.width <= 0.25 or other_box.height <= 0.25:
                        neighbor_interior_overlap = True
                        break
                if other_box.width > 0.25 and other_box.height > 0.25:
                    eroded = SourceBBox(
                        x=other_box.x + 0.125,
                        y=other_box.y + 0.125,
                        width=other_box.width - 0.25,
                        height=other_box.height - 0.25,
                    )
                    if _intersection_area(object_box, eroded) > 1e-9:
                        neighbor_interior_overlap = True
                        break
            if neighbor_interior_overlap:
                continue
            owners.append(
                (
                    (cell,),
                    cell_box,
                    insets,
                    {
                        "owner_area_ratio": round(area_ratio, 6),
                        "owner_coverage_ratio": round(coverage_ratio, 6),
                        "outside_owner_area_ratio": round(outside_ratio, 6),
                        "intersected_neighbor_cell_keys": sorted(set(neighbor_keys)),
                    },
                )
            )

    by_row: dict[tuple[Any, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for cell in cells:
        charge()
        cell_box = cell.get("bbox")
        row_index = cell.get("row_index")
        column_index = cell.get("column_index")
        if (
            not isinstance(cell_box, SourceBBox)
            or type(row_index) is not int
            or type(column_index) is not int
            or cell_box.width <= 0
            or cell_box.height <= 0
            or not _center_inside(cell_box, object_box)
        ):
            continue
        by_row[
            (
                cell.get("table_id"),
                cell.get("representation_sha256"),
                row_index,
            )
        ].append(cell)

    for row_cells in by_row.values():
        charge()
        ordered = tuple(
            sorted(row_cells, key=lambda value: int(value["column_index"]))
        )
        if len(ordered) < 2:
            continue
        columns = tuple(int(value["column_index"]) for value in ordered)
        if columns != tuple(range(columns[0], columns[0] + len(columns))):
            continue
        boxes = tuple(value["bbox"] for value in ordered)
        if not all(isinstance(value, SourceBBox) for value in boxes):
            continue
        union = _box_union(boxes)
        union_proof = near_full_union(union)
        if union_proof is None:
            continue
        insets, metrics = union_proof
        row_boxes = tuple(value.get("row_bbox") for value in ordered)
        row_keys = {value.get("row_key_sha256") for value in ordered}
        row_line_ids = {value.get("row_source_line_id") for value in ordered}
        row_text_hashes = {
            value.get("row_source_text_sha256") for value in ordered
        }
        row_id_hashes = {
            value.get("row_source_character_ids_sha256") for value in ordered
        }
        row_boxed_id_hashes = {
            value.get("row_boxed_character_ids_sha256") for value in ordered
        }
        row_index_hashes = {
            value.get("row_source_character_indexes_sha256")
            for value in ordered
        }
        row_index_spans = {
            tuple(value.get("row_source_character_index_span") or ())
            for value in ordered
        }
        if (
            any(value.get("row_source_closed") is not True for value in ordered)
            or len(row_keys) != 1
            or len(row_line_ids) != 1
            or len(row_text_hashes) != 1
            or len(row_id_hashes) != 1
            or len(row_boxed_id_hashes) != 1
            or len(row_index_hashes) != 1
            or len(row_index_spans) != 1
            or len(next(iter(row_index_spans))) != 2
            or type(next(iter(row_line_ids))) is not str
            or not next(iter(row_line_ids))
            or any(
                type(next(iter(values))) is not str
                or len(next(iter(values))) != 64
                for values in (
                    row_keys,
                    row_text_hashes,
                    row_id_hashes,
                    row_boxed_id_hashes,
                    row_index_hashes,
                )
            )
        ):
            continue
        if not all(isinstance(value, SourceBBox) for value in row_boxes):
            continue
        first_row_box = row_boxes[0]
        assert isinstance(first_row_box, SourceBBox)
        if any(
            abs(box.y - first_row_box.y) > _GEOMETRY_TOLERANCE
            or abs(_box_bottom(box) - _box_bottom(first_row_box))
            > _GEOMETRY_TOLERANCE
            or abs(cell_box.y - first_row_box.y) > _GEOMETRY_TOLERANCE
            or abs(_box_bottom(cell_box) - _box_bottom(first_row_box))
            > _GEOMETRY_TOLERANCE
            for box, cell_box in zip(row_boxes, boxes, strict=True)
            if isinstance(box, SourceBBox)
        ):
            continue
        if any(
            abs(second.x - _box_right(first)) > _PATH_BOUNDARY_TOLERANCE
            for first, second in zip(boxes, boxes[1:], strict=False)
        ):
            continue
        owners.append((ordered, union, insets, metrics))
    if len(owners) != 1:
        _refuse("canonical OCR omission filled path ownership differs")
    return owners[0]


def _path_manifest(
    obj: Any,
    *,
    object_index: int,
    object_box: SourceBBox,
    cells: Sequence[Mapping[str, Any]],
    page_height: float,
    deadline: float | None = None,
    comparison_budget: list[int] | None = None,
) -> dict[str, Any]:
    if deadline is None:
        deadline = time.perf_counter() + MAX_OMISSION_SECONDS
    if comparison_budget is None:
        comparison_budget = [0]
    table_boxes = {
        (
            cell["table_bbox"].x,
            cell["table_bbox"].y,
            cell["table_bbox"].width,
            cell["table_bbox"].height,
        )
        for cell in cells
        if isinstance(cell.get("table_bbox"), SourceBBox)
    }
    if len(table_boxes) != 1:
        _refuse("canonical OCR omission path table authority differs")
    table_tuple = next(iter(table_boxes))
    table_box = SourceBBox(
        x=table_tuple[0],
        y=table_tuple[1],
        width=table_tuple[2],
        height=table_tuple[3],
    )
    if pdfium_raw.FPDFPageObj_HasTransparency(obj.raw):
        _refuse("canonical OCR omission path transparency differs")
    if not _clip_is_empty(obj.raw):
        _refuse("canonical OCR omission path clip differs")
    matrix = _matrix_values(obj.get_matrix())
    segments = _path_segments(obj.raw, matrix)
    fill_mode = ctypes.c_int()
    stroke = ctypes.c_int()
    if not pdfium_raw.FPDFPath_GetDrawMode(
        obj.raw, ctypes.byref(fill_mode), ctypes.byref(stroke)
    ):
        _refuse("canonical OCR omission path paint differs")
    width = ctypes.c_float()
    if not pdfium_raw.FPDFPageObj_GetStrokeWidth(obj.raw, ctypes.byref(width)):
        _refuse("canonical OCR omission path width differs")
    stroke_width = float(width.value)
    if not math.isfinite(stroke_width) or stroke_width < 0:
        _refuse("canonical OCR omission path width differs")
    fill_rgba = _rgba(pdfium_raw.FPDFPageObj_GetFillColor, obj.raw)
    stroke_rgba = _rgba(pdfium_raw.FPDFPageObj_GetStrokeColor, obj.raw)
    dash_count = int(pdfium_raw.FPDFPageObj_GetDashCount(obj.raw))
    if dash_count < 0 or dash_count > MAX_OMISSION_DASH_VALUES:
        _refuse("canonical OCR omission dash differs")
    dash_values: tuple[float, ...] = ()
    dash_phase = 0.0
    if dash_count:
        raw_dash = (ctypes.c_float * dash_count)()
        raw_phase = ctypes.c_float()
        if (
            not pdfium_raw.FPDFPageObj_GetDashArray(
                obj.raw, raw_dash, dash_count
            )
            or not pdfium_raw.FPDFPageObj_GetDashPhase(
                obj.raw, ctypes.byref(raw_phase)
            )
        ):
            _refuse("canonical OCR omission dash differs")
        dash_values = tuple(float(value) for value in raw_dash)
        dash_phase = float(raw_phase.value)
        if (
            not all(
                math.isfinite(value) and 0.0 <= value <= 64.0
                for value in dash_values
            )
            or not any(value > 0 for value in dash_values)
            or not math.isfinite(dash_phase)
            or dash_phase < 0
            or dash_phase > 64.0
        ):
            _refuse("canonical OCR omission dash differs")

    if len(segments) == 5 and fill_mode.value in {1, 2} and stroke.value == 0:
        if (
            fill_rgba[3] != 255
            or dash_count
            or object_box.width <= 0
            or object_box.height <= 0
        ):
            _refuse("canonical OCR omission filled path differs")
        if [value[0] for value in segments] != [
            pdfium_raw.FPDF_SEGMENT_MOVETO,
            pdfium_raw.FPDF_SEGMENT_LINETO,
            pdfium_raw.FPDF_SEGMENT_LINETO,
            pdfium_raw.FPDF_SEGMENT_LINETO,
            pdfium_raw.FPDF_SEGMENT_LINETO,
        ] or not segments[-1][1] or any(value[1] for value in segments[:-1]):
            _refuse("canonical OCR omission filled path differs")
        points = [(value[2], value[3]) for value in segments]
        if points[0] != points[-1] or any(
            not (
                abs(first[0] - second[0]) <= 1e-6
                or abs(first[1] - second[1]) <= 1e-6
            )
            for first, second in zip(points, points[1:], strict=False)
        ):
            _refuse("canonical OCR omission filled path differs")
        owning, owning_box, insets, ownership_metrics = _filled_path_owner(
            object_box,
            cells,
            deadline=deadline,
            comparison_budget=comparison_budget,
        )
        expected_corners = (
            (object_box.x, page_height - object_box.y),
            (_box_right(object_box), page_height - object_box.y),
            (
                _box_right(object_box),
                page_height - _box_bottom(object_box),
            ),
            (object_box.x, page_height - _box_bottom(object_box)),
        )
        unique_points = points[:4]
        if len(
            {
                (round(point[0], 6), round(point[1], 6))
                for point in unique_points
            }
        ) != 4:
            _refuse("canonical OCR omission filled path corners differ")
        unmatched = list(expected_corners)
        for point in unique_points:
            matches = [
                index
                for index, corner in enumerate(unmatched)
                if abs(point[0] - corner[0]) <= _GEOMETRY_TOLERANCE
                and abs(point[1] - corner[1]) <= _GEOMETRY_TOLERANCE
            ]
            if len(matches) != 1:
                _refuse("canonical OCR omission filled path corners differ")
            unmatched.pop(matches[0])
        if unmatched:
            _refuse("canonical OCR omission filled path corners differ")
        return {
            "index": object_index,
            "kind": "cell_fill" if len(owning) == 1 else "cell_union_fill",
            "bbox": object_box.to_dict(),
            "cell_keys_sha256": _digest(
                [value["key_sha256"] for value in owning]
            ),
            "cell_span": [
                owning[0]["row_index"],
                owning[0]["column_index"],
                owning[-1]["column_index"],
            ],
            "row_source_text_sha256": owning[0].get(
                "row_source_text_sha256"
            ),
            "row_source_line_id": owning[0].get("row_source_line_id"),
            "row_source_character_ids_sha256": owning[0].get(
                "row_source_character_ids_sha256"
            ),
            "row_boxed_character_ids_sha256": owning[0].get(
                "row_boxed_character_ids_sha256"
            ),
            "row_source_character_indexes_sha256": owning[0].get(
                "row_source_character_indexes_sha256"
            ),
            "row_source_character_index_span": owning[0].get(
                "row_source_character_index_span"
            ),
            "fill_mode": fill_mode.value,
            "fill_rgba": list(fill_rgba),
            "cell_insets": [round(value, 6) for value in insets],
            "cell_area_ratio": round(
                object_box.width
                * object_box.height
                / (owning_box.width * owning_box.height),
                6,
            ),
            **ownership_metrics,
            "segments_sha256": _digest(segments),
        }

    if len(segments) != 2 or fill_mode.value != 0 or stroke.value != 1:
        _refuse("canonical OCR omission stroked path differs")
    line_cap = int(pdfium_raw.FPDFPageObj_GetLineCap(obj.raw))
    line_join = int(pdfium_raw.FPDFPageObj_GetLineJoin(obj.raw))
    if (
        stroke_rgba != (0, 0, 0, 255)
        or not 0 < stroke_width <= 0.70001
        or any(
            abs(observed - expected) > 1e-9
            for observed, expected in zip(
                matrix[:4], (1.0, 0.0, 0.0, 1.0), strict=True
            )
        )
        or line_cap != 0
        or line_join != 0
        or segments[0][0] != pdfium_raw.FPDF_SEGMENT_MOVETO
        or segments[1][0] != pdfium_raw.FPDF_SEGMENT_LINETO
        or segments[0][1]
        or segments[1][1]
    ):
        _refuse("canonical OCR omission grid path differs")
    first = (segments[0][2], segments[0][3])
    second = (segments[1][2], segments[1][3])
    x_boundaries, y_boundaries = _boundary_coordinates(
        cells,
        page_height=page_height,
        deadline=deadline,
        comparison_budget=comparison_budget,
    )
    # PDF table generators commonly place a stroke in the closed corridor
    # between two adjacent cell fill rectangles.  The authenticated cell grid
    # owns that corridor; no free-standing line is admitted.
    tolerance = _PATH_BOUNDARY_TOLERANCE
    horizontal = abs(first[1] - second[1]) <= 1e-6
    vertical = abs(first[0] - second[0]) <= 1e-6
    if math.hypot(first[0] - second[0], first[1] - second[1]) <= 1e-6:
        _refuse("canonical OCR omission grid path differs")
    if horizontal:
        expected_object_box = SourceBBox(
            x=min(first[0], second[0]) - stroke_width,
            y=page_height - first[1] - stroke_width,
            width=abs(first[0] - second[0]) + 2.0 * stroke_width,
            height=2.0 * stroke_width,
        )
    elif vertical:
        expected_object_box = SourceBBox(
            x=first[0] - stroke_width,
            y=page_height - max(first[1], second[1]) - stroke_width,
            width=2.0 * stroke_width,
            height=abs(first[1] - second[1]) + 2.0 * stroke_width,
        )
    else:
        _refuse("canonical OCR omission grid path differs")
    if any(
        abs(observed - expected) > _GEOMETRY_TOLERANCE
        for observed, expected in zip(
            (
                object_box.x,
                object_box.y,
                object_box.width,
                object_box.height,
            ),
            (
                expected_object_box.x,
                expected_object_box.y,
                expected_object_box.width,
                expected_object_box.height,
            ),
            strict=True,
        )
    ):
        _refuse("canonical OCR omission grid bounds differ")
    table_left = table_box.x
    table_right = _box_right(table_box)
    table_bottom = page_height - _box_bottom(table_box)
    table_top = page_height - table_box.y
    if horizontal:
        if not _near_any(
            first[1],
            y_boundaries,
            tolerance,
            deadline=deadline,
            comparison_budget=comparison_budget,
        ):
            _refuse("canonical OCR omission grid boundary differs")
        if not all(
            _near_any(
                value,
                x_boundaries,
                tolerance,
                deadline=deadline,
                comparison_budget=comparison_budget,
            )
            for value in (first[0], second[0])
        ):
            _refuse("canonical OCR omission grid endpoints differ")
        if (
            min(first[0], second[0]) < table_left - tolerance
            or max(first[0], second[0]) > table_right + tolerance
            or not table_bottom - tolerance <= first[1] <= table_top + tolerance
        ):
            _refuse("canonical OCR omission grid span differs")
        _charge_comparisons(comparison_budget, deadline, len(cells))
        owned_intervals = [
            (cell["bbox"].x, _box_right(cell["bbox"]))
            for cell in cells
            if isinstance(cell.get("bbox"), SourceBBox)
            and (
                abs(first[1] - (page_height - cell["bbox"].y)) <= tolerance
                or abs(
                    first[1] - (page_height - _box_bottom(cell["bbox"]))
                )
                <= tolerance
            )
        ]
        if not _interval_is_covered(
            first[0],
            second[0],
            owned_intervals,
            tolerance=tolerance,
            deadline=deadline,
            comparison_budget=comparison_budget,
        ):
            _refuse("canonical OCR omission grid ownership differs")
    elif vertical:
        if not _near_any(
            first[0],
            x_boundaries,
            tolerance,
            deadline=deadline,
            comparison_budget=comparison_budget,
        ):
            _refuse("canonical OCR omission grid boundary differs")
        if not all(
            _near_any(
                value,
                y_boundaries,
                tolerance,
                deadline=deadline,
                comparison_budget=comparison_budget,
            )
            for value in (first[1], second[1])
        ):
            _refuse("canonical OCR omission grid endpoints differ")
        if (
            not table_left - tolerance <= first[0] <= table_right + tolerance
            or min(first[1], second[1]) < table_bottom - tolerance
            or max(first[1], second[1]) > table_top + tolerance
        ):
            _refuse("canonical OCR omission grid span differs")
        _charge_comparisons(comparison_budget, deadline, len(cells))
        owned_intervals = [
            (
                page_height - _box_bottom(cell["bbox"]),
                page_height - cell["bbox"].y,
            )
            for cell in cells
            if isinstance(cell.get("bbox"), SourceBBox)
            and (
                abs(first[0] - cell["bbox"].x) <= tolerance
                or abs(first[0] - _box_right(cell["bbox"])) <= tolerance
            )
        ]
        if not _interval_is_covered(
            first[1],
            second[1],
            owned_intervals,
            tolerance=tolerance,
            deadline=deadline,
            comparison_budget=comparison_budget,
        ):
            _refuse("canonical OCR omission grid ownership differs")
    else:
        _refuse("canonical OCR omission grid path differs")
    return {
        "index": object_index,
        "kind": "grid_stroke",
        "bbox": object_box.to_dict(),
        "stroke_width": round(stroke_width, 6),
        "stroke_rgba": list(stroke_rgba),
        "line_cap": line_cap,
        "line_join": line_join,
        "matrix": [round(value, 6) for value in matrix],
        "dash": [round(value, 6) for value in dash_values],
        "dash_phase": round(dash_phase, 6),
        "segments_sha256": _digest(segments),
    }


def _text_manifest(
    obj: Any,
    *,
    object_index: int,
    object_box: SourceBBox,
    cells: Sequence[Mapping[str, Any]],
    deadline: float | None = None,
    comparison_budget: list[int] | None = None,
) -> dict[str, Any]:
    if deadline is None:
        deadline = time.perf_counter() + MAX_OMISSION_SECONDS
    if comparison_budget is None:
        comparison_budget = [0]
    if (
        pdfium_raw.FPDFPageObj_HasTransparency(obj.raw)
        or not _clip_is_empty(obj.raw)
        or int(pdfium_raw.FPDFTextObj_GetTextRenderMode(obj.raw))
        != pdfium_raw.FPDF_TEXTRENDERMODE_FILL
    ):
        _refuse("canonical OCR omission text paint differs")
    fill_rgba = _rgba(pdfium_raw.FPDFPageObj_GetFillColor, obj.raw)
    if fill_rgba[3] != 255:
        _refuse("canonical OCR omission text opacity differs")
    matrix = _matrix_values(obj.get_matrix())
    font = obj.get_font()
    if font is None:
        _refuse("canonical OCR omission text font differs")
    try:
        base_name = font.get_base_name()
        embedded = font.is_embedded
    finally:
        font.close()
    if type(base_name) is not str or base_name not in _STANDARD_FONTS or embedded:
        _refuse("canonical OCR omission text font differs")
    raw_text = obj.extract()
    if (
        type(raw_text) is not str
        or not _normalized(raw_text)
        or len(raw_text) > 4_096
        or len(raw_text.encode("utf-8")) > 16_384
    ):
        _refuse("canonical OCR omission text extraction differs")
    owning: list[Mapping[str, Any]] = []
    for cell in cells:
        _charge_comparisons(comparison_budget, deadline)
        if (
            cell.get("source_closed") is True
            and _contains(cell["bbox"], object_box, _GEOMETRY_TOLERANCE)
            and _substantive(raw_text) in _substantive(str(cell["text"]))
            and _substantive(raw_text)
            in _substantive(str(cell["source_text"]))
        ):
            owning.append(cell)
    if len(owning) != 1:
        _refuse("canonical OCR omission text ownership differs")
    return {
        "index": object_index,
        "kind": "text",
        "bbox": object_box.to_dict(),
        "cell_key_sha256": owning[0]["key_sha256"],
        "text_sha256": _digest(raw_text),
        "text": raw_text,
        "font": base_name,
        "fill_rgba": list(fill_rgba),
        "matrix": [round(value, 6) for value in matrix],
    }


def _text_object_source_proof(
    *,
    evidence: SourceTextEvidence,
    page_index: int,
    object_box: SourceBBox,
    object_text: str,
    cell: Mapping[str, Any],
    source_page: Any,
    source_characters_by_id: Mapping[str, Any],
    deadline: float,
    comparison_budget: list[int],
) -> dict[str, Any] | None:
    selection = text_for_bbox(
        evidence,
        page_index,
        object_box,
        deadline=deadline,
    )
    if (
        selection is None
        or not 1 <= len(selection.source_line_ids) <= 64
        or any(type(value) is not str or not value for value in selection.source_line_ids)
        or len(selection.source_line_ids) != len(set(selection.source_line_ids))
        or not selection.source_character_ids
        or len(selection.source_character_ids)
        != len(selection.source_character_indexes)
        or len(selection.source_character_ids)
        != len(set(selection.source_character_ids))
        or tuple(selection.source_character_indexes)
        != tuple(sorted(selection.source_character_indexes))
        or len(selection.source_character_indexes)
        != len(set(selection.source_character_indexes))
    ):
        return None
    if getattr(source_page, "page_index", None) != page_index:
        return None
    _charge_comparisons(
        comparison_budget,
        deadline,
        len(selection.source_character_ids),
    )
    characters = tuple(
        source_characters_by_id.get(value)
        for value in selection.source_character_ids
    )
    cell_box = cell.get("bbox")
    cell_ids = cell.get("source_character_ids")
    if (
        any(value is None for value in characters)
        or not isinstance(cell_box, SourceBBox)
        or type(cell_ids) is not tuple
        or tuple(
            value.character_index for value in characters if value is not None
        )
        != tuple(selection.source_character_indexes)
    ):
        return None
    for character in characters:
        assert character is not None
        if character.excluded_reason is not None:
            return None
        if character.bbox is None:
            if not character.text.isspace():
                return None
            continue
        if (
            not _center_inside(character.bbox, object_box)
            or not _center_inside(character.bbox, cell_box)
            or character.id not in cell_ids
        ):
            return None
    object_sequence = _substantive(object_text)
    source_sequence = _substantive(selection.text)
    canonical_sequence = _substantive(str(cell.get("text") or ""))
    cell_source_sequence = _substantive(str(cell.get("source_text") or ""))
    if (
        not object_sequence
        or object_sequence != source_sequence
        or canonical_sequence.count(object_sequence) != 1
        or cell_source_sequence.count(object_sequence) != 1
    ):
        return None
    return {
        "text_sha256": _digest(selection.text),
        "source_line_ids": list(selection.source_line_ids),
        "source_character_ids": list(selection.source_character_ids),
        "source_character_indexes": list(selection.source_character_indexes),
        "source_bbox": selection.bbox.to_dict(),
        "source_sequence_sha256": _digest(source_sequence),
    }


def _source_separator_manifest(
    *,
    contradiction_pairs: Sequence[tuple[str, int]],
    observed_pairs: Sequence[tuple[str, int]],
    source_characters_by_id: Mapping[str, Any],
) -> dict[str, Any] | None:
    contradiction = tuple(contradiction_pairs)
    observed = tuple(observed_pairs)
    if (
        not contradiction
        or not observed
        or len(contradiction) != len(set(contradiction))
        or len(observed) != len(set(observed))
        or tuple(value[1] for value in contradiction)
        != tuple(sorted(value[1] for value in contradiction))
        or tuple(value[1] for value in observed)
        != tuple(sorted(value[1] for value in observed))
        or len({value[0] for value in contradiction}) != len(contradiction)
        or len({value[1] for value in contradiction}) != len(contradiction)
        or len({value[0] for value in observed}) != len(observed)
        or len({value[1] for value in observed}) != len(observed)
    ):
        _refuse("canonical OCR omission source separator differs")
    observed_set = set(observed)
    if observed != tuple(value for value in contradiction if value in observed_set):
        _refuse("canonical OCR omission source separator differs")
    records: dict[tuple[str, int], Any] = {}
    for identifier, index in contradiction:
        character = source_characters_by_id.get(identifier)
        if (
            character is None
            or character.character_index != index
            or type(character.text) is not str
            or not character.text
            or character.excluded_reason is not None
        ):
            _refuse("canonical OCR omission source separator differs")
        records[(identifier, index)] = character
    if any(records[value].bbox is None for value in observed):
        _refuse("canonical OCR omission source separator differs")
    missing = tuple(value for value in contradiction if value not in observed_set)
    if not missing:
        return None
    observed_indexes = {value[1] for value in observed}
    missing_indexes = tuple(value[1] for value in missing)
    if any(
        records[value].bbox is not None or not records[value].text.isspace()
        for value in missing
    ):
        _refuse("canonical OCR omission source separator differs")
    # Every bboxless separator run is bracketed immediately by proved, visible
    # source glyphs. This admits an authentic inter-cell space without allowing
    # an unobserved prefix, suffix, or substantive glyph.
    run_start = missing_indexes[0]
    run_end = run_start
    for index in missing_indexes[1:]:
        if index == run_end + 1:
            run_end = index
            continue
        if run_start - 1 not in observed_indexes or run_end + 1 not in observed_indexes:
            _refuse("canonical OCR omission source separator differs")
        run_start = run_end = index
    if run_start - 1 not in observed_indexes or run_end + 1 not in observed_indexes:
        _refuse("canonical OCR omission source separator differs")
    if _substantive("".join(records[value].text for value in contradiction)) != _substantive(
        "".join(records[value].text for value in observed)
    ):
        _refuse("canonical OCR omission source separator differs")
    return {
        "kind": "source_whitespace_separators",
        "source_character_ids": [value[0] for value in missing],
        "source_character_indexes": [value[1] for value in missing],
        "text_sha256": _digest("".join(records[value].text for value in missing)),
    }


def _pdf_crop_manifests(
    source_pdf_bytes: bytes,
    candidates: Sequence[dict[str, Any]],
    cells_by_page: Mapping[int, Sequence[Mapping[str, Any]]],
    source_pages: Mapping[int, Any],
    evidence: SourceTextEvidence,
    *,
    deadline: float,
    comparison_budget: list[int] | None = None,
) -> dict[tuple[int, str], tuple[dict[str, Any], ...]]:
    if comparison_budget is None:
        comparison_budget = [0]
    if not isinstance(source_pdf_bytes, bytes) or not source_pdf_bytes:
        _refuse("canonical OCR omission PDF source is unavailable")
    _preflight_pdf_names(source_pdf_bytes, deadline=deadline)
    pages_needed = sorted({int(value["page_index"]) for value in candidates})
    if len(pages_needed) > MAX_OMISSION_PAGES:
        _refuse("canonical OCR omission page limit exceeded")
    result: dict[tuple[int, str], tuple[dict[str, Any], ...]] = {}
    total_objects = 0
    manifest_bytes = 0
    document = pdfium.PdfDocument(source_pdf_bytes)
    try:
        if (
            len(document) != len(source_pages)
            or int(pdfium_raw.FPDF_GetFormType(document.raw)) != 0
        ):
            _refuse("canonical OCR omission PDF document differs")
        for page_index in pages_needed:
            _check_deadline(deadline)
            source_page = source_pages.get(page_index)
            if source_page is None or page_index > len(document):
                _refuse("canonical OCR omission PDF page differs")
            page = document[page_index - 1]
            source_characters_by_id = {
                value.id: value for value in source_page.characters
            }
            text_page = None
            try:
                width, height = (float(value) for value in page.get_size())
                media = tuple(float(value) for value in page.get_mediabox())
                crop = tuple(float(value) for value in page.get_cropbox())
                if (
                    abs(width - source_page.page_width) > _GEOMETRY_TOLERANCE
                    or abs(height - source_page.page_height) > _GEOMETRY_TOLERANCE
                    or any(
                        abs(first - second) > _GEOMETRY_TOLERANCE
                        for first, second in zip(
                            media, (0.0, 0.0, width, height), strict=True
                        )
                    )
                    or any(
                        abs(first - second) > _GEOMETRY_TOLERANCE
                        for first, second in zip(
                            crop, (0.0, 0.0, width, height), strict=True
                        )
                    )
                    or int(pdfium_raw.FPDFPage_GetRotation(page.raw)) != 0
                    or int(pdfium_raw.FPDFPage_GetAnnotCount(page.raw)) != 0
                    or int(pdfium_raw.FPDFPage_HasTransparency(page.raw)) != 0
                ):
                    _refuse("canonical OCR omission PDF page state differs")
                text_page = page.get_textpage()
                page_candidates = [
                    value for value in candidates if value["page_index"] == page_index
                ]
                page_cells = tuple(cells_by_page.get(page_index, ()))
                if not page_cells:
                    _refuse("canonical OCR omission page cells are absent")
                manifests_by_owner: dict[str, list[dict[str, Any]]] = {
                    str(candidate["owner_id"]): []
                    for candidate in page_candidates
                }
                text_cells_by_owner: dict[str, dict[str, list[str]]] = {
                    str(candidate["owner_id"]): defaultdict(list)
                    for candidate in page_candidates
                }
                text_padding_by_owner: dict[str, dict[str, list[bool]]] = {
                    str(candidate["owner_id"]): defaultdict(list)
                    for candidate in page_candidates
                }
                text_claimed_source_ids: dict[str, set[str]] = {
                    str(candidate["owner_id"]): set()
                    for candidate in page_candidates
                }
                mandatory_source_pairs: dict[
                    str, list[tuple[str, int]]
                ] = {
                    str(candidate["owner_id"]): []
                    for candidate in page_candidates
                }
                mandatory_contributing_cells: dict[str, set[str]] = {
                    str(candidate["owner_id"]): set()
                    for candidate in page_candidates
                }
                candidate_cells: dict[str, tuple[Mapping[str, Any], ...]] = {}
                candidate_cells_by_key: dict[
                    str, dict[str, Mapping[str, Any]]
                ] = {}
                for candidate in page_candidates:
                    owner_id = str(candidate["owner_id"])
                    exact_cells = tuple(
                        cell
                        for cell in page_cells
                        if cell["table_id"] == candidate["table_id"]
                        and cell["representation_sha256"]
                        == candidate["representation_sha256"]
                    )
                    if not exact_cells:
                        _refuse("canonical OCR omission table cells are absent")
                    candidate_cells[owner_id] = exact_cells
                    candidate_cells_by_key[owner_id] = {
                        str(value["key_sha256"]): value for value in exact_cells
                    }
                for object_index, obj in enumerate(
                    page.get_objects(max_depth=8, textpage=text_page)
                ):
                    total_objects += 1
                    if total_objects > MAX_OMISSION_OBJECTS:
                        _refuse("canonical OCR omission object limit exceeded")
                    if total_objects % 128 == 0:
                        _check_deadline(deadline)
                    try:
                        object_box = _top_left_box(
                            obj.get_bounds(), page_height=height
                        )
                    except Exception as exc:
                        raise CanonicalOcrOmissionRefusal(
                            "canonical OCR omission object bounds differ"
                        ) from exc
                    for candidate in page_candidates:
                        owner_id = str(candidate["owner_id"])
                        crop_box = candidate["crop_bbox"]
                        _charge_comparisons(comparison_budget, deadline)
                        if not _touches_or_overlaps(crop_box, object_box):
                            continue
                        if (
                            not _object_is_active(obj.raw)
                            or int(pdfium_raw.FPDFPageObj_CountMarks(obj.raw)) != 0
                        ):
                            _refuse(
                                "canonical OCR omission object visibility differs"
                            )
                        object_type = int(pdfium_raw.FPDFPageObj_GetType(obj.raw))
                        exact_cells = candidate_cells[owner_id]
                        if object_type == pdfium_raw.FPDF_PAGEOBJ_TEXT:
                            manifest = _text_manifest(
                                obj,
                                object_index=object_index,
                                object_box=object_box,
                                cells=exact_cells,
                                deadline=deadline,
                                comparison_budget=comparison_budget,
                            )
                            text_cells_by_owner[owner_id][
                                str(manifest["cell_key_sha256"])
                            ].append(str(manifest["text"]))
                            cell_key = str(manifest["cell_key_sha256"])
                            cell = candidate_cells_by_key[owner_id].get(cell_key)
                            source_proof = (
                                _text_object_source_proof(
                                    evidence=evidence,
                                    page_index=page_index,
                                    object_box=object_box,
                                    object_text=str(manifest["text"]),
                                    cell=cell,
                                    source_page=source_page,
                                    source_characters_by_id=(
                                        source_characters_by_id
                                    ),
                                    deadline=deadline,
                                    comparison_budget=comparison_budget,
                                )
                                if cell is not None
                                else None
                            )
                            if source_proof is None:
                                _refuse(
                                    "canonical OCR omission text source proof differs"
                                )
                            proof_id_order = tuple(
                                source_proof["source_character_ids"]
                            )
                            proof_index_order = tuple(
                                source_proof["source_character_indexes"]
                            )
                            proof_ids = set(proof_id_order)
                            if proof_ids & text_claimed_source_ids[owner_id]:
                                _refuse(
                                    "canonical OCR omission text source ownership differs"
                                )
                            text_claimed_source_ids[owner_id].update(proof_ids)
                            mandatory_keys = set(candidate["owner_cell_keys"])
                            contradiction_ids = set(
                                candidate["source_contradiction"][
                                    "source_character_ids"
                                ]
                            )
                            owner_pairs = [
                                (identifier, index)
                                for identifier, index in zip(
                                    proof_id_order,
                                    proof_index_order,
                                    strict=True,
                                )
                                if identifier in contradiction_ids
                            ]
                            padding_only = cell_key not in mandatory_keys
                            if padding_only:
                                if (
                                    owner_pairs
                                    or _intersection_area(
                                        candidate["owner_bbox"], object_box
                                    )
                                    != 0.0
                                    or _center_inside(object_box, crop_box)
                                    or _center_inside(
                                        object_box, candidate["owner_bbox"]
                                    )
                                ):
                                    _refuse(
                                        "canonical OCR omission padding text differs"
                                    )
                            else:
                                mandatory_source_pairs[owner_id].extend(owner_pairs)
                                if owner_pairs:
                                    mandatory_contributing_cells[owner_id].add(
                                        cell_key
                                    )
                            manifest = {
                                **manifest,
                                "source_glyphs": source_proof,
                                "owner_source_character_ids": [
                                    value[0] for value in owner_pairs
                                ],
                                "padding_only": padding_only,
                            }
                            text_padding_by_owner[owner_id][cell_key].append(
                                padding_only
                            )
                        elif object_type == pdfium_raw.FPDF_PAGEOBJ_PATH:
                            manifest = _path_manifest(
                                obj,
                                object_index=object_index,
                                object_box=object_box,
                                cells=exact_cells,
                                page_height=height,
                                deadline=deadline,
                                comparison_budget=comparison_budget,
                            )
                        else:
                            _refuse(
                                "canonical OCR omission unsupported page object"
                            )
                        manifest_bytes += len(
                            json.dumps(
                                manifest,
                                allow_nan=False,
                                ensure_ascii=False,
                                separators=(",", ":"),
                                sort_keys=True,
                            ).encode("utf-8")
                        )
                        if manifest_bytes > MAX_REPORT_BYTES:
                            _refuse(
                                "canonical OCR omission object manifest limit exceeded"
                            )
                        manifests_by_owner[owner_id].append(manifest)
                for candidate in page_candidates:
                    owner_id = str(candidate["owner_id"])
                    manifests = manifests_by_owner[owner_id]
                    text_cells = text_cells_by_owner[owner_id]
                    text_padding = text_padding_by_owner[owner_id]
                    cells_by_key = {
                        str(cell["key_sha256"]): cell
                        for cell in candidate_cells[owner_id]
                    }
                    if not manifests or not text_cells:
                        _refuse("canonical OCR omission crop text closure differs")
                    for cell_key, fragments in text_cells.items():
                        cell = cells_by_key.get(cell_key)
                        if (
                            cell is None
                            or (
                                cell_key not in set(candidate["owner_cell_keys"])
                                and (
                                    not text_padding.get(cell_key)
                                    or not all(text_padding[cell_key])
                                )
                            )
                        ):
                            _refuse(
                                "canonical OCR omission crop text closure differs"
                            )
                    mandatory_keys = set(candidate["owner_cell_keys"])
                    contradiction_pairs = tuple(
                        zip(
                            candidate["source_contradiction"][
                                "source_character_ids"
                            ],
                            candidate["source_contradiction"][
                                "source_character_indexes"
                            ],
                            strict=True,
                        )
                    )
                    observed_pairs = tuple(
                        sorted(
                            mandatory_source_pairs[owner_id],
                            key=lambda value: value[1],
                        )
                    )
                    observed_pair_set = set(observed_pairs)
                    if observed_pairs != tuple(
                        value
                        for value in contradiction_pairs
                        if value in observed_pair_set
                    ) or mandatory_contributing_cells[owner_id] != mandatory_keys:
                        _refuse(
                            "canonical OCR omission mandatory text source differs"
                        )
                    separator_manifest = _source_separator_manifest(
                        contradiction_pairs=contradiction_pairs,
                        observed_pairs=observed_pairs,
                        source_characters_by_id=source_characters_by_id,
                    )
                    if separator_manifest is not None:
                        manifest_bytes += len(
                            json.dumps(
                                separator_manifest,
                                allow_nan=False,
                                ensure_ascii=False,
                                separators=(",", ":"),
                                sort_keys=True,
                            ).encode("utf-8")
                        )
                        if manifest_bytes > MAX_REPORT_BYTES:
                            _refuse(
                                "canonical OCR omission object manifest limit exceeded"
                            )
                        manifests.append(separator_manifest)
                    owner_cell_keys = candidate.get("owner_cell_keys")
                    if (
                        type(owner_cell_keys) is not tuple
                        or not owner_cell_keys
                        or len(owner_cell_keys) != len(set(owner_cell_keys))
                        or any(
                            type(value) is not str
                            or value not in text_cells
                            or value not in cells_by_key
                            or cells_by_key[value].get("source_closed") is not True
                            for value in owner_cell_keys
                        )
                    ):
                        _refuse(
                            "canonical OCR omission owner cell text closure differs"
                        )
                    result[(page_index, owner_id)] = tuple(manifests)
            finally:
                if text_page is not None:
                    text_page.close()
                page.close()
    finally:
        document.close()
    return result


def _build_candidates(
    pages: Sequence[Mapping[str, Any]],
    ir: DocumentIR,
    canonical: CanonicalPresentation,
    evidence: SourceTextEvidence,
    cells_by_page: Mapping[int, Sequence[Mapping[str, Any]]],
    *,
    deadline: float,
    comparison_budget: list[int],
    canonical_predecessor_explicit_null_paths: Sequence[
        Sequence[str | int]
    ] = (),
) -> list[dict[str, Any]]:
    pages_by_index, public_items = _page_and_owner_indexes(pages)
    reference_counts = _selected_vector_page_reference_counts(
        pages, deadline=deadline
    )
    source_characters_by_page = {
        page.page_index: {character.id: character for character in page.characters}
        for page in evidence.pages
    }
    candidates: list[dict[str, Any]] = []
    for (page_index, owner_id), (item_position, item) in public_items.items():
        _charge_comparisons(comparison_budget, deadline)
        _check_deadline(deadline)
        shape = _selected_vector_owner_shape(
            item,
            page_index=page_index,
            source_sha256=evidence.source_sha256,
        )
        if shape is None:
            continue
        owner_box, _promoted = shape
        contributor = item.get("ocr_contributor")
        if (
            type(contributor) is not dict
            or contributor.get("region_origin") != "pdf_page_render"
            or contributor.get("region_role") != "page_source"
            or reference_counts[owner_id] != 1
        ):
            continue
        page = pages_by_index[page_index]
        width = page.get("page_width")
        height = page.get("page_height")
        source_page = next(
            (value for value in evidence.pages if value.page_index == page_index),
            None,
        )
        if (
            source_page is None
            or type(width) not in {int, float}
            or type(height) not in {int, float}
            or abs(float(width) - source_page.page_width) > _GEOMETRY_TOLERANCE
            or abs(float(height) - source_page.page_height) > _GEOMETRY_TOLERANCE
        ):
            _refuse("canonical OCR omission page geometry differs")
        page_cells = tuple(cells_by_page.get(page_index, ()))
        _charge_comparisons(comparison_budget, deadline, len(page_cells))
        all_overlapping = [
            cell
            for cell in page_cells
            if isinstance(cell.get("bbox"), SourceBBox)
            and _overlaps(owner_box, cell["bbox"])
        ]
        if not all_overlapping:
            continue
        overlap_authorities = {
            (cell.get("table_id"), cell.get("representation_sha256"))
            for cell in all_overlapping
        }
        if len(overlap_authorities) != 1:
            continue
        overlapping = [
            cell for cell in all_overlapping if cell.get("source_closed") is True
        ]
        if not overlapping:
            continue
        _charge_comparisons(comparison_budget, deadline, len(overlapping))
        representation_ids = {cell["representation_sha256"] for cell in overlapping}
        table_ids = {cell["table_id"] for cell in overlapping}
        if len(representation_ids) != 1 or len(table_ids) != 1:
            continue
        owner_area = owner_box.width * owner_box.height
        coverage = sum(
            _intersection_area(owner_box, cell["bbox"])
            for cell in overlapping
        ) / owner_area
        union = _box_union([cell["bbox"] for cell in overlapping])
        _charge_comparisons(
            comparison_budget,
            deadline,
            len(overlapping) * max(0, len(overlapping) - 1) // 2,
        )
        if (
            coverage < 0.95
            or coverage > 1.000001
            or any(
                _intersection_area(first["bbox"], second["bbox"]) > 1e-9
                for index, first in enumerate(overlapping)
                for second in overlapping[index + 1 :]
            )
            or not _contains(union, owner_box, _GEOMETRY_TOLERANCE)
        ):
            continue
        table_id = next(iter(table_ids))
        representation_sha256 = next(iter(representation_ids))
        _charge_comparisons(comparison_budget, deadline, len(page_cells))
        exact_cells = tuple(
            cell
            for cell in page_cells
            if cell.get("table_id") == table_id
            and cell.get("representation_sha256") == representation_sha256
        )
        overlapping_cell_keys = tuple(
            cell["key_sha256"] for cell in overlapping
        )
        contradiction = _candidate_source_contradiction(
            evidence=evidence,
            page_index=page_index,
            owner_box=owner_box,
            owner_text=str(item.get("value") or ""),
            cells=page_cells,
            expected_owner_cell_keys=overlapping_cell_keys,
            expected_table_id=table_id,
            expected_representation_sha256=representation_sha256,
            deadline=deadline,
            comparison_budget=comparison_budget,
            source_characters_by_id=source_characters_by_page.get(page_index),
        )
        if contradiction is None:
            continue
        owner_cell_keys = tuple(contradiction["cell_keys"])
        _charge_comparisons(comparison_budget, deadline, len(exact_cells))
        owner_cells = tuple(
            cell for cell in exact_cells if cell["key_sha256"] in owner_cell_keys
        )
        if len(owner_cells) != len(owner_cell_keys):
            _refuse("canonical OCR omission source cell differs")
        element_id, block_id, block_sha256 = _candidate_ir_and_canonical_custody(
            ir=ir,
            canonical=canonical,
            page_index=page_index,
            item_position=item_position,
            item=item,
            owner_box=owner_box,
            deadline=deadline,
            comparison_budget=comparison_budget,
        )
        candidates.append(
            {
                "page_index": page_index,
                "owner_id": owner_id,
                "item_position": item_position,
                "owner": copy.deepcopy(dict(item)),
                "owner_bbox": owner_box,
                "crop_bbox": _crop_box(
                    owner_box,
                    width=float(width),
                    height=float(height),
                ),
                "element_id": element_id,
                "canonical_block_id": block_id,
                "canonical_block_sha256": block_sha256,
                "canonical_predecessor_explicit_null_paths": [
                    list(path)
                    for path in canonical_predecessor_explicit_null_paths
                ],
                "table_id": table_id,
                "representation_sha256": representation_sha256,
                "owner_cell_keys": owner_cell_keys,
                "owner_cell_source_sha256": _digest(
                    [
                        [cell["key_sha256"], cell["source_character_ids_sha256"]]
                        for cell in owner_cells
                    ]
                ),
                "source_contradiction": contradiction,
            }
        )
        if len(candidates) > MAX_OMISSION_CANDIDATES:
            _refuse("canonical OCR omission candidate limit exceeded")
    return candidates


def _selection(
    candidate: Mapping[str, Any],
    manifests: Sequence[Mapping[str, Any]],
    evidence: SourceTextEvidence,
) -> dict[str, Any]:
    owner = candidate["owner"]
    source_contradiction = candidate["source_contradiction"]
    pdf_manifests = [
        value
        for value in manifests
        if value.get("kind") != "source_whitespace_separators"
    ]
    separator_manifests = [
        value
        for value in manifests
        if value.get("kind") == "source_whitespace_separators"
    ]
    if (
        not pdf_manifests
        or len(pdf_manifests) + len(separator_manifests) != len(manifests)
        or len(separator_manifests) > 1
    ):
        _refuse("canonical OCR omission proof manifest differs")
    pdf_manifest_sha256 = _digest(pdf_manifests)
    separator_manifest_sha256 = _digest(separator_manifests)
    proof_manifest_sha256 = _digest(
        {
            "pdf_objects": pdf_manifests,
            "source_whitespace_separators": separator_manifests,
        }
    )
    explicit_null_paths = candidate.get(
        "canonical_predecessor_explicit_null_paths"
    )
    if type(explicit_null_paths) is not list:
        _refuse("canonical OCR omission null path differs")
    canonical_owner = {
        "policy_id": SOURCE_CONTRADICTED_PRIMARY_OCR_POLICY_ID,
        "suppression_reason": SOURCE_CONTRADICTED_PRIMARY_OCR_REASON,
        "source_sha256": evidence.source_sha256,
        "page_index": candidate["page_index"],
        "owner_item_position": candidate["item_position"],
        "owner_bbox": candidate["owner_bbox"].to_dict(),
        "crop_bbox": candidate["crop_bbox"].to_dict(),
        "crop_padding_points": PDF_RENDER_CROP_PADDING_POINTS,
        "public_table_id": candidate["table_id"],
        "terminal_authority_sha256": candidate["representation_sha256"],
        "owner_cell_keys": list(candidate["owner_cell_keys"]),
        "owner_cell_source_sha256": candidate["owner_cell_source_sha256"],
        "source_contradiction": copy.deepcopy(source_contradiction),
        "ir_element_id": candidate["element_id"],
        "canonical_block_id": candidate["canonical_block_id"],
        "canonical_predecessor_sha256": candidate["canonical_block_sha256"],
        "canonical_predecessor_explicit_null_paths": copy.deepcopy(
            explicit_null_paths
        ),
        "canonical_predecessor_explicit_null_paths_sha256": _digest(
            explicit_null_paths
        ),
        "pdf_object_count": len(pdf_manifests),
        "pdf_object_manifest_sha256": pdf_manifest_sha256,
        "source_separator_count": len(separator_manifests),
        "source_separator_manifest_sha256": separator_manifest_sha256,
        "canonical_omission_proof_sha256": proof_manifest_sha256,
    }
    identifier = "alignment-" + _digest(
        [
            SOURCE_CONTRADICTED_PRIMARY_OCR_POLICY_ID,
            evidence.source_sha256,
            candidate["page_index"],
            owner["id"],
            proof_manifest_sha256,
        ]
    )[:24]
    return {
        "id": identifier,
        "page_index": candidate["page_index"],
        "owner_id": owner["id"],
        "owner_type": owner["type"],
        "owner_bbox": candidate["owner_bbox"].to_dict(),
        "original_text": owner["value"],
        "selected_text": "",
        "selected_source": "source_owned_vector_table_render",
        "source_line_ids": copy.deepcopy(
            source_contradiction["source_line_ids"]
        ),
        "source_character_ids": copy.deepcopy(
            source_contradiction["source_character_ids"]
        ),
        "type1_mapping_ids": copy.deepcopy(
            source_contradiction["type1_mapping_ids"]
        ),
        "source_roles": copy.deepcopy(source_contradiction["source_roles"]),
        "method": "source_safe_canonical_ocr_omission",
        "checks": {
            "public_owner_retained": True,
            "selected_vector_candidate_bound": True,
            "source_cell_text_closed": True,
            "source_contradiction_closed": True,
            "pdf_page_object_inventory_closed": True,
            "canonical_primary_owner_closed": True,
        },
        "terminal_reason": SOURCE_CONTRADICTED_PRIMARY_OCR_REASON,
        "rejected_ocr_alternative": {
            "text": owner["value"],
            "source": "ocr",
            "bbox": candidate["owner_bbox"].to_dict(),
            "confidence": owner["confidence"],
            "reason": SOURCE_CONTRADICTED_PRIMARY_OCR_REASON,
            "ocr_contributor": copy.deepcopy(owner["ocr_contributor"]),
            "owner_snapshot": copy.deepcopy(owner),
            "canonical_owner": canonical_owner,
        },
    }


def _append_omission_selections(
    summary: Mapping[str, Any],
    selections: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    candidate = dict(summary)
    existing = candidate.get("selections")
    concerns = candidate.get("concerns")
    if type(existing) is not list or type(concerns) is not list:
        _refuse("canonical OCR omission summary differs")
    existing = list(existing)
    candidate["selections"] = existing
    if any(
        type(value) is not dict
        or value.get("terminal_reason") == SOURCE_CONTRADICTED_PRIMARY_OCR_REASON
        for value in existing
    ):
        _refuse("canonical OCR omission summary differs")
    existing_ids = [value.get("id") for value in existing]
    existing_owners = [value.get("owner_id") for value in existing]
    new_ids = [value.get("id") for value in selections]
    new_owners = [value.get("owner_id") for value in selections]
    concern_owners = {
        value.get("owner_id")
        for value in concerns
        if isinstance(value, Mapping) and value.get("owner_id") is not None
    }
    if (
        not selections
        or len(existing) + len(selections) > MAX_TOTAL_ALIGNMENT_SELECTIONS
        or any(type(value) is not str or not value for value in existing_ids)
        or any(type(value) is not str or not value for value in new_ids)
        or any(type(value) is not str or not value for value in new_owners)
        or len(existing_ids) != len(set(existing_ids))
        or len(new_ids) != len(set(new_ids))
        or len(new_owners) != len(set(new_owners))
        or set(existing_ids) & set(new_ids)
        or set(existing_owners) & set(new_owners)
        or set(new_owners) & concern_owners
    ):
        _refuse("canonical OCR omission summary identity differs")
    counts: dict[str, int] = {}
    for key in (
        "considered_count",
        "selected_count",
        "unchanged_count",
        "unresolved_count",
    ):
        value = candidate.get(key)
        if type(value) is not int or value < 0:
            _refuse("canonical OCR omission summary differs")
        counts[key] = value
    if (
        counts["considered_count"]
        != counts["selected_count"]
        + counts["unchanged_count"]
        + counts["unresolved_count"]
        or counts["unchanged_count"] < len(selections)
    ):
        _refuse("canonical OCR omission summary count differs")
    existing.extend(copy.deepcopy(list(selections)))
    candidate["selected_count"] = counts["selected_count"] + len(selections)
    candidate["unchanged_count"] = counts["unchanged_count"] - len(selections)
    candidate["status"] = "selected"
    return candidate


def _apply_transaction(
    payload: Mapping[str, Any],
    ir: DocumentIR,
    summary: Mapping[str, Any],
    evidence: SourceTextEvidence,
    representations: Mapping[int, Sequence[Mapping[str, Any]]],
    source_pdf_bytes: bytes,
    *,
    started: float,
    deadline: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if (
        len(source_pdf_bytes) > MAX_INPUT_BYTES
        or evidence.source_sha256 != ir.source_sha256
        or not evidence.usable
    ):
        _refuse("canonical OCR omission source identity differs")
    if sum(
        len(value)
        for value in (
            ir.coordinate_systems,
            ir.bboxes,
            ir.pages,
            ir.regions,
            ir.elements,
            ir.evidence,
            ir.text_rules,
            ir.text_runs,
            ir.relationships,
            ir.concerns,
        )
    ) > MAX_OMISSION_IR_RECORDS:
        _refuse("canonical OCR omission IR record limit exceeded")
    _check_deadline(deadline)
    if hashlib.sha256(source_pdf_bytes).hexdigest() != evidence.source_sha256:
        _refuse("canonical OCR omission PDF identity differs")
    _check_deadline(deadline)
    raw_pages = payload.get("pages")
    raw_canonical = payload.get("canonical_presentation")
    if type(raw_pages) is not list or raw_canonical is None:
        _refuse("canonical OCR omission terminal payload differs")
    raw_processing = payload.get("processing")
    if (
        not isinstance(raw_processing, Mapping)
        or raw_processing.get("source_text_alignment") != summary
    ):
        _refuse("canonical OCR omission processing state differs")
    _pages_by_index, preflight_items = _page_and_owner_indexes(raw_pages)
    candidate_page_indexes: set[int] = set()
    for (page_index, _owner_id), (_position, item) in preflight_items.items():
        shape = _selected_vector_owner_shape(
            item,
            page_index=page_index,
            source_sha256=evidence.source_sha256,
        )
        contributor = item.get("ocr_contributor")
        if (
            shape is not None
            and type(contributor) is dict
            and contributor.get("region_origin") == "pdf_page_render"
            and contributor.get("region_role") == "page_source"
        ):
            candidate_page_indexes.add(page_index)
    if not candidate_page_indexes:
        _refuse("canonical OCR omission has no candidate owners")
    if not isinstance(raw_canonical, Mapping):
        _refuse("canonical OCR omission predecessor presentation differs")
    try:
        parsed_canonical = CanonicalPresentation.model_validate(
            copy.deepcopy(dict(raw_canonical)), strict=True
        )
    except Exception as exc:
        raise CanonicalOcrOmissionRefusal(
            "canonical OCR omission predecessor presentation differs"
        ) from exc
    comparison_budget = [0]
    canonical = build_canonical_presentation(ir)
    if parsed_canonical.model_dump(
        mode="json", exclude_none=True
    ) != canonical.model_dump(mode="json", exclude_none=True):
        _refuse("canonical OCR omission predecessor presentation differs")
    explicit_null_paths = _canonical_explicit_null_paths(
        raw_canonical, canonical
    )
    _admitted, cells_by_page = _source_cells(
        raw_pages,
        evidence,
        representations,
        candidate_page_indexes=candidate_page_indexes,
        deadline=deadline,
        comparison_budget=comparison_budget,
    )
    candidates = _build_candidates(
        raw_pages,
        ir,
        canonical,
        evidence,
        cells_by_page,
        deadline=deadline,
        comparison_budget=comparison_budget,
        canonical_predecessor_explicit_null_paths=explicit_null_paths,
    )
    if not candidates:
        _refuse("canonical OCR omission has no candidates")
    source_pages = {page.page_index: page for page in evidence.pages}
    manifests = _pdf_crop_manifests(
        source_pdf_bytes,
        candidates,
        cells_by_page,
        source_pages,
        evidence,
        deadline=deadline,
        comparison_budget=comparison_budget,
    )
    selections = [
        _selection(
            candidate,
            manifests[(candidate["page_index"], candidate["owner_id"])],
            evidence,
        )
        for candidate in candidates
    ]
    if len(selections) != len({value["owner_id"] for value in selections}):
        _refuse("canonical OCR omission selection repeats")
    omitted = omit_source_contradicted_primary_ocr(
        canonical,
        [candidate["element_id"] for candidate in candidates],
    )
    candidate_payload = dict(payload)
    omitted_compact = omitted.model_dump(mode="json", exclude_none=True)
    restored_omitted = _restore_explicit_null_paths(
        omitted_compact,
        omitted,
        explicit_null_paths,
    )
    if CanonicalPresentation.model_validate(
        restored_omitted, strict=True
    ).model_dump(mode="json", exclude_none=True) != omitted_compact:
        _refuse("canonical OCR omission restored presentation differs")
    candidate_payload["canonical_presentation"] = restored_omitted
    candidate_summary = _append_omission_selections(summary, selections)
    elapsed = candidate_summary.get("elapsed_ms")
    if type(elapsed) not in {int, float} or not math.isfinite(float(elapsed)):
        _refuse("canonical OCR omission summary differs")
    candidate_summary["elapsed_ms"] = round(
        float(elapsed) + max(0.0, (time.perf_counter() - started) * 1000),
        3,
    )
    if len(
        json.dumps(
            candidate_summary,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ) > MAX_REPORT_BYTES:
        _refuse("canonical OCR omission report limit exceeded")
    from app.services.pipeline import _validate_source_alignment_summary

    policy_id = candidate_summary.get("policy_id")
    if type(policy_id) is not str or not policy_id:
        _refuse("canonical OCR omission summary policy differs")
    _validate_source_alignment_summary(
        candidate_summary,
        policy_id=policy_id,
        source_sha256=evidence.source_sha256,
    )
    candidate_processing = dict(raw_processing)
    candidate_processing["source_text_alignment"] = candidate_summary
    candidate_payload["processing"] = candidate_processing
    _check_deadline(deadline)
    return candidate_payload, candidate_summary


def apply_source_contradicted_primary_ocr_omissions(
    payload: Mapping[str, Any],
    ir: DocumentIR,
    summary: Mapping[str, Any],
    evidence: SourceTextEvidence,
    representations: Mapping[int, Sequence[Mapping[str, Any]]] | None,
    source_pdf_bytes: bytes | None,
    *,
    timeout_seconds: float = MAX_OMISSION_SECONDS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return an omitted candidate or the byte-equivalent predecessor state."""

    try:
        if type(payload) is not dict or type(summary) is not dict:
            _refuse("canonical OCR omission predecessor differs")
        if (
            not representations
            or not isinstance(source_pdf_bytes, bytes)
            or not source_pdf_bytes
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
            or timeout_seconds > MAX_OMISSION_SECONDS
        ):
            return payload, summary
        started = time.perf_counter()
        return _apply_transaction(
            payload,
            ir,
            summary,
            evidence,
            representations,
            source_pdf_bytes,
            started=started,
            deadline=started + timeout_seconds,
        )
    except Exception:
        # This optional canonical-only lane is deliberately isolated from the
        # already committed source-alignment transaction.
        return payload, summary  # type: ignore[return-value]


def _canonical_omission_primary_ids(
    raw_canonical: Any,
) -> tuple[str, ...]:
    if not isinstance(raw_canonical, Mapping):
        _refuse("canonical OCR omission presentation differs")
    raw_pages = raw_canonical.get("pages")
    if type(raw_pages) is not list:
        _refuse("canonical OCR omission presentation differs")
    result: list[str] = []
    for page in raw_pages:
        blocks = page.get("blocks") if isinstance(page, Mapping) else None
        if type(blocks) is not list:
            _refuse("canonical OCR omission presentation differs")
        for block in blocks:
            if not isinstance(block, Mapping):
                _refuse("canonical OCR omission presentation differs")
            if block.get("omission_reason") != SOURCE_CONTRADICTED_PRIMARY_OCR_REASON:
                continue
            primary_id = block.get("primary_element_id")
            if type(primary_id) is not str or not primary_id:
                _refuse("canonical OCR omission presentation differs")
            result.append(primary_id)
    if len(result) != len(set(result)):
        _refuse("canonical OCR omission presentation differs")
    return tuple(result)


def validate_source_contradicted_primary_ocr_omissions(
    payload: Mapping[str, Any],
    ir: DocumentIR,
    summary: Mapping[str, Any],
    evidence: SourceTextEvidence,
    representations: Mapping[int, Sequence[Mapping[str, Any]]] | None,
    source_pdf_bytes: bytes | None,
) -> bool:
    """Independently replay the canonical-only transaction from terminal IR."""

    try:
        if type(payload) is not dict or type(summary) is not dict:
            return False
        raw_processing = payload.get("processing")
        if (
            not isinstance(raw_processing, Mapping)
            or raw_processing.get("source_text_alignment") != summary
        ):
            return False
        selections = summary.get("selections")
        if type(selections) is not list:
            return False
        raw_canonical = payload.get("canonical_presentation")
        if not isinstance(raw_canonical, Mapping):
            return False
        parsed_observed_canonical = CanonicalPresentation.model_validate(
            copy.deepcopy(dict(raw_canonical)), strict=True
        )
        observed_null_paths = _canonical_explicit_null_paths(
            raw_canonical, parsed_observed_canonical
        )
        omission_selections = [
            value
            for value in selections
            if type(value) is dict
            and value.get("terminal_reason")
            == SOURCE_CONTRADICTED_PRIMARY_OCR_REASON
        ]
        omitted_primary_ids = _canonical_omission_primary_ids(
            raw_canonical
        )
        selected_primary_ids: list[str] = []
        selected_null_paths: tuple[tuple[str | int, ...], ...] | None = None
        for selection in omission_selections:
            rejected = selection.get("rejected_ocr_alternative")
            canonical_owner = (
                rejected.get("canonical_owner")
                if isinstance(rejected, Mapping)
                else None
            )
            element_id = (
                canonical_owner.get("ir_element_id")
                if isinstance(canonical_owner, Mapping)
                else None
            )
            if type(element_id) is not str or not element_id:
                return False
            raw_null_paths = canonical_owner.get(
                "canonical_predecessor_explicit_null_paths"
            )
            raw_null_paths_sha256 = canonical_owner.get(
                "canonical_predecessor_explicit_null_paths_sha256"
            )
            if (
                type(raw_null_paths) is not list
                or raw_null_paths_sha256 != _digest(raw_null_paths)
            ):
                return False
            normalized_null_paths = tuple(
                tuple(path) if type(path) is list else ()
                for path in raw_null_paths
            )
            if (
                any(not path for path in normalized_null_paths)
                or (
                    selected_null_paths is not None
                    and normalized_null_paths != selected_null_paths
                )
            ):
                return False
            selected_null_paths = normalized_null_paths
            selected_primary_ids.append(element_id)
        if omitted_primary_ids != tuple(selected_primary_ids):
            return False
        if not omission_selections:
            return parsed_observed_canonical.model_dump(
                mode="json", exclude_none=True
            ) == build_canonical_presentation(ir).model_dump(
                mode="json", exclude_none=True
            )
        if selected_null_paths != observed_null_paths:
            return False
        baseline_summary = dict(summary)
        baseline_summary["selections"] = [
            value
            for value in selections
            if value not in omission_selections
        ]
        selected_count = baseline_summary.get("selected_count")
        unchanged_count = baseline_summary.get("unchanged_count")
        if (
            type(selected_count) is not int
            or selected_count < len(omission_selections)
            or type(unchanged_count) is not int
            or unchanged_count < 0
        ):
            return False
        baseline_summary["selected_count"] = selected_count - len(
            omission_selections
        )
        baseline_summary["unchanged_count"] = unchanged_count + len(
            omission_selections
        )
        if baseline_summary["selected_count"] == 0:
            baseline_summary["status"] = "unchanged"
        baseline_payload = dict(payload)
        baseline_canonical = build_canonical_presentation(ir)
        baseline_payload["canonical_presentation"] = _restore_explicit_null_paths(
            baseline_canonical.model_dump(mode="json", exclude_none=True),
            baseline_canonical,
            selected_null_paths,
        )
        baseline_processing = dict(raw_processing)
        baseline_processing["source_text_alignment"] = baseline_summary
        baseline_payload["processing"] = baseline_processing
        rebuilt_payload, rebuilt_summary = (
            apply_source_contradicted_primary_ocr_omissions(
                baseline_payload,
                ir,
                baseline_summary,
                evidence,
                representations,
                source_pdf_bytes,
            )
        )
        # Elapsed wall time is intentionally observational.  Every semantic
        # field, including exact ordered selection records, must replay.
        observed_summary = dict(summary)
        observed_summary["elapsed_ms"] = rebuilt_summary.get("elapsed_ms")
        observed_processing = dict(raw_processing)
        observed_processing["source_text_alignment"] = observed_summary
        observed_payload = dict(payload)
        observed_payload["processing"] = observed_processing
        return (
            rebuilt_summary == observed_summary
            and rebuilt_payload == observed_payload
        )
    except Exception:
        return False
